"""Tests for the first-place webhook (services/notify.py): a line when a first place changes hands, none for a
player beating their own record or a chart's first clear, and a chat that does not answer never reaches the game."""

import http.server
import json
import os
import shutil
import tempfile
import threading
import unittest

from opendmt3.server import db
from opendmt3.server.services import accounts, notify, records


class Chat(http.server.BaseHTTPRequestHandler):
    """A webhook on this PC that keeps what it is sent."""
    got = []

    def do_POST(self):
        Chat.got.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


class WebhookTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        with open(os.path.join(self.tmp, "catalog.json"), "w", encoding="utf-8") as f:
            json.dump({"songs": [{"number": 56, "title": "Made-up Song", "star": [3, 7, 0, 0], "pop": [0] * 4}]}, f)
        self.db = db.connect(os.path.join(self.tmp, "openDMT3.sqlite"))
        store = accounts.Accounts(self.db)
        self.nova = store.create("NOVA", "pass1234", "DJ NOVA")
        self.rio = store.create("RIO", "pass1234", "RIO")
        self.plays = records.Records(self.db)
        self.said = []
        self.hook = notify.Webhook("http://127.0.0.1:9/unused", self.tmp, post=self.said.append)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)

    def clear(self, row, score):
        """What the game server's stage_results does for one record."""
        record = {"song": 56, "pattern": 2, "score": score, "counts": [0] * 7, "raw": bytes(47)}
        before = self.plays.top(0, 56, 2)
        self.plays.add(row["id"], "198.51.100.7:1", 0, record)
        if before is not None and before[0] != row["id"] and score > before[2]:
            self.hook.new_top(row["dj_name"], before[1], 0, record)

    def test_only_a_first_place_taken_from_someone_else_is_told(self):
        self.clear(self.nova, 500000)      # the chart's first clear: not told
        self.clear(self.nova, 600000)      # NOVA beats NOVA: not told
        self.clear(self.rio, 550000)       # below first place: not told
        self.assertEqual(self.said, [])
        self.clear(self.rio, 700000)       # RIO takes it from NOVA
        self.assertEqual(self.said, ["RIO took first place on Made-up Song (STAR · Pattern 2 · Lv 7) with 700,000, "
                                     "ahead of DJ NOVA."])

    def test_a_dj_name_never_calls_the_whole_chat(self):
        server = http.server.HTTPServer(("127.0.0.1", 0), Chat)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            hook = notify.Webhook("http://127.0.0.1:%d/hook" % server.server_address[1], self.tmp)
            # DJ names a player chose to call everyone: Discord's and Slack's ways of doing it.
            self.assertTrue(hook.send("@everyone <!here> <@U123> & took first place"))
        finally:
            server.shutdown()
        got = Chat.got[-1]
        # Discord: mentions parsed from nothing, so the text pings nobody; Slack: the brackets are only text.
        self.assertEqual(got["allowed_mentions"], {"parse": []})
        self.assertEqual(got["content"], "@everyone <!here> <@U123> & took first place")
        self.assertEqual(got["text"], "@everyone &lt;!here&gt; &lt;@U123&gt; &amp; took first place")

    def test_the_post_reaches_a_webhook_and_a_dead_one_is_only_logged(self):
        server = http.server.HTTPServer(("127.0.0.1", 0), Chat)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            hook = notify.Webhook("http://127.0.0.1:%d/hook" % server.server_address[1], self.tmp)
            self.assertTrue(hook.send("hello"))
            self.assertEqual(Chat.got[-1], {"content": "hello", "allowed_mentions": {"parse": []}, "text": "hello"})
        finally:
            server.shutdown()
        dead = notify.Webhook("http://127.0.0.1:%d/hook" % server.server_address[1], self.tmp)
        with self.assertLogs("opendmt3.notify", level="WARNING"):
            self.assertFalse(dead.send("nobody hears"))


if __name__ == "__main__":
    unittest.main()
