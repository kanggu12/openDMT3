"""The launcher's first page drawn at the start, as starts are: the first-start guide done, a player on this PC and a
last game of three cleared stages, straight on PLAY; the same with the window resized before its first drawing; and
every page (and the guide's first step) as the first page drawn. A page made before the window is laid out must
finish drawing at each size (2026-11-19: PLAY never did, its wrapping words and its columns handing the width back and
forth while the page area had none yet). In the UI container (run.sh), on a virtual screen only.

    python tests/e2e/ui/start.py --lang en [--sizes 1180x760,960x640,1600x1000]

Each start in a process of its own, given LIMIT seconds (a window that never finishes drawing holds its event loop
for good); prints a line a start and exits 1 when one does not finish drawing in its time."""
import argparse
import os
import random
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
sys.path.insert(0, HERE)

from opendmt3.core import safety  # noqa: E402

# How long a start may take to finish drawing its first page (seconds): about two in the container.
LIMIT = 60
# The window's sizes at 100 % (run.sh's); another scale passes its own (--sizes).
SIZES = ("1180x760", "960x640", "1600x1000")
# What is drawn first: PLAY as a start draws it, PLAY after the window was resized before its first drawing, each
# page as the first one drawn (made before the window is laid out), and the guide's first step at a first start.
CASES = ("play", "resized", "screen", "sound", "controls", "game", "online", "records", "help", "about", "guide")


def one(lang, size, case):
    """One start at `size`: the window made, its first page drawn, then closed."""
    import shots
    from opendmt3.client import state as st
    from opendmt3.client.app import LauncherApp
    from opendmt3.server.services import accounts
    home = tempfile.mkdtemp()
    os.environ["HOME"] = home
    os.environ["OPENDMT3_CONFIG_DIR"] = os.path.join(home, "config")
    rng = random.Random(7)
    table = bytes(rng.randrange(256) for _ in range(256))
    root = os.path.join(home, "Desktop", "TECHNIKA 3", "unpacked", "game")
    shots.make_game(root, table, rng)
    shots.stand_in(root, table)
    s = st.LauncherState()
    # The guide done (but at a first start), on this PC, with a last game of three cleared stages: a title long
    # enough to wrap and one in Hangul (shots.py's).
    s.language, s.game_folder, s.guide_done, s.mode = lang, root, case != "guide", "this_pc"
    s.last_session = {"seconds": 754, "exit_code": 0, "dumps": 0, "crashed": False, "plays": [
        {"title": shots.LONG_TITLE, "pattern": 3, "score": 987654},
        {"title": "가나다라마바사아자차카타파하", "pattern": 1, "score": 4530},
        {"title": "Made-up Song 7", "pattern": 2, "score": 301220}]}
    s.save()
    app = LauncherApp(s)
    if case == "resized":
        # Resized before its first drawing: another size first, then the one it keeps.
        other = "960x640" if size != "960x640" else "1180x760"
        app.root.geometry("%s+0+0" % other)
    # The window's size as the player left it.
    app.root.geometry("%s+0+0" % size)
    # A player of this PC, chosen.
    store = app.players()
    try:
        store.create("NOVA", "pass1234", "DJ NOVA")
    except accounts.AccountError:
        pass
    finally:
        store.db.close()
    app.state.player = "NOVA"
    app.state.save()
    if case in ("screen", "sound", "controls", "game", "online", "records", "help", "about"):
        # This page as the first one drawn: made, as PLAY was, before the window is laid out.
        app.go(case)
    shots.settle(app, 8)
    app.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", default="en")
    parser.add_argument("--sizes", default=",".join(SIZES))
    parser.add_argument("--one", help=argparse.SUPPRESS)
    parser.add_argument("--case", default="play", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not safety.on_virtual_display():
        # A window opens: only on the container's virtual screen, never on the developer's.
        sys.exit("refusing: this opens a window; run it in the UI test container (tests/e2e/ui/run.sh)")
    if args.one:
        one(args.lang, args.one, args.case)
        return
    failed = False
    for size in args.sizes.split(","):
        for case in CASES:
            started = time.time()
            try:
                done = subprocess.run([sys.executable, os.path.abspath(__file__), "--lang", args.lang, "--one", size,
                                       "--case", case], timeout=LIMIT, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
                ok = done.returncode == 0
                said = ("finished drawing in %.1f s" % (time.time() - started) if ok
                        else "stopped with %d" % done.returncode)
            except subprocess.TimeoutExpired:
                ok, said = False, "never finished drawing its first page at the start (%d s)" % LIMIT
            failed = failed or not ok
            print("%s-%s %s: the window %s" % (args.lang, size, case, said), flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
