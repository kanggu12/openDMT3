"""A made-up history for the load test: a song list, players, cabinets, play sessions and plays, written through the
server's own schema into a data folder before the server starts. No game files: the songs are numbers with made-up
titles.

As a server's history grows: players' activity and the songs' popularity fall off like a power law (a few play most),
the modes as players choose them (STAR 45 %, POP 40 %, CLUB 10 %, the crew modes 5 %), patterns 1 to 4, scores that
rise with a player's skill, three stages a session, spread over half a year. The same seed makes the same history.

  python tests/e2e/load/history.py DATA_DIR [--plays 300000] [--players 1000]
"""

import argparse
import json
import os
import random
import sys
import time

# Run from the repository root (python tests/e2e/load/history.py).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from opendmt3.server import db  # noqa: E402

SONGS = 180                 # about as many as the game's song list
CABINETS = 60               # cabinets the history was played on
DAYS = 180                  # how far back the history goes
MODES, MODE_WEIGHTS = (0, 1, 2, 3, 4), (45, 40, 10, 3, 2)


def song_list(data):
    """A song list of SONGS made-up songs (the server's catalog.json form), so the server checks results and sends
    first places as it does with a real one."""
    with open(os.path.join(data, "catalog.json"), "w") as f:
        json.dump({"songs": [{"number": n, "title": "Song %d" % n, "composer": "Nobody"} for n in range(1, SONGS + 1)]},
                  f)


def make(data, plays=300000, players=1000, secret=None, seed=42):
    """Write the history into the database in `data` (made or upgraded by the server's own code): `players` accounts
    named H0000 and on (all with the one stored `secret`, a hash made by the caller: they never sign in), and `plays`
    plays. Returns how many plays the database has."""
    song_list(data)
    rng = random.Random(seed)
    connection = db.connect(os.path.join(data, "openDMT3.sqlite"))
    try:
        now = int(time.time())
        start = now - DAYS * 86400
        connection.execute("BEGIN")
        first = connection.execute("SELECT COALESCE(MAX(id), 0) FROM accounts").fetchone()[0] + 1
        connection.executemany(
            "INSERT INTO accounts (login_id, password, dj_name, card, created_at, last_login)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [("H%04d" % i, secret, "DJ H%04d" % i, "9%019d" % i, start, now - rng.randrange(7 * 86400))
             for i in range(players)])
        hosts = ["10.1.%d.%d" % (c // 200, c % 200 + 10) for c in range(CABINETS)]
        connection.executemany(
            "INSERT OR IGNORE INTO cabinets (machine_key, name, version, address, first_seen, last_seen)"
            " VALUES (?, ?, ?, ?, ?, ?)", [(h, None, "1.0", h, start, now - rng.randrange(3600)) for h in hosts])
        ids = list(range(first, first + players))
        # A few play most: the k-th most active player plays about 1/k^0.9 as much as the first.
        activity = [1.0 / (k + 1) ** 0.9 for k in range(players)]
        popularity = [1.0 / (k + 1) ** 0.8 for k in range(SONGS)]
        skill = {a: rng.uniform(0.3, 1.0) for a in ids}
        session = connection.execute("SELECT COALESCE(MAX(id), 0) FROM sessions").fetchone()[0]
        sessions, rows = [], []
        for n in range(0, plays, 3):
            player = rng.choices(ids, activity)[0]
            at = start + rng.randrange(DAYS * 86400)
            session += 1
            sessions.append((session, rng.choice(hosts), player, at, at + 600))
            mode = rng.choices(MODES, MODE_WEIGHTS)[0]
            for k in range(min(3, plays - n)):
                song = rng.choices(range(1, SONGS + 1), popularity)[0]
                pattern = rng.randint(1, 4)
                score = int(min(300000, max(1000, rng.gauss(skill[player] * 260000, 25000))))
                rows.append((player, hosts[0], mode, song, pattern, score, "0,0,0,0,0,0,0", bytes(47),
                             at + 120 * k, session))
        connection.executemany("INSERT INTO sessions (id, cabinet, account_id, started_at, ended_at)"
                               " VALUES (?, ?, ?, ?, ?)", sessions)
        connection.executemany("INSERT INTO plays (account_id, cabinet, mode, song, pattern, score, counts, record,"
                               " played_at, session_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        connection.execute("COMMIT")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return connection.execute("SELECT COUNT(*) FROM plays").fetchone()[0]
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("data")
    parser.add_argument("--plays", type=int, default=300000)
    parser.add_argument("--players", type=int, default=1000)
    args = parser.parse_args()
    from opendmt3.server.services import accounts
    os.makedirs(args.data, exist_ok=True)
    started = time.monotonic()
    secret = accounts._hash(accounts.game_digest("never signs in"))
    total = make(args.data, args.plays, args.players, secret)
    print("%d plays in %s (%.1f s)" % (total, args.data, time.monotonic() - started))


if __name__ == "__main__":
    main()
