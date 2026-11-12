# Contributing to openDMT3

Bug reports, fixes, translations and new features are all welcome. This guide shows where the code is, how to run it
and its tests on your PC, and how a change goes in. **You do not need the game's files for most of it:** the tests
make stand-in files of their own.

| You know | A good place to start |
| :--- | :--- |
| The game, or running a server | [Report what did not work](https://github.com/kanggu12/openDMT3/issues/new/choose), improve a [guide](docs/README.md) |
| Another language | The launcher's and the site's words: [Changing the words](#changing-the-words) |
| Python and Tk | The launcher, `opendmt3/client/` |
| Python, HTML and CSS | The site, the admin pages and the API, `opendmt3/server/web/`: [Adding a page or an API call](#adding-a-page-or-an-api-call) |
| Network protocols | The game server, `opendmt3/server/`: [Changing the game server](#changing-the-game-server), and [what the game says](docs/protocol.md) |
| C and Direct3D 9 | The card reader library and the in-game layer, `native/cardreader/` |
| Docker | The server's image and the setup wizard, `packaging/docker/`, `compose.yaml`, `dmt3` |

## Before you start

- **No game files, anywhere.** Do not attach or commit the game's client, its files, songs, pictures or tables, and
  do not link to where they can be had. Logs and screenshots of openDMT3's own launcher and site are fine.
- **Security problems** go to [SECURITY.md](.github/SECURITY.md), not to an issue.
- Be kind: see the [code of conduct](.github/CODE_OF_CONDUCT.md).
- Commit messages, comments and the guides are in English. The launcher and the site speak English and Korean.

## Where the code is

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/architecture-dark.svg">
    <img alt="The map of the code. On the player's Windows PC the launcher (opendmt3/client: its pages, actions.py, hosting.py, remote.py, updates.py) only reads the client data, makes openDMT3's own folder at PLAY (core/cabinet/steps.py) and starts the game, which runs with the card reader library and in-game layer of native/cardreader. The launcher reaches a server's site and API (opendmt3/server/web, port 4730) over HTTP, and the game reaches the game server (connection.py, messages.py, port 4725) over the game's own protocol; both use the services (services/) and one SQLite file (db/). Both parts share opendmt3/core" src="docs/images/architecture-light.svg" width="100%">
  </picture>
</p>

One package, `opendmt3`, in three parts ([docs/architecture.md](docs/architecture.md) has the whole map):

| Path | What it is | Start reading at | Its tests |
| :--- | :--- | :--- | :--- |
| `opendmt3/core/` | What the other two share: the client data and its formats, the steps PLAY makes, the originals an earlier version kept, the error words, signing, and `python -m opendmt3 check, setup, restore` | `game.py`, then `cabinet/steps.py` | `tests/core/` |
| `opendmt3/server/` | The game server, its services, its database (`db/`) and its site, admin pages and API (`web/`); `python -m opendmt3.server` | `__main__.py`, then `server.py` for the game and `web/app.py` for the site | `tests/server/` |
| `opendmt3/client/` | The Windows launcher (its window, its pages, its jobs on the command line) and the installer's dialogs | `main.py`, then `app.py` and `actions.py` | `tests/client/` |
| `native/cardreader/` | The card reader library with the in-game layer, 32-bit C built with MinGW | `crt_r1.c`, then `layer.c` | `test_native.c`, run by `test.sh` |
| `native/openal/` | DSOAL and OpenAL Soft for the Sound page's mixer, built for 32-bit Windows from their pinned source archives, with their notices | `build.sh` | `tests/test_launcher_licences.py`, `tests/core/test_card_reader_notices.py` |
| `dmt3`, `packaging/docker/` | `./dmt3`: the server with Docker Compose, the build and the tests; the server's image and the setup wizard | `dmt3` (`main`), `wizard.py` | `tests/test_front_door.py`, `tests/test_setup_wizard.py` |
| `packaging/windows/`, `packaging/release.sh` | The launcher's and the installer's build on Linux, and a release | `build.sh` | `tests/test_windows_build.py`, `tests/test_launcher_licences.py` |
| `tests/e2e/` | The suites beyond unit tests: the launcher's screens, the site's, the real client under Wine, the load test, an upgrade | [docs/testing.md](docs/testing.md) | |

The version is written once, as `__version__` in `opendmt3/__init__.py`; the server, the launcher, the installer and
the Windows build all read it from there.

### The parts

The parts depend in one direction only:

- `opendmt3.core` imports nothing from `opendmt3.server` or `opendmt3.client`.
- `opendmt3.server` imports nothing from `opendmt3.client`.
- `opendmt3.client` may import both: the launcher runs a server inside itself for playing on one PC.

`tests/test_architecture.py` reads the imports of every module, those inside functions too, and fails naming the file
and line of any import that runs the other way. Code that two parts need belongs in `core`.

## Your first change

```sh
git clone https://github.com/kanggu12/openDMT3.git && cd openDMT3
python3 -m venv .venv
.venv/bin/pip install starlette==0.47.3 jinja2==3.1.6 uvicorn==0.35.0 python-multipart==0.0.20 pillow==11.3.0 \
  httpx==0.28.1 pyflakes==3.2.0
./dmt3 test --python .venv/bin/python             # the unit tests, the boundary test and pyflakes
.venv/bin/python -m opendmt3.server --data data   # the game server and the site, with no game files
```

On Debian and Ubuntu, `python3 -m venv` needs the `python3-venv` package. Open the site at the address the server
prints (`site on http://127.0.0.1:4730/`): while the server has no account, that page makes the first one, yours as
the owner. Change a word in `opendmt3/server/web/strings.py`, in both languages, start the server again, and the page
shows it. Before you send it, run `./dmt3 test --python .venv/bin/python` again, and
`tests/e2e/web/run.sh OUT_DIR` (every page in both languages at a desktop and a phone width, in Docker: 4 minutes).

## Run it on your PC

The front door, `./dmt3`, is plain Python 3 with nothing to install. `./dmt3` alone lists its commands.

```sh
git clone https://github.com/kanggu12/openDMT3.git && cd openDMT3
./dmt3 test                                   # the unit tests (on several processes), the boundary test and pyflakes
./dmt3 test --python /path/to/venv/bin/python # the same with a Python that has the site's libraries and pyflakes
./dmt3 setup                                  # a server in Docker, by its wizard
```

- **A server from source**, without Docker: the lines of [docs/server.md](docs/server.md#with-python). With no game
  files, leave out `--catalog` (songs then show as numbers) and `--host 0.0.0.0` (the site and the game's port then
  stay on this PC), as in [Your first change](#your-first-change).
- **The launcher from source**: `python -m opendmt3.client`, on a Python with Tk and Pillow (and the site's
  libraries, for playing on this PC). With a flag it does that job and opens no window
  (`python -m opendmt3.client --help` lists them); the game itself runs on Windows only.
- **The unit tests on Windows**: `python tests/e2e/windows/unit_tests.py` from the repository's top, on a Windows
  Python with the libraries of CI's `windows` job, as that job runs them.
- **The launcher's screens without a window on your screen**: `tests/e2e/ui/run.sh OUT_DIR` shoots every page on a
  virtual screen in a container, on made-up folders.
- **The Windows build**: `./dmt3 build OUT_DIR` makes the launcher and its installer on Linux, in containers. A build
  looks for updates where `OPENDMT3_UPDATE_SOURCE` points when it is made: a GitHub repository's URL (its releases),
  or a folder, local or on a web server, holding the update packages the build leaves in `OUT_DIR/releases`. Without
  it, the launcher it makes looks for none.

## Run the tests

You do not have to run them all: pick the line for what you changed, and CI runs the rest on your pull request.

| You changed | Run | Needs |
| :--- | :--- | :--- |
| anything | `./dmt3 test`: the unit tests, the boundary test and pyflakes, and with them the guides' own checks (every test case points at a check that exists, every link and picture is there, the words keep to the term table) | Python 3.10 or newer; for the site's tests its libraries and `httpx`, and `pyflakes` for the lint, in the Python that runs `dmt3` or the one `--python PATH` names (without the libraries those tests are skipped and say so; without pyflakes the run stops and says how to get it); for the archives' tests 7-Zip (`OPENDMT3_7ZIP` naming it, or `7zz`, `7z` or `7za` on the PATH; without it they are skipped, counted in the unit tests' `skipped=`) |
| `opendmt3/client/`: a page, a dialog, a word | `tests/e2e/ui/run.sh OUT_DIR`: every page, in both languages at three sizes | Docker |
| `opendmt3/server/web/`: a page, a form | `tests/e2e/web/run.sh OUT_DIR`: every page, in both languages at a desktop and a phone width | Docker |
| `native/cardreader/` | `native/cardreader/test.sh` | Docker |
| the database, or what is kept in the data folder | `tests/e2e/upgrade/run.sh vX.Y.Z OUT_DIR`, with the last release's tag | Docker |
| the game server or the site under load | `python tests/e2e/load/cabinets.py` (31 minutes) | The site's libraries and `httpx` |
| `packaging/windows/` | `./dmt3 build OUT_DIR` | Docker |
| `packaging/docker/`, `compose.yaml`, `dmt3` | `./dmt3 setup`, then `./dmt3 status` | Docker |

The scripts are bash and use GNU coreutils (`realpath -m`, `sha256sum`). They build their Docker images the first
time; the Wine tests (`tests/e2e/windows/`) run in the Wine image that `./dmt3 build` and `native/cardreader/test.sh`
make.

CI runs the unit tests, the native tests, both sets of screens, the server's image and the launcher's build on
Windows on every pull request, without the game's files ([docs/testing.md](docs/testing.md#ci)). What needs the game
runs on a maintainer's machine before a release: the real client under Wine, from the installer to a whole song
(`tests/e2e/windows/`). A change to the card reader library, the in-game layer or what PLAY makes passes CI without
ever meeting the real client, so say in the pull request that it needs that run. [docs/testing.md](docs/testing.md)
has the whole picture, and [docs/test-cases.md](docs/test-cases.md) every case with the check that covers it.

## Changing the game server

A message from the game reaches the function `opendmt3/server/server.py` registers for its header (`@handles(0x60)`,
a card login). To answer a new one:

1. A function in `messages.py` that builds the answer: `blank(header)` gives a message of the size the client
   registered for it, and the function fills in its fields, with values checked on the client's screen, as
   [docs/protocol.md](docs/protocol.md)'s are. `TO_CLIENT` and `TO_SERVER` there already hold every header the client
   takes and sends, with its size ([what the client registers](docs/protocol.md#everything-the-client-registers)).
2. A function in `server.py` under `@handles(header)`, taking `(server, connection, message)`; an `async` one when it
   waits for the database (it then runs after the link's earlier messages, in their order).
3. A test in `tests/server/test_server.py` through `StandInClient` (the client's side of the link, as the real client
   does it), a row in docs/test-cases.md, and the message's fields in docs/protocol.md.

`@handles` refuses a second handler for one header, and a header the client never sends, when `server.py` loads. A
header without a handler is named in the server's log once per connection, and with `--verbose` logged with its first
bytes: a session with the real client shows what to build next.

## Changing the words

The words a person reads are in these tables, in English and Korean side by side:

| Words | Where | Checked by |
| :--- | :--- | :--- |
| The launcher's | `TEXT` in `opendmt3/client/i18n.py` | `tests/e2e/ui/run.sh` (no text cut off, in both languages) |
| The site's and the admin pages' | `TEXT` in `opendmt3/server/web/strings.py` | `tests/server/test_site_features.py` (Korean with the same gaps), `tests/e2e/web/run.sh` |
| Errors, shared by both | `TEXT` in `opendmt3/core/errors.py` | `tests/core/test_errors.py` (every word used, Korean with the same gaps) |
| What a path on the server PC is | `WORDS` in `opendmt3/server/services/sources.py` | `tests/server/test_sources.py` |
| In the game: the menu, the question, the toast | `native/cardreader/logic.c` | `native/cardreader/test.sh` |
| The setup wizard and the command lines (English only) | `packaging/docker/wizard.py`, `dmt3`, `opendmt3/client/cli.py`, `opendmt3/server/__main__.py` | `tests/test_setup_wizard.py`, `tests/test_front_door.py` |

A new text goes into both languages of its table. `tests/test_words.py` keeps the project's terms in all of them and
in the guides: what a player brings is the client data (the PC client and the game's files, in a folder or in an
archive), and each thing is named by what it is (the PC client, the song list, jackets), never by a file name of the
game's or by where it came from.

Two texts live beside their code, in English and Korean: the note `README-openDMT3.txt` that removing openDMT3 leaves
in the client data's `backup\` folder when a file there could not be put back (`WORDS` in
`opendmt3/client/leaving.py`), and the console program's two lines when `openDMT3.exe` is missing or changed
(`packaging/windows/console_modules.py`: the modules that hold the tables are what is missing then).

## Adding a page or an API call

Everything the site shows and does can be done through the API too ([docs/api.md](docs/api.md)). A page:

1. Its handler and route in `opendmt3/server/web/pages.py` (the site) or `admin.py` (the admin pages, under
   `/admin/`); its template in `templates/`, extending `base.html`; its link, where it needs one, in the menu of
   `base.html` or the admin pages' tabs (`_admin_tabs.html`); its words in both languages of `strings.py`.
2. Its twin in the API: the route in `api.py`, its row in the table of calls (`calls.py`, which the OpenAPI document
   is made from) and in docs/api.md. `tests/server/test_api.py` fails until the three have the same calls, with the
   same who, parameters and errors.
3. The page in the list in `tests/e2e/web/shoot.js`, and `EXPECTED_PAGES` in `tests/e2e/web/run.sh` four higher (two
   widths, two languages), so its layout is checked; the same in `empty.js` with `EXPECTED_EMPTY_PAGES`, which opens
   every page on a server with nothing in it.
4. A test in `tests/server/`, and a row in docs/test-cases.md.

An API call of its own is steps 2 and 4.

## Making a change

1. Put the code in the part it belongs to, and its tests in that part's folder under `tests/`.
2. A case worth naming goes into [docs/test-cases.md](docs/test-cases.md) as `` `tests/part/test_file.py#test_name` ``
   (the path from the repository's top, then a test's name or a line the check prints), under an ID of its own;
   `tests/test_docs.py` fails when the file or the text is gone, or an ID is used twice.
3. Say what changed in the guide it belongs to, and note it under `## [Unreleased]` in [CHANGELOG.md](CHANGELOG.md),
   in the section it fits (Added, Changed, Fixed, Removed, Security: what closes a way in goes under Security, never
   under Fixed), in a line or two.
4. `./dmt3 test` passes. CI (`.github/workflows/ci.yml`) runs the same on Python 3.10 and 3.12, and the native tests,
   the launcher's and the site's screens, the server's image and the launcher on Windows, on your pull request
   ([docs/testing.md](docs/testing.md#ci)).

## Style

- Comments in English, on most lines, saying why the line is there.
- Text on the screens: short and plain, one fact and what to do about it, in the game's own words where it has them.
- `dmt3` and the setup wizard use Python's standard library only; the server runs on Python 3.10 and newer.
- A new window, question or error is drawn in the launcher's or the site's own design, never the system's.
- Nothing secret in logs or error messages: no passwords, card numbers or tokens.

## Commits and pull requests

- One change per commit or pull request, with its tests and the guides it changes.
- The first line of a commit message says what changed; the lines below say why, when that is not plain.
- CI has to pass. A maintainer runs the Wine tests on a copy of the game before a release.

## Versions and releases

Versions follow [Semantic Versioning](https://semver.org/): a release with a new feature raises the minor number
(0.1.0 to 0.2.0), one of fixes, changes and smaller additions raises the patch number (0.1.0 to 0.1.1). Each
release's section of [CHANGELOG.md](CHANGELOG.md) ([Keep a Changelog](https://keepachangelog.com/en/1.1.0/)) is its
release notes.

A release is built, signed and published on the release machine, the one that holds the project's update-signing
key, with Docker and the GitHub CLI (`gh`) signed in to an account that publishes the repository's releases: launchers
put in only update packages signed with that key, so the key never leaves that machine and no workflow builds a
release. A release, by a maintainer:

1. Moves the `[Unreleased]` notes under `## [X.Y.Z] - YYYY-MM-DD` in CHANGELOG.md, adds its link at the foot
   (`[X.Y.Z]: https://github.com/kanggu12/openDMT3/compare/vA.B.C...vX.Y.Z` from the release before, and
   `[Unreleased]` compared from `vX.Y.Z`), and sets `__version__` in `opendmt3/__init__.py` to `X.Y.Z`.
   `python3 .github/release_notes.py vX.Y.Z` prints the notes, its `### Security` part included; with no section for
   the version, or a tag the code does not carry, there is no release.
2. Runs the checks of [docs/testing.md](docs/testing.md#before-a-release): `./dmt3 test`, the native tests, the
   launcher's and the site's screens, the build, the Wine tests with that build, the upgrade from the last release,
   the load test, and the installer on a real Windows PC.
   `OPENDMT3_SIGNING_KEY=<the key's file> packaging/release.sh vX.Y.Z OUT_DIR` rehearses the release: the version
   check, the build with the key and the signatures checked, and the release it would make. The key is named in the
   environment and nowhere else: no path is tried when it is not set.
3. Commits, tags the commit (`git tag -a vX.Y.Z -m "Release X.Y.Z"`) and pushes both. The tag runs
   `.github/workflows/release.yml`: CI and the version check again on the tag's commit; no release is built or
   published there.
4. Once `release.yml` has passed on the tag, publishes with the same command and `--publish` at its end: the same
   checks and build from the tagged commit, then the GitHub release, titled with the tag itself (`vX.Y.Z`), the
   changelog's section as its notes.

What a release publishes:

| What | Files |
| :--- | :--- |
| The installer | `openDMT3-win-Setup.exe` |
| The update packages, each with the project's signature | `openDMT3-X.Y.Z-full.nupkg` and its `.sig`; with `OPENDMT3_PREVIOUS_RELEASE` naming the last release's build (its `OUT_DIR/build/releases`), a delta package from that release too, so a launcher of that version downloads only what changed (`packaging/windows/previous.py`) |
| The feed installed launchers read | `releases.win.json`, `RELEASES` |
| The source of the two LGPL libraries the launcher brings for the Sound page's OpenAL Soft mixer | `openal-soft-1.25.2.tar.gz` and `dsoal-<commit>.tar.gz`, the archives `native/openal/build.sh` builds them from (its `SHA256SUMS` names them) |

The launcher shows its version beside its logo and on its **Launcher** page, and a server at the foot of every page
of its site.
