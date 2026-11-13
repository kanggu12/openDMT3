# PyInstaller recipe for the Windows launcher: one folder with two programs that share it.
#   openDMT3.exe      the window (no console), the one the installer's shortcuts start
#   openDMT3-cmd.exe  the same program with a console, for --check, --play, --restore and --set
# Run by packaging/windows/build.sh inside the Wine build container, from the repository root.
import os
import runpy

from PyInstaller.archive.readers import CArchiveReader
from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(".")
BUILD = os.environ.get("OPENDMT3_BUILD_DIR", os.path.join(ROOT, "build", "windows"))
# What the launcher never uses, left out of the folder people install and of every update (launcher_parts.py, which the
# installer's recipe leaves out too): Pillow's AVIF and WebP codecs and colour management, Tcl's time zones, message
# catalogs and other systems' character sets.
PARTS = runpy.run_path(os.path.join(ROOT, "packaging", "windows", "launcher_parts.py"))

analysis = Analysis(
    [os.path.join(ROOT, "packaging", "windows", "entry.py")],
    pathex=[ROOT],
    # Fonts and their licences travel with the launcher (theme.py looks for them next to itself; the in-game layer's
    # copy of them is taken from there too, core/cabinet/native.py: one set of fonts in the folder).
    datas=[(os.path.join(ROOT, "opendmt3", "client", "assets"), os.path.join("opendmt3", "client", "assets")),
           # openDMT3's card reader and in-game layer (native/cardreader), built first by build.sh, with its touch
           # screen library and the notices of the code built into them: wherever the launcher puts the library, they
           # go with it (core/cabinet/native.py).
           *[(os.path.join(os.environ["OPENDMT3_NATIVE_DIR"], name), os.path.join("opendmt3", "core", "cabinet", "bin"))
             for name in ("CRT_R1.dll", "multiDLL.dll", "card-reader-NOTICES.txt")],
           # The Sound page's OpenAL Soft mixer (native/openal/build.sh): DSOAL and OpenAL Soft with their notices,
           # beside the library in bin/, from where PLAY puts them beside its copy (core/cabinet/native.py openal).
           *[(os.path.join(os.environ["OPENDMT3_OPENAL_DIR"], name), os.path.join("opendmt3", "core", "cabinet", "bin"))
             for name in ("dsoal-aldrv.dll", "openDMT3-dsoal.dll", "openal-NOTICES.txt")],
           # The official 7-Zip for Windows with its licence (build.sh takes them out of the release's installer):
           # the launcher lists, tests and unpacks the game's archives with it (client/main.py points the reading at it).
           *[(os.path.join(os.environ["OPENDMT3_7ZIP_DIR"], name), os.path.join("opendmt3", "client", "bin", "7-Zip"))
             for name in ("7z.exe", "7z.dll", "License.txt", "readme.txt")],
           # Where releases are published (empty when the build was given none); client/updates.py reads it.
           (os.path.join(BUILD, "update-source.txt"), os.path.join("opendmt3", "client")),
           # A test build's own update key (empty in every other build: the launcher takes the project's key alone);
           # core/signing.py reads it.
           (os.path.join(BUILD, "update-test-keys.txt"), os.path.join("opendmt3", "core")),
           # The site the launcher runs for playing on this PC (client/hosting.py): its pages and their files.
           (os.path.join(ROOT, "opendmt3", "server", "web", "templates"), os.path.join("opendmt3", "server", "web", "templates")),
           (os.path.join(ROOT, "opendmt3", "server", "web", "static"), os.path.join("opendmt3", "server", "web", "static")),
           # openDMT3's own licence beside the package, where the site's Licenses page reads it (server/web/common.py),
           # as in a copy of the repository and in the server's image.
           (os.path.join(ROOT, "LICENSE"), ".")],
    # Pillow finds Tk through this module at run time; PyInstaller cannot see that import. The site is imported
    # inside a function, and uvicorn picks its parts by name.
    hiddenimports=["PIL._tkinter_finder", "opendmt3.server.web.app", "multipart"] + collect_submodules("uvicorn"),
    # Nothing the launcher never uses: smaller and faster to start.
    excludes=PARTS["EXCLUDES"],
    noarchive=False,
)
analysis.datas = [entry for entry in analysis.datas if PARTS["kept_data"](entry[0])]
# Windows' own C runtime stays Windows' (launcher_parts.kept_binary).
analysis.binaries = [entry for entry in analysis.binaries if PARTS["kept_binary"](entry[0])]
icon = os.path.join(BUILD, "openDMT3.ico")
# The window carries the archive of every Python module the launcher runs (5 MB), as PyInstaller makes it.
window = EXE(PYZ(analysis.pure), analysis.scripts, [], exclude_binaries=True, name="openDMT3", console=False, icon=icon,
             version=os.path.join(BUILD, "version.txt"))
# The console program reads that same archive inside openDMT3.exe beside it, instead of a copy of its own (the copy was
# 5.25 MB of every installer and update): its own archive is empty, and a runtime hook of its own (console_modules.py,
# run first of all the hooks, right after PyInstaller's bootstrap) turns its imports to openDMT3.exe's archive, at the
# place this build writes in openDMT3-modules.txt (from PyInstaller's own reader of the program just made; the folder
# keeps the program as made).
window_archive = CArchiveReader(window.name)
pyz_entry = next(entry for entry in window_archive.toc.values() if entry[-1] == "z")
modules_at = os.path.join(os.path.dirname(window.name), "openDMT3-modules.txt")
with open(modules_at, "w", encoding="ascii") as f:
    f.write("openDMT3.exe?%d\n" % (window_archive._start_offset + pyz_entry[0]))
# The hook first among the scripts: PyInstaller's bootstrap (which sets up the imports) comes with the archive, ahead of
# every script, and PyInstaller's own runtime hooks after it import modules of the archive.
console_scripts = [("pyi_rth_opendmt3_modules", os.path.join(ROOT, "packaging", "windows", "console_modules.py"),
                    "PYSOURCE")] + analysis.scripts
console = EXE(PYZ([], name=os.path.join(os.path.dirname(window.name), "PYZ-console.pyz")), console_scripts, [],
              exclude_binaries=True, name="openDMT3-cmd", console=True, icon=icon,
              version=os.path.join(BUILD, "version.txt"))
COLLECT(window, console, analysis.binaries, analysis.datas + [("openDMT3-modules.txt", modules_at, "DATA")],
        name="openDMT3")
