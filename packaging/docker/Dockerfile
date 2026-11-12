# The openDMT3 server (game and site) as a container. No game files are inside: the song list (with its jackets and the
# DJ cards) is imported from the owner's own game folder, an archive holding it, or a song list the launcher saved
# (--catalog, or Admin, Song list), and accounts, plays and the installer to hand out live in /data.
#   docker build -f packaging/docker/Dockerfile -t opendmt3-server .
# The first account is made with --add-player (see compose.yaml): the first-run page is for visits from the
# server PC itself, and through Docker's network no visit is.
FROM python:3.12-slim-bookworm
# Exact versions, so every image runs the same site.
# Pillow keeps the jackets and the DJ cards' pictures in one form when the song list is imported (the launcher bundles
# the same version).
RUN pip install --no-cache-dir starlette==0.47.3 jinja2==3.1.6 uvicorn==0.35.0 python-multipart==0.0.20 pillow==11.3.0
# The official 7-Zip, which opens an archive holding the game (.zip, .7z, .rar, split ones; the distribution's p7zip
# cannot open RAR5): the release OpenDMTQ's tools pin, checked against the hash of the copy that was tested. Its
# licence stays in the image with it.
ADD --chmod=0644 --checksum=sha256:4ca3b7c6f2f67866b92622818b58233dc70367be2f36b498eb0bdeaaa44b53f4 \
    https://www.7-zip.org/a/7z2501-linux-x64.tar.xz /tmp/7z.tar.xz
# Unpacked with Python's own reader (the slim image has no xz program): the program, then its licence and readme.
RUN python -c "import tarfile; t = tarfile.open('/tmp/7z.tar.xz'); t.extract('7zz', '/usr/local/bin', filter='data'); \
[t.extract(n, '/usr/local/share/doc/7-zip', filter='data') for n in ('License.txt', 'readme.txt')]" \
    && chmod 0755 /usr/local/bin/7zz && rm /tmp/7z.tar.xz
# The server runs as its own user, not root.
RUN useradd --create-home --uid 4725 opendmt3 && mkdir /data && chown opendmt3 /data
COPY --chown=opendmt3 opendmt3 /app/opendmt3
# The package's bytecode, made now: the server never writes it (PYTHONDONTWRITEBYTECODE below), so without it every
# start compiled every module again (the server's imports took 286 ms, 230 with it, the median of 7 on a busy PC).
# Checked by nothing at start (unchecked hash): the image's sources never change, and a tree mounted over
# /app/opendmt3 brings its own folders.
RUN python -m compileall -q --invalidation-mode unchecked-hash /app/opendmt3
# openDMT3's own licence beside the package, where the site's Licenses page reads it (server/web/common.py).
COPY --chown=opendmt3 LICENSE /app/LICENSE
WORKDIR /app
USER opendmt3
# OPENDMT3_IN_CONTAINER: the server sees only the folders its compose file gives it (the Song list tab names the
# command for any other folder instead of showing a folder browser). MALLOC_ARENA_MAX: the C library's memory in two
# pools for all of the server's threads (the site's workers, the game server's database thread), not one a thread:
# with one a thread the server held 155 MB after 20 visitors at once (43 MB before it had threads), memory each
# thread's pool keeps once it is freed.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENDMT3_IN_CONTAINER=1 MALLOC_ARENA_MAX=2
VOLUME /data
# 4725: the game connects here. 4730: the site and the launcher's API.
EXPOSE 4725 4730
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4730/health', timeout=4)"
ENTRYPOINT ["python", "-m", "opendmt3.server", "--data", "/data", "--host", "0.0.0.0"]
