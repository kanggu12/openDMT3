# Architecture

openDMT3 is one Python package, `opendmt3`, in three parts: what every part shares (`core`), the server (`server`,
run in Docker or with Python) and the Windows client (`client`: the launcher and its installer). The command line
for the client data (`python -m opendmt3 check, setup, restore`) is part of `core`.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="images/system-dark.svg">
    <img alt="How openDMT3 fits together. On the player's Windows PC, the client data (the PC client and the game's files) is only read: the launcher finds it, and the game plays from it in place. The launcher sets the picture and the sound, puts the card in, and PLAY starts the game with openDMT3's card reader library and overlay inside it. Other players' PCs are the same. The launcher talks to a server over HTTP on port 4730: signing in, the card at each PLAY, records; the game talks to it over the game's own protocol on port 4725: its card login and its results. Browsers open the server's site (players: rankings, songs, DJ pages; the owner: the admin pages) and programs its API with a named token, on port 4730 too. The server is one process, inside the launcher, with Docker or with Python: the game server, the site and its API, and one SQLite file in its data folder, which holds the accounts, the plays and the song list read once from the client data" src="images/system-light.svg" width="100%">
  </picture>
</p>

## The package

```
opendmt3/
  __init__.py        the version, the one place it is written
  __main__.py        python -m opendmt3: the client data's command line (core/cli.py)
  core/              what the server and the client share
  server/            the game server, its services, its database and its site
  client/            the launcher and the installer, for Windows
```

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="images/architecture-dark.svg">
    <img alt="The map of the code. On the player's Windows PC the launcher (Tk, opendmt3/client: its pages, actions.py, hosting.py, remote.py, updates.py) only reads the client data, makes openDMT3's own folder from it at PLAY (core/cabinet/steps.py: the client copy, the card reader library with the in-game overlay, the settings, the card), and starts the game from there, with the card reader library of native/cardreader in it. Playing on this PC, the launcher runs the server inside itself; on another server, it signs in over the HTTP API for the player's card and records. The game logs in by card and sends its results over the game's own protocol. The server (opendmt3/server, with Docker or Python) is one process: the site and its API on port 4730 (Starlette, web/), the game server on port 4725 (asyncio, connection.py and messages.py), their services (services/) and one SQLite file (db/). Both parts share opendmt3/core" src="images/architecture-light.svg" width="100%">
  </picture>
</p>

The parts depend in one direction: `client` may use `server` and `core`, `server` uses `core`, and `core` uses neither.
`tests/test_architecture.py` reads every module's imports (those inside functions too) and fails when one runs the
other way.

