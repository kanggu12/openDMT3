"""What a path on the server PC is, by its content, and the song list read from it, whatever form it came in:

  a game folder          at the path or up to four levels below it (a cabinet's "drive d" copy included): read where
                         it is, read only (catalog.py)
  an archive             .zip, .7z, .rar or anything else the official 7-Zip opens; a split one by its first part
                         with every part in one folder; an archive inside an archive (two levels at most). Its entries
                         are listed first; only the files the server needs (the client, and the song list's, the
                         jackets' and the DJ cards' files) are taken out, into a folder of the reading's own, read
                         there and removed
  a song list            saved by openDMT3 (the launcher's Save the song list..., ./dmt3 catalog --save): taken in
                         after every check (songlist.py)
  a part of a game folder  one file of it (the client, one of the game's files): the game folder around it, if any

Everything taken in is untrusted (as OpenDMTQ's import treats it): an archive's entries are listed and judged before
anything is unpacked, an entry with an absolute path, a drive letter, "..", a device name, a stream, a link or a name
too long is refused, the entries, the nesting and the size are capped (the size against the free space), and 7-Zip
runs as a child process that writes only into a new folder of the reading's own, which is checked file by file after
it (no link, nothing else, each file the size its entry said).

look() says what a path is, as one plain line with its state (the wizard, the Status page, ./dmt3 catalog's first look);
read() reads the song list from it into a server's data folder; save() makes a song list from it.
"""

import ctypes
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
import zlib

from opendmt3.core import errors
from opendmt3.core import game as g
from opendmt3.core.errors import Worded
from opendmt3.server.services import catalog, songlist

# The 7-Zip that opens archives: the one OPENDMT3_7ZIP names, else the official 7-Zip's 7zz (in the server's image), else
# a 7z or 7za on PATH (a distribution's p7zip opens .7z and .zip; only the official 7-Zip opens RAR5).
SEVEN_ZIP_ENV = "OPENDMT3_7ZIP"
SEVEN_ZIP_NAMES = ("7zz", "7z", "7za")
# The names of archives, for a look through a folder (a path given is judged by its content whatever its name).
ARCHIVES = (".zip", ".7z", ".rar")
# The parts of a split archive by their names: x.7z.001, x.zip.001, x.rar.001, x.part1.rar (and x.rar with x.r00 after).
NUMBERED_PART = re.compile(r"(.+\.(?:7z|zip|rar))\.(\d{3})", re.I)
RAR_PART = re.compile(r"(.+)\.part(\d+)\.rar", re.I)
OLD_RAR_PART = re.compile(r"(.+)\.r(\d\d)", re.I)
# Words the game's archives are usually named with: in a look through a folder (Downloads holds other archives too) only
# an archive with one in its name is opened; one named on purpose is opened whatever its name.
GAME_WORDS = ("technika", "djmax", "dmt3")
# The families of the game's files the server reads (catalog.py, cards.py), and the one more a game folder is known by.
FAMILIES = ("DiscInfo", "DiscImg", "Script", "Icon", "emblem")
MARKS = ("Config",)
# A family's file names in an archive: its base and its numbered patches, in any letter case.
FAMILY_FILE = re.compile(r"(%s)(?:\d\d)?\.pak" % "|".join(FAMILIES + MARKS), re.I)
# The most entries an archive's listing may have (a whole game folder is about 1,100), the most the files the server
# needs may take (about 120 MB in a whole game folder), how deep archives may sit inside each other, and the free space
# kept beside what is taken out.
ENTRIES_MOST = 200_000
# The most a zip's central directory may take (a whole game folder's takes about 150 KB): Python's zip reader holds
# all of it in memory, an object an entry, before the entries can be counted.
DIRECTORY_MOST = 8 << 20
NEEDED_MOST = 2 << 30
NESTING_MOST = 2
SPACE_SPARE = 64 << 20
# Entry names a Windows PC (where a song list or an archive may go next) cannot hold, and the longest name kept.
DEVICES = {"con", "prn", "aux", "nul"} | {"com%d" % n for n in range(1, 10)} | {"lpt%d" % n for n in range(1, 10)}
NAME_MOST, PATH_MOST = 255, 1024
# The first bytes of the archives people pack the game in (zip, 7z, RAR 4 and 5): a file that starts so is an archive,
# damaged or whole, whatever its name.
SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08", b"7z\xbc\xaf\x27\x1c", b"Rar!\x1a\x07")
# What 7-Zip says of a file it knows no archive in ("Can not" in older builds, "Cannot" in newer ones).
NOT_AN_ARCHIVE = re.compile(r"Can ?not open the file as")
# How long a listing or an extraction may take: a whole game's archive (40 GB, solid) is listed in seconds, but the
# files the server needs may sit behind gigabytes of others in one solid block.
LIST_SECONDS = 120
EXTRACT_SECONDS = 3600
# What 7-Zip writes is looked at this often while it runs (Watch): at a gigabyte a second (zeros unpack so fast) it
# writes no more than about this share of a gigabyte past what the entries said before it is stopped, which the room
# kept beside them (SPACE_SPARE, the launcher's own) holds. The margin past the entries' bytes, and how often the
# folder itself is measured whatever 7-Zip's own count of written bytes says.
WATCH_EVERY = 0.05
WATCH_SPARE = 1 << 20
MEASURE_EVERY = 1.0
# The longest password passed to 7-Zip (in characters): far past any typed one, and well within a pipe's buffer.
PASSWORD_MOST = 1000
# The first bytes of a compressed stream that keeps its size at its end (gzip, xz, lzip): 7-Zip lists it as one file
# of that size, which may be anything, and only learns the truth once all of it is unpacked.
STREAMS = (b"\x1f\x8b", b"\xfd7zXZ\x00", b"LZIP")
# Windows' users under WSL, and the profiles there that are Windows' own (no person keeps the game in them).
WINDOWS_USERS = "/mnt/c/Users"
WINDOWS_PROFILES = ("all users", "default", "default user", "public", "defaultapppool", "wdagutilityaccount")
# What a look through the server PC's usual places looks at (a home's Downloads holds thousands of files), and for how
# long at most (Windows' drives under WSL list slowly). Each one found is looked at (a game folder's look reads its
# files' indexes, about a second), so the list stops at LOOK_MOST.
LOOK_DEPTH = 4
LOOK_MOST = 20
LOOK_SECONDS = 6.0
# Each path's look is kept while the path stays as it was, for this long (an archive's look runs 7-Zip for a second);
# a look through the places for this long (each visit of the Status page asks again). At most LOOKS_KEPT are kept.
LOOK_LIFE, FOUND_LIFE, LOOKS_KEPT = 60.0, 10.0, 256
_looks, _found = {}, {}
# The site's requests look on several worker threads at once: each read and change of the two tables takes this lock
# (never held while a look reads the disk).
_kept_lock = threading.Lock()

