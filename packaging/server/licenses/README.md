# Licence texts the server's packages for Linux and macOS take from here

`packaging/server/bundle.py` puts the licence text of every part a server package for Linux or macOS carries into its
`licenses` folder, with `NOTICES.txt` saying which is whose: Python's own `LICENSE.txt` from the package's Python, each
library's licence files as its metadata names them, 7-Zip's `License.txt`, the fonts' and openDMT3's own. The
libraries inside the Python's modules come without their texts: most are the ones the launcher's build keeps in
`packaging/windows/licenses` (OpenSSL, SQLite, libffi, Expat, mpdecimal, liblzma, zlib: the same texts), and the rest,
which only these Pythons carry, are kept here, unchanged from where they were taken:

| File | What it covers | From |
|---|---|---|
| `bzip2-LICENSE.txt` | bzip2 (bzip2-1.0.6 License), in Python's `bz2` | python-build-standalone 20261026, the release of the packages' Python: its full archives' `python/licenses/LICENSE.bzip2.txt` (the same in all four) |
| `libuuid-LICENSE.txt` | util-linux's libuuid (BSD 3-Clause), in Python's `uuid` | the same, `LICENSE.libuuid.txt` |
| `zlib-ng-LICENSE.txt` | zlib-ng (zlib License), named for Python's `zlib` on Linux beside zlib's own | the same, `LICENSE.zlib-ng.txt` |
| `libedit-LICENSE.txt` | libedit (BSD 3-Clause), in Python's `readline` on Linux (macOS's is the system's) | the same, `LICENSE.libedit.txt` |
| `ncurses-LICENSE.txt` | ncurses (X11), in Python's `curses` and `readline` on Linux (macOS's is the system's) | the same, `LICENSE.ncurses.txt` |

Which library a target's Python carries is that release's `python/PYTHON.json` (each module's links, static or the
system's): on macOS, zlib, libedit and ncurses are the system's own, which the package does not carry. When the
packages move to another Python release, these and that list in `bundle.py` (`LIBRARIES`, each target's `libraries`)
are taken again from that release.
