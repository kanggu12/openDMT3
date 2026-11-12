"""gpu/measure.sh's runs turned into numbers and tables.

    python3 measure.py run SESSION RUN     one run's numbers into SESSION/results.json, said in one line
    python3 measure.py table SESSION       that session's runs, as Markdown tables
    python3 measure.py compare OUT_DIR     every session under OUT_DIR (gpu-WxH, cpu-WxH) side by side
    python3 measure.py passes OUT_DIR      the passes runs under OUT_DIR: each choice's GPU time by pass
    python3 measure.py passes OUT_DIR BEFORE_DIR   the same runs of two builds: each step and choice before and after

A session is one renderer at one screen size (OUT_DIR/RENDERER-WxH). Each run's folder holds what measure.sh left:
run.txt (its choice, the load at its start and end, the count of Wine's frame time lines at its window's edges),
marks.txt (each phase's start and end on the layer's clock with the 1-minute load and the container's CPU time then),
ingame.log (the layer's log) and wine.txt (Wine's output: its frame times for the runs without the layer).

The numbers:
  frames      over the window: frames a second, mean frame time, its spread (standard deviation), the 99th
              percentile, the longest frame, the share over 20 ms (the layer's 2 s counter; Wine's own frame times
              for the game alone, where there is no layer)
  chain       the post-process chain's own GPU time a frame from its timestamps (on the GPU; the CPU renderer's
              timestamps are not where its work is done and are left out), and its CPU time to send its passes
  parts       for each part of the layer, what it adds to a frame as it is drawn: with OPENDMT3_LAYER_TIMING=frame the
              chain's and the layer's whole time a frame in each turn with the part less the turn after without it,
              the median of the turns (parts-frame); with =on, each kind of part's GPU time a frame from timestamps
              (parts-gpu, on the GPU), and the frames while the part was on the screen
  load        the machine's 1-minute load average at the window's edges, and the CPUs the test's container used
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frames  # noqa: E402

PARTS = ("chip", "bar", "menu", "question", "toast")
# The layer's cost lines by kind of part ("layer cost KIND: N frames, CPU X us a frame, GPU Y us a frame (K read)").
COST = re.compile(r"^(\d+) layer cost ([a-z ]+): (\d+) frames, CPU ([\d.]+) us a frame, (?:GPU ([\d.]+) us a frame)?", re.M)
BLUR = re.compile(r"^(\d+) layer cost blur: (\d+) passes, (?:GPU ([\d.]+) us a frame)?", re.M)
WHOLE = re.compile(r"^(\d+) layer cost frame: the chain and the layer ([\d.]+) us a frame", re.M)
# The picture's GPU time by pass (OPENDMT3_PASS_TIMES=on): the layer's line every two seconds, each step's median.
PASSLINE = re.compile(r"^(\d+) post: GPU time by pass at (\d+)x(\d+) (keep|fill), upscale (\S+), sharpness (\d+), "
                      r"anti-aliasing (\S+): (.*) \((\d+) frames\)\s*$", re.M)
STEP = re.compile(r"([a-z][a-z ]*?) ([\d.]+) us")
UPLOAD = re.compile(r"^(\d+) layer cost fps chip: .*?drawn again \d+ times at ([\d.]+) us \(longest [\d.]+\), uploaded "
                    r"\d+ times at ([\d.]+) us", re.M)
# The steps in the order a frame makes them (the passes run table's columns).
STEP_ORDER = ("game", "timestamp", "empty pass", "blur", "bars", "fxaa", "smaa edges", "smaa weights", "smaa blend",
              "sharp bilinear", "bilinear", "easu len", "easu", "rcas", "nis edges", "nis rows", "nis scale",
              "anime4k layers", "anime4k picture", "anime4k to the window", "layer", "all")
FRAMETIME = re.compile(r"Frame duration (\d+) ")


def median(values):
    return frames.median(values)


def read(path):
    try:
        return open(path, errors="replace").read()
    except OSError:
        return ""


def phases(marks):
    """(name, start ms, end ms, load at start, load at end, CPU microseconds of the container over it)."""
    out, open_at = [], {}
    for line in marks.splitlines():
        p = line.split()
        if len(p) < 5:
            continue
        name, edge, ms, load, cpu = p[0], p[1], int(p[2]), float(p[3]), int(p[4] or 0)
        if edge == "start":
            open_at[name] = (ms, load, cpu)
        elif name in open_at:
            s_ms, s_load, s_cpu = open_at.pop(name)
            out.append((name, s_ms, ms, s_load, load, cpu - s_cpu))
    return out


def stats_ms(lengths):
    """Frame lengths in milliseconds: the counter's numbers."""
    if not lengths:
        return {"windows": 0}
    n = len(lengths)
    mean = sum(lengths) / n
    var = sum((x - mean) ** 2 for x in lengths) / n
    ordered = sorted(lengths)
    return {
        "frames": n, "fps_median": 1000.0 / mean, "frame_ms_mean": mean, "sd_ms_median": var ** 0.5,
        "p99_ms_median": ordered[min(n - 1, int(n * 0.99))], "longest_ms": ordered[-1],
        "over_20ms_pct": 100.0 * sum(1 for x in lengths if x > 20.0) / n,
    }


