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
  so the process cannot stop it for good: the pages name the commands that do, on the server PC. compose.yaml says so
  (OPENDMT3_RUNNER=docker).
- "kubernetes": a cluster runs it (the Helm chart says so, OPENDMT3_RUNNER=kubernetes with the release's names, or the
  cluster's own KUBERNETES_SERVICE_HOST): the cluster owns its life, so the pages ask nothing and name the helm and
  kubectl commands that start, stop, restart and remove it.
- "container": a container started by hand (docker run): Docker's own commands for it, by the container's name.
- "other": started some other way the server cannot tell (a service manager of the owner's own): the pages say to stop
  it there.

What a Runner can do when asked (stop, restart, remove) is a button on the Server tab and a call of the API; what it
cannot, the tab names the command for (commands), or says where to do it.
"""

import threading

# The kinds, as the API names them.
KINDS = ("python", "standalone", "launcher", "docker", "kubernetes", "container", "other")
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


def kubernetes_commands(env):
    """The cluster's commands for the server, with the names the Helm chart gives it (its namespace, release,
    Deployment and claim), or the names to fill in where it gives none (a cluster without the chart)."""
    namespace = env.get("OPENDMT3_KUBE_NAMESPACE") or "<namespace>"
    release = env.get("OPENDMT3_KUBE_RELEASE") or "<release>"
    deployment = env.get("OPENDMT3_KUBE_DEPLOYMENT") or "<deployment>"
    # The chart names its claim, or none when it keeps no volume (the data then goes with the pod); without the chart
    # the owner's claim is a name to fill in.
    chart = env.get("OPENDMT3_RUNNER") == "kubernetes"
    claim = env.get("OPENDMT3_KUBE_CLAIM") or (None if chart else "<claim>")
    kubectl, helm = "kubectl -n %s" % namespace, "helm -n %s" % namespace
    return {"start": "%s scale deployment/%s --replicas=1" % (kubectl, deployment),
            "stop": "%s scale deployment/%s --replicas=0" % (kubectl, deployment),
            # A new pod (the chart's Recreate: the old one goes first, the data volume moves to the new one).
            "restart": "%s rollout restart deployment/%s" % (kubectl, deployment),
            "remove": "%s uninstall %s" % (helm, release),
            # The chart keeps the data's claim when it is uninstalled (resource-policy: keep): deleted by name.
            "remove_data": ("%s uninstall %s && %s delete pvc %s" % (helm, release, kubectl, claim) if claim else
                            "%s uninstall %s" % (helm, release))}


def container_commands(env):
    """Docker's own commands for a container started by hand, by its name (its host name is its ID, unless given
    another one)."""
    name = env.get("HOSTNAME") or "<container>"
    return {"start": "docker start %s" % name, "stop": "docker stop %s" % name, "restart": "docker restart %s" % name,
            "remove": "docker rm -f %s" % name,
            # -v: the data volume the image declares goes with it (a named volume given by hand: docker volume rm).
            "remove_data": "docker rm -f -v %s" % name}


def default(in_container, env=None):
    """The runner of a Site made without one. In a container: Docker Compose when compose.yaml says so, a cluster when
    the Helm chart (or the cluster's own variable) says so, else a container started by hand. Outside one: a way the
    server cannot tell. env: the environment to read (os.environ when not given)."""
    import os
    env = os.environ if env is None else env
    if not in_container:
        return Runner("other")
    said = env.get("OPENDMT3_RUNNER", "")
    if said == "kubernetes" or (not said and env.get("KUBERNETES_SERVICE_HOST")):
        return Runner("kubernetes", commands=kubernetes_commands(env))
    if said == "docker":
        return Runner("docker")
    return Runner("container", commands=container_commands(env))
