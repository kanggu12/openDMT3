"""Start the game and follow it until it closes.

openDMT3's copy of the client starts from openDMT3's own folder (steps.Own) with the game folder as the current one:
the game opens pack\\, Resource\\ and TECHNIKA\\ by paths relative to it, and openDMT3's library answers the client's
question about its own folder with the game folder (native/cardreader/files.c). It is started as a separate program
so the launcher can close or crash without taking the game along.

The client opens its files with Windows' ANSI calls, which take at most 259 characters in the ANSI code page. Measured
under Wine on an English Windows (code page 1252): from a folder with Korean letters the client's own path came back
with question marks and the game stopped when it read its settings; from a folder of 280 characters Windows could not
make it the current folder at all. The longest path the game opens inside its folder is 64 characters
(Resource/maingame/coolbomb/0/onePointLongLine/bar_burn_0000.dds and the backslash before it). A game folder that
cannot be written in the ANSI code page, or that leaves less room than that, is given to the game through a short
path: the folder's own 8.3 short name when its drive keeps them, else a junction of openDMT3's (made without
administrator rights) in a folder whose path is short and in the ANSI code page. Through it the same game played a
whole song in both cases.

The junction's folder is this user's alone: openDMT3's own under %LocalAppData%, or, when that path cannot be given
to the game (a user name in letters outside the ANSI code page), one made for the PLAY in a folder every user of the
PC shares (%PUBLIC%, %ProgramData%), under a random name no one can guess and make first, with access for this user
only. Right before the game starts, the folder is checked again to be this user's alone and the link to lead to the
game folder: another user of the PC can never point the game at a folder of theirs.
"""

import logging
import os
import re
import secrets
import stat
import subprocess
import sys
import time

from opendmt3.core import game as g
from opendmt3.core import safety

log = logging.getLogger(__name__)

# Windows' MAX_PATH for the ANSI calls the client makes, and the longest path the game opens inside its folder.
MAX_PATH = 260
LONGEST_INSIDE = 64
# The folder made for a PLAY in a folder every user shares: its name, a random part no one can guess.
SHARED_NAME = "openDMT3-%s"
SHARED_PATTERN = re.compile(r"openDMT3-[0-9a-f]{16}")
# How many random names are tried before a shared place is passed by (one that is there already is never used).
NAME_TRIES = 8


class LaunchError(Exception):
    """The game could not be started, worded for the player."""


class Session:
    """One run of the game: when it started, the process, and how it ended."""

    def __init__(self, process, started):
        self.process = process          # the game's process, followed until it exits
        self.started = started          # time.time() at start, for the session length shown afterwards

    def running(self):
        """True while the game is open."""
        return self.process.poll() is None

    def exit_code(self):
        """The game's exit code once it has closed, else None."""
        return self.process.poll()

    def seconds(self):
        """How long the game has been (or was) open."""
        return time.time() - self.started


def ansi(path):
    """Whether a path can be written in this Windows' ANSI code page (elsewhere every path can)."""
    if sys.platform != "win32":
        return True
    try:
        # Python's "mbcs" is the ANSI code page; "strict" refuses a letter it would turn into a question mark.
        path.encode("mbcs", "strict")
        return True
    except UnicodeEncodeError:
        return False


def needs_short_path(root):
    """Why the game folder cannot be given to the client as it is ("not ANSI", "too long"), or None when it can."""
    if not ansi(root):
        return "not ANSI"
    if len(root) + LONGEST_INSIDE >= MAX_PATH:
        return "too long"
    return None


class System:
    """What the short path asks of the system, on Linux (development and the tests): no 8.3 names, and a folder of
    this user's alone is one this user owns that no one else may enter (mode 0700). Windows is WindowsSystem."""

    def short_name(self, path):
        """The path's own 8.3 short name, or None when the system keeps none."""
        return None

    def make_folder(self, path):
        """Make a new folder for this user alone; FileExistsError when anything has the name already."""
        os.mkdir(path, 0o700)

    def own(self, path):
        """True when the folder is this user's alone: a folder (no link), this user's, no one else let in."""
        try:
            st = os.lstat(path)
        except OSError:
            return False
        return stat.S_ISDIR(st.st_mode) and st.st_uid == os.geteuid() and not st.st_mode & 0o077

    def make_own(self, path):
        """A folder that is there made this user's alone, when this user owns it (its access set so); False when it is
        someone else's, or no folder of its own (a link)."""
        try:
            st = os.lstat(path)
        except OSError:
            return False
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid():
            return False
        os.chmod(path, 0o700)
        return True