def run_numbers(session, run):
    d = os.path.join(session, run.replace(":", "-"))
    info = read(os.path.join(d, "run.txt"))
    marks = phases(read(os.path.join(d, "marks.txt")))
    log = read(os.path.join(d, "ingame.log"))
    result = {"run": run, "settled": "did not reach" not in info and "did not end" not in info}
    window = [p for p in marks if p[0] == "window"]
    if window:
        _, start, end, l0, l1, cpu = window[0]
        result["load"] = [l0, l1]
        result["container_cpus"] = cpu / 1000.0 / max(1, end - start)
    if run == "renderer":
        # The game's own process: the OpenGL strings Wine's X11 driver read at its first context.
        w = read(os.path.join(d, "wine.txt"))
        # GLX (the GPU image's prefixes) says "GL renderer : ..."; EGL (Wine's default, the CPU image's) its device's
        # name as it enumerates EGL's devices.
        r = re.search(r"GL renderer +: (.*?)\.?\s*$", w, re.M) or re.search(r'device_name: "(.*?)"', w)
        v = re.search(r"GL version +: (.*?)\.?\s*$", w, re.M) or re.search(r"- version: ([\d.]+)", w)
        result["renderer"] = r.group(1) if r else None
        result["gl_version"] = v.group(1) if v else None
        result["gpu_proof"] = "on the GPU:" in info
        return result
    if run == "present":
        # The probe's own line: one frame cleared and shown, nothing drawn.
        m = re.search(r"present: (\d+)x(\d+) cleared and presented ([\d.]+) ms a frame", read(os.path.join(d, "probe.txt")))
        if m:
            result["present_ms"] = float(m.group(3))
            result["fps_median"] = 1000.0 / float(m.group(3))
        a = re.search(r"load at the start: ([\d.]+)", info)
        result["load"] = [float(a.group(1))] if a else None
        result["source"] = "d3d9probe.exe --present"
        return result
    if run.startswith("alone"):
        # Wine's own frame times between the window's edges (the lines counted there).
        a = re.search(r"frametime lines at the start: (\d+)", info)
        b = re.search(r"frametime lines at the end: (\d+)", info)
        lengths = [int(m.group(1)) / 1000.0 for m in FRAMETIME.finditer(read(os.path.join(d, "wine.txt")))]
        if a and b:
            lengths = lengths[int(a.group(1)):int(b.group(1))]
        result.update(stats_ms(lengths))
        result["source"] = "Wine's frame times (+frametime)"
    elif run == "passes":
        result["phases"] = passes_numbers(log, marks, clocks(session))
    elif run == "chip":
        result.update(chip_numbers(log))
    elif run.startswith("pictures"):
        # The dumps made, and the frames they are of (dump.done: a line a frame).
        result["dumps"] = len([n for n in os.listdir(d) if n.endswith(".bmp")]) if os.path.isdir(d) else 0
        result["frames"] = [line.split()[0] for line in read(os.path.join(d, "dump.done")).splitlines() if line.strip()]
    elif run.startswith("parts"):
        result.update(parts_numbers(log, marks, run == "parts-gpu"))
        result["load"] = [marks[0][3], marks[-1][4]] if marks else None
    elif window:
        s = frames.summary(log, window[0][1], window[0][2])
        result.update(s)
        result["source"] = "the layer's counter"
        if run == "both-clocks":
            # Wine's own frame times over the same window, beside the layer's counter.
            a = re.search(r"frametime lines at the start: (\d+)", info)
            b = re.search(r"frametime lines at the end: (\d+)", info)
            lengths = [int(m.group(1)) / 1000.0 for m in FRAMETIME.finditer(read(os.path.join(d, "wine.txt")))]
            if a and b:
                lengths = lengths[int(a.group(1)):int(b.group(1))]
            result["wine_clock"] = stats_ms(lengths)
    return result


