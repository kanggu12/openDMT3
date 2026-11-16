"""Who started this server, and how the admin pages ask it to stop.

Whoever starts a service stops it: the admin page never ends the process on its own, it asks the one that started it.
That one hands the Site a Runner when it makes it:

- "python": the server's own command line (python -m opendmt3.server, __main__.py) runs it in the foreground; its
  stop() ends the site and the game server as Ctrl+C would, and the command returns.
- "launcher": the launcher's built-in server (opendmt3/client/hosting.py), stopped through the launcher, so its window
  knows the server is off.
- "docker": Docker Compose runs the container and starts it again whenever its process ends (restart: unless-stopped),
  so the process cannot stop it for good: the page names the command that does, on the server PC.
- "other": started some other way the server cannot tell (a service manager of the owner's own): the page says to stop
  it there.

A Runner with stop is one the page can ask; without, the page shows how to stop it instead.
"""

import threading

# The command that stops the server under Docker Compose, on the server PC (./dmt3 down: docker compose down; the data
# stays in its volume).
DOCKER_COMMAND = "./dmt3 down"
# The kinds, as the API names them.
KINDS = ("python", "launcher", "docker", "other")
# Seconds between the answer to a stop and the stop itself: the page (or the API's answer) that says so goes out first.
GRACE = 0.5


class Runner:
    """What started the server (kind), the function that asks it to stop (stop, or None when the page cannot ask it),
    and the command that stops it otherwise (command)."""

    def __init__(self, kind, stop=None, command=None):
        if kind not in KINDS:
            raise ValueError(kind)
        self.kind, self._stop, self.command = kind, stop, command
        # Asked once: a second press while it stops changes nothing.
        self.stopping = False
        self._lock = threading.Lock()

    @property
    def can_stop(self):
        """True when the page can ask the runner to stop the server."""
        return self._stop is not None

    def stop(self):
        """Ask the runner to stop the server, GRACE seconds from now (from any thread). True when asked now, False when
        it was asked already or cannot be."""
        if self._stop is None:
            return False
        with self._lock:
            if self.stopping:
                return False
            self.stopping = True
        # On a timer of its own: the request that asked is answered meanwhile, then the runner stops what it started.
        timer = threading.Timer(GRACE, self._stop)
        timer.daemon = True
        timer.start()
        return True

    def view(self):
        """The runner as GET /api/v1/server gives it: kind, whether the page can stop it, the command otherwise, and
        whether it is stopping."""
        return {"kind": self.kind, "can_stop": self.can_stop, "command": self.command, "stopping": self.stopping}


def default(in_container):
    """The runner of a Site made without one: Docker Compose's in a container, else one the server cannot tell."""
    if in_container:
        return Runner("docker", command=DOCKER_COMMAND)
    return Runner("other")
