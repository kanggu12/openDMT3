"""The launchers that ask this server, as it hears them: every call of the API a launcher makes names it in its
User-Agent (openDMT3-launcher/<version>, client/remote.py), from its PC's address, and a signed one says whose account
it is. Kept in memory while the server runs (a restart starts again, as the cabinets connected now do), at most MOST
of them, each for a day after it was last heard; the admin's Cabinets page and GET /api/v1/launchers show them."""

import re
import threading
import time

# How many launchers are kept at once (the oldest heard goes first) and for how long after they were last heard.
MOST = 256
KEPT = 86400
# A launcher heard within this many seconds counts as here now (it asks the server when it opens, signs in, starts a
# game and shows records; a launcher left open asks nothing, so "now" is a window, not a connection).
NOW = 600
# The launcher's own name in a request's User-Agent, and its version after it.
AGENT = re.compile(r"^openDMT3-launcher/([0-9A-Za-z.+-]{1,32})")


def version_of(agent):
    """The launcher's version a User-Agent says, or None when it is not a launcher's."""
    found = AGENT.match(agent or "")
    return found.group(1) if found else None


class Launchers:
    """The launchers heard, by their PC's address and the account they signed in with ("" before a sign-in)."""

    def __init__(self, clock=time.time):
        self._clock, self._lock, self._seen = clock, threading.Lock(), {}
        # When this server began to listen: what "since" means on the page and in the API.
        self.since = int(clock())

    def heard(self, address, version, account=None):
        """A call from a launcher: its address, its version, and the account's row when the call was signed."""
        now = self._clock()
        key = (str(address), account["login_id"] if account is not None else "")
        with self._lock:
            entry = self._seen.get(key)
            if entry is None:
                entry = self._seen[key] = {"address": str(address), "first_seen": int(now), "calls": 0}
            entry.update(version=str(version), last_seen=int(now), calls=entry["calls"] + 1)
            if account is not None:
                entry.update(login_id=account["login_id"], dj_name=account["dj_name"], player=account["id"])
            # A launcher heard before its sign-in and after it, from one PC: the signed one says it all.
            if account is not None:
                self._seen.pop((str(address), ""), None)
            self._trim(now)

    def _trim(self, now):
        """Those not heard for KEPT go, then the oldest heard past MOST (under the lock)."""
        for key in [k for k, e in self._seen.items() if now - e["last_seen"] > KEPT]:
            del self._seen[key]
        if len(self._seen) > MOST:
            for key, _ in sorted(self._seen.items(), key=lambda item: item[1]["last_seen"])[:len(self._seen) - MOST]:
                del self._seen[key]

    def view(self):
        """Every launcher kept, the one heard last first: address, version, first_seen, last_seen, calls, now (heard
        within NOW), and the account (login_id, dj_name, player; null before a sign-in)."""
        now = self._clock()
        with self._lock:
            self._trim(now)
            rows = [dict(e) for e in self._seen.values()]
        for row in rows:
            row.setdefault("login_id", None)
            row.setdefault("dj_name", None)
            row.setdefault("player", None)
            row["now"] = now - row["last_seen"] <= NOW
        return sorted(rows, key=lambda r: -r["last_seen"])