def clocks(session):
    """The card's readings over the session (clocks.py): (monotonic ms, shader clock MHz, memory clock MHz, busy %)."""
    out = []
    for line in read(os.path.join(session, "gpu-clocks.txt")).splitlines():
        p = line.split()
        # "ms P0 225 10501 14": a reading with numbers in every field (a card that answered "[N/A]" is left out).
        if len(p) == 5 and all(x.isdigit() for x in (p[0], p[2], p[3], p[4])):
            out.append((int(p[0]), int(p[2]), int(p[3]), int(p[4])))
    return out


def passes_numbers(log, marks, card=()):
    """Each phase of the passes run (a choice and a shape, or a part shown): every step's median over the lines wholly
    inside it, the choice the lines name, the card's median shader clock over it, and, in the chip's phase, its
    picture's updates and uploads (CPU)."""
    out = {}
    for name, s, e, l0, l1, cpu in marks:
        lines = [m for m in PASSLINE.finditer(log) if s + 2000 <= int(m.group(1)) <= e]
        steps = {}
        for m in lines:
            for sm in STEP.finditer(m.group(8)):
                steps.setdefault(sm.group(1), []).append(float(sm.group(2)))
        entry = {"steps": {k: median(v) for k, v in steps.items()}, "lines": len(lines), "load": [l0, l1]}
        if lines:
            m = lines[-1]
            entry["choice"] = "%sx%s %s, %s %s, %s" % (m.group(2), m.group(3), m.group(4), m.group(5), m.group(6),
                                                     m.group(7))
        # The shader clock over the stretches counted (their first one starts 2 s before its line).
        sm = [c[1] for c in card if s <= c[0] <= e]
        if sm:
            entry["sm_mhz"] = median(sm)
        ups = [(float(m.group(2)), float(m.group(3))) for m in UPLOAD.finditer(log) if s <= int(m.group(1)) <= e + 2000]
        if ups:
            entry["chip_redraw_us"] = median([a for a, b in ups])
            entry["chip_upload_us"] = median([b for a, b in ups])
        out[name] = entry
    return out


