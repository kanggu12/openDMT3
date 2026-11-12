# Changelog

What changed in each release of openDMT3. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/): a release with a new feature raises the minor number,
one of fixes, changes and smaller additions raises the patch number. Each release's section here is its release notes.

## [Unreleased]

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

[Unreleased]: https://github.com/kanggu12/openDMT3/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/kanggu12/openDMT3/releases/tag/v0.1.0