# The words of a path's state, in English and Korean (the site's strings take them; the command line and the wizard
# say the English).
WORDS = {
    "source.client.original": ("original PC client", "PC 클라이언트 원본"),
    "source.client.fixed": ("PC client", "PC 클라이언트"),
    "source.client.modified": ("modified PC client", "수정된 PC 클라이언트"),
    "source.folder": ("Game folder, {client}, {n} songs: ready", "게임 폴더, {client}, 곡 {n}개: 쓸 수 있음"),
    # One of a thing has words of its own ("1 song", never "1 songs"), as the launcher's card has.
    "source.folder.one": ("Game folder, {client}, 1 song: ready", "게임 폴더, {client}, 곡 1개: 쓸 수 있음"),
    "source.archive": ("A game folder in an archive: ready", "압축 파일 안의 게임 폴더: 쓸 수 있음"),
    "source.inner": ("It holds another archive. Both are opened.", "안에 다른 압축 파일이 있습니다. 함께 엽니다."),
    "source.song_list": ("Song list saved by openDMT3, {n} songs: ready", "openDMT3가 저장한 곡 목록, 곡 {n}개: 쓸 수 있음"),
    "source.song_list.one": ("Song list saved by openDMT3, 1 song: ready", "openDMT3가 저장한 곡 목록, 곡 1개: 쓸 수 있음"),
}


def counted(key, n):
    """The words of a line that counts songs: its own for one song when the table has them."""
    return WORDS[key + ".one"] if n == 1 and key + ".one" in WORDS else WORDS[key]


class SourceError(Worded):
    """A path the server cannot read the song list from, worded for whoever gave it (errors.py)."""


def nothing():
    """The refusal of a path that holds no game: neither a game folder nor an archive holding one."""
    return SourceError("This is neither a game folder nor an archive holding one.", "error.source.nothing")


def damaged():
    """The refusal of an archive that cannot be listed or unpacked as its entries say."""
    return SourceError("This archive is damaged or not fully downloaded. Download it again.", "error.source.damaged")


def entry_refused(name):
    """The refusal of one entry of an archive by its name (shortened: it comes from the archive)."""
    shown = name if len(name) <= 80 else name[:77] + "..."
    return SourceError("An entry in this archive cannot be taken: %s" % shown, "error.source.entry", name=shown)


# ------------------------------------------------------------------------------------------------ 7-Zip

def seven_zip():
    """The 7-Zip program, or None when this PC has none."""
    named = os.environ.get(SEVEN_ZIP_ENV)
    if named:
        return named if os.path.isfile(named) else shutil.which(named)
    for name in SEVEN_ZIP_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


def seven_zip_command(args, switches=()):
    """The 7-Zip command line for args, which are 7-Zip's command, its switches, then "--" and the archive (so a name
    that starts with "-" or "@" is never read as a switch or a list): the program, the command, the switches every run
    takes (names, and the password it reads, in UTF-8 whatever the system's code page) and `switches`, then the rest.
    SourceError when this PC has no 7-Zip."""
    program = seven_zip()
    if program is None:
        raise SourceError("Opening this archive needs 7-Zip on the server PC (the server's Docker image has it).",
                          "error.source.no_7zip")
    # Every switch before the caller's "--": after it 7-Zip reads only names.
    return [program] + args[:1] + ["-sccUTF-8"] + list(switches) + args[1:]


def _password_line(password):
    """What 7-Zip reads on its standard input when an archive needs a password: the password and a line's end, in
    UTF-8. A password never typed is one no archive has, so 7-Zip says the password is wrong instead of waiting. One
    with a line break or a NUL fits on no line (nor can it be typed into 7-Zip), and one longer than a pipe surely
    holds could keep this side waiting: not this archive's password."""
    if password and (any(c in password for c in "\r\n\0") or len(password) > PASSWORD_MOST):
        raise _password_error(password)
    return ((password or "none-" + secrets.token_hex(12)) + "\n").encode("utf-8")


def popen_7zip(command, password):
    """7-Zip's command line (seven_zip_command) started as a child process, its output and errors in one pipe. The
    archive's password goes on its standard input, never on its command line, which any user of the PC can read
    while it runs (/proc on Linux, a Docker host's ps for a container's). On POSIX it gets a session of its own: a
    distribution's p7zip asks a terminal it finds before its standard input, and would wait there for a person."""
    line = _password_line(password)
    # No console window of its own on Windows: the launcher, a window program, runs this too.
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                            start_new_session=os.name == "posix")
    try:
        # A line shorter than any pipe's buffer: written at once, read when 7-Zip asks (if ever), then the end.
        proc.stdin.write(line)
        proc.stdin.close()
    except OSError:
        # 7-Zip ended already (it says why on its output, read next).
        pass
    return proc


