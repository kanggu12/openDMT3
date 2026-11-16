"""How far a long piece of work has come (a song list's import, a restore), for the admin pages' jobs (web/jobs.py).

The work itself (catalog.py, songlist.py, sources.py, backups.py) says each step it reaches with step(); whoever runs
it as a job sets REPORT to the job's own reporter first. Without one (the command line, the launcher, a test) a step
costs one look at a context variable and nothing else: the work never needs to know whether anyone follows it.

A context variable, not an argument passed down: the work runs on a worker thread, which sees the context the job
set (anyio copies it to the thread), and the readers in between keep their signatures.
"""

import contextvars

# The reporter of the job this work runs for: a function (step, done, total), or None when nobody follows it.
REPORT = contextvars.ContextVar("opendmt3_progress", default=None)


def step(name, done=None, total=None):
    """The work has reached the step `name` (one of the job's known steps: jobs.STEPS), with done of total when it
    counts its way through it (jackets saved of the songs, pages copied of the database's)."""
    report = REPORT.get()
    # Nobody follows this work: nothing to say.
    if report is not None:
        report(name, done, total)
