# Changelog

What changed in each release of openDMT3. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/): a release with a new feature raises the minor number,
one of fixes, changes and smaller additions raises the patch number. Each release's section here is its release notes.

## [Unreleased]

### Added

- **Low latency** on the Sound page, on by default: while the game runs, Windows mixes the sound of the game's output
  device in the shortest steps its driver allows (2.7 ms on many devices, where 10 ms is usual), and the page and
  `--status` say the steps the last game's sound went in.
- **Mixer** on the Sound page: the game's sounds mixed by Windows' DirectSound (the default), or by OpenAL Soft through
  DSOAL, sharing the device or with it to itself (**Exclusive**); when OpenAL Soft cannot open the device, the game plays
  through DirectSound and the page says so. Each release carries the two libraries' source archives.

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

[Unreleased]: https://github.com/kanggu12/openDMT3/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/kanggu12/openDMT3/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/kanggu12/openDMT3/releases/tag/v0.1.0
