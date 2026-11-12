"""Talking to an openDMT3 server someone else runs: is it there, sign in to get the player's card, sign out, and
(for its admin) send it the song list from this PC's game folder.

Only the standard library (urllib), with short timeouts: the window calls these on a worker thread and shows
the answer. The server's own address for the game (host and game port) comes from its status, so a player only
ever types the address of the site the owner gave them.
"""

import json
import logging
import re
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request

from opendmt3 import __version__
from opendmt3.core.errors import Worded

# The launcher's own log: a server that cannot be reached leaves the system's reason there, not in a window.
log = logging.getLogger("opendmt3.launcher")

TIMEOUT = 8                 # seconds; a LAN server answers in milliseconds, a far one in well under this
# A sign-out waits less: the launcher forgets the sign-in after it whatever the server says, so a server that does not
# answer holds it up only this long.
SIGN_OUT_TIMEOUT = 4
DEFAULT_WEB_PORT = 4730     # the site's port when the address has none (opendmt3.server's default)
# The longest answer read: the launcher's calls get a few kilobytes back (a DJ's records, the largest, stay well
# under a megabyte); anything longer is not an openDMT3 answer, and is not read into memory to find out.
ANSWER_LIMIT = 4 * 1024 * 1024
# A card number as the game's card reader takes it (native/: 1 to 20 printable characters, no space).
CARD = re.compile(r"[\x21-\x7e]{1,20}")
# Sending a song list waits longer: about 14 MB go up, and the server checks every picture before it answers.
SEND_TIMEOUT = 180


class RemoteError(Worded):
    """The server could not be reached or refused, worded for the player (errors.py).

    code is the API's error code when the server answered one ("sign_in" when it no longer takes a token), None
    otherwise; the words for a code are under error.api.<code>.
    """

    def __init__(self, message, code=None, key=None, **params):
        # The server's own error codes have words of their own; the others say what failed here.
        super().__init__(message, key or ("error.api." + code if code else None), **params)
        self.code = code


def normalize(address):
    """'192.168.0.10' -> 'http://192.168.0.10:4730'; keeps a scheme and a port that are given. An address with
    port 443 and no scheme is https: that port is TLS's, as a site behind a TLS proxy shows its address."""
    text = (address or "").strip().rstrip("/")
    if not text:
        raise RemoteError("type the server's address", key="error.remote.empty")
    if "://" not in text:
        text = ("https://" if text.endswith(":443") else "http://") + text
    try:
        parts = urllib.parse.urlsplit(text)
        # .port raises ValueError for a port that is not a number or out of range ("host:4730x", ":99999").
        port = parts.port or DEFAULT_WEB_PORT
    except ValueError:
        raise RemoteError("%r is not an address" % address, key="error.remote.address", address=address) from None
    if not parts.hostname:
        raise RemoteError("%r is not an address" % address, key="error.remote.address", address=address)
    host = "[%s]" % parts.hostname if ":" in parts.hostname else parts.hostname
    return "%s://%s:%d" % (parts.scheme, host, port)


