"""Every message between the game and its server: the header byte, the direction, the size.

A message is a header byte, seven bytes the game leaves at zero, then the body from offset 8. There is no length
field: each side knows each header's size. The game registers every message it accepts with its size and drops
the connection on any other header, so the sizes here are exact, not limits. Names follow what the client's
handlers do where that is known; the rest are left as plain numbers until they are understood.
"""

import struct

HEADER_SIZE = 8

# Server to client: the size the client registered for each header (CPacketAnalyzer::RegisterPacketInfo).
TO_CLIENT = {
    0x01: 14, 0x03: 61, 0x06: 8, 0x0B: 8, 0x1E: 8, 0x1F: 145, 0x20: 224, 0x21: 184, 0x22: 24, 0x23: 220,
    0x24: 16, 0x44: 29, 0x46: 29, 0x48: 29, 0x4A: 29, 0x4C: 29, 0x4E: 30, 0x50: 29, 0x52: 29, 0x59: 14,
    0x5A: 23, 0x5B: 16, 0x5C: 20, 0x5D: 14, 0x5F: 39, 0x64: 9, 0x65: 166, 0x66: 8, 0x67: 16, 0x68: 18,
    0x69: 13, 0x6A: 9, 0x6C: 12, 0x76: 24, 0x77: 24, 0x7D: 656, 0x7E: 2536, 0x7F: 805, 0x80: 805, 0x81: 805,
    0x8C: 63, 0x8D: 136, 0x8E: 16,
}

# Client to server: the size each sending function passes. 0x55 alone carries its total size (u16 at offset 2).
TO_SERVER = {
    0x02: 48, 0x07: 8, 0x0A: 8, 0x53: 13, 0x5E: 8, 0x60: 28, 0x61: 116, 0x62: 136, 0x63: 32, 0x6E: 155,
    0x71: 116, 0x72: 49, 0x73: 49, 0x78: 120, 0x79: 16, 0x7A: 16, 0x7B: 20, 0x7C: 20, 0x82: 72,
}
VARIABLE_TO_SERVER = {0x55}
# No message is anywhere near this; a size above it means the stream is out of step.
MAX_SIZE = 8192

# The client's login messages: a card number (0x60, 0x62), or an ID with its password's MD5 (0x61). What logs a player
# in is never kept or logged as bytes, handled or not (server.dispatch).
CARRIES_SECRETS = frozenset((0x60, 0x61, 0x62))

NAMES = {
    0x01: "HandshakeRequest", 0x02: "HandshakeAnswer", 0x03: "HandshakeResult", 0x06: "Ping", 0x07: "Pong",
    0x0A: "Alive", 0x0B: "AliveAck", 0x5E: "OnlineNotify", 0x5F: "MusicHiScoreAck", 0x60: "CardAuth",
    0x61: "IdAuth", 0x62: "Join", 0x64: "AuthInAck", 0x65: "UserInfo",
}


def name(header):
    """A header's name for logs: its known name, or its number."""
    return NAMES.get(header, "0x%02x" % header)


class FrameError(Exception):
    """The stream from the client cannot be cut into messages (an unknown header or an impossible size)."""


def size_to_server(first_block):
    """The size of the client message starting with this decrypted first block (8 bytes)."""
    header = first_block[0]
    if header in VARIABLE_TO_SERVER:
        size = struct.unpack_from("<H", first_block, 2)[0]
    else:
        size = TO_SERVER.get(header)
    if size is None:
        raise FrameError("unknown header 0x%02x from the client" % header)
    if not HEADER_SIZE <= size <= MAX_SIZE:
        raise FrameError("impossible size %d for header 0x%02x" % (size, header))
    return size


def blank(header):
    """A server message of the right size, zero apart from its header."""
    msg = bytearray(TO_CLIENT[header])
    msg[0] = header
    return msg


def _text(raw):
    """A fixed-width text field: up to the first zero byte, as ASCII (the game's fields are plain ASCII)."""
    return raw.split(b"\0", 1)[0].decode("ascii", "replace")


def _put_text(msg, offset, width, text):
    """Write text into a fixed-width field, cut to fit and zero-padded."""
    data = text.encode("ascii", "replace")[:width - 1]
    msg[offset:offset + width] = data + bytes(width - len(data))


# ------------------------------------------------------------------------------------------- handshake


def handshake_request(seed, index0, index1):
    """0x01: the seed that restarts both cipher states, and two table places the client must answer with."""
    msg = blank(0x01)
    struct.pack_into("<I", msg, 8, seed)
    msg[12], msg[13] = index0, index1
    return bytes(msg)


