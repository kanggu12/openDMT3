"""The test of the connection to another server, step by step, for the ONLINE page's card, the guide's server step
and openDMT3-cmd --test-server: each step what it checked, its outcome, how long it took and, when it failed, what
to do. No Tk here: the window and the command line show the same steps (test_server.py's made-up server tests them).

The steps, in the order a game's login needs them:

  address   the site's address is one, and its name resolves to an address on the network
  site      the site answers (GET /health, its time) as an openDMT3 server's does (its status, checked as Connect
            checks it: remote.site_status), and its openDMT3 is this launcher's (same major and minor)
  game      the game's port the site tells (/api/v1/status, 4725 by default) takes a TCP connection at one of the
            name's addresses, IPv4 first (the game's own: remote.status gives it the name's IPv4 address)
  sign_in   the sign-in the launcher keeps is still taken (GET /api/v1/me with its token); not run without one, and
            the token goes only to the server it was made on (kept_token)

The first step that fails stops the test: the ones after it are not run (they need it). A step that breaks (an error
nobody foresaw) fails where it was, and the test still ends: no step is left running, none said to have passed.
"""

import logging
import socket
import time
import urllib.parse

from opendmt3 import __version__

# The launcher's own log: what broke a step goes there, the card says where it stopped.
log = logging.getLogger("opendmt3.launcher")

# The steps' keys, in order; each one's words are server_test.<key> in i18n.
STEPS = ("address", "site", "game", "sign_in")
# A step's states.
WAITING, RUNNING, OK, FAILED, NOT_RUN = "waiting", "running", "ok", "failed", "not_run"
# How long a step waits for the network (seconds): a server that does not answer in this is said to not answer.
TIMEOUT = 5
# The command line's exit code for the step that failed (0: every step passed).
EXIT_CODES = {"address": 2, "site": 3, "game": 4, "sign_in": 5}


class Step:
    """One step's outcome: its state, how long it took (ms), what it found (the words' key and values) and, when it
    failed, what to do (the words' key and values)."""

    def __init__(self, key):
        self.key, self.state, self.ms = key, WAITING, None
        self.said, self.fix = None, None

    def __repr__(self):
        return "Step(%s, %s, %s ms, %r, %r)" % (self.key, self.state, self.ms, self.said, self.fix)


def _version_line(version):
    """(major, minor) of a version, (0, 0) when it is not one."""
    parts = (str(version or "").split("+")[0].split("-")[0].split(".") + ["0", "0"])[:2]
    return tuple(int(p) if p.isdigit() else 0 for p in parts)


def _get(url, timeout):
    """GET `url` as remote's calls do (its opener: redirects on the same host only); the JSON object answered, or
    remote.RemoteError."""
    from opendmt3.client import remote
    return remote._call(url, timeout=timeout)


def kept_token(address, kept):
    """The sign-in token the launcher keeps, for a test of `address`: only when `address` is the server it was made on
    (`kept`: the launcher's state, its server_url and remote), both read as remote.normalize writes a server's address
    (the scheme, the host in lower case, the port); else None. A token is one server's own and is never sent to
    another: the window and the command line test with this one rule."""
    from opendmt3.client import remote
    token = (getattr(kept, "remote", None) or {}).get("token")
    server_url = getattr(kept, "server_url", None)
    if not token or not server_url:
        return None
    try:
        same = remote.normalize(address) == remote.normalize(server_url)
    except remote.RemoteError:
        # Not an address (the address step says so): nothing is sent anywhere.
        return None
    return token if same else None


def _shown(ip):
    """An address as it is written before a port: an IPv6 one in brackets ([::1]:4725), as a browser writes it."""
    return "[%s]" % ip if ":" in ip else ip


def _addresses(found):
    """The addresses getaddrinfo found, each once, IPv4 first (the game's: it is given the name's IPv4 address), the
    rest in the order found."""
    ips = []
    for family in (socket.AF_INET, None):
        for entry in found:
            ip = entry[4][0]
            if (family is None or entry[0] == family) and ip not in ips:
                ips.append(ip)
    return ips


def _site_failed(error, base):
    """The site step's (said, fix) for a call that failed (remote.RemoteError): nothing answers, something answers
    that is no site (the game's port typed for the site's), or something that is no openDMT3 server."""
    key = getattr(error, "key", None)
    if key == "error.remote.unreachable":
        return ("server_test.site.none", {"base": base}), ("server_test.site.none.fix", {})
    if key == "error.remote.not_a_site":
        return ("server_test.site.not_a_site", {"base": base}), ("server_test.site.not_a_site.fix", {})
    return ("server_test.site.other", {"base": base}), ("server_test.site.other.fix", {})


def run(address, kept=None, report=None, timeout=TIMEOUT, resolve=socket.getaddrinfo,
        connect=socket.create_connection, clock=time.perf_counter):
    """Run the steps against `address` (as the player typed it, or the state's server_url), with the sign-in the
    launcher keeps (`kept`, its state) when `address` is the server it was made on (kept_token); `report(steps)` after
    each change (a worker thread's way to the window). Returns the steps (Step), every one with its final state, and
    never raises: a step that breaks fails where it was."""
    steps = [Step(key) for key in STEPS]
    tell = report or (lambda steps: None)
    try:
        _run(steps, tell, address, kept_token(address, kept), timeout, resolve, connect, clock)
    except Exception:  # noqa: BLE001  (logged; the step it broke in fails, so the test still ends in words)
        log.exception("the connection test broke")
        broken = [s for s in steps if s.state == RUNNING] or [s for s in steps if s.state == WAITING][:1]
        if broken:
            broken[0].state, broken[0].said, broken[0].fix = FAILED, ("server_test.broke", {}), None
            for later in steps[steps.index(broken[0]) + 1:]:
                later.state = NOT_RUN
        tell(steps)
    return steps


