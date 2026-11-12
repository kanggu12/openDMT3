"""A song run of gpu/song.sh in numbers, into OUT_DIR/results.json and one block of lines:

    python3 song.py OUT_DIR [OUT_DIR ...]
    python3 song.py compare A_DIR[,A_DIR...] B_DIR[,B_DIR...]

The song is the second play of the game's 40 MB music buffer (the tutorial's is the first, as song.sh plays them),
from the frame its music started at to the one it stopped at (the layer's sound lines, OPENDMT3_SOUND_WATCH). Over
it:
  - the frames: the layer's series (OPENDMT3_INGAME_FRAMES; line k is the length of the frame that ends with present
    k + 2): the rate, the mean, the spread, the slowest 1 %, the longest, the share over 20 ms; and the music against
    the frames at its stop (the music played less the frames counted at 60 a second: 0 is notes on their music);
  - the input latency: each press's time from its message to its frame done on the GPU (OPENDMT3_LATENCY_WATCH), and
    where the layer gives them its parts (to the game's read of it, from the read to the present, from the present to
    done), with whether the frame that carried it was started just in time, and each press's time from the game's read
    to done (the part a build changes: the wait for the game's next read falls anywhere in a frame either way);
  - starting frames just in time: the layer's two-second lines over the song (frames held back, how far before their
    tick, their work, the spare, frames that missed their tick);
  - the container's CPU time over the song, in cores (song.sh reads its cgroup at the song's start and stop).

compare pools the songs' presses of the runs on each side (a comma between runs) and prints each side's medians, from
the press and from the game's read to done, and their difference with a 95 % interval by resampling the presses (4000
draws, the same every time).
"""
import random
import json
import re
import statistics
import sys


