"""TS-SERVER-20: the game server under garbage. Random bytes before and after the handshake, frames of every known
header filled with random bodies, impossible sizes, and whole messages cut into one-byte pieces: the server never
stops, closes only the link that sent the garbage, and keeps serving the next cabinet.

The random bodies go through the real cipher (so they reach the handlers, not just the framing). A fixed seed
makes a failure repeatable; the seed is in the failure message.
"""

import asyncio
import logging
import os
import random
import shutil
import struct
import tempfile
import unittest

from opendmt3.server import db
from opendmt3.server import connection, messages
from opendmt3.server.server import GameServer
from opendmt3.server.services import accounts, activity, records
from tests.server.test_server import StandInClient

# How many garbage links each test opens (each one is a fresh connection).
ROUNDS = 60


class FuzzTest(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db.connect(os.path.join(self.tmp, "server.sqlite"))
        self.accounts = accounts.Accounts(self.db)
        self.row = self.accounts.create("NOVA", "pass1234", "DJ NOVA")
        self.server = await GameServer("127.0.0.1", 0, rng=random.Random(5), accounts=self.accounts,
                                       records=records.Records(self.db), activity=activity.Activity(self.db)).start()
        # The garbage is meant to be logged as refused; keep the test output to failures.
        logging.getLogger("opendmt3.server").setLevel(logging.CRITICAL)
        # Every garbage link comes from 127.0.0.1, which would soon spend the address's minute of bytes (a limit of
        # its own test, tests/server/test_server.py): here the links must reach the handlers.
        connection.BYTES_PER_MINUTE, saved = 1 << 30, connection.BYTES_PER_MINUTE
        self.addCleanup(setattr, connection, "BYTES_PER_MINUTE", saved)

    async def asyncTearDown(self):
        logging.getLogger("opendmt3.server").setLevel(logging.NOTSET)
        await self.server.close()
        self.db.close()
        shutil.rmtree(self.tmp)

    async def connect(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.server.port)
        return StandInClient(reader, writer)

    async def still_serving(self, why):
        """A new cabinet still gets its handshake and an answer to its keep-alive; no link is left behind."""
        client = await self.connect()
        result = await client.handshake()
        self.assertEqual((result[0], result[8]), (0x03, 1), why)
        msg = bytearray(messages.TO_SERVER[0x0A])
        msg[0] = 0x0A
        client.write(bytes(msg))
        await client.writer.drain()
        answer = await client.read(messages.TO_CLIENT[0x0B])
        self.assertEqual(answer[0], 0x0B, why)
        client.writer.close()
        for _ in range(100):
            if not self.server.connections:
                return
            await asyncio.sleep(0.01)
        self.fail("links left open after %s: %d" % (why, len(self.server.connections)))

    async def finish(self, client):
        """Close our end and wait until the server let the link go."""
        client.writer.close()
        for _ in range(200):
            if not self.server.connections:
                return
            await asyncio.sleep(0.01)
        self.fail("the server kept a garbage link open")

    async def test_random_bytes_before_and_after_the_handshake(self):
        rng = random.Random(20)
        for n in range(ROUNDS):
            client = await self.connect()
            if n % 2:
                await client.handshake()
            client.writer.write(bytes(rng.randrange(256) for _ in range(rng.randrange(1, 3000))))
            await client.writer.drain()
            await self.finish(client)
        await self.still_serving("random bytes (seed 20)")

    async def test_every_known_header_with_a_random_body(self):
        rng = random.Random(21)
        headers = sorted(messages.TO_SERVER)
        for n in range(ROUNDS):
            client = await self.connect()
            await client.handshake()
            # A first card login, so the handlers for a logged-in player run too.
            if n % 3 == 0:
                card = bytearray(messages.TO_SERVER[0x60])
                card[0] = 0x60
                card[8:28] = self.row["card"].encode()
                client.write(bytes(card))
            for _ in range(rng.randrange(1, 6)):
                header = rng.choice(headers)
                body = bytearray(rng.randrange(256) for _ in range(messages.TO_SERVER[header]))
                body[0] = header
                client.write(bytes(body))
            await client.writer.drain()
            await asyncio.sleep(0.01)
            await self.finish(client)
        await self.still_serving("random bodies (seed 21)")

    async def test_impossible_sizes_close_only_that_link(self):
        for size in (0, 7, messages.MAX_SIZE + 1, 0xFFFF):
            client = await self.connect()
            await client.handshake()
            frame = bytearray(8)
            frame[0] = next(iter(messages.VARIABLE_TO_SERVER))
            struct.pack_into("<H", frame, 2, size)
            client.write(bytes(frame))
            await client.writer.drain()
            # The server cannot find the next message and ends the link (our read sees the end).
            data = await asyncio.wait_for(client.reader.read(100), 5)
            self.assertEqual(data, b"", "size %d" % size)
            await self.finish(client)
        await self.still_serving("impossible sizes")

    async def test_a_message_in_one_byte_pieces_is_put_back_together(self):
        client = await self.connect()
        await client.handshake()
        msg = bytearray(messages.TO_SERVER[0x0A])
        msg[0] = 0x0A
        data = client.write(bytes(msg), flush=False)
        for i in range(len(data)):
            client.writer.write(data[i:i + 1])
            await client.writer.drain()
            await asyncio.sleep(0.002)
        answer = await client.read(messages.TO_CLIENT[0x0B])
        self.assertEqual(answer[0], 0x0B)
        await self.finish(client)


if __name__ == "__main__":
    unittest.main()
