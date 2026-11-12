"""Signed values for the site's sign-in cookie and the launcher's API tokens.

A value is JSON, base64url-encoded, with an HMAC-SHA256 over it made with a secret that only this server has
(kept in its data folder, made once). Nothing can be forged without the secret, and every value carries the
time it was made so it can expire. Each also carries a short fingerprint of the account's stored password, so
a new password ends every sign-in and token made before it.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

SECRET_FILE = "web.secret"
SECRET_BYTES = 32
MIN_SECRET_BYTES = 16       # a shorter one (a file cut short, typed by hand) is replaced


def _make_secret(path):
    """A new secret in a new file, readable by the server's own user only."""
    tmp = path + ".new"
    if os.path.exists(tmp):
        os.remove(tmp)
    # Created with no permissions for others before anything is written into it, then moved into place.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(secrets.token_hex(SECRET_BYTES))
    os.replace(tmp, path)


def load_secret(folder):
    """The server's signing secret, made the first time.

    A file that is empty, not hex or too short is replaced by a new secret: a weak one would let anyone forge
    sign-ins, and a new one only means everyone signs in again.
    """
    path = os.path.join(folder, SECRET_FILE)
    os.makedirs(folder, exist_ok=True)
    for _ in range(2):
        if os.path.isfile(path):
            with open(path) as f:
                text = f.read().strip()
            try:
                secret = bytes.fromhex(text)
            except ValueError:
                secret = b""
            if len(secret) >= MIN_SECRET_BYTES:
                return secret
        _make_secret(path)
    raise OSError("could not make a signing secret in %s" % folder)


def password_mark(stored_password):
    """A short fingerprint of an account's stored secret: changes whenever the password does."""
    return hashlib.sha256(stored_password.encode("ascii")).hexdigest()[:12]


def token_id(text):
    """An API token's id in the list of tokens ended before their time: a hash of its text. The token itself, which
    signs in, is never kept; only this server can make a token's text (its MAC), so one token has one id."""
    return hashlib.sha256(text.encode("ascii", "replace")).hexdigest()


class Signer:
    def __init__(self, secret):
        self.secret = secret

    def _mac(self, body):
        return base64.urlsafe_b64encode(hmac.new(self.secret, body, hashlib.sha256).digest()).rstrip(b"=")

    def sign(self, value):
        """value (a dict) -> an opaque text that only this server can make."""
        data = dict(value, t=int(time.time()))
        body = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).rstrip(b"=")
        return (body + b"." + self._mac(body)).decode("ascii")

    def unsign(self, text, max_age):
        """The dict inside a signed text, or None when it was not made here, was changed, or is too old."""
        try:
            body, mac = text.encode("ascii").split(b".", 1)
        except (AttributeError, ValueError, UnicodeEncodeError):
            return None
        if not hmac.compare_digest(mac, self._mac(body)):
            return None
        try:
            data = json.loads(base64.urlsafe_b64decode(body + b"=" * (-len(body) % 4)))
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict) or time.time() - data.get("t", 0) > max_age:
            return None
        return data
