"""A line to a chat when someone takes a chart's first place from another player (a Discord or Slack webhook).

The server is started with --webhook URL (or OPENDMT3_WEBHOOK). The post goes out on a thread of its own with a
short timeout: a slow or broken webhook never holds up the game server, and a failure is only logged. Only a
first place taken from someone else is told; a player beating their own record, and a chart's first clear, are not
(a friend server's chat would hear of every song otherwise).

DJ names are the players' own, so the line never calls anyone: Discord is told to make no mention of it (a name like
@everyone stays text), and Slack gets <, > and & escaped (a name like <!here> stays text).
"""

import json
import logging
import threading
import urllib.request

from opendmt3 import __version__
from opendmt3.server import messages
from opendmt3.server.services import catalog

log = logging.getLogger("opendmt3.notify")

TIMEOUT = 5


class Webhook:
    def __init__(self, url, data_dir, post=None):
        self.url = url
        self.data_dir = data_dir
        # Tests pass their own; otherwise each post runs on a thread of its own.
        self.post = post or self._post_later

    def new_top(self, dj_name, previous_dj, mode, record):
        """`dj_name` took first place on a chart from `previous_dj` with the record's score."""
        songs = catalog.load(self.data_dir)
        level = catalog.level(songs, record["song"], mode, record["pattern"])
        chart = "%s · Pattern %d%s" % (messages.MODE_NAMES.get(mode, "MODE %d" % mode), record["pattern"],
                                      " · Lv %d" % level if level else "")
        self.post("%s took first place on %s (%s) with %s, ahead of %s." % (
            dj_name, catalog.title(songs, record["song"]), chart, "{:,}".format(record["score"]), previous_dj))

    def _post_later(self, text):
        threading.Thread(target=self.send, args=(text,), daemon=True, name="webhook").start()

    def send(self, text):
        """Post one line; Discord reads "content", Slack reads "text". Returns True when the chat took it."""
        body = json.dumps({
            # Discord: the text as it is, and no mention made of anything in it (no @everyone, @here, user or role).
            "content": text, "allowed_mentions": {"parse": []},
            # Slack: its three control characters escaped, so <!here>, <!channel> and <@U...> are only text.
            "text": text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"),
        }).encode("utf-8")
        request = urllib.request.Request(self.url, data=body, method="POST",
                                         headers={"Content-Type": "application/json",
                                                  "User-Agent": "openDMT3-server/%s" % __version__})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
                return 200 <= answer.status < 300
        except Exception as e:  # noqa: BLE001  (a chat that does not answer must not reach the game)
            log.warning("the webhook did not take the post: %s", e)
            return False
