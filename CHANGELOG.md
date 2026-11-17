# Changelog

What changed in each release of openDMT3. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/): a release with a new feature raises the minor number,
one of fixes, changes and smaller additions raises the patch number. Each release's section here is its release notes.

## [Unreleased]

### Added

- The admin pages are a site of their own, apart from the players' site: on the server PC at
  `http://127.0.0.1:4731/` (`--admin-port`, `--admin-host`, `--admin-on-site-port`), with their own sign-in for admins
  only, their own cookies, the first run, and a frame of their own, the server's control room: the family's mark with
  ADMIN, the pages as the game's leaning keys, and a rail of the server's state on every page. The players' site has
  no admin menu any more; its footer leads an admin there where the admin pages are within reach, and their old
  addresses there go on to them from the server PC. The API answers on both ports.
- **Connected** on the admin pages: the launchers on the server beside its cabinets (whose, from which PC, which
  version, when last heard), and `GET /api/v1/launchers`.
- The site's forms in one design: labels above their fields, hints and mistakes under them, Show inside a password,
  the site's own lists and ticks; the sign-in page as the site's front door, with Remember my ID on this browser.
- Toasts in the bar's place for what a change did, over a dialog too, and for a long job that ended elsewhere; on a
  phone the bar is one row with **MENU**.

- The Windows server package, `opendmt3-server-<version>-windows-x64.zip`: the server on a Windows PC of its own,
  without Docker, Python or the launcher, with the launcher's installer of the same release to hand out, start and
  stop from any window, a firewall helper, repair and removal.
- A one-line install for Linux and macOS without Docker (`opendmt3-server-<version>-linux-installer.sh` and
  `-macos-installer.sh`), and the same server command line there.
