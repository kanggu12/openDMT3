# PyInstaller recipe for openDMT3-win-Setup.exe: one file holding the installer's dialogs (opendmt3/client/installer.py)
# and Velopack's own setup, which it runs without a window. Run by packaging/windows/build.sh inside the Wine build
# container, from the repository root, after vpk has made Velopack's setup.
import os
import runpy

ROOT = os.path.abspath(".")
# What the launcher leaves out of its folder (openDMT3.spec) the installer leaves out of its one file too: Pillow's
# AVIF and WebP codecs and colour management (4.3 MB of the installer was the AVIF codec alone), Tcl's time zones,
# message catalogs and other systems' character sets.
LAUNCHER = runpy.run_path(os.path.join(ROOT, "packaging", "windows", "launcher_parts.py"))
BUILD = os.environ.get("OPENDMT3_BUILD_DIR", os.path.join(ROOT, "build", "windows"))
FONTS = os.path.join(ROOT, "opendmt3", "client", "assets", "fonts")
INSIDE = os.path.join("opendmt3", "client", "assets", "fonts")

analysis = Analysis(
    [os.path.join(ROOT, "packaging", "windows", "setup_entry.py")],
    pathex=[ROOT],
    # Velopack's setup (installer.py finds it next to itself) and the fonts the dialogs use, with their licences.
    datas=[(os.environ["OPENDMT3_VELOPACK_SETUP"], ".")] + [
        (os.path.join(FONTS, name), INSIDE) for name in (
            "DMT3Wide-Regular.ttf", "Pretendard-Regular.ttf", "Pretendard-SemiBold.ttf", "Pretendard-Bold.ttf",
            "Saira-OFL.txt", "Pretendard-OFL.txt", "README.md")],
    hiddenimports=["PIL._tkinter_finder"],
    # The installer needs none of the launcher's game, server or update code.
    excludes=LAUNCHER["EXCLUDES"] + ["velopack", "sqlite3", "asyncio", "email", "http", "xml", "starlette", "jinja2",
                                     "uvicorn"],
    noarchive=False,
)
analysis.datas = [entry for entry in analysis.datas if LAUNCHER["kept_data"](entry[0])]
# Windows' own C runtime stays Windows' (launcher_parts.kept_binary).
analysis.binaries = [entry for entry in analysis.binaries if LAUNCHER["kept_binary"](entry[0])]
pyz = PYZ(analysis.pure)
# The picture shown while the one file unpacks itself, before Python starts (installer.py closes it).
splash = Splash(os.path.join(BUILD, "setup-splash.png"), binaries=analysis.binaries, datas=analysis.datas,
                text_pos=None, always_on_top=False)
EXE(pyz, analysis.scripts, splash, splash.binaries, analysis.binaries, analysis.datas, [], name="openDMT3-win-Setup",
    console=False, icon=os.path.join(BUILD, "openDMT3.ico"), version=os.path.join(BUILD, "setup-version.txt"),
    upx=False)
