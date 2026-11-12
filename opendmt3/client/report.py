"""A report zip for an issue: the launcher's log and settings, and the game folder's settings and backup list.

Nothing from the game itself goes in (no archives, no executables), and the Windows user name is replaced
wherever it appears, because paths under C:\\Users\\<name> are in every file collected here. Another
server's sign-in token, the card number and the server's address are taken out of the launcher's settings, and
the address and the card number out of every other file too (the log names the server it plays on).
"""

import getpass
import os
import re
import time
import urllib.parse
import zipfile

from opendmt3 import __version__
from opendmt3.core import game as g
from opendmt3.client import state as st

# The files collected from the game folder, relative to it: the list an older openDMT3 kept of what it changed.
GAME_FILES = (os.path.join(g.BACKUP_DIR, "openDMT3.json"),)
# The files collected from openDMT3's own folder for the game (steps.Own): the game's settings as PLAY made them, the
# list of openDMT3's files the library gives the game, and what each copy was made from.
OWN_FILES = ("setting.ini", "openDMT3-files.txt", "openDMT3-made.json")


def _scrub(text, names, private=()):
    """Replace each personal name (user name, home folder) with a placeholder, then each (pattern, placeholder) of
    private (the server's address, the card number)."""
    for name in names:
        if name:
            text = text.replace(name, "<user>")
    for pattern, placeholder in private:
        text = pattern.sub(placeholder, text)
    return text


def _private(state):
    """Patterns for what identifies the player's server and signs them in, wherever a file has them: the server's
    address as given, its host on its own (as a whole name, so a short host never eats into other words), and the
    card number."""
    out = []
    url = getattr(state, "server_url", None)
    if url:
        out.append((re.compile(re.escape(url)), "<server>"))
        host = urllib.parse.urlsplit(url).hostname
        if host:
            # Not inside a longer name or number: neither "opendmt3" for a host "dmt", nor 110.0.0.5 for 10.0.0.5.
            out.append((re.compile(r"(?<![\w.-])%s(?![\w-])" % re.escape(host)), "<server>"))
    card = (getattr(state, "remote", None) or {}).get("card")
    if card:
        out.append((re.compile(re.escape(card)), "<card>"))
    return out


def _without_secrets(text):
    """The launcher's settings without what signs in: another server's token, the card number, its address."""
    import json
    try:
        data = json.loads(text)
    except ValueError:
        return "(the settings file could not be read)"
    remote = data.get("remote") or {}
    # A card number logs in to the game by itself, and the token to the server's API: neither may leave the PC.
    data["remote"] = {k: v for k, v in remote.items() if k in ("version",)} if remote else None
    data["server_url"] = "<server>" if data.get("server_url") else None
    return json.dumps(data, indent=2, ensure_ascii=False)


def make(state, folder, now=None):
    """Write the report into folder and return its path."""
    home = os.path.expanduser("~")
    # The user name, and the home folder in both slash styles, are what identifies a person in these files.
    names = sorted({getpass.getuser(), os.path.basename(home), home, home.replace("\\", "/")}, key=len, reverse=True)
    private = _private(state)
    stamp = time.strftime("%Y%m%d-%H%M", time.localtime(now))
    path = os.path.join(folder, "openDMT3-report-%s.zip" % stamp)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("about.txt", "openDMT3 %s\nmade %s\n" % (__version__, time.strftime("%Y-%m-%d %H:%M:%S")))
        # The launcher's own files: its settings and its logs (rotated, so at most a few megabytes).
        sources = [st.LauncherState.path()]
        logs = os.path.join(st.config_dir(), "logs")
        if os.path.isdir(logs):
            sources += [os.path.join(logs, n) for n in sorted(os.listdir(logs))]
        for src in sources:
            if os.path.isfile(src):
                with open(src, encoding="utf-8", errors="replace") as f:
                    text = f.read()
                if src == st.LauncherState.path():
                    text = _without_secrets(text)
                z.writestr("launcher/" + os.path.basename(src), _scrub(text, names, private))
        try:
            game = state.game()
        except g.GameError:
            game = None
        if game is not None:
            for rel in GAME_FILES:
                src = game.path(rel)
                if os.path.isfile(src):
                    with open(src, "rb") as f:
                        # setting.ini is in the Korean code page; keep the bytes readable either way.
                        text = f.read().decode("cp949", errors="replace")
                    z.writestr("game/" + rel.replace(os.sep, "/"), _scrub(text, names, private))
        own = state.own()
        for rel in OWN_FILES:
            src = own.path(rel)
            if os.path.isfile(src):
                with open(src, "rb") as f:
                    # setting.ini is in the Korean code page; keep the bytes readable either way.
                    text = f.read().decode("cp949" if rel.endswith(".ini") else "utf-8", errors="replace")
                z.writestr("openDMT3/" + rel, _scrub(text, names, private))
        if os.path.isfile(own.client()):
            digest = g.sha256_file(own.client())
            z.writestr("openDMT3/client.txt", "client copy: %s (%s)\n" % (g.CLIENT_BUILDS.get(digest, "unknown build"),
                                                                        digest))
    return path