def _run_7zip(args, password, seconds, watch=None):
    """7-Zip with these arguments as a child process (seven_zip_command, popen_7zip); (exit code, everything it said).
    SourceError (damaged) when it takes longer than `seconds`, or, with a Watch, as soon as what it writes is more than
    the entries said: it is ended at once, and what it wrote is the caller's to remove."""
    proc = popen_7zip(seven_zip_command(args), password)
    if watch is not None:
        # What it writes is read from its own process from here on.
        watch.follow(proc)
    said = []
    # Its words read apart, so a full pipe never holds it while it is watched.
    reader = threading.Thread(target=lambda: said.append(proc.stdout.read()), daemon=True, name="7-zip-output")
    reader.start()
    end = time.monotonic() + seconds
    try:
        while True:
            try:
                code = proc.wait(timeout=WATCH_EVERY)
                break
            except subprocess.TimeoutExpired:
                pass
            if time.monotonic() > end or (watch is not None and watch.over()):
                # Too slow, or writing more than its entries said (an archive lying about a size): ended now.
                raise damaged()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        reader.join()
        proc.stdout.close()
    return code, b"".join(said).decode("utf-8", "replace")


class Watch:
    """What 7-Zip writes into a folder, kept to what the entries it takes out said (`most` bytes, and a small margin
    for what a disk keeps beside a file's bytes): over() is True once the folder holds more.

    Each look reads how many bytes 7-Zip itself has written so far (follow(): the system's own count for its process,
    one cheap call), which no other program changes: the disk's free room, read here before, grew when another
    program deleted files on the same disk, and 7-Zip wrote on for up to a second unseen (112 MB against a bound of
    64, beside other processes). The folder itself is measured file by file when that count passes what the entries
    said, every MEASURE_EVERY seconds whatever it says (a file's length set without a write), and at every look where
    the system keeps no such count or before follow()."""

    def __init__(self, folder, most):
        self.folder = folder
        # The entries' bytes and the margin.
        self.most = most + max(WATCH_SPARE, most // 100)
        # 7-Zip's process, once it runs (follow()).
        self.process = None
        # What 7-Zip had written beyond what the folder held, at the last measuring (what it says on its output; less
        # than nothing when the folder held something before it began): None until the folder was measured once.
        self.elsewhere = None
        self.measured = time.monotonic()

    def follow(self, process):
        """7-Zip's process (subprocess.Popen), whose own written bytes the looks read from here on."""
        self.process = process

    def over(self):
        now = time.monotonic()
        wrote = _wrote(self.process) if self.process is not None else None
        if wrote is not None and self.elsewhere is not None and now - self.measured < MEASURE_EVERY:
            if wrote - self.elsewhere <= self.most:
                # 7-Zip wrote no more since the last measuring than the entries may take: nothing to measure yet.
                return False
        self.measured = now
        written = _written(self.folder)
        if written > self.most:
            return True
        if wrote is not None:
            # From here on the folder holds no more than this and what 7-Zip writes after.
            self.elsewhere = wrote - written
        return False


class _IoCounters(ctypes.Structure):
    """Windows' IO_COUNTERS (GetProcessIoCounters): a process's read, write and other operations and their bytes."""

    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


def _wrote(process):
    """The bytes a child process (subprocess.Popen) has written so far, by the system's own count for it (every write
    of every thread: its files, and what it says on its output), or None when the system keeps no such count, does
    not show it, or the process has just ended. Linux: wchar of /proc/<pid>/io. Windows: GetProcessIoCounters'
    WriteTransferCount, asked through the handle Popen keeps."""
    try:
        if os.name == "nt":
            counters = _IoCounters()
            # The handle as an integer; False (the call failed) is no count.
            if not ctypes.windll.kernel32.GetProcessIoCounters(ctypes.c_void_p(int(process._handle)),
                                                               ctypes.byref(counters)):
                return None
            return int(counters.WriteTransferCount)
        with open("/proc/%d/io" % process.pid, "rb") as f:
            for line in f:
                if line.startswith(b"wchar:"):
                    return int(line.split()[1])
    except (OSError, ValueError, AttributeError):
        # No such file (another system, a kernel without the count), not ours to read, or no handle.
        pass
    return None


def _written(folder):
    """How many bytes the files below a folder hold now, each asked of the disk itself (a listing's cached size lags
    behind a file still being written on Windows); a link counts as nothing (it is refused after)."""
    total = 0
    for here, _, names in os.walk(folder):
        for name in names:
            try:
                total += os.lstat(os.path.join(here, name)).st_size
            except OSError:
                # Gone between the listing and the look.
                continue
    return total


def _said_password(text):
    """True when 7-Zip's words say a password is needed or was wrong."""
    return "Wrong password" in text or "encrypted archive" in text


# ------------------------------------------------------------------------------------------------ archives

class Entry:
    """One entry of an archive: its path (with forward slashes, as listed), size (None when the listing gives none),
    and whether it is a folder, a link or encrypted."""

    def __init__(self, name, size, folder=False, link=False, encrypted=False):
        self.name, self.size, self.folder, self.link, self.encrypted = name, size, folder, link, encrypted


def part_of(path):
    """(the part's number, the parts' common name) for a part of a split archive by its name, or (None, None). An
    old-style x.rar is part 1 when an x.r00 is beside it."""
    name = os.path.basename(path)
    for pattern in (NUMBERED_PART, RAR_PART):
        m = pattern.fullmatch(name)
        if m:
            return int(m.group(2)), m.group(1)
    m = OLD_RAR_PART.fullmatch(name)
    if m:
        # x.r00 is the second part, x.r01 the third (x.rar is the first).
        return int(m.group(2)) + 2, m.group(1)
    if name.lower().endswith(".rar") and os.path.isfile(os.path.join(os.path.dirname(path), name[:-4] + ".r00")):
        return 1, name[:-4]
    return None, None


def missing_part(path):
    """The first part missing among a split archive's (by the names beside its first part), or None."""
    number, stem = part_of(path)
    if number is None:
        return None
    folder = os.path.dirname(os.path.abspath(path)) or "."
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    present = set()
    for name in names:
        n, s = part_of(os.path.join(folder, name))
        if n is not None and s.lower() == stem.lower():
            present.add(n)
    # Every part from the first to the last one there.
    for n in range(1, max(present | {1}) + 1):
        if n not in present:
            return n
    return None


def stream_refused():
    """The refusal of a compressed stream that keeps its size at its end (a .gz, .xz or .lz file): what it holds cannot
    be checked before all of it is unpacked."""
    return SourceError("This archive says its size only at its end, where it cannot be checked first. Unpack it with "
                       "another program, then choose what came out.", "error.source.stream")


def _stream(path):
    """True when a file starts as a compressed stream that keeps its size at its end (STREAMS)."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return False
    return head.startswith(STREAMS)


def listing(path, password=None):
    """Every entry of an archive. A whole .zip is listed by Python's own reader; anything else by 7-Zip. SourceError in
    plain words when it cannot be listed: a password needed or wrong, a part of a split archive missing, damaged, a
    compressed stream that says its size only at its end, or no 7-Zip on this PC."""
    number, _ = part_of(path)
    if number is None and _zip(path):
        said = songlist.zip_directory(path)
        if said is not None and (said[0] > ENTRIES_MOST or said[1] > DIRECTORY_MOST):
            # Counted by its end records, before Python's zip reader holds every entry of the directory in memory.
            raise entry_refused("(more than %d entries)" % ENTRIES_MOST)
        try:
            with zipfile.ZipFile(path) as z:
                infos = z.infolist()
        except (zipfile.BadZipFile, zlib.error, EOFError, OSError, ValueError, NotImplementedError):
            raise damaged() from None
        if len(infos) > ENTRIES_MOST:
            raise entry_refused("(%d entries)" % len(infos))
        out = []
        for info in infos:
            mode = info.external_attr >> 16
            out.append(Entry(info.filename, info.file_size, info.is_dir(), (mode & 0o170000) == 0o120000,
                             bool(info.flag_bits & 0x1)))
        return out
    if _stream(path):
        # Its one entry's size is whatever its last bytes say: refused before 7-Zip unpacks a byte of it.
        raise stream_refused()
    # -spd: the archive's own name is matched as it is, never as a pattern of names.
    code, said = _run_7zip(["l", "-ba", "-slt", "-spd", "--", path], password, LIST_SECONDS)
    if code != 0:
        if _said_password(said):
            raise _password_error(password)
        gap = missing_part(path)
        if gap is not None or number is not None:
            # A split archive cut short: the first part not beside the others (or the one after the last there).
            gap = gap or (_last_part(path) + 1)
            raise SourceError("Part %d of this split archive is missing. Put every part in one folder." % gap,
                              "error.source.missing_part", n=gap)
        if NOT_AN_ARCHIVE.search(said) and not signed(path):
            # 7-Zip knows no archive in it at all, and it does not start as one.
            raise nothing()
        raise damaged()
    return _parse_listing(said)


def _last_part(path):
    """The highest part number beside a split archive's first part."""
    number, stem = part_of(path)
    folder = os.path.dirname(os.path.abspath(path)) or "."
    found = [number or 1]
    for name in os.listdir(folder):
        n, s = part_of(os.path.join(folder, name))
        if n is not None and s.lower() == stem.lower():
            found.append(n)
    return max(found)


def _password_error(password):
    """A password needed, or the one given is not the archive's."""
    if password:
        return SourceError("That is not this archive's password. Enter it again.", "error.source.wrong_password")
    return SourceError("This archive has a password. Enter it.", "error.source.password")


def _size(value):
    """An entry's size as 7-Zip lists it, or None when it lists none (a stream that does not know its own: bzip2's)."""
    value = (value or "").strip()
    return int(value) if value.isdigit() else None


def _parse_listing(text):
    """7-Zip's technical listing (-slt) as entries: one block of "Name = value" lines each."""
    entries, block = [], {}
    for line in text.splitlines() + [""]:
        if not line.strip():
            if "Path" in block:
                attributes = block.get("Attributes", "")
                windows, _, unix = attributes.partition(" ")
                entries.append(Entry(
                    # Windows' 7-Zip lists with backslashes; one name form here.
                    block["Path"].replace("\\", "/"),
                    # None when 7-Zip gives no size: such an entry is never taken out (cannot_take()).
                    _size(block.get("Size")),
                    # A folder by its attribute (D), or its own line (a zip's Folder = +).
                    "D" in windows or block.get("Folder") == "+" or unix.startswith("d"),
                    # A link: the unix kind (l), or Windows' reparse point (L), or 7-Zip naming its target.
                    unix.startswith("l") or "L" in windows or bool(block.get("Symbolic Link")),
                    block.get("Encrypted") == "+"))
                if len(entries) > ENTRIES_MOST:
                    raise entry_refused("(more than %d entries)" % ENTRIES_MOST)
            block = {}
            continue
        key, sep, value = line.partition(" = ")
        if sep:
            block[key.strip()] = value
    return entries


def unsafe(name):
    """True for an entry name no file of the reading's own may come from: an absolute path, a drive letter, "..", a
    device name, a stream, a name or a path too long, a control character."""
    if not name or name.startswith(("/", "\\")) or re.match(r"[A-Za-z]:", name) or "\\" in name:
        return True
    if len(name.encode("utf-8")) > PATH_MOST or any(ord(c) < 32 for c in name):
        return True
    for part in name.rstrip("/").split("/"):
        stem = part.split(".")[0].strip().lower()
        if part in ("", ".", "..") or ":" in part or stem in DEVICES or len(part.encode("utf-8")) > NAME_MOST:
            return True
    return False


def cannot_take(entry):
    """True for an entry that is never taken out: a name unsafe() refuses, a link, or no size in the listing (what 7-Zip
    would write for it is bounded by nothing it said)."""
    return unsafe(entry.name) or entry.link or entry.size is None


def twice(entries):
    """The first of the entries whose name another one before it has, in any letter case (Windows keeps one file for
    both, and a Linux server matches names as Windows does), or None: taken out, it would land on the other."""
    seen = set()
    for e in entries:
        key = e.name.rstrip("/").lower()
        if key in seen:
            return e
        seen.add(key)
    return None


def game_in(entries):
    """Where a game folder is among an archive's entries (its path with a slash after it, "" for the top), the one
    nearest the top; or None. Known by content, as on a disk: a program right in it, and a pack folder with the two files
    every game folder has, in any letter case."""
    names = {e.name.rstrip("/").lower() for e in entries if not e.folder}
    roots = []
    for name in names:
        if name.endswith("pack/config.pak"):
            root = name[:-len("pack/config.pak")]
            if root + "pack/discinfo.pak" in names and any(
                    n.startswith(root) and "/" not in n[len(root):] and n.endswith(".exe") for n in names):
                roots.append(root)
    if not roots:
        return None
    best = min(roots, key=lambda r: (r.count("/"), r))
    # The path as the archive spells it (the names above are in lower case).
    spelled = next((e.name for e in entries if e.name.lower().startswith(best) and best), "")
    return spelled[:len(best)] if best else ""


def inner_archives(entries):
    """The archives inside an archive that may hold the game: whole ones and the first parts of split ones."""
    out = []
    for e in entries:
        if e.folder:
            continue
        base = os.path.basename(e.name.rstrip("/"))
        number, _ = part_of(base)
        if (number is None and base.lower().endswith(ARCHIVES)) or number == 1:
            out.append(e)
    return out


def needed(entries, root):
    """The entries the server needs from the game folder at `root` in an archive: every program right in it (one is
    the client) and the families of the game's files it reads, with the two a game folder is known by. SourceError for
    the first of them that is not safe to take out (a link, an absolute path, a device name, no size...) or whose name
    one before it has (in any letter case)."""
    lowered = root.lower()
    take = []
    for e in entries:
        if e.folder or not e.name.lower().startswith(lowered):
            continue
        rest = e.name[len(root):]
        program = "/" not in rest and rest.lower().endswith(".exe")
        game_file = rest.lower().startswith("pack/") and "/" not in rest[5:] and FAMILY_FILE.fullmatch(rest[5:])
        if not (program or game_file):
            continue
        if cannot_take(e):
            raise entry_refused(e.name)
        take.append(e)
    again = twice(take)
    if again is not None:
        # The same file twice: which one the reading would read is anyone's guess.
        raise entry_refused(again.name)
    return take


def names_file(path, take):
    """The entries' names in a list file at `path` for 7-Zip's -i@ (one a line, in UTF-8 as -scsUTF-8 says, matched as
    they are with -spd): the switch takes the list whatever its names start with, where a list after "--" would be
    one more name."""
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(e.name + "\n" for e in take))
    return "-i@" + path