class WindowsSystem(System):
    """The same of Windows, by its own calls (ctypes): GetShortPathNameW for the 8.3 name, and a folder whose owner is
    this user and whose access list is protected (no inherited entry) with one entry, full access for this user:
    made so in one step (CreateDirectoryW with that security), set so (SetNamedSecurityInfoW), checked so
    (GetNamedSecurityInfoW). kernel32 and advapi32 can be handed in (the tests' stand-ins)."""

    # Windows' numbers: ERROR_ALREADY_EXISTS; the file kind of object; owner, access list, protected access list;
    # the security descriptor strings' revision; TOKEN_QUERY; TokenUser and TokenOwner.
    ALREADY_EXISTS, FILE_OBJECT = 183, 1
    OWNER, DACL, PROTECTED = 0x1, 0x4, 0x80000000
    REVISION, TOKEN_QUERY, TOKEN_USER, TOKEN_OWNER = 1, 0x0008, 1, 4

    def __init__(self, kernel32=None, advapi32=None, last_error=None):
        self.kernel32, self.advapi32 = kernel32, advapi32
        # Whether each call has its C types yet (given once, the first time the calls are used).
        self.typed = False
        # The last call's error: Windows' own (ctypes keeps it for each call), or the stand-ins'.
        self.last_error = last_error

    def _error(self, code=None):
        """An OSError for a call that failed, with Windows' own words for its error (the last call's by default)."""
        import ctypes
        if code is None:
            code = self.last_error() if self.last_error else ctypes.get_last_error()
        maker = getattr(ctypes, "WinError", None)
        return maker(code) if maker else OSError(code, "Windows error %d" % code)

    def _dlls(self):
        """kernel32 and advapi32, loaded the first time (the last error kept for each call), each call given its C
        types: a handle or a pointer is 64 bits, which ctypes would cut to an int's 32 without them."""
        if not self.typed:
            import ctypes
            from ctypes import wintypes
            # Windows' own, unless stand-ins were handed in (they take the same C types).
            kernel32 = self.kernel32 or ctypes.WinDLL("kernel32", use_last_error=True)
            advapi32 = self.advapi32 or ctypes.WinDLL("advapi32", use_last_error=True)
            p, out = ctypes.c_void_p, ctypes.POINTER
            for dll, name, args, result in (
                    (kernel32, "GetShortPathNameW", [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD], wintypes.DWORD),
                    (kernel32, "GetCurrentProcess", [], wintypes.HANDLE),
                    (kernel32, "CloseHandle", [wintypes.HANDLE], wintypes.BOOL),
                    (kernel32, "LocalFree", [p], p),
                    (kernel32, "CreateDirectoryW", [wintypes.LPCWSTR, p], wintypes.BOOL),
                    (advapi32, "OpenProcessToken", [wintypes.HANDLE, wintypes.DWORD, out(wintypes.HANDLE)],
                     wintypes.BOOL),
                    (advapi32, "GetTokenInformation", [wintypes.HANDLE, ctypes.c_int, p, wintypes.DWORD,
                                                       out(wintypes.DWORD)], wintypes.BOOL),
                    (advapi32, "ConvertSidToStringSidW", [p, out(wintypes.LPWSTR)], wintypes.BOOL),
                    (advapi32, "ConvertStringSecurityDescriptorToSecurityDescriptorW",
                     [wintypes.LPCWSTR, wintypes.DWORD, out(p), p], wintypes.BOOL),
                    (advapi32, "GetNamedSecurityInfoW", [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, out(p),
                                                         out(p), out(p), out(p), out(p)], wintypes.DWORD),
                    (advapi32, "ConvertSecurityDescriptorToStringSecurityDescriptorW",
                     [p, wintypes.DWORD, wintypes.DWORD, out(wintypes.LPWSTR), p], wintypes.BOOL),
                    (advapi32, "GetSecurityDescriptorDacl", [p, out(wintypes.BOOL), out(p), out(wintypes.BOOL)],
                     wintypes.BOOL),
                    (advapi32, "SetNamedSecurityInfoW", [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD, p, p, p, p],
                     wintypes.DWORD)):
                function = getattr(dll, name)
                function.argtypes, function.restype = args, result
            self.kernel32, self.advapi32, self.typed = kernel32, advapi32, True
        return self.kernel32, self.advapi32

    def short_name(self, path):
        import ctypes
        kernel32, _ = self._dlls()
        # A path past MAX_PATH is asked for with the long-path prefix, which comes off the answer again.
        prefix = "\\\\?\\" if len(path) >= MAX_PATH and not path.startswith("\\\\") else ""
        size = kernel32.GetShortPathNameW(prefix + path, None, 0)
        if not size:
            return None
        buf = ctypes.create_unicode_buffer(size)
        got = kernel32.GetShortPathNameW(prefix + path, buf, size)
        if not got or got >= size:
            return None
        short = buf.value
        return short[len(prefix):] if prefix and short.startswith(prefix) else short

    def _sid(self, kind):
        """This process's user (TOKEN_USER) or the owner it gives what it makes (TOKEN_OWNER), as a SID string."""
        import ctypes
        from ctypes import wintypes
        kernel32, advapi32 = self._dlls()
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), self.TOKEN_QUERY, ctypes.byref(token)):
            raise self._error()
        try:
            needed = wintypes.DWORD()
            # Asked once for the size, then for the answer: its first field is the SID's pointer, in both kinds.
            advapi32.GetTokenInformation(token, kind, None, 0, ctypes.byref(needed))
            buf = ctypes.create_string_buffer(max(needed.value, ctypes.sizeof(ctypes.c_void_p)))
            if not advapi32.GetTokenInformation(token, kind, buf, len(buf), ctypes.byref(needed)):
                raise self._error()
            return self._sid_text(ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0])
        finally:
            kernel32.CloseHandle(token)

    def _sid_text(self, sid):
        """A SID (its pointer) as its string, S-1-5-21-..."""
        import ctypes
        from ctypes import wintypes
        kernel32, advapi32 = self._dlls()
        text = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(ctypes.c_void_p(sid), ctypes.byref(text)):
            raise self._error()
        try:
            return text.value
        finally:
            kernel32.LocalFree(text)

    def _access(self):
        """The access list of a folder of this user's alone: protected, full access for this user, passed to what is
        made in it."""
        return "D:P(A;OICI;FA;;;%s)" % self._sid(self.TOKEN_USER)

    def make_folder(self, path):
        import ctypes
        from ctypes import wintypes
        kernel32, advapi32 = self._dlls()

        class SECURITY_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                        ("bInheritHandle", wintypes.BOOL)]
        descriptor = ctypes.c_void_p()
        if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(self._access(), self.REVISION,
                                                                            ctypes.byref(descriptor), None):
            raise self._error()
        try:
            security = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), descriptor.value, False)
            # Made with its access in the same step: no moment when the shared folder's own lets anyone in.
            if not kernel32.CreateDirectoryW(path, ctypes.byref(security)):
                error = self.last_error() if self.last_error else ctypes.get_last_error()
                if error == self.ALREADY_EXISTS:
                    raise FileExistsError(path)
                raise self._error(error)
        finally:
            kernel32.LocalFree(descriptor)

    def _owner_and_access(self, path):
        """(the owner's SID string, the access list's string) of a file or a folder, or None when it cannot be read."""
        import ctypes
        from ctypes import wintypes
        kernel32, advapi32 = self._dlls()
        owner, access, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        if advapi32.GetNamedSecurityInfoW(path, self.FILE_OBJECT, self.OWNER | self.DACL, ctypes.byref(owner), None,
                                          ctypes.byref(access), None, ctypes.byref(descriptor)) != 0:
            return None
        try:
            if not owner.value:
                # No owner at all (a drive without access lists): no folder of anyone's alone.
                return None
            text = wintypes.LPWSTR()
            if not advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, self.REVISION, self.DACL,
                                                                                ctypes.byref(text), None):
                return None
            try:
                return self._sid_text(owner.value), text.value
            finally:
                kernel32.LocalFree(text)
        finally:
            kernel32.LocalFree(descriptor)

    def _as_written(self, access):
        """An access list as Windows writes one back: a well-known account by its short name (LA for the built-in
        Administrator, for one), the flags in its own order. A folder's list, as read, is written the same way."""
        import ctypes
        from ctypes import wintypes
        kernel32, advapi32 = self._dlls()
        descriptor = ctypes.c_void_p()
        if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(access, self.REVISION,
                                                                            ctypes.byref(descriptor), None):
            raise self._error()
        try:
            text = wintypes.LPWSTR()
            if not advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, self.REVISION, self.DACL,
                                                                                ctypes.byref(text), None):
                raise self._error()
            try:
                return text.value
            finally:
                kernel32.LocalFree(text)
        finally:
            kernel32.LocalFree(descriptor)

    def own(self, path):
        if not os.path.isdir(path) or _is_link(path):
            # A folder of its own, never a link to one.
            return False
        try:
            found = self._owner_and_access(path)
            if found is None:
                return False
            owner, access = found
            me = self._sid(self.TOKEN_USER)
            mine = (me, self._sid(self.TOKEN_OWNER))
            # The one entry as made, as Windows writes it back: compared with the folder's in the same writing.
            entry = re.findall(r"\(([^)]*)\)", self._as_written(self._access()))
        except OSError:
            # Windows would not say: not known to be this user's alone.
            log.warning("could not tell whose %s is", path, exc_info=True)
            return False
        # Owned by this user (or by what this process gives what it makes: Administrators, run as one), protected
        # (the flags before the entries hold P), one entry: full access for this user, as made.
        flags, _, entries = access[2:].partition("(")
        return (owner in mine and access.startswith("D:") and "P" in flags
                and re.findall(r"\(([^)]*)\)", "(" + entries) in (["A;OICI;FA;;;%s" % me], entry))

    def make_own(self, path):
        import ctypes
        from ctypes import wintypes
        if not os.path.isdir(path) or _is_link(path):
            return False
        try:
            found = self._owner_and_access(path)
            mine = (self._sid(self.TOKEN_USER), self._sid(self.TOKEN_OWNER))
        except OSError:
            log.warning("could not tell whose %s is", path, exc_info=True)
            return False
        if found is None or found[0] not in mine:
            # Someone else's folder: left as it is.
            return False
        kernel32, advapi32 = self._dlls()
        descriptor = ctypes.c_void_p()
        if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(self._access(), self.REVISION,
                                                                            ctypes.byref(descriptor), None):
            raise self._error()
        try:
            present, access, defaulted = wintypes.BOOL(), ctypes.c_void_p(), wintypes.BOOL()
            if not advapi32.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(access),
                                                      ctypes.byref(defaulted)):
                raise self._error()
            # The access list set, protected from what the folder above would pass down.
            error = advapi32.SetNamedSecurityInfoW(path, self.FILE_OBJECT, self.DACL | self.PROTECTED, None, None,
                                                   access, None)
            if error != 0:
                raise self._error(error)
        finally:
            kernel32.LocalFree(descriptor)
        return self.own(path)


