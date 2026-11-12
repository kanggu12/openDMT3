"""Tests for the game server's link layer: the cipher, cutting the stream, the handshake, keeping alive.

A stand-in client speaks the client's side as the real one does (it was proven against the real client in
Wine; tests/e2e/windows/net_green.sh repeats that proof with this code). No game file is used.
"""

import asyncio
import random
import struct
import unittest

import json
import os
import shutil
import tempfile

from opendmt3.server import db
from opendmt3.server import connection, crypto, messages
from opendmt3.server.server import GameServer
from opendmt3.server.services import accounts, records


class LoopTest(unittest.IsolatedAsyncioTestCase):
    """A test on its own event loop, as the server runs its loop on Windows too (tests/server/test_concurrency.py)."""

    async def asyncSetUp(self):
        if os.name == "nt":
            # Without the debug mode IsolatedAsyncioTestCase turns on: on Windows that mode stats every source file
            # at every callback (3.5 ms a stat under Wine), which the tests' deadlines would measure instead of the
            # server. Linux keeps the mode and its checks.
            asyncio.get_running_loop().set_debug(False)


class CryptoTest(unittest.TestCase):
    def test_table_is_the_standard_crc32_one(self):
        # The first words every CRC-32 implementation has; the client's table matched them in the proof.
        self.assertEqual((crypto.TABLE[1], crypto.TABLE[2], crypto.TABLE[255]), (0x77073096, 0xEE0E612C, 0x2D02EF8D))

    def test_round_trip_for_every_size_the_game_uses(self):
        rng = random.Random(1)
        for size in sorted(set(messages.TO_CLIENT.values()) | set(messages.TO_SERVER.values())):
            data = bytes(rng.randrange(256) for _ in range(size))
            state = rng.getrandbits(32)
            self.assertEqual(crypto.decrypt(crypto.encrypt(data, state), state), data, size)
            # The encrypted form must differ (a cipher that does nothing would pass the round trip).
            self.assertNotEqual(crypto.encrypt(data, state), data)

    def test_blocks_are_independent(self):
        # The server decrypts the first 8 bytes alone to read the header; that only works block by block.
        data = bytes(range(48))
        self.assertEqual(crypto.decrypt(crypto.encrypt(data, 9)[:8], 9), data[:8])

    def test_a_batch_encrypts_to_the_same_bytes_as_one_message_at_a_time(self):
        # encrypt_many (a card login's thousands of messages at once, off the loop) gives exactly what encrypt gives
        # message by message with the state moving on after each, for every size the game takes, in any mix.
        rng = random.Random(2)
        sizes = sorted(set(messages.TO_CLIENT.values()))
        for trial in range(100):
            batch = [bytes(rng.randrange(256) for _ in range(rng.choice(sizes))) for _ in range(rng.randint(0, 30))]
            state = rng.getrandbits(32)
            one, after = [], state
            for msg in batch:
                one.append(crypto.encrypt(msg, after))
                after = crypto.next_server_state(after)
            self.assertEqual(crypto.encrypt_many(batch, state), (b"".join(one), after), "trial %d" % trial)


class BatchTest(LoopTest):
    """A login's batch (Connection.send_all) and a message sent while it is encrypted (the server's ping)."""

    async def test_a_ping_sent_during_a_batch_goes_after_it_in_the_cipher_states_order(self):
        from opendmt3.server import connection as link

        class Writer:
            # What the link writes, kept in order.
            def __init__(self):
                self.data = bytearray()

            def get_extra_info(self, name):
                return ("203.0.113.9", 4000)

            def write(self, data):
                self.data += data

            async def drain(self):
                # Every byte taken at once, as a client that reads would.
                return None

            def is_closing(self):
                # The link is open all the while.
                return False
        writer = Writer()
        conn = link.Connection(server=None, reader=None, writer=writer, rng=random.Random(3))
        conn.to_client = 12345
        batch = [messages.best_record(0, n, 1, 1000 + n, "DJ") for n in range(2000)]
        sending = asyncio.ensure_future(conn.send_all(batch))
        # The batch is on its worker thread: a ping now waits for it.
        await asyncio.sleep(0)
        conn.send(messages.ping())
        await sending
        # The client reads every message in order with the states moving on: the batch, then the ping.
        state, at, kinds = 12345, 0, []
        data = bytes(writer.data)
        while at < len(data):
            kind = crypto.decrypt(data[at:at + 8], state)[0]
            size = messages.TO_CLIENT[kind]
            whole = crypto.decrypt(data[at:at + size], state)
            kinds.append(whole[0])
            state = crypto.next_server_state(state)
            at += size
        self.assertEqual(kinds, [0x5F] * 2000 + [0x06])
        self.assertEqual(conn.to_client, state)


