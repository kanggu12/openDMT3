"""The launcher's command line: each page's action as a flag, through the same checks as the window
(client/actions.py). main.py starts the process and hands the jobs here; what is left for it then is the window.

  openDMT3.exe                         the launcher window (the first-start guide the first time)
  openDMT3.exe --play                  get the game ready and start it, no window
  openDMT3.exe --check                 print the ready check (exit 0 when PLAY can go)
  openDMT3.exe --put-back [--yes]      put back every game file openDMT3 changed in the folder in use
                                       (--restore is the same)
  openDMT3.exe --update [--yes]        look for a newer launcher and install it (it restarts)
  openDMT3.exe --repair                put back the program's files that are missing or changed, from the
                                       package the installer left on this PC
  openDMT3.exe --uninstall [--delete-data] [--yes]
                                       uninstall openDMT3 from this PC; the game files an older openDMT3 changed
                                       go back first (--delete-data: its settings, players and records too)
  openDMT3.exe --status                print the folder, how this PC plays, the language, the sound (its device,
                                       mixer, low latency and the steps the last game's sound went in) and the ready
                                       check
  openDMT3.exe --find                  list the client data found in the usual places, in folders and in
                                       archives, each with what it is, as the first-start guide's cards say it
  openDMT3.exe --inspect <path>        what a path is (client data in a folder or in an archive, part of it, or
                                       nothing of the game's), as its card says it; exit 0 when it can be used
  openDMT3.exe --unpack <archive> [--to FOLDER] [--yes]
                                       unpack the client data from an archive (beside it unless --to), with its
                                       progress; the password from standard input when it has one
  openDMT3.exe --sound-devices         list Windows' sound output devices, for --set sound_device=GUID
  openDMT3.exe --folder <path>         use the client data in this folder (or up to four levels below it); an
                                       archive is unpacked first (beside it unless --to)
  openDMT3.exe --set name=value ...    change a setting (the names are in core/cabinet/values.py; unlock=on|off too)
                                       the SCREEN page's picture: upscale=off|smooth|fsr1|nis|anime4k,
                                       sharpness=0..100,
                                       antialiasing=off|fxaa|smaa-low|smaa-medium|smaa-high|smaa-ultra,
                                       frame_pacing=music|even|game, show_fps=on|off,
                                       fps_position=top_left|top_right|bottom_left|bottom_right,
                                       picture_shape=keep|fill, render_size=game|display (the game
                                       drawn at its own 1280x768 or at the screen's size),
                                       pass_times=on|off (the picture's GPU time by pass, into the log
                                       when the game closes), motion_clarity=off|crt|bfi,
                                       flip_model=on|off; the SOUND page's low_latency=on|off
                                       (Windows' sound engine at the shortest period the device offers
                                       while the game runs),
                                       sound_path=directsound|openal|openal-exclusive (its Mixer) and
                                       audio_offset=0..500 (ms a song's notes are held behind its music)
  openDMT3.exe --mode this_pc|server|offline   where logins and records are kept
  openDMT3.exe --server URL            connect to another server and play on it from now on
  openDMT3.exe --sign-in ID            sign in to that server (the password from standard input, or asked for)
  openDMT3.exe --sign-out              sign out of that server (it ends the sign-in when it answers)
  openDMT3.exe --player ID|guest       who plays on this PC (whose card goes in at PLAY)
  openDMT3.exe --add-player ID [--dj NAME]     make a player on this PC (the password as for --sign-in)
  openDMT3.exe --delete-player ID [--yes]      delete a player on this PC, and their cleared stages
                                       (--remove-player is the same)
  openDMT3.exe --language en|ko|system the launcher's language (system: the one Windows is shown in)
  openDMT3.exe --guide                 open the first-start guide again at the next start of the window
  openDMT3.exe --report [FOLDER]       save a report for an issue (on the desktop when no folder is given)
  openDMT3.exe --save-song-list [FILE] save the song list for a server (openDMT3-song-list.zip on the desktop
                                       when no file is given; a folder: the file in it)
  openDMT3.exe --send-song-list        send the song list to the server this launcher is signed in to (as its
                                       admin)
  openDMT3.exe --open-log              show the launcher's log folder

The console copy openDMT3-cmd.exe takes the same arguments and prints to the terminal. Several in one command run in
the order above (--server, then --sign-in, then --play). While the launcher's window is open, the ones that change
what it keeps (--folder, --set, --lan, --mode, --server, --sign-in, --sign-out, --player, --add-player,
--delete-player, --language, --guide, --uninstall) are refused: the window would write its own copy over them. An
argument the launcher does not know is said.
"""

import argparse
import logging
import os
import sys

from opendmt3 import __version__
from opendmt3.core import game as g
from opendmt3.core.cabinet import values as choices
from opendmt3.client import actions
from opendmt3.client import state as st

