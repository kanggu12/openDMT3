"""Edit the client's setting.ini without disturbing the rest of it.

The file comes from the game itself (inside its configuration archive), with comments in the client's Korean
code page and Windows line endings. Only the values asked for change; every other byte stays where it was.

The client's reader drops every space inside a value, so a path written here must not contain one.
"""

import re

ENCODING = "cp949"


def decode(raw):
    """Text of a settings file as stored by the game."""
    return raw.decode(ENCODING)


def encode(text):
    """Bytes in the game's code page."""
    return text.encode(ENCODING)


def get_value(text, key):
    """The value of the first line 'key = value' (case-insensitive key, spaces around '=' allowed), or None."""
    m = re.search(r"(?im)^[ \t]*" + re.escape(key) + r"[ \t]*=[ \t]*([^\r\n]*)", text)
    return m.group(1).strip() if m else None


def set_values(text, changes):
    """Return text with each key's value replaced; the spacing around '=' and the line ending are kept.

    Every key must already be in the file: the game reads a fixed set of keys, and a key it does not
    know would be ignored silently, which is worse than an error here.
    """
    for key, value in changes.items():
        if " " in value:
            raise ValueError("the game drops spaces inside values: %r" % value)
        pattern = re.compile(r"(?im)^([ \t]*" + re.escape(key) + r"[ \t]*=[ \t]*)([^\r\n]*)")
        text, n = pattern.subn(lambda m: m.group(1) + value, text, count=1)
        if n != 1:
            raise KeyError("no %r line in the settings file" % key)
    return text
