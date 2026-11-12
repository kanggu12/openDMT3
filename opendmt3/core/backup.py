"""Keep the game folder's originals so every change the setup makes can be undone.

Before the setup first writes a file, the file as it was (or the fact that it did not exist) is recorded in
backup\\openDMT3.json, and an existing file is copied to backup\\ under the same relative path. Restoring
puts every recorded file back as it was and removes the ones that did not exist, with the folders that were made
for them once they are empty.

Copies are written under a temporary name and then renamed, both into backup\\ and back into the game folder,
so a copy cut short (a full disk, a closed window) is never taken for a whole one.

A copy that is already in backup\\ when a file is first recorded is taken as the original: that is how a
folder set up by hand before this tool existed keeps its real originals.

Removing openDMT3 puts everything back and then forgets: it takes out the copies this tool made itself (marked
"copied" in the list) and the list, and leaves every other copy where it is. Copies found already in backup\\, and
copies listed without a mark (the earliest versions marked none), stay: nothing here can tell them from a copy
someone made by hand, and an original is never thrown away on a guess. A copy that is not the file the game has
again by then is not an original any more: it is renamed (NOT_ORIGINAL), so no later PLAY takes it for one.

The list is read as a stranger's: a game folder can come from anyone, and so can its backup\\. Only plain paths
inside the game folder are taken from it (no drive, no "..", no other separator), and no file is put back, removed
or renamed when a link or junction on its way leads out of the game folder or out of backup\\.
"""

import json
import logging
import os
import shutil
import stat

from opendmt3.core.game import BACKUP_DIR, GameError, sha256_file

MANIFEST = "openDMT3.json"
# Added to the name of a copy in backup\\ that turned out not to be the original (forget()).
NOT_ORIGINAL = ".not-the-original"
# Characters Windows refuses in a name, and the drive and stream mark (":"), which would take a path elsewhere.
_NOT_IN_A_NAME = set('<>:"|?*\\')
# Far longer than any path the setup records; a longer one is no game file.
_LONGEST = 400

log = logging.getLogger(__name__)


def plain_path(key):
    """True when a recorded path is a plain path inside the game folder, as the setup writes them: parts with "/"
    between them, none empty, "." or "..", none with a drive, a backslash, a control character or a character
    Windows refuses, and none ending in a dot or a space (Windows drops those, so two spellings would meet)."""
    if not isinstance(key, str) or not key or len(key) > _LONGEST:
        return False
    for part in key.split("/"):
        if part in ("", ".", "..") or part[-1] in ". " or part[0] == " ":
            return False
        if any(c in _NOT_IN_A_NAME or ord(c) < 32 for c in part):
            return False
    return True


def _inside(path, base):
    """True when the folder path is in, links and junctions followed, is base or a folder below it."""
    folder = os.path.normcase(os.path.realpath(os.path.dirname(path)))
    root = os.path.normcase(os.path.realpath(base))
    return folder == root or folder.startswith(root.rstrip(os.sep) + os.sep)


def _gone(path):
    """Delete a file if it is there (made writable first when Windows has it read-only, as files from a CD often
    are, and their copies with them); True when it is not there afterwards."""
    if not os.path.lexists(path):
        return True
    try:
        try:
            os.remove(path)
        except PermissionError:
            # Write added to the rights it has: Windows clears its read-only flag, and elsewhere the file keeps
            # being readable if it still will not go (S_IWRITE alone would leave it write-only there).
            os.chmod(path, stat.S_IMODE(os.stat(path).st_mode) | stat.S_IWRITE)
            os.remove(path)
    except OSError:
        return False
    return True