- The server's image for amd64 and arm64 on `ghcr.io/kanggu12/opendmt3-server`, which `./dmt3` runs by default
  (`--build` for a copy's own), and a Helm chart, `opendmt3-<version>-helm-chart.tgz`.
- `./dmt3 expose NAME`: the site over HTTPS with Caddy and a certificate it gets by itself, from Let's Encrypt, its
  staging authority, your own ACME authority or Caddy's own on a closed network.
- The invite: the players' address with a QR code on **Admin**, **Players**, in `GET /api/v1/server/invite`, and from
  `./dmt3 invite`.
- `./dmt3 ports`: the game's port and the site's set once, which every part then uses; `./dmt3 repair` and
  `./dmt3 remove [--delete-data]`.
- The server says where it is once it is up, with a logo and its addresses in a box.
- Guides for the internet, a closed network, Kubernetes, and server questions.
- The admin pages show the server's use: on **Status** the machine's CPU, memory and disk over the last day, what
  takes the data folder's disk and the hours of the week players play; **Logs**, **Requests**, every page and API call
  with a chart of the last day, a filter and a CSV file; on **Players** each player's last 14 days, sorting by any
  column and a CSV file (`/admin/players.csv`, `GET /api/v1/players.csv`). The song list's import and a restore run as
  jobs whose progress the page shows (`GET /api/v1/jobs`).
- A **Server** tab restarts, stops and removes the server by asking whoever started it: the server's own command and
  `opendmt3-server` do it themselves, and under Docker Compose or the launcher the tab names the commands. The API has
  `POST /api/v1/server/stop`, `/restart` and `/remove`, and `opendmt3-server restart` runs the server again where it
  ran. [docs/admin.md](docs/admin.md) describes every admin tab.
- A page of each player for admins, linked from **Players**: MAX points (set, added to, taken from, for one player or
  many, or unlimited), the level the game shows, a ban with its reason (the game refuses the card, the site and the
  launcher the sign-in and say why), the DJ card, the picture, a new password, and every change made to them. The game
  keeps the MAX points a session earns.
- The account page is one area in three parts: the profile (a picture of the player's own and the DJ card with a
  preview drawn as the game draws it), the account, and its security. Each control has its API call.
- A connection test of another server, on **Online** (and the first-start guide's LOG IN on another server) and as
  `openDMT3-cmd.exe --test-server [URL]`: the address and its name, the site and its openDMT3 version, the game's port
  and the sign-in, one step after another, each with its outcome and its time, and for the first that fails what to
  do; **Test again** and **Copy the result**. The command line's exit code says the step that failed.
- A master volume and a five-band equalizer (60 Hz to 12 kHz, -12 to 12 dB) on the launcher's **Sound** page, and the
  same in the game: **SOUND** in the in-game menu opens a panel under the overlay bar's X with the three volumes and the
  five bands, set by a press, a drag, the wheel or the arrow keys (a song is held still while it is open). Both keep
  the values in `sound.ini` beside the launcher's settings, each writing only what it changed, so a change made in the
  game is on the page afterwards and one made on the page while the game runs is heard at once. The master and the
  equalizer act on the whole mix with every **Mixer**, add no delay, and take the curve's highest point off so a raised
  band never makes the game louder than it was. The music's and the key sounds' volumes a player had set stay as loud.
- A tap on the overlay's handle at the game's top centre, or a press held on it half a second, brings the overlay bar,
  as a finger drawn down from the top edge does; while a song plays the press stays the game's.

- The admin pages as a site of their own, on the distribution's side: `compose.yaml` publishes their port (4731,
  `ADMIN_PORT` in `.env`) on this PC alone unless `./dmt3 setup --admin-network yes` opens it to the network
  (`ADMIN_BIND`; the wizard asks); `./dmt3 ports --admin`; `./dmt3 status`, `up` and `check` say where they are;
  `./dmt3 expose NAME --admin-public` puts them at `https://NAME:4731/` through Caddy (an address too), and without it
  nothing of them is on the internet. The Helm chart gives them a Service of their own inside the cluster
  (`kubectl port-forward`), or the site's port with `admin.onPublicPort`. The server's own program keeps their port
  and reach (`setup --admin-port`, `--admin-host`), the Windows firewall leaves their port closed until they are
  opened to the network (then it asks, as for the others), and `setup` makes the owner's account in the terminal
  when there is none, so a PC with no screen needs no browser. `.env` says what each of its lines is.
- `opendmt3-server expose NAME --admin-public` (the Windows package, the one-line install, Python) puts the admin
  pages at `https://NAME:4731/` through the Caddy beside the server, as `./dmt3 expose --admin-public` does: Caddy's
  HTTPS on their port, the admin pages behind it on the PC alone at the next one (4732), Windows asking to open that
  port; without it nothing of them is behind Caddy. Its `status`, `start`'s banner, `run` and `repair` name the admin
  pages' port too, and a port moved with `setup` while the site is behind Caddy moves in Caddy's settings.

### Changed

- TECHNIKA 3's and the Platinum Crew site's details on the launcher and both sites: one stage composition behind every
  page head (mostly charcoal, the section's colour in four pieces, a spotlight from above) with the section's thin tube
  line under it; the cabinet's lamps, lit from below with nothing round them, and its NET and ID CARD lamps with their
  words at the launcher's foot and in the admin pages' rail; scores in the game's score colour and heavy figures; the
  first place gold and the second and third silver; the DJ card as the member's platinum card, with one silver shine
  after a sign-in or a saved card; the sign-in card's name on the login page's hanging tab; steel chrome titles; opaque
  reading cards and frosted floats (the bar, toasts, the phone's menu, open lists, notices on one sheet).
- Fewer words that only said again what a screen shows: no line under the launcher's page titles but PLAY's and
  RECORDS' "On ...", no hint that only names its row, no welcome formula in the first-start guide, the installer's
  "This takes a few seconds." gone; the site's "openDMT3 · ..." label over its titles gone; card names of two words.
- The admin pages open at **Status**; the Players list is for looking and every change to a player is on their own
  page. Pages that work rather than show have a low head; the phone's heroes are low.
- A card's cut corner is one seam drawn by the card's own shape, along the top, down the cut and round the rest, on
  every part with that corner (cards, the podium's plates, dialogs, a player's picture).
- A date never breaks inside itself on a page, and a date's figure has a row of its own on a phone.
- No how-to blocks on the site's pages (the Download page is the key and its facts; the guides keep the steps).
- The requests log shows 50 requests a page; `GET /api/v1/log/requests` takes `?per=` and `?page=`.
- Motion clarity is offered from a screen's highest refresh rate at its size: on Windows 11's dynamic refresh rate,
  which gives programs 60 Hz while the monitor runs faster, the row no longer hides, and its hint says what to change
  in Windows' display settings. The in-game log names each screen's rate now, its highest and whether it is dynamic.
- The launcher's menu moves to a column down the window's left, as OpenDMTQ's launcher has it now: openDMT3's lockup
  at its top (OPEN and its slab over DMT3, the version over LAUNCHER right beside DMT3, as the site's bar sets DMT3
  SERVER), the pages' names one under another (the page on show on a raised slab with a rule in its section's
  colour), and at its foot the status line, **Save a report** and **PLAY** as wide as the column. The first-start
  guide's steps stand down the same column, with **Skip**, **Back** and **Next** (and the last step's **PLAY**) at its
  foot. The names stand closer in a short window, and a card's buttons go on a second row where the page beside the
  column has no room for them in one.
- A card's top-right corner is a real cut: its seam runs from the top edge along the diagonal to the right edge, the
  page showing past it; dialogs and the menu's lit slab are cut the same way.
- This PC's server (the launcher's own) has the admin site of its own, as every server now does: on this PC's own
  address only (`http://127.0.0.1:4731/`, or the next free port). **Online**, **Admin pages** on the Players card, and
  `openDMT3-cmd --admin`, open it signed in as the server's admin with a link that works once. While it has no admin,
  the first player made on this PC becomes it the first time they open, and the launcher says so once ("NOVA is now
  this server's admin.") and writes it in its log.
- The installer's windows and the launcher's own (getting ready, cannot start, stopped) wear the product's header in
  place of Windows' caption: the lockup with SETUP or LAUNCHER, a minimize and a close key, the window moved by its
  header; the taskbar button, Alt+Tab and minimizing from the taskbar stay as they were.
- A choice that brings or takes rows (a window's size, the FPS counter's corner, the upscale filter, the sound device)
  makes its own card again and no other, in place: the page no longer flickers or jumps, and the keyboard stays where
  it was. The drop-downs are the launcher's own: a field with a chevron that opens its list under it (above it near
  the screen's foot), with the chosen one marked in its page's colour, the arrow keys, Enter, Esc and the wheel.
- The launcher's forms are one design with the site's (fields sunk into their cards, names over them, what each
  takes or what is wrong under it, **Show** inside a password's field, the keyboard's cyan ring, a key's moving
  stripes while it works), and so are its switches, rows of choices, sliders (now moved by the keys too) and tick
  boxes. The sign-in on another server is the site's door: the server it signs in to, the ID and the password with
  their marks, **Remember my ID on this PC**, one sentence under the password for a wrong ID or password, too many
  tries and a server that does not answer above the key (the latter with the way to the connection test), and a
  banned account's reason on a plate of its own. Once a server is connected and nobody is signed in, the sign-in's
  card comes first on **Online** and in the guide's LOG IN, whole on the screen at the window's smallest size, the
  server's card folded into its first line (the address, its version and **Change**). **Add a player** takes its
  three fields side by side.
- **Play** shows who plays across its top, then the ready check beside the last game; the cards of instructions on
  **Play** and **Controls** are gone (the guides in the docs keep how the game plays). The settings' hints say one
  fact each.
- RECORDS' week chart says a week's number for a click, a tap or the arrow keys, not only under a resting pointer.
- Running the installer again over the same version offers **Uninstall** beside **Repair** and **Open openDMT3**,
  with the same choice as **Help**, **Uninstall**: keep the settings, players and records, or delete them too.
- One lit main action on a screen: the first-start guide's own button (Add a player, Sign in) goes quiet once **Next**
  is lit.
- Words never lie on a page's field outside a card: the guide's line on what **Next** waits for, its last step's way
  out of the game and DISC CHECK's "nothing found" stand on cards.

### Fixed

- When another server no longer takes the launcher's sign-in (found by the connection test, RECORDS, the song list or
  PLAY), the launcher forgets it, its sign-in card asks for the password again with the ID kept, and PLAY says why it
  cannot start; it went on showing "Signed in" and a lit PLAY.