class HandshakeAnswer:
    """0x02 as read: the machine value, the two table words, the masked machine key, the client version."""

    def __init__(self, msg, index0, index1, table):
        self.machine = struct.unpack_from("<I", msg, 8)[0]
        self.word0, self.word1 = struct.unpack_from("<II", msg, 12)
        # The client hides an 8-byte machine key with the two words it was asked for.
        mask = ((table[index1] << 7) | table[index0]) & 0xFFFFFFFFFFFFFFFF
        self.machine_key = struct.unpack_from("<Q", msg, 20)[0] ^ mask
        self.version = _text(msg[28:48])
        # The words must be the ones asked for; anything else is not this game's client (or its table).
        self.words_match = (self.word0, self.word1) == (table[index0], table[index1])


def handshake_result(ok=True, server_name="openDMT3", group=1, group_name="openDMT3"):
    """0x03: 1 lets the client online (the title's NET turns green); the names are shown nowhere known."""
    msg = blank(0x03)
    msg[8] = 1 if ok else 0
    _put_text(msg, 9, 20, server_name)
    struct.pack_into("<I", msg, 29, group)
    _put_text(msg, 33, 20, group_name)
    return bytes(msg)


def ping():
    """0x06: the server's ping; the client answers 0x07 at once."""
    return bytes(blank(0x06))


def alive_ack():
    """0x0B: the answer to the client's 0x0A; without it the client reconnects after about a minute."""
    return bytes(blank(0x0B))


# ------------------------------------------------------------------------------------------------ login

CARD_LENGTH = 20            # the card number field of 0x60 and 0x62

# 0x64 results the client acts on (proven on screen with the card login).
AUTH_OK = 0x07              # "Authentication ... completed", then mode select with the DJ card
AUTH_FAILED = 0x0E          # "Membership authentication failed"; the client tries again, then back to the card screen


def card_number(msg):
    """0x60 CardAuth: the card number the reader gave the game."""
    return _text(msg[8:8 + CARD_LENGTH])


def auth_in_ack(code):
    """0x64: the login's result (send 0x65 first on success, or the DJ card shows no name)."""
    msg = blank(0x64)
    msg[8] = code
    return bytes(msg)


def _put_wide(msg, offset, chars, text, closed=True):
    """A UTF-16LE field of `chars` units; the last is the terminating zero unless `closed` is False (a field the
    game reads by its size, the next field's zero bytes ending it).

    The text is cut to fit by units, never in the middle of a character that takes two (a surrogate pair),
    so the message keeps its size whatever the name holds.
    """
    data = text.encode("utf-16-le")
    limit = (chars - 1 if closed else chars) * 2
    if len(data) > limit:
        data = data[:limit]
        # A high surrogate (D800-DBFF) left last would be half a character: drop it too.
        if 0xD8 <= data[-1] <= 0xDB:
            data = data[:-2]
    msg[offset:offset + chars * 2] = data + bytes(chars * 2 - len(data))


EXP_AT = 16                 # experience: the game shows the level its own table gives it (expTitle)
DJ_NAME_AT = 20             # where the game reads the DJ name in 0x65 (9 UTF-16 units, the last a zero)
ICON_AT = 42                # the icon's number in the game's icon table (0: the no-card silhouette)
TITLE_AT = 46               # the DJ card's title plate: a u32, (pattern number << 16) | plate number
COMMENT_STYLE_AT = 50       # the comment's letters: 1 white with an outline (0 draws them clear: no comment shows)
COMMENT_AT = 54             # one line over the plate, 12 UTF-16 units up to the note skin at 78 (always 0 here)
COMMENT_CHARS = 12
ICON = 1                    # the basic DJ icon, a new player's
# The Platinum Crew plate with no pattern over it: what the game's own login screen calls the player (a Platinum
# Crew member), and the value proven on screen. Plate and pattern numbers come from the game's title tables;
# a number that is in neither leaves the card on its "NEED IDCARD" plate.
TITLE = 0x00008001


