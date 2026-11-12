"""Many cabinets, visitors and a greedy program on one server with a long history, for a long time.

Before the server starts, its database gets a made-up history (history.py: 300,000 plays of 1,000 players by
default, as a busy server has after half a year). Then, against a real server process (python -m opendmt3.server,
with its site):

- Stand-in cabinets (tests/server/test_server.StandInClient, the client's side of the link proven against the real
  client) go online and do what a cabinet does all day: keep alive as the real client does (0x0A every 11 seconds,
  0x07 for each of the server's pings), and every minute a player's session (a card login, its answer read whole,
  then the session's three cleared stages). One cabinet past the server's limit must be refused at once.
- One bad cabinet among them (from an address of its own): garbage, a login whose answer it never reads, a message
  cut half way, a kind the game does not have, again and again. The others must not notice.
- Twenty visitors on the site at the same time (each its own player, from an address of its own, a page every half
  second): Home, the rankings, the songs, the most played song, the busiest DJ and a typical one.
- A program with an admin's token asking for the heaviest call there is (every play as a file) four at a time,
  without a pause: it gets its share of the server's work (one call at a time, its seconds a minute) and no more.

The cabinets come from 127.0.0.1, 127.0.0.2 and on, PER_ADDRESS of them at each (one address holds no more links than
that), as cabinets of several homes would. Every SAMPLE seconds a line says the server's memory, the cabinets online,
the slowest keep-alive answer and what failed.

  python tests/e2e/load/cabinets.py [--cabinets 64] [--minutes 30] [--sample 30] [--plays 300000] [--site 20]
                                    [--no-hog] [--no-bad]

Run from the repository root with a Python that has the server's libraries and httpx (docs/server.md). It needs no
network beyond this PC's own loopback, and no game files. Passes (exit 0) when every good cabinet stayed online all the
time (none refused, dropped or left without an answer), every keep-alive was answered within 2 seconds and 95 % of them
within KEEP_ALIVE_P95, half the logins within LOGIN_P50, every session's login was answered, each page the visitors ask
for answered within SITE_P95 for 95 % of them and never refused, every call of the program answered (one at a time: the
rest wait their turn; 429 past its seconds), and the server's memory at the end within 10 % (or 8 MB) of what it was a
third of the way in (its kept lists and the C library's pools fill in the first minutes). On the history of 300,000
plays, the server before its first places were kept and its site's work moved off the game's loop failed each of
those (4 minutes: keep-alives 10.4 s at p95 with 64 cabinets and the slowest 15.2 s, logins 2.7 s at the median, 27
stages kept of 210 sessions' 630, the busiest DJ's page 27.9 s at p95 for 20 visitors), where this server kept them
for 30 minutes (keep-alives 29 ms at p95, logins 27 ms at the median, each page within 665 ms for 95 % of the
visitors' asks, memory flat at 91 MB for the last 18 minutes).
"""

import argparse
import asyncio
import json
import os
import random
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time

# Run from the repository root (python tests/e2e/load/cabinets.py).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from opendmt3.server import db  # noqa: E402
from opendmt3.server import crypto, messages  # noqa: E402
from opendmt3.server.server import MAX_CONNECTIONS, PER_ADDRESS  # noqa: E402
from opendmt3.server.services import accounts  # noqa: E402
from tests.e2e.load import history  # noqa: E402
from tests.server.test_server import StandInClient  # noqa: E402

KEEP_ALIVE = 11.0      # seconds between the real client's keep-alives
SESSION = 60.0         # seconds between one cabinet's player sessions
ANSWER_LIMIT = 2.0     # the slowest keep-alive answer that still passes
KEEP_ALIVE_P95 = 0.25  # 95 % of the keep-alives answered within this
LOGIN_P50 = 0.5        # half the card logins answered (0x64 read) within this
SITE_P95 = 1.0         # 95 % of each page the visitors ask for answered within this
THINK = 0.5            # seconds a visitor looks at a page before the next
HOG_AT_ONCE = 4        # the greedy program's calls in flight at a time
BAD_ADDRESS = "127.0.0.200"
ANSWER_TYPES = {0x1E, 0x5A, 0x65, 0x64, 0x66, 0x5F}   # what a card login is answered with
# Every made-up account's password (the cabinets' players, the visitors, the program's admin).
PASSWORD = "pass1234"


