"""Long jobs of the admin pages (a song list's import, a restore), run beside the request that starts them, with how
far each has come, for the pages' progress card and GET /api/v1/jobs.

A job runs on a thread of the long work's own (work.long) from a task on the event loop, so it outlives the request
that started it: the page goes back at once and follows the job (site.js asks /admin/jobs/{id} every second), and a
program either waits for the answer as before or asks for the job (?wait=0) and follows it. The work says how far it
has come through services/progress.py; the job keeps the step it is on, done of total within it, and when it ended,
how (done or failed) and with what (its result, or the error in words).

A job is kept in memory until KEEP_SECONDS after it ended, MOST of them at most: a restart forgets them, as it ends
the work they followed.
"""

import asyncio
import collections
import logging
import secrets
import threading
import time

from opendmt3.server.services import progress
from opendmt3.server.web.work import REQUEST, long

# Seconds a page waits for a job it starts before it sends the browser to follow it: a job done within them (a small
# restore, a song list already checked) says how it ended at once, with no progress card in between.
QUICK = 3.0
# Seconds a job is kept after it ended, and the jobs kept at most (the oldest ended one goes first).
KEEP_SECONDS = 3600
MOST = 50
# The site's log, where a job's last step that failed is said (Jobs._run).
log = logging.getLogger("opendmt3.web")
# The kinds of job, and the steps each goes through in order (what the work says with progress.step): the page lists
# the steps with the one it is on, and the bar counts them alike. An import's steps depend on what it reads, which its
# first step tells (an archive is unpacked first, a song list is checked, a folder's songs are read at once): ROUTES
# gives them by that first step.
KINDS = ("song_list", "restore")
STEPS = {"song_list": ("songs", "jackets", "cards", "swap"),
         "restore": ("check", "backup", "copy", "upgrade")}
ROUTES = {"song_list": {"unpack": ("unpack", "songs", "jackets", "cards", "swap"), "check": ("check", "swap"),
                        "songs": ("songs", "jackets", "cards", "swap")}}


class Job:
    """One long piece of work: what it is, who started it, the step it is on and how far into it, how it ended."""

    def __init__(self, kind, who, details=None, clock=time.time):
        self.id = secrets.token_hex(6)
        self.kind, self.who, self.details = kind, who, dict(details or {})
        self.clock = clock
        self.started = clock()
        self.ended = None
        # running, done or failed.
        self.state = "running"
        # The steps it goes through (STEPS, until the first step says which: ROUTES), the step it is on, and done of
        # total within it when the work counts (else None).
        self.steps = STEPS.get(kind, ())
        self.step, self.done, self.total = None, None, None
        # Once done: what the work gave (for the page's line and the API's answer). Once failed: (code, message) and
        # the error itself, for the page's words.
        self.result = None
        self.error = None
        self.exception = None
        # Set on the loop when the job ends (an asyncio future), for a program that waits for it.
        self.finished = None

    def say(self, step, done=None, total=None):
        """progress.step's reporter: the work's thread sets the step (plain attributes: a reader sees one or the
        other, each whole)."""
        if self.step is None and step in ROUTES.get(self.kind, {}):
            # The first step says what is read, and so which steps follow.
            self.steps = ROUTES[self.kind][step]
        self.step, self.done, self.total = step, done, total

    def view(self):
        """The job as GET /api/v1/jobs/{id} gives it."""
        steps = self.steps
        return {"id": self.id, "kind": self.kind, "who": self.who, "state": self.state, "started": int(self.started),
                "ended": int(self.ended) if self.ended else None, "step": self.step, "steps": list(steps),
                "done": self.done, "total": self.total, "share": self.share(), "details": dict(self.details),
                "result": self.result,
                "error": None if self.error is None else {"code": self.error[0], "message": self.error[1]}}

    def share(self):
        """How far the whole job has come, from 0 to 1 (its steps counted alike, the one it is on by done of total),
        1 once it ended; None for a job whose steps are not known."""
        if self.state != "running":
            return 1.0
        steps = self.steps
        if not steps:
            return None
        if self.step not in steps:
            return 0.0
        place = steps.index(self.step)
        within = (self.done / self.total) if self.total else 0.0
        return round((place + max(0.0, min(1.0, within))) / len(steps), 3)


class Jobs:
    """The jobs of one site: started, followed, and forgotten a while after they end."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self._jobs = collections.OrderedDict()
        # The pages' threads read and the loop adds: one lock for the table.
        self._lock = threading.Lock()

    def start(self, kind, who, work, details=None, finish=None):
        """A job running work() (a plain function) on a long work's thread, from now. finish(job), when given, runs on
        a worker thread once it ended (the change log's line, a file to remove). Returns the job; on the event loop."""
        job = Job(kind, who, details, self.clock)
        job.finished = asyncio.get_running_loop().create_future()
        with self._lock:
            self._forget()
            self._jobs[job.id] = job
        asyncio.ensure_future(self._run(job, work, finish))
        return job

    async def _run(self, job, work, finish):
        """The job's task: the work on a long thread, then how it ended, then finish()."""
        # A task of its own, outside the request that started it: no request's connection or count is its (the
        # task's copy of the context only).
        REQUEST.set(None)
        # The work's steps reach this job (the thread sees the task's context).
        progress.REPORT.set(job.say)
        try:
            job.result = await long(work)
            job.state = "done"
        except Exception as e:  # noqa: BLE001  (a job that fails says so; the server goes on)
            job.state = "failed"
            job.exception = e
            job.error = (getattr(e, "code", None) or "failed", str(e))
        finally:
            job.ended = self.clock()
            if finish is not None:
                try:
                    await long(finish, job)
                except Exception:  # noqa: BLE001  (what comes after the work never changes how the work ended)
                    # Said in the server's log with its traceback: the change log's line of an import, or its trace
                    # kept, were lost without a word otherwise (a full disk, a database held past its wait).
                    log.exception("the last step of a %s job could not be done", job.kind)
            if not job.finished.done():
                job.finished.set_result(job)

    async def settled(self, job, seconds=QUICK):
        """Wait up to `seconds` for the job to end; True when it has (the job goes on either way)."""
        try:
            # Shielded: a wait that ends never ends the job.
            await asyncio.wait_for(asyncio.shield(job.finished), seconds)
        except asyncio.TimeoutError:
            return False
        return True

    def get(self, job_id):
        """The job of that id, or None (never started, or forgotten)."""
        with self._lock:
            return self._jobs.get(job_id)

    def all(self):
        """Every job kept, newest first."""
        with self._lock:
            self._forget()
            return list(self._jobs.values())[::-1]

    def running(self, kind):
        """The job of that kind running now, or None."""
        with self._lock:
            for job in self._jobs.values():
                if job.kind == kind and job.state == "running":
                    return job
        return None

    def _forget(self):
        """Jobs that ended more than KEEP_SECONDS ago, and the oldest ended past MOST, forgotten. Under _lock."""
        now = self.clock()
        for job_id in [i for i, j in self._jobs.items() if j.ended and now - j.ended > KEEP_SECONDS]:
            del self._jobs[job_id]
        while len(self._jobs) > MOST:
            ended = [i for i, j in self._jobs.items() if j.ended]
            if not ended:
                break
            del self._jobs[ended[0]]
