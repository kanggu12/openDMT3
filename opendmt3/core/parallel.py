"""Work spread over a few threads, for reading the game's files: what each piece waits on (the drive) or computes in C
(zlib, Pillow's decoding and encoding) lets the other threads go on, so a handful of them keep a drive and the cores
busy where one thread waited on each read in turn.

Threads, not processes: since the key stream works in bulk (core/formats/pak.py) the Python left in reading the game's
files is a small part of it, and a process on Windows starts slowly (a new interpreter, every module imported again)
and would have to be handed its archive's listing and table. The pool is small (WORKERS), so a busy PC is not asked for
more than a few cores, and the window's thread, which these never run on, is not kept waiting long for Python's lock.
"""

import concurrent.futures
import os

# At most this many threads for one piece of work. Each holds Python's lock for its Python steps, and the window's thread
# waits its turn behind them: the PLAY page's header with its discs takes 10 ms to draw alone, 15 ms beside one busy
# thread, 24 ms beside two and 40 ms (up to 62) beside four. Two threads give most of what four do (the song list of a
# whole game folder: 4.0 s on one thread, 2.4 s on two, 2.2 on three, 2.0 to 3.0 on four), so two. Reading ahead of
# a walk (core/formats/pak.py) only waits on the drive, and takes four of its own.
WORKERS = 2 if (os.cpu_count() or 2) > 1 else 1


def ordered(fn, items, workers=None, name="opendmt3-read"):
    """fn over each of items on a bounded pool of threads (WORKERS unless workers says), yielding the results in the
    items' order (a generator: each as soon as it and the ones before it are done). An error raised by fn comes out at
    its item's place, and the pieces not started yet are dropped."""
    workers = WORKERS if workers is None else workers
    items = list(items)
    if len(items) < 2 or workers < 2:
        # One piece, or one thread: no pool to make.
        for item in items:
            yield fn(item)
        return
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, len(items)), thread_name_prefix=name)
    try:
        # Every piece asked for at once (they are a few hundred at most); map hands the results back in order.
        yield from pool.map(fn, items)
    finally:
        # Done, failed or left early: the pieces not started are dropped, and the ones running are waited for, so no
        # thread is left reading a file its caller is about to close.
        pool.shutdown(wait=True, cancel_futures=True)
