"""The previous release's full update package, kept in the build's releases folder so vpk makes a delta package from it
(packaging/windows/build.sh, step 3): Velopack's own way of updating, where a launcher downloads only what changed.

    python3 packaging/windows/previous.py RELEASES_DIR VERSION [FOLDER_OR_PACKAGE...]

Leaves in RELEASES_DIR the newest full package (openDMT3-<version>-full.nupkg) of a version before VERSION, found there
(the last build into the same folder) or in the folders and packages given (the release before, kept on the release
machine), and nothing else: the other files there are an earlier build's (its installer, its feed files, its other
packages and their signatures), which vpk would otherwise list in the new feed.

A package Velopack puts together from a delta is zipped again, so a launcher checks it by the files it holds
(core/signing.py). Prints the version kept, or "none".
"""

import os
import re
import shutil
import sys

# A full package's file name, as vpk names it: openDMT3-<version>-full.nupkg.
FULL = re.compile(r"^openDMT3-(?P<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)-full\.nupkg$")


def order(version):
    """A version as SemVer orders it (MAJOR.MINOR.PATCH, a pre-release before its release, its parts compared number by
    number and word by word), as something Python compares."""
    core, _, pre = version.partition("+")[0].partition("-")
    numbers = tuple(int(n) for n in core.split("."))
    if not pre:
        # A release comes after every pre-release of its version.
        return numbers, (1,)
    # Numbers come before words, and compare as numbers.
    parts = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))
    return numbers, (0,) + parts


def candidates(places):
    """{version: path} of the full packages in these folders and among these files."""
    found = {}
    for place in places:
        paths = ([os.path.join(place, name) for name in sorted(os.listdir(place))] if os.path.isdir(place)
                 else [place] if os.path.isfile(place) else [])
        for path in paths:
            match = FULL.match(os.path.basename(path))
            if match:
                found.setdefault(match.group("version"), path)
    return found


def keep_previous(releases, version, sources=()):
    """Leave in `releases` only the newest full package before `version`, from there or from `sources`; returns its
    version, or None."""
    os.makedirs(releases, exist_ok=True)
    found = candidates([releases] + list(sources))
    usable = [v for v in found if order(v) < order(version)]
    kept = max(usable, key=order) if usable else None
    keep_name = None
    if kept is not None:
        keep_name = os.path.basename(found[kept])
        if os.path.dirname(os.path.abspath(found[kept])) != os.path.abspath(releases):
            # From the release before: copied in beside where the new one goes.
            shutil.copyfile(found[kept], os.path.join(releases, keep_name))
    for name in os.listdir(releases):
        path = os.path.join(releases, name)
        if name != keep_name and os.path.isfile(path):
            # An earlier build's file: the installer, the feed, another package, a signature.
            os.remove(path)
    return kept


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip().splitlines()[3].strip(), file=sys.stderr)
        return 2
    kept = keep_previous(argv[0], argv[1], argv[2:])
    print(kept or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