def passes_table(out):
    """The passes runs under OUT_DIR (gpu-WxH sessions), as Markdown: each choice's steps at each shape, then the parts."""
    sessions = sorted((d for d in os.listdir(out) if re.match(r"^(gpu|cpu)-\d+x\d+$", d)),
                      key=lambda d: (d.split("-")[0], int(d.split("-")[1].split("x")[0])))
    for sess in sessions:
        r = load_session(os.path.join(out, sess)).get("passes")
        if not r:
            continue
        print("\n#### %s, %s\n" % (sess.split("-")[0].upper(), sess.split("-")[1].replace("x", " x ")))
        print("| Choice | Shape | Its passes (us) | All (us) | Game's frame (us) | Empty pass (us) | Two timestamps (us) "
              "| Shader clock (MHz) | Load |")
        print("|---|---|---|---|---|---|---|---|---|")
        for name, e in r["phases"].items():
            if name.startswith("parts"):
                continue
            st = e["steps"]
            own = ", ".join("%s %.0f" % (k, st[k]) for k in STEP_ORDER
                            if k in st and k not in ("game", "timestamp", "empty pass", "all", "layer", "blur"))
            shape, rest = name.split(":", 1)
            print("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                rest.replace(":", " "), shape, own or "-", f(st.get("all"), "%.0f"), f(st.get("game"), "%.0f"),
                f(st.get("empty pass"), "%.0f"), f(st.get("timestamp"), "%.0f"), f(e.get("sm_mhz"), "%.0f"),
                "-".join("%.0f" % x for x in e.get("load") or [])))
        print()
        print("| Part shown | Blur (us) | Layer's parts (us) | All (us) | Chip: drawn again, uploaded (CPU us) |")
        print("|---|---|---|---|---|")
        for name, e in r["phases"].items():
            if not name.startswith("parts"):
                continue
            st = e["steps"]
            chip = "%s, %s" % (f(e.get("chip_redraw_us"), "%.0f"), f(e.get("chip_upload_us"), "%.0f")) \
                if "chip_upload_us" in e else "-"
            print("| %s | %s | %s | %s | %s |" % (name.split(":", 1)[1], f(st.get("blur"), "%.0f"),
                                                f(st.get("layer"), "%.0f"), f(st.get("all"), "%.0f"), chip))


# The shader clock the passes tables put every time at: the card's own under this game's load (an RTX 4090's lowest),
# so the times are as measured in most phases and a phase at a higher clock is scaled to it (a pass's time goes as
# the shader clock; the memory's stays at its full clock throughout).
AT_MHZ = 225.0


def at_clock(us, mhz):
    """A time measured at `mhz` as it would be at AT_MHZ (as it is when the clock is not known)."""
    return us * mhz / AT_MHZ if mhz else us


CHIP = re.compile(r"^(\d+) layer cost fps chip: (\d+) frames, CPU ([\d.]+) us a frame, .*?drawn again (\d+) times at "
                  r"([\d.]+) us \(longest ([\d.]+)\), uploaded (\d+) times at ([\d.]+) us", re.M)
MADE = re.compile(r"^\d+ layer: (\d+) parts' textures made for (\d+)x(\d+) in ([\d.]+) ms", re.M)


def chip_numbers(log):
    """The chip's updates over the run: each of the layer's lines that had any (two seconds each): how many times its
    picture was drawn again and uploaded there and the mean time of each; the first line apart (the chip's first
    showing); what making every part's textures took at the layer's first frame at a size; the textures made after
    (none, when every part's were made as large as it gets)."""
    lines = [(int(m.group(4)), float(m.group(5)), int(m.group(7)), float(m.group(8)), float(m.group(3)))
             for m in CHIP.finditer(log)]
    out = {"chip_lines": len(lines)}
    if lines:
        first, rest = lines[0], lines[1:]
        out["chip_first"] = {"drawn": first[0], "drawn_us": first[1], "uploaded": first[2], "upload_us": first[3]}
        if rest:
            out["chip_drawn_us"] = median([x[1] for x in rest])
            out["chip_upload_us"] = median([x[3] for x in rest])
            out["chip_upload_us_max"] = max(x[3] for x in rest)
            out["chip_updates"] = sum(x[2] for x in rest)
            out["chip_cpu_us"] = median([x[4] for x in rest])
    out["made"] = [{"parts": int(m.group(1)), "size": "%sx%s" % (m.group(2), m.group(3)), "ms": float(m.group(4))}
                   for m in MADE.finditer(log)]
    out["made_in_play"] = len(re.findall(r"layer: a part's textures made while the game plays", log))
    return out


def passes_steps(r):
    """A passes run's steps over its choices' phases: each step's median over the phases that have it (each phase's own
    median first, at AT_MHZ), with the phases' median shader clock; the layer's parts' phases left out."""
    by, mhz = {}, []
    for name, e in r["phases"].items():
        if name.startswith("parts"):
            continue
        for k, v in e["steps"].items():
            by.setdefault(k, []).append(at_clock(v, e.get("sm_mhz")))
        if e.get("sm_mhz"):
            mhz.append(e["sm_mhz"])
    return {k: median(v) for k, v in by.items()}, (median(mhz) if mhz else None)


