<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="images/logo-dark.svg">
    <img alt="openDMT3" src="images/logo-light.svg" width="400">
  </picture>
</p>

# Guides

openDMT3 is a launcher that plays TECHNIKA 3 on a Windows PC and a server that keeps its players' logins and records.
New here? The [README](../README.md#quick-start) has the two ways to begin side by side: playing on your PC, and
running a server for other players' PCs. Each has a guide of its own, and the guides below are grouped by who reads
them.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="images/system-dark.svg">
    <img alt="How openDMT3 fits together. On the player's Windows PC, the client data (the PC client and the game's files) is only read: the launcher finds it, and the game plays from it in place. The launcher sets the picture and the sound, puts the card in, and PLAY starts the game with openDMT3's card reader library and overlay inside it. Other players' PCs are the same. The launcher talks to a server over HTTP on port 4730: signing in, the card at each PLAY, records; the game talks to it over the game's own protocol on port 4725: its card login and its results. Browsers open the server's site (players: rankings, songs, DJ pages, on port 4730; the owner: the admin pages, a site of their own on port 4731) and programs its API with a named token, on port 4730 too. The server is one process, inside the launcher, from a server package, with Docker or with Python: the game server, the site and its API, and one SQLite file in its data folder, which holds the accounts, the plays and the song list read once from the client data" src="images/system-light.svg" width="100%">
  </picture>
</p>

## For players

| Guide | For |
| :--- | :--- |
| [Playing on your PC](install.md) | The player's guide: what you need, the installer on Windows or on Linux with Wine, checking a download, the first start, the three ways to play, the overlay in the game, the pages, frame pacing, the picture's shape and filters, records, the other PCs on your network, the song list for a server, playing without the window, updates, what PLAY makes in openDMT3's own folder, removing it, the command line |
| [The client data](client-data.md) | Which client data plays, where the launcher finds it, the forms it comes in, what each card on DISC CHECK says and the one thing to do, what a server takes, checking from the command line, questions and answers |
| [Troubleshooting](troubleshooting.md) | The installer, finding the game, PLAY, the game closing, the picture, the sound, logins, records, the other PCs, putting everything back |
| [Questions and answers](faq.md#for-players) | Whether you need a server, which client data, your client data kept as it is, which PCs, Windows' question about the installer, where your settings are, updating and removing; what leaves your PC; the project |
| [License and notice](notice.md) | What the project is, its license, the rights holders' requests |
| [Third-party notices](THIRD_PARTY_NOTICES.md) | Each part openDMT3 brings, where it goes, and its license |

## For server owners

| Guide | For |
| :--- | :--- |
| [Running a server](server.md) | The server owner's guide: what you need, the ways (in the launcher, on Windows, on Linux or macOS, with Docker, with Python, on Kubernetes), the ports, removing a server, the song list, players, the site and the admin pages, DJ cards and the song select, the data folder and moving a server, backups, updating the server, handing out updates, a chat webhook, the internet, many players at once, without internet, what to keep private, the command line |
| [Playing from outside your home](internet.md) | A name, the router's forwards, HTTPS with `./dmt3 expose` and Caddy, checking from outside, what is open |
| [A closed network](closed-network.md) | What to bring in for a network with no internet, HTTPS with Caddy's own authority or yours, LAN parties |
| [On Kubernetes](kubernetes.md) | The Helm chart: what it makes, the first account, the song list, the game's port, an Ingress with HTTPS, backups, updates, removing, the kind test |
| [Questions and answers](faq.md#for-server-owners) | Which way to run it, why two ports, other ports, inviting players, HTTPS, the data, updating, removing, what to run first |
| [What a server takes](client-data.md#what-a-server-takes) | The song list from the client data, and each way it comes in |
| [The API](api.md) | What the site shows and does, as JSON, for scripts and the launcher: a first call, named tokens, the OpenAPI document |
| [Troubleshooting a server](troubleshooting.md#the-server) | `opendmt3-server repair` and `./dmt3 doctor`, a port another program has, the owner's first account, the ports and WSL 2, sign-ins held back, the song list |
| [If you run a server](notice.md#if-you-run-a-server) | What a server reads and keeps, and the rights holders' requests |

## For contributors

| Guide | For |
| :--- | :--- |
| [Architecture](architecture.md) | The package and its three parts, the repository and `./dmt3`, the game's files, playing client data that is only read, the in-game overlay, frame pacing, the launcher, the server, the database, performance, security, the build |
| [The game's protocol](protocol.md) | What the game and its server say to each other, as far as it is known |
| [Testing](testing.md) | The suites, the layout checks, the Wine tests on the CPU and on the graphics card, CI, what runs before a release |
| [Test cases](test-cases.md) | Every case, one table per area, with what checks it |
| [Contributing](../CONTRIBUTING.md) | Where the code is, running it and its tests, how a change goes in, releases |
