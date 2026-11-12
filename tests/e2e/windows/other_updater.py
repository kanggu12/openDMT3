"""A copy of an update feed whose whole package carries another Update.exe, for tests/e2e/windows/update.sh.

    python3 tests/e2e/windows/other_updater.py FEED_DIR OUT_DIR

The two versions update.sh packs come from one launcher and one vpk, so both carry the same Update.exe (the package's
lib/app/Squirrel.exe): a check that Update.exe is as it was after a refused update would pass whether or not the
refused package's had been put in its place. The copy made here differs in that one file (a few bytes more at its
end), and its list (releases.win.json, RELEASES) gives the changed package's own size and hashes, as a feed gives
them for the package it hands out. It carries no signature: what it is for is to be refused, with the installed
Update.exe left as it was. OUT_DIR gets the changed package and the two lists, nothing else. Prints the package's
file name.
"""

import hashlib
import json
import os
import sys
import zipfile

# The package's copy of Velopack's updater, which Velopack's own download writes over the installed Update.exe.
UPDATER = "lib/app/Squirrel.exe"
# What the copy's updater ends with: other bytes, so another hash, and nothing a test ever runs.
MORE = b"\0" * 16


def other_package(source, target):
    """Write `source` again as `target`, every entry as it is but the updater, which gets a few bytes more."""
    changed = 0
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as new:
        for entry in old.infolist():
            data = old.read(entry)
            if entry.filename == UPDATER:
                data += MORE
                changed += 1
            # Under the same name and time: the package differs in the one file's bytes alone.
            new.writestr(entry, data)
    if changed != 1:
        raise SystemExit("%s has %d files named %s, not one" % (source, changed, UPDATER))


def hashes(path):
    """(size, SHA-1, SHA-256) of a file, the hashes in capitals as vpk writes them."""
    sha1, sha256 = hashlib.sha1(), hashlib.sha256()
    with open(path, "rb") as f:
        for piece in iter(lambda: f.read(1 << 20), b""):
            sha1.update(piece)
            sha256.update(piece)
    return os.path.getsize(path), sha1.hexdigest().upper(), sha256.hexdigest().upper()


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    feed, out = argv
    os.makedirs(out)
    packages = sorted(name for name in os.listdir(feed) if name.endswith("-full.nupkg"))
    if len(packages) != 1:
        raise SystemExit("%s holds %d whole packages, not one" % (feed, len(packages)))
    name = packages[0]
    other_package(os.path.join(feed, name), os.path.join(out, name))
    size, sha1, sha256 = hashes(os.path.join(out, name))
    # The list Velopack reads: the package's entry with the changed package's own size and hashes.
    with open(os.path.join(feed, "releases.win.json"), encoding="utf-8-sig") as f:
        listed = json.load(f)
    entries = [asset for asset in listed["Assets"] if asset["FileName"] == name]
    if len(entries) != 1:
        raise SystemExit("releases.win.json lists %s %d times, not once" % (name, len(entries)))
    entries[0].update(Size=size, SHA1=sha1, SHA256=sha256)
    with open(os.path.join(out, "releases.win.json"), "w", encoding="utf-8") as f:
        json.dump(listed, f)
    # The older readers' list, in its own form (a line per package: SHA-1, name, size).
    with open(os.path.join(feed, "RELEASES"), encoding="utf-8-sig") as f:
        lines = [line.split() for line in f.read().splitlines() if line.strip()]
    with open(os.path.join(out, "RELEASES"), "w", encoding="utf-8-sig") as f:
        f.write("\n".join(" ".join([sha1, name, str(size)] if line[1] == name else line) for line in lines))
    print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
