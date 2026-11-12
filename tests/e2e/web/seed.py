"""Made-up site data for the web layout check (tests/e2e/web/run.sh): five accounts, a catalog of invented songs, backups of
every kind, a made-up installer, a notice of the longest length, maintenance on, and the admin's API tokens with the
longest names.

    python tests/e2e/web/seed.py DATA_DIR      (inside the server image: the package is importable there)

BOSS is the admin; every password is pass1234. The names and titles are the widest the layout must take: a long
Korean DJ name, eight W's, a song title that wraps over lines, one in Korean, one never played. Nothing here comes
from the game.
"""

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
    # Made-up DJ card pictures and tables (cards.py's shape): coloured plates with their numbers, six icons, five
    # plates, four patterns, and the level steps. BOSS (the signed-in admin) and HANA wear a full card.
    from opendmt3.server.services import cards
    choices = {"icon": [1, 2, 3, 4, 5, 6], "plate": [32768, 32769, 32770, 32771, 32772], "pattern": [0, 1, 2, 3]}
    for kind, numbers in choices.items():
        os.makedirs(os.path.join(data, cards.FOLDER, kind), exist_ok=True)
        for i, number in enumerate(numbers):
            size = (104, 64) if kind == "icon" else (204, 64)
            # A pattern is drawn over a plate: a see-through stripe; icons and plates are solid.
            picture = Image.new("RGBA", size, (0, 0, 0, 0) if kind == "pattern" else (40 + 40 * i, 90, 200 - 30 * i, 255))
            draw = ImageDraw.Draw(picture)
            if kind == "pattern":
                draw.rectangle((0, 24 + 4 * i, size[0], 36 + 4 * i), fill=(255, 179, 61, 160))
            draw.text((8, 8), str(number), fill=(255, 255, 255, 255))
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
    print("seeded %d accounts, %d songs" % (len(ids), len(songs)))


if __name__ == "__main__":
    main(sys.argv[1])