def passes_versus(out, before):
    """Two builds' passes runs (BEFORE_DIR's then OUT_DIR's, the same sizes), as Markdown: each step's time over the
    phases that run it, and each choice's picture work whole, before and after."""
    sessions = sorted((d for d in os.listdir(out) if re.match(r"^gpu-\d+x\d+$", d)
                       and os.path.isdir(os.path.join(before, d))), key=lambda d: int(d.split("-")[1].split("x")[0]))
    for sess in sessions:
        a = load_session(os.path.join(before, sess)).get("passes")
        b = load_session(os.path.join(out, sess)).get("passes")
        if not a or not b:
            continue
        (sa, ma), (sb, mb) = passes_steps(a), passes_steps(b)
        print("\n#### %s (shader clock %s and %s MHz at the phases' median; times at %.0f MHz)\n" % (
            sess.split("-")[1].replace("x", " x "), f(ma, "%.0f"), f(mb, "%.0f"), AT_MHZ))
        print("| Step | Before (us) | After (us) | Change |")
        print("|---|---|---|---|")
        # The steps in a frame's order, then any other the two runs name (the measuring dump's left out).
        names = [k for k in STEP_ORDER if k in sa or k in sb]
        names += sorted(k for k in set(sa) | set(sb) if k not in STEP_ORDER and k != "dump")
        for k in names:
            x, y = sa.get(k), sb.get(k)
            print("| %s | %s | %s | %s |" % (k, f(x, "%.0f"), f(y, "%.0f"),
                                             "%+.0f %%" % (100.0 * (y - x) / x) if x and y is not None else "-"))
        print()
        print("| Choice | Shape | All before (us) | All after (us) | Change |")
        print("|---|---|---|---|---|")
        for name in a["phases"]:
            if name.startswith("parts") or name not in b["phases"]:
                continue
            pa, pb = a["phases"][name], b["phases"][name]
            x, y = pa["steps"].get("all"), pb["steps"].get("all")
            x = at_clock(x, pa.get("sm_mhz")) if x is not None else None
            y = at_clock(y, pb.get("sm_mhz")) if y is not None else None
            shape, rest = name.split(":", 1)
            print("| %s | %s | %s | %s | %s |" % (rest.replace(":", " "), shape, f(x, "%.0f"), f(y, "%.0f"),
                                                  "%+.0f %%" % (100.0 * (y - x) / x) if x and y is not None else "-"))