| Part | What it is |
|---|---|
| `core/formats/` | The game's own file formats: the files that hold the others, the settings file, the operator settings, the song lists |
| `core/cabinet/` | What PLAY makes in openDMT3's own folder from the client data it only reads, as steps that each check their part and make it when asked; the display fix of the client; starting the game (through a short path when its folder's cannot be given to it) and following it |
| `core/game.py`, `core/backup.py`, `core/formats/pe.py` | The client data (what its client is, where the files are, each family of the game's files read as the client reads it: the newest of its base and numbered patches that has a file); the originals an earlier openDMT3 kept in it; the libraries a program imports |
| `core/errors.py` | Every error a person reads, with its words in English and Korean |
| `core/signing.py`, `core/preset.py`, `core/safety.py` | The update packages' signature; the server a build is made for; the guard that keeps windows shut under the tests |
| `core/cli.py` | `python -m opendmt3 check, setup, restore` on the client data |
| `server/` (its own modules) | The game server: the connection (handshake, cipher, keep-alive), every message's size, the handlers, and `__main__.py`, which runs it with the site |
| `server/services/` | What the server does without knowing about messages or HTTP: accounts, records, activity, the song list (`catalog.py`, `cards.py`; any form it comes in, `sources.py`; saved into one file and taken in, `songlist.py`; its pictures in one form, `pictures.py`), backups, the chat webhook, a DJ's profile |
| `server/web/` | The site, the admin pages and the API, as one ASGI app beside the game server |
| `server/db/` | One SQLite file, its tables made and upgraded in numbered steps |
| `client/` | The launcher's window and pages (`client/pages/`), and the same jobs without a window (`actions.py`) for the command line |
| `client/installer.py` | The installer's dialogs around Velopack's setup |
| `native/` (repository) | The game's `CRT_R1.dll`, built from C: the card reader and the in-game layer; and DSOAL and OpenAL Soft for the Sound page's mixer, built from their pinned sources (`native/openal`) |

The site serves the wide face from the launcher's fonts (`client/assets/fonts/`), which it reads as files; no module of
the server imports the client.

## The repository

| Path | What it is |
|---|---|
| `dmt3` | The front door: the server with Docker Compose (`setup`, `catalog`, `up`, `down`, `restart`, `status`, `logs`, `backup`, `backups`, `restore`, `add-player`, `check`, `doctor`), the Windows build (`build`) and the checks (`test`). Plain Python, nothing to install |
| `compose.yaml` | The server with Docker Compose |
| `opendmt3/` | The package, above |
| `tests/core/`, `tests/server/`, `tests/client/` | Each part's unit tests |
| `tests/e2e/` | The end-to-end suites: `windows/` (the real client under Wine), `ui/` (the launcher's screens), `web/` (the site's screens), `load/`, `upgrade/` |
| `packaging/` | The server's image (`docker/`), the Windows build (`windows/`), the Wine image (`wine/`), the fonts' recipes (`fonts/`), and a release (`release.sh`) |
| `native/` | The game's `CRT_R1.dll` (the card reader and the in-game layer) and its native tests (`test.sh`) |
| `.github/` | CI (`workflows/ci.yml`), a release's checks (`workflows/release.yml`, `release_notes.py`), the issue and pull request forms, the security policy and the code of conduct |

## The game's files

The game keeps its files inside larger files, in families: a base and numbered patches. `core/formats/pak.py` reads
them as the client does. Each one is a header (a seed, then the first entry's offset, the version, the entry count and
a check byte, hidden by the seed's key stream and an XOR chain), then one 0x98-byte descriptor per entry, each
followed by the entry's data in LZO1X chunks. A descriptor holds the entry's seed, the path (hidden by that seed's
key stream) and the two sizes; every fourth byte of it is also XORed with a 256-byte table and with one of 125 key
bytes, picked by a 64-bit field of the descriptor. A family's base and its patches share the key bytes. The first
1,000,000 bytes of each entry are hidden by the entry seed's key stream too.

Nothing of the game is kept in openDMT3:

- **The table** is read from the player's own client, found by its SHA-256 in the client's read-only data.
- **Each key byte** is recovered from the file itself: every path starts with `Resource\`, `pattern\` or `movie`,
  which only the right key byte gives, and the rest of a path is any bytes a Windows file name holds.
- **Korean names.** Some names have Korean letters in the client's code page (cp949: 51 names in 11 of the files of the
  whole client data), and in six files such a name is the first under its key byte; it pins the key byte like any
  other name.
- **Every one of the 92 files** of the whole client data opens with this one scheme. One that no key byte opens is
  another build's: it is left out as not readable (`pak.PakUnreadable`), never called damaged.

The reader is plain Python, so it works in bulk:

- **The key stream.** A word is the float32 bits of a sine or cosine of float32(seed + i); from seed 2^28 on,
  float32 rounds 32 to 512 consecutive values of seed + i alike, so a word is worked out once per run and repeated,
  and below it `array` and `map` work out every word in C loops. The words are added or taken all at once, as 32-bit
  lanes of one big integer. A megabyte took 220 ms one word at a time and takes 5 to 28 ms; every entry of the 92
  files of the whole client data reads the same bytes as before.
- **The key byte search** first tests word 0 of its 256 candidates, whose seeds share three bytes, from one table.
- **A file opened again** takes its listing (the header, the entries, the key bytes) from its first walk while its
  path, size, times and file number are the same.
- **The descriptors** are walked through a window of the file that grows while each read serves several, since on a
  slow drive each read is a round trip (the charts' 56,157 descriptors took 61,683 reads).

Reading also runs on a few threads (`core/parallel.py`) where they wait on the drive:

- **Reading ahead.** A large file's next windows are read ahead on four threads of its own while the walk decodes (a
  drive gives several readers more than one), a family's files are opened together, two threads opening one file wait
  for one walk, and the card's charts check starts with its look and goes on beside the survey.
- **Any thread may read.** `Pak.read` takes an entry's bytes under the file's lock and unpacks them on the caller's
  thread.
- **The song list's pictures** are read on the reading's thread and converted on the server's picture threads
  (`server/services/pictures.py`, `in_order`): reading them on these threads as well came to the same time (2.0 s
  either way as PLAY reads the whole client data, 2.4 s and 2.6 s in the server's image).
- **Threads, not processes**: the Python left is a small part of the work, and a process starts slowly on Windows.
- **Two, not more, for the work that runs Python**: the window's thread waits for Python's lock behind each (the
  PLAY page's header with its discs: 10 ms alone, 24 ms beside two busy threads, 40 ms beside four).

A family is a base (`name.pak`) and numbered patches (`name00.pak`, `name01.pak`, ...). The client opens them in number
order up to the first number missing, and each entry is read from the newest that has it (`core/game.py`, `Layers`).

## Playing client data that is only read

`core/cabinet/steps.py` lists what PLAY makes in openDMT3's own folder (`%AppData%\openDMT3\game`, `steps.Own`) from
the client data, in order: a copy of the client with the libraries it imports from the client data, the card reader
library, the settings file, the operator data with FREE PLAY (taken once: from the client data's `TECHNIKA\` an
earlier openDMT3 kept, else a copy of a cabinet's `drive e\TECHNIKA`, else the client data's `file\`), the hidden
patterns, the server address. Each step checks its part and says whether it is done; the ready check on PLAY is that
list. Then the list `openDMT3-files.txt` beside the card reader library names which of the game's paths are
openDMT3's files.

PLAY starts the client copy from openDMT3's folder with the client data's folder as its current folder. The card reader
library (`native/cardreader/files.c`, `redirect.c`) turns the client's file calls in its import table to its own:
`CreateFileA/W`, `GetFileAttributesA/W`, `CreateDirectoryA/W` and `DeleteFileA` of a path the list names open
openDMT3's file instead, and `GetModuleFileNameA/W` for the client answer a path in the client data's folder. What
was measured under Wine, the client data read only, a whole song each, and what each step does about it:

- The client finds its own folder with `GetModuleFileNameA` and makes it the current folder; answered with the
  client data's folder, its relative paths (`pack\`, `Resource\`, `TECHNIKA\`) stay the client data's.
- Every file of the game goes through the client's own `CreateFileA` (the files that hold the others, opened once and
  kept open), and its crash dumps through `CreateFileW`; nothing of the game's is opened another way.
- Run from another folder, Windows looks in System32 before the current folder: Wine's own D3DX 9 was loaded and the
  game stopped at its first sound. So the client's libraries are copied beside the copy of it.
- Each entry of a family is read from the newest of its files that has it (where the reads landed: of 31 entries in
  more than one file, every one from the newest). A changed entry goes in a copy of that file; a file written as an
  extra patch was not taken by the game.
- Client data at a path outside the ANSI code page (Korean letters on an English Windows) gave the client its own
  path with question marks, and the game stopped reading its settings; one of 280 characters could not be made the
  current folder. The longest path the game opens inside its folder is 64 characters. Such a folder is given to the game
  through its own 8.3 short name when its drive keeps them, else through a junction of openDMT3's
  (`core/cabinet/launch.py`) in a folder of the player's alone (openDMT3's own under `%LocalAppData%`, or one made for
  the PLAY under a random name in a folder every user shares, with access for the player only), checked again right
  before the game starts and taken away when the game ends.
- Without its videos the game plays songs without them; without the file with the tutorial it stops at the tutorial.

Client data an earlier openDMT3 changed (its `backup\` and list) is read through that list: the originals it kept
are what the steps start from, and the list gives them to the game where openDMT3 gives none of its own. **Put back**
restores every one. Removing openDMT3 (`client/leaving.py`) puts every file back the same way, then takes out of
`backup\` the copies the earlier version made itself (marked in its list) and the list. Every way out ends in
Velopack's uninstall, which runs the launcher once as its hook; the hook does that work too, so the app list leaves
the folder as **Help**'s **Uninstall** does.

The same steps run without the launcher, from a copy of this repository, on the client data's folder (or a folder
above it):

| Command | Does |
|---|---|
| `python -m opendmt3 check [CLIENT_DATA] [--to FOLDER]` | Prints the client's build and each step's state |
| `python -m opendmt3 setup [CLIENT_DATA] [--to FOLDER] [--window] [--keep-hidden] [--server HOST:PORT]` | Makes openDMT3's folder for the game in `FOLDER` (default `openDMT3-game`): a framed window, the hidden patterns kept hidden, the server the game connects to; then start `FOLDER\Client (openDMT3).exe` with the client data's folder as the current folder |
| `python -m opendmt3 restore [CLIENT_DATA]` | Puts back every file an earlier openDMT3 changed |

The fixed client is the game's own client with code appended (`core/cabinet/display.py`): a borderless window the size
of the main monitor with the picture stretched, the mouse read in game coordinates, and the program marked large-address
aware. openDMT3's card reader library stands in for the cabinet's in every way of playing: the game asks it for a card,
and it reads the number the launcher wrote in `openDMT3-card.txt` beside it (offline there is none, and the game plays
with NO ID CARD). It is also openDMT3's in-game layer, below.

## The in-game layer

The in-game overlay of the player's guide (the overlay bar, the menu, the quit question, notices, the FPS counter) is
the layer in the code, with frame pacing, the picture's passes, the sound and the card beside it in one library. The
game loads `CRT_R1.dll` by name before its own code runs, so openDMT3's library (`native/cardreader/`, 32-bit C
built with MinGW) lives inside the game's process. Its `DllMain` reads the launcher's choices from the environment
PLAY starts the game with (`OPENDMT3_LANGUAGE`, `OPENDMT3_CURSOR`, `OPENDMT3_PACING`, `OPENDMT3_FPS`,
`OPENDMT3_FPS_POSITION`, `OPENDMT3_SOUND_DEVICE`, `OPENDMT3_UPSCALE`, `OPENDMT3_SHARPNESS`, `OPENDMT3_ANTIALIASING`,
`OPENDMT3_PICTURE_SHAPE`, `OPENDMT3_PASS_TIMES`, `OPENDMT3_LOW_LATENCY`, `OPENDMT3_SOUND_PATH`, `OPENDMT3_RENDER`,
`OPENDMT3_AUDIO_OFFSET`, `OPENDMT3_MOTION_CLARITY`, `OPENDMT3_FLIP_MODEL`, from `core/cabinet/values.py`
`layer_environment`) and turns five of the game's imports to its own: the slots of the game's import table that hold
the real functions get ours, which call the real ones. Beside it, PLAY puts openDMT3's own `multiDLL.dll` in place of
the cabinet's touch screen library, which hands the game every finger through this one
([the touch screen](#the-touch-screen)).

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="images/inside-game-dark.svg">
    <img alt="What openDMT3's card reader library does inside the game's process. The game loads CRT_R1.dll by name before its own code runs: its own calls are openDMT3's, and the game's other calls here are turned to openDMT3's in its import table, which call the real ones. At Direct3D 9's Present: frames held to 60.0 a second, locked to the song's music (hooks.c, logic.c); the picture's passes, anti-aliasing then the upscale filter, with the safety net (post.c, shaders/); and the in-game overlay drawn over the picture (layer.c, look.c, text.c), to the graphics card and the screen. DirectSound: the chosen output, and the music held and faded while a panel is open (sound.c). GetKeyboardState and GetCursorPos: the overlay's keys and clicks never reach the game, and the pointer meets the game pixel under it (hooks.c, layer.c, logic.c). The game's file calls: openDMT3's files in place of the few it changes, the client data only read (files.c, redirect.c). The card reader's own calls: the card number the launcher wrote, so the game logs that player in (crt_r1.c)" src="images/inside-game-light.svg" width="100%">
  </picture>
</p>

| File | What it does |
| :--- | :--- |
| `crt_r1.c` | The card reader's ten exports, and `DllMain`, which starts the rest |
| `files.c`, `redirect.c` | The client's file calls turned to openDMT3's: the list beside the library read once (`redirect.c`, plain C the native tests run), each path the game opens matched against it without letter case, openDMT3's file opened in its place with the wide call; the client told it runs from the client data's folder. `OPENDMT3_FILES_TRACE` (measuring only) writes every call, and every read of one of the game's files with its place, into the in-game log |
| `hooks.c` | The five imports turned to openDMT3's: `DirectSoundCreate8` (and `DirectSoundCreate`), `Direct3DCreate9`, `GetKeyboardState`, `GetCursorPos` and `GetActiveWindow` ([the five hooks](#the-five-hooks)) |
| `methods.c` | The methods openDMT3 put in Direct3D's method tables, watched: each entry looked at once a frame and put back as openDMT3's when Direct3D filled its table in again ([the methods in the tables](#the-methods-in-the-tables)) |
| `touch.c`, `contacts.c` | The touch screen: the fingers and pens Windows reports on the game's window and the mouse as one point, handed to the game at each of its reads by `contacts.c`'s rules (plain C the native tests run) ([the touch screen](#the-touch-screen)) |
| `multidll.c`, `multidll.def` | openDMT3's `multiDLL.dll`: the three calls the client imports from the cabinet's touch screen library, at the original's names and numbers, answered from `CRT_R1.dll`'s touch screen |
| `layer.c` | The layer's state and its input: the bar and its chips, the menu and the question, the toast, the mark and the frame rate chip ([the layer's parts and their input](#the-layers-parts-and-their-input)) |
| `text.c` | The layer's words: GDI text in Pretendard Bold and Regular and DMT3 Wide, which the setup puts beside the DLL and the layer loads for the game's process only, kept once drawn so a panel drawn again costs no GDI work |
| `post.c` | The post-process chain over the game's picture, and the layer drawn in it ([the picture's chain](#the-pictures-chain), [the layer in the chain](#the-layer-in-the-chain)) |
| `render.c` | The game drawn at the screen's size: its targets made larger, its own sizes answered when it asks, its screen-space draws and rectangles turned ([the game drawn at the screen's size](#the-game-drawn-at-the-screens-size)) |
| `postmath.c` | The chain's plan and numbers with no Windows calls: which passes a choice runs, FSR 1's EASU and RCAS constants (as `FsrEasuCon` and `FsrRcasCon` work them out), NIS's (as `NVScalerUpdateConfig`), NIS's filter banks, the back buffer's size |
| `passtimes.c` | The picture's GPU time by pass (`OPENDMT3_PASS_TIMES=on`): each step's time a frame, kept over a stretch of frames and said as its median, with no Windows calls |
| `shaders/post.hlsl`, `shaders/smaa.hlsl` | The passes, shader model 3.0: nearest, bilinear, EASU's lengths (once a game texel) and EASU, RCAS, NIS's edge map and its scaler's two passes (the column sums, then across), FXAA, and SMAA's three passes around `third_party/smaa/SMAA.hlsl` |
| `third_party/` | SMAA's shader and its precomputed area and search textures (MIT); Anime4K's CNN x2 (S) as shader model 3.0 passes, `anime4k_x2_s.hlsl`, written by `generate.py` from Anime4K's own mpv shader with its weights as they are there (MIT); and the license texts of AMD FSR 1, NVIDIA NIS and the Blur Busters CRT beam simulator (MIT) and the FXAA 3.11 notice, whose algorithms the shaders follow |
| `engine.c` | Windows' shared sound engine at the shortest period the game's output offers while the game runs ([the sound engine's period](#the-sound-engines-period)) |
| `openal.c` | The Sound page's **Mixer** on OpenAL Soft: DSOAL's DirectSound over OpenAL Soft in place of Windows' own, Windows' own when it does not open ([the mixer](#the-mixer)) |
| `strobe.c`, `shaders/crt.hlsl` | Motion clarity: on a display at a whole multiple of 60 Hz from 120 up, each frame presented once a refresh over its refreshes, drawn from the chain's last two pictures by the Blur Busters CRT beam simulator's maths (`third_party/crt-beam-simulator`, MIT), a rolling scan or black frames ([motion clarity](#motion-clarity)) |
| `flip.c` | The flip model: the game's device made with Direct3D 9Ex and a `D3DSWAPEFFECT_FLIPEX` swap chain for the borderless full screen, the managed pool's resources made in the default pool as dynamic ones, the presents' statistics ([the flip model](#the-flip-model)) |
| `sound.c` | Which of the game's DirectSound buffers plays and how far, its copies of them too (for the music lock and the hold: the song's music is one buffer of minutes, played once; its key sounds are copies of short buffers), and the hold's fade, stop and start again. With `OPENDMT3_SOUND_WATCH` set (the Wine tests only), also the streams watched: when each plays against the frame count, and underruns, seen as a 20 ms block about to play that holds what it held a lap earlier (the game writes its music through one Lock a buffer, so its writes cannot be counted) |
| `look.c`, `paint.c`, `logic.c` | The pictures (anti-aliased polygons after the game's own panels: its dialogs' title tab and metal frame, its notice's glass, its glossy buttons; the bar's chips in the launcher's leaning button shape) and the decisions (the settings, the frame clock, the keys the game may see, the panels' answers and keys, the layout, when a rest may bring the bar), with no Windows calls |
| `mark.py` | The product's mark for the bar, drawn by the launcher's own code (`opendmt3/client/art.py` logo) when the DLL is built and carried in it as a resource: the bar shows the launcher's picture of the mark, never letters set in its face |
| `trace.c` | With `OPENDMT3_INGAME_TRACE` set, how the game draws (its device, its draws' vertex formats, transforms, render targets, copies), into the log; never set by the launcher |
| `test_native.c`, `test.sh` | The tests of the files with no Windows calls (the touch screen's rules read back the way the game reads them), and of the methods' watch, built with the same compiler and run under Wine |

### The five hooks

- **`DirectSoundCreate8`** (and `DirectSoundCreate`): the chosen output device by its GUID, Windows' default when
  none is chosen or it does not open, through Windows' own DirectSound or, with the **Mixer** on OpenAL Soft, DSOAL's
  ([the mixer](#the-mixer)); once it is open, the sound engine's shortest period is asked for on that device
  ([below](#the-sound-engines-period)).
- **`Direct3DCreate9`**: its `CreateDevice` gives the game's window to the layer, and the device's `Present` does
  the rest.
  - It counts frames: their length, its spread, the slowest 1 %, and openDMT3's own time in them.
  - With even pacing it holds them to 60.0 a second with a sleep and a short spin on the performance counter, in
    place of the client's own limiter (a jump the PC build's patch section put over the first instruction of the
    game's per-frame function, which is put back as it was). Locked to the music
    ([below](#frame-pacing-and-the-music)), that clock follows a song's music while one plays; with VSync on, its
    ticks are kept in the middle of a display refresh, and on a display that shows no frame sooner than its refresh
    (60 Hz) frames behind the music are left unshown now and then instead. The game's logic runs once a frame, so 60
    a second is its speed: its timers count frames.
  - It keeps at most one frame queued: an event query after each present, waited for before the next.
  - The post-process chain's safety net reads each frame's length here.
  - While the menu or the question is open during a song, it holds the game still.
- **`GetKeyboardState`**: the game reads every key and the mouse's buttons with it once a frame, so it sees none of
  those that answer the layer, and never Esc (the game's own Esc ends it at once).
- **`GetCursorPos`**: the display fix's helper reads the pointer with it; the point it is handed is turned so that the
  game gets the pixel under the pointer in the picture as placed ([the picture's chain](#the-pictures-chain)), only
  when the fix's call sites are in the client.
- **`GetActiveWindow`**: the game asks for it at the start of every frame, whether its window is the active one or
  not (`GetKeyboardState` comes only while it is), so the methods openDMT3 put in Direct3D's tables are looked at
  there ([below](#the-methods-in-the-tables)).

### The methods in the tables

openDMT3 turns methods in Direct3D's method tables once: the Direct3D object's `CreateDevice`, the device's `Present`
and `Reset`, the chain's three, the larger picture's and the flip model's. In another build of the game, Direct3D 9
was seen filling a device's method table in again about 22 frames after the device was made, which leaves the game's
own methods there. With pacing locked to the music or even, the client's own limiter is taken out, so a `Present` no
longer openDMT3's would run the game unpaced (four times its speed at 240 Hz). Every entry turned is watched
(`methods.c`): at the start of every frame (`GetActiveWindow`) and at each read of the keys, the entries are read and
any that no longer holds openDMT3's method gets it again, the real method openDMT3's calls left as it was kept (so no
one else's method is ever called in its place: one another program put over openDMT3's is taken off, never called in a
loop). The log says it the first time for each entry, then at its 10th, 100th... time. Only tables in a loaded
module's image are watched: one that could go with its object is never read after it is freed. A device whose table
was swapped for another, which no look at the entries can see, shows as 300 frames of the game with no present through
openDMT3's, said once in the log.

### The touch screen

The cabinet's touch frame came with a program that wrote the touches into shared memory; the PC client reads them
through `multiDLL.dll`, its only imports from it `OpenNexioMulti` (once at its start), `WaitNexioMulti(1, buffer)` (a
frame while a song plays, its window the active one) and `CloseNexioMulti`, all three `__cdecl`. On a PC the
original's open finds no such program, and the game plays one point read from the mouse. Measured in the client (its
touch screen's open and its point reader), with the open made to succeed:

- **The buffer**: 0x3A990 bytes, 16 of head (touching or not; how many touches, above 1 several; groups; points in a
  group), then 100 groups of 100 points of 24 bytes; the game takes up to 100 points, each at `1280 - X`, `768 - Y` of
  the point's two 16-bit numbers.
- **A press**, for the notes, is the touching starting, or, with several touches, the head's groups and points added
  up growing past the last read's. A held note and the lanes take every point of each read.
- **The menus** never read it: they read the mouse's button (`GetKeyboardState`) and the pointer, which Windows moves
  for the first finger and presses with it (its mouse made from a finger), as the cabinet's frame did.

openDMT3's `multiDLL.dll` (`multidll.c`) has those three exports at the original's names and numbers and answers from
`CRT_R1.dll` (`touch.c`, its three `openDMT3_touch_*` exports): its open succeeds when openDMT3's library is beside it
(`OPENDMT3_MULTI_TOUCH=off`, for measuring only, keeps the game's own mouse), and each read fills the game's buffer at
once (`contacts.c`):

- every finger and pen Windows reports on the game's window (`WM_POINTERDOWN`, `UPDATE`, `UP`, `CAPTURECHANGED`, from
  the layer's window procedure, which then hands them on to the game's as before, so Windows still makes the first
  finger the mouse), at the game pixel under it in the picture as placed, the same pixel the mouse gets there;
- the mouse as one point more: its left button as the game reads it this frame (the overlay's hold applied), held
  50 ms past its release as the game's own reading of the button holds it, never a button Windows made from a finger
  (`GetMessageExtraInfo`'s mark), which is a contact already;
- written turned as the frame's program wrote them, in one group, the oldest contact first;
- a contact down in the read another came up in would leave the count as it was, and the game would miss its press:
  the read then adds points off the game's screen, where nothing of the game's is, until the count is one past the
  last read's;
- a tap that comes and goes between two reads is handed once, when a read comes within 250 ms of it (the game reads
  only while a song plays: a tap on its menus is never handed to the song after);
- **the overlay's rules**: a contact begun on the bar, a chip or a panel while it shows, or anywhere while the menu or
  the question is up, never reaches the game; when a panel opens or closes, or Windows' first finger is drawn down for
  the bar, the contacts down then stay away from the game until they are lifted, as the keys and the button do;
  another finger on the game counts as play for the bar, as a click does; nothing reaches the game while a panel is
  up, nor a tap made then.

The place a finger is read at comes in the screen's physical pixels, turned into the window's own; a press that lies
in the window only one way says which way Windows gives them, and the log says so. The log says the first contact's
place and the game pixel it gave, the first finger against Windows' pointer, and each new most of fingers at once.
For the tests only (a touch screen cannot be made under Wine), `OPENDMT3_TOUCH_INJECT` puts made-up contacts down at
given reads, and `OPENDMT3_TOUCH_WATCH=on` writes what the game itself holds after each read (its count, flags and
first points) into the log, read from its memory in the PC build.

### The layer's parts and their input

<p align="center">
  <img src="images/ingame.png" alt="openDMT3's overlay over TECHNIKA 3's tutorial, in real frames. The overlay bar across the top: openDMT3's mark at its left, and at its right the menu, minimize, back to a window, and quit. The menu hangs under its button: BACK TO THE GAME, SHOW FPS, QUIT THE GAME in red. Under it, three pieces of other frames: the quit question under the X, Quit the game?, with A play in progress is not kept., KEEP PLAYING and QUIT THE GAME; a notice hanging from the top edge, Picture quality lowered to keep 60 FPS (Smooth upscale); and the FPS counter at the bottom right beside the game's FREE PLAY, 60 FPS and 16.7 ms on one line" width="100%">
</p>

- **The bar** comes when the pointer, moved to the game's very top edge or onto the mark at its top centre (the player's
  guide calls it the handle) with no button down, rests there 150 ms and the game has had no press or release for 1.5 s,
  or when a finger is drawn down from the top edge after such a quiet. It comes by itself for 3 s when the game's first
  screen shows and after each switch between a window and full screen. No key brings it.
- **How long it stays**: whole 600 ms after the pointer was last on it (looked for ten times a second), 4 s after a
  finger, then it slides back up; a press on the game takes it away.
- **Its chips**: the menu, minimise, full screen or back to a window, the X.
- **The menu** (Back to the game, Show FPS, Quit the game) and **the question** (Keep playing, Quit the game; its line
  only while a song plays): sheets hanging from the bar's foot, the menu under its chip and the chips beside it, the
  question under the X.
- **The toast, the mark and the frame rate chip**, which the menu's Show FPS turns on and off for the run. A toast that
  comes during a song waits for the song's end (`sound.c`'s song music), so nothing of the layer covers the game's
  groove meter while it is played.
- **Motion** (`logic.c`'s slides, worked out once a frame at the frame's own time, so each step is one refresh): the bar
  slides down out of the game's top edge, its foot first, in 220 ms slowing into place (a cubic ease out), and back up
  in 170 ms gathering speed (a quadratic ease in), its shadow's room travelling with it so nothing of it shows above;
  the menu, the question and the toast slide the same way out from under the bar's foot (drawn before the bar, which
  lies over what of them is still under it); the mark and a frame rate chip in a top corner hang from the bar's foot,
  the mark fading as the bar comes. A part wanted again on its way turns back from where it is, its way taking the share
  of the whole way's time its length is. With Windows' animation effects off (`SPI_GETCLIENTAREAANIMATION`, read at most
  twice a second) every part comes and goes at once; the chip and the mark fade over 150 ms otherwise. A press is judged
  where the parts stood on the screen when it was pressed (a chip pressed while the bar comes down acts).
- **The game's window** is subclassed for its mouse, its keys while a panel is up, Esc (kept from the game, which
  would end at once), Alt+F4 (nothing), its close request and command (the question) and Windows' menu mode
  (nothing). In a window its title bar's buttons are taken away and its borders size it. A press on the layer never
  reaches the game.
- **The pointer** is a cursor drawn at the display's scaling.
- **Quitting** posts the game's own close; the game's message loop ends the program (after 10 seconds without that,
  the process ends itself, exit code 0).

### The picture's chain

The game draws 1280x768, or at the picture's size in the window with **Drawn at** set to **Screen size**
([below](#the-game-drawn-at-the-screens-size)).

The game's frame, measured call by call: it clears the back buffer, draws a screen's video when it has one (Bink's
frames: the title's background, the song select's preview, a song's background), then its sprites (every draw a
textured quad in its own pixels under its orthographic projection, depth never tested), copies the frame with
`StretchRect` into a 1280x768 render-target texture for its glow, clears a second one, draws the glow composite back
over the whole frame (one quad through its effect, reading the copy) and its interface on top. Every choice runs the
chain (**Smooth** with no anti-aliasing is its bilinear pass, the picture as Direct3D's own stretch drew it), since the
in-game layer is drawn in it:

- **The device** is made with a back buffer of the window's monitor's size (the window's, if larger), copied rather
  than discarded, with no depth surface of Direct3D's own. The game's back buffer is a 1280x768 render target of the
  chain's (`GetBackBuffer`, `GetRenderTarget` and `SetRenderTarget` 0 are turned to it), with a 1280x768 depth surface
  of the format it asked for, so every size the game knows stays as it was and its own texture and glow are untouched.
- **At each present**, the state is saved in a state block; the frame is the game's back buffer itself (a texture's
  surface, with no samples; resolved from a multisampled target when the game asks for samples); the anti-aliasing
  chosen runs on it at 1280x768; the upscale filter draws it into the real back buffer at the picture's place in the
  window's client; the game's target, depth surface and state are put back; the frame is presented one to one through
  a source rectangle of the client's size, so a window that changes size needs no device reset.
- **The picture's place**: its own 5:3 shape kept, centred, with bars of the launcher's darkest neutral on the two
  other sides (logic.c `picture_rect`; the passes that draw there take its origin, constant c8, off their pixel's
  position), or the whole client with **Fill**.
- **The pointer**: the game reads it with `GetCursorPos` through the display fix's helper, which scales from the
  client's size. Its import is turned to one that hands the helper the point whose sums give the game pixel under the
  pointer in the picture as placed (logic.c `pointer_for_game`), only when the fix's call sites are in the client.
  The layer reads the pointer against the same place and lays its parts out in the picture. A reset of the game's
  releases the chain's objects first and makes them again after it.
- **The filters**: **Off** is sharp bilinear (each game pixel a block of the same width on the screen, the screen pixels
  on its edges mixed by how much of them each covers; nearest alone gave half the game's columns 1 pixel and half 2 at
  1920 across), **Smooth** bilinear, **AMD FSR 1** EASU (its two lengths worked out once a game texel, in a pass at
  1280x768) then RCAS (sharpness 0 to 100 is RCAS's 2 to 0 stops,
  FidelityFX's own mapping), **NVIDIA NIS** its edge map at 1280x768, then its 6-tap scaler with its sharpening in two
  passes: down each of the game's columns for each of the window's rows (the game's width by the window's height, one
  32-bit float), then across those sums at the window's size (NVIDIA's compute shader limits it to 2x for its tiles; as
  a pixel shader the same maths runs at 3x), **Anime4K** the small variant of Anime4K's CNN x2 (a convolutional network
  trained on drawn art): four 3x3 layers at 1280x768, each four signed features in a half-float target (the second to
  the fourth reading the one before split into its positive and negative halves), then its last layer's four values a
  texel put on the 2x2 pixels they cover at 2560x1536 and added to the picture enlarged bilinearly, and that picture
  fitted to the window bilinearly. As Anime4K's own rule, it runs only on a window more than 1.2 times the game's
  picture both ways; below that it is Smooth. On the game's own frames made smaller by the window's scale and
  enlarged back, it came closer to them than Smooth, FSR 1 and NIS at 1920x1080 and at 3840x2160, with fewer pixels
  pushed past their neighbours' range than NIS; its passes cost about 1.7 times FSR 1's at 1920x1080 and 0.6 times at
  3840x2160, since its network runs once a game pixel whatever the window's size ([measured](testing.md#anime4k)).
- **Anti-aliasing**: FXAA 3.11 Quality (preset 39) or SMAA 1x at its four presets, SMAA's luma edges (its edge pass
  reads the picture with the point filter: it reads whole pixels only).
- **Written from their published sources in floats**: shader model 3.0 has no integer or bit operations, so FSR's
  fast reciprocals, bit tricks in its source, are worked out in floats to the same values. Against those sources'
  maths run in numpy on the same game frames at 3840x2160, bilinear within 1 level, FSR 1 at 71.5 to 75.5 dB PSNR and
  NIS at 60.3 to 60.6 dB (99.9 % of pixels within 1 level for both; a few in 100,000 differ more where a comparison in
  the filter lands the other way).
- **The shaders are compiled** when the device is made by `D3DXCompileShader` from the game's own `d3dx9_40.dll` (one
  of its imports, so it is always in its process; no HLSL compiler exists for this DLL's MinGW build). Its 2008
  compiler takes 20 s over NIS's scaler at its optimisation level 3 for the same instructions it gives at its default
  level in 0.15 s, so the default is used. A shader that does not compile leaves the game as Direct3D's own stretch;
  one of Anime4K's (compiled only when it is chosen) leaves bilinear in its place.
- **The defaults**, chosen on the game's own screens at 3840x2160 (title, mode select, tutorial, song select, a song
  over its video, the result): **AMD FSR 1** at 50 with no anti-aliasing. FSR 1 is sharper than bilinear and puts no
  pixel more than 16 levels past the game's own neighbouring values on chrome and lime (NIS does on 0.6 % to 2.4 % of
  pixels, a dark ring round the notes' chrome, even at 0); RCAS at 50 keeps that, above 75 it starts to halo. The
  game's art is smooth in its textures, so anti-aliasing has little to find: FXAA changes 3 % to 12 % of pixels,
  mostly softening text, SMAA 1 % to 8 %.
- **No MSAA**: the game draws textured quads whose edges are see-through, and its hard edges are inside its textures,
  where samples do not reach. Measured with 8 samples against none on the same song, the static interface (score,
  GUIDE ON, the chrome slants, the card plates) is the same to the pixel; only animated parts differ.
- **DLSS, FSR 2 and later, and XeSS do not apply**: they need the game's motion vectors and depth, and it has
  neither.
- **No texture filtering choice**: measured on the game (`trace.c`), every draw is a textured quad sampled with
  linear minification and magnification, and none of its textures has mip levels, so a LOD bias has nothing to choose
  between. Anisotropic 16x in place of its linear filtering, on the same frames, changed the still parts of the song
  select's picture by more than 2 levels on 24 % of their pixels with no sharper art, and put a seam down a panel's
  edge; it stays the game's own.
- **The cost**: the chain's own CPU time a frame and, where the device measures it (two timestamp queries around its
  passes alone), its GPU time go into the counter's log line (never onto the screen: the chip shows a player the
  frames a second and the frame's length).
- **The safety net**: a frame counts against the chain when it took longer than 16.67 ms with 1 ms to spare and would
  not have without the chain's own GPU time (its timestamp queries; the CPU's time where the device has none), so a
  load or a stall of the game's own never counts, nor do the game's first 10 seconds (its loading), nor the frame
  after one left unshown to catch up with the music (it may go out late in its refresh, two frames' work done in
  one).
  - Two windows of 60 frames in a row with 30 such frames each step the chain down for the rest of the run, one step
    each time: SMAA to FXAA (compiled with the chain, so a step never waits for the compiler), FXAA to none, then
    FSR 1 or NIS to bilinear.
  - Each step is logged, shown once for six seconds as the layer's toast at the top of the game (a step during a song
    waits for the song's end), and written to
    `openDMT3-picture.txt` beside the DLL, which the launcher puts in its own log when the game ends and then
    removes.

### The game drawn at the screen's size

With **Drawn at**: **Screen size** (`OPENDMT3_RENDER=display`, `render.c`) the game draws its frame at the picture's
size in the window when its device is made or reset (logic.c `render_size_for`: 1800x1080 at 1920x1080, 2400x1440 at
2560x1440, 3600x2160 at 3840x2160, never under its own 1280x768), and the chain copies it into the back buffer one to
one:

- **Every target the game draws into is made at that size**: its back buffer (the chain's proxy), the depth surface
  with it, and the two 1280x768 render-target textures of its glow (its `CreateTexture`, `CreateRenderTarget` and
  `CreateDepthStencilSurface` for a target of its own size are turned to the larger one).
- **Every size it reads back is its own**: a surface's `GetDesc`, a texture's `GetLevelDesc`, the viewport and the
  scissor rectangle answer 1280x768 for a target made larger, so every sum the game makes from a size is the one it
  makes today. Measured, it reads its back buffer's size and the viewport once each, when it starts. `GetDesc` is
  replaced in the table of each kind of surface the game draws into (Windows' runtime makes a texture's level, a render
  target and a depth surface of different classes; Wine shares one table), and the chain reads a surface's real size
  through the method of its own table.
- **Its draws fill the larger target by themselves**: its sprites and its glow composite are in its own pixels under
  its projection, which the viewport maps onto the whole target. Its videos are not: they are drawn with screen-space
  vertices (a declaration with `POSITIONT`) from 0,0 to 1280,768, which no projection turns. On the larger target each
  covered its top left 1280x768 pixels, and the glow copied that over the whole picture: the background in one corner,
  black around it (an earlier try read this as the glow composite's fault). Each such draw is drawn from a copy of its
  vertices turned as the viewport turns every other draw (x by the width's ratio, y by the height's): one a frame on a
  screen with a video. A screen-space draw from a vertex buffer would not be turned; the log counts any.
- **Rectangles in its pixels are turned to the target's**: a viewport or scissor rectangle it sets, a clear's, a copy's
  and a fill's. A screenshot of its own (`GetRenderTargetData` into a 1280x768 surface) is read through a copy at its
  size.
- **The chain's own calls** (their return address in the library) pass as they are; so do the in-game layer's.
- **When a target cannot be made that large**: the chain's own (its proxy, the depth surface), every one is made again
  at the game's own size; one of the game's, that one at its own size (its glow reads it through normalised
  coordinates: blurrier, never misplaced). Either way with the reason in the log. At a device reset the game's targets
  are its own size until the chain is made again (a reset the chain does not follow leaves them so). The pointer
  reaches the game pixel under it as before (it is read against the picture's place, not the size the game draws at).
- **The upscale filter does not run**: the frame is the window's picture already (when the window grows past the size
  the game drew at, bilinear). Anti-aliasing runs at that size.
- **Checked** on every screen of a guest's play (the title, the mode select, the tutorial, the song select with its
  preview, a song with its video and notes, the result, the end), each against the same screen drawn at 1280x768:
  every part in its place and at its size. `tests/e2e/windows/render.sh` checks the sizes the game is answered and
  where its parts land without the game.
- **What it costs**: on the GPU image the game's own step and the chain with the layer came to 81 and 36 thousand of
  the card's cycles a frame at 1920x1080, against 108 and 145 with the game drawn at 1280x768 and FSR 1; 124 and 50
  against 71 and 191 at 2560x1440; 328 and 96 against 81 and 382 at 3840x2160
  ([measured](testing.md#the-game-drawn-at-the-screens-size)). The game's drawing grows with the pixels, by about
  what the upscale filter's passes cost, which do not run.
- **What it shows**: the game's art is made for 1280x768, so art that stands still is that art enlarged bilinearly as
  it is drawn, as **Smooth** enlarges it (FSR 1 sharpens its edges a little more); what moves, scales or turns lands on
  the screen's own pixels, and a video's frames are enlarged once, from their own size.

### The layer in the chain

The layer is drawn by the chain after the upscale, into the real back buffer at the window's own pixels, so its edges
and words are sharp at any size and its motion keeps the game's frame timing; no window of its own lies over the game.

- **A part's picture.** Each part (the bar, the bar's chips, the menu or the question, the toast, the mark, the frame
  rate chip) is a picture made on the CPU (`look.c`, with `text.c`'s words) only when it changes, kept as two dynamic
  textures: what is drawn and where the glass is. They are written whole with a DISCARD lock, which never waits for
  the GPU (a managed texture's lock read the texture back first, 2 ms a chip update on Wine's software renderer).
  Every part's textures are made when the layer first draws at a size (the game's loading, a change of the window, a
  reset), as large as the part gets there, filled and drawn once unseen: none is made while the game plays.
- **The glass.** While the bar, a panel or a toast shows, the game's 1280x768 frame is averaged 8x8 into a 160x96
  target, blurred across, then down (a Gaussian of sigma 1.5 texels, 12 of the game's pixels, 9 reads). The three
  passes run when the panel comes, in that frame, then one of the three every sixth frame, each reading what the pass
  before wrote, the finished picture shown while the next is made, so the glass is new every 300 ms. A pass draws
  into its own small target, which on Wine's software renderer costs about 0.3 ms whatever its size, against 0.02 ms
  of its own work; the frames between draw no pass. While the game is held still the three are made once, in one
  frame, for the frame it holds.
- **How a part is drawn.** A part with glass is composed once into a texture of its own: the blurred frame at its
  place, the tint over it (#0a0d10 at 80 %: opaque, never the game's details behind words) and its picture over
  that. It is composed again only when the glass is new, its picture changes or it moves, and every frame draws that
  one texture with the fixed function (reading the blurred frame in every frame cost Wine's software renderer about
  1 ms a part).
- **The chip** has no live blur: its glass reads a blurred frame made whole in one frame when it first shows and
  again after any live blur (reading the last live one cost that renderer about 1 ms a frame for as long as the chip
  showed; one made whole, about 0.2 ms).
  - Its picture is its glass and edge, drawn once for a size, with its words laid over from pieces kept for good
    (`text.c`, TEXT_GLYPHS: each digit in a cell as wide as the widest, so the number does not shift, and each other
    run as one piece, made by GDI the first time at a size), so its two updates a second copy rows and blend about
    ten small pieces, with no GDI drawing.
  - Its glass is faint (80 %), so the game shows through it, with its tint deeper than the panels' (92 %, so the
    blurred frame it reads, made when it first showed, comes through at 8 %: no old screen to be seen in it), and its
    words are drawn whole over it, so they keep 4.5:1 over the game's brightest screens (62 % as a whole, words
    and all, gave 2.8:1 over a bright song). It lets clicks through, and hides while the game is held still and before
    the game's first screen.
- **The mark and the bar's chips** have no glass of their own (the chips lie on the bar's): their pictures alone are
  drawn with the fixed function, the blurred frame not read (about 1.2 ms a frame on that renderer had the mark read
  the live blur's last frame; drawn so, nothing measurable).
- **Sizes.** A part's size is the game's own: one game pixel is the window's height over 768 output pixels, so the
  panels keep the proportions of the game's own dialogs at every resolution (Windows' scaling sizes the pointer).
- **Places.** Everything stays in the game's top band and its corners: the bar covers the game's own top bar (70 of its
  768 lines), the menu and the question hang from its foot at the right (the menu as wide as the chips' row, the
  question under the X) and end above a quarter of the height, the toast hangs from the top edge's middle (from the
  bar's foot while the bar is down), its right end kept clear of the panels, the mark (a rail 72 game pixels wide and a
  tab 32 wide, 9 deep, 12 under the pointer) hangs from the top edge's middle on the groove meter's chrome rim, never
  over its gauge, the chip sits in the corner chosen. The parts' quads are cut to the picture, so a part on its way out
  of the top edge never shows over a bar above the picture. Nothing reaches the middle half of the game, where notes
  come, and none of these parts covers another (`native/cardreader/test_native.c` checks both at seven window shapes).
- **The chip's corner.** Its default is the bottom right, beside the game's FREE PLAY label: on the game's screens (its
  warning, the title, the mode and song selects, a song, the results) every corner's very edge holds something of the
  game's own (JOIN THE CREW or a mode's banner at the top left, SKIP or a countdown at the top right, ID CARD and NET at
  the bottom left, FREE PLAY at the bottom right), and its notes come right up to the sides: a note of the third lower
  row, measured in a song, has its centre on line 693 of 768 and the foot of its ring on line 748, the line of the
  game's own labels. So at the foot the chip is one line of 118 by 13 game pixels on that line, from line 742: at the
  right its right end 8 game pixels left of FREE PLAY, at the left 8 right of ID CARD, NET and PATCH, placed across in
  the game's own pixels (a filled picture stretches them). There it covers none of the game's labels or buttons on any
  of its screens, and at most the foot of a note's ring passes under it, as under FREE PLAY; above FREE PLAY, where it
  was, half of such a note came under it.
- **The game's first screen** is found by averaging every 15th frame 8 by 8 and reading it back until one has
  anything on it (the frames while the game loads are black): the bar then comes down by itself for 3 s.
- **Without the glass.** When the glass passes do not compile, or the chain does not run, the parts are drawn with
  Direct3D's fixed function (the tint opaque, no blur), into the chain's back buffer or the game's own.

#### What the layer costs

The layer's cost goes into the log every two seconds, a line for each kind of part drawn (`layer cost fps chip:`,
`bar`, `bar chips`, `panel`, `toast`, `mark`, and `blur`): the frames it was drawn in, its CPU time a frame (its upload
and draw calls), each picture drawn again (its CPU time, the longest, its upload) and, for the chip, the GDI drawings
its updates needed. Its GPU time is measured only when asked, three ways:

- **`OPENDMT3_LAYER_TIMING=on`** adds timestamps around its blur pass and each part, read four frames late with the
  chain's and never waited on. On Wine's software renderer, where work is done in batches, the first part's span
  takes in the end of the chain's: there they mislead.
- **`OPENDMT3_LAYER_TIMING=frame`** (measuring only, for the Wine tests; it stalls the frame) times the chain's and
  the layer's whole work in each frame, the device made idle before and after it: turns with a part shown and without
  it give what the part adds to a frame as it is drawn.
- **`OPENDMT3_LAYER_TIMING=sync`** (measuring only too) makes the device idle around each part, draws it once and,
  every other frame, nine times over (eight copies too faint to change a pixel): what the eight cost is its drawing
  alone, and one draw against an idle round with nothing is what it costs as its own batch (about 1.15 ms for any
  part on that renderer at 1920x1080, the batch rather than the part: a part drawn after the chain's last pass shares
  that pass's batch).

The chain's own GPU time, which the safety net reads, is bracketed around its passes alone, and a frame with the bar,
a panel or a toast on the screen is not judged at all: the panels never make the picture's filters step down (the
chip and the mark, which show for long, are no panels: frames with them are judged).

Measured on Wine's software renderer at 1920x1080 with FSR 1 at 50:

- **Each part's drawing alone** (sync): the chip 1 to 10 us, the bar 105 to 140 us, the bar's chips under 3 us, the
  menu or the question 15 to 40 us, the toast 12 to 22 us, a blur pass 62 to 95 us.
- **What each adds to a frame as it is drawn** (frame, ten turns each, the median turn): the chip -0.03 and +0.04 ms
  in two runs (nothing), the bar +0.37 ms and the question +0.63 ms (their blur's passes, a pass in its own small
  target, among it). One run of the same turns gave +1.0 to +2.0 ms for all three, the chip with its turns right
  after the bar's; its next runs gave none of it. Making the blur's passes at the frame's end instead of before the
  chain measured no cheaper, so they stay first.
- **As a player has it** (no switch): the chip's CPU time 4 to 6 us a frame, an update of it 33 to 43 us drawn and 6
  to 16 us uploaded, no GDI drawing; drawing a panel's picture again when it shows takes 1 to 7 ms of CPU once (the
  bar's chips 1 ms, the toast 2.5 ms, the menu or the question up to 7 ms), at the frame it appears.
- **The timestamps** of `OPENDMT3_LAYER_TIMING=on` changed neither the CPU time a frame (48 to 74 us for the chain
  and the layer, with or without) nor the pacing.

The same parts measured on the PC's own graphics card are in [Testing](testing.md#what-it-measured).

## Frame pacing and the music

The game runs its logic once a frame, so its notes move by frames, and its music plays by the sound card's clock. A
frame late is a game slower than its music. Three pacings:

- **The game's own**: the client's limiter, 17, 17 and 16 ms.
- **Even**: openDMT3's clock at exactly 60.0 a second. A frame more than a frame late (a load) starts the count again
  from it, so a stall's time is lost against the music.
- **Locked to the music** (the default): even, and while a song plays (`sound.c`: a buffer of 10 s or more played
  once, the newest), frame k of the song belongs at k/60 s of its music. At each frame the distance between the
  music's position at the frame's tick and the frame's place is smoothed (a tenth of each reading: the sound card's
  cursor moves in steps), and a twentieth of it moves the next tick: nothing within 1 ms, at most 1 ms a frame for a
  drift, 4 ms a frame (a quarter of a frame) to win back a stall over 50 ms, so no frame is skipped or doubled and a
  correction is spread over many frames. The distance the game itself started the music at is kept, not corrected,
  for the whole song: a reset of the device during it (a switch between a window and full screen, a device lost)
  starts the lock's readings again from the same start, so the reset's own stall is won back as any stall is. A
  display that shows no frame sooner than its refresh takes the frames back in whole frames instead
  ([below](#a-display-that-shows-no-frame-sooner)).

**The audio offset** (**Sound**, 0 to 500 ms, 0 by default; `OPENDMT3_AUDIO_OFFSET`) moves the lock's target: a
song's frames are held that many milliseconds further behind its music than the game's own start put them, so the
notes, and the presses judged against them, meet the music where a sound device that plays late (Bluetooth, a TV over
HDMI) lets it be heard. The lock takes the new distance as it wins back a stall, 4 ms a frame while more than 50 ms
off and 1 ms a frame after that: no frame is skipped or doubled, the song's first frames only run a little slower.
The offset is counted once a song, from its own start, through any reset during it (`logic.c` `SongLock`).
Measured under Wine on the GPU over a whole song at 1920x1080: with 200 ms, the frames went from 184 ms short of it at
the song's 6th frame to it at the 54th (0.9 s) and kept within 4 ms of it from the 102nd on, but for a stall of the
busy machine's (81 ms), won back within a second; at the music's stop it was 213 ms ahead of its frames.

With VSync on, the display's own phase is read at each tick (`GetRasterStatus`) and the next tick moved by at most a
64th of a refresh towards the middle of a refresh, so the present waits for the same refresh every frame: on a 240 Hz
display every fourth. A display that reports no refresh rate, or whose raster position never moves, is left alone.

The sound is left as the game makes it: it asks for priority level and sets the primary buffer to 22050 Hz, 16 bits,
stereo, and its own buffers are 44100 Hz, 16 bits. Under Wine the mix runs at the output device's format whatever the
primary buffer says (recorded at a 48 kHz, 24-bit output, the music keeps its content up to 18 kHz, as at 44.1 kHz),
so a change to the primary buffer's format shows no difference here and is not made.

At most one frame waits for the GPU: after each present an event query is issued, and the next frame waits for it
(at most 100 ms) before its own tick. Work of openDMT3's own that can take milliseconds (a panel's picture drawn again
as it shows, GDI text) is done at a frame's start, inside its wait for its tick, never after the tick.

**Each frame started just in time** (`hooks.c` `jit_rest`, `logic.c` `jit_lead`). The game reads its input
(`GetKeyboardState`) as soon as a present hands it control back, so with the wait for its tick at a frame's end, the
input a frame carried was most of a period old at its present. With even pacing or locked to the music the wait comes
before the frame instead: after a present, the game's next frame is held until its tick less its work, a spare and what
may still move the tick earlier, and only then gets control and reads its input.

- **Its work** is the processor's part, from the game's control back to its frame ready to present (the chain's draws
  handed over, the frame before done on the GPU): the slowest 1 % of the last 120 frames (the second slowest).
- **The spare** is 1 ms. A frame started late whose picture is not done on the GPU by its tick adds a millisecond, a
  quarter of a frame at most; after 300 frames started late in a row done in time, it goes back a tenth of a
  millisecond a frame.
- **What may move the tick earlier**: the music lock's step while a song plays (1 ms, 4 ms while it wins back a
  stall) and the display lock's (a 64th of a refresh); on a display that shows no frame sooner than its refresh, the
  display lock's alone (the music lock takes nothing off a tick there).
- **Before its tick**, once the two locks have set it, each frame's commands are flushed to the GPU and its picture
  waited for (an event query, until the tick at most), so the GPU draws it while it waits; one not done by its tick is
  the miss above.
- **The ticks do not move**: the frames leave on them at 60.0 a second, locked to the music and kept to the display's
  refresh as before.
- **At once**, as before: a frame whose work and spare leave no room before its tick (a present that came back late),
  the first 600 frames after the game's device is made or reset (its loading, while the work is learned), the frames
  while a glass panel shows (its pictures may be drawn again at a frame's start, which the wait before the tick takes
  in), and the game's own pacing; and a frame to be left unshown to catch up with the music, and the one after it. Three frames started late in a row that miss their tick with the spare at its most
  (a GPU slower than any spare covers) start the next 300 at once too, after which the clock tries again.

Measured under Wine on the GPU over a whole song, the same build with `OPENDMT3_JIT=off` and without in turns
([Testing](testing.md#a-song-each-frame-started-just-in-time-before-and-after)): at 1280x768, 65 and 86 % of the
song's frames started just in time, 10.8 ms before their tick, and under 1 % of those were not done by it. From the
game's read of a press to its frame done on the GPU took 13.9 ms at the median against 15.6 with every frame started at
once (1.7 ms less, 1.2 to 2.1 at 95 % over 155 presses a side), at 60.0 frames a second with the same spread and the
music within 13 ms of its frames at its stop. The whole time from the press, which adds the wait for the game's next
read from wherever in a frame the press falls, was 21.3 ms against 22.8 at the median, within that wait's own spread at
these counts. At 1920x1080 Wine's present takes about 9 ms (it reads each frame back from the card to its virtual
screen, which a present on Windows does not), so a present comes back with less time to the next tick than a frame's
work and spare: 0.3 % of the frames started just in time, the rest at once by the rule above, and from the read to done
took 15.4 ms, as with it off. What it takes off on Windows, where a present leaves most of the period, is for a real PC.

Measured on the real client under Wine at 1920x1080 over a whole song (123 s, the frame series and the sound card's
own cursor):

- **The game's own pacing**: the music ends 1.2 s ahead of the frames (59.4 frames a second).
- **Even**: the frames hold 16.667 ms, but a stall's time is lost (2.0 s behind after a 10 s stretch of a busy
  machine).
- **Locked to the music**: the song ends within 7 ms of its frames at 60.01 frames a second, frame time spread
  0.2 ms.
- **From a press to its frame done on the GPU**: median 24.8 ms with one frame queued, 26.3 ms as Direct3D queues
  under Wine (whose renderer queues little; a driver's queue of up to three frames is where the limit counts).
- **NVIDIA NIS with SMAA Ultra on Wine's software renderer**: the safety net stepped it to FXAA, to none, then to
  bilinear, and the song after ran at 60.01 frames a second within 7 ms of its music (at 3840x2160 the same three
  steps 46 to 59 s after the start, then 60.01 frames a second, longest frame 19 ms).
- **The defaults** (FSR 1 at 50, locked to the music, a chosen output): 60.01 frames a second, frame time spread
  0.35 ms, the chain's CPU time 36 us and GPU time 7.5 ms a frame. Recorded from the output itself, the sound has no
  gap of 5 ms of silence and no click at the music's starts and stops, and from the device's opening to the game's
  first sound every sample is silence.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="images/chart-pacing-dark.svg">
    <img alt="Frames on time and on the music: the game's own frame limiter against openDMT3's clock, locked to the music. The spread of a frame's length (standard deviation): 2.33 milliseconds against 0.00. The slowest frame in a hundred: 20.6 milliseconds against 16.8, where a frame at 60 a second is 16.7. Measured on an RTX 4090 at 1920x1080 on the game's title screen. Over a whole song of 123 seconds on Wine's software renderer, the music ended 1.2 seconds ahead of the frames with the game's own pacing, and within 7 milliseconds of them locked to the music" src="images/chart-pacing-light.svg" width="100%">
  </picture>
</p>

For measuring only (never set by the launcher): `OPENDMT3_QUEUE=deep` leaves the queue as Direct3D has it,
`OPENDMT3_LATENCY_WATCH` logs each press's time to its frame done on the GPU (and its parts: to the game's read of it,
from the read to the present, from the present to done), `OPENDMT3_JIT=off` starts every frame at once (to compare),
`OPENDMT3_PRESS_MARK=on` draws a white square at the picture's bottom left in every frame whose read sees the mouse's
button down (a photodiode's target: a click to light is the game's own way from its input to the screen),
`OPENDMT3_SAFETY=off` keeps the chosen chain, `OPENDMT3_REFRESH` gives a refresh rate to a virtual screen that reports
none, `OPENDMT3_STROBE_WATCH` reads motion clarity's sub-frames back, one frame in 120, and logs them,
`OPENDMT3_CATCHUP=off` keeps the lock as before on a display that shows no frame sooner (every step taken, nothing left
unshown), `OPENDMT3_VBLANK=wait` brings each present back at the display's next refresh by its raster position (with
`OPENDMT3_REFRESH=60`, Wine's virtual screen, which shows every present at once, then shows no frame sooner, as a
60 Hz display with VSync), and `OPENDMT3_STALL=MS[,MS...]` stalls a frame that many milliseconds in every song, the
n-th n times 20 s into its music (four at most), as the game's own hiccups do.

While the menu or the question is open during a song (the song's music buffer playing), the game is held still:

- **The picture.** After the frame that opened the panel, the present does not hand control back to the game. It
  presents the game's last frame again through the chain at 60 a second with the layer over it, and pumps the
  thread's messages itself; the layer's window procedure takes the mouse and the keys, and every other message of the
  game's window goes to Windows' default handling instead of the game's, its timers wait.
- **The sound.** The game's DirectSound buffers playing at that moment (the music, and the key sounds over it, which
  the game plays from copies of its buffers made with DuplicateSoundBuffer) are faded out over the hold's first eight
  frames (an eighth of their level less each frame: a cut mid-wave would click) and stopped.
- **Going on.** When the panel closes, each buffer is set back to the place the hold found it, played again and faded
  in over the next eight frames; the sounds the game starts in those frames (a song's first frames back start several
  at once) come in at the same share, and a volume the game sets meanwhile becomes the fade's goal. The game's next
  frame is due a frame after the music starts, so music and notes go on from the moment they stopped together.
- **Quitting** ends the hold before the game's own close is taken.
- **With no chain** (its back buffer is not kept from one present to the next) the game goes on under the panel.

Measured on the real client under Wine (1920x1080, locked to the music, the output recorded):

- **The holds.** Three holds of 5.3, 4.0 and 2.9 s in the tutorial's song and two of 5.3 and 4.1 s in a song (there
  the music and four of its key sounds held each time, and seven or eight sounds started by the game in the fade in's
  frames) each faded out and back in: the first 16.7 ms after each silence at 0.04 to 0.07 RMS, the music's level
  reached over the next eight frames, the jump into and out of each silence 0.0001 at most, and no change between two
  samples within a fade larger than the music's own largest in the 2 s around it.
- **The music against the frames.** The music's place against the frames changed by at most 5.6 ms across a hold (the
  sound card's cursor moves in 10 ms steps; a frame is 16.7 ms), and at the music's stop music and frames agreed
  within 6.7 ms.
- **The layer's cost.** On the title screen at 1920x1080 with FSR 1 at 50, in English and Korean at Windows' scaling
  of 100, 150 and 200 %, on Wine's software renderer, the layer took a median 19 us of CPU a frame (up to 7 ms in a
  frame where a picture is drawn again) and 1.5 to 2 ms of GPU.
- **The frames with a part shown.** Where the game's picture and the chain took about 2.5 ms of GPU a frame, the
  frames held 60 a second with a spread under 0.5 ms in 84 of 100 two-second windows with a part shown (11 of 12 with
  nothing shown); where they took about 8 ms (stretches of the title screen), they held 60 in 9 of 20 windows with
  nothing shown and in none of 42 with a part shown (54 to 58 a second in 37 of them).
- **At 3840x2160** the safety net stepped FSR 1 down to bilinear, the frame was at its limit with nothing shown, and
  the layer's 2 to 2.5 ms of GPU a frame took it to 46 to 53 frames a second while a part showed.

The layer's log (`OPENDMT3_INGAME_LOG`) is for the Wine tests.

### A display that shows no frame sooner

With VSync on, a present waits for the display's next refresh, so a display under 64 Hz (60 Hz, the usual one, 59 for
59.94, 50) shows a new frame at most a millisecond a frame sooner than the game's 60 a second (`logic.c`
`catchup_display`). A tick the lock takes earlier never reaches the screen: frames behind the music after a stall (the
game's own load, Windows busy) would stay behind for the rest of the song, and so would they after any frame that
misses its refresh (it shows a refresh late, and with one frame queued so does every frame after it); at 59.94 Hz they
would fall a millisecond a second further behind with no stall at all. There the lock takes nothing off a tick (a tick it holds
back still shows, a refresh later, so that step stays), and frames are left unshown instead (`logic.c`
`catchup_frame`, `hooks.c` `leave_unshown`):

- **When**: at each frame shown, the lock's reading; when the median of the last five since the last frame left
  unshown is more than a frame (16.7 ms) behind, the next frame is left unshown. So at most one frame in six, never two
  in a row: 2.8 ms a frame (the lock's own pace elsewhere is 4 ms). Once that median is within a frame, the catch-up
  is over.
- **How**: the game runs the frame, and its present goes back to it at once, with no post-process chain, none of the
  layer's drawing and no real present; the game's next frame takes the tick the frame left unshown had, so it shows a
  refresh after the frame before, a whole frame further into the song. The frame to be left unshown starts at once rather than just
  in time, so the one after it has the most of the time before that refresh.
- **Only when it fits**: as the frame to be left unshown comes, the refresh it would have shown at is read from the
  display's raster position, as the display lock reads it, up to the blank that ends it (`catchup_deadline`: the
  raster's line runs over the visible lines only, so the rest of a refresh counts as 95 % of what the line says). It
  is left unshown only when the next frame's work on the processor and then its chain's passes on the GPU (the
  slowest 1 % of the last 120 frames' each, the GPU's by the chain's timestamps) end, and its tick comes, an eighth of
  a refresh before that blank (`catchup_work`, `catchup_fits`); otherwise it is shown and the next try is six frames
  on. The frame after one left unshown is waited for on the GPU until a sixteenth of a refresh before that blank at
  most; going out later, or with its picture not done by then (the game's own GPU work is not timed), it may have
  missed that refresh (the frame before shown twice, nothing won): none is left unshown for five seconds after it, nor
  for the rest of the song after three, a reset in the song or not.
- **Only there**: with the display lock running and the raster position read at the last frame (where it is not
  read, the lock keeps its own steps, as before: VSync may not hold there), while a song's music leads, with no glass
  panel up (the bar, the menu, the question, a toast: their motion would stutter), and not on a display from 64 Hz up
  or with VSync off, where the lock's own steps reach the screen. Motion clarity's sub-frames (from 120 Hz) and the
  flip model's judgement of a display that follows the frames (from two refreshes a frame) never meet it. A frame
  the measuring dump names (`OPENDMT3_POSTFX_DUMP_AT`) is always shown.
- **What counts it**: the game's frame number, the sound's frame and the trace count the frame left unshown, so a
  song's place is still the game's; the counter's line, the frame series and the FPS chip count the frames shown (60 a
  second). The safety net does not judge the frame after one left unshown. With **Measure the picture's GPU time**,
  the game's own frame is timed from the frame left unshown on, so its step holds one frame's work. A press the frame
  left unshown read is timed with the next frame shown, which carries it.
- **Its line**: each catch-up writes one line in the log: how far behind the music it began, the frames left unshown
  over how long, how far behind after, and frames too late or not left unshown after all, when there were any (`pacing:
  caught up with the music: ...`); one cut short by the song's end or a reset says so.

Simulated as `hooks.c` runs it (`test_native.c`: each present back at the next refresh, or at once with Direct3D's
queue of one frame; the music 0.05 % fast, read in the sound card's 10 ms steps; the game's work 2.5 to 3.5 ms a
frame): at 60 Hz with VSync a stall of 100 ms 20 s into a song was won back to within a frame in 0.47 s (six frames
left unshown) and one of 400 ms at 60 s in 1.97 s, never two in a row, none too late, no frame shown twice, and between
the catch-ups the frames kept 0 to 18 ms behind (a frame, and the little a median of the cursor's 10 ms steps misses);
before this, the frames stayed 500 ms behind to the song's end. At 59.94 Hz two minutes with no stall stayed 0 to
19 ms behind (120 ms behind before). With an audio offset of 80 ms the stalls were won back the same. At 120, 144 and 240 Hz and
with VSync off nothing was left unshown and the lock won both stalls back itself. With 6 ms of work a frame, two
frames still fit in a refresh and both stalls were won back; at 9 ms none fit and nothing was left unshown. With the
chain at 6 ms a frame on the GPU (timed) after 2 ms of the game's own draws, both were won back; with the game's own
draws at 6 ms (not timed), the first three frames after a skip were judged too late and nothing more was left
unshown in the song, none shown twice. At 50 Hz the game's 60 frames a second leave one frame in six unshown by
themselves: the frames stayed within 100 ms of the music for 90 s, where they ended 18 s behind before, but a stall's
distance is not won back there.

Measured under Wine on the GPU over a whole song and the tutorial before it, the virtual screen made a 60 Hz display
with VSync by `OPENDMT3_REFRESH=60` and `OPENDMT3_VBLANK=wait`, stalls of 100 and 400 ms in each
([Testing](testing.md#a-song-after-stalls-on-a-60-hz-display-before-and-after)): at the music's stop, music and frames
agreed within 3.3 ms in the song and 16.0 ms in the tutorial, and no frame after a skip was too late. With
`OPENDMT3_CATCHUP=off` they ended 1985 ms apart: far more than the stalls, since each present that missed its refresh
(4 to 8 % of them on that busy machine) took every frame after it a refresh later. Caught up, each of those was won
back by a frame left unshown a few frames later. There the chain's GPU time, read under WSL's D3D12, now and then ran
long in the next frame's estimate, and the tutorial's 100 ms took 4.2 s to win back, where a build counting the
processor's part alone took 0.58 s.

### Motion clarity

On a display at a whole multiple of 60 Hz from 120 up (within 1 Hz: Windows gives 119.88 and 239.76 Hz as 119 and
239), with VSync on and **Motion clarity** chosen (`strobe.c`, `logic.c` `strobe_refreshes`), each game frame is
presented once a refresh over its N refreshes (N = the refresh over 60): the first at the frame's tick,
drawn with the frame's own work, the others a refresh apart after it (`hooks.c` `present_subframes`). Each is one pass
(`shaders/crt.hlsl`) from the chain's last two pictures, copied into two kept textures at each frame (the newest and the
one before), written from the Blur Busters CRT beam simulator (MIT, `third_party/crt-beam-simulator`). In linear light,
each pixel's light is a budget of N times a gain (0.5 at 120 Hz, 0.6 at 180, 0.7 from 240 up) refreshes, given out as
early as it can be from the moment the simulated beam reaches its row: a dim pixel is lit for a part of one refresh, a
bright one for most of the frame. **CRT beam** rolls from the top down over the frame, so the lower rows are lit later
(the bottom about 12.5 ms after the top at 240 Hz) and their light runs on into the next frame's first refreshes;
**Black frames** lights every row from the frame's first refresh. The simulator's newest frame is never lit at a whole
number of refreshes a frame and is left out, and so is its slew for LCD polarity (N plus 0.001): every game frame here
is exactly N refreshes. A display not at such a rate, VSync off, or no chain leaves every frame shown whole, and so
does a display whose raster position does not move (its ticks are then not kept mid-refresh, and a sub-frame would now
and then miss its refresh). The sub-frames are presented from the
game's own thread, so the game's next frame has the frame's last refresh for its work and the chain's (8.3 ms at
120 Hz, 4.2 at 240): the log's `strobe:` line every two seconds counts the sub-frames that left over half a refresh
late. The picture's safety net does not judge frames shown over sub-frames (`logic.c` `guard_frame_shown`): the
sub-frames' wait, not the chain, is what leaves the next frame late there, and a lighter picture would not help it.

Measured under Wine on the GPU (`OPENDMT3_REFRESH` gives Wine's virtual screen, which reports no rate, 240 or 120 Hz;
`OPENDMT3_STROBE_WATCH` reads one frame in 120 back small, in eight bands from the top): with the CRT beam at 240 Hz the
bright bands went down the screen over the four sub-frames (sub-frame 0 the top two bands at 148 and 112 with the
frame before still glowing in the bottom ones, then the next two at 146 and 196, then 170 and 182, then the bottom
three), presented 0, 4.27, 8.55 and 12.50 ms after the frame's first; black frames lit every band in sub-frame 0 (118
to 155), less in the next two and none in the last; at 120 Hz the top half was lit in the first and the bottom half in
the second. Each of Wine's presents also reads the frame back from the card to its virtual screen, a cost a Windows
present does not have: at four presents a frame on a busy machine the frames there fell to 50 to 52 a second, and 6 to
8 % of the sub-frames left over half a refresh late (the same screen without them held 60.0, spread under 0.2 ms).
How it looks, flicker and brightness included, is for a real display.

### The flip model

With **Flip model** on (`flip.c`) and the game starting in a borderless window over its whole monitor with the chain
running, its device is made with Direct3D 9Ex (`Direct3DCreate9Ex` beside the game's own `Direct3DCreate9`,
`CreateDeviceEx` with present statistics) and a `D3DSWAPEFFECT_FLIPEX` swap chain of two back buffers (Direct3D adds
one): each frame's back buffer goes to Windows' compositor instead of being copied into its surface, the way to
Windows' independent flip and to a variable refresh rate for a borderless window. FLIPEX presents its whole back buffer,
so the back buffer is the window's own size, a window smaller than the game's picture too, presented with no
rectangle; when the window changes size (to a window and back), a 9Ex reset of openDMT3's own makes it again at the new
size, which keeps every other resource. The game knows nothing of that reset, so with the game drawn at the picture's
size (**Drawn at**) the size it is drawn at stays as it was: its targets made at that size live on through the reset,
and the chain scales its picture to the new window (`logic.c` `render_size_after_reset`). Anything else (another start,
a Windows with no 9Ex, a device that is not made so) is the copy model, as before.

- **No managed pool.** A 9Ex device refuses it: every texture, cube and volume texture, vertex and index buffer asked of
  the managed pool, by the game, its D3DX loader or openDMT3, is made in the default pool as a dynamic one, which can be
  locked as a managed one can. Two things found under Wine make it a managed pool's stand-in: the device and the
  Direct3D object answer to every interface but 9Ex's (the game's D3DX asks for `IDirect3DDevice9Ex` and, told it is on
  9Ex, refuses to make an empty texture in the managed pool: the game's 512 x 512 glyph textures were never made, and
  the game ended at its start), and a read lock on a texture so made, or on its levels' surfaces, is taken as a write
  (the game locks its video's planes every frame with `D3DLOCK_READONLY` and writes them: a managed texture's copy in
  memory keeps that, the default pool's hands nothing to the card, and the title's video stayed green).
- **Present statistics** come with it, read after each of the game's own frames: over how many refreshes the
  presents shown since the frame before went. Frames that were one present each (none with motion clarity's
  sub-frames), nine in ten a refresh apart over two seconds, on a display whose mode gives each frame two or more, mean
  the display follows the frames (a variable refresh rate, G-SYNC or FreeSync; `logic.c` `display_follows`): the
  display lock then stops, as there is no refresh to keep a tick in, until the display is found keeping its own
  refresh again. While motion clarity's sub-frames run there is nothing to judge: a present every refresh drives a
  display that follows the frames at its own rate just as it drives a fixed one, and the sub-frames, timed by
  openDMT3's clock, go on the same on either. Wine gives no statistics (zeros), so this part is for Windows.

Measured under Wine on the GPU: a whole song with it at 1920x1080 (152 textures and a buffer moved from the managed
pool, none refused, 25,764 read locks taken as writes), 7,391 frames at 60.00 a second with the music within 6.3 ms of
its frames at its stop, the title, its video and its glow drawn as with the copy model, and full screen to a 1350x810
window and back, the back buffer made again each time. Whether Windows flips it independently, and what it saves from a
present to the screen, are for PresentMon on Windows.

## The sound engine's period

Windows 10's audio engine mixes each output device in steps of its period: 10 ms unless a program asks for less with
`IAudioClient3`. While one does, every program in shared mode on that device goes in those steps, DirectSound among
them, and the 10 ms come back when it stops (Microsoft's "Low Latency Audio"). Windows' own HDAudio driver offers 128
to 480 frames at 48 kHz (2.67 to 10 ms); many makers' own drivers offer only their default.

With **Low latency** on (the default, `OPENDMT3_LOW_LATENCY`), `engine.c` takes over once the game's DirectSound
object has opened its device:

- **The device.** Found among Windows' endpoints by the DirectSound GUID each endpoint carries
  (`PKEY_AudioEndpoint_GUID`); for Windows' default output, by the GUID DirectSound's own `GetDeviceID` gives it.
- **The period.** Its periods for the engine's own format (`GetSharedModeEnginePeriod`), and the shortest one asked
  for with a silent stream of openDMT3's own (`InitializeSharedAudioStream`), started and never written to.
- **Held or let go.** When the engine then runs at a period shorter than its default, the stream is held until the
  game's process ends; otherwise it is let go at once.
- **Its own thread.** All of it runs on a thread of its own in COM's multithreaded apartment, with COM's library loaded
  there: the game's own thread joins no apartment, its start never waits for Windows' audio service, and the DLL's
  imports stay as they were.

What came of it is one line of the in-game log (the period asked, the engine's period before and after, the driver's
default, shortest and longest, in frames and milliseconds) and one line of `openDMT3-sound.txt` beside the DLL, which
the launcher reads into its log when the game ends and keeps with the run: the **Sound** page and `--status` say the
period the last game's sound went in, on the device chosen now. The results: `held`; `none-shorter` (the driver's
shortest is its default); `locked` (another program's stream holds the engine at a period of its own); `refused`;
`unchanged` (the stream ran and the engine kept its period); `no-answer` (numbers outside the API's own rules);
`no-client3` (Windows before 10); `no-device`; `off`.

Under Wine, which has no shared engine, the ALSA driver answers a shortest period of 240 frames at 48 kHz and keeps 480
when a stream asks for 240: `unchanged`, and the stream is let go. Its PulseAudio driver answers a shortest of 0 frames:
`no-answer`. In whole songs on the real client under Wine (the game on the GPU at 60 frames a second, its ALSA driver
through PulseAudio, recorded), Low latency on and off played alike: the stream asked for and let go at the game's
start, no underrun, the songs ending within 1.3 and 8.2 ms of their frames, no silent gap of 5 ms or more in either
(a third run with it on: one of 9.5 ms, where the game's frames stalled).

## The mixer

The **Mixer** on the **Sound** page (`OPENDMT3_SOUND_PATH`) chooses who mixes the game's sounds: Windows' own
DirectSound (`directsound`, the default), or [DSOAL](https://github.com/kcat/dsoal), a DirectSound of its own that plays
each DirectSound buffer as a source of [OpenAL Soft](https://github.com/kcat/openal-soft), which mixes them and writes
the mix to the device through WASAPI: in shared mode (`openal`) or in exclusive mode, the device to itself while the
game runs (`openal-exclusive`).

- **The libraries.** DSOAL as `openDMT3-dsoal.dll` (its `dsound.dll` under another name: Windows' own stays the game's
  import) and OpenAL Soft as `dsoal-aldrv.dll` (the name DSOAL loads it by), beside the DLL, where PLAY puts them
  (`core/cabinet/steps.py`). `openal.c` loads OpenAL Soft by its whole path first, so DSOAL's own load of it by name
  finds it loaded, then calls DSOAL's `DirectSoundCreate8` with the chosen device's GUID (DSOAL opens OpenAL Soft's
  WASAPI device by the same GUID).
- **OpenAL Soft's settings.** `openDMT3-alsoft.ini`, written beside the DLL and named in `ALSOFT_CONF` (read after any
  `alsoft.ini` of the player's own): WASAPI only; updates of 256 frames, two of them (OpenAL Soft's own default is 512
  and three, 32 ms mixed ahead); plain stereo panning with no HRTF or crossfeed (the game's buffers are plain stereo
  and mono); its band-limited `bsinc12` resampler for the game's 44.1 kHz buffers; exclusive mode for
  `openal-exclusive`, where the period is the device's own shortest.
- **The game's buffers.** DSOAL hands OpenAL Soft each buffer's own memory (`AL_EXT_STATIC_BUFFER`), so the music the
  game keeps writing into its song buffer after its one Lock is what plays, as with Windows' DirectSound. Its Stop
  pauses where the buffer is, which the hold's stop, set back and play again rely on. `sound.c` follows DSOAL's
  buffers as it follows Windows' own: the music lock, the hold and its fades are the same code.
- **The way back.** Any step that fails (a library missing or refusing, DSOAL not opening the device: exclusive mode
  not allowed for it, under Wine on both its drivers too) leaves the game on Windows' own DirectSound, opened as it
  would have been, with the sound engine's period asked for as there. A device another program has to itself plays for
  neither. In shared mode the sound engine's period is asked for as above; in exclusive mode the engine is not on the
  way.

The first line of `openDMT3-sound.txt` says which mixer was chosen, which one played, and when OpenAL Soft did not open,
the step that failed with its error; the launcher logs it when the game ends, and the **Sound** page and `--status`
say when DirectSound played in OpenAL Soft's place.

Both libraries are built for 32-bit Windows by `native/openal/build.sh` from pinned source archives (OpenAL Soft's
release 1.25.2, DSOAL's commit e111282 of 2026-10-06: DSOAL makes no releases) with MinGW-w64's GCC 14, their runtimes
linked in, in a container with no network; `openal-NOTICES.txt` beside them holds their licence texts, read from the
archives. They are under the GNU LGPL, so each release carries both archives beside its installer
(`packaging/release.sh`). They are built without libstdc++'s assertions, which both projects turn on by default: with
them, six of six runs of a test program on DSOAL ended in an assertion at their exit (a condition variable whose
waiting thread was already gone), exit code 3, which on Windows is a runtime error box as the game closes; without
them, six of six ended with 0.

Measured under Wine 11.0, the sound on a PulseAudio null sink in the container and recorded from it:

- **From Play to sound.** A buffer made as the game makes them, a 5 ms burst at its start, played every 600 ms by the
  two mixers in turn in one recording: Wine's DirectSound 43.6 to 45.5 ms at the median, DSOAL and OpenAL Soft in
  shared mode 11.6 to 15.5 ms (four recordings of 10 to 15 plays each). These are Wine's numbers: its DirectSound is
  not Windows'.
- **Whole songs**, the game drawn on the GPU at 60 frames a second, the tutorial's song and a song each held once
  under the question, the two mixers side by side at the same time: with OpenAL Soft every one of the game's sounds
  played (1,585 buffers, 1,128 of them copies, 1,768 plays), no underrun, no click at the plays, stops and holds, the
  holds silent and faded back in, and the song ended 13.9 ms from its frames (DirectSound beside it 5.9 ms); silent
  gaps of 5 ms or more in the song, none (DirectSound one of 9.5 ms). On a busier stretch both dropped out where the
  game's frames stalled: OpenAL Soft three times for 15 to 30 ms, DirectSound once for 7 ms.
- **Exclusive mode** is refused by both of Wine's drivers (0x8889000e on PulseAudio, 0x8889000a on ALSA): the game
  plays through DirectSound, and the note says so.

## The launcher

The launcher is `opendmt3/client/`. The window is Tk, drawn by the launcher itself (`theme.py`, `art.py`, `widgets.py`):
no Windows controls, so it looks the same at every scaling. Pages fill the area right of the menu (`client/pages/`);
dialogs are drawn inside the window (`dialogs.py`), over a picture of the window made from its own widgets
(`snapshot.py`).

Slow work runs on worker threads and hands its result back through a queue the window empties every 50 ms, since only
the window's thread may touch Tk. The window draws what changed and no more: a page's header keeps its shards for each
page and size (`art.header_shards`), so the title comes in the same turn as the page; a resize draws the header once
the drag settles, in the guide too; and DISC CHECK's list is drawn once the window's thread is idle, with every change
since in that one drawing, making again only the cards whose path was looked at, became the one in use or got its
jackets. A setting changes the remembered state at once (`state.py`, a JSON file in
`%AppData%\openDMT3`); openDMT3's own folder is made only at PLAY; the client data never changes.

Playing on this PC, `hosting.py` runs the server inside the launcher: the game server and the site on one asyncio loop
in a thread, the site on this PC only unless **Open this PC's server** is on. The launcher signs the player in to its
own site with a one-use link (60 seconds, from this PC only). On another server, `remote.py` speaks the server's API:
sign in once for a token, then the card at every PLAY.

`main.py` starts the window or a job from the command line; `openDMT3-cmd.exe` is the same program built as a console
program, which runs the modules inside `openDMT3.exe` (one copy of them in the folder:
`packaging/windows/console_modules.py`). `remote.py` makes its opener, and loads the system's certificates with it, at
the first call to a server.

Updates go through Velopack (`updates.py`), from the server the launcher plays on when it hands updates out, or from
the address the build was made with, and nothing of a download is in the install folder before its signature is
checked (`core/signing.py`):

1. The feed's names are checked before anything is fetched or deleted: plain file names, the package the one named
   for the version offered, that version newer than the one installed.
2. The launcher fetches the update itself into a folder of its own in the temporary folder: the package with its
   `.sig`; or, when the feed has delta packages from the version installed, each delta with its own `.sig`, checked by
   its bytes before the installed `Update.exe` puts the new package together from them.
3. The package is checked there: by its bytes, or, put together from deltas (it is zipped again, so its bytes are not
   the signed ones), by the files it holds; the version written inside it is the one offered. A package from deltas
   that is not the signed one is dropped and the whole package fetched instead, which `updating.py` says in the
   dialog.
4. Only then it is moved into `packages\`, the installed `Update.exe` is replaced by the one the package carries, and
   Velopack is told to put the package in once the launcher has ended.

Velopack's own download is never used: it writes into `packages\` under the names the feed gives, and puts the
downloaded package's `Update.exe` over the installed one before any check.

## The server

`server/__main__.py` runs both halves in one process and one asyncio loop: the game server on TCP 4725 and uvicorn on
4730. The loop only reads and sends: every query of the game server runs on its own database thread, in the order
asked, and every query, page and answer of the site on Starlette's worker threads (see Performance below). The game
server's protocol is in [protocol.md](protocol.md). In short:

1. The server sends a seed; the client answers; the link is online (the game's NET light turns green).
2. Keep-alives both ways, every 10 to 11 seconds.
3. A card in the reader: the player's details, then the login result.
4. At the end of a session, the stages the player cleared (song, pattern, score), kept with the 47 bytes as they came.

Each message has the size the client registered for it (`messages.py`), and the server answers only with values seen
working on the game's screen. A message of an unknown kind is logged once by name.

The site (`server/web/app.py`) renders Jinja templates in English or Korean, and every page and action has an API twin
([api.md](api.md); `tests/server/test_api.py` checks the guide against the routes). Sign-ins are signed cookies, the
launcher's are signed tokens, both with `data/web.secret`.

## The database

`server/db/__init__.py` holds the steps as SQL; `PRAGMA user_version` counts the steps run. An older database is copied,
then brought up to date, each step under the write lock with the version read again under it (the site's threads may
open the same older file at once); a newer one is refused and left alone. The tables: accounts, cabinets, the change
log, plays, play sessions (a card login to the end of the link or the next login), the API's tokens ended before their
time (each by a hash of it, kept until the token would have expired), and the API's named tokens (each by a hash of
it, with its name, scope and when it was made and last used).

Step 8 indexes what grows with the history: each chart's plays from its best down (`plays_by_chart`: mode, song,
pattern, score descending, time, id), a cabinet's sessions and a session's plays. The site and the game server reach
the file through connections of their own (the game server one for good, the site one a request), in write-ahead log
mode, so readers never wait for a writer. A write waits up to 15 seconds for another connection's (`db.BUSY_SECONDS`).
What reads then writes takes the write lock first (`db.immediate`: a new account after the check that its ID is free,
a new token after the count of the account's tokens, the game server's every write), so two at once never break the
database's own rules or count past a limit.

## Performance

The game server and the site share one process and one event loop, and the loop only reads and sends:

- **The game server's database thread** runs every write of the game server, one at a time in the order asked, and two
  **reading threads** beside it, each on a connection of its own, read a card login's account, records and DJ card (a
  long history's records, 45 ms for the busiest player of 300,000 plays, hold up no other cabinet's results or login);
  the writer then looks at the account again, sends the first places and starts the session, and a login whose account
  changed in between is looked up again on the writer alone. A restore or a reset of plays holds both.
  - Each chart's first place comes from memory (`services/firsts.py`: built from `plays_by_chart` in 30 to 35 ms
    whatever the history's length, followed play by play, built again only when another connection committed).
  - A link's handlers that wait for the database run one after another apart from its reading, so its keep-alives are
    answered meanwhile; past 16 waiting, its reading waits for them.
  - Writes are transactions taken with `BEGIN IMMEDIATE` and tried again while another program holds the database.
- **A login's answer** (on a long history 3,800 messages: the player's records and every chart's first place) is
  encrypted on a worker thread in one pass (`crypto.encrypt_many`: TEA over every block at once, each word in a lane
  of one large integer; 21 ms where one message at a time took 153 to 185 ms on the loop), the result first. It goes
  out before the link's next answer is made: a client that leaves it unread for 15 seconds is dropped at once, what
  was not sent thrown away, so no answers pile up for it.
- **The site's two worker threads** run every page and API answer, one connection to the database a request. Two,
  because the interpreter runs one thread's Python at a time and a query hands it over and back for every row: with
  more, threads mostly wait for one another and for the loop (20 visitors that never paused beside 64 cabinets: logins
  answered in 99 ms at the median with 2 threads, 253 with 3, 1,017 with 4).
  - The lists made from everyone's plays (rankings, months, songs, a song's boards, the totals behind the places,
    Home's newest plays and records, a DJ's page, every player's card) are kept until the plays change
    (`web/cache.py`: under the newest play's number and a count of the changes made to players and plays; a DJ's
    page under that player's own newest play), one per name, made once for every request asking at the same moment,
    at most 5 minutes old.
- **Pictures**: the client data's jackets and DJ card pictures, and a song list's taken in, are decoded, made smaller
  and encoded on up to 8 threads (Pillow does that without the interpreter's lock) while the next ones are read, never
  more than the cores the process may use (those it is allowed on, within a container's processor quota), each handed
  back in its place: the same files byte for byte as one after another.
- **Long work** (a password's check, a song list read or taken, a backup made, put back or checked, a reset of plays,
  the look through the server PC) runs on 3 threads of its own, so the site's two never wait behind it. Backups made,
  kept from an upload, put back or deleted change their folder one at a time, so two in the same second never take
  the same name.
- **Fair shares**: a caller (a sign-in or a token) has one request answered at a time and 30 seconds of processor time
  a minute, an address 8 and 90 ([server.md](server.md#many-players-at-once)); what a request used is counted on its
  threads (`web/work.py`), not the time it waited.

Measured on made-up histories of 300,000 and 1,000,000 plays (1,000 and 2,000 players, the songs by popularity),
before that work and after it, the median of three runs or more on a busy PC (32 cores):

| | 300,000 plays, before | after | 1,000,000 plays, before | after |
|---|---|---|---|---|
| The event loop held by one card login | 820 ms | 14 ms | 2,059 ms | 14 ms |
| 8 cabinets, a keep-alive's answer: p95 (the longest) | 594 ms (1,037) | 0.7 ms (71) | 1,641 ms (2,032) | 0.8 ms (83) |
| 64 cabinets, a keep-alive's answer: p50 / p95 | 466 / 1,238 ms | 1.1 / 3.1 ms |  |  |
| 64 cabinets and 20 visitors that never pause, 3 minutes: a keep-alive p50, a login p50, a page p50 / p95 (pages answered) | 7,802, 6,363, 7,714 / 10,816 ms (500) | 6.8, 136, 235 / 745 ms (12,103) |  |  |
| 20 visitors at once, p95: Home / the rankings / the busiest DJ / the most played song | 1,758 / 1,412 / 6,654 / 1,688 ms | 95 / 70 / 150 / 546 ms |  |  |
| The admin's Cabinets page, one request | 541 ms | 72 ms | 2,027 ms | 229 ms |
| A song list taken (925 pictures) | 2.19 s | 0.57 s |  |  |
| A song list read from the client data (927 files; in the server's image) | 8.75 s (9.67 s) | 7.04 s (7.42 s) |  |  |
| The server image's imports | 286 ms | 230 ms |  |  |

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="images/chart-server-dark.svg">
    <img alt="64 cabinets and 20 visitors that never pause, for three minutes, on a history of 300,000 plays, before and after the server's work: a cabinet's keep-alive, median, 7,802 milliseconds before and 6.8 after; a card login, median, 6,363 before and 136 after; a page of the site, median, 7,714 before and 235 after; a page of the site, 95th percentile, 10,816 before and 745 after. Pages answered in the three minutes: 500 before, 12,103 after. The server held 91 MB of memory" src="images/chart-server-light.svg" width="100%">
  </picture>
</p>

## Security

- **Passwords** are kept as PBKDF2-SHA256 of the MD5 the game sends at its keypad, so the site and the game check the
  same secret. Each check runs on a worker thread, two at a time, so the game's cabinets on the same event loop never
  wait for one. Wrong passwords are slowed down per address (an IPv6 /64 counts as one) and per ID (never for the
  server PC itself), and one address has at most 20 sign-ins a minute; an unknown ID costs a check too. A new
  password has 6 to 16 letters and digits.
- **Card numbers** log a player in by themselves: only their owner sees them, and a new password makes a new one.
  The admin's log keeps no bytes of a login message.
- **Sign-ins** end when the password changes, and on the site's sign-out (that account's, in every browser; the
  launcher's tokens stay). A launcher's sign-out ends its own token and no other. Every form, the sign-in's
  included, carries a token of the site's own. The first owner's page answers only visits from the server PC,
  once. After a sign-in, the site goes only to its own pages.
- **Named API tokens** are kept as their SHA-256 only, end when revoked or with a new password, and stop while their
  account is disabled; a read-only one makes `GET` calls only, none of an admin's.
- **Uploads**: a request body past 64 KB is refused before it is read. An admin's backup upload is the one exception:
  written into `data/backups/` as it comes, up to 256 MB, and checked before it is kept (an SQLite file opened
  read-only with its schema not trusted, its integrity check, this project's tables, a version this server opens).
- **Other players** are named by their account number and DJ name; cabinets' addresses and login IDs are for admins.
- **Behind a proxy**, forwarded headers count only from the addresses given to `--proxy`, and a request carrying one
  is never a visit from the server PC. `--web-host` keeps the site on the server PC while the game's port is open.
- **The game's port**: one address holds at most 16 links and sends at most 64 KB a minute over all of them; a link
  has 10 seconds to answer the handshake, and one that leaves what is sent unread for 15 seconds is dropped with it.
  Results are kept only for the client's own modes, patterns and songs, 8 stages a card login at most. Refusals are
  logged once a minute per address.
- **Fair shares of the site**: a caller (a sign-in or an API token) has 1 request answered at once and 30 seconds of
  the server's processor time a minute, an address 8 and 90; up to 32 more of each wait their turn without holding a
  thread, and past that or past the seconds a request is answered 429 with Retry-After before anything is read for it
  ([server.md](server.md#many-players-at-once) has the whole table).
- **Files**: the database, its backups (and the copy kept before an upgrade) and the secret are made readable by their
  owner only.

## The build

`packaging/windows/build.sh` builds on Linux, in Docker: PyInstaller under Wine for the launcher, the console copy and
the installer, and Velopack's `vpk` for the packages. Each build image carries a hash of its recipe and is made again
when the recipe changes. Both recipes leave out what the launcher never uses (`packaging/windows/launcher_parts.py`:
Pillow's AVIF and WebP codecs and colour management, Tcl's time zones, message catalogs and other systems' character
sets), the folder holds one set of fonts and one archive of the Python modules, and the previous release's whole
package, kept beside the new one, gives a delta package (`packaging/windows/previous.py`). `packaging/docker/` is the
server's image, and `compose.yaml` at the top runs it. Nothing in either comes from the game.