# The system's own calls for the short path (the tests hand in a stand-in).
SYSTEM = WindowsSystem() if sys.platform == "win32" else System()


def link_places():
    """Where the short path may go, the first that is short and in the ANSI code page wins, each as (folder, shared):
    openDMT3's own beside its program (%LocalAppData%\\openDMT3-link, this user's alone), else, when a Windows user
    name has letters outside the ANSI code page (which %LocalAppData% then has too), a folder made for the PLAY under
    a random name in a folder every user shares (%PUBLIC%, %ProgramData%)."""
    places = []
    if os.environ.get("LOCALAPPDATA"):
        places.append((os.path.join(os.environ["LOCALAPPDATA"], "openDMT3-link"), False))
    for base in (os.environ.get("PUBLIC"), os.environ.get("ProgramData")):
        if base:
            places.append((base, True))
    return places


def _place(item):
    """A place as (folder, shared): a plain folder is this user's own (the tests give such)."""
    return item if isinstance(item, tuple) else (item, False)


def _make_junction(target, link):
    """A junction at `link` to the folder `target` (no administrator rights needed); Windows only."""
    import _winapi
    _winapi.CreateJunction(target, link)


def _is_link(path):
    """Whether a path is a link to a folder (a junction, or a symbolic link), not a folder of its own."""
    isjunction = getattr(os.path, "isjunction", None)
    return os.path.islink(path) or bool(isjunction and isjunction(path))


