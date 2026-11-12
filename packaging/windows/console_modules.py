"""openDMT3-cmd.exe's runtime hook (packaging/windows/openDMT3.spec): its Python modules are the ones in openDMT3.exe.

The two programs run the same code. The console program carries an empty archive of modules of its own, and this hook,
run first of the runtime hooks (right after PyInstaller's bootstrap has set up its imports, before PyInstaller's own
hooks import anything), points PyInstaller's importer at the archive inside openDMT3.exe beside it: one copy of the
modules in the folder, not two (5.25 MB of every installer and every update).

Where that archive sits inside openDMT3.exe is written by the build into openDMT3-modules.txt in the program's folder
("openDMT3.exe?<offset>", taken from the program as built with PyInstaller's own reader). The archive is opened the way
PyInstaller opens its own (its magic and Python's bytecode magic checked), so a program that is not the one built with
this one stops here with a plain error instead of running other code.
"""

import os
import sys

import pyimod01_archive
import pyimod02_importers
import pyimod03_ctypes


def _take_the_windows_modules():
    """Point the imports of this program at openDMT3.exe's archive of modules."""
    # Written by the build beside the programs' other files (sys._MEIPASS: the folder PyInstaller unpacks into).
    with open(os.path.join(sys._MEIPASS, "openDMT3-modules.txt"), encoding="ascii") as f:
        name, _, offset = f.read().strip().partition("?")
    # The program beside this one (both in the installed folder), at the archive's place in it.
    where = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), name)
    try:
        archive = pyimod01_archive.ZlibArchiveReader(where, int(offset), check_pymagic=True)
    except Exception as e:
        # openDMT3.exe gone or changed (an antivirus may have taken it): nothing of openDMT3 can run, not even its
        # Repair, and its words cannot be read either. What happened, then the installer's Repair, which brings it
        # back. No traceback: PyInstaller's own error is for a fault, and this is none.
        if os.path.isfile(where):
            # There, but not the program built with this one (another version's, or changed).
            what = "%s is not the openDMT3.exe made with openDMT3-cmd.exe (%s)." % (where, e)
        else:
            what = "openDMT3-cmd.exe needs openDMT3.exe beside it, and %s is not there." % where
        lines = [what + " Run openDMT3-win-Setup.exe again and choose Repair."]
        korean = "openDMT3.exe가 없거나 바뀌었습니다. openDMT3-win-Setup.exe를 다시 실행해 복구를 고르세요."
        try:
            # A console takes any letters; a file or a pipe takes its code page's, which may have no Hangul: then the
            # Korean line is left out rather than written as escapes.
            korean.encode(sys.stderr.encoding or "ascii")
            lines.append(korean)
        except (LookupError, UnicodeError):
            pass
        sys.stderr.write("\n".join(lines) + "\n")
        sys.stderr.flush()
        # Out at once with a failure: no other runtime hook, and no script, runs without the modules.
        os._exit(1)
    # PyInstaller's importer reads its archive and the tree of names in it from these two (pyimod02_importers): the
    # tree is made again from the new archive when next asked for.
    pyimod02_importers.pyz_archive = archive
    pyimod02_importers._pyz_tree = None
    # The finders made so far hold this program's own archive, which is empty: they go, and the next import makes new
    # ones that read openDMT3.exe's.
    for path, finder in list(sys.path_importer_cache.items()):
        if isinstance(finder, pyimod02_importers.PyiFrozenFinder):
            del sys.path_importer_cache[path]
    # The bootstrap found no ctypes in the empty archive, so it did not teach ctypes to find the libraries in the
    # program's folder: done now that ctypes can be imported.
    pyimod03_ctypes.install()


_take_the_windows_modules()
