# The Wine tests' image drawn on a WSL machine's own GPU (tests/e2e/windows/gpu.sh): Wine in its new WoW64 mode (32-bit
# Windows programs on a 64-bit Unix side) and Mesa's d3d12 driver, on the same virtual screen and tools as
# packaging/wine. The CPU image (packaging/wine) stays the default and the one CI and the Windows build use.
#
# Why WoW64: the game is a 32-bit Direct3D 9 program. In packaging/wine's classic multiarch Wine a 32-bit program loads
# 32-bit Mesa, which has no d3d12 driver (WSL's libd3d12.so is 64-bit only), so it draws with llvmpipe on the CPU. In
# WoW64 mode its OpenGL calls cross to the 64-bit side, where Mesa's d3d12 driver hands them to the GPU through
# WSL's /dev/dxg. Wine is built here from the release's own source (WineHQ ships classic multiarch packages only),
# with one change to its WoW64 OpenGL (wine-wow64-gl-flush.patch), and draws through GLX with no Direct3D command
# thread (below).
#
#   docker build -t opendmt3-wine-gpu:local tests/e2e/windows/gpu
#
# The build compiles Wine (about 15 minutes on 10 CPUs); on a machine others use, cap it with the legacy builder:
#   DOCKER_BUILDKIT=0 docker build --cpu-period=100000 --cpu-quota=1000000 --build-arg JOBS=10 \
#     -t opendmt3-wine-gpu:local tests/e2e/windows/gpu
# Run with WSL's GPU (gpu.sh does this): --device /dev/dxg, /usr/lib/wsl/lib and /usr/lib/wsl/drivers read only,
# LD_LIBRARY_PATH=/usr/lib/wsl/lib and GALLIUM_DRIVER=d3d12. No game files and no Windows files are inside.