def _run(steps, tell, address, token, timeout, resolve, connect, clock):
    """run()'s steps, one after another, until one fails."""
    from opendmt3.client import remote
    by_key = {s.key: s for s in steps}

    def begin(step):
        step.state = RUNNING
        tell(steps)
        return clock()

    def end(step, started, state, said=None, fix=None):
        step.state, step.ms = state, int(round((clock() - started) * 1000))
        step.said, step.fix = said, fix
        if state == FAILED:
            # What depends on it is not run.
            for later in steps[steps.index(step) + 1:]:
                later.state = NOT_RUN
        tell(steps)
        return state == OK

    # ---- the address and its name
    step = by_key["address"]
    started = begin(step)
    try:
        base = remote.normalize(address)
    except remote.RemoteError:
        end(step, started, FAILED, ("server_test.address.bad", {"address": address or ""}),
            ("server_test.address.fix", {}))
        return steps
    parts = urllib.parse.urlsplit(base)
    host = parts.hostname
    try:
        # Every address the name has, IPv4 first: the one the game will be given leads.
        ips = _addresses(resolve(host, parts.port, type=socket.SOCK_STREAM))
        ip = ips[0]
    except (OSError, IndexError, UnicodeError):
        end(step, started, FAILED, ("server_test.address.unknown", {"host": host}),
            ("server_test.address.unknown.fix", {}))
        return steps
    if not end(step, started, OK, ("server_test.address.ok", {"base": base, "ip": ip})):
        return steps
    # ---- the site: it answers as an openDMT3 server's does, and its openDMT3 is this launcher's
    step = by_key["site"]
    started = begin(step)
    try:
        health = _get(base + "/health", timeout)
    except remote.RemoteError as e:
        end(step, started, FAILED, *_site_failed(e, base))
        return steps
    version = health.get("version") if isinstance(health, dict) else None
    if not isinstance(health, dict) or not health.get("ok") or not isinstance(version, str):
        end(step, started, FAILED, ("server_test.site.other", {"base": base}), ("server_test.site.other.fix", {}))
        return steps
    ms = int(round((clock() - started) * 1000))
    try:
        # Its status, checked as Connect checks it (an openDMT3 server's, with a game port that is one): a site that
        # passes here is one Connect takes.
        status = remote.site_status(base, timeout)
    except remote.RemoteError as e:
        end(step, started, FAILED, *_site_failed(e, base))
        return steps
    if _version_line(version) != _version_line(__version__):
        end(step, started, FAILED, ("server_test.site.version", {"server": version, "launcher": __version__}),
            ("server_test.site.version.fix" + (".newer" if _version_line(version) > _version_line(__version__)
                                               else ".older"), {}))
        return steps
    if not end(step, started, OK, ("server_test.site.ok", {"version": version, "ms": ms})):
        return steps
    # ---- the game's port, as the site tells it, at each of the name's addresses until one takes it
    step = by_key["game"]
    started = begin(step)
    port = status.get("game_port", 4725)
    for each in ips:
        try:
            connection = connect((each, port), timeout)
        except OSError:
            # Not at this address: the next (IPv6 after IPv4, as a name with both kinds may be reached).
            continue
        connection.close()
        end(step, started, OK, ("server_test.game.ok", {"ip": _shown(each), "port": port}))
        break
    else:
        # At none: said for the first, the address the game is given.
        end(step, started, FAILED, ("server_test.game.closed", {"ip": _shown(ip), "port": port}),
            ("server_test.game.closed.fix", {"port": port}))
        return steps
    # ---- the sign-in the launcher keeps
    step = by_key["sign_in"]
    if not token:
        step.state, step.said = NOT_RUN, ("server_test.sign_in.none", {})
        tell(steps)
        return steps
    started = begin(step)
    try:
        me = remote.me(base, token)
    except remote.RemoteError as e:
        if getattr(e, "code", None) == "sign_in":
            end(step, started, FAILED, ("server_test.sign_in.gone", {}), ("server_test.sign_in.gone.fix", {}))
        else:
            end(step, started, FAILED, ("server_test.site.other", {"base": base}), ("server_test.site.other.fix", {}))
        return steps
    end(step, started, OK, ("server_test.sign_in.ok", {"dj": me.get("dj_name") or "", "login_id": me["login_id"]}))
    return steps


def passed(steps):
    """True when no step failed (a sign-in not run, for want of one, is no failure)."""
    return not any(s.state == FAILED for s in steps)


def exit_code(steps):
    """0 when every step that ran passed, else the failed step's code (EXIT_CODES)."""
    failed = [s for s in steps if s.state == FAILED]
    return EXIT_CODES[failed[0].key] if failed else 0


def as_text(steps, words):
    """The steps as lines of text, for the command line and the card's Copy: each step's name, state, time and what
    it found, the fix under a failed one, and a last line of the outcome."""
    lines = []
    marks = {OK: "ok", FAILED: "FAILED", NOT_RUN: "-", WAITING: "...", RUNNING: "..."}
    for s in steps:
        took = "%d ms" % s.ms if s.ms is not None else ""
        said = words(s.said[0], **s.said[1]) if s.said else ""
        lines.append("%-7s %-26s %7s  %s" % (marks[s.state], words("server_test." + s.key), took, said))
        if s.fix:
            lines.append("        " + words(s.fix[0], **s.fix[1]))
    failed = [s for s in steps if s.state == FAILED]
    lines.append(words("server_test.failed", step=words("server_test." + failed[0].key + ".in")) if failed
                 else words("server_test.passed"))
    return "\n".join(lines)
