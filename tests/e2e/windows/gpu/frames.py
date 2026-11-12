"""The in-game layer's frame counter over a stretch of a run, summed up in one line (play_a_song.sh, gpu/measure.sh).

    python3 frames.py INGAME_LOG [--from MS] [--to MS] [--json]

The layer writes a line every two seconds: "frames: R a second, frame time M ms (sd S, 99 % within P, longest L,
over 20 ms O %); openDMT3 U us a frame (longest V)", and while its post-process chain runs "post: N passes a frame,
CPU C us a frame (longest D), GPU ..." and, where the device answers timestamp queries, "post: GPU G us a frame over
K frames". MS is the log's own clock (the monotonic clock in milliseconds, the same in the test's shell); a line is
counted when the two seconds it covers lie within the stretch. Prints the windows counted and, over them: the frame
rate's median and range, the mean frame time, the spread's median and largest, the 99th percentile's median and
largest, the longest frame, the share of frames over 20 ms, openDMT3's own CPU time a frame, and the chain's CPU and
GPU time a frame. --json prints the same as one JSON object (gpu/measure.sh keeps it).
"""
import json
import re
import sys

FRAMES = re.compile(r"^(\d+) frames: ([\d.]+) a second, frame time ([\d.]+) ms \(sd ([\d.]+), 99 % within ([\d.]+), "
                    r"longest ([\d.]+), over 20 ms ([\d.]+) %\); openDMT3 ([\d.]+) us a frame", re.M)
POST_CPU = re.compile(r"^(\d+) post: (\d+) passes a frame, CPU ([\d.]+) us a frame", re.M)
POST_GPU = re.compile(r"^(\d+) post: GPU ([\d.]+) us a frame over (\d+) frames", re.M)


def median(values):
    """The middle value (the mean of the two middle ones for an even count), or None."""
    v = sorted(values)
    if not v:
        return None
    mid = len(v) // 2
    return v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2.0


def inside(at, start, end):
    """Whether a line written at `at` covers two seconds inside [start, end] (None: open)."""
    return (start is None or at - 2000 >= start) and (end is None or at <= end)


def summary(text, start=None, end=None):
    """The stretch's numbers, as a dict (empty values as None)."""
    rows = [m for m in FRAMES.finditer(text) if inside(int(m.group(1)), start, end)]
    rates = [float(m.group(2)) for m in rows]
    times = [float(m.group(3)) for m in rows]
    sds = [float(m.group(4)) for m in rows]
    p99 = [float(m.group(5)) for m in rows]
    longest = [float(m.group(6)) for m in rows]
    over = [float(m.group(7)) for m in rows]
    ours = [float(m.group(8)) for m in rows]
    post_cpu = [float(m.group(3)) for m in POST_CPU.finditer(text) if inside(int(m.group(1)), start, end)]
    passes = [int(m.group(2)) for m in POST_CPU.finditer(text) if inside(int(m.group(1)), start, end)]
    post_gpu = [float(m.group(2)) for m in POST_GPU.finditer(text) if inside(int(m.group(1)), start, end)]
    return {
        "windows": len(rows),
        "fps_median": median(rates), "fps_min": min(rates) if rates else None, "fps_max": max(rates) if rates else None,
        "frame_ms_mean": sum(times) / len(times) if times else None,
        "sd_ms_median": median(sds), "sd_ms_max": max(sds) if sds else None,
        "p99_ms_median": median(p99), "p99_ms_max": max(p99) if p99 else None,
        "longest_ms": max(longest) if longest else None,
        "over_20ms_pct": sum(over) / len(over) if over else None,
        "opendmt3_cpu_us_median": median(ours),
        "chain_passes": median(passes),
        "chain_cpu_us_median": median(post_cpu),
        "chain_gpu_us_median": median(post_gpu),
    }


def line(s):
    """The summary in one line of words."""
    def f(value, form="%.1f"):
        return "?" if value is None else form % value
    return ("%d windows of 2 s: %s frames a second (%s to %s), frame time %s ms, spread %s ms (largest %s), 99 %% within "
            "%s ms (largest %s), longest %s ms, over 20 ms %s %%; openDMT3 %s us a frame; the chain %s passes, CPU %s us, "
            "GPU %s us a frame") % (
        s["windows"], f(s["fps_median"]), f(s["fps_min"]), f(s["fps_max"]), f(s["frame_ms_mean"], "%.2f"),
        f(s["sd_ms_median"], "%.2f"), f(s["sd_ms_max"], "%.2f"), f(s["p99_ms_median"], "%.2f"), f(s["p99_ms_max"], "%.2f"),
        f(s["longest_ms"], "%.2f"), f(s["over_20ms_pct"], "%.2f"), f(s["opendmt3_cpu_us_median"]),
        f(s["chain_passes"], "%.0f"), f(s["chain_cpu_us_median"]), f(s["chain_gpu_us_median"]))


def main(argv):
    path, start, end, as_json = argv[0], None, None, False
    i = 1
    while i < len(argv):
        if argv[i] == "--from":
            start, i = int(argv[i + 1]), i + 2
        elif argv[i] == "--to":
            end, i = int(argv[i + 1]), i + 2
        elif argv[i] == "--json":
            as_json, i = True, i + 1
        else:
            raise SystemExit("frames.py: unknown argument %s" % argv[i])
    try:
        text = open(path, errors="replace").read()
    except OSError:
        text = ""
    s = summary(text, start, end)
    print(json.dumps(s) if as_json else "  frames: " + line(s))
    return 0 if s["windows"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
