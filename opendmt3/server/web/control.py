"""What the admin's page of one player and its API twins both show and do (services/players.py for the rules): a
player's whole state as the game and the site see it, and each change an admin makes to it in the game.

Every function takes the Site and runs on a worker thread (the pages and the API hand them over), on the request's
own connection to the database.
"""

import os

from opendmt3.server.services import accounts as acc
from opendmt3.server.services import cards
from opendmt3.server.services import catalog as cat
from opendmt3.server.services import players as pl
from opendmt3.server.services import profile
from opendmt3.server.services import records as rec

# The newest plays and changes the player's page lists.
RECENT = 8
HISTORY = 40
# The changes an admin makes here, by the name the page's forms and the API give them.
ACTIONS = ("points_set", "points_add", "unlimited_on", "unlimited_off", "level_set", "level_clear", "ban", "unban",
           "card", "picture_clear")


def earned(connection, data_dir, row):
    """The experience the account's cleared stages earned, before the admin's change (cards.experience)."""
    return cards.experience(cards.load(data_dir), cat.load(data_dir), rec.Records(connection).cleared(row["id"]))


def state(site, login_id):
    """Everything the player's page and GET /api/v1/players/{login_id} show of an account, or None without one: the
    account, its DJ card as the game draws it, the level and where it comes from, the MAX points, the ban, the picture,
    its plays (how many, the newest) and the changes made to it (newest first)."""
    connection = site.connect()
    try:
        row = acc.Accounts(connection).by_login(login_id)
        if row is None:
            return None
        tables = cards.load(site.data_dir)
        plays_earned = earned(connection, site.data_dir, row)
        card = profile.card(connection, site.data_dir, row)
        store = rec.Records(connection)
        summary = store.summary(row["id"])
        recent = [profile.play(cat.load(site.data_dir), r) for r in store.recent(row["id"], RECENT)]
        history = [{"at": r["at"], "who": r["who"], "what": r["what"]} for r in pl.Players(connection).history(row["id"],
                                                                                                         HISTORY)]
    finally:
        connection.close()
    return {"login_id": row["login_id"], "dj_name": row["dj_name"], "player": row["id"],
            "is_admin": bool(row["is_admin"]), "disabled": bool(row["disabled"]),
            "banned": bool(row["disabled"]) and row["ban_reason"] is not None, "ban_reason": row["ban_reason"],
            "created_at": row["created_at"], "last_login": row["last_login"],
            # The card's last four digits: enough to tell it from another, never enough to log in with.
            "card_end": (row["card"] or "")[-4:],
            "dj_card": card, "exp_plays": plays_earned, "exp_extra": row["exp_extra"],
            "max_points": row["max_points"], "unlimited_points": bool(row["unlimited_points"]),
            "points_shown": pl.points_shown(row), "levels": len(tables.get("levels") or []),
            "picture": row["picture"], "summary": dict(summary), "recent": recent, "history": history}


def change(site, who, login_id, action, values):
    """One of ACTIONS made to the account by an admin (`who` names them in the change log), with what the form or the
    JSON body gave (`values`, a dict of its fields). Returns the notice's key and its values. PlayerError, AccountError
    or CardError when the rules refuse it; nothing changes then."""
    connection = site.connect()
    try:
        store = pl.Players(connection)
        row = store._row(login_id)
        if action == "points_set":
            amount = store.set_points(login_id, values.get("amount"), who=who)
            return "player.done.points", {"n": amount}
        if action == "points_add":
            store.add_points([login_id], values.get("amount"), who=who)
            return "player.done.points", {"n": store._row(login_id)["max_points"]}
        if action in ("unlimited_on", "unlimited_off"):
            store.set_unlimited(login_id, action == "unlimited_on", who=who)
            return "player.done." + action, {}
        if action == "level_set":
            store.set_level(login_id, values.get("level"), cards.load(site.data_dir),
                            earned(connection, site.data_dir, row), who=who)
            return "player.done.level", {"n": int(str(values.get("level")).strip())}
        if action == "level_clear":
            store.clear_level(login_id, who=who)
            return "player.done.level_clear", {}
        if action == "ban":
            reason = store.ban(login_id, values.get("reason"), who=who)
            return "player.done.ban", {"reason": reason}
        if action == "unban":
            store.unban(login_id, who=who)
            return "player.done.unban", {}
        if action == "card":
            # The DJ card by the player's own rules (cards.check): a number the game has no picture for is refused.
            store.accounts.set_card(login_id, cards.load(site.data_dir), icon=_number(values.get("icon")),
                                    plate=_number(values.get("plate")), pattern=_number(values.get("pattern")),
                                    comment=None if values.get("comment") is None else str(values.get("comment")),
                                    who=who)
            return "player.done.card", {}
        if action == "picture_clear":
            store.clear_picture(login_id, site.data_dir, who=who)
            return "player.done.picture_clear", {}
        raise pl.PlayerError("there is no change named %s" % action, "error.player.action", action=action)
    finally:
        connection.close()


def _number(value):
    """A choice's number as a form or JSON gives it: a whole number, or None when it is not given (left as it is). A
    value that is no number stays as it came, for cards.check to refuse in words."""
    if value is None or value == "":
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    text = str(value).strip()
    return int(text) if text.isdigit() else value


def picture_file(site, player):
    """The path of a player's picture by their account number, or None (no picture, or a disabled account's)."""
    connection = site.connect()
    try:
        row = connection.execute("SELECT picture, disabled FROM accounts WHERE id = ?", (player,)).fetchone()
    finally:
        connection.close()
    if row is None or not row["picture"] or row["disabled"]:
        return None
    path = pl.picture_path(site.data_dir, player)
    return path if os.path.isfile(path) else None


def ban_note(site, login_id, password):
    """The reason a banned account's sign-in is refused, said only to whoever knows its password (a sign-in that
    failed: the check in accounts.check_web answers the same for every failure), else None. Only a banned account's
    password is checked again here."""
    connection = site.connect()
    try:
        store = acc.Accounts(connection)
        row = store.by_login((login_id or "").strip())
        if row is None or not row["disabled"] or row["ban_reason"] is None:
            return None
        if not (password or "").isascii():
            return None
        # The password's own check, as the game's login makes it (a disabled account's answer is "disabled" only for
        # the right password).
        code, _ = store.check_game(row["login_id"], acc.game_digest(password))
        return row["ban_reason"] if code == "disabled" else None
    finally:
        connection.close()
