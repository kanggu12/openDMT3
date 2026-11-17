"""What an admin controls of a player in the game, and the player's own picture on the site.

The game reads a player's details at each card login (0x65, messages.user_info) and shows, beside what the DJ card
holds (services/cards.py): the level its own table gives the experience, and the MAX points, the game's currency,
beside the name on the song select. The game earns MAX points as it plays and reports what a session earned (0x79,
stage_points below); nothing in the client spends them (they were spent on the arcade's online service), so the
server keeps the balance and an admin sets it, adds to it, or makes it unlimited (the game then shows the most).

The level is the experience of the stages cleared (cards.experience) with the admin's change on top (exp_extra), so a
level an admin sets stays as the player goes on playing, and grows from there. A ban is a disabled account (the game
refuses its card, the site and the launcher its sign-in) with the reason the player is shown when they sign in.

The picture is the site's own (the game shows only the icons of its table): a picture the player uploads is decoded,
cut to a square and encoded again here as a PNG of PICTURE_SIZE pixels, so nothing of the file that came (its
metadata, a script in an SVG, a second frame) is ever served.
"""

import io
import os

from opendmt3.core.errors import Worded
from opendmt3.server.services import accounts as acc
from opendmt3.server.services import files
from opendmt3.server.services.records import changed

# The most MAX points a balance holds: six digits, the width the song select showed (432098 on its screen).
POINTS_MOST = 999_999
# What the game is told of an unlimited balance: the most.
UNLIMITED_SHOWN = POINTS_MOST
# The most one change adds or takes (an admin's typing slip of an extra digit stays inside the balance's range).
POINTS_STEP_MOST = POINTS_MOST
# The most a card login may earn by its 0x79: the game's table gives at most 224 points a stage (ResultMaxPoint.csv,
# level 12 at S++), with buffs of up to 30 % on top; eight stages a login (server.STAGES_PER_LOGIN) of that, doubled
# for room, is 3,584. A larger claim is no session the game played: it is not kept.
EARNED_MOST = 4000
# The game's levels: 1 to 99 (expTitle.csv's rows).
LEVEL_MOST = 99
# A ban's reason, shown to the player on the site: one line of this many characters at most.
REASON_MAX = 120
# The player's picture: a square of this many pixels, from an upload of at most this many bytes and pixels.
PICTURE_SIZE = 256
PICTURE_UPLOAD_MOST = 2 * 1024 * 1024
PICTURE_PIXELS_MOST = 4096 * 4096
# The kinds of picture taken (by what Pillow finds in the bytes, never by the file's name).
PICTURE_FORMATS = ("PNG", "JPEG", "WEBP", "GIF")
# Where the pictures are kept in the data folder, one file per account by its number.
PICTURES = "pictures"


class PlayerError(Worded, ValueError):
    """A change the rules refuse, worded for whoever asked (errors.py)."""


# ------------------------------------------------------------------------------------------ what the game is sent

def _field(row, name, default=0):
    """A column of an account row, or `default` for a row from before step 9 (a test's own made-up row)."""
    return row[name] if name in row.keys() else default


def points_shown(row):
    """The MAX points the game shows for an account: its balance, or the most when it is unlimited."""
    return UNLIMITED_SHOWN if _field(row, "unlimited_points") else max(0, min(POINTS_MOST, _field(row, "max_points")))


def experience(row, earned):
    """The experience the game is sent: what the stages cleared earned, with the admin's change, never below 0."""
    return max(0, earned + _field(row, "exp_extra"))


def level_start(tables, level):
    """The least experience the game shows `level` for (cards.level: a level holds up to its row's experience), or None
    without the game's tables."""
    tops = tables.get("levels") or []
    if not tops:
        return None
    level = max(1, min(int(level), len(tops)))
    # Level 1 starts at 0; every other one just past the level before it.
    return 0 if level == 1 else tops[level - 2] + 1


# ------------------------------------------------------------------------------------------ the changes

def _whole(value, low, high):
    """`value` as a whole number from `low` to `high` (a form's text or JSON's number, never a float or a bool), or
    None when it is not one: the caller raises its own words."""
    if isinstance(value, bool):
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


def check_reason(reason):
    """A ban's reason: one line of 1 to REASON_MAX printable characters, as it is shown."""
    reason = (reason or "").strip()
    if not reason or len(reason) > REASON_MAX or not reason.isprintable():
        raise PlayerError("a reason is 1 to %d characters on one line" % REASON_MAX, "error.player.reason",
                          max=REASON_MAX)
    return reason


