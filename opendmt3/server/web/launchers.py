"""The launchers that ask this server, as it hears them: every call of the API a launcher makes names it in its
User-Agent (openDMT3-launcher/<version>, client/remote.py), from its PC's address, and a signed one says whose account
it is. Kept in memory while the server runs (a restart starts again, as the cabinets connected now do), at most MOST
of them, each for a day after it was last heard; the admin's Cabinets page and GET /api/v1/launchers show them.

Only a signed call makes a row (whose launcher it is, its version): anyone can send a launcher's name in a User-Agent,
so a call without a sign-in is only counted, by its sender (an IPv6 /64 is one, as the sign-in limits count it), apart
from the rows: a flood of them never pushes a launcher that signed in out of the list, and never shows on it.
"""

import collections
import re
import threading
import time

# Senders as the limits count them: an IPv6 /64 is one (a home's or a server's whole network).
from opendmt3.server.services import limits

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
    """The launchers that signed in, by their PC's sender and the account (rows), and the senders of calls that named a
    launcher without a sign-in (a count)."""

    def __init__(self, clock=time.time):
        self._clock, self._lock, self._seen = clock, threading.Lock(), {}
        # Senders of unsigned calls -> when last heard, the one heard longest ago first (dropped first past MOST).
        self._anonymous = collections.OrderedDict()
        # When this server began to listen: what "since" means on the page and in the API.
        self.since = int(clock())

    def heard(self, address, version, account=None):
        """A call from a launcher: its address, its version, and the account's row when the call was signed (a row of
        its own then; else its sender counted, nothing more)."""
        now = self._clock()
        sender = limits.sender(address)
        with self._lock:
            if account is None:
                # Heard now: last to be dropped.
                self._anonymous.pop(sender, None)
                self._anonymous[sender] = now
                self._trim(now)
                return
            key = (sender, account["login_id"])
            entry = self._seen.get(key)
            if entry is None:
                entry = self._seen[key] = {"first_seen": int(now), "calls": 0}
            # The address it came from last (one of its /64's), its version and its account.
            entry.update(address=str(address), version=str(version), last_seen=int(now), calls=entry["calls"] + 1,
                         login_id=account["login_id"], dj_name=account["dj_name"], player=account["id"])
            # The PC said whose launcher it is: its calls before the sign-in are no anonymous one any more.
            self._anonymous.pop(sender, None)
            self._trim(now)

    def _trim(self, now):
        """Those not heard for KEPT go, then the oldest heard past MOST, of each kind apart (under the lock)."""
        for key in [k for k, e in self._seen.items() if now - e["last_seen"] > KEPT]:
            del self._seen[key]
        if len(self._seen) > MOST:
            for key, _ in sorted(self._seen.items(), key=lambda item: item[1]["last_seen"])[:len(self._seen) - MOST]:
                del self._seen[key]
        while self._anonymous and (len(self._anonymous) > MOST or now - next(iter(self._anonymous.values())) > KEPT):
            # The one heard longest ago first: past MOST, or not heard for KEPT.
            self._anonymous.popitem(last=False)

    def view(self):
        """Every launcher that signed in, kept, the one heard last first: address, version, first_seen, last_seen,
        calls, now (heard within NOW), and the account (login_id, dj_name, player)."""
        now = self._clock()
        with self._lock:
            self._trim(now)
            rows = [dict(e) for e in self._seen.values()]
        for row in rows:
            row["now"] = now - row["last_seen"] <= NOW
        return sorted(rows, key=lambda r: -r["last_seen"])

    def anonymous(self):
        """The calls that named a launcher without a sign-in, as a count: {"count": senders heard within KEPT (MOST at
        most), "now": those heard within NOW}."""
        now = self._clock()
        with self._lock:
            self._trim(now)
            heard = list(self._anonymous.values())
        return {"count": len(heard), "now": sum(1 for at in heard if now - at <= NOW)}