class StandInClient:
    """The client's side of the link, as the real client does it."""

    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer
        self.to_server = 0
        self.to_client = 0

    async def read(self, size):
        data = await asyncio.wait_for(self.reader.readexactly(size), 5)
        msg = crypto.decrypt(data, self.to_client)
        self.to_client = crypto.next_server_state(self.to_client)
        return msg

    def write(self, msg, flush=True):
        out = crypto.encrypt(msg, self.to_server)
        self.to_server = crypto.next_client_state(self.to_server)
        if flush:
            self.writer.write(out)
        return out

    async def hello(self):
        """Read the server's 0x01 and restart both states from its seed; returns the two table places asked for."""
        raw = await asyncio.wait_for(self.reader.readexactly(14), 5)
        request = crypto.decrypt(raw, 0)
        assert request[0] == 0x01
        seed = struct.unpack_from("<I", request, 8)[0]
        # The client resets both directions from the seed before it answers.
        self.to_client = crypto.next_server_state(seed)
        self.to_server = crypto.next_client_state(seed)
        return request[12], request[13]

    async def handshake(self, version="1.2.3.4", table=crypto.TABLE, split=False, asked=None):
        i0, i1 = asked or await self.hello()
        answer = bytearray(48)
        answer[0] = 0x02
        struct.pack_into("<III", answer, 8, 0, table[i0], table[i1])
        mask = ((table[i1] << 7) | table[i0]) & 0xFFFFFFFFFFFFFFFF
        struct.pack_into("<Q", answer, 20, 0x1122334455667788 ^ mask)
        answer[28:28 + len(version)] = version.encode()
        data = self.write(bytes(answer), flush=False)
        if split:
            # Arrives in two pieces, as TCP may deliver it.
            self.writer.write(data[:5])
            await self.writer.drain()
            await asyncio.sleep(0.05)
            self.writer.write(data[5:])
        else:
            self.writer.write(data)
        await self.writer.drain()
        return await self.read(61)


