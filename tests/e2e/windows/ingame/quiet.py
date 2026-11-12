"""How busy the machine is with work that is not this test's (tests/e2e/windows/ingame.sh).

    python3 quiet.py SAMPLES

SAMPLES holds a line every two seconds while the game runs: "MS USAGE_US LOAD1", the monotonic clock in milliseconds,
the CPU time the test's container has used in all (its cgroup's usage_usec) and the 1-minute load average then.
Prints "LOAD1 OURS OTHERS" for the newest line: the 1-minute load average, the CPUs our container kept busy over the
minute before it (its CPU time over that minute, in CPUs: the game alone keeps about a dozen rendering threads busy on
Wine's software renderer, which the load average counts), and the others' share, the load average less ours (never
under 0). With less than a minute of lines, over all of them; with fewer than two lines, ours is not known and the
others' share is the whole load average.
"""
import sys


def main(path):
    lines = []
    for line in open(path):
        parts = line.split()
        if len(parts) == 3:
            try:
                lines.append((int(parts[0]), int(parts[1]), float(parts[2])))
            except ValueError:
                continue
    if not lines:
        print("0.0 0.0 0.0")
        return
    now, used, load = lines[-1]
    # The line a minute before the newest (or the oldest there is).
    then = next((l for l in reversed(lines) if now - l[0] >= 60000), lines[0])
    ours = (used - then[1]) / 1e6 / ((now - then[0]) / 1000.0) if now > then[0] else 0.0
    print("%.2f %.2f %.2f" % (load, ours, max(0.0, load - ours) if now > then[0] else load))


if __name__ == "__main__":
    main(sys.argv[1])