def parts_numbers(log, marks, gpu_kinds):
    out = {"parts": {}}
    whole = [(int(m.group(1)), float(m.group(2))) for m in WHOLE.finditer(log)]
    costs = [(int(m.group(1)), m.group(2), int(m.group(3)), float(m.group(4)), m.group(5)) for m in COST.finditer(log)]
    blur = [(int(m.group(1)), int(m.group(2)), m.group(3)) for m in BLUR.finditer(log)]

    def inside(t, s, e):
        return s + 2000 <= t <= e

    for part in PARTS + ("off",):
        mine = [p for p in marks if (p[0] == part if part != "off" else p[0].startswith("off-"))]
        entry = {}
        # Frames while the part was on the screen (the counter's windows wholly inside its phases).
        rows = []
        for _, s, e, _, _, _ in mine:
            sm = frames.summary(log, s, e)
            if sm["windows"]:
                rows.append(sm)
        if rows:
            entry["fps_median"] = median([r["fps_median"] for r in rows])
            entry["sd_ms_median"] = median([r["sd_ms_median"] for r in rows])
            entry["p99_ms_max"] = max(r["p99_ms_max"] for r in rows)
        # The chain's and the layer's whole time a frame (frame timing): this part's turns less the turn after.
        if whole and part != "off":
            diffs, absolute = [], []
            order = [p for p in marks]
            for i, (name, s, e, _, _, _) in enumerate(order):
                if name != part or i + 1 >= len(order) or order[i + 1][0] != "off-" + part:
                    continue
                on = [v for t, v in whole if inside(t, s, e)]
                off = [v for t, v in whole if inside(t, order[i + 1][1], order[i + 1][2])]
                if on and off:
                    diffs.append(sum(on) / len(on) - sum(off) / len(off))
                    absolute.append(sum(on) / len(on))
            if diffs:
                entry["adds_us_median"] = median(diffs)
                entry["adds_us_range"] = [min(diffs), max(diffs)]
                entry["whole_us_median"] = median(absolute)
                entry["turns"] = len(diffs)
        if whole and part == "off":
            vals = [v for _, s, e, _, _, _ in mine for t, v in whole if inside(t, s, e)]
            if vals:
                entry["whole_us_median"] = median(vals)
        # Each kind's GPU time a frame from timestamps (timing on): the lines inside the part's phases.
        if gpu_kinds:
            kinds = {}
            for t, kind, n, cpu, gpu in costs:
                if gpu is None or not any(inside(t, s, e) for _, s, e, _, _, _ in mine):
                    continue
                kinds.setdefault(kind, []).append(float(gpu))
            entry["gpu_us_by_kind"] = {k: median(v) for k, v in kinds.items()}
            b = [float(g) for t, n, g in blur if g is not None and any(inside(t, s, e) for _, s, e, _, _, _ in mine)]
            if b:
                entry["gpu_us_blur"] = median(b)
            entry["gpu_us_total"] = sum(entry["gpu_us_by_kind"].values()) + entry.get("gpu_us_blur", 0.0)
        # The layer's CPU time a frame by kind (both timings).
        cpus = {}
        for t, kind, n, cpu, gpu in costs:
            if any(inside(t, s, e) for _, s, e, _, _, _ in mine):
                cpus.setdefault(kind, []).append(cpu)
        entry["cpu_us_by_kind"] = {k: median(v) for k, v in cpus.items()}
        out["parts"][part] = entry
    return out


def save(session, result):
    path = os.path.join(session, "results.json")
    try:
        data = json.load(open(path))
    except (OSError, ValueError):
        data = {}
    data[result["run"]] = result
    json.dump(data, open(path, "w"), indent=1, sort_keys=True)


def f(v, form="%.1f"):
    return "-" if v is None else form % v


