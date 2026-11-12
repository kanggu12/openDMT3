"""Many players, cabinets and admins on one server at once: the game server and the site on one event loop as the
server runs them (python -m opendmt3.server), stand-in cabinets on the game's port and visitors and programs on the
site at the same time.

- Thread safety: cabinets and the site's worker threads at once, and threads on the shared tables, leave every answer
  right (every result kept, the first places and the kept lists the database's own).
- Concurrency: one card on two cabinets at once, two cabinets with the same chart in the same second, plays going on
  through a backup, a restore and a song list's swap, and a database held by another connection, which no player
  ever hears of.
- Failure isolation: a bad cabinet (garbage, a link it never reads, a link cut half way) never slows the others, and
  a request that fails answers alone.
- Fairness: a caller asking over and over gets its share (requests at once, processor time a minute) and no more.

They need the web libraries (Starlette, Jinja2, httpx); without them they are skipped.
"""

import asyncio
import json
import logging
import os
import random
import shutil
import sqlite3
import struct
import tempfile
import threading
import time
import unittest
from unittest import mock

from opendmt3.server import crypto, db, messages
from opendmt3.server.server import GameServer
from opendmt3.server.services import accounts, activity, records
from tests.server.test_firsts import WINDOW
from tests.server.test_server import StandInClient
from tests.server.test_web import WEB

# How many players the made-up server has (cabinets and visitors each take their own).
PLAYERS = 40
# The charts the stand-in results land on: few, so cabinets meet on the same ones.
CHARTS = [(song, pattern) for song in (1, 2, 3) for pattern in (1, 2)]
# The results one stand-in cabinet sends while it keeps playing (Together.playing), at most: 250 of 155 bytes, a login
# of 28 after each fifth and the link's own 1,024 are 41 KB, under the 64 KiB an address may send the game's port in a
# minute (connection.BYTES_PER_MINUTE) however long the run takes.
PLAYS_MOST = 250


def results(user, stages, mode=0):
    """A 0x6E like the game's: user, mode, cleared, then a 47-byte record per stage (song, pattern, score)."""
    msg = bytearray(155)
    msg[0] = 0x6E
    struct.pack_into("<IBB", msg, 8, user, mode, 1)
    for i, (song, pattern, score) in enumerate(stages):
        at = 14 + 47 * i
        struct.pack_into("<IB", msg, at, song, pattern)
        struct.pack_into("<I", msg, at + 7, score)
    return bytes(msg)


class Cabinet:
    """A stand-in cabinet with a reader of its own: keep-alive answers timed, a login's answer gathered whole."""

    def __init__(self, port, row, address="127.0.0.1", said=None):
        self.port, self.row, self.address = port, row, address
        # What the game server said from a warning up (Together keeps it): told with a link the server closed.
        self.said = said if said is not None else []
        self.answers = []           # seconds each keep-alive took to be answered
        self.sent_at = None
        self.login = None           # the messages of the login being answered
        self.logged_in = asyncio.Event()
        self.firsts_seen = asyncio.Event()

    async def open(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port, local_addr=(self.address, 0))
        self.client = StandInClient(reader, writer)
        result = await self.client.handshake()
        assert result[8] == 1, "handshake refused"
        self.reading = asyncio.ensure_future(self.read_loop())
        return self

    async def read_loop(self):
        try:
            while True:
                head = await self.client.reader.readexactly(8)
                kind = crypto.decrypt(head, self.client.to_client)[0]
                size = messages.TO_CLIENT[kind]
                rest = await self.client.reader.readexactly(size - 8) if size > 8 else b""
                msg = crypto.decrypt(head + rest, self.client.to_client)
                self.client.to_client = crypto.next_server_state(self.client.to_client)
                if kind == 0x0B and self.sent_at is not None:
                    self.answers.append(time.monotonic() - self.sent_at)
                    self.sent_at = None
                elif kind == 0x06:
                    pong = bytearray(8)
                    pong[0] = 0x07
                    self.client.write(bytes(pong))
                elif self.login is not None:
                    self.login.append(msg)
                    if kind == 0x64:
                        self.logged_in.set()
                    if kind == 0x66:
                        # The first places follow their clear in the same burst; the burst ends when the reader would
                        # wait (checked by those who need it whole).
                        self.firsts_seen.set()
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.CancelledError):
            pass

    def keep_alive(self):
        if self.sent_at is None:
            msg = bytearray(8)
            msg[0] = 0x0A
            self.sent_at = time.monotonic()
            self.client.write(bytes(msg))

    async def card(self, card=None):
        """A card login; returns once the result (0x64) has come, with what came of the answer so far."""
        msg = bytearray(28)
        msg[0] = 0x60
        number = card or self.row["card"]
        msg[8:8 + len(number)] = number.encode()
        self.login, self.logged_in = [], asyncio.Event()
        self.firsts_seen = asyncio.Event()
        self.client.write(bytes(msg))
        await self.sent()
        await asyncio.wait_for(self.logged_in.wait(), 20)
        result = [m for m in self.login if m[0] == 0x64][0]
        return result[8] == messages.AUTH_OK

    async def send_results(self, stages, mode=0):
        self.client.write(results(self.row["id"], stages, mode))
        await self.sent()

    async def sent(self):
        """Wait for what was written to go out. A link the server closed meanwhile is said with the server's own last
        words (a refusal names its reason there: "Connection lost" alone sent a search for a race through sixteen
        runs, where the server had said the address sent more than it may in a minute)."""
        try:
            await self.client.writer.drain()
        except ConnectionError as e:
            raise type(e)("%s: the server closed the link of the cabinet at %s; the server said: %s" % (
                e, self.address, "; ".join(self.said[-3:]) or "nothing")) from None

    async def close(self):
        self.reading.cancel()
        self.client.writer.close()


