"""Read and write the game's resource archives (.pak).

Layout, as the client reads it:

  0x00  32 bytes the reader skips
  0x20  header: a 32-bit seed, then 13 bytes hidden by the seed's key stream and an XOR chain:
        first entry offset (u32), version (u8, 2), one unknown byte, entry count (u32),
        a flag byte that seeds the descriptor table walk, a stream flag and one check byte
  ...   entries, one after another from the first entry offset:
        a 0x98-byte descriptor, then the entry's data
          descriptor: a per-entry seed (u32), eight bytes that pick one byte of the archive key,
                      the path (0x80 bytes, hidden by the entry seed's key stream) and the two sizes
                      with their bytes interleaved; every fourth byte of the descriptor is further
                      XORed with the archive key byte and with a 256-byte table taken from the client
          data:       chunks of [u32 length][LZO1X stream]; the joined output, cut to the file size,
                      has its first 1,000,000 bytes hidden by the entry seed's key stream

The key stream word i for a seed s is the bit pattern of float32(sin(float32(s + i))) for an even seed
and of the cosine for an odd one.

Nothing from the game is kept here. The 256-byte table is read from the player's own client, and the
archive key bytes are recovered from the player's own archive: every path in the game's archives starts with
"Resource\\", "pattern\\" or "movie", which pins the one unknown byte of each descriptor. The rest of a path is
any bytes a Windows file name holds: 51 names in 11 archives of a whole game folder have Korean letters, in the
client's code page (cp949), and one of them can be the first under its key byte. Every archive of a whole game
folder opens this way, with the one key scheme above.

Update archives ("<name>00.pak", "<name>01.pak", ...) use their base archive's key, and the client opens
them after the base in number order, looking for each with GetFileAttributesA up to the first number missing.
It reads each file from the newest archive that has it (measured under Wine by where its reads landed: of 31
files in more than one archive of a whole game folder, every one was read from the newest). An update archive
written here (build_update) was not taken by the client, though: a networksetting.ini in one went unused.
To change a file, rebuild_pak writes a copy of the newest archive that holds it with the same entries in the
same order: unchanged entries are copied byte for byte, replaced ones are re-encoded with the key byte their
original descriptor used.
"""

import collections
import concurrent.futures
import functools
import hashlib
import math
import os
import struct
import sys
import threading
import time
from array import array

# Where the reader expects the header and how big a descriptor is.
HEADER_OFFSET = 0x20
HEADER_SIZE = 17
DESC_SIZE = 0x98
# Only this much of every file's start is hidden by the key stream.
MASKED_PREFIX = 1_000_000
# The descriptor key byte is chosen by a 64-bit field modulo this.
KEY_MODULUS = 0x7D
# Uncompressed size of each data chunk; the client's own archives cut their files at this size too.
CHUNK = 0x50000
# Paths that open an archive's entries; used to recover the key byte of each descriptor.
PATH_PREFIXES = (b"Resource\\", b"pattern\\", b"movie")
# The code page of the paths: the client is a Korean program, and some of its files have Korean names (a keyboard
# picture, a song's speed notes, a copy of a script table), spelled in this code page's two-byte letters.
PATH_CODEC = "cp949"
# SHA-256 of the client's 256-byte descriptor table; lets us find it in any build without shipping it.
XORTAB_SHA256 = "d204620c5c94da75bfa9c18c087b9bac33fee56731e24744b5e4c195e3ef8318"
# Where that table sits in the one client build known so far (checked against the hash before use).
XORTAB_KNOWN_OFFSETS = (0x3A1438,)


class PakError(Exception):
    """An archive or client file that does not look like what this module knows: damaged or cut short, unless it is
    a PakUnreadable."""


class PakUnreadable(PakError):
    """An archive with the game's header that this reader cannot open: a version other than 2, or descriptors that no
    key byte opens with this client's table (an archive of another build of the game). Never damaged in words a person
    reads: only a file openDMT3 needs from it is missing. No archive of a whole game folder of the PC build is one."""


# ----------------------------------------------------------------------------------------------- key stream

_f32 = struct.Struct("<f")
_u32 = struct.Struct("<I")
# The array type of unsigned 32-bit words on this machine ("I" wherever an int is 32 bits, as on Windows and Linux).
_WORD = next(code for code in "IL" if array(code).itemsize == 4)
# A seed at or above this has float32 steps of 32 or more over its whole stream (from 2**24 on, float32 cannot hold
# every integer, so consecutive seed + i round to one value for runs of 2, 4, ... up to 512 words): its words are
# worked out once per run and repeated, the sine of about 1,000 values instead of 250,000 for a file's hidden start.
# Below it the runs are too short to pay for finding them, and every word is worked out.
_RUNS_FROM = 1 << 28
# Below _RUNS_FROM, the words worked out this many at a time: a C loop over them keeps Python's lock to itself (about
# 1.5 ms for this many), and the threads that read the game's files share it with the window's thread (core/parallel.py:
# a whole file's hidden start at once held it 25 ms, and the window's heartbeat waited up to 120 ms behind four).
_KEY_PIECE = 1 << 14


def keystream_word(seed, i):
    """Word i of a seed's key stream: the bits of float32(sin or cos(float32(seed + i))). The reference that keystream()
    gives in bulk, word for word."""
    # The sum is rounded to float32 first, exactly as the client converts it before the call.
    x = _f32.unpack(_f32.pack(float(seed + i)))[0]
    # Even seeds use the sine, odd seeds the cosine.
    v = math.sin(x) if seed % 2 == 0 else math.cos(x)
    # The result is stored as float32 and used as raw bits.
    return _u32.unpack(_f32.pack(v))[0]