def extract(path, take, dest, password=None, most=NEEDED_MOST):
    """Take the entries out of the archive into dest (a new folder of the reading's own), then check what came out: each
    file where its entry says, a regular file of the size its entry said, nothing else, no link anywhere. SourceError
    for an entry that is not safe to take out, for more than `most` bytes (None: only the free space counts), for 7-Zip
    writing more than the entries said (stopped at once), and for anything else that went wrong."""
    for e in take:
        if cannot_take(e) or e.folder:
            raise entry_refused(e.name)
    again = twice(take)
    if again is not None:
        raise entry_refused(again.name)
    size = sum(e.size for e in take)
    if most is not None and size > most:
        need, have = _gigabytes(size), _gigabytes(most)
        raise SourceError("Not enough free space to take out what the server needs (%s needed, %s free)."
                          % (need, have), "error.source.space", need=need, free=have)
    _room(dest, size)
    number, _ = part_of(path)
    if number is None and _zip(path):
        _extract_zip(path, take, dest, password)
    else:
        # The names in a list file beside dest (not in it: the check finds nothing but the entries there).
        names = os.path.join(os.path.dirname(dest), os.path.basename(dest) + ".names")
        try:
            listed = names_file(names, take)
        except OSError:
            # The reading's own folder took no file: said as the archive's, never with a path of the server's.
            raise damaged() from None
        try:
            # Watched while it runs: stopped as soon as it writes more than the entries said.
            code, said = _run_7zip(["x", "-y", "-bso0", "-bsp0", "-spd", "-scsUTF-8", "-o" + dest, listed, "--", path],
                                   password, EXTRACT_SECONDS, watch=Watch(dest, size))
        finally:
            catalog.remove(names)
        if code != 0:
            if _said_password(said):
                raise _password_error(password)
            raise damaged()
    _check_extracted(take, dest)


