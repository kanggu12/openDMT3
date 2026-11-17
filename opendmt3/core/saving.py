"""Writing a small file whole, the way the launcher keeps its settings (launcher.json, the sound file both it and the
game write, the server an installer leaves): a temporary file beside it, flushed to the disk, then swapped in. A
crash or a power cut leaves the old file or the new one, never half of one and never an empty one (a swap whose new
file was still only in the system's memory could leave a file of no length on NTFS after a power cut).

Only the standard library: the launcher, the installer and the tests all use it.
"""

import os
import tempfile
import time


def write_whole(path, data, prefix=".opendmt3-"):
    """`data` (bytes) as the file at `path`, swapped in whole once it is on the disk; the folder is made when it is not
    there. The temporary file beside it starts with `prefix` (the name a clean-up knows it by), and goes when the
    write fails."""
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=prefix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            # Out of Python's buffer, then out of the system's onto the disk, before the swap points the name at it.
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        # Nothing half-made stays beside the file.
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def set_aside(path, now=None):
    """Keep a file that cannot be read beside it as it was (<name>.broken-<date>-<time>, a number after it when one of
    that second is there already), so that a new one can take its place; returns the name it is kept under, or None
    when it was gone already (another start set it aside a moment ago)."""
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    aside, n = "%s.broken-%s" % (path, stamp), 1
    while os.path.exists(aside):
        # Two in one second (a command run again at once): neither written over.
        n += 1
        aside = "%s.broken-%s-%d" % (path, stamp, n)
    try:
        os.replace(path, aside)
    except FileNotFoundError:
        return None
    return aside
