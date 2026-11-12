"""The game's message cipher, rebuilt from how the client encrypts and decrypts.

Every message is encrypted whole: TEA (32 rounds) over its 8-byte blocks, and the last bytes that do not fill a
block XORed with a running value. The 128-bit key is four consecutive words of the standard CRC-32 table, picked
by a per-direction state that changes after every message. The table is computed here, not read from the game.
"""

import array
import struct

M32 = 0xFFFFFFFF
DELTA = 0x9E3779B9          # TEA's constant
KEY_XOR = 0x0A030110        # mixed into the state before it picks the key
KEY_SPAN = 252              # the key starts at one of the first 252 words, so all four words exist


def _crc32_table():
    """The standard (reflected, 0xEDB88320) CRC-32 table: the client keeps the same 256 words."""
    table = []
    for n in range(256):
        c = n
        for _ in range(8):
            c = (0xEDB88320 ^ (c >> 1)) if c & 1 else (c >> 1)
        table.append(c)
    return table


TABLE = _crc32_table()


def key_for(state):
    """The four key words for a direction's current state."""
    i = ((state ^ KEY_XOR) & M32) % KEY_SPAN
    return TABLE[i:i + 4]


def next_client_state(state):
    """The client-to-server state after one message."""
    return ((state * 7) & M32) ^ 0x93783891


def next_server_state(state):
    """The server-to-client state after one message."""
    return ((state * 31) & M32) ^ 0xAABBCCDE


def _encrypt_block(v0, v1, k):
    s = 0
    for _ in range(32):
        s = (s + DELTA) & M32
        v0 = (v0 + ((((v1 << 4) & M32) + k[0]) ^ (v1 + s) ^ ((v1 >> 5) + k[1]))) & M32
        v1 = (v1 + ((((v0 << 4) & M32) + k[2]) ^ (v0 + s) ^ ((v0 >> 5) + k[3]))) & M32
    return v0, v1


def _decrypt_block(v0, v1, k):
    s = (DELTA * 32) & M32
    for _ in range(32):
        v1 = (v1 - ((((v0 << 4) & M32) + k[2]) ^ (v0 + s) ^ ((v0 >> 5) + k[3]))) & M32
        v0 = (v0 - ((((v1 << 4) & M32) + k[0]) ^ (v1 + s) ^ ((v1 >> 5) + k[1]))) & M32
        s = (s - DELTA) & M32
    return v0, v1


def _apply(data, state, block):
    k = key_for(state)
    out = bytearray()
    whole = len(data) // 8 * 8
    # Full blocks through TEA, little-endian words like the client.
    for i in range(0, whole, 8):
        v0, v1 = struct.unpack_from("<II", data, i)
        out += struct.pack("<II", *block(v0, v1, k))
    # The tail: each byte XORed with the key's low byte plus its place in the tail (the same both ways).
    low = k[0] & 0xFF
    for j, b in enumerate(data[whole:]):
        out.append(b ^ ((low + j) & 0xFF))
    return bytes(out)


def encrypt(data, state):
    return _apply(data, state, _encrypt_block)


def decrypt(data, state):
    return _apply(data, state, _decrypt_block)


def _lanes(values):
    """32-bit values as one integer of 64-bit lanes, the first value in the lowest lane: room above each value for
    what a round adds to it, so no carry ever reaches the next lane."""
    return int.from_bytes(array.array("Q", values).tobytes(), "little")


def _from_lanes(number, n):
    """The n 32-bit values back out of _lanes' integer (each lane's low half)."""
    return array.array("I", number.to_bytes(8 * n, "little"))[0::2]


def encrypt_many(messages, state):
    """encrypt() of each message in turn, the state moving on after each as send() moves it: (all of them joined, the
    state after the last). The same bytes as one at a time, about six times faster: TEA's 32 rounds run once over
    every block of every message together, each 32-bit word in a 64-bit lane of one large integer (a card login's
    answer is thousands of messages: 185 ms one at a time on 300,000 plays). Every lane keeps its own key."""
    keys, words, tails, sizes, = [], array.array("I"), [], []
    for msg in messages:
        k = key_for(state)
        whole = len(msg) // 8 * 8
        # The message's full blocks as little-endian words, each block with its message's key.
        words.frombytes(msg[:whole])
        keys.extend([k] * (whole // 8))
        # The tail: XORed with the key's low byte plus its place in it, as _apply does.
        low = k[0] & 0xFF
        tails.append(bytes(b ^ ((low + j) & 0xFF) for j, b in enumerate(msg[whole:])))
        sizes.append(whole)
        state = next_server_state(state)
    n = len(keys)
    out = array.array("I", bytes(8 * n))
    if n:
        v0, v1 = _lanes(words[0::2]), _lanes(words[1::2])
        k0, k1, k2, k3 = (_lanes([k[i] for k in keys]) for i in range(4))
        ones = _lanes([1] * n)
        low32, low27 = M32 * ones, 0x07FFFFFF * ones
        s = 0
        for _ in range(32):
            # The same round as _encrypt_block, lane by lane; a right shift brings the next lane's low bits into this
            # one's top, which the 27-bit mask clears.
            s = (s + DELTA) & M32
            both = s * ones
            v0 = (v0 + ((((v1 << 4) & low32) + k0) ^ (v1 + both) ^ (((v1 >> 5) & low27) + k1))) & low32
            v1 = (v1 + ((((v0 << 4) & low32) + k2) ^ (v0 + both) ^ (((v0 >> 5) & low27) + k3))) & low32
        out[0::2], out[1::2] = _from_lanes(v0, n), _from_lanes(v1, n)
    blocks, joined, at = out.tobytes(), [], 0
    for whole, tail in zip(sizes, tails):
        joined.append(blocks[at:at + whole])
        joined.append(tail)
        at += whole
    return b"".join(joined), state