class ServerTest(LoopTest):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.server = await GameServer("127.0.0.1", 0, rng=random.Random(5)).start()

    async def asyncTearDown(self):
        await self.server.close()

    async def connect(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.server.port)
        self.addAsyncCleanup(self._close, writer)
        return StandInClient(reader, writer)

    @staticmethod
    async def _close(writer):
        writer.close()

    async def test_handshake_puts_the_client_online(self):
        client = await self.connect()
        result = await client.handshake()
        self.assertEqual((result[0], result[8]), (0x03, 1))
        conn = next(iter(self.server.connections))
        self.assertTrue(conn.online)
        self.assertEqual((conn.answer.version, conn.answer.machine_key), ("1.2.3.4", 0x1122334455667788))

    async def test_a_split_answer_still_works(self):
        client = await self.connect()
        result = await client.handshake(split=True)
        self.assertEqual(result[8], 1)

    async def test_alive_is_answered_and_messages_in_one_write_are_all_read(self):
        client = await self.connect()
        await client.handshake()
        # The online notice and a keep-alive arrive together; both must be cut out and handled.
        notice, keep = bytearray(8), bytearray(8)
        notice[0], keep[0] = 0x5E, 0x0A
        client.writer.write(client.write(bytes(notice), flush=False) + client.write(bytes(keep), flush=False))
        await client.writer.drain()
        ack = await client.read(8)
        self.assertEqual(ack[0], 0x0B)

    async def test_ping_once_online(self):
        connection.PING_EVERY, saved = 0.1, connection.PING_EVERY
        self.addCleanup(setattr, connection, "PING_EVERY", saved)
        client = await self.connect()
        await client.handshake()
        ping = await client.read(8)
        self.assertEqual(ping[0], 0x06)

    async def test_wrong_table_words_are_refused(self):
        client = await self.connect()
        other = [w ^ 1 for w in crypto.TABLE]
        result = await client.handshake(table=other)
        self.assertEqual(result[8], 0)
        # Refused, then the link ends: no second answer on the same connection.
        rest = await asyncio.wait_for(client.reader.read(), 5)
        self.assertEqual(rest, b"")
        self.assertEqual(self.server.connections, set())

    async def test_a_flood_ends_the_link_and_reconnecting_does_not_refill_the_budget(self):
        # This test's budget: the link itself and its handshake, and 100 bytes more.
        budget = connection.LINK_BYTES + 48 + 100
        connection.BYTES_PER_MINUTE, saved = budget, connection.BYTES_PER_MINUTE
        self.addCleanup(setattr, connection, "BYTES_PER_MINUTE", saved)
        client = await self.connect()
        await client.handshake()
        keep = bytearray(8)
        keep[0] = 0x0A
        # 160 bytes in a moment: past the 100 left of the budget.
        client.writer.write(b"".join(client.write(bytes(keep), flush=False) for _ in range(20)))
        await client.writer.drain()
        await asyncio.wait_for(client.reader.read(), 5)
        self.assertEqual(self.server.connections, set())
        # The same address on a new link: the budget is the address's, so the link is closed before the handshake.
        again = await self.connect()
        self.assertEqual(await asyncio.wait_for(again.reader.read(), 5), b"")

    async def test_connections_past_the_limit_are_closed_at_once(self):
        from opendmt3.server import server as server_module
        server_module.MAX_CONNECTIONS, saved = 1, server_module.MAX_CONNECTIONS
        self.addCleanup(setattr, server_module, "MAX_CONNECTIONS", saved)
        first = await self.connect()
        await first.handshake()
        second = await self.connect()
        # No handshake request: the link is closed before anything is sent.
        self.assertEqual(await asyncio.wait_for(second.reader.read(), 5), b"")

    async def test_one_address_holds_at_most_its_share_of_links(self):
        from opendmt3.server import server as server_module
        # Links that never answer the handshake, all from 127.0.0.1: the address's share, then no more.
        idle = [await self.connect() for _ in range(server_module.PER_ADDRESS)]
        for client in idle:
            await client.hello()
        extra = await self.connect()
        self.assertEqual(await asyncio.wait_for(extra.reader.read(), 5), b"")
        # A cabinet at another address still gets online (Linux answers on all of 127.0.0.0/8).
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", self.server.port, local_addr=("127.0.0.2", 0))
        except OSError:
            self.skipTest("this system has no 127.0.0.2")
        self.addAsyncCleanup(self._close, writer)
        result = await StandInClient(reader, writer).handshake()
        self.assertEqual(result[8], 1)

    async def test_a_link_without_a_handshake_answer_is_closed_at_the_deadline(self):
        connection.HANDSHAKE_LIMIT, saved = 0.3, connection.HANDSHAKE_LIMIT
        self.addCleanup(setattr, connection, "HANDSHAKE_LIMIT", saved)
        client = await self.connect()
        await client.hello()
        # A byte now and then before the answer does not hold the place either.
        for _ in range(3):
            client.writer.write(b"\0")
            try:
                await client.writer.drain()
            except ConnectionResetError:
                # The deadline came first (a busy machine's sleeps run long): Windows says a write after the server
                # closed as a reset, which is the end this test waits for.
                break
            await asyncio.sleep(0.1)
        try:
            rest = await asyncio.wait_for(client.reader.read(), 5)
        except ConnectionResetError:
            # The same end, as Windows says it to a reader whose last write met a closed link.
            rest = b""
        self.assertEqual(rest, b"")
        self.assertEqual(self.server.connections, set())

    async def test_bytes_now_and_then_do_not_keep_an_online_link(self):
        connection.IDLE_LIMIT, saved = 0.5, connection.IDLE_LIMIT
        self.addCleanup(setattr, connection, "IDLE_LIMIT", saved)
        client = await self.connect()
        await client.handshake()
        keep = bytearray(8)
        keep[0] = 0x0A
        data = client.write(bytes(keep), flush=False)
        # One byte of a keep-alive every 0.2 s: never a whole message, so the link ends after the idle limit.
        started = asyncio.get_running_loop().time()
        for i in range(len(data)):
            client.writer.write(data[i:i + 1])
            await client.writer.drain()
            await asyncio.sleep(0.2)
            if client.reader.at_eof():
                break
        self.assertEqual(await asyncio.wait_for(client.reader.read(), 5), b"")
        self.assertLess(asyncio.get_running_loop().time() - started, 1.5)

    async def test_an_unknown_header_ends_the_link(self):
        client = await self.connect()
        await client.handshake()
        junk = bytearray(8)
        junk[0] = 0xEE
        client.write(bytes(junk))
        await client.writer.drain()
        # The server cannot know where the next message starts, so it closes; the client sees the end.
        rest = await asyncio.wait_for(client.reader.read(), 5)
        self.assertEqual(rest, b"")


