"""The judgement line's watch (native/cardreader/line.c, OPENDMT3_LINE_WATCH) read back: what the game's own frames
did with the line, set beside the score player's clock and the music's. A row's "tick" is the count the score player
counted on its clock, its "shown" the count the game's line, notes and judging read after the update (the count less
the audio offset's lag, score.c; the same with no offset, and absent before 0.4.2's watch).

    python3 tests/e2e/windows/gpu/line.py LINE_CSV [OUT_JSON]
    python3 tests/e2e/windows/gpu/line.py holds LINE_CSV INGAME_LOG [--windows]
    python3 tests/e2e/windows/gpu/line.py presses INGAME_LOG [--last-music] ASKED=EXPECT [ASKED=EXPECT...]
    python3 tests/e2e/windows/gpu/line.py lag LINE_CSV MS

holds judges each hold the layer's log names ("hold: the game held still at frame N" ... "goes on at frame N after S s
held"): between the score's frame N, the last before the hold, and N + 1, the first after it, the score may count only
the time between the two frames' updates that was not held (its ticks times one tick's length, within a tick and 20
ms: the log gives the hold to 10 ms, and the clock the game reads moves in steps of its own). Judged by the clocks
alone, never by the music: the tests' ALSA null device takes the music faster than real time and its cursor jumps.
The music's own move is said beside it; with --windows (a sound clock in real time, gpu/holds.sh) also what each hold
moved the score against the music over 2 s each side. Exit 0 when every hold is judged and held, and at least one is.

presses judges the presses the layer made itself (native/cardreader/press.c, OPENDMT3_PRESS_LATE), those asked ASKED
ms after their notes against an EXPECT: "on" (judged on the note's time), "early:MS" or "late:MS" (judged that many
milliseconds before or after it). A press is made at the first frame the score's own count reaches its time, so it is
judged up to a frame after what was asked: the median within 3 ms before to 20 ms after the expected, and every press
within 3 ms before to 40 ms after it (a slow frame); the distance the game judged by is the count it took less the
note's tick. With --last-music only the presses of the last music the log names count (gpu/judge.sh: the song after
the guest's tutorial, which plays itself), none of them with the judge's own-play flag set. Exit 0 when every ASKED
had 10 presses at least, all judged as expected.

lag judges the count shown against the score's own (the audio offset's lag, score.c): from 3 s into each score and
3 s after each change of its tempo (past the lag's growth, two seconds at most), the score's own count less the one
shown, in milliseconds at the song's tempo, within half a tick of MS in every frame counted. Exit 0 when so, over 600
frames at least.
"""
import csv
import json
import re
import statistics
import sys



def F32(value):
    """A number as a 32-bit float, as the game stores it (numpy's, imported only by the sums that need it: the holds'
    judgement runs where numpy is not)."""
    import numpy as np

    return np.float32(value)


def shown(r):
    """The count a row's frame showed and judged: its "shown" column, or the score's own count where there is none."""
    value = number(r, "shown", int)
    return value if value is not None else number(r, "tick", int)


def line_pos(tick, row_ticks, width):
    """linemath.c line_pos: the tick's place in its row times the pixels a tick, in floats as the game sums it."""
    if row_ticks <= 0:
        return F32(0)
    t = F32(tick)
    scale = F32(float(width) / float(row_ticks))
    rows = int(float(t) / float(row_ticks))
    before = (rows * row_ticks) & 0xFFFFFFFF
    in_row = F32(float(t) - float(before))
    return F32(float(in_row) * float(scale))


