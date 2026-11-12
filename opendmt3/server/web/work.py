"""What one request of the site keeps while it is answered, and the worker threads its work runs on.

The site shares its event loop with the game server, so a request's work (its queries, its page, a password's check)
runs on Starlette's worker threads: a handler without a body to read is a plain function, which Starlette runs there,
and one that must read its body first hands the rest over with threaded(). Each request has a Request of its own
(REQUEST, which the worker threads see too: Starlette copies the context to them) holding its one connection to the
database (app.Site.connect), the account its sign-in cookie names (app.Site.account), and the processor time its work
has taken on the worker threads, which the caller's fair share counts (app.Shares): the time it really used, not the
time it waited for a thread, the interpreter or another connection's write.
"""

import asyncio
import contextvars
import functools
import inspect
import time
import weakref

import anyio.to_thread
from starlette.concurrency import run_in_threadpool

# The request being answered on this task and the worker threads it hands its work to.
REQUEST = contextvars.ContextVar("opendmt3_request", default=None)
# Worker threads the site's work runs on at once (Starlette's pool, which is anyio's: 40 by default). The interpreter
# runs one thread's Python at a time, and each query hands it over and takes it back for every row, so many threads
# mostly wait for one another and for the event loop the cabinets share: 20 visitors asking for Home at once took 307
# ms at the median with 40 threads, 126 with 4 and 65 with 2; with 64 cabinets beside 20 visitors that never paused,
# 2 threads answered the cabinets' logins in 99 ms at the median (650 with 4) and their keep-alives within 57 ms for 95 %
# of them (97), and served more pages.
SITE_THREADS = 2
# Long pieces of work (a password's check, a song list read or taken, a backup made, put back or checked, the server
# PC looked through for the game's files) run on threads of their own, this many at once, so the site's two never
# wait behind them: two password checks at once (app.HASHING_AT_ONCE) and one more.
LONG_THREADS = 3
# (the loop whose pool limit was set, the pool of long work's limiter on it) (limit_threads, long), weakly: a test's
# loop that ended is not kept. Only the loop reads and sets them.
_limited = [None, None]


def limit_threads():
    """Set the running loop's pool of worker threads to SITE_THREADS and make its pool of long work, once per loop
    (every request asks; only the loop does, so this needs no lock)."""
    loop = asyncio.get_running_loop()
    known = _limited[0]() if _limited[0] is not None else None
    if known is not loop:
        anyio.to_thread.current_default_thread_limiter().total_tokens = SITE_THREADS
        _limited[0], _limited[1] = weakref.ref(loop), anyio.CapacityLimiter(LONG_THREADS)


class Request:
    """What one request keeps while it is answered (REQUEST)."""

    __slots__ = ("connection", "accounts", "cpu")

    def __init__(self):
        # Its connection to the database, opened at its first use (app.Site.connect), closed by app.Work.
        self.connection = None
        # The account each sign-in cookie it carried names (app.Site.account): looked up once.
        self.accounts = {}
        # Seconds of processor time its work took on the worker threads (charged()).
        self.cpu = 0.0


def charged(fn):
    """fn, counting the processor time it takes on its thread to the request it runs for (Request.cpu). A coroutine
    function is left as it is: what it hands to a thread is counted there (threaded())."""
    if inspect.iscoroutinefunction(fn):
        return fn

    @functools.wraps(fn)
    def counted(*args, **kwargs):
        started = time.thread_time()
        try:
            return fn(*args, **kwargs)
        finally:
            work = REQUEST.get()
            if work is not None:
                # The thread's own processor time: SQLite's work in it included, a wait for anything not. A request's
                # work goes to one thread at a time (each hand-over is awaited), so no two add at once.
                work.cpu += time.thread_time() - started
    return counted


async def threaded(fn, *args, **kwargs):
    """fn(*args, **kwargs) on one of Starlette's worker threads (run_in_threadpool), its processor time counted to the
    request: the loop goes on with the cabinets meanwhile."""
    return await run_in_threadpool(charged(fn), *args, **kwargs)


async def long(fn, *args):
    """fn(*args) on a thread of the long work's own pool (LONG_THREADS at once), its processor time counted to the
    request as threaded()'s is: the site's own threads stay free for every other request meanwhile."""
    limit_threads()
    return await anyio.to_thread.run_sync(charged(fn), *args, limiter=_limited[1])
