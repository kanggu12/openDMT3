"""Command line: check what openDMT3 makes to play the client data, make it, or put the files an earlier openDMT3
changed in it back as they were.

  python -m opendmt3 check   [CLIENT_DATA] [--to FOLDER] [--window] [--keep-hidden] [--server HOST:PORT]
  python -m opendmt3 setup   [CLIENT_DATA] [--to FOLDER] [--window] [--keep-hidden] [--server HOST:PORT]
  python -m opendmt3 restore [CLIENT_DATA]

CLIENT_DATA is the folder with the client and pack\\, or any folder above it (default: the current one). The client
data is only read: what openDMT3 makes goes in FOLDER (default: openDMT3-game in the current folder), and its copy
of the client starts from there with the client data's folder as the current folder.
"""

import argparse
import os
import sys

from opendmt3 import __version__
from opendmt3.core import game as g
from opendmt3.core.backup import Backup
from opendmt3.core.cabinet import steps


def _options(args):
    return steps.Options(display_mode="window" if getattr(args, "window", False) else "fullscreen",
                         unlock=not getattr(args, "keep_hidden", False),
                         server=getattr(args, "server", None))


def _header(game):
    print("Client data: %s" % game.root)
    digest, name = game.client_build(g.CLIENT_EXE)
    print("Client:      %s" % (name or "no %s" % g.CLIENT_EXE))


def cmd_check(args):
    game = g.Game.find(args.folder)
    _header(game)
    own = steps.Own(os.path.abspath(args.to))
    options = _options(args)
    todo = 0
    for step in steps.STEPS:
        s = step.status(game, own, options)
        todo += not s.done
        print("  [%s] %s: %s" % ("ok  " if s.done else "todo", step.name, s.detail))
    if todo:
        print("Run 'setup' to make the %d item(s) marked todo in %s." % (todo, own.folder))
    return 0


def cmd_setup(args):
    game = g.Game.find(args.folder)
    _header(game)
    own = steps.Own(os.path.abspath(args.to))
    options = _options(args)
    for step in steps.STEPS:
        s = step.status(game, own, options)
        if s.done:
            print("  [ok  ] %s: %s" % (step.name, s.detail))
            continue
        print("  [done] %s: %s" % (step.name, step.apply(game, own, options)))
    steps.write_list(game, own)
    print('Start "%s" with "%s" as the current folder.' % (own.client(), game.root))
    return 0


def cmd_restore(args):
    game = g.Game.find(args.folder)
    _header(game)
    done = Backup(game).restore_all()
    for rel in done:
        print("  [back] %s" % rel)
    print("Nothing to put back." if not done else "Put back %d file(s)." % len(done))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="opendmt3", description="Make what openDMT3 needs to play the client data.")
    parser.add_argument("--version", action="version", version="openDMT3 " + __version__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func, text in (("check", cmd_check, "show what setup would make"),
                             ("setup", cmd_setup, "make what playing the client data needs (its folder is only read)"),
                             ("restore", cmd_restore, "put back every file an earlier openDMT3 changed")):
        p = sub.add_parser(name, help=text)
        p.add_argument("folder", nargs="?", default=".", metavar="CLIENT_DATA",
                       help="the client data's folder, or a folder above it")
        if name in ("check", "setup"):
            p.add_argument("--to", default="openDMT3-game", metavar="FOLDER",
                           help="where openDMT3's files for the game go (default: openDMT3-game here)")
            p.add_argument("--window", action="store_true", help="a 1280x768 window instead of the whole screen")
            p.add_argument("--keep-hidden", action="store_true", help="leave hidden patterns hidden")
            p.add_argument("--server", metavar="HOST:PORT", help='where the game connects; "official" for its own')
        p.set_defaults(func=func)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except g.GameError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
