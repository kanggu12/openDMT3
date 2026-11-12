<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="images/logo-dark.svg">
    <img alt="openDMT3" src="images/logo-light.svg" width="400">
  </picture>
</p>

# Guides

openDMT3 is an open-source project. New here? The [README](../README.md#quick-start) has the quick start for each way
to begin, and [The game's files](game-files.md) says what you need of the game.

## Playing and running a server

| Guide | For |
| :--- | :--- |
| [Playing on your PC](install.md) | The installer, the first start, the three ways to play, the bar and the menu in the game, the pages, frame pacing, the picture's shape and filters, records, the other PCs on your network, the song list for a server, playing without the window, updates, what PLAY makes in openDMT3's own folder, removing it, the command line |
| [The game's files](game-files.md) | What the game folder has to be, the forms it comes in, each line a card says with the one thing to do, what a server takes, checking from the command line, questions and answers |
| [Running a server](server.md) | Docker or Python, the song list, updating the server, players, the site and the admin pages, DJ cards and the song select, backups, handing out updates, a chat webhook, the internet, many players at once, without internet, what to keep private, the command line |
| [The API](api.md) | What the site shows and does, as JSON, for scripts and the launcher; named tokens, the OpenAPI document |
| [Troubleshooting](troubleshooting.md) | The installer, the game folder, PLAY, the game closing, the picture, the sound, logins, records, the other PCs, the server, putting everything back |
| [License and notice](notice.md) | What the project is, its license, the third-party parts |

## Working on the code

| Guide | For |
| :--- | :--- |
| [Architecture](architecture.md) | The package and its three parts, the repository and `./dmt3`, the game's files, playing a game folder that is only read, the in-game layer, frame pacing, the launcher, the server, the database, performance, security, the build |
| [The game's protocol](protocol.md) | What the game and its server say to each other, as far as it is known |
| [Testing](testing.md) | The suites, the layout checks, the Wine tests on the CPU and on the graphics card, CI, what runs before a release |
| [Test cases](test-cases.md) | Every case, one table per area, with what checks it |
| [Contributing](../CONTRIBUTING.md) | Where the code is, running it and its tests, how a change goes in, releases |
