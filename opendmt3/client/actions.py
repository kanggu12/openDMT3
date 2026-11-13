"""What the launcher's buttons do, without any window: check, get ready, play, put back.

The window and the command line (openDMT3.exe --play, --check, --restore) both call these, so a button and its
command always run the same checks.
"""

import logging
import os
import re
import time

from opendmt3.core import game as g
from opendmt3.core.backup import Backup
from opendmt3.core.cabinet import launch, steps, values as choices
from opendmt3.core.formats import pak

log = logging.getLogger("opendmt3.launcher")


class Check:
    """One line of the ready check: whether it is fine, what it says, and which page fixes it."""

    def __init__(self, key, ok, detail, page=None, error=None, line=None):
        self.key = key          # a stable name for the line (tests and the help page refer to it)
        self.ok = ok            # True: nothing to do; False: PLAY fixes it or the player must
        self.detail = detail    # the words in plain English, for the command line and the log
        self.page = page        # the page that fixes it, or None when PLAY fixes it by itself
        self.error = error      # the error behind a failed line: the window says it in the player's language
        self.line = line        # the launcher's own words under the line, (key, values): the reason, or a note


# Ready-check lines that stop PLAY until the player fixes them (the others PLAY fixes by itself).
BLOCKING = ("folder", "client", "files", "running", "remote")


def can_play(checks):
    """True when no line of the ready check stops PLAY: the window and --play decide the same way."""
    return not blocking(checks)


def blocking(checks):
    """The lines of the ready check that stop PLAY, in the check's order (the first is what to fix first)."""
    return [c for c in checks if not c.ok and c.key in BLOCKING]


def said(check, w):
    """What stands under a line of the ready check, in w's language: why it stops PLAY (the card's words for the
    folder: errors.py's, or the launcher's own line), or a note on a line that is fine. None when the line's name
    says it all."""
    if check.error is not None:
        # The error's own words (the cabinet's client, a damaged file), as the Game page's card says them.
        return w.error(check.error)
    if check.line is not None:
        return w(check.line[0], **check.line[1])
    return None


def why_not(check, w):
    """Why a line stops PLAY, as one sentence for the status line and for the window of a PLAY that could not go:
    what stands under the line, or the launcher's own sentence for a line whose name says it."""
    # A sign-in that is missing and a game that is open are fixed elsewhere: each has its sentence.
    own = {"remote": "status.sign_in_first", "running": "status.game_open"}
    return said(check, w) or (w(own[check.key]) if check.key in own else w("check." + check.key))


def damaged(game):
    """The worded error for a game file that cannot be read (cut short while it was copied, damaged): the card's own
    sentence for the folder when its reading names the file (the one with the song list), else the one for any of the
    game's files. The reader's own words ("shorter than an archive's header") are for the log."""
    key = None
    try:
        # The same reading the folder's card is made from (half a second), asked only once a file failed to read.
        from opendmt3.server.services import catalog
        key = catalog.survey(game.root).get("problem_key")
    except Exception:  # noqa: BLE001  (the plain sentence stands in)
        log.warning("the client data could not be looked at for what is damaged", exc_info=True)
    # Each sentence where it is raised, as every keyed error has it (tests/core/test_errors.py holds each to the
    # table's own English).
    if key == "error.game.damaged.songs":
        return g.GameError("The file with the song list is damaged. Copy the client data again, or unpack the "
                           "archive again.", "error.game.damaged.songs")
    if key == "error.game.damaged.jackets":
        return g.GameError("The file with the jackets is damaged. Copy the client data again, or unpack the archive "
                           "again.", "error.game.damaged.jackets")
    if key == "error.game.damaged.cards":
        return g.GameError("The file with the DJ cards is damaged. Copy the client data again, or unpack the archive "
                           "again.", "error.game.damaged.cards")
    # Any other reading that failed, or a look that could not tell which file: the plain sentence.
    return g.GameError("One of the game's files is damaged. Copy the client data again, or unpack the archive again.",
                       "error.game.damaged")