class Together(unittest.IsolatedAsyncioTestCase):
    """A server with its database, the game server and the site on this test's loop, as __main__ runs them."""

    async def asyncSetUp(self):
        if os.name == "nt":
            # On Windows the loop as __main__ runs it, without the debug mode IsolatedAsyncioTestCase turns on: that
            # mode captures a stack at every callback it schedules, each capture stats every source file linecache
            # holds whole (90,000 stats in one test here), and a stat on Windows opens and closes the file (3.5 ms
            # under Wine, against 6 us on Linux beside it), which the time limits would measure instead of the
            # server. Linux keeps the mode and its checks of the loop's threads.
            asyncio.get_running_loop().set_debug(False)
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "openDMT3.sqlite")
        self.db = db.connect(self.path)
        store = accounts.Accounts(self.db)
        self.boss = store.create("BOSS", "pass1234", "DJ BOSS", is_admin=True)
        # The players share one hash (made once) and get cards of their own: made in milliseconds.
        secret = self.boss["password"]
        for n in range(PLAYERS):
            self.db.execute("INSERT INTO accounts (login_id, password, dj_name, card, created_at) VALUES (?, ?, ?, ?, ?)",
                            ("P%02d" % n, secret, "DJ %02d" % n, "%020d" % (n + 1), 0))
        self.players = self.db.execute("SELECT * FROM accounts WHERE login_id LIKE 'P%' ORDER BY id").fetchall()
        with open(os.path.join(self.tmp, "catalog.json"), "w") as f:
            json.dump({"songs": [{"number": n, "title": "Song %d" % n} for n in (1, 2, 3)]}, f)
        self.server = await GameServer("127.0.0.1", 0, rng=random.Random(5), accounts=accounts.Accounts(self.db),
                                       records=records.Records(self.db), activity=activity.Activity(self.db),
                                       data=self.tmp).start()
        # What the game server says from a warning up is kept for a failure's line (Cabinet.sent) and, below an error,
        # off the screen: the tests make it refuse on purpose.
        self.server_said = []
        said = self.server_said

        class Kept(logging.Filter):
            def filter(self, record):
                said.append(record.getMessage())
                return record.levelno >= logging.ERROR
        kept, logger = Kept(), logging.getLogger("opendmt3.server")
        logger.setLevel(logging.WARNING)
        logger.addFilter(kept)
        self.addCleanup(logger.setLevel, logging.NOTSET)
        self.addCleanup(logger.removeFilter, kept)
        self.cabinets = []

    async def asyncTearDown(self):
        for cab in self.cabinets:
            await cab.close()
        await self.server.close()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def cabinet(self, row, address="127.0.0.1"):
        cab = await Cabinet(self.server.port, row, address, self.server_said).open()
        self.cabinets.append(cab)
        return cab

    async def players_cabinets(self, count):
        """A cabinet for each of the first `count` players, each at an address of its own (127.0.0.2 and on), logged
        in. One address may send the game's port 64 KiB a minute over all its links, which a real cabinet (a few
        hundred bytes a minute) never comes near; four stand-in cabinets sending results every 10 ms from one address
        passed it when a run took long (66 KB counted, then every link of the address closed: "Connection lost" in 7
        runs of 96 beside seven other processes)."""
        cabs = [await self.cabinet(row, "127.0.0.%d" % (2 + k)) for k, row in enumerate(self.players[:count])]
        await asyncio.gather(*[cab.card() for cab in cabs])
        return cabs

    def playing(self, cabs, stop, sent):
        """Every cabinet sending a credit's results every 10 ms, as many cabinets at once would send them (far faster
        than a real one), and logging in again after each fifth, until `stop` is set; sent[0] counts the results.
        PLAYS_MOST results a cabinet at most, so its address never passes what it may send, however long the run
        takes. Returns the cabinets' tasks, for the caller to wait for once it has set `stop`."""
        async def keep_playing(cab, k):
            n = 0
            while not stop.is_set() and n < PLAYS_MOST:
                n += 1
                await cab.send_results([(CHARTS[(k + n) % 6][0], CHARTS[(k + n) % 6][1], 1000 + n)])
                sent[0] += 1
                await asyncio.sleep(0.01)
                if n % 5 == 0:
                    await cab.card()
        return [asyncio.ensure_future(keep_playing(cab, k)) for k, cab in enumerate(cabs)]

    def window(self):
        """Each chart's first place as the window function the game server used to run gives it."""
        reader = sqlite3.connect(self.path)
        try:
            return [tuple(r) for r in reader.execute(WINDOW)]
        finally:
            reader.close()

    def table(self):
        """The first places the game server keeps, in the window's shape."""
        return [(p.mode, p.song, p.pattern, p.score, p.dj_name) for p in self.server.firsts.places()]

    async def until(self, check, seconds=10, why="a condition"):
        """Wait (on the loop) until check() is true."""
        deadline = time.monotonic() + seconds
        while not check():
            if time.monotonic() > deadline:
                self.fail("never came: %s" % why)
            await asyncio.sleep(0.02)

    def plays(self):
        reader = sqlite3.connect(self.path)
        try:
            return reader.execute("SELECT COUNT(*) FROM plays").fetchone()[0]
        finally:
            reader.close()