def line_row(tick, row_ticks):
    return int(tick // row_ticks) % 2 if row_ticks > 0 else 0


def line_sixteenth(pos, width):
    cell = int(F32(width) / F32(16.0))
    return int(float(pos) / cell) if cell > 0 else 0


def tick_at(tick, rem, clock, ms_per_tick, at):
    """linemath.c score_tick_at: the game's own steps (in doubles here; the game's own precision is finer)."""
    left = rem - (at - clock) if at > clock else rem
    step = ms_per_tick * 10000.0
    if not step > 0:
        return tick
    if -left > step * 100000:
        whole = int(-left / step)
        tick += whole
        left += whole * step
    while left <= 0:
        tick += 1
        left += step
    return tick


def number(row, key, kind=float):
    """A field of the row, or None when it is empty."""
    value = row.get(key, "")
    if value in ("", None):
        return None
    return kind(value)


def read(path):
    rows = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def spread(values):
    """The median and the range of a list of numbers (None for none)."""
    if not values:
        return None
    return {"n": len(values), "median": statistics.median(values), "min": min(values), "max": max(values)}


def counts(values, digits=2):
    """How often each value comes, the most common first (rounded)."""
    seen = {}
    for v in values:
        k = round(v, digits)
        seen[k] = seen.get(k, 0) + 1
    return sorted(seen.items(), key=lambda kv: -kv[1])[:8]


def holds(csv_path, log_path, windows=False):
    """The holds judged (see the module's words); exit 0 when each passes and one at least is judged."""
    rows = {}
    for r in read(csv_path):
        frame = number(r, "frame", int)
        if frame is not None:
            rows[frame] = r
    # Each hold's frame and its length as the layer's log says it ("... goes on at frame N after S s held").
    held, length = [], {}
    for line in open(log_path, errors="replace"):
        m = re.search(r"hold: the game held still at frame (\d+)", line)
        if m:
            held.append(int(m.group(1)))
        m = re.search(r"hold: the game goes on at frame (\d+) after ([0-9.]+) s held", line)
        if m:
            length[int(m.group(1))] = float(m.group(2)) * 1000.0
    judged = failed = 0
    for n in held:
        a, b = rows.get(n), rows.get(n + 1)
        if not a or not b or a.get("updated") != "1" or b.get("updated") != "1" or n not in length:
            print("  hold at frame %d: not judged (no score counted on both sides of it, or no end in the log)" % n)
            continue
        ms_per_tick = number(a, "ms_per_tick")
        score_ms = (number(b, "tick", int) - number(a, "tick", int)) * ms_per_tick
        # The time between the two updates (the counter read right after each counted its ticks), less the hold: what
        # a score that waits with the game counts. The log gives the hold to 10 ms, and the clock the game reads moves
        # in steps of its own (Windows' timer, or under Wine each call into its server): a tick and 20 ms of room.
        wall_ms = (number(b, "adv_qpc", int) - number(a, "adv_qpc", int)) * 1000.0 / number(a, "qpc_freq", int)
        due_ms = wall_ms - length[n]
        ok = abs(score_ms - due_ms) <= ms_per_tick + 20.0
        judged += 1
        failed += not ok
        ma, mb = number(a, "music_ms"), number(b, "music_ms")
        music = "%.1f ms" % (mb - ma) if ma is not None and mb is not None and ma >= 0 and mb >= 0 else "none"
        print("  hold at frame %d (%.2f s held): the score counted %.1f ms across it, %.1f ms of it not held (the music "
              "played %s; a tick %.2f ms): %s" % (n, length[n] / 1000.0, score_ms, due_ms, music, ms_per_tick,
                                                   "held with the game" if ok else "RAN ON while the game was held"))
    print("  %d holds judged, %d ran on" % (judged, failed))
    if windows:
        # With a sound clock that runs in real time: what each hold moved the score against the music over two
        # seconds each side (the means of the music's position less the score's time, so the music cursor's steps of
        # 10 ms or so average out).
        for n, moved in hold_moves(csv_path, held):
            print("  hold at frame %d: over 2 s each side, the score went %s" % (
                n, "%.1f ms ahead of the music (behind it when negative)" % moved if moved is not None
                else "(too few frames around it)"))
    return 0 if judged and not failed else 1


def hold_moves(csv_path, held, frames=120):
    """For each hold, how far the score went ahead of the music across it: the mean of the music's position less the
    score's time over `frames` counted frames before it, less the same after it (None when either side has fewer than
    half of them)."""
    rows = [r for r in read(csv_path) if r.get("updated") == "1" and r.get("playing") == "1"]
    series, chart, song = [], None, None
    for a, b in zip(rows, rows[1:]):
        key, mb = b.get("music_frame"), number(b, "music_ms")
        if key in (None, "", "-1") or mb is None or mb < 0 or a.get("music_frame") != key:
            chart = None
            continue
        # The score's time from its song's start: the first frame's ticks at its tempo, then each step at its own.
        if chart is None or song != key:
            chart, song = number(a, "tick", int) * number(a, "ms_per_tick"), key
        chart += (number(b, "tick", int) - number(a, "tick", int)) * number(a, "ms_per_tick")
        series.append((number(b, "frame", int), mb - chart))
    out = []
    for n in held:
        before = [v for f, v in series if f <= n][-frames:]
        after = [v for f, v in series if f > n][:frames]
        ok = len(before) >= frames // 2 and len(after) >= frames // 2
        out.append((n, statistics.mean(before) - statistics.mean(after) if ok else None))
    return out


PRESS = re.compile(r"press: music from frame (-?\d+), a note at tick (\d+), asked (\d+) ms after it, pressed at the "
                   r"score's own count ([-+]\d+) \(([-+][0-9.]+) ms\), judged at ([-+]\d+) \(([-+][0-9.]+) ms\): "
                   r"distance (\d+), level (\d+)(?:, the judge playing itself (\d+))?")


def presses(log_path, expects):
    """The layer's own presses judged against what each EXPECT says of those asked so many ms after their notes (see
    the module's words); with --last-music first, only those of the last music the log names."""
    last = expects[:1] == ["--last-music"]
    expects = expects[1:] if last else expects
    found = []
    for line in open(log_path, errors="replace"):
        m = PRESS.search(line)
        if m:
            found.append(m)
    own_play = 0
    if last and found:
        music = max(int(m.group(1)) for m in found)
        found = [m for m in found if int(m.group(1)) == music]
        # Its judge's own-play flag at each press: none of them may be the game's own (the tutorial's is).
        own_play = sum(1 for m in found if m.group(10) and int(m.group(10)))
        print("  the last music's presses only (it started at frame %d): %d of them, its judge playing itself at "
              "%d" % (music, len(found), own_play))
    asked = {}
    for m in found:
        judged, judged_ms, distance = int(m.group(6)), float(m.group(7)), int(m.group(8))
        asked.setdefault(int(m.group(3)), []).append((judged_ms, abs(judged) == distance, int(m.group(9))))
    failed = 0
    for expect in expects:
        late, _, what = expect.partition("=")
        kind, _, ms = what.partition(":")
        want = {"on": 0.0, "early": -float(ms or 0), "late": float(ms or 0)}.get(kind)
        if not late.isdigit() or want is None:
            print("  %r: not ASKED=on, ASKED=early:MS or ASKED=late:MS" % expect)
            failed += 1
            continue
        got = asked.get(int(late), [])
        if len(got) < 10:
            print("  pressed %s ms after their notes: %d presses judged, fewer than 10" % (late, len(got)))
            failed += 1
            continue
        times = [g[0] for g in got]
        median = statistics.median(times)
        # Up to a frame after the time asked (the first frame there), 3 ms before it for the tick's rounding.
        ok = want - 3.0 <= median <= want + 20.0 and all(want - 3.0 <= t <= want + 40.0 for t in times) and \
            all(g[1] for g in got)
        failed += not ok
        levels = {}
        for g in got:
            levels[g[2]] = levels.get(g[2], 0) + 1
        print("  pressed %s ms after their notes: %d presses judged %+.1f ms from them at the median (%+.1f to %+.1f), "
              "expected %s; the game's levels %s; the distance the count judged: %s; %s" % (
                  late, len(got), median, min(times), max(times), what,
                  ", ".join("%d x%d" % (k, levels[k]) for k in sorted(levels, reverse=True)),
                  "every press" if all(g[1] for g in got) else "NOT every press",
                  "as expected" if ok else "NOT as expected"))
    return 0 if not failed and not own_play else 1


def lag(csv_path, ms):
    """The count shown against the score's own, past each score's first 3 s (see the module's words)."""
    played = [r for r in read(csv_path) if r.get("updated") == "1" and r.get("playing") == "1"]
    judged = off = 0
    worst = 0.0
    first = {}
    tempo, since = None, 0
    for r in played:
        tick, seen, per = number(r, "tick", int), shown(r), number(r, "ms_per_tick")
        clock = number(r, "clock", int)
        if None in (tick, seen, per, clock) or per <= 0:
            continue
        # A score's start is where its count was 0; its first 3 s (in its own ticks) are the lag's growth.
        key = clock - int(tick * per * 10000)
        start = first.setdefault(round(key / 1e7), tick)
        # A new tempo makes a new lag in ticks, grown into again: 3 s past each change left out too.
        if per != tempo:
            tempo, since = per, tick
        if (tick - start) * per < 3000 or (tick - since) * per < 3000 and since != start:
            continue
        judged += 1
        gap = (tick - seen) * per - float(ms)
        worst = max(worst, abs(gap))
        off += abs(gap) > per / 2 + 1e-6
    print("  the count shown %s ms behind the score's own in %d of %d frames past each score's first 3 s (the worst "
          "%.2f ms off it)" % (ms, judged - off, judged, worst))
    return 0 if judged >= 600 and not off else 1


def main(argv):
    if argv and argv[0] == "holds":
        sys.exit(holds(argv[1], argv[2], "--windows" in argv[3:]))
    if argv and argv[0] == "presses":
        sys.exit(presses(argv[1], argv[2:]))
    if argv and argv[0] == "lag":
        sys.exit(lag(argv[1], argv[2]))
    rows = read(argv[0])
    played = [r for r in rows if r.get("updated") == "1" and r.get("playing") == "1"]
    out = {"frames": len(rows), "frames_counted": len(played)}
    pos_ok = row_ok = six_ok = 0
    offsets = {}
    for r in played:
        # The line is drawn where the count shown puts it.
        tick, rt, w = shown(r), number(r, "row_ticks", int), number(r, "width")
        pos = number(r, "pos")
        mine = line_pos(tick, rt, w)
        pos_ok += abs(float(mine) - pos) <= 1e-3
        row_ok += line_row(tick, rt) == number(r, "row", int)
        six_ok += line_sixteenth(F32(pos), w) == number(r, "sixteenth", int)
        # The first quad drawn is the main line: its left edge less (or plus, flipped) its place is the row's offset.
        if number(r, "lines", int):
            x0, u0, u1 = number(r, "x0_0"), number(r, "u0_0"), number(r, "u1_0")
            flipped = u0 is not None and u1 is not None and u0 > u1
            key = "%s row %s" % ("flipped" if flipped else "unflipped", r.get("row"))
            offsets.setdefault(key, []).append(round(x0 + pos if flipped else x0 - pos, 2))
    out["place_by_the_sum"] = "%d of %d" % (pos_ok, len(played))
    out["row_by_the_sum"] = "%d of %d" % (row_ok, len(played))
    out["sixteenth_by_the_sum"] = "%d of %d" % (six_ok, len(played))
    out["main_line_offsets"] = {k: counts(v) for k, v in offsets.items()}
    # From each frame's clock, the next frame's tick.
    exact = near = off = 0
    changes = 0
    clock_steps, line_steps, music_steps, music_against_clock = [], [], [], []
    for a, b in zip(played, played[1:]):
        if number(b, "frame", int) != number(a, "frame", int) + 1:
            continue
        ta, tb = number(a, "tick", int), number(b, "tick", int)
        mine = tick_at(ta, number(a, "rem"), number(a, "clock", int), number(a, "ms_per_tick"), number(b, "clock", int))
        exact += mine == tb
        near += abs(mine - tb) == 1
        off += abs(mine - tb) > 1
        changes += number(a, "ms_per_tick") != number(b, "ms_per_tick")
        clock_steps.append((number(b, "clock", int) - number(a, "clock", int)) / 10000.0)
        rt, w = number(a, "row_ticks", int), number(a, "width")
        line_steps.append((tb - ta) * float(F32(float(w) / float(rt))))
        ma, mb = number(a, "music_ms"), number(b, "music_ms")
        if ma is not None and mb is not None and ma >= 0 and mb >= 0:
            music_steps.append(mb - ma)
            music_against_clock.append(mb - number(b, "clock", int) / 10000.0)
    out["next_tick_from_the_clock"] = {"exact": exact, "one_off": near, "more_off": off, "tempo_changes": changes}
    # Gaps of 150 ms or more between two frames the score counted in (a hold, a load, a stall): how far the
    # clock, the score's ticks and the music each went over it.
    gaps = []
    for a, b in zip(played, played[1:]):
        clock_ms = (number(b, "clock", int) - number(a, "clock", int)) / 10000.0
        if clock_ms < 150:
            continue
        score_ms = (number(b, "tick", int) - number(a, "tick", int)) * number(a, "ms_per_tick")
        ma, mb = number(a, "music_ms"), number(b, "music_ms")
        music = round(mb - ma, 1) if ma is not None and mb is not None and ma >= 0 and mb >= 0 else None
        frames = number(b, "frame", int) - number(a, "frame", int)
        gaps.append({"frames": [number(a, "frame", int), number(b, "frame", int)], "clock_ms": round(clock_ms, 1),
                     "score_ms": round(score_ms, 1), "music_ms": music,
                     # What the gap did to the score against the music, and to the frames (at 60 a second) against it.
                     "score_less_music_ms": round(score_ms - music, 1) if music is not None else None,
                     "frames_less_music_ms": round(frames * 1000.0 / 60 - music, 1) if music is not None else None})
    out["gaps"] = gaps
    # Each song's music against its score (a song is the frames with the same music start): the music's position less
    # the score's time from its start (the first frame's ticks at its tempo, then each step at its own), at the first
    # frame, the median and the last. Two runs that differ only in how the frames are held (an audio offset) show
    # whether holding them moves the score against the music.
    songs = {}
    for a, b in zip(played, played[1:]):
        key = number(b, "music_frame", int)
        mb = number(b, "music_ms")
        if key is None or key < 0 or mb is None or mb < 0 or number(a, "music_frame", int) != key:
            continue
        # The score's time from its start: the first frame's ticks at its tempo, then each step at its own.
        s = songs.setdefault(key, {"chart_ms": number(a, "tick", int) * number(a, "ms_per_tick"), "against": [],
                                   "shown_ms": shown(a) * number(a, "ms_per_tick"), "shown_against": []})
        s["chart_ms"] += (number(b, "tick", int) - number(a, "tick", int)) * number(a, "ms_per_tick")
        s["against"].append(mb - s["chart_ms"])
        # The same for the count shown and judged: with an audio offset, the offset more behind the music.
        s["shown_ms"] += (shown(b) - shown(a)) * number(a, "ms_per_tick")
        s["shown_against"].append(mb - s["shown_ms"])
        # The music lock's own measure beside it: the music less the song's frames at 60 a second (this frame is the
        # song's frame number b - key + 1).
        s.setdefault("lock", []).append(mb - (number(b, "frame", int) + 1 - key) * 1000.0 / 60)
    out["songs"] = {str(k): {"frames": len(v["against"]), "music_less_score_ms_first": round(v["against"][0], 1),
                             "median": round(statistics.median(v["against"]), 1), "last": round(v["against"][-1], 1),
                             "music_less_shown_ms_median": round(statistics.median(v["shown_against"]), 1),
                             "music_less_shown_ms_last": round(v["shown_against"][-1], 1),
                             "music_less_frames_ms_first": round(v["lock"][0], 1),
                             "music_less_frames_median": round(statistics.median(v["lock"]), 1),
                             "music_less_frames_last": round(v["lock"][-1], 1)}
                    for k, v in songs.items() if v["against"]}
    out["clock_step_ms"] = {"spread": spread(clock_steps), "most": counts(clock_steps)}
    out["line_step_px"] = {"spread": spread(line_steps), "most": counts(line_steps)}
    out["music_step_ms"] = {"spread": spread(music_steps), "most": counts(music_steps)}
    if music_against_clock:
        base = music_against_clock[0]
        drift = [m - base for m in music_against_clock]
        out["music_less_clock_ms"] = spread(drift)
    # The interrupt time against the performance counter: their difference's spread over the run.
    gaps = []
    for r in rows:
        now, qpc, freq = number(r, "now", int), number(r, "qpc", int), number(r, "qpc_freq", int)
        if now is not None and qpc is not None and freq:
            gaps.append(now / 10.0 - qpc * 1e6 / freq)
    if gaps:
        out["interrupt_less_counter_us"] = spread([g - gaps[0] for g in gaps])
    text = json.dumps(out, indent=1)
    print(text)
    if len(argv) > 1:
        open(argv[1], "w").write(text + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
