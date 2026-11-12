"""Maintenance: while it is on, the game server refuses every card login with the reply the protocol notes prove (0x64
with 0x0E, which the game shows as a failed membership authentication: docs/protocol.md); cabinets already online stay
connected, and a game being played keeps its results. The admin turns it on and off on the Status page (or through the
API), and every page of the site says it is on, beside the notice.

It is kept beside the database as maintenance.json ({"at", "by"}), written to a new file and moved into place, as the
notice is (services/notice.py): no file, no maintenance. Readers go through files.load, which reads the file again only
when it changes, so every card login and every page can ask.
"""

import json
import os
import threading
import time

from opendmt3.server.services import files

FILE = "maintenance.json"


def read(data_dir):
    """Since when maintenance is on and who turned it on ({"at", "by"}), or None while it is off. A file that cannot be
    read counts as off: the cabinets log in rather than be shut out by a broken file."""
    try:
        kept = files.load(os.path.join(data_dir, FILE))
    except (OSError, ValueError):
        return None
    if not isinstance(kept, dict):
        return None
    # Only the two values it has ever held, whatever else a hand-written file holds.
    return {"at": kept.get("at"), "by": kept.get("by")}


def _write(data_dir, on, who="system", now=None):
    """Turn maintenance on or off: (the state now, as read() gives it, and whether it changed). On while on, or off
    while off, changes nothing (the moment and the admin it was turned on by stay)."""
    path = os.path.join(data_dir, FILE)
    kept = read(data_dir)
    if not on:
        try:
            # Off: no file. One that could not be read goes too.
            os.remove(path)
        except FileNotFoundError:
            pass
        return None, kept is not None
    if kept is not None:
        return kept, False
    os.makedirs(data_dir, exist_ok=True)
    state = {"at": int(now if now is not None else time.time()), "by": who}
    # A new file moved over the old one: the game server reads maintenance on or off, never half a file.
    partial = path + ".new"
    with open(partial, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(partial, path)
    return state, True


# One write at a time in this process: the site's threads may ask at once, and two writing the same ".new" file
# interleaved into a file that reads as nothing (maintenance off while an admin turned it on).
_WRITING = threading.Lock()


def write(*args, **kwargs):
    """_write(), one at a time (_WRITING)."""
    with _WRITING:
        return _write(*args, **kwargs)
