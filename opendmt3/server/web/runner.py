"""Who started this server, and how the admin pages ask it to stop, restart or remove it.

Whoever starts a service stops it: the admin pages never end the process on their own, they ask the one that started
it. That one hands the Site a Runner when it makes it, with what it can do when asked:

- "python": the server's own command line (python -m opendmt3.server, __main__.py) runs it in the foreground. Asked
  to stop, it ends the site and the game server as Ctrl+C would and returns; to restart, it does that and runs itself
  again in the same process (the window that started it keeps it); to remove, it stops, keeps a last backup beside the
  data folder and deletes the data folder.
- "standalone": the server's command for a PC of its own (opendmt3-server): its own stop, start and remove commands.
- "launcher": the launcher's built-in server, stopped and removed through the launcher, so its window knows.
- "docker": Docker Compose runs the container and starts it again whenever its process ends (restart: unless-stopped),
  so the process cannot stop it for good: the pages name the commands that do, on the server PC.
- "other": started some other way the server cannot tell (a service manager of the owner's own): the pages say to stop
  it there.

What a Runner can do when asked (stop, restart, remove) is a button on the Server tab and a call of the API; what it
cannot, the tab names the command for (commands), or says where to do it.
"""

import threading

# The kinds, as the API names them.
KINDS = ("python", "standalone", "launcher", "docker", "other")
# What can be asked of a runner, as the API names it.
ACTIONS = ("stop", "restart", "remove")
# The commands each kind's owner runs on the server PC, for what the pages cannot ask: start, stop, restart, remove
# (the program, the data kept) and remove with the data. None: there is no such command (a button, or the launcher's
# window, does it).
COMMANDS = {
    "docker": {"start": "./dmt3 up", "stop": "./dmt3 down", "restart": "./dmt3 restart", "remove": "./dmt3 remove",
               "remove_data": "./dmt3 remove --delete-data"},
    "standalone": {"start": "opendmt3-server start", "stop": "opendmt3-server stop",
                   "restart": "opendmt3-server restart", "remove": "opendmt3-server remove",
                   "remove_data": "opendmt3-server remove --delete-data"},
    "python": {"start": "python -m opendmt3.server", "stop": None, "restart": None, "remove": None,
               "remove_data": None},
}
# Seconds between the answer to a request and doing it: the page (or the API's answer) that says so goes out first.
GRACE = 0.5


class Runner:
    """What started the server (kind), the functions that ask it to stop, to restart and to remove it (each None when
    the pages cannot ask it that), and the commands that do the rest on the server PC."""

    def __init__(self, kind, stop=None, restart=None, remove=None, commands=None):
        if kind not in KINDS:
            raise ValueError(kind)
        self.kind = kind
        # remove takes one argument: whether the data goes too.
        self._asks = {"stop": stop, "restart": restart, "remove": remove}
        self.commands = dict(COMMANDS.get(kind, {}), **(commands or {}))
        # What it was asked, once: a second press while it is done changes nothing.
        self.asked = None
        self._lock = threading.Lock()

    @property
    def command(self):
        """The command that stops it on the server PC, or None (the API's runner.command)."""
        return self.commands.get("stop")

    def can(self, action):
        """True when the pages can ask the runner this (stop, restart or remove)."""
        return self._asks.get(action) is not None

    @property
    def can_stop(self):
        return self.can("stop")

    @property
    def stopping(self):
        return self.asked is not None

    def ask(self, action, *args):
        """Ask the runner to do `action` GRACE seconds from now (from any thread). True when asked now; False when
        something was asked already, or the runner cannot be asked this."""
        do = self._asks.get(action)
        if do is None:
            return False
        with self._lock:
            if self.asked is not None:
                return False
            self.asked = action
        # On a timer of its own: the request that asked is answered meanwhile, then the runner does what it said.
        timer = threading.Timer(GRACE, do, args)
        timer.daemon = True
        timer.start()
        return True

    def stop(self):
        """Ask the runner to stop the server (ask("stop"))."""
        return self.ask("stop")

    def view(self):
        """The runner as GET /api/v1/server gives it: kind, what the pages can ask it (can: stop, restart, remove),
        the commands for the rest, what it was asked (asked, or None), and command and stopping as before."""
        return {"kind": self.kind, "can": [a for a in ACTIONS if self.can(a)], "can_stop": self.can_stop,
                "commands": dict(self.commands), "command": self.command, "asked": self.asked,
                "stopping": self.stopping}


def default(in_container):
    """The runner of a Site made without one: Docker Compose's in a container, else one the server cannot tell."""
    if in_container:
        return Runner("docker")
    return Runner("other")
