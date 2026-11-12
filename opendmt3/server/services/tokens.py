"""The API's named tokens: a player makes one on the Account page (or through the API) for a program of their own, with
a name that says what it is for and a scope, read (GET calls only) or write (read and write). The token is shown once;
the database keeps its SHA-256 only (table api_tokens, db step 7), so a lost token cannot be shown again: make another.

A token acts as its owner, with the owner's rights as they are at each call (web/api.py): it stops while the account is
disabled and goes with the account; revoking it, or a new password for the account, ends it for good. The sign-in
tokens of POST /api/v1/session are another kind (signed values, web/session.py) and work as before.
"""

import hashlib
import hmac
import re
import secrets
import time

from opendmt3.server import db

from opendmt3.core.errors import Worded

# A token as it is sent: odt3_, the id that names it in lists (12 hex digits), _, then 32 random bytes (43 letters of
# base64url). Anything else is no named token and is refused before the database is asked.
PREFIX = "odt3_"
SHAPE = re.compile(r"^odt3_([0-9a-f]{12})_([A-Za-z0-9_-]{43})$")
# What a token may do: read answers only GET (and HEAD) calls, write every call its owner may make.
SCOPES = ("read", "write")
# A token's name: what it is for, as its owner wrote it, on one line.
NAME_MAX = 40
# How many tokens one account holds at most: the Account page lists them all.
MOST = 20
# When a token was last used is written at most this often (seconds): a program that calls every second does not make
# every call a write to the database.
USED_EVERY = 60


class TokenError(Worded, ValueError):
    """A token the rules refuse to make, or one that is not there to revoke, worded for its owner (errors.py)."""


def read_only():
    """The refusal of a call a read-only token may not make (web/api.py answers it 403 read_only): anything but a GET,
    and any of an admin's calls."""
    return TokenError("a read-only token makes GET calls only, and none of an admin's", "error.token.read_only")


def digest(token):
    """What the database keeps of a token: its SHA-256 in hex. The token itself is never stored, logged or shown
    again."""
    return hashlib.sha256(token.encode("ascii", "replace")).hexdigest()


def clean_name(name):
    """A token's name as it is kept: every run of whitespace one space, nothing at the ends."""
    return " ".join(str(name or "").split())


class Tokens:
    """Named tokens in the server's database (table api_tokens), each for one account."""

    def __init__(self, db):
        self.db = db

    def _log(self, who, what):
        # The change log, as every change made on the site or through the API writes it.
        self.db.execute("INSERT INTO changes (at, who, what) VALUES (?, ?, ?)", (int(time.time()), who, what))

    def all(self, account_id):
        """The account's tokens, newest first: id, name, scope, when made and last used (never the hash)."""
        return [dict(r) for r in self.db.execute(
            "SELECT id, name, scope, created_at, used_at FROM api_tokens WHERE account_id = ? ORDER BY created_at DESC,"
            " id", (account_id,))]

    def make(self, account, name, scope, who="system", now=None):
        """A new token for `account` (its row): (its row as all() gives it, the token itself, which only this answer
        has). TokenError for a name that is empty or too long, a scope that is neither read nor write, or an account
        that has MOST tokens already."""
        name = clean_name(name)
        if not 1 <= len(name) <= NAME_MAX or not name.isprintable():
            raise TokenError("a token's name is 1 to %d characters" % NAME_MAX, "error.token.name", max=NAME_MAX)
        if scope not in SCOPES:
            raise TokenError("a token's scope is read or write", "error.token.scope")
        # The count and the new token in one write transaction: two made at once (two tabs, a program's two calls)
        # cannot both find room for the last one.
        with db.immediate(self.db):
            held = self.db.execute("SELECT COUNT(*) FROM api_tokens WHERE account_id = ?",
                                   (account["id"],)).fetchone()[0]
            if held >= MOST:
                raise TokenError("an account holds at most %d tokens: revoke one first" % MOST, "error.token.many",
                                 most=MOST)
            while True:
                # A new id, whatever ids there are: twelve hex digits are many, but never two tokens with one.
                token_id = secrets.token_hex(6)
                if not self.db.execute("SELECT 1 FROM api_tokens WHERE id = ?", (token_id,)).fetchone():
                    break
            token = "%s%s_%s" % (PREFIX, token_id, secrets.token_urlsafe(32))
            made = int(now if now is not None else time.time())
            self.db.execute("INSERT INTO api_tokens (id, account_id, name, scope, hash, created_at)"
                            " VALUES (?, ?, ?, ?, ?, ?)", (token_id, account["id"], name, scope, digest(token), made))
            # In the change log by its name and scope: never the token.
            self._log(who, "made the API token %s (%s) for %s" % (name, scope, account["login_id"]))
        return {"id": token_id, "name": name, "scope": scope, "created_at": made, "used_at": None}, token

    def revoke(self, account, token_id, who="system"):
        """End one of the account's tokens for good; returns its name. TokenError when the account has no token of
        that id (revoked already, never made, or another account's)."""
        row = self.db.execute("SELECT name FROM api_tokens WHERE id = ? AND account_id = ?",
                              (str(token_id), account["id"])).fetchone()
        if row is None:
            raise TokenError("no token %s on this account" % token_id, "error.token.unknown", id=token_id)
        self.db.execute("DELETE FROM api_tokens WHERE id = ?", (str(token_id),))
        self._log(who, "revoked the API token %s of %s" % (row["name"], account["login_id"]))
        return row["name"]

    def check(self, sent):
        """The token sent, looked up: its row (id, account_id, name, scope, used_at) when it is one of these, None when
        it is not (another shape, an unknown id, or the right id with a wrong secret). Its id finds the row; the hash is
        compared in constant time."""
        match = SHAPE.match(sent or "")
        if not match:
            return None
        row = self.db.execute("SELECT id, account_id, name, scope, hash, used_at FROM api_tokens WHERE id = ?",
                              (match.group(1),)).fetchone()
        if row is None or not hmac.compare_digest(row["hash"], digest(sent)):
            return None
        return {key: row[key] for key in ("id", "account_id", "name", "scope", "used_at")}

    def touch(self, row, now=None):
        """Note that a token was used now, at most every USED_EVERY seconds (the time is only for the list)."""
        now = int(now if now is not None else time.time())
        if row["used_at"] and now - row["used_at"] < USED_EVERY:
            return
        self.db.execute("UPDATE api_tokens SET used_at = ? WHERE id = ?", (now, row["id"]))
