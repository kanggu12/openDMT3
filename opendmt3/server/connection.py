"""One cabinet's connection: cutting the encrypted stream into messages, the handshake, keeping it alive.

The order is fixed by the client. The server speaks first (0x01, the seed), then waits: the client resets both
cipher states from the seed on its main thread, so nothing else may be sent before its answer (0x02) arrives.
After 0x03 the client is online (NET green); from then on it sends 0x0A about every 11 seconds and drops the
link if 0x0B does not come back, and the server pings (0x06) every 10 seconds.

A link that has not answered the handshake within HANDSHAKE_LIMIT seconds is closed, and so is one that sent no whole
message for IDLE_LIMIT seconds (a byte now and then does not keep a place).
"""

import asyncio
import logging
import random
import time

from opendmt3.server import crypto, messages
from opendmt3.server.services import limits

log = logging.getLogger("opendmt3.server")

PING_EVERY = 10.0       # seconds between the server's pings (what the tests with the real client used)
IDLE_LIMIT = 90.0       # a client without a whole message this long is gone (it sends 0x0A every ~11 s)
HANDSHAKE_LIMIT = 10.0  # seconds a new link has to answer the handshake (the client answers at once)
SEND_LIMIT = 15.0       # seconds a send may wait for a client that does not read before the link is dropped
# A link's handlers that wait for the database, queued at most (queue()): a cabinet sends a login and, minutes apart,
# its results, so even a database held for the 10 minutes a write waits (server.WRITE_PATIENCE) queues a few. Past this
# the link's reading waits until they are done, so a link that floods logins has no more than this waiting.
QUEUED_MOST = 16
# What one address may send in a minute, over all its links (server.GameServer.spend): a new link does not start
# a new count. The game sends 8 bytes every 11 seconds and a few hundred at the end of a session, so the most
# cabinets one address has (server.PER_ADDRESS) send a few kilobytes a minute; this is many times that, and keeps a
# flood from taking the server's time from the others (decrypting 64 KiB takes the loop about 0.1 s).
BYTES_PER_MINUTE = 64 * 1024
# What a new link counts for in that budget: reconnecting again and again costs an address as much as sending (each
# link that gets online is a line in the log and a write to the database). The most cabinets one address has all
# connecting at once take a quarter of the budget.
LINK_BYTES = 1024


