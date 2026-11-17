# A closed network

For server owners whose server and players share a network with no way out to the internet: a LAN party, an arcade
room, a club's own network. The server needs no internet once it is set up: nothing it does reaches outside (but
the chat webhook, when you give it one), and the site's fonts and pictures come with it. Only the setup needs files
brought in from a PC that has internet. The other guides: [Running a server](server.md),
[Playing from outside your home](internet.md).

## What to bring in

From a PC with internet, onto a USB stick or a share:

- **The launcher's installer** for the players, from the [releases](https://github.com/kanggu12/openDMT3/releases),
  and your client data's song list ([what a server takes](client-data.md#what-a-server-takes)).
- **The server**, one of these:
  - **Windows**: the release's `opendmt3-server-0.3.1-windows-x64.zip`. It needs nothing else: it brings its own
    Python, 7-Zip and the launcher's installer.
  - **Docker**: the server's image as a file. Pull it there and save it:
    `docker pull ghcr.io/kanggu12/opendmt3-server:0.3.1` then
    `docker save ghcr.io/kanggu12/opendmt3-server:0.3.1 -o opendmt3-server.tar`; with HTTPS, Caddy's too:
    `docker pull caddy:2.10.2-alpine` and `docker save caddy:2.10.2-alpine -o caddy.tar`. Bring the release's
    server package (`opendmt3-server-0.3.1.zip`) or a copy of the repository beside them.
  - **Python**: the release's server package, and the site's libraries as files, downloaded there on the same system
    and Python version as the server:
    `pip download -d wheels starlette==0.47.3 jinja2==3.1.6 uvicorn==0.35.0 python-multipart==0.0.20 pillow==11.3.0`.

## Setting it up

- **Windows**: unpack the zip and start `opendmt3-server.exe`, as its `README.txt` says.
- **Docker**: `docker load -i opendmt3-server.tar` (and `caddy.tar`), then in the package's folder
  `./dmt3 setup --address 192.168.0.5`: the image is there already, so it is neither pulled nor built. `./dmt3 up
  --no-build` starts the server from it later on.
- **Python**: `python3 -m venv .venv`, then
  `.venv/bin/pip install --no-index --find-links wheels starlette jinja2 uvicorn python-multipart pillow`, and run the
  server as [With Python](server.md#with-python) says.

Players install the launcher from the site's **Download** page and connect to the address you chose.

## HTTPS on a closed network

Let's Encrypt cannot reach a closed network, so its certificates are out. Two ways instead:

- **Caddy's own authority.** `./dmt3 expose dmt3.lan --local-ca` (a name your network's DNS gives the server PC, or
  its address: `./dmt3 expose 192.168.0.5 --local-ca`). Caddy signs the site's certificate with an authority of its
  own. With an address, the certificate is the address's, and Caddy gives it to every visitor that names no site in
  its handshake (a browser opening `https://192.168.0.5/` names none). Each player's PC trusts that authority's root
  once: `./dmt3 expose --root-cert dmt3-root.crt` saves it; on Windows, open the file, **Install Certificate**,
  **Local Machine**, and put it in **Trusted Root Certification Authorities**.
- **Your network's own ACME authority** (step-ca, for example): `./dmt3 expose dmt3.lan --ca
  https://ca.lan/acme/acme/directory --ca-root ca-root.crt`. Caddy then gets and renews the certificate from it as
  from Let's Encrypt, and players' PCs that trust your authority trust the site.

Without either, the site works the same over plain HTTP at the server's address.

## Players at a LAN party

- The server PC's address must stay the same: give it a fixed address on the router, or set one on the PC.
- `./dmt3 invite` (or `opendmt3-server invite`) prints the address with a QR code; **Admin**, **Players** shows the
  same, to put on a screen.
- Cabinets behind one router share its address: the game's port takes up to 16 of them from one address, and 64 in
  all ([Many players at once](server.md#many-players-at-once)).
