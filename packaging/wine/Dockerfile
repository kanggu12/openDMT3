# Wine on a virtual screen: the base of the Windows build (packaging/windows/Dockerfile) and of the tests that run
# the launcher and the game under Wine (tests/e2e/windows/). No game files and no Windows files are inside.
#   docker build -t opendmt3-wine:local packaging/wine
FROM debian:bookworm
# Wine 11 from WineHQ, 32- and 64-bit, at one exact version so every build and test run behaves the same.
RUN dpkg --add-architecture i386 && apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
      --no-install-recommends ca-certificates curl gnupg python3 >/dev/null \
    && mkdir -pm755 /etc/apt/keyrings \
    && curl -fsSL https://dl.winehq.org/wine-builds/winehq.key | gpg --dearmor -o /etc/apt/keyrings/winehq-archive.key \
    && curl -fsSL -o /etc/apt/sources.list.d/winehq-bookworm.sources \
      https://dl.winehq.org/wine-builds/debian/dists/bookworm/winehq-bookworm.sources \
    && apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --install-recommends \
      winehq-stable=11.0.0.0~bookworm-1 wine-stable=11.0.0.0~bookworm-1 wine-stable-amd64=11.0.0.0~bookworm-1 \
      wine-stable-i386=11.0.0.0~bookworm-1 >/dev/null \
    && rm -rf /var/lib/apt/lists/*
ENV PATH=/opt/wine-stable/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# The virtual screen, screenshots of it, and a way to click and type on it.
RUN apt-get update && apt-get install -y --no-install-recommends xvfb xauth x11-utils x11-apps imagemagick procps \
      xdotool iproute2 && rm -rf /var/lib/apt/lists/*