def _run_end(k):
    """The last integer that float32 rounds to the same value as k (k at least 2**24, where float32 steps by 2 or
    more): rounding goes to the nearest float32, a tie to the one whose significand is even."""
    # float32(k) as an integer, and the step between float32 values from it up to the next one.
    x = int(_f32.unpack(_f32.pack(float(k)))[0])
    shift = x.bit_length() - 24
    step = 1 << shift
    # Halfway to the next value is a tie: it stays with x when x's significand is even, else goes up.
    return x + (step >> 1) - (1 if (x >> shift) & 1 else 0)


def _runs(seed, count, fn):
    """The key stream for a seed of _RUNS_FROM or more: one word per run of seed + i that float32 rounds to one value,
    repeated over the run (count * 4 little-endian bytes)."""
    parts = []
    k, end = seed, seed + count
    while k < end:
        x = _f32.unpack(_f32.pack(float(k)))[0]
        last = _run_end(k)
        if _f32.pack(float(last)) != _f32.pack(x) or _f32.pack(float(last + 1)) == _f32.pack(x):
            # The rounding was not where it was worked out to be (it always is with IEEE float32): the run is found
            # by the conversion itself instead, one value at a time.
            last = k
            while _f32.pack(float(last + 1)) == _f32.pack(x):
                last += 1
        n = min(last + 1, end) - k
        # The word as keystream_word makes it, repeated (bytes repetition is one C copy).
        parts.append(_f32.pack(fn(x)) * n)
        k += n
    return b"".join(parts)


def keystream(seed, count):
    """Words 0 to count-1 of a seed's key stream as count * 4 little-endian bytes: keystream_word(seed, i) for each i,
    bit for bit, without one Python call per word (220 ms a megabyte one word at a time).

    From _RUNS_FROM on, a word is worked out once for each run of seed + i that rounds to one float32 value. Below it,
    array("f") converts each integer and each sine to float32 in C loops, the way struct's "<f" does (rounded to the
    nearest, ties to even: the client's own conversion); math.sin and math.cos are the calls keystream_word makes."""
    if count <= 0:
        return b""
    # Even seeds use the sine, odd seeds the cosine.
    fn = math.sin if seed % 2 == 0 else math.cos
    if seed >= _RUNS_FROM:
        return _runs(seed, count, fn)
    words = array("f")
    for at in range(0, count, _KEY_PIECE):
        # float32(seed + i) for every i, then the function over each, stored back as float32: two C loops, a piece at
        # a time (a C loop keeps Python's lock to itself, so the window's thread waits through one piece at most).
        n = min(_KEY_PIECE, count - at)
        words.extend(array("f", map(fn, array("f", range(seed + at, seed + at + n)))))
    if sys.byteorder != "little":
        # The archives' words are little-endian; array holds the machine's order.
        words.byteswap()
    return words.tobytes()


@functools.lru_cache(maxsize=4)
def _lane_masks(count):
    """(the top bit of each 32-bit lane, the 31 bits under it) over count lanes, as integers: what lets one big integer
    add or subtract count words at once without a carry crossing from one word into the next. A few sizes are kept
    (a file's whole hidden start, a descriptor's path), each another megabyte at most."""
    return (int.from_bytes(b"\x00\x00\x00\x80" * count, "little"),
            int.from_bytes(b"\xff\xff\xff\x7f" * count, "little"))


def _stream(buf, seed, count, sign):
    """Add (sign=+1) or subtract (sign=-1) the key stream over the first count whole words of buf, in place.

    Every word at once, as lanes of one big integer: arithmetic modulo 2**32 in each lane, like the client's unsigned
    words, the carry (or borrow) of the low 31 bits kept inside the lane and the top bit worked out apart."""
    if count <= 0:
        return
    size = 4 * count
    # The buffer's words and the stream's words, each as one integer (word i in bits 32i to 32i+31).
    data = int.from_bytes(buf[:size], "little")
    keys = int.from_bytes(keystream(seed, count), "little")
    high, low = _lane_masks(count)
    if sign > 0:
        # a + b in each lane: the low 31 bits add with room for their carry in the top bit, which then takes the two
        # top bits as well (XOR is addition without carry; the carry out of the top bit is dropped, modulo 2**32).
        out = ((data & low) + (keys & low)) ^ ((data ^ keys) & high)
    else:
        # a - b in each lane: a's top bit set first, so the low 31 bits never borrow from the lane above; the top bit
        # is then put right by the two top bits (a's flipped back, b's subtracted: XOR again).
        out = ((data | high) - (keys & low)) ^ ((data ^ keys ^ high) & high)
    buf[:size] = out.to_bytes(size, "little")


