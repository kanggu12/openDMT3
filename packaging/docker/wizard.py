"""./dmt3 setup's wizard: a server set up in paged steps in the terminal, one question a page.

Welcome, Docker and ports, the address players type, the admin's ID, its password, the song list (from your game
folder, an archive holding it, or a song list the launcher saved), the installer to hand out, a page that confirms
them all, the setup's progress line by line, and what to do next. Each page shows at
once what its answer means (its preview); Esc goes back a page and Enter on to the next one.

The pages are plain functions of the answers (Answers) and of what they look at on this PC (an environment the front
door gives: FrontDoor in ./dmt3; the tests give a made-up one), so they are tested without a terminal. They are drawn
with curses, or asked as plain numbered prompts when the terminal cannot draw (TERM=dumb, no curses, a window too
small). Plain Python 3, as the front door is.

DMT3_WIZARD_CAPTURE=FOLDER writes each page's screen, as drawn, to FOLDER/NN-name.txt (the guide's and the tests'
text captures).
"""

import getpass
import importlib.util
import os
import sys
import textwrap
import threading
import time

# The site's and the game's ports, as the server publishes them (compose.yaml).
WEB_PORT, GAME_PORT = 4730, 4725
# The rules of an ID and a password, as the server's accounts take them (opendmt3/server/services/accounts.py).
ID_MAX, PASSWORD_MIN, PASSWORD_MAX = 8, 6, 16
# The smallest window the pages are drawn in; a smaller one is asked to grow, or the plain prompts are used.
MIN_COLUMNS, MIN_LINES = 64, 20
# How long the typing stops before a typed path is looked at (each look reads the game's archives' indexes).
IDLE = 0.35
# The installer's choices.
BUILD, FILE, NONE = "build", "file", "none"


# ------------------------------------------------------------------------------------------------ the answers

class Answers:
    """What the person chose, and what the pages looked at on the way (each None until looked at)."""

    def __init__(self):
        # Docker's checks as (key, ok, text, fix), and the LAN addresses as (address, where it is).
        self.docker = None
        self.addresses = None
        self.address = None
        # How many accounts the server's database has: None when it cannot be told yet, False before looking.
        self.accounts = False
        self.admin = "BOSS"
        # The password typed twice, or nothing: one is made and shown once at the end.
        self.password = ""
        self.again = ""
        self.game = ""
        # An archive's password, when the game's archive has one (asked on the game page only then).
        self.archive_password = ""
        # The game's files found in the usual places (each with its line), and each looked-at path's look and mounts.
        self.found = None
        self.surveys = {}
        self.mounts = {}
        self.installer = None
        self.installer_file = ""
        # The setup's lines as it runs: {key: [state, text]}, and what it gave back.
        self.progress = {}
        self.made_password = None
        self.failed = None
        self.done = False

    def game_path(self):
        """The game folder typed, as a path of this PC ("" for none)."""
        return clean_path(self.game) if self.game.strip() else ""

    def installer_path(self):
        """The installer file typed, as a path of this PC ("" for none)."""
        return clean_path(self.installer_file) if self.installer_file.strip() else ""

    def survey(self):
        """The look at the path typed (with the password typed), or None when it was not looked at yet."""
        return self.surveys.get((clean_path(self.game), self.archive_password)) if self.game.strip() else None

    def kept(self):
        """(mounts, refused, readable by the server) of the game folder typed, or None before it was looked at (or
        when what was typed is no folder: an archive or a song list is read once, never kept mounted)."""
        return self.mounts.get(clean_path(self.game)) if self.game.strip() else None

    def needs_password(self):
        """True when the look at the path typed says its archive has a password (or the one typed is not its)."""
        found = self.survey()
        return bool(found) and found.get("key") in ("error.source.password", "error.source.wrong_password")


# ------------------------------------------------------------------------------------------------ paths

def clean_path(text):
    """A typed or pasted path as a path of this PC: quotes around it off, ~ for the home folder, and a Windows path
    (C:\\Users\\...) as WSL sees it (/mnt/c/Users/...) when that drive is mounted there."""
    text = text.strip()
    # A path pasted from a file manager often comes in quotes.
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1]
    if len(text) >= 3 and text[1] == ":" and text[2] in "\\/" and text[0].isalpha():
        drive = "/mnt/%s" % text[0].lower()
        if os.path.isdir(drive):
            # The Windows drive's folder under WSL, with the slashes turned.
            text = drive + "/" + text[3:].replace("\\", "/")
    return os.path.expanduser(text)


def complete(text):
    """Tab on a typed path: (the path completed as far as every match agrees, the names that match). A single folder
    gets its slash; letter case is ignored when nothing matches as typed (Windows' folders)."""
    path = clean_path(text) if text.strip() else ""
    head, tail = os.path.split(path)
    try:
        names = sorted(os.listdir(head or "."))
    except OSError:
        return text, []
    # Hidden names only when a dot was typed.
    names = [n for n in names if tail.startswith(".") or not n.startswith(".")]
    matches = [n for n in names if n.startswith(tail)]
    if not matches:
        # Windows' folders are named in any case; typing "desk" should find "Desktop".
        matches = [n for n in names if n.lower().startswith(tail.lower())]
        if not matches:
            return text, []
        tail = matches[0][:len(tail)]
    common = os.path.commonprefix(matches) if len(matches) > 1 else matches[0]
    done = os.path.join(head, common) if head else common
    if len(matches) == 1 and os.path.isdir(done):
        done += os.sep
    return done, matches


# ------------------------------------------------------------------------------------------------ lines

def good(text):
    """A line of a check that passed."""
    return (text, "ok")


def bad(text):
    """A line of a check that did not."""
    return (text, "bad")


def plain(text=""):
    """A line of words."""
    return (text, None)


def dim(text):
    """A line that says how, less loud than the rest."""
    return (text, "dim")