class Players:
    """The game's side of the accounts in the server's database: MAX points, the level, bans, the picture, and the
    change log of one player."""

    def __init__(self, db):
        self.db = db
        # The account rules (the last enabled admin, the log's lines) are the accounts' own.
        self.accounts = acc.Accounts(db)

    def _row(self, login_id):
        """The account, or PlayerError when there is none."""
        row = self.accounts.by_login(login_id)
        if row is None:
            raise PlayerError("no player with the ID %s" % login_id, "error.player.unknown", login_id=login_id)
        return row

    # ------------------------------------------------------------------------------ MAX points

    def set_points(self, login_id, amount, who="system"):
        """The balance set to `amount` (0 to POINTS_MOST)."""
        row = self._row(login_id)
        amount = _whole(amount, 0, POINTS_MOST)
        if amount is None:
            raise PlayerError("MAX points are 0 to %d" % POINTS_MOST, "error.player.points", most=POINTS_MOST)
        self.db.execute("UPDATE accounts SET max_points = ? WHERE id = ?", (amount, row["id"]))
        self.accounts._log(who, "set the MAX points of %s to %d" % (login_id, amount), login_id)
        return amount

    def add_points(self, login_ids, amount, who="system"):
        """`amount` added to (or, below 0, taken from) each account of `login_ids` (None: every account), each balance
        kept from 0 to POINTS_MOST. Returns how many accounts it reached."""
        amount = _whole(amount, -POINTS_STEP_MOST, POINTS_STEP_MOST)
        if amount is None or amount == 0:
            raise PlayerError("a change of MAX points is a whole number from -%d to %d, not 0" % (POINTS_STEP_MOST, POINTS_STEP_MOST),
                              "error.player.points.step", most=POINTS_STEP_MOST)
        if login_ids is None:
            rows = self.accounts.all()
        else:
            rows = [self._row(login_id) for login_id in login_ids]
        for row in rows:
            # Kept within the range in the change itself, so two changes at once cannot pass it.
            self.db.execute("UPDATE accounts SET max_points = MAX(0, MIN(?, max_points + ?)) WHERE id = ?",
                            (POINTS_MOST, amount, row["id"]))
            self.accounts._log(who, "%s %d MAX points %s %s" % ("gave" if amount >= 0 else "took", abs(amount),
                                                                  "to" if amount >= 0 else "from", row["login_id"]),
                               row["login_id"])
        return len(rows)

    def set_unlimited(self, login_id, on, who="system"):
        """Unlimited MAX points on (the game shows the most) or off (the balance again, which kept growing)."""
        row = self._row(login_id)
        self.db.execute("UPDATE accounts SET unlimited_points = ? WHERE id = ?", (int(bool(on)), row["id"]))
        self.accounts._log(who, "turned unlimited MAX points %s for %s" % ("on" if on else "off", login_id), login_id)

    def earned(self, account_id, points):
        """What a session earned by the game's own count (0x79), added to the balance; False when the claim is more
        than a login can earn (EARNED_MOST) and nothing was kept. Not in the change log: the plays are its record."""
        if not isinstance(points, int) or not 0 <= points <= EARNED_MOST:
            return False
        self.db.execute("UPDATE accounts SET max_points = MIN(?, max_points + ?) WHERE id = ?",
                        (POINTS_MOST, points, account_id))
        return True

    # ------------------------------------------------------------------------------ the level

    def set_level(self, login_id, level, tables, earned, who="system"):
        """The level the game shows set to `level` (1 to the game's last): the admin's change becomes what takes the
        experience the stages cleared earned (`earned`) to that level's start. PlayerError without the game's tables
        (the server cannot know the levels then)."""
        row = self._row(login_id)
        tops = tables.get("levels") or []
        if not tops:
            raise PlayerError("the server has no table of levels yet", "error.player.levels")
        top = len(tops)
        level = _whole(level, 1, top)
        if level is None:
            raise PlayerError("a level is 1 to %d" % top, "error.player.level", top=top)
        extra = level_start(tables, level) - earned
        self.db.execute("UPDATE accounts SET exp_extra = ? WHERE id = ?", (extra, row["id"]))
        # The DJ page and the lists show the level.
        changed()
        self.accounts._log(who, "set the level of %s to %d" % (login_id, level), login_id)
        return extra

    def clear_level(self, login_id, who="system"):
        """The admin's change taken away: the level is the stages cleared's again."""
        row = self._row(login_id)
        self.db.execute("UPDATE accounts SET exp_extra = 0 WHERE id = ?", (row["id"],))
        changed()
        self.accounts._log(who, "gave %s the level of their plays again" % login_id, login_id)

    # ------------------------------------------------------------------------------ bans

    def ban(self, login_id, reason, who="system"):
        """The account disabled with a reason: the game refuses its card, the site and the launcher its sign-in, and
        the player is told the reason when they sign in. Never the only enabled admin (AccountError)."""
        self._row(login_id)
        reason = check_reason(reason)
        # The account rules first (the last enabled admin stays): nothing changes when they refuse.
        self.accounts.set_disabled(login_id, True, who=who)
        self.db.execute("UPDATE accounts SET ban_reason = ? WHERE login_id = ?", (reason, login_id))
        self.accounts._log(who, "banned %s: %s" % (login_id, reason), login_id)
        return reason

    def unban(self, login_id, who="system"):
        """The ban lifted: the account enabled again, its reason gone."""
        self._row(login_id)
        # Enabling takes the reason away with it (accounts.set_disabled).
        self.accounts.set_disabled(login_id, False, who=who)

    # ------------------------------------------------------------------------------ the change log of one player

    def history(self, account_id, limit=50):
        """The newest changes made to the account (at, who, what), newest first."""
        return self.db.execute("SELECT at, who, what FROM changes WHERE account_id = ? ORDER BY id DESC LIMIT ?",
                               (account_id, int(limit))).fetchall()

    # ------------------------------------------------------------------------------ the picture

    def set_picture(self, login_id, who="system"):
        """A new picture kept for the account (save_picture): its count goes up, so its address is new."""
        row = self._row(login_id)
        self.db.execute("UPDATE accounts SET picture = picture + 1 WHERE id = ?", (row["id"],))
        changed()
        self.accounts._log(who, "changed the picture of %s" % login_id, login_id)
        return self._row(login_id)["picture"]

    def clear_picture(self, login_id, data_dir, who="system"):
        """The account's picture taken away (its file too)."""
        row = self._row(login_id)
        self.db.execute("UPDATE accounts SET picture = 0 WHERE id = ?", (row["id"],))
        path = picture_path(data_dir, row["id"])
        if os.path.exists(path):
            os.remove(path)
        changed()
        self.accounts._log(who, "removed the picture of %s" % login_id, login_id)


