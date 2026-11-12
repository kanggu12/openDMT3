"""The server an installer handed out by a server's site is set up for, and the hand-over from the installer to the
launcher (as the OpenDMTQ PC client does it, with its own mark).

The site adds an end to openDMT3-win-Setup.exe as it hands it out (server/web/pages.py): the server's details as JSON, their
length in 4 bytes (little-endian), and OPENDMT3-PRESET1:

    <{"version": 1, "url": "http://host:port", "name": "host:port"}><length><OPENDMT3-PRESET1>

The installer reads the end from its own file and, once it has installed, leaves the details in the launcher's folder
as preset.json; the launcher takes them at its next start and plays on that server from then on, its address filled
in for the guide's LOG IN (or Online) to connect. An installer from a release has no end and changes nothing.

Plain Python, no window and no network: the site, the installer and the launcher all use it.
"""

import json
import os
import struct
import tempfile

MAGIC = b"OPENDMT3-PRESET1"
FORMAT = 1
# The details are a few hundred bytes; anything far longer is no server's end.
LIMIT = 64 * 1024
# The hand-over file in the launcher's folder.
FILE_NAME = "preset.json"


def _valid(details):
    """The details when they are a server's address and name in a format this launcher reads, else None."""
    if not isinstance(details, dict) or details.get("version") != FORMAT:
        return None
    url = details.get("url")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")) or len(url) > 300:
        return None
    name = details.get("name")
    return {"url": url.rstrip("/"), "name": name if isinstance(name, str) and name.strip() else url}


def tail(url, name):
    """The end for a server, as the site adds it to the installer it hands out."""
    data = json.dumps({"version": FORMAT, "url": url, "name": name}, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    return data + struct.pack("<I", len(data)) + MAGIC


def read(path):
    """The server an installer's file is set up for, {"url", "name"}, or None (no end, or one that cannot be read)."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            # The length and the mark come last.
            if size < len(MAGIC) + 4:
                return None
            f.seek(size - len(MAGIC) - 4)
            end = f.read(len(MAGIC) + 4)
            if end[4:] != MAGIC:
                return None
            length = struct.unpack("<I", end[:4])[0]
            if not 0 < length <= LIMIT or length > size - len(MAGIC) - 4:
                return None
            f.seek(size - len(MAGIC) - 4 - length)
            details = json.loads(f.read(length).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError, struct.error):
        return None
    return _valid(details)


def hand_over(details, folder):
    """Leave the server for the launcher to take at its next start (the installer, once it has installed)."""
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".preset-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"version": FORMAT, "url": details["url"], "name": details["name"]}, f, ensure_ascii=False)
    os.replace(tmp, os.path.join(folder, FILE_NAME))


def take(folder):
    """The server an installer left, once: {"url", "name"}, or None. The file goes either way: one that cannot be read
    would otherwise be read again at every start."""
    path = os.path.join(folder, FILE_NAME)
    try:
        with open(path, encoding="utf-8") as f:
            details = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        details = None
    try:
        os.remove(path)
    except OSError:
        pass
    return _valid(details)
