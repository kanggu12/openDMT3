"""The renderer check's findings side by side (tests/e2e/windows/gpu/check.sh).

    python3 compare.py OUT_DIR GPU_RUN OTHER_RUN...

Each run left in OUT_DIR its probe's output (RUN.txt: d3d9probe.exe's lines and its exit code), the frame it read
back (RUN.bmp) and the screen's copy of its window (RUN-screen.bmp). Passes when:
  - the GPU run's OpenGL renderer names D3D12 (Mesa's d3d12 driver: the frames are drawn by the graphics card);
  - every run had all of the probe's points as they must be (the known picture drawn right);
  - the GPU run's frame matches each other run's (llvmpipe's: the reference) in every pixel, within 2 a channel;
  - each run's screen shows the frame it read back (the picture reached the virtual screen as it was drawn).
Plain Python, 24-bit BMP files only (ingame/picture.py's reader).
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ingame"))
from picture import bmp  # noqa: E402

# Pixels that may differ between two renderers' frames of the same picture: none. Every edge of the probe's shapes
# lies half way between pixel centres and every texel covers whole pixels, so no pixel's coverage or texel is in
# doubt; a blend's rounding stays within the tolerance of 2.
EDGE_PIXELS = 0


def differing(a, b, tolerance=2):
    """How many pixels of two equal-sized frames differ by more than the tolerance in a channel."""
    if a[0] != b[0] or a[1] != b[1]:
        return None
    count = 0
    for ra, rb in zip(a[2], b[2]):
        if ra == rb:
            continue
        for x in range(0, len(ra), 3):
            if any(abs(ra[x + i] - rb[x + i]) > tolerance for i in range(3)):
                count += 1
    return count


def run(out, name):
    """A run's lines: its OpenGL strings, its adapter, its points, its timings and exit code."""
    text = open(os.path.join(out, name + ".txt"), errors="replace").read()
    found = {
        "text": text,
        "renderer": (re.search(r'renderer "([^"]*)"', text) or [None, "none"])[1],
        "version": (re.search(r'version "([^"]*)"', text) or [None, "none"])[1],
        "adapter": (re.search(r'adapter "([^"]*)"', text) or [None, "none"])[1],
        "points": re.search(r"picture: (\d+) of (\d+) points", text),
        "present": (re.search(r"presented ([\d.]+) ms a frame", text) or [None, None])[1],
        "fill": (re.search(r"window ([\d.]+) ms a frame, finished", text) or [None, None])[1],
        "exit": (re.search(r"^exit (\d+)", text, re.M) or [None, "?"])[1],
        "process": (re.search(r"process: (\d+)-bit", text) or [None, "?"])[1],
    }
    return found


def main(out, gpu, others):
    ok = True
    runs = {name: run(out, name) for name in [gpu] + others}
    for name, r in runs.items():
        points = "%s of %s" % r["points"].groups() if r["points"] else "none"
        print("  %-10s %s-bit process; OpenGL renderer \"%s\" (%s); Direct3D 9 adapter \"%s\"" % (
            name, r["process"], r["renderer"], r["version"], r["adapter"]))
        print("  %-10s points as they must be: %s; drawn and presented %s ms a frame; 500 blended quads %s ms a "
              "frame; exit %s" % ("", points, r["present"] or "?", r["fill"] or "?", r["exit"]))
        if not r["points"] or r["points"].group(1) != r["points"].group(2) or r["exit"] != "0":
            print("  FAIL: %s did not draw the known picture right" % name)
            ok = False
        # The screen against the frame read back: the picture as it reached the virtual screen.
        frame, screen = bmp(os.path.join(out, name + ".bmp")), bmp(os.path.join(out, name + "-screen.bmp"))
        d = differing(frame, screen)
        print("  %-10s the screen against the frame read back: %s pixels differ" % ("", "?" if d is None else d))
        if d is None or d > 0:
            print("  FAIL: %s's screen does not show what it drew" % name)
            ok = False
    if "D3D12" not in runs[gpu]["renderer"]:
        print("  FAIL: the GPU run's OpenGL renderer does not name D3D12: it did not draw on the graphics card")
        ok = False
    # The GPU's frame against each other renderer's.
    gpu_frame = bmp(os.path.join(out, gpu + ".bmp"))
    for name in others:
        d = differing(gpu_frame, bmp(os.path.join(out, name + ".bmp")))
        print("  %s's frame against %s's: %s of %d pixels differ by more than 2 a channel" % (
            gpu, name, "?" if d is None else d, gpu_frame[0] * gpu_frame[1]))
        if d is None or d > EDGE_PIXELS:
            print("  FAIL: %s's frame is not %s's picture" % (gpu, name))
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3:]))
