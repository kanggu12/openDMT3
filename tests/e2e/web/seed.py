"""Made-up site data for the web layout check (tests/e2e/web/run.sh): five accounts, a catalog of invented songs, backups of
every kind, a made-up installer, a notice of the longest length, maintenance on, and the admin's API tokens with the
longest names.

    python tests/e2e/web/seed.py DATA_DIR      (inside the server image: the package is importable there)

BOSS is the admin; every password is pass1234. The names and titles are the widest the layout must take: a long
Korean DJ name, eight W's, a song title that wraps over lines, one in Korean, one never played. Nothing here comes
from the game.
"""

import io
import json
import os
import random
import sys
import time

from opendmt3.server import db
from opendmt3.server.services import accounts, activity, records


def main(data):
    os.makedirs(data, exist_ok=True)
    connection = db.connect(os.path.join(data, "openDMT3.sqlite"))
    store = accounts.Accounts(connection)
    # Login ID, DJ name, admin.
    people = [("BOSS", "BOSS", True), ("NOVA", "DJ NOVA", False), ("RIO", "RIO", False),
              ("HANA", "가나다라마바사아", False), ("WWWWWWWW", "WWWWWWWW", False)]
    ids = {login: store.create(login, "pass1234", dj, is_admin=admin)["id"] for login, dj, admin in people}
    songs = [{"number": n, "name": "madeup%d" % n, "title": t, "genre": g, "composer": c, "star": [1 + n, 4 + n, 8 + n, 0],
              "pop": [2 + n, 5 + n, 9 + n, 12]} for n, t, c, g in (
        (1, "Made-up Opening Track", "Composer A", "Trance"),
        (2, "Another Invented Song", "Composer B", "Pop"),
        (3, "가상의 노래 제목", "작곡가 C", "Ballad"),
        (4, "An Extremely Long Made-up Song Title That Wraps Over Lines (Extended Mix)", "Composer D", "Rock"),
        (5, "Unplayed Example", "Composer E", "House"))]
    with open(os.path.join(data, "catalog.json"), "w", encoding="utf-8") as f:
        json.dump({"songs": songs}, f, ensure_ascii=False)
    # Made-up disc pictures for four of the five songs: a coloured disc with the song's number.
    from PIL import Image, ImageDraw
    os.makedirs(os.path.join(data, "jackets"), exist_ok=True)
    for number, colour in ((1, (60, 110, 255)), (2, (255, 79, 160)), (3, (180, 240, 42)), (4, (255, 179, 61))):
        disc = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
        draw = ImageDraw.Draw(disc)
        draw.ellipse((4, 4, 156, 156), fill=colour + (255,))
        draw.ellipse((62, 62, 98, 98), fill=(16, 19, 23, 255))
        draw.text((74, 30), str(number), fill=(16, 19, 23, 255))
        disc.save(os.path.join(data, "jackets", "%d.png" % number))
    # Made-up DJ card pictures and tables (cards.py's shape): six icons, five plates, four patterns, and the level
    # steps. BOSS (the signed-in admin) and HANA wear a full card. The pictures carry no words or numbers: a pattern
    # is drawn over its plate and the comment over both, so a number in each would stand one over another (a
    # pattern's 3 over a plate's 32770); each is told from the others by its colour and shape alone.
    from opendmt3.server.services import cards
    choices = {"icon": [1, 2, 3, 4, 5, 6], "plate": [32768, 32769, 32770, 32771, 32772], "pattern": [0, 1, 2, 3]}
    for kind, numbers in choices.items():
        os.makedirs(os.path.join(data, cards.FOLDER, kind), exist_ok=True)
        for i, number in enumerate(numbers):
            size = (104, 64) if kind == "icon" else (204, 64)
            picture = Image.new("RGBA", size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(picture)
            if kind == "icon":
                # An emblem: a disc of its own colour on a darker square.
                colour = (60 + 30 * i, 120 + 15 * i, 230 - 30 * i)
                draw.rectangle((0, 0, size[0] - 1, size[1] - 1), fill=tuple(c // 3 for c in colour) + (255,))
                draw.ellipse((34, 14, 70, 50), fill=colour + (255,))
            elif kind == "plate":
                # A plate: its colour, a lighter band over its top third as a plate's sheen.
                colour = (40 + 40 * i, 90, 200 - 30 * i)
                draw.rectangle((0, 0, size[0] - 1, size[1] - 1), fill=colour + (255,))
                draw.rectangle((0, 0, size[0] - 1, 20), fill=tuple(min(255, c + 40) for c in colour) + (255,))
            elif number:
                # A pattern is seen over a plate: a see-through stripe at its own height (pattern 0 is none: the plate
                # alone, so its picture is empty).
                draw.rectangle((0, 24 + 4 * i, size[0], 36 + 4 * i), fill=(255, 179, 61, 160))
            picture.save(os.path.join(data, cards.FOLDER, kind, "%d.png" % number))
    with open(os.path.join(data, cards.FILE), "w", encoding="utf-8") as f:
        json.dump(dict({k: [{"number": n, "grade": "S" if n % 2 else ""} for n in v] for k, v in choices.items()},
                       points={"1": 9, "2": 9, "3": 10, "4": 10, "5": 10, "6": 10, "7": 11, "8": 11, "9": 12,
                               "10": 12, "11": 13, "12": 13},
                       levels=[12, 42, 92, 162, 252, 362, 492, 642, 812, 1002]), f)
    for login, card in (("BOSS", (3, 32770, 2, "가나다라마바사아자차카타")), ("HANA", (6, 32772, 3, "WWWWWWWWWWWW"))):
        store.set_card(login, cards.load(data), icon=card[0], plate=card[1], pattern=card[2], comment=card[3])
    # A song list as the launcher saves it, from this made-up data: the Song list tab's upload takes it (run.sh hands
    # it to the browser).
    from opendmt3.server.services import songlist
    songlist.save(data, os.path.join(data, songlist.NAME),
                  {"songs": len(songs), "jackets": 4, "cards": {k: len(v) for k, v in choices.items()}, "missing": {},
                   "reasons": {}})
    plays = records.Records(connection)
    act = activity.Activity(connection)
    # Two cabinets (documentation addresses), one with a long name.
    act.seen("198.51.100.7", "test", "198.51.100.7:50000", at=1762560000)
    act.seen("198.51.100.8", "test", "198.51.100.8:50000", at=1762560000)
    act.rename_cabinet(act.cabinets()[-1]["id"], "A cabinet with a long name")
    # A fixed seed: the same plays on every run, so two runs' screenshots compare. Each player plays over the last
    # ten weeks up to today, a few minutes' session (a credit) per cleared stage, on one of the two cabinets.
    rng = random.Random(3)
    now = int(time.time())
    for login in ids:
        host = rng.choice(["198.51.100.7", "198.51.100.8"])
        for song in (1, 2, 3, 4):
            for pattern in (1, 2, 3):
                if rng.random() < 0.7:
                    for _ in range(rng.randint(1, 3)):
                        at = now - rng.randint(0, 70 * 86400)
                        session = act.start(host, ids[login], at=at - 240)
                        plays.add(ids[login], host + ":50000", rng.choice([0, 0, 1]),
                                  {"song": song, "pattern": pattern, "score": rng.randint(300000, 1000000),
                                   "counts": [0] * 7, "raw": bytes(47)}, at=at, session_id=session)
                        act.end(session, host, at=at + 30)
    # What an admin controls of a player and what a player decorates (services/players.py): HANA with a picture of
    # their own (drawn here), MAX points and a level an admin set; RIO banned with a long made-up reason in Korean.
    from opendmt3.server.services import players
    control = players.Players(connection)
    face = Image.new("RGB", (320, 240), (40, 90, 200))
    ImageDraw.Draw(face).ellipse((100, 60, 220, 180), fill=(255, 179, 61))
    out = io.BytesIO()
    face.save(out, "JPEG")
    players.save_picture(data, ids["HANA"], players.make_picture(out.getvalue()))
    control.set_picture("HANA", who="HANA")
    control.set_points("HANA", 432098, who="BOSS")
    # The level from the plays' own experience (web/control.py, as the admin's page counts it), so the page says 7.
    from opendmt3.server.web import control as web_control
    control.set_level("HANA", 7, cards.load(data), earned=web_control.earned(connection, data, store.by_login("HANA")),
                      who="BOSS")
    control.ban("RIO", "가상의 사유입니다. 같은 카드로 여러 사람이 번갈아 기록을 올린 것으로 보여 이용을 잠시 멈춥니다.",
                who="BOSS")
    connection.close()
    # The admin's named API tokens: a name of the longest length and a Korean one, one of them used, so the Account
    # page lists them with their revoke questions.
    from opendmt3.server.services import tokens
    connection = db.connect(os.path.join(data, "openDMT3.sqlite"))
    try:
        boss = accounts.Accounts(connection).by_login("BOSS")
        named = tokens.Tokens(connection)
        used, _ = named.make(boss, "Made-up nightly backup script, long name", "write", who="BOSS")
        named.make(boss, "가나다라마바사아자차카타파하 순위 알림 봇", "read", who="BOSS")
        named.touch(dict(used, used_at=None))
    finally:
        connection.close()
    # Backups of every kind but daily, so the Backups tab has rows with their restore and delete questions: one made
    # now, one before a reset, and one uploaded (a copy of the first, checked as an upload is).
    from opendmt3.server.services import backups, maintenance, notice
    made = backups.make(os.path.join(data, "openDMT3.sqlite"), data, "manual")
    backups.make(os.path.join(data, "openDMT3.sqlite"), data, "reset")
    out, part = backups.upload_part(data)
    with out, open(os.path.join(backups.folder(data), made), "rb") as f:
        out.write(f.read())
    backups.keep_upload(data, part)
    # A made-up installer, so the Download page shows its size and date (not a Windows program: no version).
    os.makedirs(os.path.join(data, "downloads"), exist_ok=True)
    with open(os.path.join(data, "downloads", "openDMT3-win-Setup.exe"), "wb") as f:
        f.write(b"MZ" + bytes(3 * 1048576))
    # The notice at its longest (200 characters), Korean and Latin in one line, on every page of the run.
    line = "이번 주 일요일 오전에는 서버를 백업하느라 잠시 멈춥니다. Made-up notice for the layout check, as long as one can be. "
    notice.write(data, (line * 4)[:notice.MOST], who="BOSS")
    # Maintenance on, so every page shows its line beside the notice (the run turns it off and on again once a round).
    maintenance.write(data, True, who="BOSS")
    machine_day(data, rng, now)
    requests_day(data, rng, now)
    print("seeded %d accounts, %d songs" % (len(ids), len(songs)))


def machine_day(data, rng, now):
    """A made-up last day of the machine, as the server's sampler keeps it (services/machine.py): a point every five
    minutes, the processors busier in the evening when people play, memory a little up with them, the disk filling
    slowly, cabinets online in the evening, and an hour with no point (the server was stopped then), so the Status tab
    shows its charts with a gap."""
    from opendmt3.server.services import machine
    points = []
    for n in range(machine.KEEP):
        at = now - (machine.KEEP - 1 - n) * machine.POINT
        hour = time.localtime(at).tm_hour
        if 140 <= n < 152:
            # The hour the server was stopped: nothing kept.
            continue
        evening = 1.0 if 18 <= hour <= 23 else (0.4 if 12 <= hour < 18 else 0.1)
        cpu = round(4 + 30 * evening + rng.random() * 6, 1)
        points.append({"at": at, "cpu": cpu, "peak": round(min(100, cpu * (1.6 + rng.random())), 1),
                       "memory": round(34 + 8 * evening + rng.random() * 2, 1),
                       "disk": round(61.0 + n * 0.004, 1), "cabinets": int(round(6 * evening))})
    with open(os.path.join(data, machine.FILE), "w", encoding="utf-8") as f:
        json.dump({"points": points}, f)


def requests_day(data, rng, now):
    """A made-up last day of the site's requests log (services/requestlog.py): the players' pages through the day,
    busier in the evening, the launcher's API calls, a few pages that are not there and a few sign-ins held back, from
    documentation addresses."""
    from opendmt3.server.services import requestlog
    pages = ["/", "/rankings", "/rankings?by=month", "/songs", "/songs/1", "/songs/4", "/dj/2", "/download", "/account"]
    who = ["NOVA", "RIO", "HANA", "WWWWWWWW", None]
    lines = []
    for slot in range(requestlog.SLOTS):
        start = now - (requestlog.SLOTS - slot) * requestlog.SLOT
        hour = time.localtime(start).tm_hour
        busy = 40 if 18 <= hour <= 23 else (12 if 9 <= hour < 18 else 2)
        for _ in range(rng.randint(busy // 2, busy)):
            at = start + rng.random() * requestlog.SLOT
            n = rng.random()
            # A page that is not there, a sign-in held back, the launcher's sign-in, or a player's page.
            if n < 0.06:
                method, path, status = "GET", "/old-page-%d" % rng.randint(1, 3), 404
            elif n < 0.09:
                method, path, status = "POST", "/signin", 429
            elif n < 0.3:
                method, path, status = "POST", "/api/v1/session", 200
            else:
                method, path, status = "GET", rng.choice(pages), 200
            lines.append({"at": round(at, 3), "method": method, "path": path, "status": status,
                          "ms": round(3 + rng.random() * 40, 1), "address": "198.51.100.%d" % rng.randint(2, 30),
                          "who": rng.choice(who) if status == 200 else None})
    lines.sort(key=lambda line: line["at"])
    os.makedirs(os.path.join(data, requestlog.FOLDER), exist_ok=True)
    with open(os.path.join(data, requestlog.FOLDER, requestlog.NAME), "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