def marker(tone):
    """What stands before a line, so it reads the same without colour: ok, no, or nothing."""
    return {"ok": "ok  ", "bad": "no  "}.get(tone, "")


def site(address):
    """The site's address at an address of this PC."""
    return "http://%s:%d/" % (address, WEB_PORT)


def short(text, room=84):
    """A long path shown by its end, where the folders that tell it apart are."""
    return text if len(text) <= room else "..." + text[-(room - 3):]


def size(n):
    """A file's size in words."""
    return "%.1f MB" % (n / 1048576.0) if n >= 1048576 else "%d KB" % max(1, n // 1024)


# ------------------------------------------------------------------------------------------------ fields

class Text:
    """A line to type in: its answer's name in Answers, its label, hidden letters (a password), and Tab completion
    (a path)."""

    def __init__(self, attr, label, secret=False, paths=False):
        self.attr, self.label, self.secret, self.paths = attr, label, secret, paths

    def shown(self, a):
        return True


class Choice:
    """One of a few options: its answer's name, its label, and the options as (value, words) for the answers."""

    def __init__(self, attr, label, options):
        self.attr, self.label, self.options = attr, label, options

    def shown(self, a):
        return True


class PathOnly(Text):
    """A path typed only when its choice asks for one (the installer's file)."""

    def __init__(self, attr, label, when):
        super().__init__(attr, label, paths=True)
        # (the answer's name, its value) that shows this field.
        self.when = when

    def shown(self, a):
        return getattr(a, self.when[0]) == self.when[1]


# ------------------------------------------------------------------------------------------------ pages

class Page:
    """One step of the wizard: its short name for the steps' row, its title, the lines above its question, the
    question (its fields), what the answer means (the preview), a slow look-up to run while the person waits
    (pending), and the check on Next (leave: the words that keep the page, or None)."""

    name = ""
    title = ""
    # The page's own keys, said in the footer.
    keys = ""
    # Whether Esc may leave it (the progress and the last page say no).
    back = True

    def can_back(self, a):
        """Whether Esc may leave the page now."""
        return self.back

    def again(self, a):
        """True when Enter looks at the page's own facts again instead of going on (the Docker page while something
        stops the setup): what it looked at is forgotten here, so the next look is a new one."""
        return False

    def skip(self, a):
        return False

    def body(self, a, env):
        return []

    def fields(self, a, env):
        return []

    def preview(self, a, env):
        return []

    def pending(self, a, env):
        return None

    def leave(self, a, env):
        return None

    def key(self, a, env, k):
        return False


class Welcome(Page):
    name, title = "Welcome", "Set up an openDMT3 server"

    def body(self, a, env):
        return [plain("This sets up an openDMT3 server: the game connects to it, and its site keeps"),
                plain("the logins, the records and the launcher to download."),
                plain(),
                plain("It will:"),
                plain("  1. check Docker and the two ports the server uses (%d and %d)" % (GAME_PORT, WEB_PORT)),
                plain("  2. ask for this server's address, the admin's ID and password,"),
                plain("     where the song list comes from and the installer to hand out"),
                plain("  3. show every answer on one page before anything is done"),
                plain("  4. build the server, make the account, import the song list, and start it"),
                plain(),
                plain("What you need:"),
                plain("  - Docker, running on this PC"),
                plain("  - your own game folder, an archive holding it, or a song list the launcher saved: the"),
                plain("    server reads only the song list, which holds the jackets and the DJ cards too"),
                plain(),
                # No key is named here: the drawn pages say theirs at the bottom, the plain prompts in each prompt.
                dim("Every page can be changed later.")]


class Docker(Page):
    name, title = "Docker", "Docker and ports"
    keys = "r  checks again"

    def pending(self, a, env):
        if a.docker is None:
            return lambda: setattr(a, "docker", env.docker_checks())
        return None

    def body(self, a, env):
        if a.docker is None:
            return [dim("Looking at Docker and the ports...")]
        out = []
        for key, ok, text, fix in a.docker:
            out.append(good(text) if ok else bad(text))
            if not ok and fix:
                out.append(dim("      fix: " + fix))
        return out

    def preview(self, a, env):
        if a.docker is None:
            return []
        if blocking(a.docker):
            return [bad("The server cannot start until these are fixed.")]
        return [good("Docker is ready, and the ports are free for the server.")]

    def again(self, a):
        if a.docker is not None and blocking(a.docker):
            # Enter checks again: what was looked at is forgotten, and the page's next look is a new one.
            a.docker = None
            return True
        return False

    def leave(self, a, env):
        if a.docker is None:
            return "Docker is still being looked at."
        if blocking(a.docker):
            # Not reached by Enter (again() looks first); kept for a caller that asks leave() alone.
            return "The server cannot start until the problems above are fixed."
        return None

    def key(self, a, env, k):
        if k in ("r", "R"):
            # Looked at again on the next idle moment.
            a.docker = None
            return True
        return False


def blocking(checks):
    """The checks that stop the setup: every failed one but the image's, which the setup builds itself."""
    return [c for c in checks if not c[1] and c[0] != "image"]


class Address(Page):
    name, title = "Address", "This server's address"
    keys = "Up/Down  choose"

    def pending(self, a, env):
        if a.addresses is None:
            def look():
                a.addresses = env.addresses() or [("127.0.0.1", "this PC only")]
                # The first address found is the one most likely on the LAN.
                a.address = a.address or a.addresses[0][0]
            return look
        return None

    def body(self, a, env):
        if a.addresses is None:
            return [dim("Looking at this PC's addresses...")]
        return [plain("Players reach the server at this PC's address: in their browser for the site, and"),
                plain("in the launcher. These are the addresses this PC has on its networks.")]

    def fields(self, a, env):
        return [Choice("address", "Address", lambda: [(addr, "%-15s  %s" % (addr, where))
                                                       for addr, where in (a.addresses or [])])]

    def preview(self, a, env):
        if not a.address:
            return []
        out = [good("The site: " + site(a.address)), good("The game: %s:%d" % (a.address, GAME_PORT))]
        if a.address.startswith("127."):
            out.append(dim("Only this PC reaches this address; other PCs need one of the others."))
        return out


class AdminId(Page):
    name, title = "Admin", "The first admin account"

    def pending(self, a, env):
        if a.accounts is False:
            return lambda: setattr(a, "accounts", env.accounts())
        return None

    def body(self, a, env):
        if a.accounts is False:
            return [dim("Looking at the server's database...")]
        if a.accounts:
            return [plain("Accounts in the server's database already: %d." % a.accounts),
                    plain("No account is made: sign in with the admin account you have.")]
        return [plain("The owner's account, with the admin pages: you sign in to the site with it, and play"),
                plain("with it too. Its ID is what the game's keypad types.")]

    def fields(self, a, env):
        return [] if a.accounts else [Text("admin", "ID")]

    def preview(self, a, env):
        if a.accounts:
            return [good("The admin account you have stays as it is.")]
        rules = id_rules(a.admin)
        out = [(text, "ok" if ok else "bad") for ok, text in rules]
        if all(ok for ok, _ in rules):
            out.append(dim("Signs in as %s (IDs are kept in capitals)." % a.admin.strip().upper()))
        return out

    def leave(self, a, env):
        if a.accounts is False:
            return "The database is still being looked at."
        if a.accounts:
            return None
        failed = [text for ok, text in id_rules(a.admin) if not ok]
        return failed[0] if failed else None


def id_rules(login_id):
    """Each rule of an ID as (met, words)."""
    login_id = login_id.strip()
    return [(1 <= len(login_id) <= ID_MAX, "1 to %d characters" % ID_MAX),
            (bool(login_id) and login_id.isascii() and login_id.isalnum(), "only letters and digits")]


class Password(Page):
    name, title = "Password", "The admin's password"
    keys = "Up/Down  the other box"

    def skip(self, a):
        # No account is made: no password to choose.
        return bool(a.accounts)

    def body(self, a, env):
        return [plain("Type a password twice, or leave both empty and one is made for you; it is shown once"),
                plain("at the end. The game's keypad types it too: %d to %d letters or digits." %
                      (PASSWORD_MIN, PASSWORD_MAX))]

    def fields(self, a, env):
        return [Text("password", "Password", secret=True), Text("again", "Again", secret=True)]

    def preview(self, a, env):
        if not a.password and not a.again:
            return [good("A password is made for you and shown once at the end.")]
        return [(text, "ok" if ok else "bad") for ok, text in password_rules(a.password, a.again)]

    def leave(self, a, env):
        if not a.password and not a.again:
            return None
        failed = [text for ok, text in password_rules(a.password, a.again) if not ok]
        return failed[0] if failed else None


def password_rules(password, again):
    """Each rule of a password typed twice as (met, words)."""
    return [(PASSWORD_MIN <= len(password) <= PASSWORD_MAX, "%d to %d characters" % (PASSWORD_MIN, PASSWORD_MAX)),
            (bool(password) and password.isascii() and password.isalnum(), "only letters and digits"),
            (bool(password) and password == again, "typed the same twice")]


class Game(Page):
    name, title = "Game", "The song list"
    keys = "Tab  completes   Up/Down  one found"

    def pending(self, a, env):
        if a.found is None:
            return lambda: setattr(a, "found", env.found_games())
        path = clean_path(a.game) if a.game.strip() else None
        if path and (path, a.archive_password) not in a.surveys:
            def look():
                found = env.survey(path, a.archive_password or None)
                a.surveys[(path, a.archive_password)] = found
                # The mounts only for a game folder found: they walk the folder (an archive or a song list is read
                # once, never kept mounted).
                if found.get("kind") == "folder" and found.get("ready"):
                    a.mounts[path] = env.mounts(path)
            return look
        return None

    def body(self, a, env):
        out = [plain("Type or paste the path to your game folder (or a folder above it), an archive holding"),
               plain("the game (.zip, .7z, .rar; a split one by its first part), or a song list the launcher"),
               plain("saved. The server reads only the song list, which holds the jackets and the DJ cards"),
               plain("too. Empty: none now; ./dmt3 catalog PATH imports it later.")]
        if a.found is None:
            out.append(dim("Looking in the usual places..."))
        elif a.found:
            out.append(plain("Found on this PC:"))
            chosen = clean_path(a.game) if a.game.strip() else None
            for item in a.found[:5]:
                # Each with its one line, as the site's Song list tab shows it.
                out.append(plain(("> " if item["path"] == chosen else "  ") + short(item["path"])))
                out.append((("      " + item["line"]), "ok" if item["ready"] else "bad"))
        return out

    def fields(self, a, env):
        fields = [Text("game", "Path", paths=True)]
        if a.needs_password() or a.archive_password:
            # Only for an archive that has one.
            fields.append(Text("archive_password", "Password", secret=True))
        return fields

    def preview(self, a, env):
        if not a.game.strip():
            return [dim("No song list now: songs show as numbers until ./dmt3 catalog PATH imports it.")]
        found = a.survey()
        if found is None:
            return [dim("Looking at it...")]
        out = [(found["line"], "ok" if found["ready"] else "bad")]
        if not found["ready"]:
            return out
        if found["kind"] == "folder":
            out.append(good("the game folder: " + short(found["path"], 78)))
        elif found["kind"] == "archive":
            out.append(dim("only the files the server needs are taken out, into a folder of its own, then removed"))
        out += [(text, "ok" if ok else "bad") for ok, text in found["parts"]]
        kept = a.kept()
        if kept:
            mounts, refused, readable = kept
            if len(mounts) > 1:
                out.append(good("links inside it are followed (more folders mounted read-only: %d)" %
                                (len(mounts) - 1)))
            for path in refused:
                out.append(bad("links into %s cannot be followed in the container" % path))
            out.append(good("the Song list tab's Import: offered") if readable else
                       dim("the Song list tab's Import: not offered (only its owner reads these files); "
                           "./dmt3 catalog imports it again"))
        return out

    def leave(self, a, env):
        if not a.game.strip():
            return None
        found = a.survey()
        if found is None:
            # Pressed before the look finished: the page says when it has.
            return "It is still being looked at."
        if not found["ready"]:
            return found["line"]
        return None

    def key(self, a, env, k):
        if k in ("up", "down") and a.found:
            # One found, the next or the one before, put in the box.
            paths = [item["path"] for item in a.found[:5]]
            chosen = clean_path(a.game) if a.game.strip() else None
            at = paths.index(chosen) if chosen in paths else -1
            at = (at + (1 if k == "down" else -1)) % len(paths)
            a.game = paths[at]
            return True
        return False


class Installer(Page):
    name, title = "Installer", "The installer to hand out"
    keys = "Up/Down  choose   Tab  to the path"

    def options(self, a, env):
        """The choices: the one ./dmt3 build left (when there is one), a file, none for now."""
        built = env.default_installer()
        out = [(BUILD, "The one ./dmt3 build left: " + built)] if built else []
        return out + [(FILE, "A file"), (NONE, "None for now")]

    def body(self, a, env):
        if a.installer is None:
            # First shown: the build's own when there is one, else none.
            a.installer = BUILD if env.default_installer() else NONE
        return [plain("The site's Download page hands out the launcher's installer."),
                plain("./dmt3 build makes one; a file you have works too.")]

    def fields(self, a, env):
        return [Choice("installer", "Installer", lambda: self.options(a, env)),
                PathOnly("installer_file", "File", ("installer", FILE))]

    def chosen(self, a, env):
        """The installer's path as chosen, or None."""
        if a.installer == BUILD:
            return env.default_installer()
        if a.installer == FILE and a.installer_file.strip():
            return clean_path(a.installer_file)
        return None

    def preview(self, a, env):
        if a.installer == NONE:
            return [dim("The Download page says there is no installer yet; ./dmt3 setup --installer FILE puts one.")]
        path = self.chosen(a, env)
        if not path:
            return [dim("Type the installer's path.")]
        info = env.installer_info(path)
        if info is None:
            return [bad("no such file: " + path)]
        return [good("version %s, %s" % (info["version"] or "not written in the file", size(info["size"])))]

    def leave(self, a, env):
        if a.installer == NONE:
            return None
        path = self.chosen(a, env)
        if not path or env.installer_info(path) is None:
            return "Choose an installer that is there, or None for now."
        return None


class Confirm(Page):
    name, title = "Confirm", "Ready to set up"
    keys = "1-5  change that answer"

    def body(self, a, env):
        found = a.survey()
        kept = a.kept()
        if a.accounts:
            admin = "accounts in the database: %d (none is made)" % a.accounts
        else:
            admin = "%s, password %s" % (a.admin.strip().upper(), "typed" if a.password else "made for you")
        if not a.game.strip():
            game, parts = "none now (./dmt3 catalog imports it later)", []
        else:
            game = short(found["path"] if found and found.get("path") else a.game, 70)
            # Its line, then its parts under it, one a line.
            parts = [text for _, text in env.lines(found)] if found else []
        installer = Installer().chosen(a, env) if a.installer != NONE else None
        rows = [("1", "Docker and ports", "ready"),
                ("2", "Address", site(a.address or "127.0.0.1")),
                ("3", "Admin", admin),
                ("4", "Song list from", game),
                ("5", "Installer", installer or "none for now")]
        out = [plain("Nothing is done until Enter. Press a number to change that answer.")]
        for number, what, value in rows:
            out.append(plain("%s  %-17s %s" % (number, what, value)))
            if number == "4":
                out += [plain("   %-17s %s" % ("", part)) for part in parts]
        if kept:
            out.append(plain("   %-17s %s" % ("Import again", "offered on the site's Song list tab" if kept[2]
                                              else "with ./dmt3 catalog")))
        return out

    def preview(self, a, env):
        return [dim("Enter starts the setup. It builds the image, which takes a few minutes the first time.")]


class Progress(Page):
    name, title = "Setup", "Setting up"
    back = False

    def can_back(self, a):
        # Back to change the answers only once the setup stopped at a step.
        return bool(a.failed)

    def pending(self, a, env):
        if not a.progress or a.failed == "again":
            return lambda: run_setup(a, env, self.redraw)
        return None

    def body(self, a, env):
        out = []
        for key, label in STEPS:
            state, text = a.progress.get(key, ("wait", ""))
            tone = {"ok": "ok", "bad": "bad"}.get(state)
            words = {"wait": "waiting", "run": "running", "skip": "skipped", "ok": "", "bad": ""}[state]
            line = "%-19s %s" % (label, text or words)
            out.append((("..  " if state == "run" else "    " if state in ("wait", "skip") else "") + line, tone))
        return out

    def preview(self, a, env):
        if a.failed:
            # What to press is said where the keys are (the drawn page's bottom line, the plain prompt).
            return [bad("The setup stopped at %s." % a.failed)]
        if a.done:
            return [good("The server is set up and running.")]
        return [dim("Each step in turn; the image takes a few minutes the first time.")]

    def leave(self, a, env):
        if a.failed:
            # Enter tries again: every step is safe to run again.
            a.progress, a.failed = {}, None
            return "Trying again."
        return None if a.done else "The setup is still running."

    @staticmethod
    def redraw():
        # Replaced by the screen's own while it is drawn.
        pass


class Done(Page):
    name, title = "Done", "Your server is running"
    back = False

    def body(self, a, env):
        address = a.address or "127.0.0.1"
        # An address of this PC alone is one no other PC reaches: said so, with how to choose another.
        alone = address.startswith("127.")
        out = [plain("The site:"),
               good("  on this PC:      " + site("127.0.0.1")),
               # (Four spaces in the place of the line above's "ok  ", so the two addresses stand in one column.)
               dim("      from other PCs:  not reachable at this address (./dmt3 setup again to choose another)") if alone
               else good("  from other PCs:  " + site(address)),
               plain()]
        if a.accounts:
            out.append(plain("Sign in with the admin account you have."))
        else:
            out.append(plain("The admin account (the password is shown only this once):"))
            out.append(plain("  ID        " + a.admin.strip().upper()))
            out.append(plain("  password  " + (a.made_password or a.password or "(see the setup's log)")))
        # The address chosen, so the site's pages and the message to send a player carry the one players reach.
        out += [plain(),
                plain("Next:"),
                plain("  1. Open %s and sign in." % site(address))]
        if not alone:
            # The accounts first: the Download page asks for a sign-in, and each account's message has it.
            out += [plain("  2. Make the players' accounts on Admin, Players: each gives a message to send."),
                    plain("  3. Send each player their message: it has the Download page and the steps.")]
        return out

    def preview(self, a, env):
        # What Enter does here is said where the keys are (the drawn page's bottom line, the plain prompt).
        return [dim("./dmt3 alone lists the other commands.")]


# The setup's lines, in order: the front door's steps by key, the catalog's three parts, and the check.
STEPS = [("image", "Server image"), ("data", "Data folder"), ("account", "Admin account"),
         ("songs", "Song list"), ("jackets", "Jackets"), ("cards", "DJ cards"),
         ("installer", "Installer"), ("server", "Server up"), ("check", "Check")]


def pages():
    """The wizard's pages, in order."""
    return [Welcome(), Docker(), Address(), AdminId(), Password(), Game(), Installer(), Confirm(), Progress(), Done()]


# The pages the confirm page's numbers go back to, by their class.
CHANGE = {"1": Docker, "2": Address, "3": AdminId, "4": Game, "5": Installer}


def step(at, ordered, a, forward=True):
    """The page after (or before) the one at `at`, past the pages that skip themselves."""
    move = 1 if forward else -1
    at += move
    while 0 <= at < len(ordered) and ordered[at].skip(a):
        at += move
    return max(0, min(at, len(ordered) - 1))


# ------------------------------------------------------------------------------------------------ the setup

def run_setup(a, env, redraw):
    """Run the setup the answers ask for, each step's line in a.progress as it goes (redraw shows it). Stops at the
    first step that fails (a.failed names it); a.done once the check passed."""
    a.progress, a.failed, a.done = {}, None, False

    def mark(key, state, text=""):
        a.progress[key] = (state, text)
        redraw()

    def stream(key, cmd):
        """A command, its last line of output shown on its step's line while it runs; (code, every line)."""
        mark(key, "run")
        return env.stream(cmd, lambda line: mark(key, "run", line.strip()[:70]))

    # The image first: counting the accounts runs in it.
    code, lines = stream("image", env.build_command())
    if code:
        return fail(a, "image", "Server image", lines, mark)
    mark("image", "ok", "built")
    a.accounts = env.accounts()
    if a.address and hasattr(env, "keep_address"):
        # Kept before the server starts, so the server is given it: the message to send a player carries the address
        # chosen here, never the one the admin's own browser used (127.0.0.1 on the server PC).
        env.keep_address(a.address)
    for key, what, cmd in env.plan(a):
        if key == "image":
            continue
        if key == "server" and a.game.strip() and a.kept() and a.kept()[2]:
            # Kept mounted before the server starts, so its Song list tab can import it again.
            env.keep_game(clean_path(a.game))
        code, lines = stream("songs" if key == "catalog" else key, cmd)
        if key == "catalog":
            if code:
                return fail(a, "songs", "Song list", lines, mark)
            # The server's own lines: one for each part, ok or not yet; a part it did not name, said so.
            said = dict(catalog_lines(lines))
            for part in ("songs", "jackets", "cards"):
                text = said.get(part)
                mark(part, "bad" if text is None or "not yet" in text else "ok", text or "not said by the server")
            continue
        if code:
            return fail(a, key, dict(STEPS)[key], lines, mark)
        if key == "account":
            # The password the server made, from its line "made ID, DJ name ..., password XXXX".
            made = [line for line in lines if line.startswith("made ")]
            if made and "password " in made[-1]:
                a.made_password = made[-1].rsplit("password ", 1)[1].strip()
            mark(key, "ok", "%s, with the admin pages" % a.admin.strip().upper())
        else:
            mark(key, "ok", {"data": "made", "installer": "on the Download page", "server": "started"}.get(key, ""))
    for key in ("account", "songs", "jackets", "cards", "installer"):
        if key not in a.progress:
            why = {"account": "the database has accounts", "installer": "none for now"}.get(key, "no song list now")
            mark(key, "skip", why)
    mark("check", "run", "waiting for the server")
    checks = env.check()
    failed = [text for ok, text in checks if not ok]
    if failed:
        return fail(a, "check", "Check", failed, mark)
    mark("check", "ok", "the site and the game port answer")
    a.done = True
    return True


def catalog_lines(lines):
    """The parts the server's --catalog printed: (part, its line) for the song list, the jackets, the DJ cards."""
    out = []
    for line in lines:
        for prefix, part in (("song list:", "songs"), ("jackets:", "jackets"), ("DJ cards:", "cards")):
            if line.startswith(prefix):
                out.append((part, line.strip()))
    return out


def fail(a, key, label, lines, mark):
    """A step that failed: its line says so with the last thing it printed."""
    last = [line.strip() for line in lines if line.strip()]
    mark(key, "bad", (last[-1] if last else "failed")[:70])
    a.failed = label
    return False


# ------------------------------------------------------------------------------------------------ plain prompts

def run_plain(env, ask=input, secret=getpass.getpass, out=print, a=None):
    """The wizard as numbered prompts, one page after another, for a terminal that cannot draw. "b" goes back, Enter
    keeps what is shown; the end of input stops. Returns the exit code."""
    a = a or Answers()
    ordered = pages()
    at = 0
    try:
        while True:
            page = ordered[at]
            if isinstance(page, Progress):
                # Each step's line printed once it is done (ok, a problem, or skipped).
                page.redraw = printer(a, out)
            running = isinstance(page, Progress)
            if running:
                # The setup's title first, then each step's line as it is done (printer).
                out("")
                out("== Step %d of %d: %s" % (at + 1, len(ordered), page.title))
            # What the page looks up first (each look may give the next: the found folders, then a survey).
            for _ in range(4):
                look = page.pending(a, env)
                if not look:
                    break
                look()
            # A page that asks nothing (the checks, the confirm page, the end) says what its facts mean with them,
            # before its one prompt; a page with questions says it after the answers it is about.
            asks = bool([f for f in page.fields(a, env) if f.shown(a)])
            if not running:
                out("")
                out("== Step %d of %d: %s" % (at + 1, len(ordered), page.title))
                for text, tone in page.body(a, env):
                    out(marker(tone) + text)
            if not asks:
                for text, tone in page.preview(a, env):
                    out(marker(tone) + text)
            answer = ask_fields(page, a, env, ask, secret, out)
            if answer == "back":
                at = step(at, ordered, a, forward=False) if page.can_back(a) else at
                continue
            if isinstance(page, Confirm) and answer in CHANGE:
                at = next(i for i, p in enumerate(ordered) if isinstance(p, CHANGE[answer]))
                continue
            if page.again(a):
                # Enter on a page that stops the setup: looked at anew (the loop's next turn looks and prints it).
                continue
            if asks:
                for text, tone in page.preview(a, env):
                    out(marker(tone) + text)
            error = page.leave(a, env)
            if error:
                out("!!  " + error)
                continue
            if isinstance(page, Done):
                return 0
            at = step(at, ordered, a)
    except (EOFError, KeyboardInterrupt):
        out("")
        out("Setup stopped.")
        return 1


def printer(a, out):
    """The plain prompts' redraw for the setup's progress: each step's line once it is done."""
    shown = {}

    def redraw():
        for key, label in STEPS:
            state, text = a.progress.get(key, ("wait", ""))
            if state in ("ok", "bad", "skip") and shown.get(key) != (state, text):
                shown[key] = (state, text)
                out("%s%-19s %s" % (marker({"ok": "ok", "bad": "bad"}.get(state)) or "    ", label,
                                     text or state))
    return redraw


def ask_fields(page, a, env, ask, secret, out):
    """Each field of a page asked in turn; "back" when b was typed, a confirm page's number, or None."""
    fields = [f for f in page.fields(a, env) if f.shown(a)]
    if not fields:
        if isinstance(page, Progress) and not a.failed:
            return None
        if isinstance(page, Confirm):
            hint = "Enter starts the setup, 1-5 changes an answer, b goes back"
        elif isinstance(page, Progress):
            hint = "Enter tries again, b goes back"
        elif isinstance(page, Docker) and a.docker is not None and blocking(a.docker):
            # Enter here looks again (Page.again): going on is not possible until the checks pass.
            hint = "Enter checks again, b goes back"
        elif isinstance(page, Done):
            # The last page: there is nothing to go on to.
            hint = "Enter closes this"
        else:
            hint = "Enter goes on" + (", b goes back" if page.can_back(a) else "")
        reply = ask("[%s] " % hint).strip()
        return "back" if reply.lower() == "b" and page.can_back(a) else reply or None
    for field in fields:
        # A field shown only for one choice is asked after that choice was made.
        if not field.shown(a):
            continue
        if isinstance(field, Choice):
            options = field.options()
            current = getattr(a, field.attr)
            for number, (value, words) in enumerate(options, start=1):
                out("  %d. %s%s" % (number, words, "   (chosen)" if value == current else ""))
            reply = ask("%s: number, Enter keeps the chosen one, b goes back: " % field.label).strip()
            if reply.lower() == "b":
                return "back"
            if reply.isdigit() and 1 <= int(reply) <= len(options):
                setattr(a, field.attr, options[int(reply) - 1][0])
        else:
            current = getattr(a, field.attr)
            shown = "" if field.secret or not current else " [%s]" % current
            reply = (secret if field.secret else ask)("%s%s (b goes back): " % (field.label, shown))
            if reply.strip().lower() == "b":
                return "back"
            if reply.strip() or field.secret:
                setattr(a, field.attr, reply.strip())
        # A typed path is looked at before the next question (and the preview).
        look = page.pending(a, env)
        if look:
            look()
    return None


# ------------------------------------------------------------------------------------------------ curses

class Screen:
    """The pages drawn with curses: a title row with the steps, the page's lines, its fields, its preview, and the
    keys at the bottom. Colour only marks ok (green) and a problem (red); the words before each line say the same."""

    def __init__(self, scr, env, a, capture=None):
        import curses
        self.curses, self.scr, self.env, self.a = curses, scr, env, a
        self.ordered = pages()
        self.at, self.focus, self.error, self.capture = 0, 0, "", capture
        self.last_key = time.monotonic()
        # Green for ok, red for a problem, on the terminal's own background; plain where colour is not there.
        self.tones = {"ok": curses.A_BOLD, "bad": curses.A_BOLD, "dim": curses.A_DIM, None: curses.A_NORMAL}
        try:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_GREEN, -1)
            curses.init_pair(2, curses.COLOR_RED, -1)
            self.tones["ok"] = curses.color_pair(1)
            self.tones["bad"] = curses.color_pair(2) | curses.A_BOLD
        except curses.error:
            pass
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    @property
    def page(self):
        return self.ordered[self.at]

    def put(self, y, x, text, attr=0):
        """Text at a place, cut at the window's edge, never past its last cell (curses refuses that one)."""
        rows, cols = self.scr.getmaxyx()
        if 0 <= y < rows and x < cols:
            try:
                self.scr.addnstr(y, x, text, max(0, cols - x - (1 if y == rows - 1 else 0)), attr)
            except self.curses.error:
                pass

    def lines(self, y, x, mark, text, attr):
        """One line of a page from row y, wrapped at the window's edge under its own start (past its marker);
        returns the row after it."""
        cols = self.scr.getmaxyx()[1]
        room = max(20, cols - x - len(mark) - 2)
        # Words kept whole; a path longer than the room is cut where it must be.
        parts = textwrap.wrap(text, room, break_on_hyphens=False) or [""]
        for i, part in enumerate(parts):
            self.put(y, x, (mark if i == 0 else " " * len(mark)) + part, attr)
            y += 1
        return y

    def draw(self):
        """The whole page, as the answers stand now."""
        curses, scr, a, page = self.curses, self.scr, self.a, self.page
        scr.erase()
        rows, cols = scr.getmaxyx()
        if cols < MIN_COLUMNS or rows < MIN_LINES:
            self.put(0, 0, "Make the window at least %d x %d to see the setup." % (MIN_COLUMNS, MIN_LINES))
            scr.refresh()
            return
        # The title row: the setup, the step, and every page's short name, this one in brackets.
        self.put(0, 1, "openDMT3 server setup", curses.A_BOLD)
        self.put(0, cols - 16, "step %2d of %2d" % (self.at + 1, len(self.ordered)))
        x = 1
        for i, p in enumerate(self.ordered):
            name = "[%s]" % p.name if i == self.at else " %s " % p.name
            self.put(1, x, name, curses.A_REVERSE if i == self.at else (curses.A_DIM if i > self.at else 0))
            x += len(name) + 1
        self.put(2, 0, "-" * (cols - 1), curses.A_DIM)
        self.put(3, 1, page.title, curses.A_BOLD)
        y = 5
        body = page.body(a, self.env)
        for text, tone in body:
            y = self.lines(y, 1, marker(tone), text, self.tones.get(tone, 0))
        y += 1 if body else 0
        # The fields: a choice's options, a line to type in; the one in focus marked with ">".
        fields = [f for f in page.fields(a, self.env) if f.shown(a)]
        self.focus = min(self.focus, max(0, len(fields) - 1))
        cursor = None
        for i, field in enumerate(fields):
            mine = i == self.focus
            if isinstance(field, Choice):
                self.put(y, 1, ("> " if mine else "  ") + field.label + ":", curses.A_BOLD if mine else 0)
                y += 1
                for value, words in field.options():
                    picked = value == getattr(a, field.attr)
                    self.put(y, 3, ("(*) " if picked else "( ) ") + words, curses.A_BOLD if picked else 0)
                    y += 1
            else:
                value = getattr(a, field.attr)
                shown = "*" * len(value) if field.secret else value
                label = ("> " if mine else "  ") + "%-9s" % (field.label + ":")
                room = cols - len(label) - 4
                # A long path shows its end, where the typing is.
                shown = shown if len(shown) <= room else "..." + shown[-(room - 3):]
                self.put(y, 1, label, curses.A_BOLD if mine else 0)
                self.put(y, 2 + len(label), shown + " ", curses.A_UNDERLINE)
                if mine:
                    cursor = (y, 2 + len(label) + len(shown))
                y += 1
        # What the answer means, under a line of its own.
        preview = page.preview(a, self.env)
        if preview:
            y += 1
            self.put(y, 1, "What this means:", curses.A_DIM)
            y += 1
            for text, tone in preview:
                y = self.lines(y, 3, marker(tone), text, self.tones.get(tone, 0))
        if self.error:
            self.put(rows - 3, 1, "!!  " + self.error, self.tones["bad"])
        # The keys, at the bottom.
        if isinstance(page, Done):
            enter = "Enter  close"
        elif isinstance(page, Progress) and a.failed:
            enter = "Enter  try again   Ctrl-C  quit"
        elif isinstance(page, Docker) and a.docker is not None and blocking(a.docker):
            enter = "Enter  check again   Ctrl-C  quit"
        else:
            enter = "Enter  next   Ctrl-C  quit"
        keys = ("Esc  back   " if page.can_back(a) and self.at else "") + enter
        if page.keys:
            keys = page.keys + "   " + keys
        self.put(rows - 2, 0, "-" * (cols - 1), curses.A_DIM)
        self.put(rows - 1, 1, keys, curses.A_DIM)
        if cursor:
            try:
                curses.curs_set(1)
                scr.move(*cursor)
            except curses.error:
                pass
        else:
            try:
                curses.curs_set(0)
            except curses.error:
                pass
        scr.refresh()
        self.write_capture()

    def write_capture(self):
        """The screen as drawn, as text, to the capture folder (DMT3_WIZARD_CAPTURE), one file a page."""
        if not self.capture:
            return
        rows, cols = self.scr.getmaxyx()
        lines = []
        for y in range(rows):
            raw = self.scr.instr(y, 0, cols)
            lines.append(raw.decode("utf-8", "replace").rstrip())
        name = "%02d-%s.txt" % (self.at + 1, self.page.name.lower())
        with open(os.path.join(self.capture, name), "w", encoding="utf-8") as f:
            f.write("\n".join(lines).rstrip("\n") + "\n")

    def keyname(self, ch):
        """A key as a name: enter, esc, up, down, tab, backtab, backspace, the letter itself, or None."""
        curses = self.curses
        names = {curses.KEY_UP: "up", curses.KEY_DOWN: "down", curses.KEY_BTAB: "backtab",
                 curses.KEY_BACKSPACE: "backspace", curses.KEY_ENTER: "enter", curses.KEY_RESIZE: "resize"}
        if isinstance(ch, str):
            return {"\n": "enter", "\r": "enter", "\x1b": "esc", "\t": "tab", "\x7f": "backspace", "\x08": "backspace",
                    "\x15": "clear"}.get(ch, ch if ch.isprintable() else None)
        return names.get(ch)

    def run(self):
        """Draw, wait for a key, act, until the last page is left; returns the exit code. A page's slow look-up (and
        the setup itself) runs on a worker thread once the typing stops, so the keys keep working; the screen is drawn
        again as it finishes and, while it runs, a few times a second (the setup's lines as they change)."""
        self.scr.timeout(100)
        self.worker, self.dirty = None, False
        self.draw()
        while True:
            page = self.page
            if self.worker is not None and not self.worker.is_alive():
                # A look-up finished: its answer is on the page now.
                self.worker = None
                self.draw()
                if isinstance(page, Progress) and self.a.done:
                    # The setup went through: on to what to do next, after a moment to see the last line.
                    time.sleep(1.5)
                    self.go(step(self.at, self.ordered, self.a))
                    self.draw()
            if self.worker is None:
                look = page.pending(self.a, self.env)
                if look and (time.monotonic() - self.last_key > IDLE or isinstance(page, Progress)):
                    if isinstance(page, Progress):
                        # The setup marks each line as it goes; the loop below draws it.
                        page.redraw = self.mark_dirty
                    self.worker = threading.Thread(target=self.guarded(look), daemon=True)
                    self.worker.start()
                    continue
            try:
                ch = self.scr.get_wch()
            except self.curses.error:
                # No key this tenth of a second: draw what changed meanwhile.
                if self.dirty:
                    self.dirty = False
                    self.draw()
                continue
            self.last_key = time.monotonic()
            k = self.keyname(ch)
            if k is None:
                continue
            if self.act(k) == "quit":
                return 0
            self.draw()

    def mark_dirty(self):
        """Asked from the worker: draw again on the next tick (curses is drawn from this thread only)."""
        self.dirty = True

    def guarded(self, look):
        """A look-up that cannot end the wizard: what it raises is said on the page, as one line."""
        def runner():
            try:
                look()
            except Exception as e:  # noqa: BLE001  (shown, not raised, on a thread no one waits for)
                self.error = "%s: %s" % (type(e).__name__, str(e).strip().splitlines()[0] if str(e).strip() else "")
                if isinstance(self.page, Progress):
                    self.a.failed = "the step that was running"
            self.dirty = True
        return runner

    def act(self, k):
        """One key on the page; "quit" when the last page is left."""
        a, page = self.a, self.page
        fields = [f for f in page.fields(a, self.env) if f.shown(a)]
        field = fields[self.focus] if fields else None
        self.error = ""
        if k == "resize":
            return None
        if k == "esc":
            if page.can_back(a) and self.at:
                self.go(step(self.at, self.ordered, a, forward=False))
            return None
        if k == "enter":
            if page.again(a):
                # Looked at anew on the next idle moment (as r does on the Docker page).
                return None
            error = page.leave(a, self.env)
            if error:
                self.error = error
                return None
            if isinstance(page, Done):
                return "quit"
            self.go(step(self.at, self.ordered, a))
            return None
        if isinstance(page, Confirm) and k in CHANGE:
            self.go(next(i for i, p in enumerate(self.ordered) if isinstance(p, CHANGE[k])))
            return None
        if isinstance(field, Choice) and k in ("up", "down"):
            options = [value for value, _ in field.options()]
            if options:
                current = getattr(a, field.attr)
                at = options.index(current) if current in options else 0
                setattr(a, field.attr, options[(at + (1 if k == "down" else -1)) % len(options)])
            return None
        if page.key(a, self.env, k):
            return None
        if k in ("tab", "backtab", "up", "down") and fields:
            if k == "tab" and isinstance(field, Text) and field.paths:
                done, matches = complete(getattr(a, field.attr))
                if done != getattr(a, field.attr):
                    setattr(a, field.attr, done)
                    return None
                if len(matches) > 1:
                    self.error = "More than one: " + "  ".join(matches[:6])
                    return None
            # Tab, Up and Down move between the page's boxes.
            self.focus = (self.focus + (-1 if k in ("backtab", "up") else 1)) % len(fields)
            return None
        if isinstance(field, Text):
            value = getattr(a, field.attr)
            if k == "backspace":
                setattr(a, field.attr, value[:-1])
            elif k == "clear":
                setattr(a, field.attr, "")
            elif len(k) == 1:
                setattr(a, field.attr, value + k)
        return None

    def go(self, at):
        """To another page, its first box in focus."""
        self.at, self.focus = at, 0


