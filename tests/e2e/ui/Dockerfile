# The launcher's UI test machine: Linux Python with Tk, a virtual X screen and screenshot tools.
# Nothing here reaches a real screen; the tests run with OPENDMT3_VIRTUAL_DISPLAY=1 only inside it.
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
        libtk8.6 tk8.6 xvfb x11-utils xdotool imagemagick fontconfig curl xz-utils ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pillow==11.3.0
# The official 7-Zip, the same release the Windows launcher brings (the distribution's p7zip cannot open RAR5), pinned
# and checked: the screens of archives list, test and unpack made-up archives with it.
RUN curl -fsSL -o /tmp/7z.tar.xz https://www.7-zip.org/a/7z2501-linux-x64.tar.xz \
    && echo "4ca3b7c6f2f67866b92622818b58233dc70367be2f36b498eb0bdeaaa44b53f4  /tmp/7z.tar.xz" | sha256sum -c - \
    && tar -xJf /tmp/7z.tar.xz -C /usr/local/bin 7zz && rm /tmp/7z.tar.xz
ENV OPENDMT3_VIRTUAL_DISPLAY=1 DISPLAY=:99 OPENDMT3_7ZIP=/usr/local/bin/7zz
