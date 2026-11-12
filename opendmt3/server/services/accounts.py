"""Accounts: an ID and a password for the site and the launcher, a DJ name, and a card number for the game.

The game logs players in by card: the launcher's stand-in card reader hands it the account's card number (20
random digits), which the launcher gets by signing in with the ID and password. A new password also gives the
account a new card, so a card number copied off a PC stops working with the password it came with.

The stored secret is a slow hash (PBKDF2-SHA256) of the password's MD5 as hex text, the form the game's own ID
login sends (this build never shows that login, but the stored form already fits it), so the database does not
give away passwords. Card numbers are kept as they are, because the game sends them as they are: like a real
card, a card number alone logs in to the game, so the database stays private to the server.
"""

import hashlib
import hmac
import os
import re
import secrets
import threading
import time

from opendmt3.core.errors import Worded
from opendmt3.server import db
# What the site's lists of everyone's plays are made of changes with a player's name, card, state or account: counted
# there, so the lists made before are made again (services/records.py, web/cache.py).
from opendmt3.server.services.records import changed

# The game's ID field (in its ID login) is 8 bytes of letters and digits.
ID_MAX = 8
ID_PATTERN = re.compile(r"^[A-Za-z0-9]{1,%d}$" % ID_MAX)
# A new password: at least as long as the sister project OpenDMTQ asks for (6), at most what the game's keypad
# login takes (16). Only new passwords are checked: an account made with a shorter one before keeps signing in.
PASSWORD_MIN, PASSWORD_MAX = 6, 16
DJ_NAME_MAX = 8                      # the game's DJ name field: 8 UTF-16 units and the closing zero
ITERATIONS = 200_000
CARD_DIGITS = 20


class AccountError(Worded, ValueError):
    """A request the account rules refuse, worded for the person who made it (errors.py)."""


def game_digest(password):
    """What the game sends for a password: its MD5 as lower-case hex."""
    return hashlib.md5(password.encode("ascii")).hexdigest()


def _hash(digest, salt=None, iterations=ITERATIONS):
    salt = salt or os.urandom(16)
    value = hashlib.pbkdf2_hmac("sha256", digest.lower().encode("ascii"), salt, iterations)
    return "pbkdf2_sha256$%d$%s$%s" % (iterations, salt.hex(), value.hex())


def _matches(stored, digest):
    try:
        _, iterations, salt, value = stored.split("$")
    except ValueError:
        return False
    again = _hash(digest, bytes.fromhex(salt), int(iterations)).split("$")[3]
    # A constant-time comparison, so the time taken says nothing about how close a guess was.
    return hmac.compare_digest(again, value)


def check_id(login_id):
    if not ID_PATTERN.match(login_id or ""):
        raise AccountError("an ID is 1 to %d letters or digits (what the game's keypad can type)" % ID_MAX,
                           "error.account.id", max=ID_MAX)


def check_password(password):
    if not (PASSWORD_MIN <= len(password or "") <= PASSWORD_MAX) or not password.isascii() or not password.isalnum():
        raise AccountError("a password is %d to %d letters or digits" % (PASSWORD_MIN, PASSWORD_MAX),
                           "error.account.password", min=PASSWORD_MIN, max=PASSWORD_MAX)


def check_dj_name(name):
    """A DJ name the game can show: 1 to 8 places in its UTF-16 field, no control characters."""
    # Counted the way the game stores it: a character outside the basic plane (an emoji) takes two places.
    if not name or len(name.encode("utf-16-le")) // 2 > DJ_NAME_MAX or not name.isprintable():
        raise AccountError("a DJ name is 1 to %d characters" % DJ_NAME_MAX, "error.account.dj", max=DJ_NAME_MAX)


def _last_admin(login_id):
    """The refusal to disable the server's only enabled admin or take its rights: nobody could sign in to the admin
    pages after it (Accounts.set_admin, Accounts.set_disabled)."""
    return AccountError("the server needs an enabled admin, and %s is the only one" % login_id,
                        "error.account.last_admin", login_id=login_id)


_DUMMY = []
# Sign-ins are checked on several worker threads at once: the secret is made once, under this lock.
_DUMMY_LOCK = threading.Lock()


def _dummy_hash():
    """A stored secret no password matches, made once, to spend a check's time on an ID that does not exist."""
    with _DUMMY_LOCK:
        if not _DUMMY:
            _DUMMY.append(_hash(game_digest("no account has this")))
        return _DUMMY[0]