def user_info(user_number, dj_name, title=TITLE, exp=0, icon=ICON, comment=""):
    """0x65: the player as the game shows them on the DJ card: their number, the DJ name, the level (from the
    experience), the icon, the title plate and the comment over it. The other fields (MAX points, the note skin,
    the crew, the boosts) stay zero. Each field here was seen on the game's screen with these values; a number
    outside the game's own tables crashed it once (a note skin it has no folder for), so the callers send only
    numbers the tables have (services/cards.py).

    The client reads the fields from the body (the message after its 8-byte head). The DJ name sits at 20: a name
    written at 12 showed only from its fifth character. The title plate at 46 replaces the card's "NEED IDCARD"
    plate; its low 16 bits pick the plate, its high 16 bits a pattern drawn over it (0: none). The comment shows
    only with a letter style (50) that is not clear."""
    msg = blank(0x65)
    struct.pack_into("<I", msg, 8, user_number)
    struct.pack_into("<I", msg, EXP_AT, exp)
    _put_wide(msg, DJ_NAME_AT, 9, dj_name)
    struct.pack_into("<I", msg, ICON_AT, icon)
    struct.pack_into("<I", msg, TITLE_AT, title)
    if comment:
        # White letters with an outline; all 12 places may hold letters (the note skin after them is zero).
        struct.pack_into("<I", msg, COMMENT_STYLE_AT, 1)
        _put_wide(msg, COMMENT_AT, COMMENT_CHARS, comment, closed=False)
    return bytes(msg)


# -------------------------------------------------------------------------------- the song select's records
# The song select shows, for the chart under the cursor, the server's first place (BEST RECORD and its DJ) and the
# player's own best (MY RECORD, MAX COMBO, a trophy on the tile). The game keeps both as lists the server fills:
# its own records with 0x1e then 0x5A lines before 0x65 (it takes the list over as it reads the player), the first
# places with 0x66 then 0x5F lines. Seen on the game's screen with every song's four STAR charts in each list.

SONG_SELECT_MODES = (0, 1)  # the modes the game keeps a player's records for (STAR, POP)
BEST_MODES = (0, 1, 2, 3, 4)  # the first-place lists the game has (it indexes them by mode without a check)
# A song's patterns: the song list has a level for each of four per mode (core/formats/discstock.py), and the song
# select's lists take patterns 1 to 4.
PATTERNS = (1, 2, 3, 4)


def clear_my_records():
    """0x1e: empties the game's list of the player's records (the last player's included) and its player details."""
    return bytes(blank(0x1E))


def my_record(mode, song, pattern, score, combo=0, trophy=0):
    """0x5A: one of the player's records: mode, song, pattern, the trophy on the tile (0 none, 1 bronze, 2 silver,
    3 gold, 4 all combo), the score and the max combo."""
    msg = blank(0x5A)
    struct.pack_into("<BIBBII", msg, 8, mode, song, pattern, trophy, score, combo)
    return bytes(msg)


def clear_bests():
    """0x66: empties the game's first-place lists (one per mode), before they are sent again."""
    return bytes(blank(0x66))


def best_record(mode, song, pattern, score, dj_name):
    """0x5F: one chart's first place: mode, song, pattern, score and the DJ name the song select shows with it."""
    msg = blank(0x5F)
    struct.pack_into("<IIBI", msg, 8, mode, song, pattern, score)
    _put_wide(msg, 21, 9, dj_name)
    return bytes(msg)



# ---------------------------------------------------------------------------------------------- results

RECORD_SIZE = 47            # one stage in 0x6e
RECORDS_AT = 14             # the first stage record's offset; three fit in the 155 bytes
# The mode-select scene stores the pressed button's number as the mode (CModeSelectState::NextState); only 0 and
# 1 ever come in 0x6e (CLUB, CREW RACE and CREW CHALLENGE end with messages of their own).
MODE_NAMES = {0: "STAR", 1: "POP", 2: "CLUB", 3: "CREW RACE", 4: "CREW CHALLENGE"}


def stage_results(msg):
    """0x6e at the end of a session: (user number, mode, last stage cleared, [stage records]).

    Only cleared stages are in it (a failed last stage is left out); an empty slot has song number 0. In each
    record the score (u32 at 7) and the seven counts at 15 are read from one capture: the score is what the
    result screen showed, the counts' order (which judgement is which) is not proven yet.
    """
    user, mode, cleared = struct.unpack_from("<IBB", msg, 8)
    records = []
    for i in range(3):
        at = RECORDS_AT + RECORD_SIZE * i
        raw = bytes(msg[at:at + RECORD_SIZE])
        song = struct.unpack_from("<I", raw, 0)[0]
        if song == 0:
            continue
        records.append({
            "song": song,
            "pattern": raw[4],
            "score": struct.unpack_from("<I", raw, 7)[0],
            "counts": list(struct.unpack_from("<7H", raw, 15)),
            "raw": raw,
        })
    return user, mode, bool(cleared), records
