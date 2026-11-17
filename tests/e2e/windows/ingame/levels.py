"""The mix's level at openDMT3's last stage over the same seconds of a song in two games (tests/e2e/windows/ingame.sh,
the review's L7): the game's own music volume curve, and the music's move by it while the song plays.

    python3 levels.py REFERENCE_LOG MEASURED_LOG

Both logs are the in-game layer's (ingame.log) with OPENDMT3_SOUND_LEVELS on: a line a second with the level of the
mix as it reached the last stage (before the master volume and the equaliser) and the song's place then. The
reference game played the tutorial's song untouched; the measured one started with the music at another percent (or
the same) and had it moved once while the song played (the launcher's --set, or a write of the sound file). Two
windows of the song, the same place in both games: its 1.5 to 5.5 s (the game's own curve between the two start
percents' setting.ini values, 40 log10(value / 127) dB), and the 4 s from 1.5 s after the move was heard (the moved
percent's against the reference's, by the same curve). Each within 1 dB, or the exit status is 1.
"""
import math
import re
import sys

# The layer's level line (mix.c, measuring only): its clock (ms), the writer of the stream, the level, the samples it
# counted, and the song's place (-1 with no song playing).
LEVEL = re.compile(r"^(\d+) mix: level of the stream written by (\S+) over the last second: rms ([0-9.]+) .*, "
                   r"(\d+) samples, the song at (-?\d+) ms")
# The tutorial's song starting (sound.c with the watch: its music in one buffer, played once).
SONG = re.compile(r"^(\d+) sound: stream \S+ \(41943040 bytes, \d+ a second, once\) plays")
# The values the game started with (soundset.c), and a move of the volumes while it runs (sound.c sound_volumes).
START = re.compile(r"^\d+ sound: master \d+ %, music (\d+) %, key sounds (\d+) %")
MOVED = re.compile(r"^(\d+) sound: the music at (\d+) %, the key sounds at (\d+) %")
# A line counts when the song moved about as long as the log's clock did since the line before (within this many ms):
# no hold in its stretch (a held song does not move), whatever a slow frame made of the second's length.
STEADY = 150
# The share of a window the counted seconds must cover, and the window's length after its start (ms).
COVER = 0.9
SPAN = 4000
# The most a window may differ from the game's curve (dB).
LIMIT = 1.0


def game_value(percent):
    """setting.ini's value for a percent: the launcher's values.to_game_volume (never 0)."""
    return max(1, int(round(percent * 127 / 100.0)))


def curve_db(percent):
    """The game's own gain for a percent against 127, measured: 40 log10(value / 127), twice an amplitude's."""
    return 40 * math.log10(game_value(percent) / 127.0)


def read(path):
    """The song's start (the log's clock), the music's percent the game started with, its first move after the song
    started (clock, percent) or None, and the level lines after the song started (clock, rms, samples, place), of the
    stream with the most of them (DirectSound's mix: one stream)."""
    song = start = moved = None
    lines = {}
    for line in open(path, errors="replace"):
        m = START.match(line)
        if m and start is None:
            start = int(m.group(1))
            continue
        m = SONG.match(line)
        if m and song is None:
            song = int(m.group(1))
            continue
        m = MOVED.match(line)
        if m and song is not None and moved is None:
            moved = (int(m.group(1)), int(m.group(2)))
            continue
        m = LEVEL.match(line)
        if m and song is not None and int(m.group(1)) > song:
            lines.setdefault(m.group(2), []).append(
                (int(m.group(1)), float(m.group(3)), int(m.group(4)), int(m.group(5))))
    stream = max(lines.values(), key=len) if lines else []
    return song, start, moved, stream


def place_at(stream, clock):
    """The song's place (ms) at a moment of the log's clock, from the first counted line after it."""
    for at, _rms, _n, place in stream:
        if at >= clock and place >= 0:
            return place - (at - clock)
    return None


def window(stream, w0, w1):
    """The level (dBFS) over the song's w0 to w1 ms: each counted second's mean square, weighted by how much of the
    window its stretch of the song covers; None when the counted seconds cover under COVER of it."""
    energy = covered = 0.0
    last = None
    for at, rms, _n, place in stream:
        if (place >= 0 and last is not None and last[1] >= 0 and place > last[1]
                and abs((place - last[1]) - (at - last[0])) <= STEADY):
            # The stretch of the song this line's time played, against the window.
            overlap = min(place, w1) - max(last[1], w0)
            if overlap > 0:
                energy += rms * rms * overlap
                covered += overlap
        last = (at, place)
    if covered < COVER * (w1 - w0):
        return None
    return 10 * math.log10(energy / covered) if energy > 0 else float("-inf")


def main(reference, measured):
    ref_song, ref_start, _ref_moved, ref = read(reference)
    song, start, moved, mine = read(measured)
    if ref_song is None or song is None or ref_start is None or start is None:
        print("  not measured: the song's start or the starting volumes are not in both logs")
        return 1
    if moved is None:
        print("  not measured: no move of the music's volume after the song started in the measured log")
        return 1
    ok = True
    # The game's own curve: the song's first seconds at the two start percents.
    a_ref, a_mine = window(ref, 1500, 1500 + SPAN), window(mine, 1500, 1500 + SPAN)
    want = curve_db(start) - curve_db(ref_start)
    if a_ref is None or a_mine is None:
        print("  the song's 1.5 to 5.5 s: not covered in both logs (%s, %s)" % (a_ref, a_mine))
        ok = False
    else:
        print("  the song's 1.5 to 5.5 s: %.2f dBFS at %d %%, %.2f at %d %%: %+.2f dB (the game's curve %+.2f dB)"
              % (a_ref, ref_start, a_mine, start, a_mine - a_ref, want))
        ok &= abs((a_mine - a_ref) - want) <= LIMIT
    # The move: from 1.5 s after it was heard, the moved percent against the reference's.
    at = place_at(mine, moved[0])
    if at is None:
        print("  the move: the song's place when it was heard is not in the log")
        return 1
    b0 = at + 1500
    b_ref, b_mine = window(ref, b0, b0 + SPAN), window(mine, b0, b0 + SPAN)
    want = curve_db(moved[1]) - curve_db(ref_start)
    if b_ref is None or b_mine is None:
        print("  the move to %d %% at %.1f s of the song: its %.1f to %.1f s not covered in both logs (%s, %s)"
              % (moved[1], at / 1000.0, b0 / 1000.0, (b0 + SPAN) / 1000.0, b_ref, b_mine))
        ok = False
    else:
        print("  the move from %d %% to %d %% at %.1f s of the song, its %.1f to %.1f s: %.2f dBFS at %d %%, %.2f "
              "moved: %+.2f dB (the game's curve %+.2f dB)" % (start, moved[1], at / 1000.0, b0 / 1000.0,
                                                              (b0 + SPAN) / 1000.0, b_ref, ref_start, b_mine,
                                                              b_mine - b_ref, want))
        ok &= abs((b_mine - b_ref) - want) <= LIMIT
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