def take_short_path_away(place):
    """Remove the short path in `place` if one is there: the link alone, never what it leads to (rmdir on a junction
    removes the junction; a folder of its own at that name is left as it is). True when none is there afterwards."""
    link = os.path.join(place, "game")
    if not os.path.lexists(link):
        return True
    if not _is_link(link):
        # Not one of openDMT3's links: something someone made there, never removed.
        log.warning("%s is a folder, not openDMT3's short path: left as it is", link)
        return False
    try:
        if os.path.islink(link):
            os.unlink(link)
        else:
            os.rmdir(link)
        return True
    except OSError:
        log.warning("the short path %s could not be taken away", link, exc_info=True)
        return False


def take_short_paths_away(system=None):
    """Every short path openDMT3 may have left (a launcher that ended while its game ran keeps none past the next
    start, and removing openDMT3 keeps none at all): openDMT3's own place's link, and in a shared folder each folder a
    PLAY made there that is this user's alone, with its link."""
    system = system or SYSTEM
    for item in link_places():
        folder, shared = _place(item)
        if not shared:
            take_short_path_away(folder)
            continue
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            made = os.path.join(folder, name)
            # Only a folder of a PLAY's (its name's form) that is this user's alone: another user's is never touched.
            if SHARED_PATTERN.fullmatch(name) and system.own(made) and take_short_path_away(made):
                try:
                    os.rmdir(made)
                except OSError:
                    log.warning("the folder %s could not be taken away", made, exc_info=True)