def one_line(r):
    if r.get("run", "").startswith("pictures"):
        return "  %s: %d dumps of frames %s" % (r["run"], r.get("dumps", 0), ", ".join(r.get("frames") or []) or "-")
    if r.get("run") == "chip":
        first = r.get("chip_first") or {}
        return ("  chip: %s updates in %s lines after the first: drawn again %s us, uploaded %s us at the lines' median "
                "(the slowest line %s us), CPU %s us a frame; its first line: %s uploads at %s us; textures made at the "
                "layer's first frame: %s; made while the game plays: %s" % (
                    r.get("chip_updates", 0), max(r.get("chip_lines", 0) - 1, 0), f(r.get("chip_drawn_us")),
                    f(r.get("chip_upload_us")), f(r.get("chip_upload_us_max")), f(r.get("chip_cpu_us")),
                    first.get("uploaded", "-"), f(first.get("upload_us")),
                    ", ".join("%d parts for %s in %.1f ms" % (m["parts"], m["size"], m["ms"]) for m in r.get("made") or [])
                    or "not said (a build before they were)", r.get("made_in_play", 0)))
    if r.get("run") == "passes":
        # Each phase's picture work whole (its steps are in measure.py passes OUT_DIR's table).
        return "  passes: %s" % "; ".join("%s all %s us at %s MHz" % (name, f(e["steps"].get("all"), "%.0f"),
                                                                     f(e.get("sm_mhz"), "%.0f"))
                                          for name, e in r.get("phases", {}).items())
    if r.get("run") == "renderer":
        return "  renderer: the game's OpenGL renderer %s (%s)%s" % (
            r.get("renderer") or "not found", r.get("gl_version") or "-",
            ", its process drawing through WSL's D3D12" if r.get("gpu_proof") else "")
    if r.get("run") == "present":
        return "  present: a frame shown with nothing drawn in it %s ms (%s a second), load %s" % (
            f(r.get("present_ms"), "%.2f"), f(r.get("fps_median"), "%.0f"),
            "-".join("%.1f" % x for x in (r.get("load") or [])))
    if "wine_clock" in r:
        w = r["wine_clock"]
        r = dict(r)
        extra = "; Wine's clock: %s fps, %s ms, spread %s ms, 99 %% %s ms, over 20 ms %s %%" % (
            f(w.get("fps_median")), f(w.get("frame_ms_mean"), "%.2f"), f(w.get("sd_ms_median"), "%.2f"),
            f(w.get("p99_ms_median"), "%.2f"), f(w.get("over_20ms_pct"), "%.1f"))
    else:
        extra = ""
    if "parts" in r:
        bits = []
        for part in PARTS:
            e = r["parts"].get(part, {})
            bits.append("%s %s us%s" % (part, f(e.get("adds_us_median"), "%+.0f"),
                                        (", GPU %s us" % f(e.get("gpu_us_total"), "%.0f")) if "gpu_us_total" in e else ""))
        return "  %s: %s" % (r["run"], "; ".join(bits))
    return ("  %s: %s fps, frame time %s ms, spread %s ms, 99 %% %s ms, longest %s ms, over 20 ms %s %%, chain GPU %s us, "
            "chain CPU %s us, container %s CPUs, load %s" % (
                r["run"], f(r.get("fps_median")), f(r.get("frame_ms_mean"), "%.2f"), f(r.get("sd_ms_median"), "%.2f"),
                f(r.get("p99_ms_median"), "%.2f"), f(r.get("longest_ms"), "%.1f"), f(r.get("over_20ms_pct"), "%.1f"),
                f(r.get("chain_gpu_us_median"), "%.0f"), f(r.get("chain_cpu_us_median"), "%.0f"),
                f(r.get("container_cpus"), "%.1f"), "-".join("%.1f" % x for x in (r.get("load") or [])))) + extra


ORDER = ["present", "alone", "alone-free", "both-clocks", "own-steps", "free", "fsr1:off", "smooth:off", "nis:off", "fsr1:fxaa", "fsr1:smaa-low",
         "fsr1:smaa-medium", "fsr1:smaa-high", "fsr1:smaa-ultra"]
LABELS = {"present": "showing a frame, nothing drawn (the test's own cost)", "alone": "the game alone, its own 60", "alone-free": "the game alone, uncapped",
          "both-clocks": "openDMT3 defaults (the layer's counter)",
          "own-steps": "the game's own limiter, openDMT3's lightest picture",
          "free": "openDMT3 defaults, uncapped", "fsr1:off": "openDMT3 defaults (FSR 1, no AA)",
          "smooth:off": "Smooth (bilinear)", "nis:off": "NIS", "fsr1:fxaa": "FSR 1 + FXAA",
          "fsr1:smaa-low": "FSR 1 + SMAA Low", "fsr1:smaa-medium": "FSR 1 + SMAA Medium",
          "fsr1:smaa-high": "FSR 1 + SMAA High", "fsr1:smaa-ultra": "FSR 1 + SMAA Ultra"}


def load_session(session):
    try:
        return json.load(open(os.path.join(session, "results.json")))
    except (OSError, ValueError):
        return {}


