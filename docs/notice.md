# License and notice

For everyone who plays with openDMT3, runs an openDMT3 server, or works on the code. It is not legal advice. The
launcher's **Launcher** page and the site's footers say what the project is and that the project acts on rights
holders' requests.

## The project

openDMT3 is an unofficial, non-commercial community project. It is not affiliated with or endorsed by NEOWIZ. DJMAX
and TECHNIKA are trademarks of NEOWIZ, and the game is NEOWIZ's copyrighted work.

openDMT3 is a launcher and a server. The repository and its releases contain none of the game's files: no game client,
songs, charts, images, videos or sounds. The launcher works only with client data its owner provides, with a client
that runs on a PC, and only reads it: what it needs to play it is made in a folder of openDMT3's own. A server reads
only the song list, which holds the jackets and the DJ cards too (no charts, music or videos), from its owner's own
client data, in a folder or in an archive, or from a song list openDMT3's own code made from that client data (the
launcher's **Save the song list...**); without it its pages show song numbers and no jackets
([The client data](client-data.md)).

What the repository does hold is openDMT3's own code and what it takes to work with those files: the names of the game's
files it reads, the shapes of the messages the game sends and of the replies it reads ([docs/protocol.md](protocol.md)),
the client builds it recognizes by their hashes, the short byte patterns PLAY changes in its copy of the PC client,
and a card reader library of its own that takes the cabinet's place (`native/cardreader`).

## For rights holders

This project respects the rights of NEOWIZ and other rights holders. If a rights holder asks, the repository will
promptly be made private or taken down, in whole or in the part concerned. No lawsuit or formal notice is needed: a
request in the repository's issues is enough, saying who is asking and what it concerns. The maintainer can act on
this repository's own contents; about a fork, another copy or a particular server, please contact whoever runs it.

## License

openDMT3's own code and documentation are under the MIT License: see [LICENSE](../LICENSE).

The license does not cover the game or its files. Those are not in the repository and are not licensed by it.

Nor does it cover third-party parts, which keep their own licenses:

| Part | Where | License |
| :--- | :--- | :--- |
| The fonts: DMT3 Wide (a cut of Saira) and Pretendard, with DMT3 Text (a cut of Pretendard) for the site | The launcher, the site, and beside the card reader library wherever the launcher puts it, each with its license text | SIL Open Font License 1.1 |
| The picture's passes in the card reader library: AMD FidelityFX Super Resolution 1, NVIDIA Image Scaling and SMAA (with its area and search textures), and a pass written from FXAA 3.11 | `native/cardreader/third_party`, built into the card reader library | FSR 1, NIS and SMAA: MIT License (their `LICENSE.txt`). FXAA 3.11: NVIDIA's notice (`third_party/fxaa/NOTICE.txt`). The library's build writes these texts, with its compiler runtime's below, into `card-reader-NOTICES.txt`, which goes beside the library wherever the launcher puts it and is in the installed program's `licenses/` |
| The card reader library's compiler runtime: the mingw-w64 C runtime and GCC's (libgcc), linked in | Built by `native/cardreader/build.sh` with Debian 12's MinGW-w64 | The mingw-w64 runtime: ZPL 2.1 and the other licenses its Debian copyright file lists, which `card-reader-NOTICES.txt` carries in full with the package's version. libgcc: GPL 3 with the GCC Runtime Library Exception, which asks nothing of what is built with it |
| The launcher: Python 3.12 (python-build-standalone's Windows build) with the Microsoft C runtime it ships and the libraries in its modules (OpenSSL, SQLite, libffi, zlib, Expat, mpdecimal, liblzma, bzip2, Tcl/Tk), Pillow, Velopack, the web libraries the launcher runs the site with on the player's PC (Starlette, Jinja2, Uvicorn, python-multipart and what they bring: AnyIO, idna, typing_extensions, MarkupSafe, Click, h11), packaging, and PyInstaller's bootloader | Built by `packaging/windows/build.sh` into the installer and the program it installs | Python: PSF License, with bzip2's and Tcl/Tk's terms and Microsoft's for its C runtime. OpenSSL: Apache License 2.0. SQLite: public domain. libffi, Expat: MIT. zlib: zlib License. mpdecimal: BSD 2-Clause. liblzma: 0BSD. Pillow: MIT-CMU, with the licenses of the image libraries in it. Velopack: MIT. The web libraries: BSD 3-Clause, MIT, PSF and Apache License 2.0. packaging: Apache License 2.0 or BSD 2-Clause. PyInstaller's bootloader: GPL 2 with the Bootloader Exception, which allows it in a program under any license. The installed program carries every text in `licenses/`, with `NOTICES.txt` saying which is whose: the build gathers them from what it holds (`packaging/windows/notices.py`: the packages' metadata, Python's own files, and `packaging/windows/licenses` for the texts the build's Python lacks), and stops when a part has none |
| 7-Zip 25.01 for Windows (`7z.exe`, `7z.dll`) | Taken out of the official release by `packaging/windows/sevenzip.sh` and installed beside the launcher in `opendmt3/client/bin/7-Zip`: the launcher lists, tests and unpacks the game's archives with it | GNU LGPL with the unRAR license restriction for its RAR code and BSD licenses for some code, its `License.txt` beside it and in `licenses/` |
| The server's container image | Built by `packaging/docker/Dockerfile` on the official `python:3.12-slim-bookworm` image (Debian 12), with Starlette, Jinja2, Uvicorn, python-multipart, Pillow and what they bring, and the official 7-Zip (`7zz`, which opens an archive holding the game) | Each its own: PSF License, BSD, MIT, MIT-CMU and Apache License 2.0; 7-Zip: GNU LGPL with the unRAR license restriction for its RAR code and BSD licenses for some code. The image keeps each text with its part: Python's `LICENSE.txt`, each Python package's in its `.dist-info` folder, 7-Zip's `License.txt` under `/usr/local/share/doc/7-zip`, the system packages' copyright files under `/usr/share/doc`, and openDMT3's `LICENSE` beside the package; `packaging/docker/check_licences.py` checks that each is there |

Those terms apply to whoever hands the launcher or the server's image on. To make that simple, the installed launcher
carries the full texts in its `licenses` folder, and every server lists its parts with their licenses at `/licenses`,
linked from the site's footer, with openDMT3's own license and the fonts' in full.

## If you play

- openDMT3 works with client data you provide; it does not come with any. Please use files you have the right to
  use, within the rules that apply where you are.
- For questions about a server, please ask the person who runs it.

## If you run a server

- A server reads only the song list (with its jackets and the DJ cards) from your own client data, in a folder or in
  an archive, or from a song list openDMT3 made from it, and keeps it in its `data` folder.
- Players get the launcher from your server's **Download** page, with the accounts you make on the admin pages.
- If a rights holder asks you to take something down, please do so.

## Developers and contributors

- The software is provided "as is", without warranty of any kind, as the license states. To the fullest extent the
  law allows, the authors and contributors are not liable for any claim, damages or other liability arising from it or
  from how anyone uses it.
- Authors and contributors do not supply game files, do not tell anyone where to get them, and do not grant any right
  to use them.
- Each server is run independently by its own owner. This project is not a service and does not run servers on
  anyone's behalf.
- Please use, run and change this software in line with copyright law, the game's terms and the laws where you live,
  and only with game files you have the right to use.
- Contributions come in under the same license.
