# Questions and answers

Short answers, each with the guide that has the rest: for players, for server owners, what leaves your PC, and the
project. Problems with their fixes are in [Troubleshooting](troubleshooting.md).

## For players

### Do I need a server to play?

No. On the launcher's **Online** page, **On this PC** keeps your players and records in a server inside the launcher,
and **Offline** plays with no server at all, every player a guest with **NO ID CARD**
([three ways to play](install.md#three-ways-to-play)).

### Which client data plays?

Your own TECHNIKA 3 client data with a client that runs on a PC, in a folder or in an archive. The cabinet's own
client needs the cabinet's security keys and does not run on a PC
([which client data](client-data.md#which-client-data)).

### Does openDMT3 change my client data?

No. PLAY only reads it, and makes what the game needs in a folder of openDMT3's own
([your client data stays as it is](install.md#your-client-data-stays-as-it-is)).

### Which PCs does it run on?

64-bit Windows 10 or 11, or Linux under Wine 11: the launcher and the game are Windows programs
([on Linux, with Wine](install.md#on-linux-with-wine)). The game needs a graphics card with Direct3D 9, and a mouse or
a touch screen plays it ([what it runs on](../README.md#what-it-runs-on)).

### Why does Windows say it protected my PC?

The installer is not signed. Choose **More info**, then **Run anyway**. Windows 11's Smart App Control, when it is on,
blocks it with no such choice ([Install](install.md#install)).

### Where are my settings and records?

In `%AppData%\openDMT3`: the settings, the logs and, playing on this PC, the server's database
(`server\openDMT3.sqlite`, with its daily backups beside it). Playing on another server, your records are on that
server.

### How do I update or remove it?

**Launcher**, **Check for updates** updates it; **Help**, **Uninstall** removes it, with or without your settings,
players and records ([Updates](install.md#updates), [Removing openDMT3](install.md#removing-opendmt3)).

## For server owners

### Which way should I run the server?

- To play with the other PCs on your network while you play too: the launcher's own server
  ([In the launcher](server.md#in-the-launcher)).
- A Windows PC that stays on, without Docker: the Windows server package, or its one-line install
  ([On Windows](server.md#on-windows)).
- Linux or macOS: the release's package for the machine, or its one-line install, without Docker or Python
  ([On Linux or macOS](server.md#on-linux-or-macos)); or Docker with `./dmt3 setup`
  ([With Docker](server.md#with-docker)).
- A Kubernetes cluster: the Helm chart ([On Kubernetes](kubernetes.md)).

Each runs the same server, with the same database in its data folder.

### Why two ports for the players, not one?

The game speaks its own protocol on TCP 4725, and in it the server speaks first. A web port waits for the browser to
speak first, so one port for both would hold every cabinet's login until the server was sure no browser was there.
The players' site and the launcher's API share the other port, 4730. The launcher asks the site for the game's port,
so players type only the site's address. The admin pages have a third, 4731, for the owner alone.

### Where are the admin pages?

A site of their own: `http://127.0.0.1:4731/` on the server PC, and nowhere else until you open them. To the other
PCs of your network: `./dmt3 setup --admin-network yes` or `opendmt3-server setup --admin-host 0.0.0.0`. Over the
internet, over HTTPS: `./dmt3 expose NAME --admin-public` (or `opendmt3-server expose NAME --admin-public`), at
`https://NAME:4731/`. On Kubernetes:
`kubectl port-forward`. A server PC with no screen needs no browser for the owner's account: `./dmt3 setup` makes it,
and `opendmt3-server setup` asks for it in the terminal ([The admin pages](server.md#the-admin-pages)).

### Can I use other ports?

Yes, set once and used everywhere: `./dmt3 ports --game 5725 --web 8080 --admin 8731` with Docker,
`opendmt3-server setup --game-port 5725 --web-port 8080 --admin-port 8731` on Windows or with Python,
`game.service.port` with the Helm chart. The server listens on the same numbers it publishes, so the site tells
launchers the game's port they reach, and the players' address setup kept moves to the new site port with it (an
`https://` address through a proxy stays).

### How do players find my server?

The admin pages' **Players** shows the address players open, with a QR code to scan from the screen
(`./dmt3 invite` and `opendmt3-server invite` print the same). Making an account there gives the message to send the
player: the address, the ID, the password and the steps. The players' address is the one `setup --address` kept;
without it, this PC's address on its network.

### Does the server need the whole game?

No: only the song list (with the jackets and the DJ cards), read once from your client data, about 13 MB
([What a server takes](client-data.md#what-a-server-takes)).

### How do I put the site on HTTPS?

`./dmt3 expose NAME` with Docker, or `opendmt3-server expose NAME` with Caddy beside it
([Playing from outside your home](internet.md)). On a network without internet, Caddy's own authority or yours
([A closed network](closed-network.md#https-on-a-closed-network)).

### Where is my data, and how do I back it up?

In the data folder: `data` beside a server package's program (Windows, Linux or macOS),
`~/.local/share/opendmt3-server/data` after the one-line install on Linux or macOS, `data` in
`%LOCALAPPDATA%\Programs\opendmt3-server` after the one on Windows, the volume `opendmt3_data` with Docker
([The data folder](server.md#the-data-folder)). The server backs it up once a day and keeps a week; `backup` makes one
now ([Backups](server.md#backups)).

### How do I update the server?

[Updating the server](server.md#updating-the-server): the data stays, and a newer server takes an older database
forward.

### How do I remove the server?

[Removing a server](server.md#removing-a-server): `./dmt3 remove` or `opendmt3-server remove`, with
`--delete-data` to delete the data too (with Docker, Caddy's certificates too), after a last backup kept beside it,
readable by its owner alone. On a cluster, the admin pages' **Server** names the helm and kubectl commands
([On Kubernetes](kubernetes.md#the-admins-server-tab)).

### Something is broken. What do I run first?

`./dmt3 doctor` (Docker) or `opendmt3-server repair` (the server's packages, and Python): each problem with the one
thing that fixes it. `./dmt3 repair` gets the image again and makes the server's container afresh; the data stays
([Troubleshooting a server](troubleshooting.md#the-server)).

## What leaves your PC

- **The launcher** talks to the server you play on: the one inside it, or the address you gave on **Online**; offline,
  none. It looks for a newer launcher only when you press **Check for updates** (or run `--update`): on that server
  when it hands updates out, else on the project's releases on GitHub.
- **The game** talks to the same server, on the game's port. Offline, openDMT3 changes no address of the game's: it
  tries the one its client data has, as it always did.
- **A report** (**Help**, **Report**, **Save**) is a zip on your desktop and goes nowhere by itself; your Windows user
  name, your sign-in, your card number and the server's address are taken out of it.
- **A server** keeps the accounts (each password as a slow hash), the plays and its logs in its data folder. It
  reaches outside only for a chat webhook you give it; with `expose`, Caddy gets the site's certificate, and `./dmt3`
  pulls the server's image when it sets up or updates.

## The project

### Is this official?

No. openDMT3 is an unofficial, non-commercial project, not affiliated with or endorsed by NEOWIZ
([License and notice](notice.md)).

### Does it cost anything?

No. It is MIT licensed, and everything runs on your own PCs.

### Where do I ask when something does not work?

[Troubleshooting](troubleshooting.md) answers most of it. If not, please
[open an issue](https://github.com/kanggu12/openDMT3/issues/new/choose) with a report from **Help**, **Report**, and
without any of the game's files.

### Can I help?

Yes: [CONTRIBUTING.md](../CONTRIBUTING.md). Working on the code needs no game files.
