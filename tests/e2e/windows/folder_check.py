"""A game folder before and after removing openDMT3, for tests/e2e/windows/remove.sh. Plain Python, no packages.

  folder_check.py snapshot GAME_DIR OUT.json
      every file's sha256 (a link is recorded as a link, never followed), relative and "/" separated
  folder_check.py removed GAME_DIR LIST.json BEFORE.json
      the folder as removing leaves it: every file in openDMT3's list (LIST.json, a copy of backup\\openDMT3.json
      taken before) back as the list says, every file openDMT3 added gone, the card file gone, the list and
      openDMT3's own copies gone from backup\\, every other copy still there, no copy cut short left, no note,
      and every file outside the list as it was in BEFORE.json
  folder_check.py unchanged GAME_DIR BEFORE.json
      removing while the game was open: nothing changed but a note in backup\\ that names every changed file

Prints one line counting what it checked; exits 1 with the problems listed otherwise.
"""

import hashlib
import json
import os
import sys

CARD = "openDMT3-card.txt"
NOTE = "README-openDMT3.txt"


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        # In blocks: the game's archives are large.
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def files(root):
    """{relative path: sha256 or "link"} for every file under root."""
    found = {}
    for folder, _, names in os.walk(root):
        for name in names:
            path = os.path.join(folder, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            # A link into the original archives is never read through: only that it is a link counts.
            found[rel] = "link" if os.path.islink(path) else sha256(path)
    return found


def snapshot(root, out):
    with open(out, "w", encoding="utf-8") as f:
        json.dump(files(root), f, indent=1, sort_keys=True)
    print("snapshot: %d files" % len(files(root)))
    return []


def removed(root, listed, before):
    with open(listed, encoding="utf-8") as f:
        entries = json.load(f)["files"]
    with open(before, encoding="utf-8") as f:
        was = json.load(f)
    now, problems = files(root), []
    back = gone = kept = others = 0
    for key, entry in sorted(entries.items()):
        live = os.path.join(root, *key.split("/"))
        if entry["existed"]:
            if not os.path.isfile(live) or os.path.islink(live) or sha256(live) != entry["sha256"]:
                problems.append("not back as it was: " + key)
            else:
                back += 1
            copy = os.path.join(root, "backup", *key.split("/"))
            if entry.get("copied") and os.path.lexists(copy):
                problems.append("openDMT3's own copy is still in backup: " + key)
            elif not entry.get("copied"):
                if os.path.isfile(copy):
                    kept += 1
                else:
                    problems.append("an original openDMT3 did not copy is gone from backup: " + key)
        elif os.path.lexists(live):
            problems.append("still there, though openDMT3 added it: " + key)
        else:
            gone += 1
    for rel in (CARD, "backup/openDMT3.json", "backup/openDMT3.json.tmp", "backup/" + NOTE):
        if os.path.lexists(os.path.join(root, *rel.split("/"))):
            problems.append("still there: " + rel)
    for rel in now:
        if rel.endswith(".opendmt3-tmp"):
            problems.append("a copy cut short is left: " + rel)
    # Everything removing has no business with is exactly as it was.
    for rel, digest in sorted(was.items()):
        if rel in entries or rel == CARD or rel.startswith("backup/"):
            continue
        others += 1
        if now.get(rel) != digest:
            problems.append("changed, though not openDMT3's: " + rel)
    print("removed: %d file(s) back, %d added file(s) gone, %d original(s) kept in backup, %d other file(s) as they "
          "were, %d listed" % (back, gone, kept, others, len(entries)))
    return problems


def unchanged(root, before):
    with open(before, encoding="utf-8") as f:
        was = json.load(f)
    now, problems = files(root), []
    note = "backup/" + NOTE
    if note not in now:
        problems.append("no note in backup")
    for rel in sorted(set(was) | set(now)):
        if rel != note and was.get(rel) != now.get(rel):
            problems.append("changed while the game was open: " + rel)
    named = 0
    if note in now:
        with open(os.path.join(root, *note.split("/")), encoding="utf-8-sig") as f:
            text = f.read()
        with open(os.path.join(root, "backup", "openDMT3.json"), encoding="utf-8") as f:
            entries = json.load(f)["files"]
        for key in entries:
            # Every file still changed is named in the note, with Windows' separators.
            path = os.path.join(root, *key.split("/"))
            still = (os.path.lexists(path) if not entries[key]["existed"]
                     else not os.path.isfile(path) or sha256(path) != entries[key]["sha256"])
            if still:
                named += 1
                if key.replace("/", "\\") not in text:
                    problems.append("the note does not name " + key)
    print("unchanged: %d files as they were, the note names %d changed file(s)" % (len(was), named))
    return problems


def main(argv):
    job = argv[1] if len(argv) > 1 else ""
    jobs = {"snapshot": (snapshot, 4), "removed": (removed, 5), "unchanged": (unchanged, 4)}
    if job not in jobs or len(argv) != jobs[job][1]:
        sys.exit(__doc__)
    problems = jobs[job][0](*argv[2:])
    for problem in problems:
        print("  problem: " + problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
