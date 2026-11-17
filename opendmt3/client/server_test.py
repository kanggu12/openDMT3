"""The test of the connection to another server, step by step, for the ONLINE page's card, the guide's server step
and openDMT3-cmd --test-server: each step what it checked, its outcome, how long it took and, when it failed, what
to do. No Tk here: the window and the command line show the same steps (test_server.py's made-up server tests them).

The steps, in the order a game's login needs them:

  address   the site's address is one, and its name resolves to an address on the network
  site      the site answers (GET /health, its time), and its openDMT3 is this launcher's (same major and minor)
  game      the game's port the site tells (/api/v1/status, 4725 by default) takes a TCP connection
  sign_in   the sign-in the launcher keeps is still taken (GET /api/v1/me with its token); not run without one

The first step that fails stops the test: the ones after it are not run (they need it).
"""

import socket
import time
import urllib.parse

from opendmt3 import __version__

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


def run(address, token=None, report=None, timeout=TIMEOUT, resolve=socket.getaddrinfo,
        connect=socket.create_connection, clock=time.perf_counter):
    """Run the steps against `address` (as the player typed it, or the state's server_url), with the sign-in's
    `token` when there is one; `report(steps)` after each change (a worker thread's way to the window). Returns the
    steps (Step), every one with its final state."""
    from opendmt3.client import remote
    steps = [Step(key) for key in STEPS]
    tell = report or (lambda steps: None)
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
        found = resolve(host, parts.port, type=socket.SOCK_STREAM)
        ip = found[0][4][0]
    except (OSError, IndexError, UnicodeError):
        end(step, started, FAILED, ("server_test.address.unknown", {"host": host}),
            ("server_test.address.unknown.fix", {}))
        return steps
    if not end(step, started, OK, ("server_test.address.ok", {"base": base, "ip": ip})):
        return steps
    # ---- the site: it answers, and its openDMT3 is this launcher's
    step = by_key["site"]
    started = begin(step)
    try:
        health = _get(base + "/health", timeout)
    except remote.RemoteError as e:
        if getattr(e, "key", None) == "error.remote.unreachable":
            end(step, started, FAILED, ("server_test.site.none", {"base": base}), ("server_test.site.none.fix", {}))
        else:
            end(step, started, FAILED, ("server_test.site.other", {"base": base}), ("server_test.site.other.fix", {}))
        return steps
    version = health.get("version") if isinstance(health, dict) else None
    if not isinstance(health, dict) or not health.get("ok") or not isinstance(version, str):
        end(step, started, FAILED, ("server_test.site.other", {"base": base}), ("server_test.site.other.fix", {}))
        return steps
    ms = int(round((clock() - started) * 1000))
    if _version_line(version) != _version_line(__version__):
        end(step, started, FAILED, ("server_test.site.version", {"server": version, "launcher": __version__}),
            ("server_test.site.version.fix" + (".newer" if _version_line(version) > _version_line(__version__)
                                               else ".older"), {}))
        return steps
    if not end(step, started, OK, ("server_test.site.ok", {"version": version, "ms": ms})):
        return steps
    # ---- the game's port, as the site tells it
    step = by_key["game"]
    started = begin(step)
    try:
        status = _get(base + "/api/v1/status", timeout)
        port = status.get("game_port", 4725)
        if not isinstance(port, int) or isinstance(port, bool) or not 0 < port < 65536:
            raise ValueError(port)
    except (remote.RemoteError, ValueError, AttributeError):
        end(step, started, FAILED, ("server_test.site.other", {"base": base}), ("server_test.site.other.fix", {}))
        return steps
    try:
        connection = connect((ip, port), timeout)
        connection.close()
    except OSError:
        end(step, started, FAILED, ("server_test.game.closed", {"ip": ip, "port": port}),
            ("server_test.game.closed.fix", {"port": port}))
        return steps
    if not end(step, started, OK, ("server_test.game.ok", {"ip": ip, "port": port})):
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
    lines.append(words("server_test.failed", step=words("server_test." + failed[0].key)) if failed
                 else words("server_test.passed"))
    return "\n".join(lines)
