"""What the layer's parts do to the frames, judged fairly (tests/e2e/windows/ingame.sh).

    python3 pace.py INGAME_LOG MARKS [QUIET]

MARKS holds one line a phase edge, "NAME start|end MS [LOAD1 OURS OTHERS]", on the clock of the layer's log (the
monotonic clock in milliseconds, the same in the test's shell and in Wine), with the machine's load then as
ingame/quiet.py gives it: phases of a part shown (chip, bar, question, menu, toast) in turn with phases of nothing
shown ("nothing") between them. The layer's log has a counter line every two seconds ("frames: R a second, frame time
.. ms (sd S, ..."); the lines whose whole two seconds lie inside a phase are its windows. A window holds 60 when it
counts 59.5 a second or more with a spread under 0.5 ms; a phase holds 60 when it has at least two windows and most
of them hold (what openDMT3 adds is in every frame it draws, so it would show in every window; a stall of the machine
shows in one). The same rule for the game alone and for a part.

A part is judged only on a quiet machine and where the game alone held 60 next to it: with QUIET given, the others'
share of the load (OTHERS) at each edge of the part's phase and of the nothing phase next to it under QUIET; and that
nothing phase (just before or just after) holding 60, the same kind of stretch (Wine's software renderer misses 60 by
itself in some). There it must hold 60 too. Exit 0 when every part had such a phase and each held 60; 1 when a judged
phase did not; 2 when a part has no such phase yet (more rounds, or the machine was not quiet). Prints every phase with
its windows and the others' load.
"""
import re
import sys


def windows(log):
    """The counter's lines: (end ms, start ms, rate, spread), each window from the line before to its own."""
    lines = [(int(m.group(1)), float(m.group(2)), float(m.group(3))) for m in re.finditer(
        r"^(\d+) frames: ([\d.]+) a second, frame time [\d.]+ ms \(sd ([\d.]+)", log, re.M)]
    return [(end, prev_end, rate, sd) for (prev_end, _, _), (end, rate, sd) in zip(lines, lines[1:])]


def phases(marks):
    """The phases in order: (name, start ms, end ms, the others' load at its start and end, or None)."""
    out, open_at = [], {}
    for line in marks.splitlines():
        parts = line.split()
        if len(parts) not in (3, 6):
            continue
        name, edge, ms = parts[0], parts[1], int(parts[2])
        others = float(parts[5]) if len(parts) == 6 else None
        if edge == "start":
            open_at[name] = (ms, others)
        elif name in open_at:
            start, at_start = open_at.pop(name)
            loads = [x for x in (at_start, others) if x is not None]
            out.append((name, start, ms, loads))
    return out


def held(wins):
    """Whether most of these windows (two at least) hold 60 evenly."""
    good = sum(1 for _, _, rate, sd in wins if rate >= 59.5 and sd < 0.5)
    return len(wins) >= 2 and 2 * good > len(wins)


def quiet(loads, limit):
    """Whether the others' load stayed under the limit at a phase's edges (always, with no limit)."""
    return limit is None or (bool(loads) and max(loads) < limit)


def main(log_path, marks_path, limit=None):
    wins = windows(open(log_path).read())
    order = phases(open(marks_path).read())
    inside = [[w for w in wins if w[1] >= start and w[0] <= end] for _, start, end, _ in order]
    judged, failed = {}, []
    # Why the parts not judged were not: a busy machine, or the game alone missing 60 next to them on a quiet one.
    busy = slow = 0
    for i, (name, _, _, loads) in enumerate(order):
        mark = ""
        if name != "nothing":
            # The game alone next to it, on the same kind of stretch and a quiet machine: the nothing phase before or
            # after.
            near = [j for j in (i - 1, i + 1) if 0 <= j < len(order) and order[j][0] == "nothing"]
            if not quiet(loads, limit):
                busy += 1
                mark = "not judged: the machine was busy (others' load over %.1f)" % limit
            elif any(held(inside[j]) and quiet(order[j][3], limit) for j in near):
                judged[name] = judged.get(name, 0) + 1
                if held(inside[i]):
                    mark = "judged: held 60"
                else:
                    mark = "judged: DID NOT hold 60"
                    failed.append(name)
            else:
                slow += 1
                mark = "not judged: the game alone did not hold 60 next to it on a quiet machine"
        shown = ", ".join("%.1f/%.2f" % (rate, sd) for _, _, rate, sd in inside[i]) or "no whole window"
        load = " [others' load %s]" % "-".join("%.1f" % x for x in loads) if loads else ""
        print("  %-9s %s%s%s" % (name, shown, load, "; " + mark if mark else ""))
    parts = sorted({name for name, _, _, _ in order if name != "nothing"})
    missing = [p for p in parts if not judged.get(p)]
    print("  judged: %s; not judged anywhere: %s; failed: %s" % (
        ", ".join("%s %d" % (p, judged[p]) for p in parts if judged.get(p)) or "none",
        ", ".join(missing) or "none", ", ".join(failed) or "none"))
    # The game alone's own frame rate over the phases of nothing: what the machine gave it.
    alone = [w for (name, _, _, _), wins in zip(order, inside) if name == "nothing" for w in wins]
    held_alone = sum(1 for _, _, rate, sd in alone if rate >= 59.5 and sd < 0.5)
    print("  phases not judged: %d on a busy machine, %d where the game alone missed 60 on a quiet one; the game alone "
          "held 60 in %d of its %d windows" % (busy, slow, held_alone, len(alone)))
    sys.exit(1 if failed else 2 if missing else 0)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else None)
