# Licence texts the build machine does not carry

`packaging/windows/notices.py` puts the licence text of every part the installed launcher carries into its
`licenses` folder, with `NOTICES.txt` saying which is whose. It takes them from the build itself: the Windows Python's
own `LICENSE.txt` (the PSF License, with bzip2's and Tcl/Tk's terms and Microsoft's for its C runtime) and Tk's
`license.terms`, each Python package's licence files as its metadata names them, and openDMT3's own (its `LICENSE`,
the fonts', 7-Zip's and the card reader library's notices). The libraries inside Python's modules and Velopack's
Python package come without their texts, so these are kept here, unchanged from where they were taken:

| File | What it covers | From |
|---|---|---|
| `OpenSSL-LICENSE.txt` | OpenSSL 3 (Apache License 2.0), in Python's `ssl` and `hashlib` | python-build-standalone 20261026, the release of the Windows Python the build uses: its full archive's `python/licenses/LICENSE.openssl-3.txt` |
| `libffi-LICENSE.txt` | libffi (MIT), in Python's `ctypes` | the same, `LICENSE.libffi.txt` |
| `zlib-LICENSE.txt` | zlib (zlib License), in Python's `zlib` and in Tk | the same, `LICENSE.zlib.txt` |
| `Expat-LICENSE.txt` | Expat (MIT), in Python's XML readers | the same, `LICENSE.expat.txt` |
| `mpdecimal-LICENSE.txt` | mpdecimal (BSD 2-Clause), in Python's `decimal` | the same, `LICENSE.mpdecimal.txt` |
| `SQLite-LICENSE.txt` | SQLite (public domain), in Python's `sqlite3` | the same, `LICENSE.sqlite.txt` |
| `liblzma-LICENSE.txt` | XZ Utils' liblzma (BSD Zero Clause), in Python's `lzma` | the same, `LICENSE.liblzma.txt` |
| `Velopack-LICENSE.txt` | Velopack (MIT): the installer's setup, `Update.exe` and the launcher's updates | Velopack's `LICENSE` at the commit its 1.2.161 release names |

When the build moves to another Python or Velopack release, these are taken again from that release.
