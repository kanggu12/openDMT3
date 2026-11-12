"""The site's notice: one line the admin sets on the Status page, shown at the top of every page of the site.

It is kept beside the database as notice.json ({"text", "at", "by"}), written to a new file and moved into place, so a
page never reads half of one; without the file there is no notice. Pages read it through files.load: the file is read
again only when it changes, so every page can ask for it.
"""

import json
import os
import threading
import time

from opendmt3.core.errors import Worded
from opendmt3.server.services import files

FILE = "notice.json"
# The longest notice, in characters: one line at the top of a page.
MOST = 200


class NoticeError(Worded, ValueError):
    """A notice the rules refuse: longer than MOST characters, or with characters that are not text. Worded for the
    admin who typed it (errors.py), on the Status page and through the API alike."""


def clean(text):
    """The notice as it is kept: every run of whitespace (line breaks too) one space, nothing at the ends."""
    return " ".join((text or "").split())


def check(text):
    """Refuse a notice (already cleaned) longer than MOST characters, or with control or formatting characters
    (a direction override would turn the page's own words around)."""
    if len(text) > MOST or not text.isprintable():
        # The key gives the Status page its words in the admin's language; the sentence is the API's message.
        raise NoticeError("a notice is one line of up to %d characters" % MOST, "error.notice.long", max=MOST)


def read(data_dir):
    """The notice as kept ({"text", "at", "by"}), or None: no file, an empty one, or one that cannot be read (a
    page goes on without a notice rather than fail)."""
    try:
        kept = files.load(os.path.join(data_dir, FILE))
    except (OSError, ValueError):
        return None
    if not isinstance(kept, dict) or not isinstance(kept.get("text"), str) or not kept["text"]:
        return None
    return kept


def _write(data_dir, text, who="system", now=None):
    """Show `text` (cleaned, then checked) as the notice, or clear it when nothing is left; returns what is shown
    now ("" once cleared)."""
    text = clean(text)
    check(text)
    path = os.path.join(data_dir, FILE)
    if not text:
        # Cleared: no file, no notice.
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        return ""
    os.makedirs(data_dir, exist_ok=True)
    # A new file moved over the old one: readers see the old notice or the new one, never half of either.
    partial = path + ".new"
    with open(partial, "w", encoding="utf-8") as f:
        json.dump({"text": text, "at": int(now if now is not None else time.time()), "by": who}, f,
                  ensure_ascii=False)
    os.replace(partial, path)
    return text


# One write at a time in this process: the site's threads may ask at once, and two writing the same ".new" file
# interleaved into a file that reads as nothing (maintenance off while an admin turned it on).
_WRITING = threading.Lock()


def write(*args, **kwargs):
    """_write(), one at a time (_WRITING)."""
    with _WRITING:
        return _write(*args, **kwargs)
