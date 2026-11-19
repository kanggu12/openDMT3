# Changelog

What changed in each release of openDMT3. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/): a release with a new feature raises the minor number,
one of fixes, changes and smaller additions raises the patch number. Each release's section here is its release notes.

## [Unreleased]

## [0.4.0] - 2026-11-17

The admin pages on a site of their own with a page for each player, a master volume and an equalizer in the launcher
and in the game, new ways to run a server, and TECHNIKA 3's look for the launcher and both sites.

### Added

- A master volume and a five-band equalizer on the launcher's **Sound** page, and every volume and band in the game
  (**SOUND** in the in-game menu), kept in one file: a change made in either shows in the other.
- A connection test of another server, step by step, on **Online** and as `openDMT3-cmd.exe --test-server [URL]`.
- Outside a song, a tap on the in-game overlay's handle, or a press held on it, brings the overlay bar.
- When the in-game menu, the question or the sound panel closes during a song, 3, 2, 1 in the middle of the screen
  before the song goes on.
- On the players' site, a picture of the player's own, a preview of the DJ card drawn as the game draws it, and
  **Remember my ID on this browser** at the sign-in.
- A page for each player on the admin pages, where every change to them is made: MAX points, the level the game
  shows, a ban with its reason (the game refuses the card, the site and the launcher say why), the DJ card, the
  picture, a new password and the list of changes made. The server keeps the MAX points a session earns.
- On the admin pages: the machine's CPU, memory and disk over the last day and when players play (**Status**), the
  site's requests (**Logs**), each player's last 14 days (**Players**) and the launchers signed in (**Connected**).
- A **Server** tab that restarts, stops or removes the server by asking what started it, or names the commands; an
  invite with a QR code on **Players** and from `./dmt3 invite`. Every admin page and control has its API call.
- A Windows server package and a one-line install for Linux and macOS, both without Docker and with the
  `opendmt3-server` command; the server's image for amd64 and arm64 at `ghcr.io/kanggu12/opendmt3-server`, which
  `./dmt3` now runs; and a Helm chart.
- The site over HTTPS through Caddy, which gets its certificate itself: `./dmt3 expose NAME`, `opendmt3-server expose`.
- `./dmt3 ports`, `repair` and `remove`, and guides for the internet, a closed network, Kubernetes and server questions.

### Changed

- The admin pages are a site of their own with a sign-in for admins alone, opening at **Status**; the players' site
  has no admin menu. The launcher's own server has an admin site too, opened signed in by **Online**, **Admin pages**.
- The launcher's menu is a column down the window's left, with **PLAY** at its foot.
- The launcher's forms follow the site's design, and its sign-in on another server works as the site's, with
  **Remember my ID on this PC**, one sentence for a wrong ID or password, and a banned account's reason.
- The launcher and both sites take on TECHNIKA 3's look: a stage behind each page's head, the cabinet's lamps, the
  game's score colour, gold and silver places, and the DJ card as a member's platinum card.
- Fewer words: no cards of instructions on the launcher's **Play** and **Controls** or on the site's pages, and the
  settings' hints say one fact each.
- Running the installer again over the same version offers **Uninstall** beside **Repair**.
- The release's files are named for what each holds and where it runs: `opendmt3-server-0.4.0-linux-macos.zip`
  (0.3.1: `opendmt3-server-0.3.1.zip`), `opendmt3-0.4.0-sha256sums.txt` (`opendmt3-0.3.1-checksums.txt`) and
  `opendmt3-launcher-0.4.0-openal-sources.zip` (`opendmt3-launcher-0.3.1-lgpl-sources.zip`).
- Backups, the CSV files and the song list are named in lowercase with the tool, what they are and their date:
  `opendmt3-backup-<date>-<time>-<kind>.sqlite`, `opendmt3-plays-<date>.csv`, `opendmt3-song-list.zip`.
- **Rankings** light each mode's key in its own colour (STAR's lime, POP's pink) and one's own row in openDMT3's blue.
- The in-game menu's rows and the sound panel's sliders are a finger's size: a tap above or below a knob moves it one
  step, a drag moves it from where it was, and a column's value or name only chooses it. **SOUND** shows it opens a
  panel, whose title goes back to the menu, and the panel uses the launcher's words (**MASTER**, **MUSIC**, **KEYS**).