def pct(values, q):
    """The q-th percentile of a list by nearest rank."""
    s = sorted(values)
    return s[min(len(s) - 1, max(0, int(-(-q * len(s) // 100)) - 1))]


def song_of(log):
    """The song's play in a run's log: (its stream, the frame and the log's time it started at), or None. The second
    play of the 40 MB buffer, as song.sh takes it (a later one, on the result screen say, is not the song)."""
    plays = [(m.group(1), int(m.group(2)), int(m.group(0).split()[0])) for m in re.finditer(
        r"^\d+ sound: stream (\S+) \(41943040 bytes, \d+ a second, once\) plays from frame (\d+)", log, re.M)]
    return plays[1] if len(plays) > 1 else None


def song_presses(log, start_ms, stop_ms):
    """The presses in the song, each as its latency line's match (the log's time, the whole, and where given its parts
    and how its frame started)."""
    return [m for m in re.finditer(
        r"^(\d+) latency: press to its frame done ([\d.]+) ms(?: \(to the game's read ([\d.]+), read to present "
        r"([\d.]+), present to done ([\d.]+);.*?(started just in time|started at once))?", log, re.M)
        if start_ms <= int(m.group(1)) <= stop_ms]


def numbers(out):
    """One run's numbers, as a dict (a key left out where the run has nothing for it)."""
    log = open(out + "/ingame.log", errors="replace").read()
    gaps = [float(x) for x in open(out + "/frames.txt").read().split()]
    r = {"run": out.rstrip("/")}
    # The song's music: its play (the frame it started at, the log's time) and its stop.
    song = song_of(log)
    if not song:
        r["error"] = "no song in the log"
        return r
    name, start, start_ms = song
    stop = re.search(r"^(\d+) sound: stream " + re.escape(name) + r" stops at frame (\d+) after ([\d.]+) ms played",
                     log[log.index(" plays from frame %d" % start):], re.M)
    if not stop:
        r["error"] = "the song did not stop in the log"
        return r
    stop_ms, end, played = int(stop.group(1)), int(stop.group(2)), float(stop.group(3))
    g = gaps[start - 1:end - 1]
    r.update(song_s=round((stop_ms - start_ms) / 1000.0, 1), frames=len(g), fps=round(1000.0 / statistics.mean(g), 3),
             mean_ms=round(statistics.mean(g), 3), sd_ms=round(statistics.pstdev(g), 3), p99_ms=round(pct(g, 99), 3),
             longest_ms=round(max(g), 2), over_20_ms_pct=round(100.0 * sum(1 for x in g if x > 20) / len(g), 3),
             music_minus_frames_ms=round(played - (end - start) * 1000.0 / 60, 1))
    # The presses in the song.
    lat = song_presses(log, start_ms, stop_ms)
    if lat:
        total = [float(m.group(2)) for m in lat]
        r.update(presses=len(total), latency_median_ms=round(statistics.median(total), 2),
                 latency_mean_ms=round(statistics.mean(total), 2), latency_p10_ms=round(pct(total, 10), 2),
                 latency_p90_ms=round(pct(total, 90), 2), latency_min_ms=round(min(total), 2),
                 latency_max_ms=round(max(total), 2))
        parts = [m for m in lat if m.group(3)]
        if parts:
            r.update(to_read_median_ms=round(statistics.median(float(m.group(3)) for m in parts), 2),
                     read_to_present_median_ms=round(statistics.median(float(m.group(4)) for m in parts), 2),
                     present_to_done_median_ms=round(statistics.median(float(m.group(5)) for m in parts), 2),
                     read_to_done_median_ms=round(statistics.median(float(m.group(4)) + float(m.group(5))
                                                                    for m in parts), 2),
                     presses_in_frames_started_just_in_time=sum(1 for m in parts
                                                                if m.group(6) == "started just in time"))
    # Starting frames just in time, over the song's two-second lines.
    jit = [m for m in re.finditer(
        r"^(\d+) jit: (\d+) of (\d+) frames started just in time, ([\d.]+) ms before their tick \(their work ([\d.]+) "
        r"ms; the clock counts on ([\d.]+) with ([\d.]+) spare\); (\d+) not done by their tick \((\d+) of those"
        r"(?:.*?every frame's work ([\d.]+) ms to its picture done, ([\d.]+) of it on the processor)?", log,
        re.M) if start_ms + 2000 <= int(m.group(1)) <= stop_ms]
    if jit:
        held = sum(int(m.group(2)) for m in jit)
        r.update(jit_held_pct=round(100.0 * held / max(1, sum(int(m.group(3)) for m in jit)), 1),
                 jit_lead_ms=round(sum(float(m.group(4)) * int(m.group(2)) for m in jit) / max(1, held), 2),
                 jit_work_ms=round(sum(float(m.group(5)) * int(m.group(2)) for m in jit) / max(1, held), 2),
                 jit_spare_most_ms=max(float(m.group(7)) for m in jit),
                 jit_missed=sum(int(m.group(8)) for m in jit), jit_missed_held=sum(int(m.group(9)) for m in jit))
        # Every frame's work (from its start to its picture done on the GPU) and the processor's part of it, each
        # two-second line's mean, as their median over the song.
        whole = [float(m.group(10)) for m in jit if m.group(10)]
        if whole:
            r.update(work_median_ms=round(statistics.median(whole), 2),
                     work_on_the_processor_median_ms=round(statistics.median(float(m.group(11)) for m in jit
                                                                             if m.group(11)), 2))
    # The chain's GPU time a frame, the lock's start, and the container's CPU over the song.
    gpu = [float(m.group(2)) for m in re.finditer(r"^(\d+) post: GPU ([\d.]+) us a frame", log, re.M)
           if start_ms <= int(m.group(1)) <= stop_ms]
    if gpu:
        r["chain_gpu_us"] = round(statistics.mean(gpu), 1)
    lock = re.findall(r"pacing: locked to the music started at frame (\d+) \(([-\d.]+) ms from its frames", log)
    if lock:
        r["lock_start_ms"] = float(lock[-1][1])
    txt = open(out + "/run.txt").read()
    a = re.search(r"cpu_usec at its start (\d+) at (\d+) ms", txt)
    b = re.search(r"cpu_usec at the song's stop (\d+) at (\d+) ms", txt)
    if a and b and int(b.group(2)) > int(a.group(2)):
        r["cpu_cores"] = round((int(b.group(1)) - int(a.group(1))) / 1000.0 / (int(b.group(2)) - int(a.group(2))), 2)
    return r


def pooled(runs):
    """The songs' presses of the runs (comma-separated): each press's whole, and each from the game's read to done
    where the layer gave its parts."""
    whole, read_done = [], []
    for out in runs.split(","):
        log = open(out + "/ingame.log", errors="replace").read()
        song = song_of(log)
        if not song:
            continue
        name, start, start_ms = song
        stop = re.search(r"^(\d+) sound: stream " + re.escape(name) + r" stops at frame",
                         log[log.index(" plays from frame %d" % start):], re.M)
        if not stop:
            continue
        for m in song_presses(log, start_ms, int(stop.group(1))):
            whole.append(float(m.group(2)))
            if m.group(3):
                read_done.append(float(m.group(4)) + float(m.group(5)))
    return whole, read_done


def compare(a_runs, b_runs):
    """Each side's medians and their difference (A less B) with its 95 % interval by resampling, as lines."""
    a, b = pooled(a_runs), pooled(b_runs)
    # The same draws every time, so a table made from them is made again the same.
    rand = random.Random(1)
    lines = []
    for i, what in ((0, "press to done"), (1, "read to done")):
        va, vb = a[i], b[i]
        if not va or not vb:
            lines.append("%s: no presses on one side" % what)
            continue
        diffs = sorted(statistics.median(rand.choices(va, k=len(va))) - statistics.median(rand.choices(vb, k=len(vb)))
                       for _ in range(4000))
        lines.append("%s: A %.2f ms (%d presses), B %.2f ms (%d), A less B %+.2f ms, 95 %% %+.2f to %+.2f"
                     % (what, statistics.median(va), len(va), statistics.median(vb), len(vb),
                        statistics.median(va) - statistics.median(vb), diffs[100], diffs[3899]))
    return lines


if __name__ == "__main__":
    if sys.argv[1:2] == ["compare"] and len(sys.argv) == 4:
        print("\n".join(compare(sys.argv[2], sys.argv[3])))
        sys.exit(0)
    for out in sys.argv[1:]:
        r = numbers(out)
        json.dump(r, open(out + "/results.json", "w"), indent=1)
        print("\n".join("  %s: %s" % (k, v) for k, v in r.items()))