def _fits(path):
    """True when the client can be given a path to the game folder: in the ANSI code page, with room for the longest
    path the game opens inside it."""
    return ansi(path) and len(path) + LONGEST_INSIDE < MAX_PATH


def _leads_to(path, root):
    """True when a path leads to the game folder and nowhere else (realpath follows junctions and links alike)."""
    return os.path.normcase(os.path.realpath(path)) == os.path.normcase(os.path.realpath(root))


def _folder_for_link(folder, shared, system):
    """The folder of this user's alone the link goes in: openDMT3's own (made, or made this user's alone, when it is
    there and this user's), or one made new under a random name in a shared folder. None when the place is passed by
    (someone else's folder, a link, no random name free)."""
    if not shared:
        if not os.path.lexists(folder):
            try:
                os.makedirs(os.path.dirname(folder) or ".", exist_ok=True)
                system.make_folder(folder)
            except OSError:
                log.warning("could not make %s for the short path", folder, exc_info=True)
                return None
            return folder
        return folder if system.make_own(folder) else None
    for _ in range(NAME_TRIES):
        made = os.path.join(folder, SHARED_NAME % secrets.token_hex(8))
        try:
            # New, this user's alone from the moment it is there: one that is there already is never used.
            system.make_folder(made)
            return made
        except FileExistsError:
            continue
        except OSError:
            # A shared folder this user may not make a folder in: passed by.
            log.warning("could not make a folder in %s for the short path", folder, exc_info=True)
            return None
    return None


def short_path(root, places=None, make=_make_junction, system=None):
    """A path the client can be given for the game folder at root: root itself when it can; else its own 8.3 short
    name when that fits and leads to it; else a junction to it in a folder of this user's alone in the first of
    `places` (link_places()) whose path fits, made new for this PLAY and checked to lead to root. LaunchError when
    none can be made."""
    system = system or SYSTEM
    why = needs_short_path(root)
    if why is None:
        return root
    short = system.short_name(root)
    if short and _fits(short) and _leads_to(short, root):
        # No link at all: the drive keeps 8.3 names, and the folder's own fits.
        log.info("the client data's path is %s (%d characters): played through its short name %s", why, len(root),
                 short)
        return short
    for item in places if places is not None else link_places():
        folder, shared = _place(item)
        # The link's path as it will be (a shared place's folder has a name of a fixed length).
        link = os.path.join(os.path.join(folder, SHARED_NAME % ("0" * 16)) if shared else folder, "game")
        if not _fits(link):
            continue
        holder = _folder_for_link(folder, shared, system)
        if holder is None:
            continue
        link = os.path.join(holder, "game")
        # A link from an earlier PLAY leads to the folder used then: made again for this one. A folder of its own at
        # that name is not openDMT3's: this place is passed by.
        if not take_short_path_away(holder):
            continue
        make(root, link)
        # The link must lead to the game folder and nowhere else.
        if not _leads_to(link, root):
            take_short_path_away(holder)
            raise LaunchError("the short path %s does not lead to the client data" % link)
        # One line for the log (none on the screen): the game is played through openDMT3's short path.
        log.info("the client data's path is %s (%d characters): played through %s", why, len(root), link)
        return link
    raise LaunchError("the client data's path is %s and no short path could be made for it" % why)