class BeforeTheHandshakeTest(LoopTest):
    """Nothing a client sends before its handshake answer counts, a login least of all."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.tmp = tempfile.mkdtemp()
        self.db = db.connect(os.path.join(self.tmp, "server.sqlite"))
        self.accounts = accounts.Accounts(self.db)
        self.row = self.accounts.create("NOVA", "pass1234", "DJ NOVA")
        self.server = await GameServer("127.0.0.1", 0, rng=random.Random(5), accounts=self.accounts).start()

    async def asyncTearDown(self):
        await self.server.close()
        self.db.close()
        shutil.rmtree(self.tmp)

    async def test_a_card_before_the_answer_is_ignored(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.server.port)
        self.addAsyncCleanup(ServerTest._close, writer)
        client = StandInClient(reader, writer)
        asked = await client.hello()
        card = bytearray(28)
        card[0] = 0x60
        card[8:28] = self.row["card"].encode()
        client.write(bytes(card))
        await writer.drain()
        # The next thing the server sends is the handshake's result, not a login.
        result = await client.handshake(asked=asked)
        self.assertEqual((result[0], result[8]), (0x03, 1))
        self.assertIsNone(next(iter(self.server.connections)).player)


class CardLoginTest(LoopTest):
    """The card login as the game does it with openDMT3's card reader: 0x60 with the card number."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.tmp = tempfile.mkdtemp()
        self.db = db.connect(os.path.join(self.tmp, "server.sqlite"))
        self.accounts = accounts.Accounts(self.db)
        self.row = self.accounts.create("NOVA", "pass1234", "DJ NOVA")
        self.records = records.Records(self.db)
        self.server = await GameServer("127.0.0.1", 0, rng=random.Random(5), accounts=self.accounts,
                                       records=self.records).start()
        reader, writer = await asyncio.open_connection("127.0.0.1", self.server.port)
        self.client = StandInClient(reader, writer)
        await self.client.handshake()

    async def asyncTearDown(self):
        self.client.writer.close()
        await self.server.close()
        self.db.close()
        shutil.rmtree(self.tmp)

    async def card(self, number):
        msg = bytearray(28)
        msg[0] = 0x60
        msg[8:8 + len(number)] = number.encode()
        self.client.write(bytes(msg))
        await self.client.writer.drain()

    async def login_answer(self, mine=0, firsts=0):
        """The whole answer to a card the server knows, in the game's order: the player's records (0x1e, then
        `mine` 0x5A lines), the player (0x65), the result (0x64), the first places (0x66, then `firsts` 0x5F)."""
        answer = {"clear": await self.client.read(8)}
        answer["mine"] = [await self.client.read(23) for _ in range(mine)]
        answer["info"] = await self.client.read(166)
        answer["result"] = await self.client.read(9)
        answer["clear_bests"] = await self.client.read(8)
        answer["firsts"] = [await self.client.read(39) for _ in range(firsts)]
        return answer

    async def test_a_known_card_logs_in_with_the_dj_name(self):
        await self.card(self.row["card"])
        answer = await self.login_answer()
        self.assertEqual((answer["clear"][0], answer["clear_bests"][0]), (0x1E, 0x66))
        info = answer["info"]
        self.assertEqual(info[0], 0x65)
        self.assertEqual(struct.unpack_from("<I", info, 8)[0], self.row["id"])
        # The DJ name in the game's wide characters, ending in a zero, where the game reads it (offset 20).
        self.assertEqual(info[20:20 + 18].decode("utf-16-le").rstrip("\0"), "DJ NOVA")
        self.assertEqual(info[12:20], bytes(8))
        # A new card: the basic icon, the Platinum Crew plate, no comment (its letters' style stays clear).
        self.assertEqual(struct.unpack_from("<III", info, 42), (1, 0x00008001, 0))
        result = answer["result"]
        self.assertEqual((result[0], result[8]), (0x64, messages.AUTH_OK))
        self.assertEqual(next(iter(self.server.connections)).player, "NOVA")

    async def test_the_song_select_gets_the_players_bests_and_the_servers_first_places(self):
        rio = self.accounts.create("RIO", "pass1234", "RIO")
        stage = lambda song, pattern, score: {"song": song, "pattern": pattern, "score": score, "counts": [0] * 7,
                                              "raw": bytes(47)}
        # NOVA: two plays of one chart (the better counts) and a POP chart; RIO: first on the STAR chart.
        self.records.add(self.row["id"], "x", 0, stage(56, 1, 4000))
        self.records.add(self.row["id"], "x", 0, stage(56, 1, 4530))
        self.records.add(self.row["id"], "x", 1, stage(12, 2, 99000))
        self.records.add(rio["id"], "x", 0, stage(56, 1, 5000))
        await self.card(self.row["card"])
        answer = await self.login_answer(mine=2, firsts=2)
        mine = sorted(struct.unpack_from("<BIBBII", m, 8) for m in answer["mine"])
        # mode, song, pattern, trophy (none: not read from the results), score, max combo (not read either).
        self.assertEqual(mine, [(0, 56, 1, 0, 4530, 0), (1, 12, 2, 0, 99000, 0)])
        firsts = sorted((struct.unpack_from("<IIBI", m, 8), m[21:39].decode("utf-16-le").rstrip("\0"))
                        for m in answer["firsts"])
        self.assertEqual(firsts, [((0, 56, 1, 5000), "RIO"), ((1, 12, 2, 99000), "DJ NOVA")])
        self.assertTrue(all(m[0] == 0x5A for m in answer["mine"]) and all(m[0] == 0x5F for m in answer["firsts"]))

    async def test_the_dj_card_shows_the_players_choices_and_level(self):
        from opendmt3.server.services import cards
        # Tables as the game's (read from its files): two icons, two plates, patterns 0 and 7, and experience.
        with open(os.path.join(self.tmp, cards.FILE), "w") as f:
            json.dump({"icon": [{"number": 1}, {"number": 6}], "plate": [{"number": 32768}, {"number": 32769}],
                       "pattern": [{"number": 0}, {"number": 7}], "points": {"1": 9, "2": 9},
                       "levels": [12, 42, 92]}, f)
        self.server.data = self.tmp
        self.db.execute("UPDATE accounts SET icon = 6, plate = 32768, pattern = 7, comment = ? WHERE id = ?",
                        ("한글ABCDEFGHIJ", self.row["id"]))
        for _ in range(3):
            self.records.add(self.row["id"], "x", 0, {"song": 56, "pattern": 1, "score": 1, "counts": [0] * 7,
                                                      "raw": bytes(47)})
        await self.card(self.row["card"])
        info = (await self.login_answer(mine=1, firsts=1))["info"]
        # Three stages of a chart of unknown level (no song list): level 1's 9 points each.
        self.assertEqual(struct.unpack_from("<I", info, messages.EXP_AT)[0], 27)
        self.assertEqual(struct.unpack_from("<II", info, messages.ICON_AT), (6, (7 << 16) | 32768))
        # White letters, all twelve places used (the note skin after them is zero).
        self.assertEqual(struct.unpack_from("<I", info, messages.COMMENT_STYLE_AT)[0], 1)
        self.assertEqual(info[54:78].decode("utf-16-le"), "한글ABCDEFGHIJ")
        self.assertEqual(info[78:82], bytes(4))
        # A choice the tables no longer have goes out as the default, never as a number the game may not have.
        self.db.execute("UPDATE accounts SET icon = 200 WHERE id = ?", (self.row["id"],))
        await self.card(self.row["card"])
        info = (await self.login_answer(mine=1, firsts=1))["info"]
        self.assertEqual(struct.unpack_from("<I", info, messages.ICON_AT)[0], cards.ICON)

    def results(self, songs):
        """A 0x6e like the game's: user, mode 0 (STAR), cleared, then a 47-byte record per cleared stage."""
        msg = bytearray(155)
        msg[0] = 0x6E
        struct.pack_into("<IBB", msg, 8, self.row["id"], 0, 1)
        for i, (song, pattern, score) in enumerate(songs):
            at = 14 + 47 * i
            struct.pack_into("<IB", msg, at, song, pattern)
            struct.pack_into("<I", msg, at + 7, score)
            struct.pack_into("<7H", msg, at + 15, 0, 43, 20, 0, 0, 1, 0)
        return bytes(msg)

    async def test_cleared_stages_are_kept_for_the_logged_in_player(self):
        await self.card(self.row["card"])
        await self.login_answer()
        self.client.write(self.results([(56, 1, 4530), (12, 2, 99000)]))
        await self.client.writer.drain()
        # The server keeps them without answering; give it a moment to read.
        for _ in range(50):
            if len(self.records.recent(self.row["id"])) == 2:
                break
            await asyncio.sleep(0.02)
        plays = self.records.recent(self.row["id"])
        self.assertEqual(sorted((p["song"], p["pattern"], p["score"]) for p in plays), [(12, 2, 99000), (56, 1, 4530)])
        self.assertEqual(plays[0]["counts"], "0,43,20,0,0,1,0")
        self.assertEqual(len(bytes(plays[0]["record"])), 47)

    async def test_a_guests_results_are_not_kept(self):
        self.client.write(self.results([(56, 1, 4530)]))
        await self.client.writer.drain()
        await asyncio.sleep(0.2)
        self.assertEqual(self.records.recent(), [])

    async def test_results_of_an_account_disabled_after_its_login_are_not_kept(self):
        await self.card(self.row["card"])
        await self.login_answer()
        self.accounts.set_disabled("NOVA", True)
        self.client.write(self.results([(56, 1, 4530)]))
        await self.client.writer.drain()
        await asyncio.sleep(0.2)
        self.assertEqual(self.records.recent(), [])

    async def test_a_login_opens_a_session_that_the_link_closes(self):
        from opendmt3.server.services import activity
        self.server.activity = activity.Activity(self.db)
        # The cabinet as the handshake saw it (this test's server got its activity after the handshake).
        self.server.activity.seen("127.0.0.1", "test", "127.0.0.1:1")
        await self.card(self.row["card"])
        await self.login_answer()
        self.client.write(self.results([(56, 1, 4530)]))
        await self.client.writer.drain()
        conn = next(iter(self.server.connections))
        # Until the server has handled the results: the play is kept on the database's thread first, and the link's
        # session is let go after (the play alone can be seen before that on a busy PC).
        for _ in range(250):
            if self.records.recent(self.row["id"]) and conn.session is None:
                break
            await asyncio.sleep(0.02)
        play = self.db.execute("SELECT session_id FROM plays").fetchone()
        self.assertIsNotNone(play[0])
        # The results end the session (the credit is over), though the cabinet stays connected.
        ended = self.db.execute("SELECT ended_at FROM sessions WHERE id = ?", (play[0],)).fetchone()[0]
        self.assertIsNotNone(ended)
        self.assertIsNone(conn.session)
        # A second card on the same link opens a new session, which the link's end closes.
        await self.card(self.row["card"])
        await self.login_answer(mine=1, firsts=1)
        second = conn.session
        self.assertNotEqual(second, play[0])
        self.client.writer.close()

        def ended():
            return self.db.execute("SELECT ended_at FROM sessions WHERE id = ?", (second,)).fetchone()[0]
        # Until the link is gone and its session's end written (on the database's thread, after the link is let go).
        for _ in range(250):
            if not self.server.connections and ended() is not None:
                break
            await asyncio.sleep(0.02)
        self.assertIsNotNone(ended())
        # The admin's log kept the messages, and no card number: the card login has a handler, so no bytes.
        kept = list(self.server.messages)
        login = [m for m in kept if m["header"] == 0x60]
        self.assertEqual(len(login), 2)
        self.assertEqual([m["bytes"] for m in login], ["", ""])
        self.assertFalse(any(self.row["card"] in str(m) for m in kept))

    async def test_taking_first_place_from_someone_else_tells_the_webhook(self):
        from opendmt3.server.services import notify
        said = []
        self.server.webhook = notify.Webhook("http://127.0.0.1:9/unused", self.tmp, post=said.append)
        rio = self.accounts.create("RIO", "pass1234", "RIO")
        self.records.add(rio["id"], "198.51.100.7:1", 0, {"song": 56, "pattern": 1, "score": 4000, "counts": [0] * 7,
                                                          "raw": bytes(47)})
        await self.card(self.row["card"])
        await self.login_answer(mine=0, firsts=1)
        # NOVA: song 56 above RIO's 4000 (told), song 12 a first clear (not told).
        self.client.write(self.results([(56, 1, 4530), (12, 2, 99000)]))
        await self.client.writer.drain()
        # Until the server has told what it tells: the plays are kept on the database's thread first, and the lines
        # for the whole message go out together after (the plays alone can be seen before them on a busy PC).
        for _ in range(250):
            if said:
                break
            await asyncio.sleep(0.02)
        self.assertEqual(said, ["DJ NOVA took first place on #56 (STAR · Pattern 1) with 4,530, ahead of RIO."])

    async def test_the_log_never_shows_a_whole_card_number(self):
        with self.assertLogs("opendmt3.server", level="INFO") as logs:
            await self.card("12345678901234567890")
            await self.client.read(9)
        self.assertFalse(any("12345678901234567890" in line for line in logs.output))
        self.assertTrue(any("refused: an unknown card" in line and "card ...7890" in line for line in logs.output))

    async def test_wrong_cards_are_logged_once_a_minute_per_address(self):
        clock = [1000.0]
        self.server.refusals.clock = lambda: clock[0]
        with self.assertLogs("opendmt3.server", level="INFO") as logs:
            for n in range(20):
                await self.card("%020d" % n)
                await self.client.read(9)
            # The minute ends: one more line, with how many more there were.
            clock[0] += 61
            self.server.refusals.flush()
        refused = [line for line in logs.output if "refused" in line]
        self.assertEqual(len(refused), 2, refused)
        self.assertIn("refused 19 more times in a minute: an unknown card (19)", refused[1])

    async def test_a_login_message_is_kept_without_its_bytes(self):
        # 0x62 has no handler yet and carries a card number: the admin's log and --verbose show neither.
        join = bytearray(messages.TO_SERVER[0x62])
        join[0] = 0x62
        join[8:28] = self.row["card"].encode()
        with self.assertLogs("opendmt3.server", level="DEBUG") as logs:
            self.client.write(bytes(join))
            await self.client.writer.drain()
            for _ in range(50):
                if any(m["header"] == 0x62 for m in self.server.messages):
                    break
                await asyncio.sleep(0.02)
        kept = [m for m in self.server.messages if m["header"] == 0x62]
        self.assertEqual([m["bytes"] for m in kept], [""])
        self.assertFalse(any(self.row["card"] in line or self.row["card"].encode().hex() in line
                             for line in logs.output))

    def catalog(self, numbers):
        """A song list with these song numbers, as --catalog leaves it, read by this test's server."""
        with open(os.path.join(self.tmp, "catalog.json"), "w") as f:
            json.dump({"songs": [{"number": n, "title": "#%d" % n} for n in numbers]}, f)
        self.server.data = self.tmp

    def forged(self, i, mode=0, songs=None):
        """A 0x6e as exp3 of the review sent: any mode, made-up songs, the highest score there is."""
        msg = bytearray(155)
        msg[0] = 0x6E
        struct.pack_into("<IBB", msg, 8, self.row["id"], mode, 1)
        for k, (song, pattern) in enumerate(songs or [(1_000_000 + 3 * i + k, 1 + k % 4) for k in range(3)]):
            at = 14 + 47 * k
            struct.pack_into("<IB", msg, at, song, pattern)
            struct.pack_into("<I", msg, at + 7, 0xFFFFFFFF)
        return bytes(msg)

    async def settle(self):
        """Wait until the server read everything sent (a keep-alive's answer comes after it) and did what it asked of
        the database: a link's handlers that wait for it run apart from its reading (Connection.queue), so the
        keep-alive is answered first."""
        keep = bytearray(8)
        keep[0] = 0x0A
        self.client.write(bytes(keep))
        await self.client.writer.drain()
        while (await self.client.read(8))[0] != 0x0B:
            pass
        for conn in list(self.server.connections):
            await conn.finish()

    async def test_forged_results_stop_at_eight_stages_a_login(self):
        await self.card(self.row["card"])
        await self.login_answer()
        with self.assertLogs("opendmt3.server", level="INFO") as logs:
            # The review's attack: hundreds of results on one login, every mode the game has, the top score.
            for i in range(200):
                self.client.write(self.forged(i, mode=i % 5), flush=True)
            await self.client.writer.drain()
            await self.settle()
        count = self.db.execute("SELECT COUNT(*) FROM plays").fetchone()[0]
        self.assertEqual(count, 8)
        # One line says results were not kept, not one a message.
        self.assertEqual(sum("results not kept" in line for line in logs.output), 1)
        # A new card login (the next credit) keeps its own stages. Its answer: the six of the eight in STAR and POP
        # (the modes the game keeps a player's records for), and all eight as first places.
        await self.card(self.row["card"])
        await self.login_answer(mine=6, firsts=8)
        self.client.write(self.results([(56, 1, 4530)]))
        await self.settle()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM plays").fetchone()[0], 9)

    async def test_results_the_game_cannot_send_are_not_kept(self):
        self.catalog([56, 12])
        await self.card(self.row["card"])
        await self.login_answer()
        # A mode the game does not have, patterns outside its four, songs not in the song list.
        self.client.write(self.forged(0, mode=5, songs=[(56, 1)]))
        self.client.write(self.forged(1, songs=[(56, 0), (56, 5), (56, 255)]))
        self.client.write(self.forged(2, songs=[(77, 1), (1_000_000, 2)]))
        # And one stage that is right, in the same message as one that is not.
        self.client.write(self.forged(3, mode=1, songs=[(12, 2), (99, 1)]))
        await self.settle()
        plays = [tuple(p) for p in self.db.execute("SELECT mode, song, pattern FROM plays")]
        self.assertEqual(plays, [(1, 12, 2)])

    async def test_first_places_go_out_only_for_songs_in_the_song_list(self):
        stage = lambda song: {"song": song, "pattern": 1, "score": 5000, "counts": [0] * 7, "raw": bytes(47)}
        # Plays from before the server checked results: one on a song the list has, one on a song it does not.
        self.records.add(self.row["id"], "x", 0, stage(56))
        self.records.add(self.row["id"], "x", 0, stage(1_000_000))
        self.catalog([56])
        await self.card(self.row["card"])
        answer = await self.login_answer(mine=1, firsts=1)
        self.assertEqual(struct.unpack_from("<I", answer["firsts"][0], 12)[0], 56)
        self.assertEqual(struct.unpack_from("<I", answer["mine"][0], 9)[0], 56)
        # Nothing else came: the next message is the keep-alive's answer.
        await self.settle()

    async def test_maintenance_refuses_card_logins_and_keeps_the_cabinets_online(self):
        from opendmt3.server.services import maintenance
        self.server.data = self.tmp
        # A player logged in before maintenance began goes on playing.
        await self.card(self.row["card"])
        await self.login_answer()
        maintenance.write(self.tmp, True, who="BOSS")
        # The next card, the player's own: refused with the result alone (0x64 with 0x0E, nothing before it), as an
        # unknown card is, and the refusal is in the log once.
        with self.assertLogs("opendmt3.server", level="WARNING") as logs:
            await self.card(self.row["card"])
            result = await self.client.read(9)
        self.assertEqual((result[0], result[8]), (0x64, messages.AUTH_FAILED))
        self.assertTrue(any("refused: a card login during maintenance" in line for line in logs.output), logs.output)
        # The link stays online: the next thing it hears is the answer to its keep-alive.
        keep = bytearray(8)
        keep[0] = 0x0A
        self.client.write(bytes(keep))
        await self.client.writer.drain()
        self.assertEqual((await self.client.read(8))[0], 0x0B)
        self.assertTrue(next(iter(self.server.connections)).online)
        # The game being played keeps its results.
        self.client.write(self.results([(56, 1, 4530)]))
        await self.client.writer.drain()
        for _ in range(50):
            if self.records.recent(self.row["id"]):
                break
            await asyncio.sleep(0.02)
        self.assertEqual([p["score"] for p in self.records.recent(self.row["id"])], [4530])
        # A cabinet that connects during maintenance gets online too; only its card is refused.
        reader, writer = await asyncio.open_connection("127.0.0.1", self.server.port)
        self.addAsyncCleanup(ServerTest._close, writer)
        other = StandInClient(reader, writer)
        self.assertEqual((await other.handshake())[8], 1)
        card = bytearray(28)
        card[0] = 0x60
        card[8:28] = self.row["card"].encode()
        other.write(bytes(card))
        await writer.drain()
        refused = await other.read(9)
        self.assertEqual((refused[0], refused[8]), (0x64, messages.AUTH_FAILED))
        # Over: the same card logs in again, with the stage it cleared.
        maintenance.write(self.tmp, False)
        await self.card(self.row["card"])
        answer = await self.login_answer(mine=1, firsts=1)
        self.assertEqual(answer["result"][8], messages.AUTH_OK)

    async def test_an_unknown_or_disabled_card_is_refused(self):
        await self.card("00000000000000000000")
        result = await self.client.read(9)
        self.assertEqual((result[0], result[8]), (0x64, messages.AUTH_FAILED))
        self.accounts.set_disabled("NOVA", True)
        await self.card(self.row["card"])
        result = await self.client.read(9)
        self.assertEqual(result[8], messages.AUTH_FAILED)