def readiness(state):
    """The ready check shown on the PLAY page and by --check, in the order a player would fix things."""
    lines = []
    try:
        game = state.game()
    except g.GameError as e:
        # Without a game folder nothing else can be checked.
        return [Check("folder", False, str(e), page="game", error=e)]
    lines.append(Check("folder", True, game.root, page="game"))
    try:
        # The client the game's files open with: the PC client, a fixed copy, or a modified PC client.
        game.table()
    except g.GameError as e:
        # The cabinet's client, or none of the game's: the game cannot be started from here. The Game page is where
        # another folder is chosen, and its card says the same words.
        return lines + [Check("client", False, str(e), page="game", error=e)]
    # A modified PC client plays without the screen fit: said under the line, in the card's words.
    modified = bool(game.client) and game.client[1] == g.MODIFIED
    lines.append(Check("client", True, "modified PC client" if modified else "supported client",
                       line=("intake.line.modified", {}) if modified else None))
    missing = game.missing()
    for part, words in (("tutorial", "The file with the tutorial is missing: the game stops at the tutorial."),
                        ("charts", "The file with the charts is missing: the game stops when a song starts.")):
        if part in missing:
            # Measured: the game stops when the tutorial, or a song, starts; PLAY waits for a whole copy. The window
            # says it in the card's words (intake.line.no_tutorial, intake.line.no_charts).
            return lines + [Check("files", False, words + " Copy the client data again, or unpack the archive again.",
                                  page="game", line=("intake.line.no_" + part, {}))]
    from opendmt3.client import intake
    try:
        unplayable = intake.without_charts(game)
    except pak.PakError as e:
        # One of the game's files does not read (a copy cut short): the game would stop, and PLAY waits for a whole
        # copy. Said in the card's words, never the reader's own.
        log.info("a game file of %s could not be read: %s", game.root, e)
        error = damaged(game)
        return lines + [Check("files", False, str(error), page="game", error=error)]
    if unplayable and unplayable["first"]:
        # The first song the game shows has no chart: it would stop at once (this check runs off the window's thread,
        # and the card's look has usually worked it out already).
        return lines + [Check("files", False, "The first song the game shows has no charts: the game stops when it "
                                              "starts. Copy the client data again, or unpack the archive again.",
                              page="game", line=("intake.line.first_song_no_charts", {}))]
    if state.mode == "server":
        signed = bool(state.remote and state.remote.get("card"))
        # Without a sign-in there is no card to put in: the Online page signs in.
        lines.append(Check("remote", signed, (state.remote or {}).get("dj_name") or "not signed in", page="online"))
    own = state.own()
    if launch.running_clients(own) or launch.running_clients(game):
        # Rewriting openDMT3's copies under a running game would break it.
        lines.append(Check("running", False, "the game is open: close it first"))
    options = state.options()
    for step in steps.STEPS:
        try:
            status = step.status(game, own, options)
        except pak.PakError as e:
            # A game file the step reads does not read: PLAY could not make it either. Said as the card says it.
            log.info("a game file of %s could not be read for %s: %s", game.root, step.name, e)
            error = damaged(game)
            return lines + [Check("files", False, str(error), page="game", error=error)]
        except (g.GameError, OSError, ValueError) as e:
            # A step that cannot tell (a file it reads is damaged): PLAY says the same when it tries.
            status = steps.Status(False, str(e))
        if state.mode == "offline" and step.name == "server address" and status.done:
            # Offline with the game's own address: nothing to say about it.
            continue
        # Steps that are not done are done by PLAY itself; they are listed so the player sees what will change.
        lines.append(Check("step:" + step.name, status.done, status.detail))
    return lines


def prepare(state, report=lambda text: None, took=None, game=None):
    """Bring openDMT3's own folder in line with the game folder and the choices (the game folder is only read);
    returns the lines of what changed.

    report(text) is told each step as it starts, for the progress look; `took` gets each step's time; `game`, the game
    folder when PLAY has found it already.
    """
    game = game or state.game()
    own = state.own()
    if launch.running_clients(own) or launch.running_clients(game):
        raise g.GameError("the game is open: close it before changing its files", "error.game.open_change")
    try:
        return steps.prepare(game, own, state.options(), report, took)
    except pak.PakError as e:
        # A game file that does not read (cut short, damaged): said in the card's words; the reader's own go to the
        # log with the traceback.
        log.info("a game file of %s could not be read", game.root, exc_info=True)
        raise damaged(game) from e