def can_draw():
    """True when this terminal can draw the pages: curses there, a terminal it knows, and room enough."""
    if os.environ.get("TERM", "dumb") in ("dumb", ""):
        return False
    # Only whether it is there (Windows' Python has none).
    if importlib.util.find_spec("curses") is None:
        return False
    room = os.get_terminal_size(sys.stdout.fileno()) if sys.stdout.isatty() else None
    return bool(room) and room.columns >= MIN_COLUMNS and room.lines >= MIN_LINES


def run(env):
    """The wizard: drawn with curses when the terminal can, as plain prompts otherwise. Returns the exit code."""
    capture = os.environ.get("DMT3_WIZARD_CAPTURE")
    if capture:
        os.makedirs(capture, exist_ok=True)
    if not can_draw():
        return run_plain(env)
    import curses
    # Esc goes back at once, not after curses' own wait for a longer key.
    os.environ.setdefault("ESCDELAY", "25")
    a = Answers()
    try:
        code = curses.wrapper(lambda scr: Screen(scr, env, a, capture).run())
    except KeyboardInterrupt:
        print("Setup stopped.")
        return 1
    if a.done:
        # The page closes with the screen; what to keep is said once more where it stays.
        chosen = a.address or "127.0.0.1"
        print("The site: %s%s" % (site("127.0.0.1"), "" if chosen.startswith("127.") else
                                  " (from other PCs: %s)" % site(chosen)))
        if not a.accounts:
            print("Admin %s, password %s" % (a.admin.strip().upper(), a.made_password or a.password))
    return code
