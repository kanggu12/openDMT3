<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/logo-dark.svg">
    <img alt="openDMT3" src="docs/images/logo-light.svg" width="400">
  </picture>
</p>

<p align="center">
  <b>An open-source launcher and server for DJMAX TECHNIKA 3, on your own PC.</b><br>
  It plays the game from your own client data as it is, with an overlay in the game, card logins, records, rankings
  and a site for the players.
</p>

<p align="center">
  <a href="https://github.com/kanggu12/openDMT3/actions/workflows/ci.yml"><img src="https://github.com/kanggu12/openDMT3/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/kanggu12/openDMT3/releases/latest"><img src="https://img.shields.io/badge/download-latest%20release-2a5ff0" alt="Download the latest release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2a5ff0" alt="License: MIT"></a>
  <a href="#what-it-runs-on"><img src="https://img.shields.io/badge/runs%20on-Windows%20%7C%20Docker%20%7C%20Python-2b323b" alt="The launcher runs on Windows, a server with Docker or Python"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> &nbsp;|&nbsp;
  <a href="#what-it-does">What it does</a> &nbsp;|&nbsp;
  <a href="#how-it-works">How it works</a> &nbsp;|&nbsp;
  <a href="#guides">Guides</a> &nbsp;|&nbsp;
  <a href="#contributing">Contributing</a>
</p>

<p align="center">
  <img src="docs/images/showcase.webp" alt="openDMT3 in four screens, with made-up players, songs and folders: the launcher's PLAY page with who plays, the ready check and the last session; the site's rankings, each mode's DJs by total score; the game's own tutorial with openDMT3's overlay bar and its FPS counter at 60 FPS, 16.7 ms; and the admin pages' Players tab" width="100%">
</p>

**DJMAX TECHNIKA 3** is an arcade rhythm game of 2011: a cabinet with a touch screen, coins for each play, and an ID
card that logged a player in to the game's online service, which kept their records and rankings. openDMT3 plays your
own copy of the game on a Windows PC: a mouse or a touch screen in place of the cabinet's, FREE PLAY in place of coins,
a card the launcher puts in for you, and a server of your own in place of the service.

> [!IMPORTANT]
> **No game files are included.** You need your own copy of the TECHNIKA 3 client data, with a client that runs on a
> PC. Please use only files you have the right to use. openDMT3 is an unofficial, non-commercial project, not
> affiliated with or endorsed by NEOWIZ.

## Quick start

Two ways to begin, each complete on its own: playing on your PC, and running a server for players on their own PCs.

<table>
<tr>
<th width="50%" align="left">Play on your PC</th>
<th width="50%" align="left">Run a server</th>
</tr>
<tr>
<td valign="top">

