"""The in-game layer's own cost against its targets (tests/e2e/windows/ingame.sh).

    python3 costs.py play INGAME_LOG MARKS
    python3 costs.py turns INGAME_LOG MARKS

The layer logs a line every two seconds for each kind of part it drew ("layer cost fps chip: N frames, CPU X us a
frame, GPU ..., drawn again K times at A us (longest L), uploaded K times at B us, G GDI drawings in its updates").

play: a run as a player has it, with the phases of ingame/pace.py in MARKS. In the chip's phases (the chip alone on
the screen): its CPU time a frame under 100 us in every line. Over the whole run (its number changes when the frame
rate does: at the game's loads, rarely at a steady 60): each update (its picture drawn again from the kept pieces of
its words, then uploaded) under 200 us at the median of the lines that had one, the longest said; no GDI drawing in
any update. The mark at the top centre, on the screen through every phase of nothing (alone there): its CPU time a
frame under 100 us in every line wholly inside one. The CPU times are the wall clock's around the work, so a busy
machine can only make them longer.

turns: a run with OPENDMT3_LAYER_TIMING=frame, where every frame's chain and layer work is timed whole, the device made
idle before it and after it ("layer cost frame: the chain and the layer X us a frame"), and MARKS holds turns of a
part shown ("chip", "bar", "question") each followed by one with it gone ("off-chip", ...). Each turn's whole time a
frame with the part, less the turn right after without it, is what the part adds a frame as it is drawn (its state,
its draws, the blur's passes for a panel); the median over the turns is judged (the machine's load moves both halves
of a turn alike, and a stall falls in one turn, not in the median). The chip's under 200 us; the bar's and the
question's said.
"""
import re
import sys

LINE = re.compile(r"^(\d+) layer cost ([a-z ]+): (\d+) frames, CPU ([\d.]+) us a frame, (.*)$", re.M)
FRAME = re.compile(r"^(\d+) layer cost frame: the chain and the layer ([\d.]+) us a frame", re.M)


def phases(marks):
    """The phases in order: (name, start ms, end ms)."""
    out, open_at = [], {}
    for line in marks.splitlines():
        parts = line.split()
        # "NAME start|end MS", with the machine's load after it in ingame/pace.py's rounds.
        if len(parts) < 3:
            continue
        if parts[1] == "start":
            open_at[parts[0]] = int(parts[2])
        elif parts[0] in open_at:
            out.append((parts[0], open_at.pop(parts[0]), int(parts[2])))
    return out


def median(values):
    values = sorted(values)
    return values[len(values) // 2] if values else None


def play(log, marks):
    spans = [(s, e) for name, s, e in phases(marks) if name == "chip"]
    cpu, updates, longest, gdi = [], [], [], 0
    for m in LINE.finditer(log):
        at, kind, rest = int(m.group(1)), m.group(2), m.group(5)
        if kind != "fps chip":
            continue
        # A line covers the two seconds before it: its CPU a frame judged when wholly inside a chip phase.
        if any(s + 2000 <= at <= e for s, e in spans):
            cpu.append(float(m.group(4)))
        again = re.search(r"drawn again \d+ times at ([\d.]+) us \(longest ([\d.]+)\), uploaded \d+ times at ([\d.]+) us",
                          rest)
        if again:
            updates.append(float(again.group(1)) + float(again.group(3)))
            longest.append(float(again.group(2)) + float(again.group(3)))
        g = re.search(r"(\d+) GDI drawings in its updates", rest)
        gdi += int(g.group(1)) if g else 0
    print("  the chip alone: %d lines; CPU a frame %s us; updates (drawn again and uploaded) %s us at the median of "
          "the lines, the longest %s us; GDI drawings in its updates %d" % (
              len(cpu), "%.1f to %.1f" % (min(cpu), max(cpu)) if cpu else "none",
              "%.1f" % median(updates) if updates else "none", "%.1f" % max(longest) if longest else "none", gdi))
    # The mark: alone on the screen in the phases of nothing (it shows whenever nothing else is at the top).
    nothing = [(s, e) for name, s, e in phases(marks) if name == "nothing"]
    mark = [float(m.group(4)) for m in LINE.finditer(log)
            if m.group(2) == "mark" and any(s + 2000 <= int(m.group(1)) <= e for s, e in nothing)]
    print("  the mark alone: %d lines; CPU a frame %s us" % (
        len(mark), "%.1f to %.1f" % (min(mark), max(mark)) if mark else "none"))
    ok = cpu and max(cpu) < 100 and updates and median(updates) < 200 and gdi == 0 and mark and max(mark) < 100
    return 0 if ok else 1


def turns(log, marks):
    lines = [(int(m.group(1)), float(m.group(2))) for m in FRAME.finditer(log)]
    order = phases(marks)

    def mean_in(s, e):
        # The lines wholly inside the phase (each covers the two seconds before it).
        vals = [v for t, v in lines if s + 2000 <= t <= e]
        return sum(vals) / len(vals) if vals else None

    result = 0
    for part in ("chip", "bar", "question"):
        diffs = []
        for i, (name, s, e) in enumerate(order):
            if name == part and i + 1 < len(order) and order[i + 1][0] == "off-" + part:
                on, off = mean_in(s, e), mean_in(order[i + 1][1], order[i + 1][2])
                if on is not None and off is not None:
                    diffs.append(on - off)
        if not diffs:
            print("  %-9s no turn with whole lines" % part)
            result = 1 if part == "chip" else result
            continue
        mid = median(diffs)
        print("  %-9s adds %+.0f us a frame at the median of %d turns (from %+.0f to %+.0f)" % (
            part, mid, len(diffs), min(diffs), max(diffs)))
        if part == "chip" and mid >= 200:
            result = 1
    return result


if __name__ == "__main__":
    mode, text, marks = sys.argv[1], open(sys.argv[2]).read(), open(sys.argv[3]).read()
    sys.exit(play(text, marks) if mode == "play" else turns(text, marks))