class Backup:
    def __init__(self, game):
        self.game = game
        self.dir = game.path(BACKUP_DIR)
        self.manifest_path = os.path.join(self.dir, MANIFEST)
        self.files = {}
        # Empty folders the setup made on their own (without a recorded file in them), "/" separated.
        self.folders = []
        if os.path.isfile(self.manifest_path):
            with open(self.manifest_path, encoding="utf-8") as f:
                data = json.load(f)
            self._take(data if isinstance(data, dict) else {})

    def _take(self, data):
        """The list's entries that are this tool's kind: plain paths inside the game folder with a record of whether
        the file existed. Anything else is left out (and goes at the next save), so nothing here acts on it."""
        files = data.get("files")
        for key, entry in (files.items() if isinstance(files, dict) else ()):
            if not plain_path(key) or not isinstance(entry, dict) or not isinstance(entry.get("existed"), bool):
                log.warning("backup list: left out an entry that is not a file of the game folder: %r", key)
                continue
            # The folders made for a new file are paths too, read the same way (left as they are when absent).
            if "made_folders" in entry:
                made = entry["made_folders"]
                entry["made_folders"] = [f for f in made if plain_path(f)] if isinstance(made, list) else []
            self.files[key] = entry
        folders = data.get("folders")
        self.folders = [f for f in folders if plain_path(f)] if isinstance(folders, list) else []

    def _paths(self, key):
        """(the file in the game folder, its copy in backup\\) for a recorded path, or None when a link or junction
        on the way leads out of the game folder or out of backup\\: such a file is not this tool's to touch."""
        parts = key.split("/")
        live, kept = self.game.path(*parts), os.path.join(self.dir, *parts)
        if not _inside(live, self.game.root) or not _inside(kept, self.dir):
            log.warning("backup list: %s leads out of the game folder through a link; it is left alone", key)
            return None
        return live, kept

    def _save(self):
        os.makedirs(self.dir, exist_ok=True)
        tmp = self.manifest_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "files": self.files, "folders": self.folders}, f, indent=2, sort_keys=True)
        os.replace(tmp, self.manifest_path)

    @staticmethod
    def _key(rel):
        # One spelling for every path, whatever separator the caller used.
        return rel.replace("\\", "/")

    @staticmethod
    def _copy(src, dst):
        """Copy src to dst through a temporary file beside dst, so dst is either the old file or a whole copy."""
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + ".opendmt3-tmp"
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)

    def _missing_folders(self, key):
        """The folders above a game-folder file that do not exist yet, deepest first (relative, "/" separated)."""
        parts = key.split("/")[:-1]
        missing = []
        while parts:
            if os.path.isdir(self.game.path(*parts)):
                break
            missing.append("/".join(parts))
            parts = parts[:-1]
        return missing

    def protect(self, rel):
        """Record a file before its first change; copy it into backup\\ unless a copy is already there."""
        key = self._key(rel)
        if key in self.files:
            return
        live = self.game.path(*key.split("/"))
        kept = os.path.join(self.dir, *key.split("/"))
        if os.path.isfile(kept):
            self.files[key] = {"existed": True, "sha256": sha256_file(kept)}
        elif os.path.isfile(live):
            self._copy(live, kept)
            # "copied": this tool made the copy, so forget() may take it away again once the file is back.
            self.files[key] = {"existed": True, "sha256": sha256_file(kept), "copied": True}
        else:
            # The folders the new file will need are noted too, so restoring can take them away again.
            self.files[key] = {"existed": False, "sha256": None, "made_folders": self._missing_folders(key)}
        self._save()

    def protect_folder(self, rel):
        """Record a folder the setup is about to make (and the missing ones above it), so restoring removes it."""
        key = self._key(rel).rstrip("/")
        # The folder itself is the first "missing folder above" a name inside it.
        missing = [f for f in self._missing_folders(key + "/-") if f not in self.folders]
        if missing:
            self.folders += missing
            self._save()

    def original(self, rel):
        """Path of the file as it was before the setup changed it (the live file if it was never changed)."""
        key = self._key(rel)
        entry = self.files.get(key)
        if entry and entry["existed"]:
            return os.path.join(self.dir, *key.split("/"))
        return self.game.path(*key.split("/"))

    def changed(self, rel):
        """True when the live file differs from the recorded original."""
        key = self._key(rel)
        entry = self.files.get(key)
        paths = self._paths(key) if entry else None
        if not paths:
            return False
        live = paths[0]
        if not entry["existed"]:
            return os.path.exists(live)
        return not os.path.isfile(live) or sha256_file(live) != entry["sha256"]

    def put_back(self, rel):
        """Return one file to its recorded state."""
        key = self._key(rel)
        entry = self.files.get(key)
        paths = self._paths(key) if entry else None
        if not paths:
            return False
        live, kept = paths
        if entry["existed"]:
            if not os.path.isfile(kept):
                # Said in words instead of a bare "file not found": the list names a copy that is gone.
                raise GameError("the original of %s is not in backup\\ any more" % key, "error.game.original_missing",
                                path=key)
            self._copy(kept, live)
        elif os.path.isfile(live):
            os.remove(live)
        return True

    def _remove_made_folders(self):
        """Remove the folders the setup made for new files, once nothing is left in them (deepest first)."""
        folders = set(self.folders)
        for entry in self.files.values():
            folders.update(entry.get("made_folders") or ())
        # Deeper paths have more separators; removing them first lets their parents become empty.
        for rel in sorted(folders, key=lambda r: r.count("/"), reverse=True):
            path = self.game.path(*rel.split("/"))
            if not _inside(path, self.game.root):
                # A link on the way leads out of the game folder: not a folder the setup made.
                continue
            try:
                os.rmdir(path)
            except OSError:
                # Not empty (the game wrote something of its own there) or already gone: leave it.
                pass

    def restore_all(self):
        """Put every recorded file back; returns the relative paths handled."""
        done = []
        for key in sorted(self.files):
            if self.changed(key) and self.put_back(key):
                done.append(key)
        self._remove_made_folders()
        return done

    def still_changed(self):
        """The recorded files that differ from their originals now (relative paths, sorted)."""
        return sorted(key for key in self.files if self.changed(key))

    def forget(self):
        """Take this tool's own copies and its list out of backup\\, once every file is back as it was.

        The list goes first. A removal stopped halfway (a crash, a copy Windows will not let go) then leaves only
        copies equal to the files the game has again, which a later PLAY may rightly take as the originals; a list
        naming copies that are gone would let that PLAY change a file with no copy kept at all.

        Returns the relative paths whose copies stay in backup\\ (made by someone else or listed without a mark, set
        aside as NOT_ORIGINAL, or not deletable), or None when a file is still changed: then nothing is touched,
        since the copies are the only originals left.
        """
        if self.still_changed():
            return None
        entries = dict(self.files)
        if not all(_gone(path) for path in (self.manifest_path, self.manifest_path + ".tmp")):
            # The list stays, so the copies stay with it: every one is still where the list says.
            return sorted(key for key, entry in entries.items() if entry.get("existed"))
        self.files, self.folders = {}, []
        stays, emptied = [], set()
        for key, entry in sorted(entries.items()):
            parts, paths = key.split("/"), self._paths(key)
            if not paths:
                # Leads out of the game folder through a link: nothing there is touched.
                continue
            live, kept = paths
            # A copy cut short by a crash, beside the copy it was going to be (in backup\\, or in the game folder
            # on the way back): never an original, and never the game's.
            for leftover in (kept + ".opendmt3-tmp", live + ".opendmt3-tmp"):
                _gone(leftover)
            if not entry.get("existed") or not os.path.isfile(kept):
                continue
            digest = sha256_file(kept)
            # Only a copy this tool made, and only while it is still the very copy it listed.
            if entry.get("copied") and digest == entry.get("sha256") and _gone(kept):
                # Its folder inside backup\\ (and the ones above) may be empty now.
                for depth in range(len(parts) - 1, 0, -1):
                    emptied.add("/".join(parts[:depth]))
                continue
            if not os.path.isfile(live) or sha256_file(live) != digest:
                # Not the file the game has again, so not its original: renamed, so no later PLAY takes it for one.
                aside, n = kept + NOT_ORIGINAL, 1
                while os.path.lexists(aside):
                    aside, n = "%s%s-%d" % (kept, NOT_ORIGINAL, n), n + 1
                try:
                    os.replace(kept, aside)
                except OSError:
                    pass
            stays.append(key)
        # Deepest first, so a parent is empty by the time its turn comes; rmdir leaves any folder with something in it.
        for rel in sorted(emptied, key=lambda r: r.count("/"), reverse=True) + [""]:
            try:
                os.rmdir(os.path.join(self.dir, *rel.split("/")) if rel else self.dir)
            except OSError:
                # Not empty (someone else's files, or a copy that stays) or already gone: it stays as it is.
                pass
        return stays