- The overlay bar's X is quiet like the buttons beside it, and the overlay shrinks with the game in a small window.
- The launcher's and the installer's dialogs follow one rule: the main key is blue and says what it does, a question
  that changes or removes something starts on **Cancel**, pink is only for what failed, and the tab names the state
  (**Older version**, **Game open**, **Not installed**, **Done**). **Uninstall** asks **Remove** (settings, players and
  records stay) or **Remove all**; work under way, an unpacking or an uninstall included, is blue with moving stripes.
- The ready check, the **NET** lamp and **PLAY** follow what the launcher last learned: another server that did not
  answer, another server not chosen yet (**Connect** in place of **Sign in**), or a players' database that cannot be
  opened stop **PLAY** and say so; on **PLAY** the foot points at the check's line instead of repeating it.
- The settings' controls start on one line across **Screen**, **Sound**, **Controls** and **Game**, and across
  **Launcher** and **Help**; **Help**'s lines lead to the setting they name.
- After **Repair** puts back the launcher's own files, its one key starts the launcher again.
- In a tall window, **Last game** lists up to six cleared stages.
- The launcher's report is named in lowercase too: `opendmt3-report-<date>.zip`.

### Fixed

- **Copy** works over plain http on the network too (the API token shown once, the message to send a player), where
  the browser gives a page no clipboard.
- On a phone a date no longer breaks from its time, nor a figure from its unit.
- **Status** counts every account, as the Players list does, and says how many of them are disabled.
- After an account is made, the Players page's form is empty again.
- **Disc check** no longer offers openDMT3's own downloads (the launcher's portable zip, the server's packages, the
  OpenAL sources) as client data, whatever they are called: they are told by what they hold.
- **Who plays**'s list stays inside its card, and every drop-down's list is whole on the screen; the fifth upscale
  filter fits the smallest window; Tab scrolls the page to the control it reaches; the menu column no longer moves
  when the status line grows, which keeps to three lines.
- Korean lines no longer break inside a phrase, and a long folder path breaks after a separator, never inside a name.
- A dialog with a text box shows one keyboard mark: no ring on a key while the box has the keyboard.
- The installer's known failures (no room, no access, a missing file) are said in the person's language, and its
  window after a crash says **SETUP**.
- A small archive's progress no longer reads "1 MB of 1 MB" while it is under way.
- The launcher takes an `https://` address without a port as port 443, as a browser does.
- **QUIT THE GAME** in the game ends it within about a second, silent (a song held still) and the overlay bar saying
  the game is ending; it took 10 seconds, with the song playing on.
- A double-click on the in-game menu's **SOUND** no longer changes a value, and the wheel moves a sound value one step
  a notch with a touchpad too; under an open in-game panel the wheel and the right and middle buttons no longer reach
  the game.
- Two starts of this PC's server at once (**Open my records** and PLAY) no longer leave a second server holding the
  game's port.
- **Remove all** deletes openDMT3's own folder for playing too: the client copy PLAY made, its card and its settings.
- A power cut right after a save no longer leaves the launcher's settings empty, and the command line works past a
  `launcher.json` it cannot read.

### Security