On Windows 10 or 11, with your own client data ([which](docs/client-data.md#which-client-data)):

1. Download **[openDMT3-win-Setup.exe](https://github.com/kanggu12/openDMT3/releases/latest/download/openDMT3-win-Setup.exe)**
   and run it.
2. Choose **Install**. The launcher opens on its first-start guide, which finds your client data and takes you to
   **PLAY**.

If Windows says it protected your PC, choose **More info**, then **Run anyway** (the installer is not signed). On Linux
the same installer runs under Wine ([how](docs/install.md#on-linux-with-wine)).

**[The player's guide](docs/install.md)**

</td>
<td valign="top">

On Linux, macOS or Windows in WSL 2, with Docker (Compose v2), git, Python 3, and your client data for the song list:

```sh
git clone https://github.com/kanggu12/openDMT3
cd openDMT3
./dmt3 setup
```

A wizard in the terminal asks where your client data is and which installer to hand out (an
`openDMT3-win-Setup.exe` you downloaded), then gives the site's address and the admin's password. A server also runs
[in the launcher](docs/server.md#in-the-launcher) or [with Python](docs/server.md#with-python).

**[The server guide](docs/server.md)**

</td>
</tr>
</table>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/steps-dark.svg">
    <img alt="Playing in three steps. 1, Install: run openDMT3-win-Setup.exe, which installs for your Windows user only, without administrator rights. 2, DISC CHECK: the launcher finds your client data and says what it is, here made-up client data in a folder that is READY, with its original PC client, its songs and jackets, only read and never changed. 3, PLAY: your card goes in and the game starts" src="docs/images/steps-light.svg" width="100%">
  </picture>
</p>

## What it does

- **Plays your client data as it is.** It only reads the client data. What the game needs on a PC goes in a folder of
  openDMT3's own: a copy of the client that fills the screen at any Windows scaling and reads the mouse in the right
  place, FREE PLAY, the patterns the cabinet hid, the server address.
- **An overlay in the game.** An overlay bar at the top edge with a menu and an X that asks first, the game held still
  while the menu or the question is open, a notice when there is something to say, an FPS counter if you want one,
  and a pointer of its own. It stays in the top band and the corners, never where the notes come, and no key brings it.
- **A picture and a sound for your PC.** Frame pacing locked to the music, the game's 5:3 shape kept on any screen,
  upscale filters and anti-aliasing with a safety net that keeps 60 frames a second, and on the **Sound** page the
  device, Windows' sound engine in its shortest steps, OpenAL Soft as the mixer and an offset for headphones or a TV
  that play late.
- **Logs in by card, without a reader.** The PC client logs players in only by card. openDMT3 gives the game a card
  reader library of its own, which reads the card number the launcher writes, so the game logs in the player you
  picked.
- **Records and the DJ card.** The stages each player clears, on the launcher's **Records** page and on the site:
  rankings per mode, a board per chart, each DJ's page with the last 12 weeks. The song select shows each player's best
  and the server's first place; the DJ card shows a level, and an icon, plate, pattern and comment chosen on the site.
- **A site for the players.** Rankings, songs, DJ pages, the launcher's installer set up for that server, admin pages
  with backups, and an API for all of it, in English and Korean.
- **Plays with others, and without internet.** On someone's server, or on one PC opened to the others on its network;
  without internet on this PC, or with a server on a closed network ([without internet](docs/server.md#without-internet)).
- **Updates itself** with packages signed by the openDMT3 project, downloading only what changed when it can, and
  **says what is wrong** in English or Korean, with a ready check before PLAY and a report for an issue.

### In the game

Rest the pointer at the game's top edge and the overlay bar comes down: openDMT3's mark, the menu, minimize, full
screen or a window, and the X. The X asks before the game ends, and during a song the menu and the question hold the
game still until you go back to it.

<p align="center">
  <img src="docs/images/ingame.png" alt="openDMT3's overlay over TECHNIKA 3's tutorial, in real frames. The overlay bar across the top: openDMT3's mark at its left, and at its right the menu, minimize, back to a window, and quit. The menu hangs under its button: BACK TO THE GAME, SHOW FPS, QUIT THE GAME in red. Under it, three pieces of other frames: the quit question under the X, Quit the game?, with A play in progress is not kept., KEEP PLAYING and QUIT THE GAME; a notice hanging from the top edge, Picture quality lowered to keep 60 FPS (Smooth upscale); and the FPS counter in the bottom right corner above the game's FREE PLAY, 60 FPS over 16.7 ms" width="100%">
</p>

### Frames on time, and on the music

The game runs its logic once a frame, so a late frame slows the game against its music. openDMT3 holds the frames to
60.0 a second with its own clock and, while a song plays, follows the song's music, so the notes stay on it. Each frame
also starts just in time for its turn, so the touch it carries reaches the screen sooner: under Wine at 1280x768,
1.7 ms less from the game's read of a touch to its frame done
([measured](docs/testing.md#a-song-each-frame-started-just-in-time-before-and-after)).

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/chart-pacing-dark.svg">
    <img alt="Frames on time and on the music: the game's own frame limiter against openDMT3's clock, locked to the music. The spread of a frame's length (standard deviation): 2.33 milliseconds against 0.00. The slowest frame in a hundred: 20.6 milliseconds against 16.8, where a frame at 60 a second is 16.7. Measured on an RTX 4090 at 1920x1080 on the game's title screen. Over a whole song of 123 seconds on Wine's software renderer, the music ended 1.2 seconds ahead of the frames with the game's own pacing, and within 7 milliseconds of them locked to the music" src="docs/images/chart-pacing-light.svg" width="100%">
  </picture>
</p>

The game draws 1280x768. openDMT3 enlarges it to your screen with AMD FSR 1 by default, or NVIDIA NIS, Anime4K or
bilinear, with FXAA or SMAA first if you want them, or has the game draw at the screen's size. They are shaders any
card with shader model 3.0 runs, and when frames come late they step down by themselves
([the picture](docs/install.md#frame-pacing-the-picture-the-fps-counter-and-the-sound-device)). While the game runs,
Windows mixes its sound in the shortest steps the device's driver allows (2.7 ms with Windows' own audio driver, where
10 ms is usual), and OpenAL Soft can mix the game's sounds on a shorter way to the device: under Wine, 12 to 16 ms
from a sound's start to its output, against DirectSound's 44 ([measured](docs/architecture.md#the-mixer)).

### A server for many cabinets

One process answers the cabinets, the site's visitors and the API at once, and none of them holds up the others
([many players at once](docs/server.md#many-players-at-once)).

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/chart-server-dark.svg">
    <img alt="64 cabinets and 20 visitors that never pause, for three minutes, on a history of 300,000 plays, before and after the server's work: a cabinet's keep-alive, median, 7,802 milliseconds before and 6.8 after; a card login, median, 6,363 before and 136 after; a page of the site, median, 7,714 before and 235 after; a page of the site, 95th percentile, 10,816 before and 745 after. Pages answered in the three minutes: 500 before, 12,103 after. The server held 91 MB of memory" src="docs/images/chart-server-light.svg" width="100%">
  </picture>
</p>

### Where things stand

- **Works:** the launcher with its guide and pages, the installer and its updates, the connection to the game (NET),
  card logins with the DJ card, the stages a player clears (song, pattern, score) and the song select's records, the
  site with its rankings, song and DJ pages and admin pages, and the server in Docker. Each release is checked with the
  game's own PC client under Wine, from the installer to a whole song, on one PC and across two machines.
- **Experiments, off by default:** motion clarity on a 120, 180 or 240 Hz display (a CRT's rolling beam or black
  frames, from the Blur Busters CRT beam simulator) and the flip model (Direct3D 9Ex's flip swap chain, the way to
  Windows' independent flip and a variable refresh rate). How they look on real displays is still to be seen.
- **Not yet:** the rank and max combo of each stage, missions and crews, and two-finger touch.

## How it works

The game runs on your PC, from your client data, which stays as it is. Logins and records live on a server: the one
inside the launcher, someone else's, or none at all. The launcher talks to the server over HTTP, and the game over its
own protocol; browsers and programs use the same site and API.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/system-dark.svg">
    <img alt="How openDMT3 fits together. On the player's Windows PC, the client data (the PC client and the game's files) is only read: the launcher finds it, and the game plays from it in place. The launcher sets the picture and the sound, puts the card in, and PLAY starts the game with openDMT3's card reader library and overlay inside it. Other players' PCs are the same. The launcher talks to a server over HTTP on port 4730: signing in, the card at each PLAY, records; the game talks to it over the game's own protocol on port 4725: its card login and its results. Browsers open the server's site (players: rankings, songs, DJ pages; the owner: the admin pages) and programs its API with a named token, on port 4730 too. The server is one process, inside the launcher, with Docker or with Python: the game server, the site and its API, and one SQLite file in its data folder, which holds the accounts, the plays and the song list read once from the client data" src="docs/images/system-light.svg" width="100%">
  </picture>
</p>

Choose how you play on the launcher's **Online** page or in its first-start guide:

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/ways-to-play-dark.svg">
    <img alt="Three ways to play. On this PC: a server inside the launcher keeps the logins and the records in one file on this PC. Another server: the launcher and the game on your PC log in on a server someone runs, with an ID and a password from its owner, and the records stay on that server. Offline: no server; everyone plays as a guest with NO ID CARD, and no records are kept" src="docs/images/ways-to-play-light.svg" width="100%">
  </picture>
</p>

Run a server when others play from their own PCs: in the launcher, with Docker or with Python, it is the same server,
with the game on port 4725, people and launchers on port 4730, and everything it keeps in one folder. It takes one
thing from the client data: the song list, which holds the jackets and the DJ cards too
([what a server takes](docs/client-data.md#what-a-server-takes)). [Running a server](docs/server.md) has each way step
by step.

## What it runs on

| | Minimum | Recommended |
| :--- | :--- | :--- |
| **To play** | 64-bit Windows 10 or 11, or Linux with Wine 11 ([how](docs/install.md#on-linux-with-wine)), on an x64 processor (Intel or AMD), a graphics card with Direct3D 9 (NVIDIA, AMD or Intel), a mouse, and your client data (about 38 GB whole) | Shader model 3.0 on the graphics card for the upscale filters and anti-aliasing, and a touch screen to play as on the cabinet |
| **The launcher** | About 43 MB to download; installed for your Windows user only, without administrator rights | |
| **A server** | The launcher, for the PCs on its network; Docker with Compose v2, git and Python 3 on Linux, on macOS, or on Windows in WSL 2; or Python 3.10 or newer on Linux; ports 4725 (the game) and 4730 (the site) open to the players' PCs | About 100 MB of memory for 64 cabinets |
| **On a server** | The song list alone, about 13 MB: no charts, music or videos | |

A card without shader model 3.0 gets Direct3D's own scaling. Tested under Wine, on an NVIDIA graphics card through
WSL's Direct3D 12 and on Mesa's software renderer; not yet on an AMD or Intel graphics card.

## Guides

### For players

| Guide | What it covers |
| :--- | :--- |
| [Playing on your PC](docs/install.md) | The player's guide: the installer on Windows or with Wine, the first start, the three ways to play, the overlay in the game, the pages, the picture and the sound, records, updates, the command line |
| [The client data](docs/client-data.md) | Which client data plays, the forms it comes in, what each card on DISC CHECK says and the one thing to do, what a server takes |
| [Troubleshooting](docs/troubleshooting.md) | When something does not work |

### For server owners

| Guide | What it covers |
| :--- | :--- |
| [Running a server](docs/server.md) | The server owner's guide: in the launcher, with Docker or with Python, the song list, players, the site and the admin pages, backups, updates, the internet, without internet |
| [The API](docs/api.md) | Everything the site shows and does, as JSON |

[License and notice](docs/notice.md) says what the project is, its license and the third-party parts, for everyone.

## Contributing

Bug reports, ideas and pull requests are welcome: [Issues](https://github.com/kanggu12/openDMT3/issues/new/choose).
[CONTRIBUTING.md](CONTRIBUTING.md) is the contributors' guide: where the code is, how to run each part and its
tests with no game files, and how a change goes in. [Architecture](docs/architecture.md),
[Protocol](docs/protocol.md) and [Testing](docs/testing.md) go deeper; [CHANGELOG.md](CHANGELOG.md) says what
changed.

## Credits and license

The launcher and the site follow the look of TECHNIKA 3's own screens, drawn in code, in DMT3 Wide (a cut of Saira)
and Pretendard. The picture's passes are AMD FidelityFX Super Resolution 1, NVIDIA Image Scaling, Anime4K, SMAA and
FXAA, and motion clarity's is the Blur Busters CRT beam simulator; the Sound page's OpenAL Soft mixer is DSOAL and
OpenAL Soft; the installer and its updates are Velopack's; archives are opened with 7-Zip.

openDMT3's own code and documentation are under the MIT License ([LICENSE](LICENSE)); the parts it brings with it are
listed in [the notice](docs/notice.md#license). The license does not cover the game or its files, which are not in
this repository. DJMAX and TECHNIKA are trademarks of NEOWIZ. If a rights holder asks through the issues, the
repository will promptly be made private or taken down, in whole or in part ([notice](docs/notice.md)).
