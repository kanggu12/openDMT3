# The Wine image (packaging/wine) with python3-xlib besides, for tests/e2e/windows/ingame.sh to read the pointer's
# picture through XFixes.
#   docker build -t opendmt3-wine-ingame:local tests/e2e/windows/ingame
FROM opendmt3-wine:local
RUN apt-get update && apt-get install -y --no-install-recommends python3-xlib && rm -rf /var/lib/apt/lists/*