- No page of either site can be shown inside another site's frame.
- Wrong passwords hold back an ID at the address they came from, and the whole address only after 30, so the other
  players behind one address (a game centre's) go on signing in; in 0.3.1 five held back all of them.

### Upgrading from 0.3.1

- The admin pages leave the site's port for `http://127.0.0.1:4731/`, on the server PC alone. To open them to the
  network: `./dmt3 setup --admin-network yes` (Docker) or `--admin-host 0.0.0.0` (Python); to the internet:
  `./dmt3 expose NAME --admin-public`, at `https://NAME:4731/`. `--admin-on-site-port` keeps them on the site's port
  too, at `/admin/`.
- Old `/admin` bookmarks on the site's port go on to the admin site from wherever it can be reached.
- Backups made before keep their names (`openDMT3-<date>-<time>-<kind>.sqlite`) and stay listed, restorable and
  deletable; a song list saved as `openDMT3-song-list.zip` is read as before.
- Players and launchers stay signed in. Admins sign in again on the admin site, which keeps its own sign-in; signing
  out on either site ends the account's sign-ins on both.
- The server upgrades its database on its first start, after keeping a copy beside it
  (`openDMT3.sqlite.v8-<date>-<time>.bak`). 0.3.1 refuses the upgraded database: that copy is the way back.
- **Music** sounds as before at the same value, on the game's own curve, which the in-game panel follows.
  **Keys** (the key sounds) start at 100 %, as loud as before: the game never applied its key sounds' setting.
- The admin pages take TCP 4731 (`--admin-port`, `./dmt3 ports --admin`). With Docker, when the site or the game
  already has 4731, the first `./dmt3 up` gives the admin pages the next free port and says so.

## [0.3.1] - 2026-11-17

### Added

- The server has a download of its own, `opendmt3-server-0.3.1.zip`: what a server needs to run with Docker Compose
  (`./dmt3 setup`) or with Python, with its guides, and none of the launcher's parts or the tests. Unpacked, it runs
  as a clone of the repository does.
- The release notes start with a table of the release's files: what each is and who it is for, with
  `opendmt3-0.3.1-checksums.txt` holding the SHA-256 of every file.

### Changed

- The release's files say which part they are and of which version, in lowercase:
  `opendmt3-launcher-0.3.1-windows-x64-setup.exe` is the launcher's installer, and the source archives of the two LGPL
  libraries the launcher brings are one `opendmt3-launcher-0.3.1-lgpl-sources.zip`, no longer two files beside the
  installer. The launcher's update files keep their names, which every installed launcher reads, and `RELEASES`,
  a feed file no launcher of openDMT3's reads, is no longer published.
- A server hands out its installer under the release's name with its own address after it
  (`opendmt3-launcher-0.3.1-windows-x64-setup-dmt.example.org-443.exe`), and takes an installer put in its downloads
  folder under the release's name as it is: of the installers there, the newest version is handed out. One put there
  by an earlier setup keeps being handed out.
- The launcher's and the installer's messages name the openDMT3 installer, not a file name of one release.
- The notice on the launcher's **Launcher** page, the site's footer and the README says: openDMT3 contains no game
  data, and if the copyright holder requests it, this project may be made private or shut down.

## [0.3.0] - 2026-11-13

### Added

- Every finger on a touch screen plays, as on the cabinet: openDMT3's own touch screen library takes the place of the
  cabinet's in openDMT3's copy of the client, so the game reads each finger on its window, and the mouse as one point,
  where it read one point from the mouse before. A long note held with one finger stays held while others tap, a
  finger down as another comes up is a press, and a touch on the overlay bar or its panels never reaches the game.
  Tried with made-up touches under Wine; a real touch screen has yet to try it.

### Changed

- The methods openDMT3 puts in Direct3D's tables are looked at every frame and put back if Direct3D fills a table in
  again, as it was seen to do in another build of the game, so the frames stay paced and the picture's passes stay on.
- The launcher is laid out as OpenDMTQ's PC client and openDMT3's own site are: the pages' names in a bar across the
  top, in English in both languages and reached by the keyboard, each page's title scrolling with its parts on cards
  with a cut corner, **Check again** at the ready check's title, and a page's main button quiet beside a lit **PLAY**.
  The first-start guide's steps stand across the top, with **Skip**, **Back**, **Next** and the last step's **PLAY** at
  its foot.
- The overlay bar slides down out of the game's top edge and back up into it, in about a fifth of a second, as
  OpenDMTQ's does, turned back from where it is when the pointer comes back and at once with Windows' animation
  effects off; the menu and the quit question come out from under it as sheets hanging from its foot, and the notice
  and an FPS counter in a top corner move down with it. A handle at the game's top centre shows where it comes from.
- The FPS counter is one line, at the bottom right beside the game's FREE PLAY, below the notes (where it was, half
  of a note at the right end of the lowest row came under it), and its words read on the game's brightest screens.
  The quit question's QUIT THE GAME is quiet until the pointer or the keys are on it, and a notice that comes during
  a song waits for the song's end, so nothing of the overlay covers the groove meter while you play.
- Words as the menu and the guides say them: a page by the menu's name (the ONLINE page), **Last game**,
  **FPS counter**, the overlay bar and its handle, **Open my records**, **Open on the site**, the site's address.

### Fixed

- A cabinet's client of the China region is told apart, and said not to work here: the launcher took it for a modified
  PC client and made it ready, and the game then stopped at the cabinet's USB lock.

## [0.2.0] - 2026-11-13

### Added

