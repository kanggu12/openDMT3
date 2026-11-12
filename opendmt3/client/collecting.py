"""Python's garbage collector, kept on the window's thread while a window is open.

A picture, a Tk variable or a font that sits in a reference cycle is freed by the collector, and the automatic
collector runs on whichever thread allocates next: a page's worker, the server's thread. Freed there, such an
object calls Tk from that thread (`image delete`), and Tk may only be touched from its own. Under mainloop() the
call is handed over and the worker waits for the window to answer; a window that is itself waiting for that
worker (closing joins the server's thread) then stands still until the join gives up. Under a loop of update()
every such call waits a second and fails, picture after picture.

So while the launcher's window is open the automatic collector is off and the window's thread collects instead,
from its 50 ms pump (app.py): what is new as soon as there is enough of it, everything a little after the
window was last busy (a page that was left takes its pictures with it then). An idle window collects nothing.
"""

import gc
import time

# Objects made since the last pass before what is new is looked at: CPython's own first threshold.
YOUNG = 700
# Seconds between two looks at everything. One costs a few milliseconds here (26 000 objects: 1.5 ms).
FULL_AFTER = 2.0
# How far the count of new objects must have moved for the window to count as having been busy.
STIR = 100


class OnThisThread:
    """Turn the automatic collector off; collect from tick(), called on the window's thread."""

    def __init__(self, clock=time.monotonic):
        # Whoever had the collector off already (a test, an embedding program) keeps it off afterwards.
        self.was_on = gc.isenabled()
        # Seconds that only go forward (a test passes its own).
        self.clock = clock
        gc.disable()
        # When everything was last looked at, and the count of new objects right after.
        self.full_at, self.count_then = clock(), gc.get_count()[0]
        # Something was made or freed since then.
        self.stirred = False

    def tick(self):
        """One look from the window's thread. Returns the generation collected (0: what is new, 2: everything)
        or None when there was nothing to do."""
        count = gc.get_count()[0]
        if abs(count - self.count_then) >= STIR:
            # Made (the count rose) or freed (it fell): a page was built or left.
            self.stirred = True
        if self.stirred and self.clock() - self.full_at >= FULL_AFTER:
            gc.collect()
            self.full_at, self.count_then, self.stirred = self.clock(), gc.get_count()[0], False
            return 2
        if count >= YOUNG:
            # Generation 0 is what was made since the last pass: cheap, and most garbage dies young.
            gc.collect(0)
            self.stirred = True
            return 0
        return None

    def stop(self):
        """The window is going: the automatic collector comes back as it was."""
        if self.was_on:
            gc.enable()
