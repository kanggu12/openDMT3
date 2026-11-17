# PyInstaller recipe for the Windows server package: one folder with opendmt3-server.exe, a console program (the
# server's own command line, opendmt3/server/standalone.py), the site's pages and files, and the official 7-Zip for
# the client data's archives. No window toolkit, no launcher: only what the server runs. Run by
# packaging/windows/server.sh inside the Wine build container, from the repository root.
import os
import runpy

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(".")
# The icon and the version file (assets.py), made first by server.sh.
BUILD = os.environ["OPENDMT3_BUILD_DIR"]
# The launcher's own leave-outs (tests, docs tools, Pillow's codecs the site never decodes) apply here too.
PARTS = runpy.run_path(os.path.join(ROOT, "packaging", "windows", "launcher_parts.py"))

analysis = Analysis(
    [os.path.join(ROOT, "packaging", "windows", "server_entry.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "opendmt3", "server", "web", "templates"), os.path.join("opendmt3", "server", "web", "templates")),
           (os.path.join(ROOT, "opendmt3", "server", "web", "static"), os.path.join("opendmt3", "server", "web", "static")),
           # The official 7-Zip for Windows with its licence (sevenzip.sh): server_entry.py names it for the reading.
           *[(os.path.join(os.environ["OPENDMT3_7ZIP_DIR"], name), os.path.join("opendmt3", "server", "bin", "7-Zip"))
             for name in ("7z.exe", "7z.dll", "License.txt", "readme.txt")],
           # The fonts the site serves at /fonts (web/app.py FONTS: the launcher's own set, one copy for both), with
           # their licences.
           (os.path.join(ROOT, "opendmt3", "client", "assets", "fonts"), os.path.join("opendmt3", "client", "assets", "fonts")),
           # openDMT3's own licence beside the package, where the site's Licenses page reads it (server/web/common.py).
           (os.path.join(ROOT, "LICENSE"), ".")],
    # The site is imported inside a function, and uvicorn picks its parts by name. The server's own command line
    # (server/__main__.py, which standalone.py runs in-process) is a package's __main__, which PyInstaller never takes
    # in by itself.
    hiddenimports=["opendmt3.server.__main__", "opendmt3.server.web.app", "multipart"] + collect_submodules("uvicorn"),
    # The launcher's parts and Tk are never imported by the server; left out so nothing pulls them in by a stray path.
    excludes=PARTS["EXCLUDES"] + ["tkinter", "_tkinter", "opendmt3.client", "velopack", "PIL.ImageTk",
                                  "PIL._tkinter_finder"],
    noarchive=False,
)
# Windows' own C runtime stays Windows' (launcher_parts.kept_binary).
analysis.binaries = [entry for entry in analysis.binaries if PARTS["kept_binary"](entry[0])]
program = EXE(PYZ(analysis.pure), analysis.scripts, [], exclude_binaries=True, name="opendmt3-server", console=True,
              icon=os.path.join(BUILD, "openDMT3.ico"), version=os.path.join(BUILD, "server-version.txt"))
COLLECT(program, analysis.binaries, analysis.datas, name="opendmt3-server")