class MessagesTest(unittest.TestCase):
    def test_every_server_message_builder_has_the_registered_size(self):
        for msg in (messages.handshake_request(1, 2, 3), messages.handshake_result(), messages.ping(),
                    messages.alive_ack(), messages.auth_in_ack(messages.AUTH_OK), messages.user_info(1, "DJ"),
                    messages.user_info(1, "DJ", exp=100000, icon=255, comment="한" * 20),
                    messages.clear_my_records(), messages.my_record(1, 999, 4, 900000, 1234, 4),
                    messages.clear_bests(), messages.best_record(4, 999, 4, 900000, "\U0001F3B5" * 9)):
            self.assertEqual(len(msg), messages.TO_CLIENT[msg[0]], hex(msg[0]))

    def test_a_dj_name_is_cut_by_whole_characters(self):
        # Four emoji fill the eight places; a fifth does not fit and the message keeps its size.
        msg = messages.user_info(1, "\U0001F3B5" * 5)
        self.assertEqual(len(msg), messages.TO_CLIENT[0x65])
        self.assertEqual(msg[20:20 + 18].decode("utf-16-le").rstrip("\0"), "\U0001F3B5" * 4)
        # Seven places used and an emoji next: the emoji would be cut in half, so it is left out whole.
        msg = messages.user_info(1, "ABCDEFG\U0001F3B5")
        self.assertEqual(msg[20:20 + 18].decode("utf-16-le").rstrip("\0"), "ABCDEFG")

    def test_the_dj_card_gets_its_title_plate(self):
        # The plate number low, the pattern high, at 46; the fields around it stay zero.
        msg = messages.user_info(1, "DJ NOVA")
        self.assertEqual(struct.unpack_from("<I", msg, messages.TITLE_AT)[0], 0x00008001)
        # The basic icon at 42; nothing else around the plate, and no comment (its style clear, its text empty).
        self.assertEqual(msg[38:42], bytes(4))
        self.assertEqual(struct.unpack_from("<I", msg, messages.ICON_AT)[0], 1)
        self.assertEqual(msg[50:82], bytes(32))
        self.assertEqual(struct.unpack_from("<I", messages.user_info(1, "DJ", title=0x00018001), 46)[0], 0x00018001)

    def test_variable_message_reads_its_own_size(self):
        first = bytearray(8)
        first[0] = 0x55
        struct.pack_into("<H", first, 2, 40)
        self.assertEqual(messages.size_to_server(bytes(first)), 40)
        struct.pack_into("<H", first, 2, 3)
        with self.assertRaises(messages.FrameError):
            messages.size_to_server(bytes(first))


if __name__ == "__main__":
    unittest.main()