class _SameHost(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only on the same host (a site moving a page, or on to https), never to another: the
    request carries the player's token, and another host is not the server they chose."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(req.full_url).hostname:
            # None: urllib then treats the answer as an error (HTTPError with the redirect's status).
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# The opener every call uses, made by the first call that needs it (_opener): making it loads the system's
# certificates for https (42 ms at every launcher start, which imports this module when it reads the installer's
# server, while most starts call no server at all).
_OPENER = None
_opener_lock = threading.Lock()


def _opener():
    """The opener of the calls (_SameHost's redirects), made once, by the first call."""
    global _OPENER
    with _opener_lock:
        if _OPENER is None:
            _OPENER = urllib.request.build_opener(_SameHost)
        return _OPENER


def _not_an_answer(url):
    """The error for an answer that is not an openDMT3 server's (too long, not JSON, not an object)."""
    base = url.split("/api/")[0]
    return RemoteError("%s did not answer as an openDMT3 server does" % base, key="error.remote.not_an_answer",
                       base=base)


def _call(url, method="GET", body=None, token=None, timeout=TIMEOUT, raw=None, kind=None):
    """One call of the server's API: a JSON body, or `raw` bytes of the content type `kind` (a file); its answer, one
    JSON object. RemoteError in words when it cannot be reached or refuses."""
    data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("User-Agent", "openDMT3-launcher/%s" % __version__)
    if data is not None:
        request.add_header("Content-Type", kind or "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with _opener().open(request, timeout=timeout) as response:
            raw = response.read(ANSWER_LIMIT + 1)
    except urllib.error.HTTPError as e:
        # The API answers errors as {"error": {"code", "message"}}; the code picks the words shown (errors.py).
        try:
            error = json.loads(e.read(ANSWER_LIMIT + 1).decode("utf-8"))["error"]
            message, code = str(error["message"])[:500], error.get("code")
            if code is not None and not isinstance(code, str):
                raise TypeError(code)
        except (ValueError, KeyError, TypeError, AttributeError, OSError):
            raise RemoteError("the server answered %d" % e.code, key="error.remote.answered", status=e.code) from None
        raise RemoteError(message, code) from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        reason = getattr(e, "reason", e)
        base = url.split("/api/")[0]
        # The system's own reason ("[Errno 101] Network is unreachable") goes to the log; the window says what to do.
        log.info("cannot reach %s: %s", base, reason)
        raise RemoteError("Cannot reach %s. Check the address and the network." % base, key="error.remote.unreachable",
                          base=base) from None
    # Every answer the launcher asks for is one JSON object of moderate size.
    try:
        answer = json.loads(raw.decode("utf-8")) if len(raw) <= ANSWER_LIMIT else None
    except (ValueError, UnicodeDecodeError):
        answer = None
    if not isinstance(answer, dict):
        raise _not_an_answer(url)
    return answer


def _player(url, answer):
    """A signed-in player's answer, checked before anything of it is kept or written into the game folder."""
    card = answer.get("card")
    if (not isinstance(answer.get("login_id"), str) or not isinstance(answer.get("dj_name"), (str, type(None)))
            or not (card is None or (isinstance(card, str) and CARD.fullmatch(card)))):
        raise _not_an_answer(url)
    return answer


def status(base):
    """The server's status; RemoteError unless it is an openDMT3 server. Adds 'game' (host:port for the game)."""
    answer = _call(base + "/api/v1/status")
    if answer.get("server") != "openDMT3":
        raise RemoteError("%s is not an openDMT3 server" % base, key="error.remote.not_opendmt3", base=base)
    host = urllib.parse.urlsplit(base).hostname
    try:
        # The game reads an address, not a name (its networksetting.ini always held one): resolve it here, where
        # the launcher can say so if the name does not resolve.
        address = socket.gethostbyname(host)
    except OSError as e:
        # The resolver's own reason goes to the log; the window says what to do.
        log.info("cannot find %s: %s", host, e)
        raise RemoteError("Cannot find %s. Check the address." % host, key="error.remote.unknown_host",
                          host=host) from None
    port = answer.get("game_port", 4725)
    # The game reads a plain number there; anything else is not this server's answer.
    if not isinstance(port, int) or isinstance(port, bool) or not 0 < port < 65536:
        raise _not_an_answer(base + "/api/v1/status")
    answer["game"] = "%s:%d" % (address, port)
    return answer


def sign_in(base, login_id, password):
    """Sign in; returns {login_id, dj_name, card, token}."""
    url = base + "/api/v1/session"
    answer = _player(url, _call(url, "POST", {"login_id": login_id, "password": password}))
    if not isinstance(answer.get("token"), str):
        raise _not_an_answer(url)
    return answer


def sign_out(base, token):
    """Ask the server to end the launcher's token (DELETE /api/v1/session), so a copy of it left anywhere stops
    working; the player's other sign-ins (a launcher on another PC, the site) go on. True when the server ended it;
    False when it could not be asked (no answer within SIGN_OUT_TIMEOUT), is older than this call (it answers 404 or
    405), or no longer took the token. Never raises RemoteError: the launcher forgets the sign-in either way."""
    try:
        _call(base + "/api/v1/session", "DELETE", token=token, timeout=SIGN_OUT_TIMEOUT)
    except RemoteError:
        return False
    return True


def me(base, token):
    """The signed-in player as the server has them now: {login_id, dj_name, card, is_admin}."""
    url = base + "/api/v1/me"
    return _player(url, _call(url, token=token))


def dj(base, token, player):
    """A player's records as the site's DJ page has them (GET /api/v1/djs/{player})."""
    return _call(base + "/api/v1/djs/%d" % int(player), token=token)


def plays(base, token):
    """The signed-in player's recent plays (newest first), with song titles from the server's list."""
    return _call(base + "/api/v1/plays", token=token).get("plays", [])


def send_song_list(base, token, path):
    """Send a song list (a file songlist.save made) to the server, whose admin the token signs in: it imports it as
    its Song list tab's upload does. Returns the server's answer ({"song_list", "lines"}); RemoteError in words when
    it refuses (admin_only for a player's token, too_large, busy, refused with its reason)."""
    with open(path, "rb") as f:
        data = f.read()
    return _call(base + "/api/v1/server/song_list", "POST", token=token, timeout=SEND_TIMEOUT, raw=data,
                 kind="application/zip")