def unmask(buf, seed):
    """Reveal a hidden byte run in place (whole words only; a trailing partial word is left as it is)."""
    _stream(buf, seed, len(buf) // 4, -1)


def mask(buf, seed):
    """Hide a byte run in place; the inverse of unmask."""
    _stream(buf, seed, len(buf) // 4, +1)


# ------------------------------------------------------------------------------------------- header chain

def _xor_chain_decode(b):
    """The header's XOR chain: the first word XORed with (length ^ 0x18385868), later words with the first."""
    b = bytearray(b)
    key = len(b) ^ 0x18385868
    first = int.from_bytes(b[0:4], "little") ^ key
    b[0:4] = first.to_bytes(4, "little")
    # The client walks words while a counter that steps by 4 stays below (length - 7) >> 2.
    p, cnt = 4, 0
    while cnt < (len(b) - 7) >> 2:
        w = int.from_bytes(b[p:p + 4], "little") ^ first
        b[p:p + 4] = w.to_bytes(4, "little")
        p += 4
        cnt += 4
    return bytes(b)


def _xor_chain_encode(b):
    """Inverse of _xor_chain_decode: later words take the plain first word, the first word the length key."""
    b = bytearray(b)
    key = len(b) ^ 0x18385868
    first = int.from_bytes(b[0:4], "little")
    p, cnt = 4, 0
    while cnt < (len(b) - 7) >> 2:
        w = int.from_bytes(b[p:p + 4], "little") ^ first
        b[p:p + 4] = w.to_bytes(4, "little")
        p += 4
        cnt += 4
    b[0:4] = (first ^ key).to_bytes(4, "little")
    return bytes(b)


class Header:
    """The archive header fields."""

    def __init__(self, seed, first, version, unknown, count, flag, stream_flag, check):
        self.seed = seed
        self.first = first
        self.version = version
        self.unknown = unknown
        self.count = count
        self.flag = flag
        self.stream_flag = stream_flag
        self.check = check

    @classmethod
    def parse(cls, raw):
        """Decode the 17 header bytes found at HEADER_OFFSET."""
        if len(raw) < HEADER_SIZE:
            # A file shorter than a header (cut short, or not an archive) is refused as an archive error.
            raise PakError("the file is shorter than an archive's header (%d bytes)" % len(raw))
        seed = int.from_bytes(raw[0:4], "little")
        body = bytearray(raw[4:17])
        # Key stream first (three whole words; the thirteenth byte is not covered), then the XOR chain.
        unmask(body, seed)
        body = _xor_chain_decode(body)
        return cls(seed, int.from_bytes(body[0:4], "little"), body[4], body[5],
                   int.from_bytes(body[6:10], "little"), body[10], body[11], body[12])

    def expected_check(self):
        """The check byte the client computes before it accepts a header (CPackBase::LoadHeader)."""
        # Its first two steps always give 0 (a byte times a shifted version, then times the unknown byte).
        c = 1 if self.stream_flag else 0
        c = (c ^ self.count) & 0xFF
        c = (c * self.first) & 0xFF
        c = (c + self.flag) & 0xFF
        return ~c & 0xFF

    def build(self):
        """Encode back to 17 bytes, with the check byte the client expects."""
        self.check = self.expected_check()
        body = (self.first.to_bytes(4, "little") + bytes([self.version, self.unknown])
                + self.count.to_bytes(4, "little") + bytes([self.flag, self.stream_flag, self.check]))
        body = bytearray(_xor_chain_encode(body))
        mask(body, self.seed)
        return self.seed.to_bytes(4, "little") + bytes(body)


# --------------------------------------------------------------------------------------------- descriptors

def _key_index(raw):
    """Which archive key byte a descriptor uses: its 64-bit field at 4..11 modulo 0x7D."""
    f1 = int.from_bytes(raw[4:8], "little")
    f2 = int.from_bytes(raw[8:12], "little")
    return ((f2 << 32) | f1) % KEY_MODULUS


# The key byte's layer over a whole descriptor as one number, for each key byte: the byte at every fourth place.
_KEY_LAYERS = tuple(int.from_bytes(bytes((kb, 0, 0, 0)) * (DESC_SIZE // 4), "little") for kb in range(256))


@functools.lru_cache(maxsize=1024)
def _table_layer(table, table_start):
    """The client table's layer over a whole descriptor as one number: at every fourth place o, the table's byte
    table_start + o (the place in the table steps by 4 with the place in the descriptor, round its 256 bytes)."""
    layer = bytearray(DESC_SIZE)
    layer[0::4] = bytes(table[(table_start + o) & 0xFF] for o in range(0, DESC_SIZE, 4))
    return int.from_bytes(layer, "little")


def _xor_layers(d, key_byte, table, table_start):
    """XOR every fourth byte of a whole descriptor with the archive key byte and with the client table; its own
    inverse. Both layers at once, as numbers the size of the descriptor (a byte at a time took a third of a walk)."""
    layers = _KEY_LAYERS[key_byte] ^ _table_layer(bytes(table), table_start)
    d[:] = (int.from_bytes(d, "little") ^ layers).to_bytes(DESC_SIZE, "little")


class Entry:
    """One file of an archive. Read only once made: the listings kept for archives opened again (Pak) share them."""

    # No dictionary per entry: a whole game folder's charts are 56,157 of them, kept while the launcher runs.
    __slots__ = ("index", "name", "seed", "offset", "packed", "size")

    def __init__(self, index, name, seed, offset, packed, size):
        self.index = index        # position in the archive
        self.name = name          # path as the client asks for it, with backslashes
        self.seed = seed          # entry seed (key stream of the path and of the data's start)
        self.offset = offset      # file offset of the data (right after the descriptor)
        self.packed = packed      # bytes of data in the archive
        self.size = size          # bytes after unpacking


def _decode_descriptor(raw, key_byte, table, table_start):
    """Return (seed, name bytes or None, packed size, size) for a descriptor decrypted with key_byte."""
    d = bytearray(raw)
    _xor_layers(d, key_byte, table, table_start)
    seed = int.from_bytes(d[0:4], "little")
    blob = bytearray(d[0x0C:0x8C])
    unmask(blob, seed)
    name = bytes(blob).split(b"\x00", 1)[0]
    # The two sizes share eight bytes, interleaved.
    packed = d[0x8F] | d[0x91] << 8 | d[0x8D] << 16 | d[0x93] << 24
    size = d[0x92] | d[0x8C] << 8 | d[0x90] << 16 | d[0x8E] << 24
    return seed, name, packed, size


def _encode_descriptor(seed, name, packed, size, key_field, key_byte, table, table_start):
    """Build a 0x98-byte descriptor; key_field is the raw 8 bytes that select key_byte when read back."""
    d = bytearray(DESC_SIZE)
    d[0:4] = seed.to_bytes(4, "little")
    blob = bytearray(name.ljust(0x80, b"\x00"))
    if len(name) >= 0x80:
        raise PakError("path too long: %r" % name)
    mask(blob, seed)
    d[0x0C:0x8C] = blob
    d[0x8F], d[0x91], d[0x8D], d[0x93] = packed & 0xFF, packed >> 8 & 0xFF, packed >> 16 & 0xFF, packed >> 24 & 0xFF
    d[0x92], d[0x8C], d[0x90], d[0x8E] = size & 0xFF, size >> 8 & 0xFF, size >> 16 & 0xFF, size >> 24 & 0xFF
    _xor_layers(d, key_byte, table, table_start)
    # Bytes 4..11 are only read raw, to pick the key byte; their decoded value is never used.
    d[4:12] = key_field
    return bytes(d)


def _recover_key_byte(raw, table, table_start, file_size, offset):
    """Find the key byte that turns a descriptor into a known path prefix with a size that fits the file.

    No key byte at all is either an archive of another build, written with another table (PakUnreadable), or one cut
    short, whose last entry's data runs past the end of the file: the two are told apart by trying again without the
    size, which finds the one key byte of an archive cut short (a PakError: damaged) and none of another build's."""
    hits = _key_bytes(raw, table, table_start, file_size, offset)
    if len(hits) == 1:
        return hits[0]
    if not hits and len(_key_bytes(raw, table, table_start, None, offset)) == 1:
        # The path reads as one, but the data it names is not all in the file: the archive was cut short.
        raise PakError("descriptor at %#x: its data runs past the end of the file (cut short)" % offset)
    # None that reads, or more than one: not hidden with this client's table (another build's archive).
    raise PakUnreadable("descriptor at %#x: %d candidate key bytes" % (offset, len(hits)))


def _reads_as_path(name):
    """True for bytes that read as a path of the client's: one of the known prefixes, then any byte a Windows file name
    holds, which is every byte but the control characters 1 to 31. A Korean name in the client's code page, or a name
    in any other, is a name like an ASCII one: the prefix and the size are what pin the key byte."""
    if not name or not name.startswith(PATH_PREFIXES):
        # Every file of the game's archives sits under one of these folders.
        return False
    # A control character is in no file name: a key byte that gives one did not give a path. (A wrong key byte also
    # changes the entry seed, so its path comes out as noise that the prefix alone already refuses.)
    return not any(c < 0x20 for c in name)


def _first_words(first):
    """Word 0 of the key stream of each of the 256 seeds first to first + 255 (first a multiple of 256), as numbers:
    keystream_word(seed, 0) for each, the float32 bits of the sine (even seeds) or cosine (odd seeds) of the seed as
    float32, worked out in two C loops."""
    # float32 of each seed: the value word 0 of its stream is worked out from.
    xs = array("f", range(first, first + 256))
    words = array("f", xs)
    # first is even, so the even places hold the even seeds (sine) and the odd places the odd ones (cosine).
    words[0::2] = array("f", map(math.sin, xs[0::2]))
    words[1::2] = array("f", map(math.cos, xs[1::2]))
    # The float32 bits read as unsigned words (the machine's order for both, so each number is its float's bits).
    return array(_WORD, words.tobytes())


# The first word of each path prefix, as a little-endian number: a key byte that does not reveal one of these as the
# path's first word is no key byte (every prefix is at least four bytes long).
_PREFIX_WORDS = frozenset(int.from_bytes(prefix[:4], "little") for prefix in PATH_PREFIXES)


def _key_bytes(raw, table, table_start, file_size, offset):
    """Every key byte that turns a descriptor into a known path prefix, with a size that fits the file (any size when
    file_size is None)."""
    hits = []
    # The key byte changes only the low byte of the entry's seed (offset 0) and of the path's first word (offset 12),
    # each further XORed with its byte of the client table: the 256 candidates' seeds are the 256 seeds that share the
    # three upper bytes, so word 0 of every candidate's key stream comes from one table of 256 words.
    seed_xor, path_xor = table[table_start & 0xFF], table[(table_start + 12) & 0xFF]
    seed_top = int.from_bytes(raw[1:4], "little") << 8
    path_top = int.from_bytes(raw[13:16], "little") << 8
    firsts = _first_words(seed_top)
    for kb in range(256):
        # The cheapest test, the path's first word as this key byte reveals it: one subtraction instead of a key stream
        # (it lets through every key byte the test below lets through, and almost no other).
        word = (((raw[12] ^ kb ^ path_xor) | path_top) - firsts[raw[0] ^ kb ^ seed_xor]) & 0xFFFFFFFF
        if word not in _PREFIX_WORDS:
            continue
        # Cheap test next: only the seed and the first three words of the path.
        d = bytearray(raw[:0x18])
        arg = table_start
        for o in range(0, 0x18, 4):
            d[o] ^= kb ^ table[arg & 0xFF]
            arg = (arg + 4) & 0xFFFFFFFF
        seed = int.from_bytes(d[0:4], "little")
        head = bytearray(d[0x0C:0x18])
        unmask(head, seed)
        if not bytes(head).startswith(PATH_PREFIXES):
            continue
        seed, name, packed, size = _decode_descriptor(raw, kb, table, table_start)
        # The whole path, Korean letters included: an archive whose first entry under a key byte has a Korean name
        # (six in a whole game folder) is opened like any other, the same key scheme throughout.
        if not _reads_as_path(name):
            continue
        if file_size is not None and offset + DESC_SIZE + packed > file_size:
            continue
        hits.append(kb)
    return hits


# ---------------------------------------------------------------------------------------------- LZO1X

def lzo1x_decompress(src, limit=None):
    """Standard LZO1X decompression of one chunk. Stops at the end marker or the end of the input.

    limit is the most the chunk may unpack to (CHUNK in an archive): a stream that says more is not one the client
    wrote, and is refused before its runs are spelled out (a few bytes can say gigabytes). A stream cut short is
    refused as well, as a PakError like every other archive fault.
    """
    try:
        return _lzo1x(src, limit)
    except IndexError:
        # An instruction that reads past the end of the stream: cut short, or not LZO1X.
        raise PakError("LZO stream cut short") from None


def _lzo1x(src, limit):
    out = bytearray()
    ip, n = 0, len(src)

    def room(count):
        # Checked before each run or match is written out, not byte by byte.
        if limit is not None and len(out) + count > limit:
            raise PakError("LZO stream unpacks past its chunk's size")

    def take(count):
        nonlocal ip
        room(count)
        out.extend(src[ip:ip + count])
        ip += count

    def copy_match(dist_back, count):
        # Byte by byte, so an overlapping match repeats its pattern as LZO requires.
        start = len(out) - dist_back
        if start < 0:
            raise PakError("LZO match before the start of the output")
        room(count)
        for k in range(count):
            out.append(out[start + k])

    if n == 0:
        return bytes(out)
    t = src[ip]
    state = "loop"
    if t > 17:
        ip += 1
        t -= 17
        if t < 4:
            # A short run is copied by match_next, which then reads the next instruction as a match.
            state = "match_next"
        else:
            take(t)
            state = "first_literal_run"
    while ip < n:
        if state == "loop":
            t = src[ip]
            ip += 1
            if t >= 16:
                state = "match"
                continue
            if t == 0:
                while ip < n and src[ip] == 0:
                    t += 255
                    ip += 1
                t += 15 + src[ip]
                ip += 1
            take(t + 3)
            state = "first_literal_run"
            continue
        if state == "first_literal_run":
            t = src[ip]
            ip += 1
            if t >= 16:
                state = "match"
                continue
            # A three-byte match far back, right after a literal run.
            dist = 1 + 0x0800 + (t >> 2) + (src[ip] << 2)
            ip += 1
            copy_match(dist, 3)
            state = "match_done"
            continue
        if state == "match":
            if t >= 64:
                dist = 1 + ((t >> 2) & 7) + (src[ip] << 3)
                ip += 1
                count = (t >> 5) - 1 + 2
            elif t >= 32:
                t &= 31
                if t == 0:
                    while src[ip] == 0:
                        t += 255
                        ip += 1
                    t += 31 + src[ip]
                    ip += 1
                dist = 1 + ((src[ip] | src[ip + 1] << 8) >> 2)
                ip += 2
                count = t + 2
            elif t >= 16:
                far = (t & 8) << 11
                t &= 7
                if t == 0:
                    while src[ip] == 0:
                        t += 255
                        ip += 1
                    t += 7 + src[ip]
                    ip += 1
                back = far + ((src[ip] | src[ip + 1] << 8) >> 2)
                ip += 2
                if back == 0:
                    break                                  # end marker
                dist = back + 0x4000
                count = t + 2
            else:
                dist = 1 + (t >> 2) + (src[ip] << 2)
                ip += 1
                count = 2
            copy_match(dist, count)
            state = "match_done"
            continue
        if state == "match_done":
            t = src[ip - 2] & 3
            if t == 0:
                state = "loop"
                continue
            state = "match_next"
            continue
        if state == "match_next":
            take(t)
            t = src[ip]
            ip += 1
            state = "match"
            continue
    return bytes(out)


def lzo1x_store(data):
    """An LZO1X stream that holds data as literals only, which any LZO1X decompressor accepts."""
    out = bytearray()
    n = len(data)
    if 0 < n <= 238:
        # One leading literal run: the first byte is 17 + length.
        out.append(17 + n)
    elif n > 238:
        # A long literal run: 0, then 255 for every zero byte, then the rest of (length - 18).
        rest = n - 3 - 15
        out.append(0)
        while rest > 255:
            out.append(0)
            rest -= 255
        out.append(rest)
    out += data
    # End marker: a far match with distance 0.
    out += b"\x11\x00\x00"
    return bytes(out)


# ----------------------------------------------------------------------------------------- client table

def _section_ranges(data, name):
    """File ranges of the PE sections with this name (read from the headers with struct, no PE library)."""
    pe = int.from_bytes(data[0x3C:0x40], "little")
    count = int.from_bytes(data[pe + 6:pe + 8], "little")
    opt_size = int.from_bytes(data[pe + 20:pe + 22], "little")
    table = pe + 24 + opt_size
    out = []
    for i in range(count):
        s = table + 40 * i
        if data[s:s + 8].rstrip(b"\x00") == name:
            raw_size = int.from_bytes(data[s + 16:s + 20], "little")
            raw_ptr = int.from_bytes(data[s + 20:s + 24], "little")
            out.append((raw_ptr, raw_ptr + raw_size))
    return out


def load_table(client_path):
    """Find the 256-byte descriptor table in the player's client by its hash (it sits in .rdata)."""
    with open(client_path, "rb") as f:
        data = f.read()

    def matches(off):
        return hashlib.sha256(data[off:off + 256]).hexdigest() == XORTAB_SHA256

    # The build we know keeps it at a fixed offset; any other build is searched in its read-only data.
    for off in XORTAB_KNOWN_OFFSETS:
        if off + 256 <= len(data) and matches(off):
            return data[off:off + 256]
    for start, end in _section_ranges(data, b".rdata"):
        # A section table that claims more than the file holds (a program that is no PE file, or a damaged one) is
        # searched only as far as the file goes, never for billions of offsets.
        end = min(end, len(data))
        for off in range(start, max(start, end - 256 + 1)):
            if matches(off):
                return data[off:off + 256]
    raise PakError("the descriptor table was not found in %s" % client_path)


# ------------------------------------------------------------------------------------------------ reading

# Listings of archives already walked (the header, the entries and the key bytes found), by the file as it was: its
# path, size, modification and change times and file number, with the client table it was read with. An archive opened
# again takes its listing from here instead of walking its descriptors again: the card's look opens the song list's
# family three times, and a second look opened 28 archives anew (2.2 to 3.8 s on a whole game folder). A file changed
# in any of these ways is walked again. Only a file left alone for a while is kept (LISTED_AFTER): one rewritten in
# place at once, at the same size, can keep its times on a clock that ticks every few milliseconds.
_listings = collections.OrderedDict()
_listings_lock = threading.Lock()
# The most entries kept in all (a whole game folder's charts are 56,157); past this the listings used least recently go.
LISTED_MOST = 100_000
# Nanoseconds a file must have been left alone before its listing is kept.
LISTED_AFTER = 2_000_000_000
# How much of the file one read takes while the descriptors are walked: a descriptor's 152 bytes cost a whole round
# trip on a slow drive (61,683 reads of 8 KB, 13 s, for the charts' family of a whole game folder on WSL's mount of a
# Windows drive), so one read takes the next descriptors of small entries along. The window grows while each read
# serves several descriptors (the charts' entries average 22 KB: 15 s to 4 s for their walk) and shrinks while entries
# are longer than it (a read of the songs' previews serves one descriptor, whatever its size).
WALK_WINDOW_LEAST = 16 << 10
WALK_WINDOW_MOST = 1 << 20
# A file at least this large is walked with its next windows read ahead on threads of their own (_Ahead); a smaller one
# takes a window or two anyway.
WALK_AHEAD_FROM = 8 << 20
# How many windows are read ahead at once: four readers give a drive most of what it gives (WSL's mount of a Windows
# drive: 200 MB/s for one reader, 440 for two, 480 to 510 for four or eight). The walk of a whole game folder's charts
# (56,157 descriptors in 1.2 GB) took 4.7 to 5.1 s reading one window at a time, 4.0 s with two read ahead and 2.8 to
# 3.0 s with four (six gave no more).
WALK_AHEAD = 4


def _listing(key):
    """The listing kept for this file (header, key bytes, key fields, entries), or None; the most recent use last."""
    with _listings_lock:
        found = _listings.get(key)
        if found is not None:
            _listings.move_to_end(key)
        return found


def _keep_listing(key, listing):
    """Keep a listing just walked, the least recently used ones going while more than LISTED_MOST entries are kept."""
    with _listings_lock:
        _listings[key] = listing
        _listings.move_to_end(key)
        total = sum(len(kept[3]) for kept in _listings.values())
        while total > LISTED_MOST and _listings:
            _, gone = _listings.popitem(last=False)
            total -= len(gone[3])


def forget_listings():
    """Drop every listing kept (the tests' clean start; a file changed is walked again without this)."""
    with _listings_lock:
        _listings.clear()


# The files being walked now, each with what its walk sets once done: a thread that opens one of them meanwhile (two
# readers of one family at once, the card's look and its charts' check) waits for that walk's listing instead of
# walking the file a second time.
_walking = {}


def _walk_once(key):
    """The listing of this file once a walk of it going on in another thread is done (None when there is none, or it
    kept none), or (None, a function to call when this thread's own walk is done) for the thread that walks it."""
    with _listings_lock:
        done = _walking.get(key)
        if done is None:
            # This thread walks it: the others wait for what it sets.
            done = _walking[key] = threading.Event()
            mine = True
        else:
            mine = False
    if not mine:
        done.wait()
        return _listing(key), None

    def finished():
        with _listings_lock:
            _walking.pop(key, None)
        done.set()

    return None, finished


class _Ahead:
    """A file's bytes for a walk of its descriptors, from wherever the walk is: the windows after the one in use are read
    ahead on threads of their own, each with a handle of its own, so the drive reads while the walk decodes, and a drive
    that gives more to several readers at once gives it. When the walk jumps past them (a long entry), what was read
    ahead is dropped and the window it needs is read at once."""

    def __init__(self, path, own):
        self.path = path
        # The walk's own handle, for a window read at once on the walk's thread.
        self.own = own
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=WALK_AHEAD, thread_name_prefix="opendmt3-walk")
        # Each thread of the pool reads with a handle of its own (a handle's place is one for all who use it).
        self.local = threading.local()
        self.handles, self.handles_lock = [], threading.Lock()
        # The window in hand and where it starts; the windows read ahead after it, in order: (start, size, future).
        self.buf, self.buf_at = b"", 0
        self.pending = collections.deque()

    def _read(self, at, size):
        """size bytes from at (fewer at the file's end), on a thread of the pool."""
        f = getattr(self.local, "file", None)
        if f is None:
            f = open(self.path, "rb")
            with self.handles_lock:
                self.handles.append(f)
            self.local.file = f
        f.seek(at)
        return f.read(size)

    def window(self, at, size, ahead):
        """The bytes from at: up to size of them read at once, or what was read ahead from at on (joined with the next
        window read ahead when a descriptor runs into it). With ahead, WALK_AHEAD windows of size after them are read
        ahead."""
        # Windows read ahead that end before at were jumped over (a long entry): their bytes are not needed.
        while self.pending and self.pending[0][0] + self.pending[0][1] <= at:
            self.pending.popleft()[2].cancel()
        parts = []
        if self.buf_at <= at < self.buf_at + len(self.buf):
            # In the window in hand (a descriptor that runs past its end): its last bytes.
            parts, reached = [self.buf[at - self.buf_at:]], self.buf_at + len(self.buf)
        elif self.pending and self.pending[0][0] <= at:
            # In the first window read ahead: waited for, if it is still being read.
            start, _, future = self.pending.popleft()
            data = future.result()
            parts, reached = [data[at - start:]], start + len(data)
        # A descriptor running past those bytes takes the next window read ahead (it starts where they end).
        while parts and sum(len(part) for part in parts) < DESC_SIZE and self.pending and \
                self.pending[0][0] == reached:
            start, _, future = self.pending.popleft()
            data = future.result()
            parts.append(data)
            reached = start + len(data)
        data = b"".join(parts)
        if len(data) < DESC_SIZE:
            # Nothing in hand or read ahead holds the descriptor whole (a jump past them, or nothing read after them):
            # whatever was read ahead is dropped, and the window read now (at the file's end, the few bytes there are).
            for _, _, future in self.pending:
                future.cancel()
            self.pending.clear()
            self.own.seek(at)
            data = self.own.read(size)
        self.buf, self.buf_at = data, at
        if ahead:
            # WALK_AHEAD windows kept being read after what is in hand (or after the last one asked for).
            after = self.pending[-1][0] + self.pending[-1][1] if self.pending else at + len(self.buf)
            while len(self.pending) < WALK_AHEAD:
                self.pending.append((after, size, self.pool.submit(self._read, after, size)))
                after += size
        return self.buf

    def close(self):
        """The reads not started dropped, the ones running waited for, and every handle closed."""
        self.pool.shutdown(wait=True, cancel_futures=True)
        for f in self.handles:
            f.close()


class Pak:
    """An open archive: header, entries, and the data of any entry."""

    def __init__(self, path, table):
        self.path = path
        self.table = table
        self.file = open(path, "rb")
        # One read at a time of the handle (its place is one for every thread): entries are read on several threads
        # (core/parallel.py), each taking its bytes under this, then unpacking them on its own.
        self.reading = threading.Lock()
        try:
            st = os.fstat(self.file.fileno())
            self.size = st.st_size
            # The file as opened (its times and number from the open file itself, so a file replaced meanwhile is
            # never taken for the one listed), with the table its descriptors were read with.
            key = (os.path.normcase(os.path.abspath(path)), st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino,
                   bytes(table))
            kept, finished = _listing(key), None
            if kept is None:
                # Not walked before: walked here, or (another thread walking it now) its listing waited for.
                kept, finished = _walk_once(key)
            if kept is not None:
                # Walked before, unchanged since: its own copies of the lists (the entries themselves are read only).
                header, key_bytes, key_fields, entries = kept
                self.header, self.key_bytes, self.key_fields, self.entries = (
                    header, dict(key_bytes), dict(key_fields), list(entries))
                return
            try:
                self._open_and_walk(path, st, key)
            finally:
                if finished is not None:
                    # The threads waiting for this walk take its listing now (or walk the file themselves when it
                    # kept none: damaged, or written just now).
                    finished()
        except BaseException:
            # An archive refused while opening is closed here: no `with` block owns it yet.
            self.file.close()
            raise

    def _open_and_walk(self, path, st, key):
        """The header read and checked, every descriptor walked, and the listing kept when the file was left alone a
        while (LISTED_AFTER)."""
        self.file.seek(HEADER_OFFSET)
        self.header = Header.parse(self.file.read(HEADER_SIZE))
        if self.header.check != self.header.expected_check():
            # The client checks this byte before it takes an archive (CPackBase::LoadHeader): a header without it is
            # not one the game wrote (overwritten, or not an archive at all). Every archive of a whole game folder has
            # it, the ones this reader cannot open included.
            raise PakError("%s: the header's check byte is not the game's" % path)
        if self.header.version != 2:
            # A header the game wrote, of a version this reader does not know.
            raise PakUnreadable("%s: archive version %d" % (path, self.header.version))
        self.key_bytes = {}       # key index -> key byte, recovered as descriptors are read
        self.key_fields = {}      # key index -> one raw 8-byte field that selects it
        self.entries = self._walk()
        if time.time_ns() - st.st_mtime_ns > LISTED_AFTER:
            # Kept for the next opening of the same file (a damaged or unreadable one never gets here).
            _keep_listing(key, (self.header, dict(self.key_bytes), dict(self.key_fields), list(self.entries)))

    def close(self):
        self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _walk(self):
        entries = []
        off = self.header.first
        # The bytes of the file read last, and where they start: the next descriptor is taken from them when it is
        # inside them (an entry shorter than the window), else read with the window after it.
        window, window_at = b"", 0
        # The size of the next read, and how many descriptors the last one served.
        reach, served = WALK_WINDOW_LEAST * 4, 0
        # A large file's next windows are read ahead on threads of their own while this one decodes.
        ahead = _Ahead(self.path, self.file) if self.size >= WALK_AHEAD_FROM else None
        try:
            entries = self._walk_with(entries, off, window, window_at, reach, served, ahead)
        finally:
            if ahead is not None:
                ahead.close()
        return entries

    def _walk_with(self, entries, off, window, window_at, reach, served, ahead):
        """_walk's loop: each descriptor taken from the window in hand, or a new window read (or read ahead)."""
        # The data size of the entry walked last: what a window must hold to serve its like.
        packed = 0
        for t in range(self.header.count):
            if not window_at <= off <= window_at + len(window) - DESC_SIZE:
                if served > 1:
                    # Small entries: a larger window serves more of them for each round trip.
                    reach = min(WALK_WINDOW_MOST, reach * 4)
                elif served == 1:
                    # An entry longer than the window: the next window holds about four of its like, so it serves
                    # several again (and is read ahead); after one longer than the largest window, only the
                    # descriptor of the next is sure to be of use, and the least is read.
                    reach = WALK_WINDOW_LEAST if packed > WALK_WINDOW_MOST else \
                        min(WALK_WINDOW_MOST, max(WALK_WINDOW_LEAST, 4 * (packed + DESC_SIZE)))
                if ahead is None:
                    self.file.seek(off)
                    window = self.file.read(reach)
                else:
                    # Windows read ahead only while they serve several descriptors (small entries); after a long
                    # entry the next descriptor is anywhere.
                    window = ahead.window(off, reach, served > 1)
                window_at, served = off, 0
            served += 1
            raw = window[off - window_at:off - window_at + DESC_SIZE]
            if len(raw) < DESC_SIZE:
                raise PakError("%s: descriptor %d cut short" % (self.path, t))
            start = (self.header.flag - t) & 0xFF
            idx = _key_index(raw)
            if idx not in self.key_bytes:
                self.key_bytes[idx] = _recover_key_byte(raw, self.table, start, self.size, off)
                self.key_fields[idx] = raw[4:12]
            seed, name, packed, size = _decode_descriptor(raw, self.key_bytes[idx], self.table, start)
            # Paths are ASCII except a few Korean names, in the client's code page.
            entries.append(Entry(t, name.decode(PATH_CODEC, errors="replace"), seed, off + DESC_SIZE, packed, size))
            off += DESC_SIZE + packed
        return entries

    def read(self, entry):
        """The unpacked bytes of one entry (from any thread: the handle is read under a lock, the rest is the thread's
        own work)."""
        with self.reading:
            self.file.seek(entry.offset)
            packed = self.file.read(entry.packed)
        out = bytearray()
        p = 0
        while p + 4 <= len(packed):
            clen = int.from_bytes(packed[p:p + 4], "little")
            p += 4
            if clen == 0 or p + clen > len(packed):
                break
            # No chunk unpacks past CHUNK; the archive's own writer cuts its files there.
            out += lzo1x_decompress(packed[p:p + clen], CHUNK)
            p += clen
            if len(out) >= entry.size:
                break
        if len(out) < entry.size:
            # Fewer bytes than the entry says it holds: the archive was cut short (or its chunks are not the game's).
            # Said as damaged, never handed on as a shorter file.
            raise PakError("%s: %s is cut short (%d of %d bytes)" % (self.path, entry.name, len(out), entry.size))
        del out[entry.size:]
        head = bytearray(out[:MASKED_PREFIX])
        unmask(head, entry.seed)
        out[:len(head)] = head
        return bytes(out)

    def find(self, name):
        """The entry with this path (case-insensitive, either slash), or None."""
        want = name.replace("/", "\\").lower()
        for e in self.entries:
            if e.name.lower() == want:
                return e
        return None


# ------------------------------------------------------------------------------------------------ writing

def write_pak(out_path, files, table, key_byte, key_field, template, lead, seed_source=os.urandom):
    """Write an archive holding files {path: bytes}; every descriptor uses one key byte, selected by key_field.

    template supplies the header values other than the first entry offset and the count; lead is the 32
    bytes the reader skips.
    """
    names = list(files)
    h = template
    header = Header(h.seed, HEADER_OFFSET + HEADER_SIZE, h.version, h.unknown, len(names), h.flag, h.stream_flag, h.check)
    out = bytearray(lead)
    out += header.build()
    for t, name in enumerate(names):
        data = bytearray(files[name])
        seed = int.from_bytes(seed_source(4), "little")
        head = bytearray(data[:MASKED_PREFIX])
        mask(head, seed)
        data[:len(head)] = head
        packed = bytearray()
        for p in range(0, len(data), CHUNK):
            stream = lzo1x_store(bytes(data[p:p + CHUNK]))
            packed += len(stream).to_bytes(4, "little") + stream
        start = (header.flag - t) & 0xFF
        # Spelled in the client's code page, as its own archives spell their Korean names (ASCII stays as it was).
        desc = _encode_descriptor(seed, name.replace("/", "\\").encode(PATH_CODEC), len(packed), len(files[name]),
                                  key_field, key_byte, table, start)
        out += desc + packed
    with open(out_path, "wb") as f:
        f.write(out)
    return out_path


def build_update(base_path, out_path, files, table, seed_source=os.urandom):
    """Write an update archive that the client opens after base_path, holding files {path: bytes}.

    It reuses the base archive's header values and one of its descriptor key fields, so every descriptor
    decrypts with a key byte recovered from the base itself.
    """
    with Pak(base_path, table) as base:
        idx = next(iter(base.key_bytes))
        key_field = base.key_fields[idx]
        key_byte = base.key_bytes[idx]
        template = base.header
        base.file.seek(0)
        lead = base.file.read(HEADER_OFFSET)
    return write_pak(out_path, files, table, key_byte, key_field, template, lead, seed_source)


def rebuild_pak(base_path, out_path, replacements, table):
    """Copy an archive, swapping the data of the entries named in replacements {path: bytes}.

    Everything else stays as it was: the 32 leading bytes, the header and whatever sits between the header and
    the first entry, and every other entry's descriptor and data, byte for byte. A replaced entry keeps its
    position (the descriptor table walk depends on it) and its original key field, so it decrypts with the
    same key byte as before, and its original entry seed, so the same input always gives the same file.
    """
    wanted = {name.replace("/", "\\").lower(): data for name, data in replacements.items()}
    with Pak(base_path, table) as base:
        base.file.seek(0)
        out = bytearray(base.file.read(base.header.first))     # lead, header and filler before the first entry
        done = set()
        for e in base.entries:
            base.file.seek(e.offset - DESC_SIZE)
            raw = base.file.read(DESC_SIZE + e.packed)
            key = e.name.lower()
            if key not in wanted:
                out += raw
                continue
            data = bytearray(wanted[key])
            seed = e.seed
            head = bytearray(data[:MASKED_PREFIX])
            mask(head, seed)
            data[:len(head)] = head
            packed = bytearray()
            for p in range(0, len(data), CHUNK):
                stream = lzo1x_store(bytes(data[p:p + CHUNK]))
                packed += len(stream).to_bytes(4, "little") + stream
            key_field = raw[4:12]
            key_byte = base.key_bytes[_key_index(raw)]
            start = (base.header.flag - e.index) & 0xFF
            out += _encode_descriptor(seed, e.name.encode(PATH_CODEC), len(packed), len(wanted[key]),
                                      key_field, key_byte, table, start)
            out += packed
            done.add(key)
    missing = set(wanted) - done
    if missing:
        raise PakError("not in %s: %s" % (base_path, ", ".join(sorted(missing))))
    with open(out_path, "wb") as f:
        f.write(out)
    return out_path
