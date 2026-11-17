# Server questions

For server owners: short answers, each with the guide that has the rest. Problems with their fixes are in
[Troubleshooting](troubleshooting.md#the-server).

## Which way should I run the server?

- To play with the other PCs on your network while you play too: the launcher's own server ([In the launcher](server.md#in-the-launcher)).
- A Windows PC that stays on, without Docker: the Windows server package ([On Windows](server.md#on-windows)).
- Linux or macOS: Docker with `./dmt3 setup` ([With Docker](server.md#with-docker)), or the one-line install without
  Docker ([With Python](server.md#with-python)).
- A Kubernetes cluster: the Helm chart ([On Kubernetes](kubernetes.md)).

Each runs the same server, with the same database in its data folder.

## Why two ports for the players, not one?

The game speaks its own protocol on TCP 4725, and in it the server speaks first. A web port waits for the browser to
speak first, so one port for both would hold every cabinet's login until the server was sure no browser was there.
The players' site and the launcher's API share the other port, 4730. The launcher asks the site for the game's port,
so players type only the site's address. The admin pages have a third, 4731, for the owner alone.

## Where are the admin pages?

A site of their own: `http://127.0.0.1:4731/` on the server PC, and nowhere else until you open them. To the other
PCs of your network: `./dmt3 setup --admin-network yes` or `opendmt3-server setup --admin-host 0.0.0.0`. Over the
internet, over HTTPS: `./dmt3 expose NAME --admin-public` (or `opendmt3-server expose NAME --admin-public`), at
`https://NAME:4731/`. On Kubernetes:
`kubectl port-forward`. A server PC with no screen needs no browser for the owner's account: `./dmt3 setup` makes it,
and `opendmt3-server setup` asks for it in the terminal ([The admin pages](server.md#the-admin-pages)).

## Can I use other ports?

Yes, set once and used everywhere: `./dmt3 ports --game 5725 --web 8080 --admin 8731` with Docker,
`opendmt3-server setup --game-port 5725 --web-port 8080 --admin-port 8731` on Windows or with Python,
`game.service.port` with the Helm chart. The server listens on the same numbers it publishes, so the site tells
launchers the game's port they reach, and the players' address setup kept moves to the new site port with it (an
`https://` address through a proxy stays).

## How do players find my server?

The admin pages' **Players** shows the address players open, with a QR code to scan from the screen
(`./dmt3 invite` and `opendmt3-server invite` print the same). Making an account there gives the message to send the
player: the address, the ID, the password and the steps. The players' address is the one `setup --address` kept;
without it, this PC's address on its network.

## Does the server need the whole game?

No: only the song list (with the jackets and the DJ cards), read once from your client data, about 13 MB
([What a server takes](client-data.md#what-a-server-takes)).

## How do I put the site on HTTPS?

`./dmt3 expose NAME` with Docker, or `opendmt3-server expose NAME` with Caddy beside it
([Playing from outside your home](internet.md)). On a network without internet, Caddy's own authority or yours
([A closed network](closed-network.md#https-on-a-closed-network)).

## Where is my data, and how do I back it up?

In the data folder: `data` beside the Windows package's program, `~/.local/share/opendmt3-server/data` after the
one-line install, the volume `opendmt3_data` with Docker. The server backs it up once a day and keeps a week; `backup`
makes one now ([Backups](server.md#backups)).

## How do I update the server?

[Updating the server](server.md#updating-the-server): the data stays, and a newer server takes an older database
forward.

## How do I remove the server?

[Removing a server](server.md#removing-a-server): `./dmt3 remove` or `opendmt3-server remove`, with
`--delete-data` to delete the data too (with Docker, Caddy's certificates too), after a last backup kept beside it,
readable by its owner alone. On a cluster, the admin pages' **Server** names the helm and kubectl commands
([On Kubernetes](kubernetes.md#the-admins-server-tab)).

## Something is broken. What do I run first?

`./dmt3 doctor` (Docker) or `opendmt3-server repair` (Windows, Python): each problem with the one thing that fixes it.
`./dmt3 repair` gets the image again and makes the server's container afresh; the data stays.