- The touch screen's hint on **Controls** says every finger plays, as it has since 0.3.0.
- `.env` saved by Notepad (with a byte-order mark, CRLF or spaces around `=`) reads the same as any other.
- `opendmt3-server setup --game-port` alone keeps the site's port it had (it went back to 4730), and `setup` refuses
  two parts on one port, as `./dmt3 ports` does. `./dmt3 ports` refuses the ports the container uses itself (the
  admin pages' 4731 inside, and Caddy's while exposed), and a refused change gives back the port kept before it.
- The launcher connects to an `https://` address without a port on 443, as a browser does.
- `./dmt3 expose <address> --local-ca` (an IP address as the site's name, on a closed network) answers over HTTPS:
  Caddy gives the address's certificate to visitors that name no site in their handshake, as browsers opening an
  address do.
- `./dmt3 setup` gets the server's image before anything runs in a container: the published one is pulled, and a
  build of this copy is always `opendmt3-server:local` (`compose.yaml` has no recipe of its own; the recipe is
  `packaging/docker/build.yaml`). A failed step says which: Docker, the image, or Compose's own words.
- A new site port (`./dmt3 ports --web`, `setup --web-port`) moves the players' address with it: the invite and its
  QR code, the start banner, `status`, `GET /api/v1/server/invite` and the message to send a player.
- The last backup that `remove --delete-data` keeps (Docker and the server's own program) is readable by its owner
  alone, as the database is.
- `./dmt3 remove --delete-data` takes Caddy's volumes (its certificates and local authority) after `expose --off`
  too, and names any volume Docker still has instead of saying everything went; `./dmt3 remove` takes only the image
  this server runs.
- The admin's **Server** tab on Kubernetes names the cluster's helm and kubectl commands with the release's names,
  and has no buttons there (the cluster runs the server); a container started by hand gets Docker's own commands.
- On Windows `opendmt3-server remove --delete-data` deletes the data before it takes the firewall rules out, asks
  Windows for an administrator only when a rule is there, and says which rules stay when the answer is no.
- `expose --off` gives back the players' address `setup --address` kept; `expose` names Caddy's own ports in its line
  for the router when `./dmt3 ports --http/--https` moved them; while exposed, the start banner names no address of
  this PC that does not reach the site.
- The one-line install's update makes the new version's Python environment before it stops the running server: when
  its libraries cannot be had, it says so and the server runs as it was.
- The Account page's picture form and the admin's upload forms read no further than such a form holds: a body sent in
  chunks without a length, however long, no longer fills the server's memory (any signed-in player could).
- The requests log keeps HTTP's own methods (any other as `OTHER`) and cuts a long address, and its CSV file never
  starts a cell as a formula, the method and the address included.
- A ban ends the player's sign-ins on the site and in the launcher and their API tokens at once, as a new password
  does, and lifting it brings none back; the card number stays.
- MAX points and levels take ASCII digits alone (a minus only for a change of MAX points): digits of another script, a
  plus sign or a line break are refused as any other number that is not one.
- Wrong passwords hold back the ID at the address they came from, so the other players behind one address (a game
  centre's) go on signing in; the address itself waits after 30 for any IDs. A banned player's right password is no
  longer counted as a wrong one, and is checked once.
- Delete all takes openDMT3's own folder for playing too (the client copy PLAY made, its card and settings), and the
  question's size counts it.
- The launcher's settings, the sound file and the server an installer leaves are on the disk before they take the old
  file's place, and the command line does its job from a first start's settings past a `launcher.json` it cannot read
  (empty after a power cut), keeping that file beside.
- The connection test sends the sign-in the launcher keeps only to the server it was made on (in the window it went to
  whatever address was typed), checks the site as Connect does, so a site that is no openDMT3 server stops there, and
  tries the game's port at each of the name's addresses, IPv4 first as the game connects. An address that answers with
  no HTTP (the game's port typed for the site's) is said in words at Connect and at the test's site step, where
  `--test-server` ended with a traceback and the window's card said every step passed.
- On the command line, `--sign-in` of a banned account says the ban's reason, `--server URL --test-server` tests the
  server it connected to, and the test's fixes name its own flags (`--sign-in ID`, `--update`).

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

[Unreleased]: https://github.com/kanggu12/openDMT3/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/kanggu12/openDMT3/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/kanggu12/openDMT3/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/kanggu12/openDMT3/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/kanggu12/openDMT3/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/kanggu12/openDMT3/releases/tag/v0.1.0