# ------------------------------------------------------------------------------------------ the picture's file

def picture_path(data_dir, account_id):
    """Where an account's picture is kept (whether it is there or not)."""
    return os.path.join(data_dir, PICTURES, "%d.png" % int(account_id))


def picture_too_large():
    """The refusal of an upload past PICTURE_UPLOAD_MOST (raised by the upload's reader as the bytes pass it)."""
    mb = PICTURE_UPLOAD_MOST >> 20
    return PlayerError("a picture is up to %d MB" % mb, "error.player.picture.size", mb=mb)


def make_picture(data):
    """An uploaded picture as the site keeps it: a square PNG of PICTURE_SIZE pixels, cut from its middle, made of its
    pixels alone (its first frame). PlayerError when it is not a picture of PICTURE_FORMATS, larger than its limits, or
    does not decode. Needs Pillow (pictures.available)."""
    from PIL import Image, ImageOps
    if len(data) > PICTURE_UPLOAD_MOST:
        raise picture_too_large()
    try:
        with Image.open(io.BytesIO(data)) as picture:
            # The kind by the bytes themselves; a file named .png that is something else is refused here.
            if picture.format not in PICTURE_FORMATS:
                raise PlayerError("not a picture", "error.player.picture.kind")
            width, height = picture.size
            # The size from the header alone, before a byte of the pixels is decoded (a crafted header claims much).
            if width < 1 or height < 1 or width * height > PICTURE_PIXELS_MOST:
                raise PlayerError("a picture is up to %d pixels in all" % PICTURE_PIXELS_MOST,
                                  "error.player.picture.pixels", most=PICTURE_PIXELS_MOST)
            # The first frame of an animation, turned as its camera said, in colour with its transparency.
            picture.seek(0)
            turned = ImageOps.exif_transpose(picture)
            rgba = turned.convert("RGBA")
    except PlayerError:
        raise
    except Exception as e:  # noqa: BLE001  (Pillow raises many kinds for a broken picture; each is one refusal)
        raise PlayerError("not a picture", "error.player.picture.kind") from e
    # The middle square, made the kept size.
    square = ImageOps.fit(rgba, (PICTURE_SIZE, PICTURE_SIZE), Image.LANCZOS)
    # A new picture from the pixels alone: no metadata of the upload is carried over.
    clean = Image.frombytes("RGBA", square.size, square.tobytes())
    out = io.BytesIO()
    clean.save(out, "PNG")
    return out.getvalue()


def save_picture(data_dir, account_id, png):
    """Keep a picture made by make_picture for the account, replacing the last one at once (never half-written)."""
    path = picture_path(data_dir, account_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Never through a link left at the name (files.open_new), then moved over the old one.
    with files.open_new(path + ".new") as f:
        f.write(png)
    os.replace(path + ".new", path)