class Accounts:
    """Account rows in the server's database (openDMT3.sqlite)."""

    def __init__(self, db):
        self.db = db

    def _log(self, who, what):
        self.db.execute("INSERT INTO changes (at, who, what) VALUES (?, ?, ?)", (int(time.time()), who, what))

    def _new_card(self):
        """A card number no account has, of random digits."""
        while True:
            card = "".join(secrets.choice("0123456789") for _ in range(CARD_DIGITS))
            if not self.db.execute("SELECT 1 FROM accounts WHERE card = ?", (card,)).fetchone():
                return card

    def create(self, login_id, password, dj_name=None, is_admin=False, who="system"):
        check_id(login_id)
        check_password(password)
        name = (dj_name or login_id).strip()
        check_dj_name(name)
        # The slow hash first, so the write lock below is held for milliseconds, never for a hash.
        secret = _hash(game_digest(password))
        # The check that the ID is free and the account in one write transaction: two admins making the same ID at
        # once get one account and one "taken", never a failure of the database's own rule.
        with db.immediate(self.db):
            if self.by_login(login_id):
                raise AccountError("the ID %s is taken" % login_id, "error.account.taken", login_id=login_id)
            self.db.execute(
                "INSERT INTO accounts (login_id, password, dj_name, card, is_admin, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (login_id, secret, name, self._new_card(), int(bool(is_admin)), int(time.time())))
            self._log(who, "made the account %s" % login_id)
        # A new player in the lists of every player (the API's players with their cards).
        changed()
        return self.by_login(login_id)

    def by_login(self, login_id):
        return self.db.execute("SELECT * FROM accounts WHERE login_id = ?", (login_id,)).fetchone()

    def by_card(self, card):
        return self.db.execute("SELECT * FROM accounts WHERE card = ?", (card,)).fetchone()

    def all(self):
        return self.db.execute("SELECT * FROM accounts ORDER BY login_id").fetchall()

    def has_any(self):
        """True once the server has an account: a look at one row, where all() reads every one (the sign-in page asks
        on every visit whether the owner's first-run page comes first)."""
        return self.db.execute("SELECT 1 FROM accounts LIMIT 1").fetchone() is not None

    def check_game(self, login_id, digest):
        """A login from the game (ID and the MD5 hex it sent): ('ok', row), ('unknown', None),
        ('wrong_password', None) or ('disabled', None)."""
        row = self.by_login(login_id)
        if row is None:
            # As slow as a wrong password, so how long an answer takes does not tell which IDs exist.
            _matches(_dummy_hash(), digest)
            return "unknown", None
        if not _matches(row["password"], digest):
            return "wrong_password", None
        if row["disabled"]:
            return "disabled", None
        self.db.execute("UPDATE accounts SET last_login = ? WHERE id = ?", (int(time.time()), row["id"]))
        return "ok", row

    def check_web(self, login_id, password):
        """A sign-in on the site or from the launcher: the account, or None (the same answer for every failure).

        IDs match in any case (the column compares without it).
        """
        password = password or ""
        if not password.isascii():
            # No account has such a password (they are letters and digits); answered after the same wait.
            _matches(_dummy_hash(), game_digest("no account has this"))
            return None
        code, row = self.check_game((login_id or "").strip(), game_digest(password))
        return row if code == "ok" else None

    def set_password(self, login_id, password, who="system"):
        check_password(password)
        # A new card goes with the new password: a card file left on a PC stops logging in, and the launcher
        # fetches the new card when it signs in again.
        self.db.execute("UPDATE accounts SET password = ?, card = ? WHERE login_id = ?",
                        (_hash(game_digest(password)), self._new_card(), login_id))
        # The account's named API tokens end with it too, as its sign-ins and sign-in tokens do (services/tokens.py):
        # whoever made one with the old password keeps nothing.
        self.db.execute("DELETE FROM api_tokens WHERE account_id IN (SELECT id FROM accounts WHERE login_id = ?)",
                        (login_id,))
        self._log(who, "set a new password (and card) for %s" % login_id)

    def end_sign_ins(self, account_id):
        """End the account's sign-ins on the site (a sign-out): each sign-in cookie carries the account's round of
        sign-ins when it was made, and this starts the next round. The launcher's tokens do not carry it."""
        self.db.execute("UPDATE accounts SET session_generation = session_generation + 1 WHERE id = ?", (account_id,))

    def end_token(self, token_id, account_id, expires, now=None):
        """End one API token before its time (DELETE /api/v1/session: the launcher's Sign out), and no other: the
        account's other tokens (a launcher on another PC) go on. Its id (a hash of it, web/session.py) is kept until
        `expires`, the moment the token would have stopped working by itself; ids past theirs go now, so the table
        holds only the last 30 days' sign-outs."""
        now = int(now if now is not None else time.time())
        # Pruned as it goes: a token past its moment is refused for its age, so its id is no longer needed. Strictly
        # past it: within its last second the token's age still lets it through, so its id stays until then.
        self.db.execute("DELETE FROM revoked_tokens WHERE expires < ?", (now,))
        # The same token ended twice (a sign-out sent again) keeps its one row.
        self.db.execute("INSERT OR IGNORE INTO revoked_tokens (id, account_id, expires) VALUES (?, ?, ?)",
                        (token_id, account_id, int(expires)))

    def token_ended(self, token_id):
        """True when the API token of this id was ended before its time (end_token)."""
        return self.db.execute("SELECT 1 FROM revoked_tokens WHERE id = ?", (token_id,)).fetchone() is not None

    def set_dj_name(self, login_id, dj_name, who="system"):
        """The name the game shows on the DJ card and the site shows everywhere."""
        check_dj_name(dj_name)
        self.db.execute("UPDATE accounts SET dj_name = ? WHERE login_id = ?", (dj_name, login_id))
        # The rankings and the boards show the name.
        changed()
        self._log(who, "named %s %s" % (login_id, dj_name))

    def set_card(self, login_id, tables, icon=None, plate=None, pattern=None, comment=None, who="system"):
        """The DJ card's icon, title plate, pattern and comment (cards.py); what is None stays. `tables` are the
        game's card tables as read (cards.load): a number they lack is refused before anything changes."""
        from opendmt3.server.services import cards
        comment = comment.strip() if comment is not None else None
        cards.check(tables, icon=icon, plate=plate, pattern=pattern, comment=comment)
        fields = {k: v for k, v in (("icon", icon), ("plate", plate), ("pattern", pattern), ("comment", comment))
                  if v is not None}
        if not fields:
            return
        # Column names from the fixed list above, values as parameters.
        self.db.execute("UPDATE accounts SET %s WHERE login_id = ?" % ", ".join("%s = ?" % k for k in fields),
                        list(fields.values()) + [login_id])
        # The DJ page shows the card.
        changed()
        self._log(who, "changed the DJ card of %s (%s)" % (login_id, ", ".join(sorted(fields))))

    def leaves_no_admin(self, login_id):
        """True when the account is the server's only enabled admin: taking its admin rights, or disabling it, would
        leave nobody who can sign in to the admin pages."""
        row = self.by_login(login_id)
        if row is None or not row["is_admin"] or row["disabled"]:
            # Not an enabled admin: the enabled admins stay as many as they are.
            return False
        return not self.db.execute("SELECT 1 FROM accounts WHERE is_admin = 1 AND disabled = 0 AND id != ?",
                                   (row["id"],)).fetchone()

    def set_admin(self, login_id, is_admin, who="system"):
        """Give an account the admin pages, or take them away. Never from the only enabled admin (leaves_no_admin):
        AccountError then, and nothing changes. True once done; False for an ID no account has."""
        if not is_admin and self.leaves_no_admin(login_id):
            raise _last_admin(login_id)
        # The guard again in the change itself, so two admins taking each other's rights at once cannot both win.
        cursor = self.db.execute(
            "UPDATE accounts SET is_admin = ? WHERE login_id = ? AND (? OR disabled = 1 OR is_admin = 0 OR EXISTS ("
            " SELECT 1 FROM accounts AS other WHERE other.is_admin = 1 AND other.disabled = 0"
            " AND other.id != accounts.id))", (int(bool(is_admin)), login_id, int(bool(is_admin))))
        if not cursor.rowcount:
            if self.by_login(login_id) is not None:
                # The account is there: the other admin's change took the last other rights in the meantime.
                raise _last_admin(login_id)
            # No such account: nothing changed.
            return False
        self._log(who, ("gave admin rights to %s" if is_admin else "took admin rights from %s") % login_id)
        return True

    def set_disabled(self, login_id, disabled, who="system"):
        """Disable an account (it cannot log in at the cabinet or sign in, and leaves the rankings), or enable it
        again. Never the only enabled admin (leaves_no_admin): AccountError then, and nothing changes."""
        if disabled and self.leaves_no_admin(login_id):
            raise _last_admin(login_id)
        # The guard again in the change itself, as in set_admin: two admins disabling each other at once cannot both
        # win. Enabling, or disabling an account that is not an enabled admin, always goes through.
        cursor = self.db.execute(
            "UPDATE accounts SET disabled = ? WHERE login_id = ? AND (? = 0 OR is_admin = 0 OR disabled = 1 OR EXISTS ("
            " SELECT 1 FROM accounts AS other WHERE other.is_admin = 1 AND other.disabled = 0"
            " AND other.id != accounts.id))", (int(bool(disabled)), login_id, int(bool(disabled))))
        if not cursor.rowcount:
            if self.by_login(login_id) is not None:
                # The account is there: it became the last enabled admin in the meantime.
                raise _last_admin(login_id)
            # No such account: nothing changed, so nothing goes into the change log either.
            return
        # A disabled player leaves everything that shows other players (and comes back when enabled).
        changed()
        self._log(who, "%s the account %s" % ("disabled" if disabled else "enabled", login_id))

    def delete(self, login_id, who="system"):
        self.db.execute("DELETE FROM accounts WHERE login_id = ?", (login_id,))
        # Its plays go with it (ON DELETE CASCADE).
        changed()
        self._log(who, "deleted the account %s" % login_id)
