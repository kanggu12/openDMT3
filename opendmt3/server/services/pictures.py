"""The pictures a server keeps (the jackets, the DJ cards' icons, plates and patterns), in one form whichever way they
came: decoded by Pillow, made RGBA, stripped of everything but their pixels, and encoded again as PNG.

Read from a game folder or taken from a song list, a picture ends up as the same bytes: encoding the pixels of a
picture already in this form gives it back exactly (measured on a whole game folder: 924 pictures, every one the same
the second time). A song list's pictures are untrusted input, so a picture that is not a PNG, is larger than its kind
may be, or does not decode is refused, never kept.

A picture that is in the one form already (plain: nothing but its header, its pixels and its end, 8-bit RGBA, its
pixel data one whole stream with nothing after it) is kept as it came, once it has been decoded and checked like any
other: encoding it again would give the same pixels, and cost 69 % of taking a song list (925 pictures, 1.9 s of
2.6). Anything else, a text chunk, a colour profile, another colour type, a byte after the end, is encoded again.

A song list's pictures are converted side by side (in_order): Pillow decodes, shrinks and encodes in its C code
without the interpreter's lock, so up to THREADS pictures convert at once on as many cores while the next ones are
read, and each comes back in its place in the list, the same bytes as one after another.
"""

import collections
import concurrent.futures
import io
import math
import os
import struct
import zlib

# The decoder's own limit for one picture, in pixels: far above any picture here (the largest is 204 x 64), far below
# what a crafted header could claim.
MAX_PIXELS = 1 << 20
# The largest each kind may be, in pixels across and down. Jackets are made this size when a game folder is read (the
# game's are 256 px); the DJ cards' pictures are kept as the game has them (icons 104 x 64, plates and patterns
# 204 x 64), with room above for another build of the game.
MOST = {"jacket": (160, 160), "icon": (512, 256), "plate": (512, 256), "pattern": (512, 256)}


# What every PNG starts with.
SIGNATURE = b"\x89PNG\r\n\x1a\n"
# The header of a picture in the one form, after its size: 8 bits a sample, colour type 6 (RGBA), zlib's compression,
# the one filter method, no interlacing.
PLAIN_HEADER = (8, 6, 0, 0, 0)


# Pictures converted at once at most (in_order), and never more than the cores this process may use (cores()).
THREADS = 8
# Pictures read ahead of the one handed back, for each thread: enough to keep every thread busy, few enough that a
# list of hundreds is never held in memory whole.
AHEAD = 2


class PictureError(ValueError):
    """A picture that cannot be kept: why, in a few words."""


def cores():
    """The cores this process may run on: those it is allowed on (os.sched_getaffinity, where the system has it),
    within its container's processor quota (a container run with --cpus), at least one."""
    try:
        count = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        # Windows and macOS: every core of the machine.
        count = os.cpu_count() or 1
    quota = _quota()
    if quota is not None:
        # A quota of 2.5 cores lets three threads run part of the time: rounded up.
        count = min(count, max(1, math.ceil(quota)))
    return max(1, count)


def _quota():
    """This process's processor quota in cores (cgroup v2's cpu.max, else v1's cfs quota and period), or None when it
    has none (or the system says nothing of one)."""
    try:
        with open("/sys/fs/cgroup/cpu.max") as f:
            quota, period = f.read().split()[:2]
        # "max": no quota.
        return None if quota == "max" else int(quota) / int(period)
    except (OSError, ValueError):
        pass
    try:
        with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us") as f:
            quota = int(f.read())
        with open("/sys/fs/cgroup/cpu/cpu.cfs_period_us") as f:
            period = int(f.read())
    except (OSError, ValueError):
        return None
    # -1: no quota.
    return quota / period if quota > 0 and period > 0 else None


def threads():
    """How many pictures in_order converts at once here: THREADS, or fewer when this process has fewer cores."""
    return min(THREADS, cores())


def in_order(items, convert, workers=None):
    """(tag, converted) for each (tag, data) of `items` in their order, `converted` being convert(data) or the
    PictureError it raised (the caller says why and leaves that one out, or refuses, as it would one at a time).
    `convert` runs on up to `workers` threads at once (threads()), the items read here, on the caller's thread, ahead
    of the one handed back by at most AHEAD a thread (the game's files and a zip are read from one position, one at a
    time). What happens is what one after another would do: an error reading an item comes after every item read
    before it is handed back, and any error converting one other than a PictureError is raised at that item's turn,
    the rest given up. One worker: each converted here, one after another."""
    workers = threads() if workers is None else max(1, workers)
    if workers == 1:
        for tag, data in items:
            try:
                yield tag, convert(data)
            except PictureError as e:
                yield tag, e
        return
    # Pillow's formats registered here, once, before any thread opens a picture.
    from PIL import Image
    Image.preinit()

    def guarded(data):
        # A refusal is the item's answer; anything else is raised at its turn.
        try:
            return convert(data)
        except PictureError as e:
            return e
    pool = concurrent.futures.ThreadPoolExecutor(workers, thread_name_prefix="opendmt3-pictures")
    waiting = collections.deque()
    reading = iter(items)
    try:
        while True:
            try:
                tag, data = next(reading)
            except StopIteration:
                break
            except Exception:
                # The items read before it first, in their order, as one after another would have handed them back
                # before it met this one; then the error (unless the caller stopped at one of them).
                while waiting:
                    tag, future = waiting.popleft()
                    yield tag, future.result()
                raise
            waiting.append((tag, pool.submit(guarded, data)))
            if len(waiting) >= workers * AHEAD:
                # The oldest handed back, in its place, before more is read.
                tag, future = waiting.popleft()
                yield tag, future.result()
        while waiting:
            tag, future = waiting.popleft()
            yield tag, future.result()
    finally:
        # Given up (an error, or the caller stopped): what was not started never starts, and no thread is left behind.
        pool.shutdown(wait=True, cancel_futures=True)


