"""core/parallel.py: work on a few threads, handed back in order, an error at its own place, nothing left running."""

import threading
import time
import unittest
from unittest import mock

from opendmt3.core import parallel


class OrderedTest(unittest.TestCase):
    def test_results_come_in_the_items_order_from_several_threads(self):
        names = set()

        def slow(n):
            # Later items finish first: the order handed back is still the items'.
            time.sleep(0.002 * (10 - n))
            names.add(threading.current_thread().name)
            return n * n

        with mock.patch.object(parallel, "WORKERS", 4):
            self.assertEqual(list(parallel.ordered(slow, range(10))), [n * n for n in range(10)])
        # On the pool's threads, at most four of them.
        self.assertTrue(names and len(names) <= 4 and all(n.startswith("opendmt3-read") for n in names))

    def test_one_thread_or_one_item_makes_no_pool(self):
        with mock.patch.object(parallel, "WORKERS", 1):
            self.assertEqual(list(parallel.ordered(lambda n: threading.current_thread(), [1, 2])),
                             [threading.current_thread()] * 2)
        self.assertEqual(list(parallel.ordered(lambda n: threading.current_thread(), [1])),
                         [threading.current_thread()])

    def test_an_error_comes_at_its_items_place_and_the_rest_is_dropped(self):
        started = []

        def piece(n):
            started.append(n)
            if n == 2:
                raise ValueError("item 2")
            time.sleep(0.01)
            return n

        got = []
        with mock.patch.object(parallel, "WORKERS", 2):
            with self.assertRaises(ValueError):
                for value in parallel.ordered(piece, range(50)):
                    got.append(value)
        # Everything before it came; the pieces not started when it came were never run.
        self.assertEqual(got, [0, 1])
        self.assertLess(len(started), 50)

    def test_leaving_early_waits_for_the_pieces_running(self):
        running = threading.Event()
        finished = []

        def piece(n):
            running.set()
            time.sleep(0.05)
            finished.append(n)
            return n

        with mock.patch.object(parallel, "WORKERS", 2):
            made = parallel.ordered(piece, range(20))
            self.assertEqual(next(made), 0)
            made.close()
        # Closed: no piece is still running after it (a caller may close the files they read).
        count = len(finished)
        time.sleep(0.1)
        self.assertEqual(len(finished), count)


if __name__ == "__main__":
    unittest.main()
