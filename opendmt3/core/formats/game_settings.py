"""The operator settings file the client keeps next to its rankings (GAME\\game, 20 bytes).

Layout, as the client loads it into its game settings object:
  0   u32  layout version; the client only accepts 0
  4   u32  coins per credit
  8   u32  a further count the client keeps beside it (1 in every copy seen)
  12  u8   a switch (1 in every copy seen), then three unused bytes
  16  u32  free play: 1 starts a game with a touch and shows FREE PLAY, 0 asks for coins
"""

import struct

SIZE = 20
_FMT = struct.Struct("<IIIB3sI")


class GameSettings:
    def __init__(self, version=0, coins_per_credit=1, count=1, switch=1, pad=b"\x00\x00\x00", free_play=0):
        self.version = version
        self.coins_per_credit = coins_per_credit
        self.count = count
        self.switch = switch
        self.pad = pad
        self.free_play = free_play

    @classmethod
    def parse(cls, raw):
        if len(raw) != SIZE:
            raise ValueError("game settings file is %d bytes, expected %d" % (len(raw), SIZE))
        return cls(*_FMT.unpack(raw))

    def build(self):
        # The unused bytes are written back as found, so an untouched file stays byte for byte the same.
        return _FMT.pack(self.version, self.coins_per_credit, self.count, self.switch, self.pad, self.free_play)