def _extract_zip(path, take, dest, password):
    """The zip's entries written one by one into dest by Python's own reader, never past their size."""
    try:
        with zipfile.ZipFile(path) as z:
            for e in take:
                target = os.path.join(dest, *e.name.split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(e.name, pwd=password.encode("utf-8") if password else None) as src, \
                        open(target, "xb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
    except RuntimeError as e:
        # The zip's own reader refuses an encrypted entry without its password, or with a wrong one.
        if "password" in str(e).lower() or "encrypted" in str(e).lower():
            raise _password_error(password) from None
        raise damaged() from None
    except (zipfile.BadZipFile, zlib.error, EOFError, KeyError, NotImplementedError):
        raise damaged() from None
    except OSError:
        # Anything else while taking out (a name where a folder must go, a file there already): the archive's
        # entries are not what a game folder is, said in its words, never with a path of the server's.
        raise damaged() from None


def _check_extracted(take, dest):
    """What came out of an archive, against what was asked for."""
    wanted = {os.path.normpath(os.path.join(dest, *e.name.split("/"))): e for e in take}
    for folder, dirs, names in os.walk(dest):
        for name in dirs + names:
            path = os.path.join(folder, name)
            if os.path.islink(path):
                raise entry_refused(os.path.relpath(path, dest))
            if name in names and os.path.normpath(path) not in wanted:
                # Something no entry asked for.
                raise entry_refused(os.path.relpath(path, dest))
    for path, e in wanted.items():
        if not os.path.isfile(path) or os.path.getsize(path) != e.size:
            # Cut short, or not there: what the entry said is not what came.
            raise damaged()


def _room(folder, size):
    """SourceError when the disk the folder is on has not the room for `size` bytes and a little more."""
    try:
        free = shutil.disk_usage(folder).free
    except OSError:
        return
    if free < size + SPACE_SPARE:
        need, have = _gigabytes(size + SPACE_SPARE), _gigabytes(free)
        raise SourceError("Not enough free space to take out what the server needs (%s needed, %s free)."
                          % (need, have), "error.source.space", need=need, free=have)


def _gigabytes(size):
    """A size for a sentence: '120 MB', '1.5 GB'."""
    if size >= 1 << 30:
        return "%.1f GB" % (size / float(1 << 30))
    return "%d MB" % max(1, round(size / float(1 << 20)))


class _Unpacked:
    """The game folder inside an archive (inside another, at most NESTING_MOST deep), taken out into a folder of the
    reading's own: its .game is the game folder there. Removed with everything in it when the `with` block ends."""

    def __init__(self, path, work, password=None):
        self.path, self.password = path, password
        self.folder = tempfile.mkdtemp(prefix=catalog.STAGING + "archive-", dir=work)
        self.inner = False
        try:
            self.game, self.root = self._open(path, 1)
        except BaseException:
            catalog.remove(self.folder)
            raise

    def _open(self, path, depth):
        entries = listing(path, self.password)
        root = game_in(entries)
        if root is not None:
            out = os.path.join(self.folder, "game%d" % depth)
            os.makedirs(out)
            take = needed(entries, root)
            if any(e.encrypted for e in take) and not self.password:
                raise _password_error(None)
            extract(path, take, out, self.password)
            # The game folder taken out: read there (its own pack folder's case kept as the archive spells it).
            return g.Game(os.path.join(out, *root.rstrip("/").split("/")) if root else out), root
        inside = inner_archives(entries)
        if not inside or depth >= NESTING_MOST:
            raise nothing()
        # The archive inside, whole (with the later parts of a split one beside it), then looked into as the outer one.
        out = os.path.join(self.folder, "inner%d" % depth)
        os.makedirs(out)
        first = inside[0]
        stem = part_of(os.path.basename(first.name))[1]
        parts = [e for e in entries if not e.folder and stem and part_of(os.path.basename(e.name))[1] == stem]
        extract(path, [first] + [p for p in parts if p is not first], out, self.password, most=None)
        self.inner = True
        return self._open(os.path.join(out, *first.name.split("/")), depth + 1)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        catalog.remove(self.folder)


# ------------------------------------------------------------------------------------------------ what a path is

def kind_of(path):
    """What a path is by its content: "folder" (a folder: a game folder may be in it), "song list" (one openDMT3
    saved), "archive" (anything 7-Zip or the zip reader opens, a split archive's first part), "part" (a later part of
    a split archive), "file" (any other file: part of a game folder, or nothing of the game's), or None when there is
    nothing at the path."""
    if os.path.isdir(path):
        return "folder"
    if not os.path.isfile(path):
        return None
    number, _ = part_of(path)
    if number is not None and number > 1:
        return "part"
    if number is None and songlist.is_song_list(path):
        return "song list"
    # A compressed stream is an archive too, by its first bytes whatever 7-Zip this PC has (its listing refuses it).
    if number is not None or signed(path) or _stream(path) or zipfile.is_zipfile(path) or _opened_by_7zip(path):
        return "archive"
    return "file"


def _zip(path):
    """True when a file is a zip from its first bytes. Python's own check (zipfile.is_zipfile) looks for a zip's end
    anywhere near the file's end, so a 7z that stores a zip without compressing it would be read as that zip."""
    try:
        with open(path, "rb") as f:
            head = f.read(4)
    except OSError:
        return False
    return head in (b"PK\x03\x04", b"PK\x05\x06")


def signed(path):
    """True when a file starts as an archive people pack the game in does (SIGNATURES)."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return False
    return head.startswith(SIGNATURES)


def _opened_by_7zip(path):
    """True when 7-Zip opens the file as an archive of some kind (asked only of files that are not zips, and only when
    this PC has a 7-Zip)."""
    if seven_zip() is None or path.lower().endswith((".pak", ".exe", ".dll")):
        # The game's own files and programs are never archives to the server, whatever 7-Zip thinks of a program.
        return False
    try:
        code, said = _run_7zip(["l", "-ba", "-spd", "--", path], None, LIST_SECONDS)
    except SourceError:
        return False
    # Opened (even one that needs a password, or a damaged one 7-Zip still knows the kind of).
    return code == 0 or _said_password(said) or (not NOT_AN_ARCHIVE.search(said) and "ERROR" in said)


def around(path):
    """The game folder a file is part of (its folder, or the folder above its pack folder), or None."""
    folder = os.path.dirname(os.path.abspath(path))
    for candidate in (folder, os.path.dirname(folder)):
        if g.Game._looks_like_game(candidate):
            return candidate
    return None


def look(path, password=None):
    """What a path is, without reading anything into the server: {"path", "kind", "ready", "line", "key", "values",
    ...} where line is the one plain line (English) and key and values give it in the site's words. A game folder also
    has its survey (catalog.survey); a song list its counts; an archive whether it holds another."""
    out = {"path": path, "kind": kind_of(path), "ready": False, "line": None, "key": None, "values": {}}
    kind = out["kind"]
    try:
        if kind is None or kind == "file":
            game = around(path) if kind == "file" else None
            if game is None:
                raise (SourceError("This is part of a game folder. Choose the whole game folder.", "error.source.part")
                       if kind == "file" and path.lower().endswith((".pak", ".exe")) else nothing())
            # One file of a game folder: the folder around it.
            path, kind = game, "folder"
            out.update(path=game, kind="folder")
        if kind == "part":
            n = part_of(path)[0]
            raise SourceError("This is part %d of a split archive. Put every part in one folder and choose the first."
                              % n, "error.source.later_part", n=n)
        if kind == "folder":
            found = catalog.survey(path)
            out["survey"] = found
            if found["problem"]:
                # The survey's own line: no game folder there, the cabinet's client, a damaged song list...
                out.update(line=found["problem"], key=found["problem_key"], path=found["folder"] or path)
                return out
            client = found["client_kind"] or g.ORIGINAL
            out.update(ready=True, key="source.folder", values={"client": client, "n": found["songs"]},
                       line=folder_line(client, found["songs"]), path=found["folder"])
        elif kind == "song list":
            manifest = songlist.look(path)
            out["manifest"] = manifest
            out.update(ready=True, key="source.song_list", values={"n": manifest["songs"]},
                       line=counted("source.song_list", manifest["songs"])[0].format(n=manifest["songs"]))
        elif kind == "archive":
            gap = missing_part(path)
            if gap is not None:
                raise SourceError("Part %d of this split archive is missing. Put every part in one folder." % gap,
                                  "error.source.missing_part", n=gap)
            entries = listing(path, password)
            root = game_in(entries)
            if root is None:
                inside = inner_archives(entries)
                if not inside:
                    raise nothing()
                refused = next((e for e in inside if cannot_take(e)), None)
                if refused is not None:
                    # One the reading would refuse (no size, a link...): said now, as it would be then.
                    raise entry_refused(refused.name)
                # Looked into when it is read: the archive inside is taken out whole first.
                out.update(ready=True, key="source.inner", line=WORDS["source.inner"][0])
            else:
                take = needed(entries, root)
                if any(e.encrypted for e in take) and not password:
                    raise _password_error(None)
                out.update(ready=True, key="source.archive", line=WORDS["source.archive"][0], inside=root,
                           needed=sum(e.size for e in take))
    except (SourceError, songlist.SongListError, g.GameError) as e:
        # Does not work here: the one problem, with the one thing to do.
        out.update(ready=False, line=errors.say(e), key=e.key, values=dict(e.params))
    return out


def said(item, language="en"):
    """A path's look (look()) as its one line in English or Korean: its state's own words, or the refusal's (errors.py),
    or the line as it came."""
    key, values = item.get("key"), dict(item.get("values") or {})
    if key == "source.folder":
        return folder_line(values.get("client") or g.ORIGINAL, values.get("n"), language)
    if key in WORDS:
        return counted(key, values.get("n"))[1 if language == "ko" else 0].format(**values)
    if key in errors.TEXT:
        return errors.say(Worded(item["line"], key, **values), language)
    return item["line"]


def folder_line(client, songs, language="en"):
    """A game folder's line: "Game folder, original PC client, 177 songs: ready", in English or Korean."""
    at = 1 if language == "ko" else 0
    return counted("source.folder", songs)[at].format(client=WORDS["source.client." + client][at], n=songs)


# ------------------------------------------------------------------------------------------------ reading

def read(path, data_dir, now=None, traces=False, password=None):
    """Read the song list from a path in any form into data_dir; returns the report kept as catalog-read.json (where it
    came from with it). SourceError, SongListError or GameError (each worded) when it cannot be read, and nothing in
    the data folder changes; an archive's files taken out are removed either way."""
    kind = kind_of(path)
    if kind == "song list":
        return songlist.take(path, data_dir, now=now)
    if kind in ("file", None):
        game = around(path) if kind == "file" else None
        if game is None:
            raise (SourceError("This is part of a game folder. Choose the whole game folder.", "error.source.part")
                   if kind == "file" and path.lower().endswith((".pak", ".exe")) else nothing())
        path, kind = game, "folder"
    if kind == "part":
        n = part_of(path)[0]
        raise SourceError("This is part %d of a split archive. Put every part in one folder and choose the first." % n,
                          "error.source.later_part", n=n)
    if kind == "folder":
        try:
            game = g.Game.find(path)
        except g.GameError:
            raise nothing() from None
        return catalog.read_game(game, data_dir, now=now, traces=traces, source={"from": "folder", "path": game.root})
    gap = missing_part(path)
    if gap is not None:
        raise SourceError("Part %d of this split archive is missing. Put every part in one folder." % gap,
                          "error.source.missing_part", n=gap)
    os.makedirs(data_dir, exist_ok=True)
    with _Unpacked(path, data_dir, password) as unpacked:
        source = {"from": "archive", "path": os.path.abspath(path), "inside": unpacked.root}
        return catalog.read_game(unpacked.game, data_dir, now=now, traces=traces, source=source)


def save(path, out_path, password=None, now=None, work=None):
    """Make a song list from a path in any form (a game folder, an archive holding one, or a song list, checked again)
    and save it at out_path; returns (the manifest, the reading's report). The reading goes into a folder of its own
    (in `work`, beside the file by default), removed after; then the file is checked as a server would take it."""
    folder = tempfile.mkdtemp(prefix=catalog.STAGING + "save-", dir=work or os.path.dirname(os.path.abspath(out_path)))
    made = False
    try:
        data = os.path.join(folder, "data")
        report = read(path, data, now=now, password=password)
        manifest = songlist.save(data, out_path, report, now=now)
        made = True
        # The file just made, taken as a server takes it, so a song list that would be refused is said here, not
        # after it travelled.
        songlist.take(out_path, os.path.join(folder, "check"), now=now)
    except BaseException:
        if made:
            # A file no server would take is not left behind.
            catalog.remove(out_path)
        raise
    finally:
        catalog.remove(folder)
    return manifest, report


# ------------------------------------------------------------------------------------------------ the server PC

def in_container():
    """True when this server runs in a container (Docker): it sees only the folders its compose file gives it."""
    return os.path.exists("/.dockerenv") or os.environ.get("OPENDMT3_IN_CONTAINER") == "1"


def places(game_folder=None):
    """The folders on the server PC this server looks in for the game's files: the game folder it was given (in Docker
    the one compose.yaml mounts) and, outside a container, the server's user's Downloads, Desktop and Documents, and
    Windows' own under WSL. Each that is there, once."""
    found = [game_folder] if game_folder else []
    if not in_container():
        home = os.path.expanduser("~")
        found += [os.path.join(home, n) for n in ("Downloads", "Desktop", "Documents")]
        for user in sorted(_listdir(WINDOWS_USERS)):
            # People's own folders only: not Windows' own profiles, nor the links it keeps for old names.
            if user.lower() in WINDOWS_PROFILES or os.path.islink(os.path.join(WINDOWS_USERS, user)):
                continue
            found += [os.path.join(WINDOWS_USERS, user, n) for n in ("Downloads", "Desktop", "Documents")]
    seen, out = set(), []
    for p in found:
        key = os.path.normcase(os.path.abspath(p))
        if key not in seen and os.path.isdir(p):
            seen.add(key)
            out.append(p)
    return out


def _listdir(folder):
    try:
        return os.listdir(folder)
    except OSError:
        return []


def looked(path):
    """look(path), kept while the path stays as it was (its time and size) for LOOK_LIFE seconds."""
    try:
        st = os.stat(path)
        key = (os.path.abspath(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return look(path)
    with _kept_lock:
        kept = _looks.get(key)
    if kept is not None and time.monotonic() - kept[0] < LOOK_LIFE:
        return kept[1]
    result = look(path)
    with _kept_lock:
        if len(_looks) >= LOOKS_KEPT and key not in _looks:
            # The one kept longest goes (dicts keep their order).
            _looks.pop(next(iter(_looks)))
        _looks[key] = (time.monotonic(), result)
    return result


def found(where):
    """The game's files in these folders, each judged (look()): game folders up to LOOK_DEPTH levels down, archives
    named with a game word, song lists openDMT3 saved; at most LOOK_MOST, the ready ones first. The same folders'
    answer is kept for FOUND_LIFE seconds."""
    key = tuple(where)
    with _kept_lock:
        kept = _found.get(key)
    if kept is not None and time.monotonic() - kept[0] < FOUND_LIFE:
        return kept[1]
    paths, until = [], time.monotonic() + LOOK_SECONDS
    for base in where:
        top = base.rstrip(os.sep).count(os.sep)
        for here, dirs, names in os.walk(base):
            if len(paths) >= LOOK_MOST or time.monotonic() > until:
                break
            # The game's files' folder is large and holds no other; hidden folders hold none of the game's.
            dirs[:] = sorted(d for d in dirs if d.lower() != g.PACK_DIR and not d.startswith("."))
            if here.count(os.sep) - top >= LOOK_DEPTH:
                dirs[:] = []
            if g.Game._looks_like_game(here):
                paths.append(here)
                # A game folder holds nothing else to find.
                dirs[:] = []
                continue
            for name in sorted(names):
                low = name.lower()
                full = os.path.join(here, name)
                number, _ = part_of(full)
                if low.endswith(".zip") and songlist.is_song_list(full):
                    paths.append(full)
                elif (number == 1 or (number is None and low.endswith(ARCHIVES))) and any(
                        w in low for w in GAME_WORDS):
                    paths.append(full)
    looks = sorted((looked(p) for p in list(dict.fromkeys(paths))[:LOOK_MOST]), key=lambda item: not item["ready"])
    with _kept_lock:
        _found.clear()
        _found[key] = (time.monotonic(), looks)
    return looks


def folders(path):
    """A folder of the server PC as the Status page's folder browser shows it: {"path", "up", "folders"}, the folders
    in it by name (hidden ones and the game's files' folder left out). SourceError when it cannot be listed."""
    path = os.path.abspath(path or "/")
    try:
        names = sorted(os.listdir(path), key=str.lower)
    except OSError as e:
        raise SourceError("This cannot be read by the server (%s)." % (e.strerror or type(e).__name__),
                          "error.source.unreadable", reason=e.strerror or type(e).__name__) from None
    shown = [n for n in names if not n.startswith(".") and n.lower() != g.PACK_DIR
             and os.path.isdir(os.path.join(path, n))]
    up = os.path.dirname(path)
    return {"path": path, "up": up if up != path else None, "folders": shown[:400]}


def as_json(found_items):
    """found()'s answer as the API gives it: each path's kind, state, line and the words' key and values."""
    return [{"path": item["path"], "kind": item["kind"], "ready": item["ready"], "line": item["line"],
             "key": item["key"], "values": dict(item["values"])} for item in found_items]