class Connection:
    """The state of one cabinet's link: the two cipher states, the handshake, what the client said."""

    def __init__(self, server, reader, writer, rng=None):
        self.server = server
        self.reader, self.writer = reader, writer
        peer = writer.get_extra_info("peername") or ("?", 0)
        self.address = "%s:%s" % (peer[0], peer[1])
        # The cabinet as the admin pages know it: its IP, the same on every link from that PC.
        self.host = str(peer[0])
        # Who sends, for the limits per address (an IPv6 address counts as its /64).
        self.sender = limits.sender(peer[0])
        self.session = None         # the play session of the player logged in here (services.activity)
        self.rng = rng or random.SystemRandom()
        self.to_server = 0          # cipher state of the client-to-server direction
        self.to_client = 0          # cipher state of the server-to-client direction
        self.online = False         # the handshake succeeded (the client shows NET green)
        self.answer = None          # the client's 0x02, read (machine value, version)
        self.player = None          # the ID of the player logged in on this cabinet, if any
        self.stages_kept = 0        # cleared stages kept since the player's card login (server.STAGES_PER_LOGIN)
        self.results_told = False   # results not kept were already named in the log for this link
        self.opened = time.monotonic()
        self.last_heard = self.opened       # the last bytes received
        self.last_message = self.opened     # the last whole message received (what keeps the link's place)
        self.closed = asyncio.Event()
        self.closing = False        # a handler asked for the link to end once what it sent has gone out
        self.unhandled = set()      # headers without a handler already named in the log for this connection
        # While send_all() encrypts a batch off the loop, what else is sent (the server's ping) waits here, so the
        # cipher states stay in the order the bytes go out; None the rest of the time.
        self._held = None
        # The last of the link's handlers that wait for the database (queue()), each run after the one before it, and
        # how many are queued and not done.
        self._work = None
        self._queued = 0

    # ----------------------------------------------------------------------------------- sending

    @staticmethod
    def _checked(msg):
        """The message, refused (ValueError) when its size is not the one the client registered for its header."""
        size = messages.TO_CLIENT.get(msg[0])
        if size != len(msg):
            # The client drops the link on a wrong size; better to fail here, loudly, with the header.
            raise ValueError("message 0x%02x is %d bytes; the client expects %s" % (msg[0], len(msg), size))
        return msg

    def send(self, msg):
        """Encrypt one message with the current state, then move the state on (the client does the same)."""
        self._checked(msg)
        if self.writer.is_closing():
            # The link has ended (or was dropped): nothing more goes out, and nothing is kept for it.
            return
        if self._held is not None:
            # A batch is being encrypted from the current state: this one goes right after it (send_all).
            self._held.append(msg)
            return
        self.writer.write(crypto.encrypt(msg, self.to_client))
        self.to_client = crypto.next_server_state(self.to_client)
        log.debug("%s <- %s", self.address, messages.name(msg[0]))

    @classmethod
    def _sealed(cls, batch, state):
        """send_all's work on its worker thread: every message's size checked (_checked), then all of them encrypted
        from `state` (crypto.encrypt_many). Thousands of checks are milliseconds the loop does not spend either."""
        for msg in batch:
            cls._checked(msg)
        return crypto.encrypt_many(batch, state)

    async def send_all(self, batch):
        """Send many messages in order (a card login's answer: thousands of first places), encrypted together on a
        worker thread (crypto.encrypt_many: 21 ms for 3,800, where one at a time on the loop took 153): no cabinet waits
        for it. What is sent meanwhile on this link (the server's ping) is held and goes right after, so the bytes leave
        in the order of their cipher states."""
        batch = list(batch)
        if not batch or self.writer.is_closing():
            # Nothing to send, or a link that has ended (a handler queued before it was dropped): no work for it.
            return
        if self._held is not None:
            # Another batch is on its way (a link's messages are handled one at a time, so only a ping could be): this
            # one follows it.
            self._held.extend(batch)
            return
        self._held = []
        try:
            data, state = await asyncio.get_running_loop().run_in_executor(None, self._sealed, batch, self.to_client)
            self.writer.write(data)
            self.to_client = state
        finally:
            held, self._held = self._held, None
            # Whatever happened to the batch, what was held goes out now, after it.
            for msg in held:
                self.send(msg)
        log.debug("%s <- %d messages", self.address, len(batch))
        # Gone out before the next: a client that does not read has the link dropped after SEND_LIMIT (_drain), never
        # thousands of answers kept for it in memory.
        await self._drain()

    def _send_handshake_request(self):
        """0x01 under state 0, then both states from the seed, as the client sets them on reading it."""
        self.seed = self.rng.getrandbits(32)
        # Two places in the 256-word table the client must answer with (a check that it has the same table).
        self.index0, self.index1 = self.rng.randrange(256), self.rng.randrange(256)
        self.writer.write(crypto.encrypt(messages.handshake_request(self.seed, self.index0, self.index1), 0))
        self.to_client = crypto.next_server_state(self.seed)
        self.to_server = crypto.next_client_state(self.seed)

    # --------------------------------------------------------------------------- the link's own work

    def queue(self, work):
        """Run the coroutine `work` (a handler that waits for the database: a card login, results, the note of the
        cabinet) after the link's earlier ones, in the order their messages came, while the link goes on reading: a
        keep-alive is answered while a login waits for a database another program holds. A handler that fails is
        logged and ends the link, as a failure of any handler always did."""
        previous = self._work
        self._queued += 1

        async def after():
            try:
                if previous is not None:
                    # The one before first (it never raises: each catches its own failure below).
                    await asyncio.gather(previous, return_exceptions=True)
                try:
                    await work
                except asyncio.TimeoutError:
                    # Its answer waited SEND_LIMIT for a client that does not read: _drain dropped the link and said so.
                    pass
                except (ConnectionError, OSError) as e:
                    # The client left while its answer went out: worth a line, as a broken link always is (run()).
                    log.info("%s: %s", self.address, e)
                    self.writer.close()
                except Exception:  # noqa: BLE001  (one cabinet's failure must not reach the others)
                    log.exception("%s: the server failed on a message; closing", self.address)
                    self.writer.close()
            finally:
                self._queued -= 1
        self._work = asyncio.ensure_future(after())
        return self._work

    async def finish(self):
        """Wait until the link's queued handlers are done (as the link ends: their results kept, its last session
        known)."""
        if self._work is not None:
            await asyncio.gather(self._work, return_exceptions=True)

    # --------------------------------------------------------------------------------- receiving

    def take(self, buf):
        """One whole decrypted message cut from the front of buf, or None until enough has arrived.

        The size is known only after decrypting the first 8 bytes (they hold the header), which the state allows
        because the cipher works block by block.
        """
        if len(buf) < messages.HEADER_SIZE:
            return None
        first = crypto.decrypt(bytes(buf[:messages.HEADER_SIZE]), self.to_server)
        size = messages.size_to_server(first)
        if len(buf) < size:
            return None
        msg = crypto.decrypt(bytes(buf[:size]), self.to_server)
        del buf[:size]
        self.to_server = crypto.next_client_state(self.to_server)
        # A whole message: the link is alive (bytes alone do not count, or one byte now and then would keep it).
        self.last_message = time.monotonic()
        return msg

    def _time_left(self):
        """Seconds until the link is given up: the handshake's deadline until it is online, then the idle limit
        from the last whole message."""
        now = time.monotonic()
        if not self.online:
            return max(0.0, self.opened + HANDSHAKE_LIMIT - now)
        return max(0.0, self.last_message + IDLE_LIMIT - now)

    async def run(self):
        """Serve the link until the client leaves, goes silent, or breaks the protocol."""
        # Links that never get online are not logged one by one (only refusals are, once a minute per address):
        # a stream of empty connections writes no stream of lines.
        log.debug("%s connected", self.address)
        pinger = None
        buf = bytearray()
        try:
            self._send_handshake_request()
            await self._drain()
            pinger = asyncio.ensure_future(self._ping_loop())
            while True:
                try:
                    data = await asyncio.wait_for(self.reader.read(65536), timeout=self._time_left())
                except asyncio.TimeoutError:
                    if not self.online:
                        # A place held without the handshake: given back.
                        self.server.refusals.note(self.sender, "no handshake answer within %g s" % HANDSHAKE_LIMIT,
                                                  self.address)
                    else:
                        log.info("%s silent for %d s, closing", self.address, IDLE_LIMIT)
                    break
                if not data:
                    break
                self.last_heard = time.monotonic()
                if not self.server.spend(self.sender, len(data)):
                    # Counted per address over every link, so reconnecting does not refill it.
                    self.server.refusals.note(self.sender, "more than %d bytes in a minute" % BYTES_PER_MINUTE,
                                              self.address)
                    break
                buf += data
                # Until a handler asks for the end (closing) or the link was dropped (a queued handler's answer was not
                # read): what is left in buf is then not handled.
                while not self.closing and not self.writer.is_closing():
                    msg = self.take(buf)
                    if msg is None:
                        break
                    await self.server.dispatch(self, msg)
                    if self._queued >= QUEUED_MOST:
                        # The link asks faster than the database answers it (a flood of logins): its reading waits
                        # for its queued handlers, the rest of the server does not.
                        await self.finish()
                if self.writer.is_closing():
                    # Dropped meanwhile (_drain): nothing more is read from it.
                    break
                await self._drain()
                if self.closing:
                    break
        except messages.FrameError as e:
            # Without lengths there is no way to find the next message: the link cannot go on. Told once a minute
            # per address, like every refusal (a stream of garbage links writes no stream of lines).
            self.server.refusals.note(self.sender, "a stream the server cannot cut into messages",
                                      "%s, %s" % (self.address, e))
        except (ConnectionError, OSError) as e:
            # A cabinet's broken link is worth a line; one that never got online is not.
            log.log(logging.INFO if self.online else logging.DEBUG, "%s: %s", self.address, e)
        except asyncio.TimeoutError:
            # What was sent waited SEND_LIMIT for a client that does not read: _drain dropped the link and said so.
            pass
        except Exception:  # noqa: BLE001  (one cabinet's failure must not reach the others)
            log.exception("%s: the server failed on a message; closing", self.address)
        finally:
            if pinger is not None:
                pinger.cancel()
            # A cabinet that was online leaves a line; a link that never was leaves none (see above).
            log.log(logging.INFO if self.online else logging.DEBUG, "%s disconnected", self.address)
            self.online = False
            self.closed.set()
            self.writer.close()

    async def _drain(self):
        """Wait for what was written to go out, but not for ever: a client that stops reading is dropped (drop()) after
        SEND_LIMIT, and the caller gets asyncio.TimeoutError."""
        try:
            await asyncio.wait_for(self.writer.drain(), timeout=SEND_LIMIT)
        except asyncio.TimeoutError:
            self.drop("does not read what is sent")
            raise

    def drop(self, why):
        """End the link at once, what was written and not sent thrown away (the transport aborted): close() would keep
        it, in the server's memory and the system's, until it went out, which for a client that does not read is
        never. The link's reading and its queued handlers then stop (run(), send())."""
        if not self.writer.is_closing():
            # Said once, by the first to find it.
            log.info("%s %s: dropped", self.address, why)
        self.writer.transport.abort()

    async def _ping_loop(self):
        """Ping every few seconds once online; the client answers 0x07."""
        try:
            while True:
                await asyncio.sleep(PING_EVERY)
                if self.online:
                    self.send(messages.ping())
                    await self._drain()
        except asyncio.TimeoutError:
            # The pings were not read for SEND_LIMIT: _drain dropped the link, and the reading side ends with it.
            pass
        except (ConnectionError, OSError):
            # The reading side sees the same broken link and ends the connection.
            self.writer.close()