def address(number):
    """The loopback address cabinet `number` connects from: PER_ADDRESS cabinets on each (Linux answers on all of
    127.0.0.0/8)."""
    return "127.0.0.%d" % (1 + number // PER_ADDRESS)


def free_port():
    """A port nothing listens on now (the server is told to take it)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def listening(port):
    """True when something takes connections on this PC's port."""
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def rss_kib(pid):
    """The server process's resident memory in KiB (Linux /proc)."""
    with open("/proc/%d/status" % pid) as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    return 0


def percentile(values, p):
    """The p-th fraction of the sorted values (the largest for 1.0); None for none."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p * (len(ordered) - 1))))] if ordered else None


async def read_any(client, whole=False):
    """The next message from the server: its kind from its first block (the cipher works block by block, so the
    first 8 bytes decrypt alone), the rest read by the size the table gives. Decrypted whole only when asked
    (`whole`, or a kind whose body is read): a login's thousands of first places need only their kind, and decrypting
    them in Python would make this process the slow one."""
    head = await client.reader.readexactly(8)
    first = crypto.decrypt(head, client.to_client)
    kind = first[0]
    size = messages.TO_CLIENT[kind]
    rest = await client.reader.readexactly(size - 8) if size > 8 else b""
    msg = crypto.decrypt(head + rest, client.to_client) if (whole or kind == 0x64) else first + rest
    client.to_client = crypto.next_server_state(client.to_client)
    return msg


def results(user, stages):
    """A 0x6e like the game's (tests/server/test_server.CardLoginTest.results): user, mode 0, cleared, 47 bytes a
    stage."""
    msg = bytearray(155)
    msg[0] = 0x6E
    struct.pack_into("<IBB", msg, 8, user, 0, 1)
    for i, (song, pattern, score) in enumerate(stages):
        at = 14 + 47 * i
        struct.pack_into("<IB", msg, at, song, pattern)
        struct.pack_into("<I", msg, at + 7, score)
        struct.pack_into("<7H", msg, at + 15, 0, 43, 20, 0, 0, 1, 0)
    return bytes(msg)


class Cabinet:
    """One stand-in cabinet: online, keeping alive, a player's session every minute; it counts what went wrong."""

    def __init__(self, number, row, port, stats, source=None):
        self.number, self.row, self.port, self.stats = number, row, port, stats
        self.source = source or address(number)
        self.online, self.sent_at, self.logins = False, None, 0
        self.answered = asyncio.Event()
        self.answered_at = None

    async def run(self, until):
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", self.port, local_addr=(self.source, 0))
            self.client = StandInClient(reader, writer)
            answer = await self.client.handshake()
            if answer[8] != 1:
                self.stats["failures"].append("cabinet %d: handshake refused" % self.number)
                return
            # The client's online notice, as the real one sends it after 0x03.
            notice = bytearray(8)
            notice[0] = 0x5E
            self.client.write(bytes(notice))
            self.online = True
            reading = asyncio.ensure_future(self.read_loop())
            try:
                await self.write_loop(until)
            finally:
                reading.cancel()
                writer.close()
        except (OSError, asyncio.IncompleteReadError, asyncio.TimeoutError) as e:
            self.stats["failures"].append("cabinet %d: %s" % (self.number, e.__class__.__name__))
        finally:
            self.online = False

    async def read_loop(self):
        while True:
            msg = await read_any(self.client)
            kind = msg[0]
            if kind == 0x0B and self.sent_at is not None:
                # The keep-alive's answer: how long it took.
                self.stats["answers"].append(time.monotonic() - self.sent_at)
                self.sent_at = None
            elif kind == 0x06:
                # The server's ping: the real client answers 0x07.
                pong = bytearray(8)
                pong[0] = 0x07
                self.client.write(bytes(pong))
            elif kind == 0x64:
                # The login's result comes after the player's records and the player (0x1E, 0x5A..., 0x65); the
                # moment is noted here, where it is read (the session waiting for it runs only once the first places
                # after it are read too).
                self.answered_at = time.monotonic()
                self.stats["logins"] += 1 if msg[8] == messages.AUTH_OK else 0
                if msg[8] != messages.AUTH_OK:
                    self.stats["failures"].append("cabinet %d: login refused" % self.number)
                self.answered.set()
            elif kind not in ANSWER_TYPES:
                self.stats["failures"].append("cabinet %d: unexpected message 0x%02x" % (self.number, kind))

    async def write_loop(self, until):
        # Spread over the first keep-alive period, as cabinets switched on one by one.
        await asyncio.sleep(self.number % 11)
        next_alive = time.monotonic()
        next_session = time.monotonic() + (self.number * 7) % SESSION
        while time.monotonic() < until:
            now = time.monotonic()
            if now >= next_alive:
                if self.sent_at is not None:
                    self.stats["failures"].append("cabinet %d: a keep-alive went unanswered" % self.number)
                keep = bytearray(8)
                keep[0] = 0x0A
                self.sent_at = time.monotonic()
                self.client.write(bytes(keep))
                next_alive += KEEP_ALIVE
            if now >= next_session:
                await self.session()
                next_session += SESSION
            await self.client.writer.drain()
            await asyncio.sleep(0.2)

    async def session(self):
        """A player's session: the card, the whole answer, then three cleared stages."""
        card = bytearray(28)
        card[0] = 0x60
        card[8:8 + len(self.row["card"])] = self.row["card"].encode()
        self.answered.clear()
        sent = time.monotonic()
        self.client.write(bytes(card))
        await self.client.writer.drain()
        try:
            await asyncio.wait_for(self.answered.wait(), 5)
        except asyncio.TimeoutError:
            self.stats["failures"].append("cabinet %d: no answer to a card login" % self.number)
            return
        self.stats["login_ms"].append((self.answered_at - sent) * 1000)
        self.logins += 1
        score = 500000 + self.logins * 997 + self.number
        self.client.write(results(self.row["id"], [(1 + self.number % 5, 1, score), (7, 2, score // 2),
                                                   (12, 3, score // 3)]))


class BadCabinet:
    """A cabinet that does everything wrong, from an address of its own, again and again until `until`: garbage, a login
    whose answer it never reads, a message cut half way, a kind the game does not have. One link at a time."""

    def __init__(self, row, port):
        self.row, self.port = row, port
        self.rounds = 0

    async def link(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port, local_addr=(BAD_ADDRESS, 0))
        return StandInClient(reader, writer)

    async def run(self, until):
        rng = random.Random(4725)
        while time.monotonic() < until - 30:
            try:
                # Garbage at once.
                client = await self.link()
                client.writer.write(bytes(rng.randrange(256) for _ in range(2048)))
                await client.writer.drain()
                client.writer.close()
                # A login whose answer (thousands of first places) it never reads, held for 20 seconds.
                client = await self.link()
                await client.handshake()
                card = bytearray(28)
                card[0] = 0x60
                card[8:8 + len(self.row["card"])] = self.row["card"].encode()
                client.write(bytes(card))
                await client.writer.drain()
                await asyncio.sleep(20)
                client.writer.close()
                # Results cut half way, then the link gone.
                client = await self.link()
                await client.handshake()
                client.writer.write(client.write(results(self.row["id"], [(1, 1, 1)]), flush=False)[:40])
                await client.writer.drain()
                client.writer.close()
                # A kind of message the game does not have.
                client = await self.link()
                await client.handshake()
                odd = bytearray(8)
                odd[0] = 0xEE
                client.write(bytes(odd))
                await client.writer.drain()
                await asyncio.sleep(1)
                client.writer.close()
                self.rounds += 1
            except (OSError, asyncio.IncompleteReadError, asyncio.TimeoutError, AssertionError):
                # Refused or dropped, as it deserves: the next round.
                pass
            await asyncio.sleep(2)


async def refused_at_once(port, number):
    """One cabinet past the limit, from an address with room of its own (the server's limit refuses it, not the
    address's): the link closes before the server says anything (False when it does not)."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port, local_addr=(address(number), 0))
    try:
        return await asyncio.wait_for(reader.read(), 5) == b""
    except asyncio.TimeoutError:
        # Still open five seconds later: the server took it as one more cabinet.
        return False
    finally:
        writer.close()


async def watch(cabinets, stats, server, until, sample, lines):
    """One line every `sample` seconds: memory, cabinets online, the slowest keep-alive answer, failures so far."""
    start = time.monotonic()
    while time.monotonic() < until:
        await asyncio.sleep(min(sample, max(0.1, until - time.monotonic())))
        answers = stats["answers"][stats["seen"]:]
        stats["seen"] = len(stats["answers"])
        line = {"at": int(time.monotonic() - start), "rss_kib": rss_kib(server.pid),
                "online": sum(c.online for c in cabinets), "slowest": max(answers or [0.0]),
                "answers": len(answers), "logins": stats["logins"], "failures": len(stats["failures"])}
        stats["slowest"] = max(stats["slowest"], line["slowest"])
        lines.append(line)
        print("%5ds  memory %6.1f MB  online %3d  keep-alives %4d (slowest %.3f s)  logins %5d  failures %d"
              % (line["at"], line["rss_kib"] / 1024, line["online"], line["answers"], line["slowest"],
                 line["logins"], line["failures"]), flush=True)


async def drive(args, port, server):
    stats = {"answers": [], "failures": [], "logins": 0, "slowest": 0.0, "login_ms": [], "seen": 0}
    until = time.monotonic() + args.minutes * 60
    good = args.cabinets - (1 if args.bad else 0)
    cabinets = [Cabinet(i, args.rows[i], port, stats) for i in range(good)]
    runs = [asyncio.ensure_future(c.run(until)) for c in cabinets]
    # Everyone online first (the watch below says so if some never are), then one past the limit.
    for _ in range(300):
        if all(c.online for c in cabinets):
            break
        await asyncio.sleep(0.1)
    extra = None
    if args.cabinets >= MAX_CONNECTIONS and all(c.online for c in cabinets):
        # The bad cabinet's place filled by a quiet one meanwhile, so the server holds its most.
        filler = []
        for k in range(args.cabinets - good):
            reader, writer = await asyncio.open_connection("127.0.0.1", port, local_addr=(BAD_ADDRESS, 0))
            filler.append(writer)
        await asyncio.sleep(0.5)
        extra = await refused_at_once(port, args.cabinets + PER_ADDRESS)
        for writer in filler:
            writer.close()
        await asyncio.sleep(0.5)
    bad = None
    if args.bad:
        bad = BadCabinet(args.rows[good], port)
        runs.append(asyncio.ensure_future(bad.run(until)))
    lines = []
    await watch(cabinets, stats, server, until, args.sample, lines)
    await asyncio.gather(*runs)
    return stats, lines, extra, bad


# ------------------------------------------------------------------------------- the site's visitors and the program

def site_main(web, seconds, logins, pages, out):
    """--visitors: each login a visitor of its own (an address of its own: 127.0.0.20 and on) signed in on the site,
    asking for the pages in turn with THINK seconds between; each page's times (answers 200) and every status."""
    import httpx

    async def visitor(k, login, times, statuses, until):
        transport = httpx.AsyncHTTPTransport(local_address="127.0.0.%d" % (20 + k))
        async with httpx.AsyncClient(base_url=web, transport=transport, timeout=60) as client:
            page = (await client.get("/signin")).text
            token = page.split('name="csrf" value="', 1)[1].split('"', 1)[0]
            r = await client.post("/signin", data={"csrf": token, "login_id": login, "password": PASSWORD})
            statuses["signin %d" % r.status_code] = statuses.get("signin %d" % r.status_code, 0) + 1
            n = k
            while time.monotonic() < until:
                path = pages[n % len(pages)]
                started = time.monotonic()
                r = await client.get(path)
                took = time.monotonic() - started
                statuses[r.status_code] = statuses.get(r.status_code, 0) + 1
                if r.status_code == 200:
                    times.setdefault(path, []).append(took)
                n += 1
                await asyncio.sleep(THINK)

    async def main():
        until = time.monotonic() + seconds
        times, statuses = {}, {}
        await asyncio.gather(*[visitor(k, login, times, statuses, until) for k, login in enumerate(logins)])
        return times, statuses
    times, statuses = asyncio.run(main())
    with open(out, "w") as f:
        json.dump({"times": times, "statuses": {str(k): v for k, v in statuses.items()}}, f)


def hog_main(web, seconds, login, out):
    """--hog: an admin's token asking for every play as a file, HOG_AT_ONCE at a time without a pause, from an address
    of its own (127.0.0.60); every status and how long the answers took."""
    import httpx

    async def main():
        until = time.monotonic() + seconds
        statuses, took = {}, []
        transport = httpx.AsyncHTTPTransport(local_address="127.0.0.60")
        async with httpx.AsyncClient(base_url=web, transport=transport, timeout=120) as client:
            r = await client.post("/api/v1/session", json={"login_id": login, "password": PASSWORD})
            auth = {"Authorization": "Bearer " + r.json()["token"]}

            async def loop():
                while time.monotonic() < until:
                    started = time.monotonic()
                    r = await client.get("/api/v1/log/plays.csv", headers=auth)
                    statuses[r.status_code] = statuses.get(r.status_code, 0) + 1
                    took.append(time.monotonic() - started)
            await asyncio.gather(*[loop() for _ in range(HOG_AT_ONCE)])
        return statuses, took
    statuses, took = asyncio.run(main())
    with open(out, "w") as f:
        json.dump({"statuses": {str(k): v for k, v in statuses.items()}, "took": took}, f)


def helper(mode, *args):
    """This script again, as a process of its own (the visitors or the program: their own work never slows the
    cabinets' clock)."""
    return subprocess.Popen([sys.executable, os.path.abspath(__file__), mode] + [str(a) for a in args])


# ----------------------------------------------------------------------------------------------- the run

def prepare(data, args):
    """The players (the cabinets', the visitors', the program's admin, made with the server's own account code), then
    the made-up history; returns the rows of the cabinets' players, and the pages the visitors ask for."""
    store = accounts.Accounts(db.connect(os.path.join(data, "openDMT3.sqlite")))
    try:
        rows = [store.create("CAB%02d" % i, PASSWORD, "DJ %02d" % i) for i in range(args.cabinets)]
        visitors = [store.create("VIS%02d" % k, PASSWORD, "VIS %02d" % k)["login_id"] for k in range(args.site)]
        store.create("HOG", PASSWORD, "HOG", is_admin=True)
        secret = rows[0]["password"]
    finally:
        store.db.close()
    started = time.monotonic()
    plays = history.make(data, args.plays, args.players, secret) if args.plays else 0
    print("history: %d plays of %d players (%.1f s)" % (plays, args.players, time.monotonic() - started), flush=True)
    connection = db.connect(os.path.join(data, "openDMT3.sqlite"))
    try:
        newest = connection.execute("SELECT COALESCE(MAX(id), 0) FROM plays").fetchone()[0]
        ranked = [r[0] for r in connection.execute(
            "SELECT account_id FROM plays GROUP BY account_id ORDER BY COUNT(*) DESC LIMIT 201")]
        song = connection.execute("SELECT song FROM plays GROUP BY song ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
    finally:
        connection.close()
    pages = ["/", "/rankings", "/songs"]
    if song:
        pages.append("/songs/%d" % song[0])
    if ranked:
        pages += ["/dj/%d" % ranked[0], "/dj/%d" % ranked[-1]]
    return rows, visitors, pages, newest


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("--visitors", "--hog-worker"):
        # A helper process of a run (helper()).
        if sys.argv[1] == "--visitors":
            web, seconds, out, pages = sys.argv[2], float(sys.argv[3]), sys.argv[4], json.loads(sys.argv[5])
            site_main(web, seconds, json.loads(sys.argv[6]), pages, out)
        else:
            hog_main(sys.argv[2], float(sys.argv[3]), sys.argv[5], sys.argv[4])
        return 0
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cabinets", type=int, default=MAX_CONNECTIONS)
    parser.add_argument("--minutes", type=float, default=30)
    parser.add_argument("--sample", type=float, default=30)
    parser.add_argument("--plays", type=int, default=300000, help="the made-up history's plays (0: none)")
    parser.add_argument("--players", type=int, default=1000, help="the made-up history's players")
    parser.add_argument("--site", type=int, default=20, help="visitors on the site at the same time (0: none)")
    parser.add_argument("--no-hog", dest="hog", action="store_false", help="without the greedy program")
    parser.add_argument("--no-bad", dest="bad", action="store_false", help="without the bad cabinet")
    args = parser.parse_args()
    data = tempfile.mkdtemp(prefix="opendmt3-load-")
    try:
        args.rows, visitors, pages, newest = prepare(data, args)
        port, web = free_port(), free_port()
        log = open(os.path.join(data, "server.log"), "w")
        # The C library's memory in two pools for all the server's threads, as the server's image sets it
        # (packaging/docker/Dockerfile): its memory is measured as it runs there.
        server = subprocess.Popen([sys.executable, "-m", "opendmt3.server", "--data", data, "--host", "127.0.0.1",
                                   "--port", str(port), "--web-port", str(web)], stdout=log, stderr=subprocess.STDOUT,
                                  env=dict(os.environ, MALLOC_ARENA_MAX="2"))
        helpers = []
        try:
            for _ in range(300):
                # Both of its ports listening: the game's and the site's.
                if all(listening(p) for p in (port, web)):
                    break
                time.sleep(0.1)
            url = "http://127.0.0.1:%d" % web
            seconds = args.minutes * 60
            if args.site:
                helpers.append(helper("--visitors", url, seconds, os.path.join(data, "visitors.json"),
                                      json.dumps(pages), json.dumps(visitors)))
            if args.hog:
                helpers.append(helper("--hog-worker", url, seconds, os.path.join(data, "hog.json"), "HOG"))
            stats, lines, extra, bad = asyncio.run(drive(args, port, server))
            for process in helpers:
                process.wait(120)
        finally:
            for process in helpers:
                if process.poll() is None:
                    process.kill()
            server.send_signal(signal.SIGTERM)
            server.wait(20)
            log.close()
        problems = list(stats["failures"])
        if extra is False:
            problems.append("the cabinet past the limit was not refused at once")
        good = args.cabinets - (1 if args.bad else 0)
        if any(line["online"] != good for line in lines):
            problems.append("not every cabinet was online at every sample: %s" % [l["online"] for l in lines])
        if stats["slowest"] > ANSWER_LIMIT:
            problems.append("a keep-alive took %.3f s to be answered" % stats["slowest"])
        keep_p95 = percentile(stats["answers"], 0.95)
        if keep_p95 is not None and keep_p95 > KEEP_ALIVE_P95:
            problems.append("95 %% of the keep-alives within %.3f s (at most %.3f)" % (keep_p95, KEEP_ALIVE_P95))
        login_p50 = percentile(stats["login_ms"], 0.5)
        if login_p50 is not None and login_p50 > LOGIN_P50 * 1000:
            problems.append("half the logins within %.0f ms (at most %.0f)" % (login_p50, LOGIN_P50 * 1000))
        # Memory from a third of the run on (at least the first minute): the visitors' pages and the program's files
        # of every play fill the server's kept lists and the C library's pools in the first minutes (80 to 91 MB in
        # the first 12 of 30, then flat for 18); a leak grows on after that.
        warm = [line for line in lines if line["at"] >= max(60, args.minutes * 20)]
        if len(warm) >= 2:
            first, last = warm[0]["rss_kib"], warm[-1]["rss_kib"]
            if last - first > max(first * 0.10, 8 * 1024):
                problems.append("the server's memory grew from %.1f MB to %.1f MB" % (first / 1024, last / 1024))
        with open(os.path.join(data, "server.log")) as f:
            errors = [l.rstrip() for l in f if " ERROR " in l or "Traceback" in l]
        problems += ["server log: " + e for e in errors[:5]]
        # The sessions' stages, as the server kept them (the history's aside): three a session, but for each cabinet's
        # last session, whose results may have been on their way when the run ended.
        connection = db.connect(os.path.join(data, "openDMT3.sqlite"))
        kept = connection.execute("SELECT COUNT(*) FROM plays WHERE id > ?", (newest,)).fetchone()[0]
        connection.close()
        if not 3 * (stats["logins"] - good) <= kept <= 3 * stats["logins"]:
            problems.append("%d stages kept for %d sessions" % (kept, stats["logins"]))
        site_line = ""
        if args.site:
            with open(os.path.join(data, "visitors.json")) as f:
                visited = json.load(f)
            refused = {k: v for k, v in visited["statuses"].items() if k not in ("200", "signin 303")}
            if refused:
                problems.append("the visitors got %s" % refused)
            worst = []
            for path, times in sorted(visited["times"].items()):
                p95 = percentile(times, 0.95)
                worst.append("%s p50 %.0f p95 %.0f ms" % (path, percentile(times, 0.5) * 1000, p95 * 1000))
                if p95 > SITE_P95:
                    problems.append("95 %% of %s within %.3f s (at most %.3f)" % (path, p95, SITE_P95))
            site_line = "; ".join(worst)
        hog_line = ""
        if args.hog:
            with open(os.path.join(data, "hog.json")) as f:
                hog = json.load(f)
            hog_line = "the program's calls: %s" % hog["statuses"]
            # Its share is one call answered at a time (the others wait their turn) and its seconds a minute: the
            # visitors' pages and the cabinets above show it took no more. Here: every call answered (none failed),
            # past its seconds with 429 and Retry-After, and it was served all along (at least one call a minute).
            failed = {k: v for k, v in hog["statuses"].items() if k not in ("200", "429")}
            if failed or hog["statuses"].get("200", 0) < args.minutes:
                problems.append("the program's calls: %s" % hog["statuses"])
        login_p95 = percentile(stats["login_ms"], 0.95)
        print("%d cabinets, %.0f minutes on %d plays: %d samples, %d logins (p50 %s ms, p95 %s ms), %d stages kept, "
              "keep-alive p95 %s ms, slowest %.3f s, the one past the limit %s%s"
              % (args.cabinets, args.minutes, newest, len(lines), stats["logins"],
                 "%.0f" % login_p50 if login_p50 is not None else "-",
                 "%.0f" % login_p95 if login_p95 is not None else "-", kept,
                 "%.1f" % (keep_p95 * 1000) if keep_p95 is not None else "-", stats["slowest"],
                 {True: "refused at once", False: "NOT refused", None: "not tried"}[extra],
                 ", the bad cabinet's rounds %d" % bad.rounds if bad else ""))
        if site_line:
            print("site, %d visitors: %s" % (args.site, site_line))
        if hog_line:
            print(hog_line)
        for problem in problems[:20]:
            print("  problem: " + problem)
        print("PASS" if not problems else "FAIL: %d problems" % len(problems))
        return 0 if not problems else 1
    finally:
        shutil.rmtree(data, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