def plain(data, width, height):
    """True when `data` is a PNG of `width` x `height` pixels in the one form already: the signature, then its header
    (IHDR, PLAIN_HEADER), its pixel data (IDAT) and its end (IEND) and no other chunk, each with its CRC right, nothing
    after the end; the pixel data one zlib stream that ends exactly where the data does and holds exactly the rows the
    header says, each starting with one of the five filter types. Read with limits: no more than one picture's rows
    are ever inflated."""
    if not data.startswith(SIGNATURE):
        return False
    at, chunks, pixels = len(SIGNATURE), [], []
    while at < len(data):
        if at + 12 > len(data):
            # Not even a whole chunk's length, type and CRC left.
            return False
        length, kind = struct.unpack(">I4s", data[at:at + 8])
        end = at + 12 + length
        if end > len(data):
            return False
        body = data[at + 8:at + 8 + length]
        # The chunk's CRC covers its type and its data.
        if zlib.crc32(kind + body) != struct.unpack(">I", data[end - 4:end])[0]:
            return False
        chunks.append(kind)
        if kind == b"IDAT":
            pixels.append(body)
        elif kind == b"IHDR":
            if length != 13 or struct.unpack(">IIBBBBB", body) != (width, height) + PLAIN_HEADER:
                return False
        elif kind != b"IEND" or length:
            # Any other chunk (text, gamma, a colour profile, a palette...), or an end with data, is not plain.
            return False
        at = end
        if kind == b"IEND":
            break
    # The header first, the pixel data next, the end last and nothing after it.
    if at != len(data) or len(chunks) < 3 or chunks[0] != b"IHDR" or chunks[-1] != b"IEND" or \
            set(chunks[1:-1]) != {b"IDAT"}:
        return False
    rows, row = height, 1 + 4 * width
    stream = zlib.decompressobj()
    try:
        # One more byte than the rows may hold: a stream that holds more is not this picture's.
        raw = stream.decompress(b"".join(pixels), rows * row + 1)
    except zlib.error:
        return False
    if len(raw) != rows * row or not stream.eof or stream.unused_data or stream.unconsumed_tail:
        return False
    # Each row's first byte is its filter: 0 to 4.
    return max(raw[0::row]) <= 4


def available():
    """True when Pillow is there to decode and encode pictures (the server's image and the launcher have it)."""
    try:
        from PIL import Image
    except ImportError:
        return False
    # Imported: the module is there to use.
    return Image is not None


def canonical(data, kind, shrink=False):
    """The picture's bytes in the server's one form: PNG, RGBA, nothing but its pixels, at most MOST[kind] across and
    down. With shrink a larger picture is made smaller to fit, keeping its shape (a jacket read from a game folder);
    without it a larger one is refused. PictureError when it is no PNG, too large, or does not decode."""
    from PIL import Image
    most = MOST[kind]
    try:
        with Image.open(io.BytesIO(data)) as picture:
            # Only PNG: what the game keeps and what this module writes. Pillow knows many formats; none is wanted.
            if picture.format != "PNG":
                raise PictureError("not a PNG picture")
            width, height = picture.size
            # Checked before a byte of the pixels is decoded: the header alone says the size.
            if width < 1 or height < 1 or width * height > MAX_PIXELS:
                raise PictureError("a picture of %d x %d pixels" % (width, height))
            if (width > most[0] or height > most[1]) and not shrink:
                raise PictureError("larger than %d x %d pixels" % most)
            picture.load()
            if width <= most[0] and height <= most[1] and plain(data, width, height):
                # Decoded and checked, and in the one form already: kept as it came (see above).
                return data
            if shrink:
                # Made smaller to fit, its shape kept; one already small enough stays as it is.
                picture.thumbnail(most)
            rgba = picture.convert("RGBA")
    except PictureError:
        raise
    except Exception as e:  # noqa: BLE001  (Pillow raises many kinds for a broken picture; each is one refusal)
        raise PictureError("it does not decode (%s)" % type(e).__name__) from e
    # A new picture from the pixels alone: no text, colour profile, gamma or other chunk of the one that came.
    clean = Image.frombytes("RGBA", rgba.size, rgba.tobytes())
    out = io.BytesIO()
    # Pillow's default compression: as small as its best within a few percent, four times as fast.
    clean.save(out, "PNG")
    return out.getvalue()
