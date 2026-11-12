"""Playing without the launcher's window: a desktop shortcut that plays at once, and playing when Windows starts.

Both start the installed launcher with --play (the console-free copy: it gets the folder ready, starts the game,
and keeps this PC's server until the game closes). They point at Velopack's `current` folder, which stays the same
path through updates. Only an installed launcher on Windows can make them; anywhere else they say why.

The shortcut is a Windows .lnk made by Windows itself (WScript.Shell through PowerShell, no window); starting with
Windows is the user's own Run key, nothing for every user and nothing that needs administrator rights. Removing
openDMT3 takes both away again (client/leaving.py).
"""

import os
import subprocess
import sys

from opendmt3.core import game as g

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "openDMT3"
SHORTCUT_NAME = "TECHNIKA 3 (openDMT3).lnk"


def launcher_exe():
    """The installed launcher's openDMT3.exe (in Velopack's current folder); GameError when not installed."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise g.GameError("only the installed launcher on Windows can make this", "error.shortcut.installed")
    exe = os.path.join(os.path.dirname(sys.executable), "openDMT3.exe")
    if os.path.basename(os.path.dirname(exe)).lower() != "current" or not os.path.isfile(exe):
        raise g.GameError("only the installed launcher on Windows can make this", "error.shortcut.installed")
    return exe


def desktop():
    """The desktop folder: Windows' own answer (it follows OneDrive and a desktop moved to another drive), else
    the Desktop folder in the user's home."""
    return desktops()[0]


def desktops():
    """Every place the desktop may be, Windows' own answer first, without duplicates."""
    places = []
    if sys.platform == "win32":
        from opendmt3.client import find
        try:
            places.append(find.known_folder(find.DESKTOP))
        except (AttributeError, OSError, ValueError):
            # An older Windows or Wine without the call: the home folder's Desktop below still answers.
            pass
    places.append(os.path.join(os.environ.get("USERPROFILE") or os.path.expanduser("~"), "Desktop"))
    seen, out = set(), []
    for place in places:
        key = os.path.normcase(os.path.abspath(place)) if place else None
        if key and key not in seen:
            seen.add(key)
            out.append(place)
    return out


def remove_shortcut(folders=None):
    """Take the shortcut make_shortcut() made off the desktop (each place it may be); returns the paths removed."""
    removed = []
    for folder in folders or desktops():
        path = os.path.join(folder, SHORTCUT_NAME)
        if os.path.isfile(path):
            os.remove(path)
            removed.append(path)
    return removed


def make_shortcut(exe=None, folder=None, run=subprocess.run):
    """A desktop shortcut that plays at once; returns its path."""
    exe = exe or launcher_exe()
    path = os.path.join(folder or desktop(), SHORTCUT_NAME)
    # The paths reach PowerShell through the environment, never inside the script: a folder name can hold any
    # quote PowerShell ends a string at (', and the curly ones too), and none of them can end anything there.
    script = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:OPENDMT3_SHORTCUT); "
              "$s.TargetPath = $env:OPENDMT3_EXE; $s.Arguments = '--play'; $s.WorkingDirectory = $env:OPENDMT3_DIR; "
              "$s.IconLocation = $env:OPENDMT3_EXE + ',0'; $s.Description = 'TECHNIKA 3 with openDMT3'; $s.Save()")
    env = dict(os.environ, OPENDMT3_SHORTCUT=path, OPENDMT3_EXE=exe, OPENDMT3_DIR=os.path.dirname(exe))
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    done = run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
               capture_output=True, text=True, timeout=30, creationflags=flags, env=env)
    if done.returncode != 0:
        raise g.GameError("Windows did not make the shortcut: %s" % (done.stderr or "").strip()[:200],
                          "error.shortcut.failed", reason=(done.stderr or "").strip()[:200])
    return path


def _winreg():
    import winreg
    return winreg


def autostart(on=None, exe=None, registry=None):
    """Whether the game starts with Windows; with on=True/False, set it first. Returns the state."""
    reg = registry or _winreg()
    if on is not None:
        key = reg.CreateKey(reg.HKEY_CURRENT_USER, RUN_KEY)
        try:
            if on:
                reg.SetValueEx(key, RUN_NAME, 0, reg.REG_SZ, '"%s" --play' % (exe or launcher_exe()))
            else:
                try:
                    reg.DeleteValue(key, RUN_NAME)
                except FileNotFoundError:
                    pass
        finally:
            reg.CloseKey(key)
    try:
        key = reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY)
    except FileNotFoundError:
        return False
    try:
        reg.QueryValueEx(key, RUN_NAME)
        return True
    except FileNotFoundError:
        return False
    finally:
        reg.CloseKey(key)
