# shellcheck shell=bash
# Which renderer a Wine test's container draws with, sourced by install_and_play.sh, offline_play.sh, play_a_song.sh,
# ingame.sh, gpu/check.sh and gpu/measure.sh (OPENDMT3_WINE_GPU=1 tests/e2e/windows/ingame.sh ..., say):
#   unset (the default, and CI's)  the CPU image the test names (packaging/wine, or ingame's on top of it): Mesa's
#                                  llvmpipe draws every frame on the CPU
#   OPENDMT3_WINE_GPU=1            the GPU image (gpu/Dockerfile: Wine in WoW64 mode and Mesa's d3d12 driver) with
#                                  WSL's GPU handed to the container: the frames are drawn on this PC's graphics card,
#                                  each read back to the virtual screen
# The GPU needs WSL 2 with the graphics card's Windows driver: /dev/dxg, /usr/lib/wsl/lib (WSL's D3D12 and DXCore
# libraries) and /usr/lib/wsl/drivers (the card's own user-mode driver, which WSL's D3D12 loads from there). Nothing
# is drawn on the Windows desktop: the container's virtual screen is the only one it has.
#
#   wine_image CPU_IMAGE   the image to run (CPU_IMAGE on the CPU)
#   wine_name NAME         the container's name: NAME on the CPU, odt3-gpu-NAME on the GPU, so a GPU run never removes
#                          a CPU run of the same test going on at the same time
#   WINE_RUN_ARGS          docker run's arguments for the renderer (none on the CPU)
# Inside the container the tests start their virtual screen as `env -u GALLIUM_DRIVER -u LD_LIBRARY_PATH Xvfb`: Xvfb
# only shows what it is sent, and with WSL's variables its own GLX would make a D3D12 device it never uses (on the
# CPU image the variables are not set and the command is plain Xvfb).
#   gpu_proof CONTAINER PROCESS   on the GPU, whether the program PROCESS (a part of its command line) in CONTAINER
#                          draws through WSL's D3D12: its memory has WSL's libd3d12 and it holds /dev/dxg open; the
#                          finding printed, exit 1 when it does not (so a GPU run that fell back to the CPU fails)

# The GPU image's name, and its recipe beside this file.
WINE_GPU_IMAGE=opendmt3-wine-gpu:local
WINE_GPU_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/gpu

wine_on_gpu() { [ "${OPENDMT3_WINE_GPU:-}" = 1 ]; }

wine_image() {
  if wine_on_gpu; then echo "$WINE_GPU_IMAGE"; else echo "$1"; fi
}

wine_name() {
  if wine_on_gpu; then echo "odt3-gpu-$1"; else echo "$1"; fi
}

WINE_RUN_ARGS=()
if wine_on_gpu; then
  # WSL's GPU: its device, its libraries and the card's driver store, read only, and Mesa told to draw through D3D12
  # (WSLg sets the same two variables); Mesa finds libd3d12.so and libdxcore.so on LD_LIBRARY_PATH.
  for need in /dev/dxg /usr/lib/wsl/lib/libd3d12.so /usr/lib/wsl/lib/libdxcore.so /usr/lib/wsl/drivers; do
    [ -e "$need" ] || { echo "FAIL: OPENDMT3_WINE_GPU=1 needs WSL's GPU ($need is missing)"; exit 1; }
  done
  WINE_RUN_ARGS=(--device /dev/dxg -v /usr/lib/wsl/lib:/usr/lib/wsl/lib:ro -v /usr/lib/wsl/drivers:/usr/lib/wsl/drivers:ro
                 -e LD_LIBRARY_PATH=/usr/lib/wsl/lib -e GALLIUM_DRIVER=d3d12)
  # No core dumps: a Direct3D program drawn through Mesa's d3d12 driver was seen to crash in its last moments, after
  # its exit code was set (wined3d's command thread, as the libraries went), and WSL's crash capture writes every such
  # dump into Windows' temporary folder (a limit of 1 is the kernel's sign to skip a dump that goes to a program).
  WINE_RUN_ARGS+=(--ulimit core=1)
  # Built the first time (it compiles Wine: about 15 minutes).
  if ! docker image inspect "$WINE_GPU_IMAGE" >/dev/null 2>&1; then
    echo "  building $WINE_GPU_IMAGE (Wine in WoW64 mode, compiled once: about 15 minutes)"
    docker build -q -t "$WINE_GPU_IMAGE" "$WINE_GPU_DIR" >/dev/null || { echo "FAIL: the GPU image did not build"; exit 1; }
  fi
fi

gpu_proof() {
  wine_on_gpu || return 0
  # Every process whose command line holds PROCESS: its mapped files and its open files, read from inside.
  docker exec "$1" sh -c '
    for d in /proc/[0-9]*; do
      case "$(tr "\0" " " < "$d/cmdline" 2>/dev/null)" in *"$0"*) ;; *) continue ;; esac
      d3d12=$(grep -c "/usr/lib/wsl/lib/libd3d12" "$d/maps" 2>/dev/null)
      dxg=$(ls -l "$d/fd" 2>/dev/null | grep -c " /dev/dxg$")
      if [ "${d3d12:-0}" -gt 0 ] && [ "${dxg:-0}" -gt 0 ]; then
        echo "  on the GPU: process ${d#/proc/} has WSL'"'"'s libd3d12 in its memory and /dev/dxg open ($dxg)"
        exit 0
      fi
    done
    echo "  not on the GPU: no process of $0 has WSL'"'"'s libd3d12 and /dev/dxg"
    exit 1' "$2"
}