def check_again(path, root, system=None):
    """Right before the game starts: the path it is given still leads to the game folder, and when it is a link of
    openDMT3's, the folder holding it is still this user's alone. LaunchError (the link taken away) when not."""
    system = system or SYSTEM
    if path == root:
        return
    if _is_link(path) and not system.own(os.path.dirname(path)):
        raise LaunchError("the short path %s is in a folder that is not this user's alone any more" % path)
    if not _leads_to(path, root):
        if _is_link(path):
            take_short_path_away(os.path.dirname(path))
        raise LaunchError("the short path %s does not lead to the client data" % path)


def start(game, own, popen=subprocess.Popen, env=None, places=None, make=_make_junction, system=None):
    """Start openDMT3's copy of the client (own: steps.Own) with the game folder as the current folder; the session.

    env: variables added to this program's own environment for the game (the in-game layer's choices,
    values.layer_environment). popen is replaceable so the tests can follow a stand-in program instead of the real
    game; places, make and system, so they can make the short path in a folder of their own.
    """
    # Opening the game opens a full-screen window: never from a test outside the virtual screen.
    if popen is subprocess.Popen:
        safety.refuse_windows_in_tests("the game")
    exe = own.client()
    if not os.path.isfile(exe):
        raise LaunchError('"%s" is not in %s yet; PLAY makes it first' % (g.FIXED_EXE, own.folder))
    # The game folder as the client can be given it: itself, or a short path to it.
    folder = short_path(game.root, places, make, system)
    # Checked again at the last moment: the folder holding the link is still this user's alone, the link still leads
    # to the game folder.
    check_again(folder, game.root, system)
    try:
        # The game reads its files relative to the current folder, so the game folder is the current one.
        if env:
            # The game gets everything this program has, and the layer's choices on top.
            process = popen([exe], cwd=folder, env=dict(os.environ, **env))
        else:
            process = popen([exe], cwd=folder)
    except OSError as e:
        # Windows refuses for reasons a player can act on: antivirus quarantine, a folder without access.
        raise LaunchError("Windows did not start the game: %s" % e) from None
    return Session(process, time.time())


def crash_dumps(own, since):
    """Crash dumps the game wrote after `since` (the client writes them in Dump\\, which openDMT3's library gives it
    in openDMT3's folder), newest first."""
    folder = own.path("Dump")
    if not os.path.isdir(folder):
        return []
    found = []
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        # Only dumps from this session count; older ones are from earlier crashes the player already saw.
        if os.path.isfile(path) and os.path.getmtime(path) >= since:
            found.append(path)
    return sorted(found, key=os.path.getmtime, reverse=True)


def running_clients(game):
    """Paths of programs from this folder (a game folder, or openDMT3's own for the game: anything with .root or
    .folder) that are running now (Windows only; elsewhere empty).

    The launcher must not rewrite the client copy or its libraries while the game runs them, nor put a game folder
    back while an earlier openDMT3's copy of the client runs from it.
    """
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes
    # Every process id, read with a buffer large enough for any desktop.
    psapi = ctypes.WinDLL("psapi")
    kernel32 = ctypes.WinDLL("kernel32")
    ids = (wintypes.DWORD * 4096)()
    needed = wintypes.DWORD()
    if not psapi.EnumProcesses(ids, ctypes.sizeof(ids), ctypes.byref(needed)):
        return []
    count = needed.value // ctypes.sizeof(wintypes.DWORD)
    root = os.path.normcase(os.path.abspath(getattr(game, "root", None) or game.folder))
    found = []
    # PROCESS_QUERY_LIMITED_INFORMATION is enough to read a process's image path, without admin rights.
    access = 0x1000
    for pid in ids[:count]:
        handle = kernel32.OpenProcess(access, False, pid)
        if not handle:
            continue
        try:
            size = wintypes.DWORD(32768)
            buf = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                path = os.path.normcase(buf.value)
                # A game program is any .exe directly in the folder (the client, or openDMT3's copy of it).
                if os.path.dirname(path) == root and path.endswith(".exe"):
                    found.append(buf.value)
        finally:
            kernel32.CloseHandle(handle)
    return found