# The card the launcher puts in openDMT3's card reader: a text file beside the library in openDMT3's folder
# (native/cardreader).
CARD_FILE = "openDMT3-card.txt"
# The in-game layer's note when its safety net made the picture lighter to keep 60 frames a second (one line a step),
# beside the library.
PICTURE_NOTE = "openDMT3-picture.txt"
# The in-game layer's note of the picture's GPU time by pass (the Screen page's Measure the picture's GPU time): a line
# each ten seconds of play, each pass's median, beside the library; an hour's lines at most.
PICTURE_TIMES_NOTE = "openDMT3-picture-times.txt"
PICTURE_TIMES_LINES = 360
# The in-game layer's note of the run's sound, beside the library: the Mixer's line (native/cardreader/hooks.c), then
# the sound engine's period's (native/cardreader/engine.c), written when the game opens its sound.
SOUND_NOTE = "openDMT3-sound.txt"
# The steps of OpenAL Soft's opening the layer names when one failed (native/cardreader/openal.c, hooks.c).
MIXER_FAILURES = ("path", "settings", "openal", "dsoal", "device", "old-call")
# Its results' words, as the layer writes them (ENGINE_NAMES in native/cardreader/logic.c), and its numbers' names.
ENGINE_RESULTS = ("off", "no-device", "no-client3", "no-answer", "none-shorter", "locked", "refused", "unchanged",
                  "held")
ENGINE_NUMBERS = ("rate", "default", "step", "min", "max", "before", "asked", "got")


class SignedOut(Exception):
    """Another server no longer takes the launcher's sign-in (a new password, a disabled account)."""


def card_for(state, host=None):
    """The card number to put in for this PLAY, or None to play as a guest.

    On this PC it is the chosen player's card on the built-in server. On another server it is asked for again
    at every PLAY, because a new password there gives a new card; SignedOut when that server no longer takes
    the sign-in. When the server cannot be reached, PLAY stops with that reason (RemoteError, worded): the
    game would not reach it either, and the plays would be kept nowhere (Offline plays without a server).
    """
    if state.mode == "this_pc":
        if not state.player or host is None:
            return None
        store = host.accounts()
        try:
            row = store.by_login(state.player)
            return row["card"] if row and not row["disabled"] else None
        finally:
            store.db.close()
    if state.mode == "server":
        signed = state.remote or {}
        if not signed.get("token"):
            return None
        from opendmt3.client import remote
        try:
            me = remote.me(state.server_url, signed["token"])
            # Admin rights given or taken on the server since the sign-in: the Game page follows them.
            state.remote = dict(state.remote, is_admin=me.get("is_admin") is True)
            return me["card"]
        except remote.RemoteError as e:
            if e.code == "sign_in":
                raise SignedOut(str(e)) from None
            raise
    return None


def server_status(address):
    """Another server's address, made whole, and what it says about itself (its version and the game's port): the
    Online page's Connect and --server ask the same. RemoteError (worded) when it does not answer."""
    from opendmt3.client import remote
    base = remote.normalize(address)
    return base, remote.status(base)


def use_server(state, base, found):
    """Play on that server from now on (what server_status() found). A new server forgets the old sign-in: its card
    belongs to the other server."""
    if state.server_url != base:
        state.remote = None
    state.server_url = base
    state.remote = dict(state.remote or {}, game=found["game"], version=found.get("version"),
                        updates=bool(found.get("updates")))


def signed_in(state, me):
    """Keep what signing in to the other server brought: the player, the card, the token, and whether the account is
    an admin of that server (the Game page then offers to send it the song list)."""
    state.remote = dict(state.remote or {}, login_id=me["login_id"], dj_name=me["dj_name"], card=me["card"],
                        token=me["token"], is_admin=me.get("is_admin") is True)


def is_server_admin(state):
    """True when the launcher plays on another server, signed in to an account that is its admin."""
    signed = state.remote or {}
    return state.mode == "server" and bool(state.server_url and signed.get("token") and signed.get("is_admin"))


def end_token(base, token):
    """Ask the other server to end the launcher's token (remote.sign_out), so a copy of it stops working there too.
    Best effort, and it never raises: True when the server ended it, False when there was nothing to end or it could
    not be done (no answer, a server older than the call, any failure, which is logged)."""
    if not (base and token):
        return False
    from opendmt3.client import remote
    try:
        return remote.sign_out(base, token)
    except Exception:  # noqa: BLE001  (a sign-out never stops on the server's answer: what follows forgets anyway)
        log.exception("the server could not be asked to end the sign-in")
        return False