# ---------------------------------------------------------------------------------------------------- the Wine build
# The same Debian release as packaging/wine, so the two images differ in Wine's mode and the renderer, not the system.
FROM debian:bookworm AS build
# The Wine release the CPU image has (WineHQ's winehq-stable 11.0.0.0), from its source tarball, checked by its hash
# (the SHA-256 of the file whose SHA-512 is in WineHQ's signed sha512sums.asc for 11.0).
ARG WINE_VERSION=11.0
ARG WINE_SHA256=c07a6857933c1fc60dff5448d79f39c92481c1e9db5aa628db9d0358446e0701
# Parallel compile jobs: the container sees every CPU (nproc), so the count is given, not guessed.
ARG JOBS=10
# The compilers (the host's for the Unix side, MinGW's for both Windows sides) and the 64-bit development files of what
# the tests use: X11 and its extensions, fonts, OpenGL through EGL and GLX, Vulkan, ALSA sound, TLS, D-Bus, unwinding.
# A WoW64 build needs no 32-bit Unix library at all.
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
      ca-certificates curl xz-utils gcc libc6-dev make flex bison \
      gcc-mingw-w64-i686-win32 gcc-mingw-w64-x86-64-win32 \
      libx11-dev libxext-dev libxrender-dev libxrandr-dev libxi-dev libxcursor-dev libxcomposite-dev \
      libxinerama-dev libxfixes-dev libxxf86vm-dev libfreetype-dev libfontconfig-dev libgl-dev libegl-dev \
      libvulkan-dev libasound2-dev libgnutls28-dev libdbus-1-dev libunwind-dev >/dev/null \
    && rm -rf /var/lib/apt/lists/*
# The source, refused unless it is exactly the release's.
RUN curl -fsSL -o /tmp/wine.tar.xz "https://dl.winehq.org/wine/source/${WINE_VERSION%%.*}.0/wine-${WINE_VERSION}.tar.xz" \
    && echo "${WINE_SHA256}  /tmp/wine.tar.xz" | sha256sum -c - \
    && mkdir /src && tar -xf /tmp/wine.tar.xz -C /src --strip-components=1 && rm /tmp/wine.tar.xz
WORKDIR /src
# WoW64: both Windows architectures in one 64-bit Wine. Left out: what no test here touches (Wayland, media
# frameworks, printing, scanners, cameras, smart cards, USB, PulseAudio: the tests' sound is ALSA's null device). The
# compile at the lowest priority, so it takes what others leave.
RUN ./configure --prefix=/opt/wine --enable-archs=i386,x86_64 --disable-tests \
      --without-wayland --without-gstreamer --without-ffmpeg --without-cups --without-sane --without-gphoto \
      --without-v4l2 --without-pcsclite --without-pcap --without-usb --without-capi --without-krb5 --without-gssapi \
      --without-netapi --without-opencl --without-sdl --without-udev --without-pulse --without-oss > /tmp/configure.log \
    && grep "^configure:" /tmp/configure.log | tail -30
RUN nice -n 19 make -j"${JOBS}" -s > /tmp/make.log 2>&1 || { tail -60 /tmp/make.log; exit 1; }
# One change to Wine's WoW64 OpenGL (wine-wow64-gl-flush.patch says why): without it every DrawPrimitiveUP of the game
# and of the in-game layer costs about a millisecond on WSL's GPU, which no Windows PC has. Applied after the build
# above so that build stays cached; make then compiles again only what the patch touched.
COPY wine-wow64-gl-flush.patch /tmp/
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends patch >/dev/null \
    && patch -p1 < /tmp/wine-wow64-gl-flush.patch && nice -n 19 make -j"${JOBS}" -s > /tmp/make2.log 2>&1 \
    || { tail -60 /tmp/make2.log; exit 1; }
# Only what runs Wine (no headers, no development tools), without symbols.
RUN make install-lib -s >/dev/null && find /opt/wine -name "*.so" -exec strip --strip-unneeded {} + \
    && strip /opt/wine/bin/wine /opt/wine/bin/wineserver /opt/wine/bin/wine-preloader 2>/dev/null; \
    ls /opt/wine/lib/wine/

# ------------------------------------------------------------------------------------------------------ the image
FROM debian:bookworm
# Wine's 64-bit Unix side's libraries (the ones the build above found), and Mesa: its EGL and GLX libraries and its
# 64-bit drivers, among them d3d12 (the GPU through WSL) and llvmpipe (the CPU, when GALLIUM_DRIVER is not d3d12).
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
      libx11-6 libxext6 libxrender1 libxrandr2 libxi6 libxcursor1 libxcomposite1 libxinerama1 libxfixes3 libxxf86vm1 \
      libfreetype6 libfontconfig1 fonts-dejavu-core libgl1 libglx-mesa0 libegl1 libegl-mesa0 libgl1-mesa-dri \
      libvulkan1 libasound2 libgnutls30 libdbus-1-3 libunwind8 >/dev/null \
    && rm -rf /var/lib/apt/lists/*
# The tests' tools, as packaging/wine and tests/e2e/windows/ingame have them: the virtual screen, screenshots of it, a
# way to click and type on it, python3 with Xlib for the pointer's picture (XFixes); and glxinfo for the renderer.
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
      python3 python3-xlib xvfb xauth x11-utils x11-apps imagemagick procps xdotool iproute2 mesa-utils >/dev/null \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /opt/wine /opt/wine
# wine, wineboot and wineserver first on the PATH, as /opt/wine-stable/bin is in packaging/wine.
ENV PATH=/opt/wine/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# Two defaults every prefix this image makes gets (wine.inf, which wineboot writes them from):
# - GLX, not EGL (Wine's X11 driver's UseEGL=N): on the virtual screen, which has no DRI3, Mesa puts each frame there
#   more cheaply through GLX, measured 8.3 ms a frame against EGL's 27.5 for a 1920 x 1920 window on the GPU. Showing
#   a frame is the test's own cost, not the game's, so the cheaper way keeps the frame times nearer a player's.
# - Direct3D with no command thread of its own (csmt=0): WoW64's OpenGL has no buffer storage, so with that thread
#   every DrawPrimitiveUP waited for it to catch up, 140 to 340 us of the layer's CPU time for each of its parts on
#   this PC against 6 to 19 us without it (the CPU image's are 2 to 8). A Direct3D 9 call on Windows does not wait so.
RUN sed -i 's/^\[Misc\]$/[Misc]\nHKCU,Software\\Wine\\X11 Driver,"UseEGL",,"N"\nHKCU,Software\\Wine\\Direct3D,"csmt",0x10001,0/' \
      /opt/wine/share/wine/wine.inf \
    && grep -q '^HKCU,Software\\Wine\\X11 Driver,"UseEGL",,"N"$' /opt/wine/share/wine/wine.inf \
    && grep -q '^HKCU,Software\\Wine\\Direct3D,"csmt",0x10001,0$' /opt/wine/share/wine/wine.inf
# Every 32-bit Windows program goes through WoW64: a check at build time that this Wine has no 32-bit Unix side.
RUN test -d /opt/wine/lib/wine/i386-windows && test -d /opt/wine/lib/wine/x86_64-unix \
    && test ! -e /opt/wine/lib/wine/i386-unix