- **Low latency** on the Sound page, on by default: while the game runs, Windows mixes the sound of the game's output
  device in the shortest steps its driver allows (2.7 ms with Windows' own audio driver, where 10 ms is usual), and
  the page and `--status` say the steps the last game's sound went in.
- **Mixer** on the Sound page: the game's sounds mixed by Windows' DirectSound (the default), or by OpenAL Soft through
  DSOAL, sharing the device or with it to itself (**Exclusive**); when OpenAL Soft cannot open the device, the game plays
  through DirectSound and the page says so. Each release carries the two libraries' source archives.
- **Drawn at** on the Screen page: **Screen size** has the game draw its picture at its size on the screen (1800x1080
  on a 1920x1080 screen, 3600x2160 at 3840x2160) rather than at its own 1280x768 enlarged after, so what moves,
  scales or turns lands on the screen's own pixels. The game is answered its own sizes wherever it asks, and its
  videos are drawn to the larger picture with the rest. **1280×768** stays the default; `--set render_size=display`.
- **Anime4K** among the Screen page's upscale filters: the small model of Anime4K's CNN x2, a neural network made for
  drawn art, doubles the game's picture, which is then fitted to the window. `--set upscale=anime4k`.
- An audio offset on the Sound page (0 to 500 ms, `--set audio_offset=`), for a sound device that plays late such as
  Bluetooth headphones: with the frames locked to the music, a song's notes and their judging are held that much
  behind its music.
- Motion clarity on the Screen page, an experiment off by default, offered on a display at a whole multiple of 60 Hz
  from 120 up: each frame shown over its refreshes as a CRT's rolling beam (from the Blur Busters CRT beam simulator)
  or with black frames between, for moving notes that smear less (`--set motion_clarity=`).
- The flip model in the Screen page's Advanced, an experiment off by default: in a borderless full screen, the game's
  frames handed to Windows by Direct3D 9Ex's flip swap chain instead of copied, the way to Windows' independent flip
  and a display's variable refresh rate (`--set flip_model=`).

### Changed

- With the frames locked to the music or even, each frame starts just in time for its turn instead of right after
  the frame before, so the touch it carries is read later and shows sooner.

### Fixed

- A switch between full screen and a window during a song, or any other reset of the game's graphics device, no
  longer moves the music lock's target: the lock keeps the song's start through it, and wins the pause back as it
  does any stall.
- Locked to the music on a 60 Hz display with VSync on, a song's notes catch up with its music after a stall, such
  as the game's own load or a busy PC, and after a frame that missed its refresh: a frame is left unshown now and then,
  at most one in six, until the notes are within a frame of the music. Before, such a display could not show frames
  sooner, and each stall or missed refresh left the notes that much further behind the music for the rest of the
  song; at 59.94 Hz they also fell a millisecond a second further behind. On a 50 Hz display, where the game's 60
  frames a second do not fit, the notes now keep up with the music instead of falling further behind every second.

## [0.1.1] - 2026-11-13

### Added

- The README and the guides in pictures: the game with openDMT3's parts over it, the server and its clients, the
  ways to play and to run a server, the first start in three steps, and charts of what was measured.
- Playing on Linux: the player's guide says how the launcher runs under Wine, with the steps the project's own tests
  take and what has not been tried.

### Changed

- What you bring to play is called the client data: the game's PC client and its files, in a folder or in an
  archive. The launcher, the site, the setup wizard and the guides say so in English and Korean, and each card on
  DISC CHECK says whether it is client data in a folder or in an archive.
- The README and the guides have one path for playing and one for running a server, each complete on its own: the
  player's guide from the installer to PLAY, and the server guide with a server in the launcher, with Docker or with
  Python, and how to update it. The client data guide says which client data plays, with what its card says.

## [0.1.0] - 2026-11-13

### Added

- A launcher for Windows 10 and 11 that plays your own DJMAX TECHNIKA 3 game folder as it is, with a mouse or a
  touch screen: it finds the folder, or an archive holding it, says what each one is, unpacks an archive with 7-Zip,
  and only reads the folder.
- A card reader of its own in place of the cabinet's, which logs the player in. In the game, a bar and a menu at the
  top in the game's own look, the picture's shape and filters (FSR 1, NIS, FXAA, SMAA), frames paced to the music,
  and the sound held while the menu is open.
- A game server of its own for card logins, records, MY RECORD and BEST RECORD, DJ cards and rankings, with the song
  list taken from your own game files. The launcher runs one on the same PC; on a server PC it runs with Docker
  Compose (`./dmt3`, with a setup wizard) or with Python.
- A site for the players (rankings, songs, DJ pages) and admin pages, with an API for everything they do.
- Updates inside the launcher, signed by the project, and an installer with repair and removal, in English and
  Korean.

[Unreleased]: https://github.com/kanggu12/openDMT3/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/kanggu12/openDMT3/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/kanggu12/openDMT3/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/kanggu12/openDMT3/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/kanggu12/openDMT3/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/kanggu12/openDMT3/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/kanggu12/openDMT3/releases/tag/v0.1.0