def sign_out(state):
    """Sign out of the other server (Online's Sign out, --sign-out): the server is asked to end the launcher's token
    first (end_token, best effort), then the sign-in is forgotten here (signed_out) whatever it answered."""
    end_token(state.server_url, (state.remote or {}).get("token"))
    signed_out(state)


def signed_out(state):
    """Forget the sign-in on the other server; its address and its game stay."""
    if state.remote:
        state.remote = {k: v for k, v in state.remote.items() if k in ("game", "version", "updates")}


def forget_sign_in(state):
    """Drop another server's token, card and admin rights (kept: its game address), after it stopped taking them."""
    if state.remote:
        state.remote = {k: v for k, v in state.remote.items() if k not in ("token", "card", "is_admin")}


def put_card(place, card):
    """Put a card in the reader (its number), or take it out (None). place: openDMT3's folder (steps.Own), or a game
    folder where an earlier openDMT3 left a card.

    The launcher writes it at PLAY, before the game starts; the game reads it when its card screen looks for a
    card, so the player in the file is the one who logs in.
    """
    from opendmt3.client import remote
    path = place.path(CARD_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # A link at that name (or an earlier card) goes first: the file is made new, never written through a link.
    if os.path.lexists(path):
        os.remove(path)
    if card:
        if not remote.CARD.fullmatch(card):
            # Only a number the card reader takes; the launcher checked it already, this keeps the file sound.
            raise ValueError("not a card number")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(card + "\n")


def play(state, report=lambda text: None, popen=None, host=None, card=None):
    """Get openDMT3's folder ready, then start the game; returns the running session. This launcher holds the playing
    mutex from here until the game closes (the caller's finish); another launcher's PLAY is refused meanwhile.

    host is the built-in server (started here when playing on this PC); card is the number of the player's
    card, or None to play as a guest.
    """
    from opendmt3.client import playing
    if not playing.claim():
        raise g.GameError("Another openDMT3 is getting the game ready or playing it. Wait until that game closes.",
                          "error.game.another_play")
    try:
        return _play(state, report, popen, host, card)
    except BaseException:
        # Nothing started: the next PLAY, here or in another launcher, may go.
        playing.release()
        raise


# What PLAY does, in order, by the names report() is told: the server on this PC and its song list (playing on this
# PC), each of openDMT3's steps (core/cabinet/steps.py), then starting the game. The progress look shows the share.
PHASES = ["server", "song list"] + [step.name for step in steps.STEPS] + ["starting"]


def _play(state, report, popen, host, card):
    took = []
    began = time.perf_counter()

    def timed(name, work):
        """Run one part of PLAY and keep how long it took, for the log's line."""
        at = time.perf_counter()
        try:
            return work()
        finally:
            took.append("%s %.1f s" % (name, time.perf_counter() - at))

    # The game folder found once for the whole PLAY (finding it lists the folder: 0.7 s under Wine each time).
    game = timed("client data", state.game)
    if state.mode == "this_pc":
        if host is None:
            raise g.GameError("playing on this PC needs the built-in server", "error.game.needs_host")
        report("server")
        timed("server", host.start)
        game_root = game.root
        if not host.catalog():
            # Read once (catalog.load answers {} until then): titles for the records and the DJ cards' tables, from
            # this player's own game files; a reading started ahead is waited for.
            report("song list")

        def song_list():
            try:
                host.import_catalog(game_root)
            except Exception:  # noqa: BLE001  (records still work with song numbers)
                log.warning("the song list could not be read from the client data", exc_info=True)

        timed("song list", song_list)
    timed("openDMT3's folder", lambda: prepare(state, report, took, game))
    own = state.own()
    report("starting")
    timed("card", lambda: put_card(own, card if state.mode in ("this_pc", "server") else None))
    kwargs = {} if popen is None else {"popen": popen}
    # The in-game layer's choices (language, pointer, frame limit, sound device) travel in the game's environment.
    session = timed("start", lambda: launch.start(game, own, env=choices.layer_environment(state.values, state.language),
                                                  **kwargs))
    # One line for the log: how long PLAY took to start the game, and each part of it.
    log.info("PLAY started the game in %.1f s (%s)", time.perf_counter() - began, ", ".join(took))
    return session


def finish(state, session):
    """Remember how the last run ended (length, exit code, new crash dumps) and return that record."""
    own = state.own()
    seconds = int(session.seconds())
    code = session.exit_code()
    # The client writes a dump when it crashes (into openDMT3's folder); new ones mean this run ended in a crash.
    dumps = len(launch.crash_dumps(own, session.started))
    record = {
        "ended": time.time(),
        "seconds": seconds,
        "exit_code": code,
        "dumps": dumps,
        # One verdict for every place that reports it: a dump, or an error code within the first half
        # minute (the game did not get going: a missing DLL, a driver that refused).
        "crashed": dumps > 0 or (code not in (0, None) and seconds < 30),
    }
    state.last_session = record
    # One line for the log: how the run ended (a report for an issue reads it, and so do the Wine tests).
    log.info("the game closed after %d s (exit code %s, %d crash dump(s))", seconds, code, dumps)
    # The layer's safety net, when it stepped the picture down in this run: into the log, then the note goes.
    record["picture_steps"] = picture_steps(own)
    # The picture's GPU time by pass, when it was measured: into the log (and so into a report), then the note goes.
    record["picture_times"] = picture_times(own)
    # Who mixed the game's sound and the sound engine's period it ran at: into the log, and kept for the Sound page;
    # then the note goes.
    record["sound_mixer"], record["sound_engine"] = sound_notes(own)
    # The card is a login of its own: it stays only while the game runs.
    try:
        put_card(own, None)
    except OSError:
        log.warning("could not take the card file out", exc_info=True)
    # The short path to the game folder, when one was made, goes with the game (a junction left behind is a link to
    # the player's game a careless clean-up could follow).
    launch.take_short_paths_away()
    return record


def tidy_after_an_end(state):
    """At a launcher's start: a short path a launcher left when it ended while its game ran goes, unless a game is
    running now (another launcher's, or one this folder's client copy runs)."""
    from opendmt3.client import playing
    try:
        if playing.running() or launch.running_clients(state.own()):
            return
        launch.take_short_paths_away()
    except Exception:  # noqa: BLE001  (never in the way of starting)
        log.warning("could not look for a short path left behind", exc_info=True)


def picture_steps(own):
    """The in-game layer's steps to a lighter picture in the run that ended (its note's lines), logged; the note goes."""
    path = own.path(PICTURE_NOTE)
    try:
        with open(path, encoding="ascii", errors="replace") as f:
            # A few short lines at most (one a step, three steps at most); more is not the layer's.
            steps = [line.strip() for line in f.read(4096).splitlines() if line.strip()][:8]
    except OSError:
        return []
    for step in steps:
        log.info("the in-game picture %s to keep 60 frames a second", step)
    try:
        os.remove(path)
    except OSError:
        log.warning("could not remove the in-game picture note", exc_info=True)
    return steps


def picture_times(own):
    """The in-game layer's GPU time by pass in the run that ended (its note's lines, one each ten seconds), logged; the
    note goes. Empty when it was not measured."""
    path = own.path(PICTURE_TIMES_NOTE)
    try:
        with open(path, encoding="ascii", errors="replace") as f:
            # An hour's lines at most (the layer writes no more); each line a few hundred bytes.
            lines = [line.strip() for line in f.read(PICTURE_TIMES_LINES * 1024).splitlines() if line.strip()]
    except OSError:
        return []
    lines = lines[:PICTURE_TIMES_LINES]
    for line in lines:
        log.info("the in-game picture's GPU time by pass at %s", line)
    try:
        os.remove(path)
    except OSError:
        log.warning("could not remove the in-game picture's time note", exc_info=True)
    return lines


def engine_from_line(line):
    """The layer's line of the sound engine's period as a record: {"result": its word, "output": "chosen" or
    "default", "device": its GUID, "hr": the last call's result, and each of ENGINE_NUMBERS in frames}; None for a line
    the layer does not write. Only the words and numbers it knows are taken."""
    words = line.split()
    # "engine", then one of the results' words, then key=value pairs.
    if len(words) < 2 or words[0] != "engine" or words[1] not in ENGINE_RESULTS:
        return None
    record = {"result": words[1]}
    for word in words[2:]:
        key, _, value = word.partition("=")
        if key in ENGINE_NUMBERS and value.isdigit():
            # Frames (or the rate's frames a second): whole numbers only.
            record[key] = int(value)
        elif key == "output" and value in ("chosen", "default"):
            record[key] = value
        elif key == "device" and re.fullmatch(r"\{[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}\}", value):
            # As the launcher keeps a chosen device: upper case with braces.
            record[key] = value
        elif key == "hr" and re.fullmatch(r"0x[0-9a-f]{8}", value):
            record[key] = value
    return record


def engine_ms(frames, rate):
    """Frames at a rate as the pages say milliseconds: one decimal, none for a whole number (2.7, 10)."""
    ms = round(frames * 1000.0 / rate, 1)
    return ("%.1f" % ms).rstrip("0").rstrip(".")


def engine_said(record):
    """The log's line for the sound engine's period in a run (the layer's record)."""
    rate = record.get("rate") or 0
    # Each period with its milliseconds when the rate is known.
    at = lambda name: "%d frames%s" % (record.get(name, 0), " (%s ms)" % engine_ms(record.get(name, 0), rate)
                                       if rate else "")
    where = "Windows' default output" if record.get("output") == "default" else "the chosen device"
    device = "%s %s" % (where, record.get("device", "")) if record.get("device") else where
    if record["result"] == "off":
        return "the sound engine's period was left as Windows has it (low latency off)"
    if record["result"] == "held":
        return "the sound engine ran at %s a period on %s while the game ran, %s without openDMT3" % (
            at("got"), device, at("default"))
    return ("the sound engine's period was not made shorter on %s (%s): asked %s, the driver's shortest %s, its "
            "default %s, the engine's period %s (%s)") % (device, record["result"], at("asked"), at("min"),
                                                          at("default"), at("got") if record.get("got") else
                                                          at("before"), record.get("hr", "-"))


def mixer_from_line(line):
    """The layer's line of the run's Mixer as a record: {"chosen": the Mixer chosen, "played": the one that played,
    "output": "chosen" or "default", "device": the launcher's device by its GUID, "failed": the step of OpenAL Soft's
    opening that failed (None when none did), "hr": its error}; None for a line the layer does not write."""
    words = line.split()
    # "mixer", then key=value pairs.
    if len(words) < 3 or words[0] != "mixer":
        return None
    fields = dict(word.partition("=")[::2] for word in words[1:])
    # The two names must be the launcher's own; anything else is not the layer's line.
    if fields.get("chosen") not in choices.SOUND_PATHS or fields.get("played") not in choices.SOUND_PATHS:
        return None
    failed, hr, device = fields.get("failed"), fields.get("hr", ""), fields.get("device", "")
    return {"chosen": fields["chosen"], "played": fields["played"],
            # Which of the launcher's choices of device the run had: its own words only.
            "output": fields.get("output") if fields.get("output") in ("chosen", "default") else None,
            "device": device if re.fullmatch(r"\{[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}\}", device) else None,
            # The step words the layer writes (openal.c, hooks.c); "-" and anything else is no failure said.
            "failed": failed if failed in MIXER_FAILURES else None,
            "hr": hr if re.fullmatch(r"0x[0-9a-f]{8}", hr) else None}


def mixer_said(record):
    """The log's line for who mixed the game's sound in a run (the layer's record)."""
    names = {"directsound": "Windows' DirectSound", "openal": "OpenAL Soft (shared)",
             "openal-exclusive": "OpenAL Soft (exclusive)"}
    if record["chosen"] == record["played"]:
        # As chosen.
        return "the game's sound was mixed by %s" % names[record["played"]]
    # Chosen and not opened: the step that failed and its error, for a report.
    return "%s was chosen and did not open (at its %s, %s): %s mixed the game's sound" % (
        names[record["chosen"]], record["failed"] or "?", record["hr"] or "-", names[record["played"]])


def sound_notes(own):
    """Who mixed the run that ended and the sound engine's period it ran at, from the in-game layer's note: the records
    of mixer_from_line and engine_from_line (None for either the note does not hold), each logged; the note goes."""
    path = own.path(SOUND_NOTE)
    try:
        with open(path, encoding="ascii", errors="replace") as f:
            # Two short lines (the layer writes no more): the first four lines are the most that are read.
            lines = f.read(1024).splitlines()[:4]
    except OSError:
        return None, None
    mixer = engine = None
    for line in lines:
        mixer = mixer or mixer_from_line(line)
        engine = engine or engine_from_line(line)
    if mixer is None and engine is None:
        log.warning("the in-game sound note is not the layer's: %r", lines[:2])
    if mixer is not None:
        log.info(mixer_said(mixer))
    if engine is not None:
        log.info(engine_said(engine))
    try:
        os.remove(path)
    except OSError:
        log.warning("could not remove the in-game sound note", exc_info=True)
    return mixer, engine


def sound_mixer_line(record, chosen, device):
    """What the Sound page says under Mixer about the last game (its words' key), or None: only when that game's Mixer
    and device are the ones chosen now and OpenAL Soft did not open, so Windows' DirectSound played.
    "sound.mixer.not_loaded" when its libraries did not load (Help's Repair puts them back), else
    "sound.mixer.fell_back" (the device did not open through it)."""
    # No record, another Mixer than the one chosen now, or the chosen one played: nothing to say.
    if not record or record.get("chosen") != chosen or record.get("played") == chosen:
        return None
    if device == choices.DEFAULT_DEVICE:
        # Windows' default output then and now.
        if record.get("output") != "default":
            return None
    elif record.get("output") != "chosen" or (record.get("device") or "").upper() != str(device).upper():
        # Another device: what happened on it says nothing of this one.
        return None
    # The libraries themselves (their files, their path, the settings beside them), or the device's opening.
    if record.get("failed") in ("path", "settings", "openal", "dsoal"):
        return "sound.mixer.not_loaded"
    return "sound.mixer.fell_back"


def sound_engine_line(record, chosen):
    """What the Sound page says under Low latency about the last game (its words' key and their values), or None: only
    when that game ran on the device chosen now (by its GUID, or Windows' default output both times) and the engine's
    period it ran at is known. "sound.low_latency.held" when Low latency made it shorter than the device's default;
    "sound.low_latency.other" when it was shorter already before the ask (another program's stream held it so, and
    turning Low latency off would not change it); "sound.low_latency.kept" when it stayed at the default."""
    # Off, or no record at all: nothing about the last game to say under the row.
    if not record or record.get("result") == "off":
        return None
    if chosen == choices.DEFAULT_DEVICE:
        # Windows' default output then and now (which device that was is Windows' to say).
        if record.get("output") != "default":
            return None
    elif record.get("output") != "chosen" or record.get("device", "").upper() != str(chosen).upper():
        # Another device than the one chosen now: its periods say nothing of this one.
        return None
    rate, usual = record.get("rate") or 0, record.get("default") or 0
    # The engine's period with the stream running, or before it when none ran (another program's, or the default).
    before = record.get("before") or 0
    period = record.get("got") or before
    if not rate or not usual or not period:
        # The device's format or its periods were never read (no IAudioClient3, the device not found).
        return None
    if period >= usual:
        # The default's steps: nothing shorter was allowed.
        return "sound.low_latency.kept", {"ms": engine_ms(period, rate)}
    if before and before < usual:
        # Shorter already before the ask: another program's doing, which goes on whatever Low latency says.
        return "sound.low_latency.other", {"ms": engine_ms(period, rate)}
    # Shorter because of the ask: without Low latency the device's own default.
    return "sound.low_latency.held", {"ms": engine_ms(period, rate), "usual": engine_ms(usual, rate)}


def save_song_list(state, path):
    """Save the song list from the game folder in use into one file for a server (the Game page's Save the song
    list..., --save-song-list): the song list, its jackets and the DJ cards, read as a server reads them and checked as
    a server takes them (services/sources.py). Returns (the file's manifest, its size in bytes). A folder named: the
    file goes in it under its usual name."""
    from opendmt3.server.services import songlist, sources
    if os.path.isdir(path):
        path = os.path.join(path, songlist.NAME)
    manifest, _ = sources.save(state.game().root, path)
    return manifest, os.path.getsize(path)


def send_song_list(state):
    """Send the song list from the game folder in use to the other server, as its admin (the Game page's Send the song
    list to this server, --send-song-list): made into a file in a folder of its own, sent, and the file removed.
    Returns the server's answer; RemoteError (worded) when it refuses, GameError when the game folder cannot give one."""
    import shutil
    import tempfile
    from opendmt3.client import remote
    from opendmt3.server.services import songlist
    token = (state.remote or {}).get("token")
    if state.mode != "server" or not state.server_url or not token:
        raise g.GameError("sign in on the ONLINE page first", "error.records.signin")
    folder = tempfile.mkdtemp(prefix="openDMT3-song-list-")
    try:
        path = os.path.join(folder, songlist.NAME)
        save_song_list(state, path)
        return remote.send_song_list(state.server_url, token, path)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def restore(state):
    """Put every file an earlier openDMT3 changed back as it was in the folder in use (PLAY changes none now); returns
    the relative paths put back."""
    return put_back(state.game().root)


def put_back(root):
    """Put every file an earlier openDMT3 changed back as it was in the game folder at root (the folder in use, or
    another a card names); returns the relative paths put back."""
    from opendmt3.client import state as st
    game = g.Game(root)
    # The game reads the folder's files while it runs from openDMT3's folder: nothing is put back under it.
    if launch.running_clients(game) or launch.running_clients(st.own_folder()):
        raise g.GameError("the game is open: close it before putting its files back", "error.game.open_restore")
    # A card an earlier openDMT3 left there is not one of the game's; it goes too, so the folder is exactly as it came.
    put_card(game, None)
    return Backup(game).restore_all()


def records(state, host):
    """The chosen player's records, as the Records page and --records --text show them (server/services/profile.py): from
    this PC's own database, or through the other server's API. GameError (worded) when there are none to show."""
    from opendmt3.client import remote
    from opendmt3.server.services import profile
    if state.mode == "this_pc":
        if not state.player:
            raise g.GameError("choose a player first: a guest has no records page", "error.records.guest")
        store = host.accounts()
        try:
            row = store.by_login(state.player)
        finally:
            store.db.close()
        if row is None:
            raise g.GameError("%s is not a player on this PC" % state.player, "error.records.no_player",
                              login_id=state.player)
        try:
            # Titles and levels instead of song numbers (read once from this player's own game files).
            host.import_catalog(state.game().root)
        except Exception:  # noqa: BLE001  (the numbers still show)
            pass
        found = profile.dj(host.path, os.path.dirname(host.path), row["id"])
        if found is None:
            raise g.GameError("%s is not a player on this PC" % state.player, "error.records.no_player",
                              login_id=state.player)
        return found
    if state.mode == "server":
        token = (state.remote or {}).get("token")
        if not token:
            raise g.GameError("sign in on the ONLINE page first", "error.records.signin")
        me = remote.me(state.server_url, token)
        if "player" not in me:
            raise g.GameError("this server is too old for the RECORDS page",
                              "error.records.old_server")
        return remote.dj(state.server_url, token, me["player"])
    raise g.GameError("records are kept when playing on this PC or on another server, not offline",
                      "error.records.offline")


def records_link(state, host):
    """A link that opens the chosen player's DJ page on this PC's site, signed in (PLAY's button and --records).

    Starts the built-in server and its site when they are not running yet.
    """
    if state.mode != "this_pc":
        raise g.GameError("the records page is for playing on this PC", "error.records.mode")
    if not state.player:
        raise g.GameError("choose a player first: a guest has no records page", "error.records.guest")
    host.start()
    try:
        # Titles instead of song numbers, from this player's own game files.
        host.import_catalog(state.game().root)
    except Exception:  # noqa: BLE001  (the pages still work with song numbers)
        pass
    if host.site is None:
        raise g.GameError("this launcher cannot show the records page (its web libraries are missing)",
                          "error.records.no_site")
    link = host.sign_in_link(state.player, state.language)
    if link is None:
        raise g.GameError("%s is not a player on this PC" % state.player, "error.records.no_player",
                          login_id=state.player)
    return link


def open_link(url):
    """Open a page in the default browser, never from a test."""
    from opendmt3.core import safety
    safety.refuse_windows_in_tests("the browser")
    import webbrowser
    webbrowser.open(url)


def open_folder(path):
    """Show a folder in Explorer (Windows only), never from a test outside the virtual screen."""
    from opendmt3.core import safety
    safety.refuse_windows_in_tests("Explorer")
    if hasattr(os, "startfile"):
        os.startfile(path)