log = logging.getLogger("opendmt3.launcher")


def window_open():
    """True while a launcher window is open (the mutex _single_instance makes); False off Windows."""
    from opendmt3.client import installer
    return installer.launcher_open()


def say(text, error=False):
    """Print for the console copy; the window copy has no console, so errors also go to the log."""
    stream = sys.stderr if error else sys.stdout
    if stream is not None:
        # Flushed at once: --update hands the process to Velopack, which ends it without Python's own exit, so
        # anything still buffered (output sent to a file) would be lost.
        print(text, file=stream, flush=True)
    (log.error if error else log.info)(text)


def _serve(state):
    """--serve: this PC's server (game and site), as the launcher runs it for PLAY or for the other PCs, until Ctrl+C."""
    import time
    from opendmt3.client import hosting
    host = hosting.BuiltinServer(lan=state.lan)
    try:
        host.start()
    except Exception as e:  # noqa: BLE001  (said, never swallowed)
        say(str(e), error=True)
        return 2
    say("Game server on %s:%d, site on %s" % (host.listen_address, host.port, host.web_url or "(no site)"))
    for address in host.addresses():
        say("  other PCs on this network: %s" % address)
    say("Ctrl+C stops it.")
    try:
        while host.running:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    host.stop()
    return 0


def _records_text(state):
    """--records --text: the Records page as text, from the same place (this PC's database or the other server)."""
    from opendmt3.client import hosting
    try:
        dj = actions.records(state, hosting.BuiltinServer(game=False))
    except Exception as e:  # noqa: BLE001  (said, never swallowed)
        say(str(e), error=True)
        return 2
    s, done = dj["summary"], dj["activity"]
    say("%s: %d stages cleared, %d songs, %d charts, %d sessions, %d min played"
         % (dj["dj_name"], s["plays"], s["songs"], s["charts"], done["sessions"], done["seconds"] // 60))
    say("weeks (oldest first): " + " ".join(str(wk["plays"]) for wk in done["weeks"]))
    for title, items in (("recent plays", dj["recent"]), ("best scores", dj["bests"][:10])):
        say(title + ":")
        for item in items:
            level = " Lv %d" % item["level"] if item.get("level") else ""
            say("  %9s  %s · pattern %d%s  %s" % ("{:,}".format(item["score"]), item["mode_name"], item["pattern"],
                                                   level, item["title"]))
    return 0


def _records(state, no_browser):
    """--records: the same link as PLAY's [My records], from a site of its own that runs until Ctrl+C.

    Only the site runs here (no game server), so it works beside an open launcher that holds the game's port.
    """
    import time
    from opendmt3.client import hosting
    host = hosting.BuiltinServer(game=False)
    try:
        link = actions.records_link(state, host)
    except Exception as e:  # noqa: BLE001  (said, logged, never swallowed)
        log.exception("--records failed")
        say(str(e), error=True)
        host.stop()
        return 2
    say("Records page: %s" % host.web_url)
    if no_browser:
        say("Sign-in link (works once, for a minute): %s" % link)
    else:
        actions.open_link(link)
        say("Opened in the browser. Ctrl+C stops the site.")
    try:
        while host.running:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    host.stop()
    return 0


def _repair():
    """--repair: Help's Repair (client/repair.py), its outcome in a line or two."""
    from opendmt3.core import errors
    from opendmt3.client import repair
    try:
        result = repair.run()
    except repair.RepairError as e:
        say(errors.say(e), error=True)
        return 2
    for name in result.missing + result.changed:
        say("  %s %s%s" % ("missing" if name in result.missing else "changed", name,
                            " (not put back)" if name in result.failed else ""))
    if result.failed:
        say("Files put back: %d; not put back: %d. Run openDMT3-win-Setup.exe again and choose Repair."
             % (result.restored, len(result.failed)), error=True)
        return 2
    if result.restored:
        say("Files put back: %d.%s" % (result.restored, " Some are the launcher's own: open it again."
                                         if result.needs_restart else ""))
        return 0
    say("Nothing to repair: all %d files of the program are as installed." % result.checked)
    return 0


def _update(yes, state):
    """--update: the same check as the Launcher page, then the same update (the launcher restarts into it)."""
    from opendmt3 import __version__
    from opendmt3.client import updates
    result = updates.check(updates.source_for(state))
    if result.kind != "available":
        said = {"not_installed": "Updates work in the launcher installed by openDMT3-win-Setup.exe.",
                "no_source": "No update address is set for this build.",
                "uptodate": "This is the newest version (%s)." % (updates.current_version() or __version__),
                "failed": "Could not check for updates: %s" % result.error}
        say(said.get(result.kind, result.kind), error=result.kind == "failed")
        return 0 if result.kind == "uptodate" else 2
    say("openDMT3 %s is available (this is %s)." % (result.version, updates.current_version() or __version__))
    if not yes:
        answer = input("Update now? The launcher closes and starts again. [y/N] ") if sys.stdin else "n"
        if answer.strip().lower() not in ("y", "yes"):
            say("Nothing changed.")
            return 1
    try:
        # Fetches and checks the update, then hands it to Velopack, which waits for this process to end, puts the
        # update in and starts the new launcher. What the window says in its dialog is a line here.
        updates.apply(result, tell=lambda what: what == "whole" and say(
            "The whole update is downloading instead of only what changed."))
    except Exception as e:  # noqa: BLE001  (shown and logged, never swallowed)
        log.exception("--update failed")
        say("The update failed: %s" % e, error=True)
        return 2
    say("Updating: the launcher starts again in a few seconds.")
    return 0


def _busy_for_uninstall():
    """A game running (it plays from openDMT3's folder, which uninstalling removes) or the launcher's window open
    (Velopack would close it mid-work): said, and True. Asked before the question and again after it: either may
    start while it waits."""
    from opendmt3.client import installer
    from opendmt3.client import playing
    if playing.running():
        say("Close the game first.", error=True)
        return True
    if installer.launcher_open():
        say("The launcher's window is open: uninstall there (Help, Uninstall), or close the window first.",
             error=True)
        return True
    return False


def _uninstall(yes, everything, state):
    """--uninstall: Help's Uninstall, in a terminal. Velopack's uninstall closes this program before it begins, so
    everything is said first."""
    from opendmt3.client import leaving
    updater = leaving.uninstaller()
    if updater is None:
        say("Uninstalling works in the launcher installed by openDMT3-win-Setup.exe. This launcher runs from a "
             "folder: delete the folder to remove it.", error=True)
        return 2
    if _busy_for_uninstall():
        return 2
    # As Help's Uninstall asks: the game's files are named only when an older openDMT3 changed some there.
    what = "Uninstall openDMT3 from this PC?%s%s" % (
        " The files an older openDMT3 changed in the client data go back to how they were."
        if leaving.changed_before(state) else "",
        " Its settings, players and records are deleted." if everything else "")
    if not yes:
        answer = input(what + " [y/N] ") if sys.stdin else "n"
        if answer.strip().lower() not in ("y", "yes"):
            say("Nothing changed.")
            return 1
        if _busy_for_uninstall():
            return 2
    try:
        outcome = leaving.before_uninstall(state)
    except Exception as e:  # noqa: BLE001  (said and logged, never swallowed: nothing is removed then)
        log.exception("--uninstall failed")
        say("Uninstall failed: %s. openDMT3 is still on this PC." % e, error=True)
        return 2
    if outcome.put_back:
        say("Game files put back: %d." % len(outcome.put_back))
    if outcome.stays:
        say("Originals kept in the client data's backup folder, which openDMT3 did not copy there itself: %d."
             % len(outcome.stays))
    say("Uninstalling openDMT3: the program is gone in a few seconds%s."
         % (", with its settings, players and records" if everything else ""))
    leaving.start_uninstall(updater, everything)
    return 0


def _save_song_list(state, path):
    """--save-song-list: the Game page's Save the song list..., the file where it is asked for (the desktop when no
    path is given). True when it failed (said)."""
    from opendmt3.client import leaving, shortcuts
    from opendmt3.server.services import songlist
    target = path or os.path.join(shortcuts.desktop(), songlist.NAME)
    try:
        manifest, size = actions.save_song_list(state, target)
    except Exception as e:  # noqa: BLE001  (a folder, a file, a damaged game file: said, never swallowed)
        log.exception("--save-song-list failed")
        say(str(e), error=True)
        return True
    if os.path.isdir(target):
        target = os.path.join(target, songlist.NAME)
    say("Saved the song list: %s (%d songs, %s)." % (target, manifest["songs"], leaving.megabytes(size)))
    return False


def _send_song_list(state):
    """--send-song-list: the Game page's Send the song list to this server, with the launcher's sign-in. True when it
    failed (said)."""
    try:
        answer = actions.send_song_list(state)
    except Exception as e:  # noqa: BLE001  (not signed in, not an admin, refused: said, never swallowed)
        log.exception("--send-song-list failed")
        say(str(e), error=True)
        return True
    for line in answer.get("lines") or []:
        say("  " + str(line))
    say("Sent the song list to %s." % state.server_url)
    return False
class Said(Exception):
    """A job that stopped after saying why in its own lines: nothing more is said for it."""


# A card's state in a word, for the command line's lists.
STATE_WORDS = {"ready": "ready", "unpack": "unpack", "not_here": "no", "not_yet": "not yet", "checking": "checking"}


def _unpack(archive, to, yes):
    """--unpack (and --folder with an archive): the same checks and work as the card's Unpack..., in a terminal.
    Returns the new game folder's path, or None when nothing was made (said)."""
    from opendmt3.client import i18n, intake, unpack, unpacking
    w = i18n.Words("en")
    archive = os.path.abspath(archive)
    found = intake.inspect(archive)
    if found.state != intake.UNPACK:
        say("%s: %s" % (archive, found.sentence(w)), error=True)
        return None
    secret = None
    if found.password:
        secret = password("Password for %s: " % os.path.basename(archive))
        if not intake.password_opens(archive, secret):
            say(w.error(intake.said("error.source.wrong_password")), error=True)
            return None
        found = intake.inspect_archive(archive, secret)
        if found.state != intake.UNPACK:
            say("%s: %s" % (archive, found.sentence(w)), error=True)
            return None
    parent = os.path.abspath(to) if to else unpack.default_parent(archive)
    if not unpack.writable(parent):
        say(w("unpack.not_writable"), error=True)
        return None
    free = unpack.room(parent)
    space = w("unpack.space", needed=intake.size_words(found.needed or 0),
              free=intake.size_words(free) if free is not None else "?")
    if free is not None and found.needed and free < found.needed:
        say(w("intake.line.no_space", needed=intake.size_words(found.needed), free=intake.size_words(free)),
            error=True)
        return None
    target = unpack.target(parent, archive)
    if not yes:
        answer = input("Unpack the client data into %s? %s [y/N] " % (target, space)) if sys.stdin else "n"
        if answer.strip().lower() not in ("y", "yes"):
            say("Nothing changed.")
            return None
    said = {"at": -1.0}

    def progress(fraction, left):
        # A line at every tenth, and the last one: a terminal or a log keeps them all.
        step = int(fraction * 10)
        if step > said["at"] or fraction >= 1.0:
            said["at"] = step
            total = found.size or found.needed or 0
            done = intake.size_words(int(total * fraction)) if total else "%d%%" % int(fraction * 100)
            more = ", %s left" % unpacking.left_words(w, left) if left else ""
            say("  %3d%%  %s of %s%s" % (int(fraction * 100), done, intake.size_words(total) if total else "", more))

    try:
        made = unpack.Unpacking(archive, parent, secret, progress).run()
    except KeyboardInterrupt:
        say("Stopped. What was unpacked is removed.", error=True)
        return None
    except Exception as e:  # noqa: BLE001  (said in the launcher's words, never swallowed)
        log.exception("--unpack failed")
        say(w.error(e), error=True)
        return None
    say("Unpacked: %s" % made)
    return made


def password(prompt):
    """A password from standard input when it is not a terminal (a script), else asked without showing it."""
    if sys.stdin is None:
        raise g.GameError("no password: give it on standard input", "error.cli.password")
    if sys.stdin.isatty():
        import getpass
        return getpass.getpass(prompt)
    return sys.stdin.readline().rstrip("\r\n")


def writes(args):
    """Whether the command line changes what the launcher keeps (refused while its window is open)."""
    return any((args.folder, args.set, args.lan, args.mode, args.server, args.sign_in, args.sign_out, args.player,
                args.add_player, args.remove_player, args.language, args.guide, args.uninstall))


def _say_checks(checks, error=False):
    """The ready check's lines, each by the name the window gives it (never the code's own key): ok, todo (it stops
    PLAY until it is fixed), or play (PLAY makes it ready by itself)."""
    from opendmt3.client import i18n
    w = i18n.Words("en")
    for c in checks:
        mark = "ok  " if c.ok else "play" if c.key.startswith("step:") else "todo"
        say("  [%s] %s: %s" % (mark, w("check." + c.key), c.detail), error=error)


def _status(state):
    """--status: what the window's pages show at a glance, then the ready check; True when PLAY can go."""
    from opendmt3 import __version__
    from opendmt3.client import updates
    say("openDMT3 %s" % (updates.current_version() or __version__))
    say("client data: %s" % (state.game_folder or "(none chosen)"))
    if state.mode == "this_pc":
        names = []
        try:
            from opendmt3.client import hosting
            names = [r["login_id"] for r in hosting.BuiltinServer(game=False).player_rows() if not r["disabled"]]
        except Exception as e:  # noqa: BLE001  (a database that cannot be read is said, the rest goes on)
            say("players on this PC: %s" % e, error=True)
        say("plays: on this PC (players: %s; the card at PLAY: %s)"
             % (", ".join(names) or "none", state.player or "a guest"))
    elif state.mode == "server":
        remote_state = state.remote or {}
        signed = ("signed in as %s (%s)" % (remote_state.get("dj_name"), remote_state.get("login_id"))
                  if remote_state.get("card") else "not signed in")
        say("plays: on another server, %s (%s)" % (state.server_url or "(no address)", signed))
    else:
        say("plays: offline (no logins, no records)")
    say("language: %s%s" % (state.language, "" if state.picked_language else " (the one Windows is shown in)"))
    # The Sound page's output: the device, the Mixer, Low latency, and what the page says of the last game with them.
    from opendmt3.client import i18n
    words, session = i18n.Words("en"), state.last_session or {}
    device, mixer = state.values["sound_device"], state.values["sound_path"]
    fell_back = actions.sound_mixer_line(session.get("sound_mixer"), mixer, device)
    say("sound: %s, mixer %s.%s" % ("Windows' default output" if device == choices.DEFAULT_DEVICE else device, mixer,
                                    " " + words(fell_back) if fell_back else ""))
    # Low latency, as the page shows it, with its line about the last game while it is on.
    last = actions.sound_engine_line(session.get("sound_engine"), device)
    said = " " + words(last[0], **last[1]) if last and state.values["low_latency"] else ""
    say("sound: low latency %s.%s" % ("on" if state.values["low_latency"] else "off", said))
    checks = actions.readiness(state)
    _say_checks(checks)
    return actions.can_play(checks)


def _settings(args, state):
    """The settings jobs, in the order the help lists them; True when one of them changed the state. Raises what it
    says (GameError, ChoiceError, RemoteError, HostingError, AccountError)."""
    from opendmt3.client import hosting
    changed = False
    if args.folder:
        from opendmt3.client import i18n, intake
        item = intake.inspect(os.path.abspath(args.folder))
        if item.state == intake.UNPACK:
            # An archive: unpacked first (its own lines say how it went), then its game folder is the one in use.
            made = _unpack(args.folder, args.to, args.yes)
            if made is None:
                raise Said()
            item = intake.inspect(made)
        if item.state != intake.READY or item.kind != intake.FOLDER:
            # Not a game folder that plays: what it is, and the one thing to do.
            say("%s: %s" % (item.path, item.sentence(i18n.Words("en"))), error=True)
            raise Said()
        state.game_folder = item.root
        say("The client data: %s" % item.root)
        changed = True
    for item in args.set:
        name, _, value = item.partition("=")
        name, value = name.strip(), value.strip()
        if name == "unlock":
            # The Game page's Show hidden patterns: kept beside the screen and sound values.
            if value not in ("on", "off"):
                raise choices.ChoiceError("unlock is on or off, not %r" % value)
            state.unlock = value == "on"
        else:
            state.set_value(name, value)
        changed = True
    if args.lan:
        state.lan = args.lan == "on"
        changed = True
    if args.language:
        state.language = None if args.language == "system" else args.language
        changed = True
    if args.guide:
        state.guide_done = False
        say("The first-start guide opens at the next start of the window.")
        changed = True
    if args.mode:
        state.mode = args.mode
        changed = True
    if args.server:
        base, found = actions.server_status(args.server)
        actions.use_server(state, base, found)
        state.mode = "server"
        say("Connected to %s: openDMT3 %s, the game at %s." % (base, found.get("version", "?"), found["game"]))
        changed = True
    if args.sign_in:
        from opendmt3.client import remote
        if not state.server_url:
            raise g.GameError("connect to a server first (--server URL)", "error.cli.no_server")
        me = remote.sign_in(state.server_url, args.sign_in, password("Password for %s: " % args.sign_in))
        actions.signed_in(state, me)
        say("Signed in as %s (%s)." % (me["dj_name"], me["login_id"]))
        changed = True
    if args.sign_out:
        actions.sign_out(state)
        say("Signed out.")
        changed = True
    if args.add_player or args.remove_player or args.player:
        store = hosting.BuiltinServer(game=False).accounts()
        try:
            if args.add_player:
                login_id = args.add_player.upper()
                row = store.create(login_id, password("Password for %s: " % login_id), args.dj or login_id,
                                   who="launcher")
                say("Added %s (%s)." % (row["dj_name"], row["login_id"]))
            if args.remove_player:
                login_id = args.remove_player.upper()
                row = store.by_login(login_id)
                if row is None:
                    raise g.GameError("%s is not a player on this PC" % login_id, "error.records.no_player",
                                      login_id=login_id)
                if not args.yes:
                    answer = input("Delete %s (%s) and their cleared stages? This cannot be undone. [y/N] "
                                   % (row["dj_name"], login_id)) if sys.stdin else "n"
                    if answer.strip().lower() not in ("y", "yes"):
                        say("Nothing changed.")
                        return changed
                store.delete(login_id, who="launcher")
                if state.player == login_id:
                    state.player = None
                say("Deleted %s (%s)." % (row["dj_name"], login_id))
                changed = True
            if args.player:
                if args.player.lower() == "guest":
                    state.player = None
                else:
                    login_id = args.player.upper()
                    if store.by_login(login_id) is None:
                        raise g.GameError("%s is not a player on this PC" % login_id, "error.records.no_player",
                                          login_id=login_id)
                    state.player = login_id
                say("At PLAY the card in the reader is %s." % (state.player or "none: a guest"))
                changed = True
        finally:
            store.db.close()
    return changed


class _Help(argparse.HelpFormatter):
    """argparse's help, its lines never broken inside a value (smaa-medium, bottom_right): only at spaces."""

    def _split_lines(self, text, width):
        # argparse's own wrap breaks at hyphens too; values must stay whole to be read and typed.
        import textwrap
        return textwrap.wrap(" ".join(text.split()), width, break_on_hyphens=False)


def parse(argv):
    p = argparse.ArgumentParser(prog="openDMT3", description="The openDMT3 launcher for TECHNIKA 3.",
                                formatter_class=_Help)
    p.add_argument("--version", action="version", version="openDMT3 " + __version__)
    job = p.add_mutually_exclusive_group()
    job.add_argument("--play", action="store_true", help="get the game ready and start it")
    job.add_argument("--check", action="store_true", help="print the ready check")
    job.add_argument("--put-back", "--restore", dest="restore", action="store_true",
                     help="put back every game file openDMT3 changed in the folder in use")
    job.add_argument("--update", action="store_true", help="look for a newer launcher and install it")
    job.add_argument("--repair", action="store_true",
                     help="put back the program's files that are missing or changed, from the installed package")
    job.add_argument("--uninstall", action="store_true",
                     help="uninstall openDMT3 from this PC (the game files an older openDMT3 changed go back first)")
    p.add_argument("--delete-data", action="store_true",
                   help="with --uninstall: delete the settings, players and records on this PC too")
    job.add_argument("--records", action="store_true",
                     help="open the chosen player's records on this PC's site (it runs until Ctrl+C)")
    p.add_argument("--no-browser", action="store_true", help="with --records: print the link instead of opening it")
    job.add_argument("--serve", action="store_true",
                     help="run this PC's server (game and site) until Ctrl+C, open to the other PCs on this network "
                          "with --lan on")
    p.add_argument("--lan", choices=("on", "off"),
                   help="open this PC's server to the other PCs on this network, or not")
    job.add_argument("--shortcut", action="store_true", help="make the desktop shortcut that plays at once")
    p.add_argument("--autostart", choices=("on", "off"), help="play when Windows starts, or not")
    p.add_argument("--text", action="store_true",
                   help="with --records: print the RECORDS page (numbers, recent plays, best scores) instead")
    p.add_argument("--yes", action="store_true",
                   help="do not ask before --put-back, --unpack, --update, --uninstall or --delete-player")
    p.add_argument("--status", action="store_true",
                   help="print the folder, how this PC plays, the language, the sound and the ready check (exit 0: "
                        "PLAY can go)")
    p.add_argument("--find", action="store_true",
                   help="list the client data found in the usual places (Desktop, Downloads, Documents, each drive's "
                        "top), in folders and in archives, each with what it is")
    p.add_argument("--inspect", metavar="PATH", help="say what a path is, as its card says it (exit 0: it can be used)")
    p.add_argument("--unpack", metavar="ARCHIVE", help="unpack the client data from an archive (beside it unless --to)")
    p.add_argument("--to", metavar="FOLDER", help="with --unpack or --folder: the folder to unpack into")
    p.add_argument("--sound-devices", action="store_true",
                   help="list Windows' sound output devices (their GUIDs for --set sound_device=)")
    p.add_argument("--folder", metavar="PATH",
                   help="use the client data in this folder (or a folder above it); an archive is unpacked first")
    p.add_argument("--set", metavar="NAME=VALUE", action="append", default=[],
                   help="change a setting: " + ", ".join(sorted(choices.DEFAULTS)) + ", unlock"
                        # The picture choices' values, from the same lists the Screen page offers, so --help never
                        # lags behind them.
                        + "; upscale takes " + "|".join(choices.UPSCALES)
                        + ", sharpness %d to %d" % choices.SHARPNESS_RANGE
                        + ", antialiasing " + "|".join(choices.ANTIALIASINGS)
                        # The frame rate chip's corners, as the Screen page offers them.
                        + ", fps_position " + "|".join(choices.FPS_POSITIONS)
                        # The picture's shape: the game's own kept (the default) or the window filled.
                        + ", picture_shape " + "|".join(choices.PICTURE_SHAPES)
                        # The size the game draws at: its own 1280x768 (the default) or the screen's.
                        + ", render_size " + "|".join(choices.RENDER_SIZES)
                        # The Sound page's Mixer, by the layer's names.
                        + ", sound_path " + "|".join(choices.SOUND_PATHS)
                        # Motion clarity's names, as the Screen page offers them on a screen at a multiple of 60 Hz.
                        + ", motion_clarity " + "|".join(choices.MOTION_CLARITIES)
                        # The Sound page's audio offset, in its range.
                        + ", audio_offset %d to %d ms" % choices.AUDIO_OFFSET_RANGE)
    p.add_argument("--mode", choices=st.MODES, help="where logins and records are kept: this_pc, server or offline")
    p.add_argument("--server", metavar="URL", help="connect to another server and play on it from now on")
    p.add_argument("--sign-in", metavar="ID", help="sign in to that server (the password from standard input)")
    p.add_argument("--sign-out", action="store_true",
                   help="sign out of that server: it ends the sign-in when it answers, and the launcher forgets it")
    p.add_argument("--player", metavar="ID", help="who plays on this PC: a player's ID, or guest")
    p.add_argument("--add-player", metavar="ID", help="make a player on this PC (the password from standard input)")
    p.add_argument("--dj", metavar="NAME", help="with --add-player: the DJ name (the ID when not given)")
    # Delete, as the site and the Online page say it; --remove-player, its name before, still works.
    p.add_argument("--delete-player", "--remove-player", dest="remove_player", metavar="ID",
                   help="delete a player on this PC, and their cleared stages")
    p.add_argument("--language", choices=st.LANGUAGES + ("system",),
                   help="the launcher's language (system: the one Windows is shown in)")
    p.add_argument("--guide", action="store_true", help="open the first-start guide again at the next start")
    p.add_argument("--report", nargs="?", const="", metavar="FOLDER",
                   help="save a report for an issue (on the desktop when no folder is given)")
    p.add_argument("--save-song-list", nargs="?", const="", metavar="FILE",
                   help="save the song list (with its jackets and the DJ cards) for a server: openDMT3-song-list.zip on "
                        "the desktop when no file is given, in the folder when a folder is given")
    p.add_argument("--send-song-list", action="store_true",
                   help="send the song list to the server this launcher is signed in to, as its admin")
    p.add_argument("--open-log", action="store_true", help="show the launcher's log folder")
    # Velopack passes its own --veloapp-* arguments (each with its value); they are handled before this parser runs
    # and let through here. Anything else unknown is a mistake, said as argparse says it (exit code 2).
    args, unknown = p.parse_known_args(argv)
    rest, after_velopack = [], False
    for item in unknown:
        if item.startswith("--veloapp-"):
            after_velopack = True
        elif after_velopack and not item.startswith("-"):
            # The value of the --veloapp-* argument before it.
            after_velopack = False
        else:
            rest.append(item)
            after_velopack = False
    if rest:
        p.error("unrecognized arguments: %s" % " ".join(rest))
    if args.delete_data and not args.uninstall:
        p.error("--delete-data goes with --uninstall")
    if args.dj and not args.add_player:
        p.error("--dj goes with --add-player")
    if args.to and not (args.unpack or args.folder):
        p.error("--to goes with --unpack or --folder")
    return args


def has_jobs(args):
    """Whether the command line asks for anything besides the window (then no window opens)."""
    return (args.play or args.check or args.restore or args.update or args.repair or args.uninstall or args.records
            or args.serve
            or args.shortcut or args.autostart or args.status or args.find or args.inspect or args.unpack
            or args.sound_devices
            or args.report is not None or args.save_song_list is not None or args.send_song_list
            or args.open_log or writes(args))


def run_jobs(args, state, play_failed):
    """Do what the command line asks, in the order main.py's description gives; returns the exit code, or None when
    nothing asked for one (then the window opens). play_failed(state, key, blocked=(), error=None) tells a failed
    --play in the launcher's own window when there is no console (main.py)."""
    if args.find:
        # The guide's search (DISC CHECK): every game folder and archive found, each with what its card says.
        from opendmt3.client import find, i18n, intake
        w = i18n.Words("en")
        # Found, not picked: each archive said from its listing alone, as the found list says it.
        found = [intake.inspect(path, picked=False) for path in find.paths()]
        for item in sorted(found, key=lambda f: {intake.READY: 0, intake.UNPACK: 1}.get(f.state, 2)):
            say("  %-9s %s  %s" % (STATE_WORDS[item.state], item.path, item.sentence(w)))
        if not found:
            say("No client data in the usual places: give its folder or archive with --folder PATH.")
    if args.inspect:
        from opendmt3.client import i18n, intake
        item = intake.inspect(os.path.abspath(args.inspect))
        say("%s  %s" % (item.path, item.sentence(i18n.Words("en"))))
        # Exit 0 when it can be used (as it is, or once unpacked), 1 when it does not work here.
        return 0 if item.state in (intake.READY, intake.UNPACK) else 1
    if args.unpack:
        made = _unpack(args.unpack, args.to, args.yes)
        if made is None:
            return 2
    if args.sound_devices:
        # The Sound page's list: Windows' default output first, then each device by its GUID.
        from opendmt3.client import sound_devices
        chosen = state.values["sound_device"]
        devices = sound_devices.listed()
        say("  %s default  Windows' default output" % ("*" if chosen == "default" else " "))
        for guid, name in devices:
            say("  %s %s  %s" % ("*" if guid == chosen else " ", guid, name))
        if sound_devices.chosen_is_gone(chosen, devices):
            say("The chosen device %s is not connected: the game plays on Windows' default output." % chosen)
    if writes(args) and window_open():
        say("The launcher's window is open: change this there, or close the window first.", error=True)
        return 2
    try:
        if _settings(args, state):
            state.save()
    except Said:
        return 2
    except Exception as e:  # noqa: BLE001  (a folder, a value, a server, a sign-in, a player: said, never swallowed)
        log.exception("a setting from the command line failed")
        say(str(e), error=True)
        return 2
    if args.status and not _status(state):
        return 1
    if args.report is not None:
        from opendmt3.client import report, shortcuts
        target = args.report or shortcuts.desktop()
        if not os.path.isdir(target):
            target = os.path.expanduser("~")
        try:
            say("Saved %s" % report.make(state, target))
        except OSError as e:
            say(str(e), error=True)
            return 2
    if args.save_song_list is not None and _save_song_list(state, args.save_song_list):
        return 2
    if args.send_song_list and _send_song_list(state):
        return 2
    if args.open_log:
        logs = os.path.join(st.config_dir(), "logs")
        say(logs)
        if sys.platform == "win32":
            actions.open_folder(logs)
    if args.check:
        checks = actions.readiness(state)
        _say_checks(checks)
        return 0 if actions.can_play(checks) else 1
    if args.restore:
        if not args.yes:
            answer = input("Put every changed game file back? [y/N] ") if sys.stdin else "n"
            if answer.strip().lower() not in ("y", "yes"):
                say("Nothing changed.")
                return 1
        try:
            done = actions.restore(state)
        except g.GameError as e:
            say(str(e), error=True)
            return 2
        say("Files put back: %d." % len(done) if done else "Nothing to put back.")
        return 0
    if args.update:
        return _update(args.yes, state)
    if args.repair:
        return _repair()
    if args.uninstall:
        return _uninstall(args.yes, args.delete_data, state)
    if args.serve:
        return _serve(state)
    if args.shortcut or args.autostart:
        from opendmt3.client import shortcuts
        try:
            if args.shortcut:
                say("Made %s" % shortcuts.make_shortcut())
            if args.autostart:
                on = shortcuts.autostart(args.autostart == "on")
                say("The game %s with Windows." % ("starts" if on else "does not start"))
        except Exception as e:  # noqa: BLE001  (said, never swallowed)
            say(str(e), error=True)
            return 2
        return 0
    if args.records and args.text:
        return _records_text(state)
    if args.records:
        return _records(state, args.no_browser)
    if args.play:
        from opendmt3.client import hosting
        checks = actions.readiness(state)
        if not actions.can_play(checks):
            # The same lines that keep the window's PLAY from starting.
            blocked = actions.blocking(checks)
            _say_checks(blocked, error=True)
            return play_failed(state, "quick.failed", blocked=blocked)
        host = hosting.BuiltinServer()
        try:
            card = actions.card_for(state, host)

            def go(report):
                return actions.play(state, report=report, host=host, card=card)

            if sys.stdout is None or sys.stderr is None:
                # The window copy (the desktop shortcut, playing when Windows starts) has no console: what PLAY is
                # doing shows in the launcher's own progress look, in a window of its own, until the game starts.
                from opendmt3.client import getting_ready
                session = getting_ready.standalone(state.language, go)
            else:
                session = go(lambda step: say("  getting ready: %s" % step))
        except actions.SignedOut:
            actions.forget_sign_in(state)
            state.save()
            say("The server no longer takes your sign-in. Sign in again on the ONLINE page.", error=True)
            return play_failed(state, "status.signed_out")
        except Exception as e:  # noqa: BLE001  (shown and logged, never swallowed)
            log.exception("--play failed")
            say(str(e), error=True)
            host.stop()
            return play_failed(state, None, error=e)
        say("The game is starting (process %d)." % session.process.pid)
        # PLAY holds the playing mutex from its start (client/playing.py): the installer refuses while a game runs,
        # and so does another launcher's PLAY; it goes when this process ends.
        # Stay until the game closes: the server on this PC lives in this process, the installer sees the game
        # running for as long as it runs, and the card leaves the game folder once the game is done with it.
        session.process.wait()
        actions.finish(state, session)
        state.save()
        if state.mode == "this_pc":
            host.stop()
        return 0
    return None
