# The Windows build machine: Wine with a Windows Python that has Tk, PyInstaller and the launcher's two
# libraries. The Python is python-build-standalone's Windows build (an archive, no installer to run under Wine).
# Built by packaging/windows/build.sh, which passes the archive in and checks its hash first.
# packaging/wine: Wine on a virtual screen (build.sh makes it first).
FROM opendmt3-wine:local
ENV WINEPREFIX=/wine WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml="
COPY pbs.tar.gz /tmp/pbs.tar.gz
# The Windows Python lives at C:\python inside the Wine prefix.
RUN wineboot -i >/dev/null 2>&1; wineserver -w; \
    mkdir -p /wine/drive_c && tar -xzf /tmp/pbs.tar.gz -C /wine/drive_c && rm /tmp/pbs.tar.gz
# Exact versions, so every build bundles the same code. The web libraries are the server's (packaging/docker): the
# launcher runs the site for playing on this PC.
RUN wine 'C:\python\python.exe' -m pip install --no-warn-script-location --disable-pip-version-check \
        pyinstaller==6.16.0 pillow==11.3.0 velopack==1.2.161 \
        starlette==0.47.3 jinja2==3.1.6 uvicorn==0.35.0 python-multipart==0.0.20 >/tmp/pip.log 2>&1 \
    || (cat /tmp/pip.log; exit 1); wineserver -w