def compare(out):
    """Every session under OUT_DIR, GPU and CPU side by side at each screen size, as Markdown tables."""
    sessions = sorted(d for d in os.listdir(out) if re.match(r"^(gpu|cpu)-\d+x\d+$", d))
    screens = sorted({s.split("-", 1)[1] for s in sessions}, key=lambda s: int(s.split("x")[0]))

    def load(r):
        # The CPUs the test's container used over the window, and the 1-minute load average at its edges (the machine
        # is shared: other work moves the numbers).
        cores = "%.1f, " % r["container_cpus"] if r.get("container_cpus") is not None else ""
        return cores + ("-".join("%.0f" % x for x in (r.get("load") or [])) or "-")

    for screen in screens:
        gpu, cpu = load_session(os.path.join(out, "gpu-" + screen)), load_session(os.path.join(out, "cpu-" + screen))
        print("\n#### %s\n" % screen.replace("x", " x "))
        for name, sess in (("GPU", gpu), ("CPU", cpu)):
            r = sess.get("renderer")
            if r:
                print("- %s: the game's OpenGL renderer %s (%s)%s" % (
                    name, r.get("renderer") or "not found", r.get("gl_version") or "-",
                    ", its process drawing through WSL's D3D12" if r.get("gpu_proof") else ""))
        print()
        print("| Scene | GPU fps | GPU spread, 99 % (ms) | GPU chain span (us) | GPU cores, load | CPU fps | CPU spread, 99 % (ms) | CPU cores, load |")
        print("|---|---|---|---|---|---|---|---|")
        for run in ORDER:
            g, c = gpu.get(run), cpu.get(run)
            if not g and not c:
                continue

            def cells(r, with_chain):
                if not r:
                    return ["-", "-"] + (["-"] if with_chain else []) + ["-"]
                if r.get("run") == "present":
                    out_cells = ["%s (%s ms a frame)" % (f(r.get("fps_median"), "%.0f"), f(r.get("present_ms"), "%.2f")), "-"]
                else:
                    out_cells = [f(r.get("fps_median")),
                                 "%s, %s" % (f(r.get("sd_ms_median"), "%.2f"), f(r.get("p99_ms_median"), "%.1f"))
                                 if r.get("fps_median") else "-"]
                if with_chain:
                    out_cells.append(f(r.get("chain_gpu_us_median"), "%.0f"))
                return out_cells + [load(r)]
            print("| %s | %s | %s |" % (LABELS.get(run, run), " | ".join(cells(g, True)), " | ".join(cells(c, False))))
        gp, cp = gpu.get("parts-frame", {}).get("parts", {}), cpu.get("parts-frame", {}).get("parts", {})
        gg = gpu.get("parts-gpu", {}).get("parts", {})
        # The frames while a part shows, from the run that disturbs them least on each renderer: on the GPU the frame
        # timing run (with Wine's Direct3D command thread on, the timestamps' run lost frames there), on the CPU the
        # timestamps' run (cheap on llvmpipe, where the frame timing's idle waits stall it).
        cg = cpu.get("parts-gpu", {}).get("parts", {})
        if gp or cp or gg:
            print()
            print("| Part | GPU: adds a frame | GPU: its timestamps (us) | GPU fps (spread) while shown | CPU: adds a frame | CPU fps (spread) while shown |")
            print("|---|---|---|---|---|---|")
            for part in PARTS + ("off",):
                a, b, k, kc = gp.get(part, {}), cp.get(part, {}), gg.get(part, {}), cg.get(part, {})
                name = "nothing but the mark" if part == "off" else part

                def adds(e):
                    if "adds_us_median" in e:
                        return "%s us" % f(e.get("adds_us_median"), "%+.0f")
                    if "whole_us_median" in e:
                        return "%s us whole" % f(e.get("whole_us_median"), "%.0f")
                    return "-"

                def shown(e):
                    return "%s (%s)" % (f(e.get("fps_median")), f(e.get("sd_ms_median"), "%.2f")) if e.get("fps_median") else "-"
                print("| %s | %s | %s | %s | %s | %s |" % (
                    name, adds(a), f(k.get("gpu_us_total"), "%.0f") if "gpu_us_total" in k else "-", shown(a), adds(b),
                    shown(kc)))


def main(argv):
    if argv[0] == "run":
        r = run_numbers(argv[1], argv[2])
        save(argv[1], r)
        print(one_line(r))
    elif argv[0] == "table":
        for run, r in sorted(load_session(argv[1]).items(), key=lambda kv: (ORDER + [kv[0]]).index(kv[0])):
            print(one_line(r))
    elif argv[0] == "compare":
        compare(argv[1])
    elif argv[0] == "passes" and len(argv) > 2:
        passes_versus(argv[1], argv[2])
    elif argv[0] == "passes":
        passes_table(argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