class ConcurrencyTest(Together):

    async def test_one_card_on_two_cabinets_at_once(self):
        player = self.players[0]
        one, two = await self.cabinet(player), await self.cabinet(player)
        # The same card at the same moment on both: both log in, each with a session of its own.
        oks = await asyncio.gather(one.card(), two.card())
        self.assertEqual(oks, [True, True])
        links = sorted(self.server.connections, key=lambda c: c.address)
        sessions = [c.session for c in links]
        self.assertEqual(len(set(sessions)), 2)
        self.assertEqual({c.player for c in links}, {player["login_id"]})
        # Each cabinet's results are kept, each with its own session.
        await asyncio.gather(one.send_results([(1, 1, 5000)]), two.send_results([(1, 1, 6000)]))
        await self.until(lambda: self.plays() == 2, why="both cabinets' results")
        reader = sqlite3.connect(self.path)
        kept = sorted(reader.execute("SELECT score, session_id FROM plays").fetchall())
        reader.close()
        self.assertEqual([k[0] for k in kept], [5000, 6000])
        self.assertEqual(sorted(k[1] for k in kept), sorted(sessions))
        await self.until(lambda: self.table() == self.window(), why="the first places")

    async def test_eight_cabinets_send_the_same_chart_in_the_same_second(self):
        cabs = [await self.cabinet(row) for row in self.players[:8]]
        await asyncio.gather(*[cab.card() for cab in cabs])
        # The same chart from all eight at once: scores that tie, and played in the same second.
        scores = [7000, 9000, 9000, 8000, 9000, 6000, 9000, 1000]
        await asyncio.gather(*[cab.send_results([(2, 1, score)]) for cab, score in zip(cabs, scores)])
        await self.until(lambda: self.plays() == 8, why="every result")
        # No write lost, and the first place is the database's own: the highest score, the earliest play of it.
        self.assertEqual(self.table(), self.window())
        reader = sqlite3.connect(self.path)
        top = reader.execute("SELECT account_id FROM plays WHERE score = 9000 ORDER BY played_at, id LIMIT 1").fetchone()
        reader.close()
        self.assertEqual(self.server.firsts.top(0, 2, 1).account_id, top[0])
        # A login afterwards sends that first place.
        later = await self.cabinet(self.players[9])
        await later.card()
        await asyncio.wait_for(later.firsts_seen.wait(), 5)
        await self.until(lambda: any(m[0] == 0x5F for m in later.login), why="the first places sent")
        sent = [m for m in later.login if m[0] == 0x5F]
        self.assertEqual(struct.unpack_from("<IIBI", sent[0], 8), (0, 2, 1, 9000))

    async def test_plays_go_on_through_a_backup_a_restore_and_a_song_list_swap(self):
        from opendmt3.server.services import backups
        from opendmt3.server.web.app import Site
        from opendmt3.server.web import common
        site = Site(self.tmp, game_server=self.server)
        cabs = await self.players_cabinets(6)
        stop = asyncio.Event()
        sent = [0]
        playing = self.playing(cabs, stop, sent)
        loop = asyncio.get_running_loop()
        await asyncio.sleep(0.3)
        # A backup while plays come in: a consistent copy, the plays going on meanwhile.
        name = await loop.run_in_executor(None, backups.make, self.path, self.tmp, "manual")
        copy = sqlite3.connect(os.path.join(backups.folder(self.tmp), name))
        self.assertEqual(copy.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        in_backup = copy.execute("SELECT COUNT(*) FROM plays").fetchone()[0]
        copy.close()
        self.assertGreater(in_backup, 0)
        # The song list put in its place again and again while results come in: never half read.
        song_list = os.path.join(self.tmp, "catalog.json")

        def swap():
            for n in range(30):
                part = song_list + ".part"
                with open(part, "w") as f:
                    json.dump({"songs": [{"number": s, "title": "Song %d (%d)" % (s, n)} for s in (1, 2, 3)]}, f)
                # Windows replaces no file another handle has open (a login reading the list at that moment): tried
                # again once it is closed, as anything replacing a file there must, for a few seconds at most.
                given_up = time.monotonic() + 5
                while True:
                    try:
                        os.replace(part, song_list)
                        break
                    except PermissionError:
                        if os.name != "nt" or time.monotonic() > given_up:
                            raise
                        time.sleep(0.002)
                time.sleep(0.005)
        await loop.run_in_executor(None, swap)
        await asyncio.sleep(0.2)
        # A restore while plays come in (the site's: the game server's writes wait meanwhile): every play kept before
        # it is in the backup the restore makes first, every play after it is in the database as restored, and none
        # falls between the two.
        before_restore = self.plays()
        safety = await loop.run_in_executor(None, common._restore, site, name)
        await asyncio.sleep(0.3)
        stop.set()
        await asyncio.gather(*playing)
        safe = sqlite3.connect(os.path.join(backups.folder(self.tmp), safety))
        kept_in_safety = safe.execute("SELECT COUNT(*) FROM plays").fetchone()[0]
        safe.close()
        self.assertGreaterEqual(kept_in_safety, before_restore)
        # Results get no answer: wait until the last ones sent are written, every one of them in one of the two.
        await self.until(lambda: kept_in_safety + self.plays() - in_backup == sent[0], seconds=15,
                         why="every play in the restore's first backup or after it (sent %d)" % sent[0])
        # And the first places follow the restored database.
        await self.until(lambda: self.table() == self.window(), why="the first places after the restore")

    async def test_a_reset_while_plays_come_in_loses_none(self):
        # Every play is reset while cabinets keep sending results: each play is in the reset's backup or in the
        # database after it, never between the two (the game server's writes wait from the backup to the deletion).
        from opendmt3.server.services import backups
        from opendmt3.server.web.app import Site
        from opendmt3.server.web import common
        site = Site(self.tmp, game_server=self.server)
        cabs = await self.players_cabinets(4)
        stop, sent = asyncio.Event(), [0]
        playing = self.playing(cabs, stop, sent)
        await asyncio.sleep(0.3)
        real = backups.make

        def slow_make(*args, **kwargs):
            # The backup taken, then half a second before the deletion: plays sent meanwhile must not fall between.
            name = real(*args, **kwargs)
            time.sleep(0.5)
            return name
        with mock.patch.object(backups, "make", slow_make):
            gone, kept = await asyncio.get_running_loop().run_in_executor(None, common._reset_plays, site, "BOSS")
        await asyncio.sleep(0.3)
        stop.set()
        await asyncio.gather(*playing)
        copy = sqlite3.connect(os.path.join(backups.folder(self.tmp), kept))
        in_backup = copy.execute("SELECT COUNT(*) FROM plays").fetchone()[0]
        copy.close()
        self.assertEqual(gone, in_backup)
        await self.until(lambda: in_backup + self.plays() == sent[0], seconds=15,
                         why="every play in the reset's backup or after it (sent %d)" % sent[0])

    async def test_a_held_database_never_reaches_a_player(self):
        cab = await self.cabinet(self.players[0])
        await cab.card()
        loop = asyncio.get_running_loop()
        # Another connection (another program, a long restore) holds the write lock for longer than the busy timeout.
        holder = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        holder.execute("BEGIN IMMEDIATE")
        try:
            # The game server's connection gives up a statement after 0.2 s here (BUSY_SECONDS is 15 by default).
            self.db.execute("PRAGMA busy_timeout = 200")
            await cab.send_results([(1, 1, 4321)])
            # The loop goes on meanwhile: the cabinet's keep-alives are answered at once, the link stays.
            for _ in range(8):
                cab.keep_alive()
                await self.until(lambda: cab.sent_at is None, seconds=2, why="a keep-alive's answer")
                await asyncio.sleep(0.1)
            self.assertLess(max(cab.answers), 0.5)
            self.assertEqual(self.plays(), 0)
        finally:
            await loop.run_in_executor(None, holder.execute, "COMMIT")
            holder.close()
        # Once the database is free the results are kept: tried again, never lost, the link never dropped.
        await self.until(lambda: self.plays() == 1, why="the results after the lock")
        self.assertEqual(len(self.server.connections), 1)
        self.db.execute("PRAGMA busy_timeout = %d" % (db.BUSY_SECONDS * 1000))

    async def test_a_site_write_waits_out_a_short_hold(self):
        import httpx
        from opendmt3.server.web.app import Site, create_app
        app = create_app(Site(self.tmp, game_server=self.server))
        holder = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        holder.execute("BEGIN IMMEDIATE")
        loop = asyncio.get_running_loop()
        loop.call_later(1.0, holder.execute, "COMMIT")
        transport = httpx.ASGITransport(app=app, client=("203.0.113.5", 50000))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # A sign-in writes the account's last sign-in: it waits for the lock and goes through.
            r = await client.post("/api/v1/session", json={"login_id": "BOSS", "password": "pass1234"})
        holder.close()
        self.assertEqual(r.status_code, 200)


class ReadersTest(Together):
    """The game server's reads on threads beside its one writer (GameServer.read): a long read holds up nobody, and
    every read sees the writes made before it, in their order."""

    def scores(self):
        """Every play's score in the database, as another program reads it."""
        reader = sqlite3.connect(self.path)
        try:
            return [row[0] for row in reader.execute("SELECT score FROM plays")]
        finally:
            reader.close()

    async def test_a_long_read_never_holds_up_another_cabinets_write_or_login(self):
        from opendmt3.server.services import records as records_service
        slow, other, third = self.players[0], self.players[1], self.players[2]
        real = records_service.Records.bests

        def bests(records_self, account_id):
            # The slow player's records take a second to read (a history of tens of thousands of plays).
            if account_id == slow["id"]:
                time.sleep(1.0)
            return real(records_self, account_id)
        b = await self.cabinet(other, "127.0.0.2")
        c = await self.cabinet(third, "127.0.0.3")
        self.assertTrue(await b.card())
        a = await self.cabinet(slow, "127.0.0.4")
        with mock.patch.object(records_service.Records, "bests", bests):
            # Timed by perf_counter: Windows' monotonic clock moves in steps of 15.6 ms (before Python 3.13), which
            # could make the slow login's second measure shorter than the second it slept.
            started = time.perf_counter()
            asking = asyncio.ensure_future(a.card())
            await asyncio.sleep(0.1)
            # While the slow login reads: another cabinet's results, and a third cabinet's login.
            await b.send_results([(1, 1, 777001)])
            await self.until(lambda: 777001 in self.scores(), seconds=0.6,
                             why="the other cabinet's results kept while the slow login reads")
            kept = time.perf_counter() - started
            self.assertTrue(await c.card())
            third_done = time.perf_counter() - started
            self.assertTrue(await asking)
            slow_done = time.perf_counter() - started
        # The writer and the other readers went on beside the slow read: neither waited for its second.
        self.assertLess(kept, 0.7)
        self.assertLess(third_done, 0.8)
        self.assertGreaterEqual(slow_done, 1.0)

    async def test_each_login_reads_the_results_its_link_sent_before_it(self):
        # Eight cabinets, five rounds each: results with a new best on one chart, then a card login at once. Each
        # login's records (read beside the writer) hold that best, every stage is kept, and the first places are the
        # database's own.
        cabs = [await self.cabinet(row, "127.0.0.%d" % (2 + n // 8)) for n, row in enumerate(self.players[:8])]
        for cab in cabs:
            self.assertTrue(await cab.card())

        async def rounds(n, cab):
            seen = []
            for k in range(5):
                score = 600000 + n * 1000 + k * 10
                await cab.send_results([(1 + n % 3, 1 + k % 2, score)])
                self.assertTrue(await cab.card())
                mine = {}
                for msg in cab.login:
                    if msg[0] == 0x5A:
                        mode, song, pattern, _, best, _ = struct.unpack_from("<BIBBII", msg, 8)
                        mine[(mode, song, pattern)] = best
                seen.append(mine.get((0, 1 + n % 3, 1 + k % 2)) == score)
            return seen
        seen = await asyncio.gather(*[rounds(n, cab) for n, cab in enumerate(cabs)])
        self.assertEqual(seen, [[True] * 5] * 8)
        self.assertEqual(len([score for score in self.scores() if score >= 600000]), 40)
        self.assertEqual(self.table(), self.window())

    async def test_a_restore_holds_the_readers_too(self):
        # paused() holds the reading threads with the writer: no login reads the database while it is put back.
        cab = await self.cabinet(self.players[0], "127.0.0.2")
        loop = asyncio.get_running_loop()
        held, release = threading.Event(), threading.Event()

        def restore_like():
            with self.server.paused():
                held.set()
                release.wait(5)
        reads_while_held = []
        real = GameServer.login_reads

        def login_reads(server_self, *args):
            # A login's reads, noted when they run while the database is held.
            reads_while_held.append(held.is_set() and not release.is_set())
            return real(server_self, *args)
        with mock.patch.object(GameServer, "login_reads", login_reads):
            holder = loop.run_in_executor(None, restore_like)
            await loop.run_in_executor(None, held.wait, 5)
            asking = asyncio.ensure_future(cab.card())
            await asyncio.sleep(0.5)
            # Not answered, nor even read, while held.
            self.assertFalse(asking.done())
            release.set()
            await holder
            self.assertTrue(await asking)
        self.assertEqual(reads_while_held, [False])


class HoldsTest(Together):
    """GameServer.paused: a hold lasts as long as its block, and a login that a reset came between is done again."""

    async def test_a_hold_lasts_until_its_block_ends_past_the_wait_for_it(self):
        from opendmt3.server import server as server_module
        cab = await self.cabinet(self.players[0], "127.0.0.2")
        self.assertTrue(await cab.card())
        loop = asyncio.get_running_loop()
        held, release = threading.Event(), threading.Event()

        def long_block():
            # A block three times as long as the wait for the hold (a reset of a large database).
            with self.server.paused():
                held.set()
                release.wait(5)
        with mock.patch.object(server_module, "PAUSE_MOST", 0.3):
            holder = loop.run_in_executor(None, long_block)
            await loop.run_in_executor(None, held.wait, 5)
            before = self.plays()
            await cab.send_results([(1, 1, 424242)])
            await asyncio.sleep(0.9)
            # Past PAUSE_MOST since the hold began: still held, nothing kept.
            self.assertEqual(self.plays(), before)
            release.set()
            await holder
        await self.until(lambda: self.plays() == before + 1, why="the results kept once the block ended")

    async def test_a_login_that_a_reset_came_between_is_done_again(self):
        from opendmt3.server.web.app import Site
        from opendmt3.server.web import common
        site = Site(self.tmp, game_server=self.server)
        cab = await self.cabinet(self.players[0], "127.0.0.2")
        self.assertTrue(await cab.card())
        await cab.send_results([(1, 1, 515151), (2, 1, 616161)])
        await self.until(lambda: self.plays() == 2, why="the results kept")
        read, go_on = threading.Event(), threading.Event()
        real = GameServer.login_reads

        def login_reads(server_self, *args):
            # The reads made, then held until the reset is done.
            out = real(server_self, *args)
            read.set()
            go_on.wait(5)
            return out
        loop = asyncio.get_running_loop()
        with mock.patch.object(GameServer, "login_reads", login_reads):
            asking = asyncio.ensure_future(cab.card())
            await loop.run_in_executor(None, read.wait, 5)
            await loop.run_in_executor(None, common._reset_plays, site, "BOSS")
            go_on.set()
            self.assertTrue(await asking)
        # The records the login sent are the database's after the reset (none), not the two before it.
        self.assertEqual([m for m in cab.login if m[0] == 0x5A], [])


class IsolationTest(Together):

    async def test_one_bad_cabinet_never_slows_the_others(self):
        good = [await self.cabinet(row, "127.0.0.%d" % (1 + k // 8)) for k, row in enumerate(self.players[:15])]
        await asyncio.gather(*[cab.card() for cab in good])
        stop = asyncio.Event()

        async def keep_alive(cab):
            while not stop.is_set():
                cab.keep_alive()
                await asyncio.sleep(0.05)
        alive = [asyncio.ensure_future(keep_alive(cab)) for cab in good]
        bad_row = self.players[20]

        async def bad():
            # From an address of its own (its limits are its own): garbage, a link it never reads (the server stops
            # writing to it after SEND_LIMIT), a link cut half way through a message, a message of no kind.
            for round_ in range(3):
                reader, writer = await asyncio.open_connection("127.0.0.1", self.server.port,
                                                               local_addr=("127.0.0.9", 0))
                writer.write(os.urandom(4096))
                await writer.drain()
                writer.close()
                link = await Cabinet(self.server.port, bad_row, "127.0.0.9").open()
                link.reading.cancel()
                msg = bytearray(28)
                msg[0] = 0x60
                msg[8:8 + 20] = bad_row["card"].encode()
                link.client.write(bytes(msg))
                await link.client.writer.drain()
                await asyncio.sleep(0.3)
                link.client.writer.close()
                half = await Cabinet(self.server.port, bad_row, "127.0.0.9").open()
                half.client.writer.write(half.client.write(results(bad_row["id"], [(1, 1, 1)]), flush=False)[:40])
                await half.client.writer.drain()
                half.client.writer.close()
                odd = await Cabinet(self.server.port, bad_row, "127.0.0.9").open()
                unknown = bytearray(8)
                unknown[0] = 0xEE
                odd.client.write(bytes(unknown))
                await asyncio.sleep(0.1)
                for gone in (link, half, odd):
                    gone.reading.cancel()
                    gone.client.writer.close()
        await bad()
        await asyncio.sleep(0.5)
        stop.set()
        await asyncio.gather(*alive)
        # The fifteen good cabinets: every one still online, every keep-alive answered at once.
        answers = [a for cab in good for a in cab.answers]
        self.assertGreater(len(answers), 15 * 10)
        self.assertLess(max(answers), 0.25, "the slowest keep-alive took %.0f ms" % (max(answers) * 1000))
        online = [c for c in self.server.connections if c.online and c.player in {r["login_id"] for r in
                                                                                   self.players[:15]}]
        self.assertEqual(len(online), 15)

    async def test_a_link_that_asks_and_never_reads_is_dropped_holding_nothing(self):
        from opendmt3.server import connection
        # A long history: 20,000 charts' first places, all one player's, so a login's answer is thousands of messages
        # (the song list has their songs).
        with open(os.path.join(self.tmp, "catalog.json"), "w") as f:
            json.dump({"songs": [{"number": n, "title": "Song %d" % n} for n in range(1, 5001)]}, f)
        # The good cabinet logs in before the history is there: its own answer is a few messages. Logged in after it,
        # it had the 20,000 first places to read itself (761 KB the stand-in decrypts in Python on this test's loop),
        # and its keep-alives' answers sat behind them in its own stream: 1.011 s once on a busy PC, the server's
        # answer long sent.
        good = await self.cabinet(self.players[1], "127.0.0.2")
        await good.card()
        self.assertLess(len(good.login), 50)
        player = self.players[0]
        self.db.execute("BEGIN")
        self.db.executemany("INSERT INTO plays (account_id, cabinet, mode, song, pattern, score, counts, record,"
                            " played_at) VALUES (?, 'x', 0, ?, ?, 1000, '', x'00', 1)",
                            [(player["id"], song, pattern) for song in range(1, 5001) for pattern in range(1, 5)])
        self.db.execute("COMMIT")
        most, links, answers, drops, unsent = [0], [], [], [], []
        real_queue, real_sealed, real_drop = connection.Connection.queue, connection.Connection._sealed, \
            connection.Connection.drop

        def counted(conn, work):
            # How many handlers the greedy link ever had queued at once, and the link itself.
            task = real_queue(conn, work)
            if conn.address.startswith("127.0.0.9"):
                most[0] = max(most[0], conn._queued)
                if conn not in links:
                    links.append(conn)
            return task

        def sealed(batch, state):
            # Every answer made (on its worker thread): when it began, and its size.
            began = time.monotonic()
            data, after = real_sealed(batch, state)
            answers.append((began, len(data)))
            return data, after

        def dropped(conn, why):
            # When the server gave the link up, and what it had written for the link that had not gone out by then.
            drops.append(time.monotonic())
            unsent.append(conn.writer.transport.get_write_buffer_size())
            return real_drop(conn, why)
        with mock.patch.object(connection, "SEND_LIMIT", 0.5), \
                mock.patch.object(connection.Connection, "queue", counted), \
                mock.patch.object(connection.Connection, "_sealed", staticmethod(sealed)), \
                mock.patch.object(connection.Connection, "drop", dropped):
            reader, writer = await asyncio.open_connection("127.0.0.1", self.server.port, local_addr=("127.0.0.9", 0))
            greedy = StandInClient(reader, writer)
            await greedy.handshake()
            card = bytearray(28)
            card[0] = 0x60
            card[8:28] = player["card"].encode()
            # Forty logins at once, and never a byte read of their answers: far more than the system's buffers take (4
            # MB sent, the reader's window), so the server's sends must wait.
            for _ in range(40):
                greedy.write(bytes(card))
            await writer.drain()
            started = time.monotonic()
            gone = []

            async def watch():
                # The moment the greedy link left the server's list.
                while any(c.address.startswith("127.0.0.9") for c in self.server.connections):
                    await asyncio.sleep(0.05)
                gone.append(time.monotonic() - started)
            watcher = asyncio.ensure_future(watch())
            # The other cabinet goes on meanwhile: a keep-alive every 0.1 s for 6 s.
            for _ in range(60):
                good.keep_alive()
                await asyncio.sleep(0.1)
            await asyncio.wait_for(watcher, 30)
            writer.close()
        transport = links[0].writer.transport
        # Dropped once an answer waited past SEND_LIMIT (long before the 90 s a silent link gets), what it left unsent
        # thrown away at once (not kept until a client that never reads takes it), no answer made once it was gone,
        # never more kept for it in memory than the answer it did not read, its queue never past QUEUED_MOST, and the
        # other cabinet's keep-alives answered at once all the while.
        # The largest answer made (a login's 20,000 first places: 780,008 bytes).
        largest = max((size for began, size in answers), default=0)
        # What happened, in every failure's line (a busy PC: 2.2 s, 10 answers and 808,020 bytes here at a load of 12).
        seen = ("dropped after %.1f s, %d answers made, %d bytes unsent at the drop (the largest answer %d), "
                "at most %d queued, the other's slowest keep-alive %.3f s" % (
                    gone[0], len(answers), unsent[0] if unsent else -1, largest, most[0], max(good.answers)))
        # Dropped by the send limit, long before the 90 s a silent link gets.
        self.assertLess(gone[0], 20, seen)
        self.assertTrue(transport.is_closing(), seen)
        self.assertEqual(transport.get_write_buffer_size(), 0, seen)
        self.assertTrue(drops, seen)
        self.assertEqual([size for began, size in answers if began > drops[0]], [], seen)
        # What waited for the link in the server's memory when it was dropped: the answer that did not go out and
        # what was left of the one before (under the transport's 64 KiB mark), never two answers' worth: each answer
        # has gone out before the next is made (send_all's _drain). Without that, 34 to 39 MB waited here. How many
        # answers were made says nothing of it: as many as the system's own buffers took (3 to 28 of the 80 in 113
        # runs, up to 32 MB a reading side by this kernel's limits; 32 to 70 without the wait).
        self.assertLess(unsent[0], 2 * largest, seen)
        self.assertLessEqual(most[0], connection.QUEUED_MOST, seen)
        self.assertLess(max(good.answers), 0.25, seen)
        self.assertIn(good.row["login_id"], {c.player for c in self.server.connections})

    @unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
    async def test_a_failing_request_answers_alone(self):
        import httpx
        from opendmt3.server.web import api
        from opendmt3.server.web.app import Site, create_app
        site = Site(self.tmp, game_server=self.server)
        app = create_app(site)
        opened = []
        real = db.connect

        def traced(path, **kwargs):
            connection_ = real(path, **kwargs)
            opened.append(connection_)
            return connection_
        failing = [True]
        real_songs = api._songs

        def songs_once(s):
            # The first request for the songs fails half way (a bug, a broken file); the rest go through.
            if failing[0]:
                failing[0] = False
                raise RuntimeError("made-up failure")
            return real_songs(s)
        cab = await self.cabinet(self.players[0])
        await cab.card()
        transport = httpx.ASGITransport(app=app, client=("203.0.113.5", 50000))
        with mock.patch.object(db, "connect", traced), mock.patch.object(api, "_songs", songs_once), \
                self.assertLogs("opendmt3.web", "ERROR"):
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                token = (await client.post("/api/v1/session", json={"login_id": "BOSS", "password": "pass1234"}
                                           )).json()["token"]
                auth = {"Authorization": "Bearer " + token}
                cab.keep_alive()
                answers = await asyncio.gather(client.get("/api/v1/songs", headers=auth),
                                               *[client.get(path, headers=auth) for path in
                                                 ("/api/v1/rankings", "/api/v1/plays?everyone=1", "/api/v1/me",
                                                  "/api/v1/songs/1")])
                again = await client.get("/api/v1/songs", headers=auth)
        self.assertEqual([a.status_code for a in answers], [500, 200, 200, 200, 200])
        self.assertEqual(again.status_code, 200)
        await self.until(lambda: cab.sent_at is None, why="the keep-alive's answer")
        # Every request's connection was given back (closed), the failing one's too, and no turn is left held.
        for c in opened:
            with self.assertRaises(sqlite3.ProgrammingError):
                c.execute("SELECT 1")
        self.assertEqual(site.turns().keys, {})


@unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
class FairnessTest(Together):

    async def asyncSetUp(self):
        await super().asyncSetUp()
        from opendmt3.server.web.app import Site, create_app
        self.site = Site(self.tmp, game_server=self.server)
        self.app = create_app(self.site)

    async def token(self, client, login_id):
        r = await client.post("/api/v1/session", json={"login_id": login_id, "password": "pass1234"})
        return {"Authorization": "Bearer " + r.json()["token"]}

    async def test_a_token_asking_over_and_over_gets_its_share_and_others_keep_theirs(self):
        import httpx
        from opendmt3.server.web import app as web_app
        from opendmt3.server.web import api
        running, most, lock = [0], [0], threading.Lock()
        real = api._dj

        def heavy(site, player):
            # The heaviest call made heavy: 50 ms of processor time each, and how many run at once is noted.
            with lock:
                running[0] += 1
                most[0] = max(most[0], running[0])
            try:
                started = time.thread_time()
                while time.thread_time() - started < 0.05:
                    pass
                return real(site, player)
            finally:
                with lock:
                    running[0] -= 1
        hog_transport = httpx.ASGITransport(app=self.app, client=("198.51.100.7", 50000))
        transport = httpx.ASGITransport(app=self.app, client=("203.0.113.5", 50000))
        with mock.patch.object(api, "_dj", heavy), mock.patch.object(web_app, "CALLER_SECONDS", 0.5):
            async with httpx.AsyncClient(transport=hog_transport, base_url="http://testserver") as hog, \
                    httpx.AsyncClient(transport=transport, base_url="http://testserver") as other:
                hog_auth = await self.token(hog, "P00")
                other_auth = await self.token(other, "P01")
                deadline = time.monotonic() + 3
                hog_codes, other_times, other_codes = [], [], []

                async def hog_loop():
                    while time.monotonic() < deadline:
                        r = await hog.get("/api/v1/djs/%d" % self.players[0]["id"], headers=hog_auth)
                        hog_codes.append(r.status_code)
                        if r.status_code == 429:
                            self.assertGreaterEqual(int(r.headers["Retry-After"]), 1)

                async def other_loop():
                    while time.monotonic() < deadline:
                        started = time.monotonic()
                        r = await other.get("/api/v1/rankings", headers=other_auth)
                        other_times.append(time.monotonic() - started)
                        other_codes.append(r.status_code)
                        await asyncio.sleep(0.05)
                # Eight of the hog's requests at once, all the time, beside one other player.
                await asyncio.gather(*[hog_loop() for _ in range(8)], other_loop())
        # The hog: its heavy call ran, its share at once and never more, and was refused once its half second was spent.
        self.assertEqual(most[0], web_app.CALLER_AT_ONCE)
        self.assertIn(429, hog_codes)
        self.assertIn(200, hog_codes)
        # The other player: every request answered, none refused, none kept waiting behind the hog.
        self.assertEqual(set(other_codes), {200})
        other_times.sort()
        self.assertLess(other_times[int(0.95 * (len(other_times) - 1))], 0.5)

    async def test_requests_waiting_their_turn_are_refused_once_the_seconds_are_spent(self):
        # Four heavy calls of one token at once, each taking 0.2 s of processor time against a share of 0.1 s: the
        # first runs; the others, admitted while nothing was spent, find the seconds spent when their turn comes.
        import httpx
        from opendmt3.server.web import app as web_app
        from opendmt3.server.web import api
        real = api._dj

        def heavy(site, player):
            started = time.thread_time()
            while time.thread_time() - started < 0.2:
                pass
            return real(site, player)
        transport = httpx.ASGITransport(app=self.app, client=("198.51.100.7", 50000))
        with mock.patch.object(api, "_dj", heavy), mock.patch.object(web_app, "CALLER_SECONDS", 0.1):
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                auth = await self.token(client, "P00")
                answers = await asyncio.gather(*[client.get("/api/v1/djs/%d" % self.players[0]["id"], headers=auth)
                                                 for _ in range(4)])
        self.assertEqual(sorted(a.status_code for a in answers), [200, 429, 429, 429])

    async def test_refusals_and_missing_files_make_no_page_each(self):
        # A flood of refused page requests: the busy page made once and handed out; a missing file or picture under
        # the free paths answered plainly; "/healthX" is no free path.
        import httpx
        from opendmt3.server.web import app as web_app
        made, renders = [], []
        real_made, real_render = web_app.Site._busy_made, web_app.Site.render

        def counted_made(site_self, key):
            made.append(key)
            return real_made(site_self, key)

        def counted_render(site_self, *args, **kwargs):
            renders.append(args[1] if len(args) > 1 else kwargs.get("name"))
            return real_render(site_self, *args, **kwargs)
        transport = httpx.ASGITransport(app=self.app, client=("198.51.100.9", 50000))
        # The shares' clock held still: the busy page is made for each number of seconds to wait it says, which a
        # flood answered over more than a second (a busy PC, Wine) would see go down by one, and make a second page.
        held = time.monotonic()
        with mock.patch.object(web_app.Site, "_busy_made", counted_made), \
                mock.patch.object(web_app.Site, "render", counted_render), \
                mock.patch.object(self.site.spent, "clock", lambda: held):
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                # The address's seconds spent: every page it asks for is refused.
                self.site.spent.add("address:198.51.100.9", 10 * web_app.ADDRESS_SECONDS)
                refused = await asyncio.gather(*[client.get("/") for _ in range(30)])
                self.assertEqual({r.status_code for r in refused}, {429})
                self.assertTrue(all("Retry-After" in r.headers for r in refused))
                self.assertEqual(len(made), 1)
                # Missing files: plain, no page made (and not counted, so not refused either).
                for path in ("/static/nothing.css", "/fonts/none"):
                    r = await client.get(path)
                    self.assertEqual((r.status_code, r.text), (404, "Not Found"), path)
                # Pictures are for those signed in: the wall's redirect, no page made either.
                for path in ("/jackets/99999.png", "/cards/icon/99999.png"):
                    self.assertEqual((await client.get(path)).status_code, 303, path)
                self.assertEqual(renders, [])
                # "/healthX" is counted as a page: refused like the rest from this address.
                self.assertEqual((await client.get("/healthX")).status_code, 429)
                self.assertEqual((await client.get("/health")).status_code, 200)

    async def test_health_checks_while_the_database_is_held_never_hold_up_a_page(self):
        # Another connection holds the write lock two seconds; the health check, past its kept answer, waits for it on
        # the long work's threads, one look at a time, while a page is answered at once on the site's own.
        import httpx
        from opendmt3.server.web import app as web_app
        held, release = threading.Event(), threading.Event()

        def hold():
            other = sqlite3.connect(self.path)
            other.execute("BEGIN IMMEDIATE")
            held.set()
            release.wait(5)
            other.execute("ROLLBACK")
            other.close()
        holder = threading.Thread(target=hold)
        holder.start()
        held.wait(5)
        try:
            transport = httpx.ASGITransport(app=self.app, client=("203.0.113.8", 50000))
            with mock.patch.object(web_app, "HEALTH_KEPT", 0.0):
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                    checks = [asyncio.ensure_future(client.get("/health")) for _ in range(4)]
                    await asyncio.sleep(0.2)
                    started = time.monotonic()
                    page = await client.get("/signin")
                    took = time.monotonic() - started
                    await asyncio.sleep(1.5)
                    release.set()
                    answers = await asyncio.gather(*checks)
        finally:
            release.set()
            holder.join()
        self.assertEqual(page.status_code, 200)
        self.assertLess(took, 1.0, "a page waited %.2f s behind health checks" % took)
        self.assertEqual({a.status_code for a in answers} - {200, 503}, set())

    async def test_uploads_take_their_turns(self):
        # Fifty uploads at once with one token (refused as no admin's, slowly): one at a time and 32 waiting, the
        # rest refused at once with 429.
        import httpx
        from opendmt3.server.web import app as web_app
        real = web_app.Site.connect

        def slow_connect(site_self):
            # The token looked up slowly: each upload holds its turn a while.
            time.sleep(0.2)
            return real(site_self)
        transport = httpx.ASGITransport(app=self.app, client=("198.51.100.20", 50000))
        with mock.patch.object(web_app.Site, "connect", slow_connect):
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=60) as client:
                answers = await asyncio.gather(*[client.post("/api/v1/backups/upload", content=b"x",
                                                             headers={"Authorization": "Bearer odt3_made_up"})
                                                 for _ in range(50)])
        codes = [a.status_code for a in answers]
        self.assertEqual(codes.count(429), 50 - 1 - 32, codes)

    async def test_a_missing_picture_is_a_plain_answer_for_those_signed_in(self):
        import httpx
        transport = httpx.ASGITransport(app=self.app, client=("203.0.113.7", 50000))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            page = (await client.get("/signin")).text
            token = page.split('name="csrf" value="', 1)[1].split('"', 1)[0]
            r = await client.post("/signin", data={"csrf": token, "login_id": "P00", "password": "pass1234"})
            self.assertEqual(r.status_code, 303)
            for path in ("/jackets/99999.png", "/cards/icon/99999.png"):
                r = await client.get(path)
                self.assertEqual((r.status_code, r.text), (404, "Not Found"), path)

    async def test_a_callers_waiting_requests_hold_no_worker_thread_and_too_many_are_refused(self):
        import httpx
        from opendmt3.server.web import app as web_app
        from opendmt3.server.web import api
        real = api._dj
        busy, most, lock = [0], [0], threading.Lock()

        def slow(site, player):
            with lock:
                busy[0] += 1
                most[0] = max(most[0], busy[0])
            try:
                time.sleep(0.2)
                return real(site, player)
            finally:
                with lock:
                    busy[0] -= 1
        transport = httpx.ASGITransport(app=self.app, client=("198.51.100.7", 50000))
        other_transport = httpx.ASGITransport(app=self.app, client=("203.0.113.5", 50000))
        with mock.patch.object(api, "_dj", slow), mock.patch.object(web_app, "WAITING_MOST", 4):
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as hog, \
                    httpx.AsyncClient(transport=other_transport, base_url="http://testserver") as other:
                auth = await self.token(hog, "P00")
                other_auth = await self.token(other, "P01")
                path = "/api/v1/djs/%d" % self.players[0]["id"]
                started = time.monotonic()
                hog_calls = asyncio.gather(*[hog.get(path, headers=auth) for _ in range(10)])
                await asyncio.sleep(0.05)
                # Meanwhile another player's call is answered without waiting for the hog's queue.
                r = await other.get("/api/v1/me", headers=other_auth)
                other_took = time.monotonic() - started
                answers = await hog_calls
        self.assertEqual(r.status_code, 200)
        self.assertLess(other_took, 0.4)
        codes = sorted(a.status_code for a in answers)
        # Its share answered at a time, four more waiting their turn, the rest refused at once.
        self.assertEqual(codes.count(200), web_app.CALLER_AT_ONCE + 4)
        self.assertEqual(codes.count(429), 10 - web_app.CALLER_AT_ONCE - 4)
        self.assertEqual(most[0], web_app.CALLER_AT_ONCE)


class HammerTest(Together):

    @unittest.skipUnless(WEB, "needs starlette, jinja2, httpx and python-multipart")
    async def test_cabinets_visitors_and_threads_at_once_leave_every_answer_right(self):
        import httpx
        from concurrent.futures import ThreadPoolExecutor
        from starlette.testclient import TestClient
        from opendmt3.server.services import limits
        from opendmt3.server.web.app import Site, create_app
        site = Site(self.tmp, game_server=self.server)
        app = create_app(site)
        rng = random.Random(9)
        cabs = [await self.cabinet(row, "127.0.0.%d" % (1 + k // 8)) for k, row in enumerate(self.players[:16])]
        stages_sent = [0]
        failures = []

        async def play(cab):
            # Six credits each: a login (its whole answer read), then a credit's three stages.
            for _ in range(6):
                if not await cab.card():
                    failures.append("a login refused")
                stages = [CHARTS[rng.randrange(6)] + (rng.randrange(1, 100) * 1000,) for _ in range(3)]
                await cab.send_results(stages, mode=rng.choice((0, 1)))
                stages_sent[0] += 3
                await asyncio.sleep(rng.random() * 0.05)

        codes = []

        async def visit(k):
            # Sixteen visitors on the site's pages and API meanwhile, each its own token from an address of its own.
            transport = httpx.ASGITransport(app=app, client=("203.0.113.%d" % (10 + k), 50000))
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                r = await client.post("/api/v1/session", json={"login_id": "P%02d" % (20 + k), "password": "pass1234"})
                auth = {"Authorization": "Bearer " + r.json()["token"]}
                paths = ["/api/v1/rankings", "/api/v1/rankings?by=best30", "/api/v1/songs", "/api/v1/songs/1",
                         "/api/v1/plays?everyone=1", "/api/v1/plays?records=1", "/api/v1/cabinets",
                         "/api/v1/djs/%d" % self.players[k % 16]["id"]]
                asked = 0
                # Until the cabinets are done, and three times at the least.
                while not finished.is_set() or asked < 3:
                    r = await client.get(paths[rng.randrange(len(paths))], headers=auth)
                    codes.append(r.status_code)
                    asked += 1

        table = limits.Recent(60, lambda: 100000)

        def count(k):
            # The sign-in limits' table from many threads at once: every event counted, none lost.
            for n in range(2000):
                table.add("key%d" % (n % 7))
                table.count("key%d" % (n % 5))
        finished = asyncio.Event()
        visitors = [asyncio.ensure_future(visit(k)) for k in range(16)]
        with ThreadPoolExecutor(8) as pool:
            counting = [asyncio.get_running_loop().run_in_executor(pool, count, k) for k in range(8)]
            await asyncio.gather(*[play(cab) for cab in cabs])
            finished.set()
            await asyncio.gather(*visitors, *counting)
        self.assertEqual(failures, [])
        # Every request of the visitors answered (none failed, none refused: each had its own share).
        self.assertEqual(set(codes), {200})
        self.assertGreaterEqual(len(codes), 16 * 3)
        # Every stage sent was kept.
        await self.until(lambda: self.plays() == stages_sent[0], why="every stage kept")
        # The first places in memory are the database's own.
        self.assertEqual(self.table(), self.window())
        # The lists the site kept are the lists a site that keeps nothing makes now.
        def answers(application):
            client = TestClient(application)
            auth = {"Authorization": "Bearer " + client.post("/api/v1/session", json={
                "login_id": "BOSS", "password": "pass1234"}).json()["token"]}
            return {p: client.get(p, headers=auth).json() for p in (
                "/api/v1/rankings", "/api/v1/rankings?mode=1", "/api/v1/rankings?by=best30", "/api/v1/songs",
                "/api/v1/songs/1", "/api/v1/songs/2", "/api/v1/plays?everyone=1", "/api/v1/plays?records=1")}
        kept = await asyncio.get_running_loop().run_in_executor(None, answers, app)
        fresh = await asyncio.get_running_loop().run_in_executor(None, answers, create_app(Site(self.tmp)))
        self.assertEqual(kept, fresh)
        # The table every thread counted into holds every event (7 keys, 16,000 events).
        self.assertEqual(sum(len(v) for v in table.table.values()), 16000)


if __name__ == "__main__":
    unittest.main()
