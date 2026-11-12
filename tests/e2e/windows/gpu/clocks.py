#!/usr/bin/env python3
"""The graphics card's clocks while a measuring run goes on: every half second, the monotonic clock's milliseconds (the
clock measure.sh marks its phases by) and the card's performance state, its shader and memory clocks (MHz) and how busy
it is (%), as WSL's nvidia-smi reads them, one line each into OUT. A GPU's time for a pass scales with its shader clock,
and an NVIDIA card idles along at a few hundred MHz under a load as light as this game's, so measure.py puts each
phase's median clock beside its times. Ends when STOP_FILE appears (or after LIMIT seconds); nothing on a PC with no
nvidia-smi.

    clocks.py OUT STOP_FILE [LIMIT]
"""
import os
import shutil
import subprocess
import sys
import time

# WSL's own copy of the NVIDIA tool (the driver store's), else one on the path.
TOOL = "/usr/lib/wsl/lib/nvidia-smi" if os.path.exists("/usr/lib/wsl/lib/nvidia-smi") else shutil.which("nvidia-smi")
QUERY = "--query-gpu=pstate,clocks.sm,clocks.mem,utilization.gpu"


def main(argv):
    out, stop = argv[0], argv[1]
    # An hour at most by default: a run that never says it ended does not leave this going.
    limit = float(argv[2]) if len(argv) > 2 else 3600.0
    if not TOOL:
        return 0
    began = time.monotonic()
    with open(out, "a", encoding="ascii") as f:
        while not os.path.exists(stop) and time.monotonic() - began < limit:
            at = int(time.monotonic() * 1000)
            try:
                # One reading: "P0, 225, 10501, 14" with no units.
                text = subprocess.run([TOOL, QUERY, "--format=csv,noheader,nounits"], capture_output=True,
                                      text=True, timeout=5).stdout.strip().splitlines()
            except (OSError, subprocess.SubprocessError):
                text = []
            if text:
                # The first card's line only, its fields apart by spaces.
                f.write("%d %s\n" % (at, " ".join(p.strip() for p in text[0].split(","))))
                f.flush()
            # Half a second between readings (each reading itself takes a few tens of milliseconds).
            time.sleep(0.5)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
