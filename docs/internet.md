# Playing from outside your home

For server owners. By default the server is for your own network: the other PCs on it reach the server at this PC's
address. To let players connect from anywhere, give the site a name that leads to your PC, forward the ports on the
router, and put the site behind HTTPS, which the sign-ins need on the internet. The other guides:
[Running a server](server.md), [A closed network](closed-network.md), [Kubernetes](kubernetes.md).

## What players reach

Players reach two ports from outside:

- **The game's port**, TCP 4725. The game speaks its own protocol there, the server first, so it is not HTTP and no
  web proxy can carry it: it is forwarded as it is.
- **The site's port**, 4730: the players' site and the launcher's API. On the internet it goes behind
  [Caddy](https://caddyserver.com), which answers HTTPS on 443 (and plain HTTP on 80, sent on to HTTPS), gets the
  certificate from Let's Encrypt and renews it by itself.

The admin pages, a site of their own on port 4731, stay on the server PC: nothing of them is on the internet unless
you put them there too ([The admin pages](#the-admin-pages)).

The launcher asks the site for the game's port, so players type only the site's address.

## What you need

- **A name.** A domain of yours, or a free dynamic DNS name (your router may offer one: ASUS `*.asuscomm.com`, ipTIME
  `*.iptime.org`; else DuckDNS or No-IP). It follows your public address when it changes. A certificate needs a
  name: a bare address does not get one from Let's Encrypt.
- **Port forwards** on the router to the server PC: TCP 80, TCP 443 (and UDP 443 for HTTP/3) and TCP 4725 (and TCP
  4731 for the admin pages, only with `--admin-public`). With two routers in a row, each needs the forwards, the first
  pointing at the second.
- **NAT loopback** (hairpinning) for players on your own network who use the public name: most routers have it.

## With Docker

```sh
./dmt3 expose dmt3.example.org --email you@example.org
```

This writes Caddy's settings (`.edge/Caddyfile`), keeps the name in `.env`, and starts Caddy beside the server, in
the server's own network. From then on:

- the site answers at `https://dmt3.example.org/`, and the message to send a player and the invite carry that
  address (the one `setup --address` kept is set aside, and `expose --off` gives it back);
- the site's own port 4730 is no longer published: the site listens on the container's `127.0.0.1`, where Caddy
  reaches it, and believes the forwarded headers from that address alone (`--proxy 127.0.0.1`), so the server tells
  visitors apart and HTTPS sign-ins get secure cookies; the start banner in `./dmt3 logs` then names the site's
  name alone, as no address of this PC reaches the site's own port;
- every `./dmt3` command reads `packaging/docker/edge.yaml` after `compose.yaml`.

`./dmt3 check` says when the site answers over HTTPS, and who signed its certificate. Caddy's lines in `./dmt3 logs`
say what Let's Encrypt answered. The certificates stay in a volume of their own, so a restart or an update asks for
none again.

- `--staging`: Let's Encrypt's staging authority, to try the setup first. Browsers do not trust its certificates;
  run `expose` again without it once the site answers.
- `./dmt3 expose` alone says how the site is reached now; `./dmt3 expose --off` goes back to the site on its own
  port, Caddy goes, and the players' address is the one setup kept before (none if it kept none).
- When 80 or 443 is another program's, `./dmt3 ports --http 8080 --https 8443` publishes Caddy on others (the
  certificate then needs the router to forward 80 and 443 from outside to these); `expose` then names them in its
  line for the router ("forward TCP 80 to this PC's 8080 and TCP 443 to its 8443").

## The admin pages

Without more, `./dmt3 expose` leaves the admin pages where they were: on the server PC at `http://127.0.0.1:4731/`
(or the other PCs of your network, when `./dmt3 setup --admin-network yes` opened them), and nothing of them behind
Caddy. To run the server from anywhere:

```sh
./dmt3 expose dmt3.example.org --email you@example.org --admin-public
```

The admin pages are then at `https://dmt3.example.org:4731/`, through Caddy, over HTTPS with the site's certificate:
their own port on the same name, with their own sign-in (an account with admin rights). Forward TCP 4731 on the router
too, as `expose` says. The server PC opens them at that address too (the name must lead there: NAT loopback, as for
players on your own network): port 4731 of this PC is Caddy's HTTPS then, so `http://127.0.0.1:4731/` no longer
answers. `./dmt3 expose dmt3.example.org` without `--admin-public` takes them off the internet again, and
`./dmt3 expose --off` takes both.

With an address as the name (`./dmt3 expose 192.168.0.5 --local-ca --admin-public`, a closed network), the admin
pages are at `https://192.168.0.5:4731/`, with the address's certificate.

The server's own program takes the same `--admin-public` for the Caddy beside it ([below](#on-windows-or-with-python)).

## On Windows or with Python

The server's own command line writes the same settings for a Caddy you run beside it:

```sh
opendmt3-server expose dmt3.example.org --email you@example.org
```

It keeps the name, sets the server to listen for the site on this PC only behind the proxy, and writes `Caddyfile`
into the data folder. Restart the server (`opendmt3-server restart`), then run
[Caddy](https://caddyserver.com/download) with it: `caddy run --config "<data folder>\Caddyfile"`.
`opendmt3-server firewall` opens 80, 443 and the game's port on this PC; `expose --off` undoes it and gives back the
players' address setup kept.

With `--admin-public` the admin pages are there too, as with `./dmt3`:

```sh
opendmt3-server expose dmt3.example.org --email you@example.org --admin-public
```

They are then at `https://dmt3.example.org:4731/`: Caddy's HTTPS on their port, with the site's certificate. The admin
pages themselves move to the next port, 4732, on this PC alone, behind Caddy: the server PC opens them at
`http://127.0.0.1:4732/` too. Forward TCP 4731 on the router as well; on Windows `expose` asks to open that port in
the firewall. `opendmt3-server expose dmt3.example.org` without `--admin-public` takes them off the internet again
(and the port's rule out): Caddy with the new settings first (`caddy reload`), so it lets go of port 4731, then the
server's restart, as `expose` lists them (a restart while Caddy still has the port says so, and the server runs on as
it was). A port moved later with `opendmt3-server setup` moves in Caddy's settings
too, which Caddy reads when it starts again.

## Checking from outside

A check from inside your network does not prove the forwards work. From a phone on mobile data, open the site's
address; or ask a site such as [check-host.net](https://check-host.net) to fetch `https://dmt3.example.org/health`
and to connect to TCP 4725.

## What is open

- **The site**: every page asks for a sign-in first, but the sign-in page, its language switch, the licenses,
  `/health` and the launcher's updates when the server hands them out.
  Repeated wrong passwords are slowed down for each ID at each address, for each address and for each ID.
  Accounts are made by an admin; nobody makes their own.
- **The admin pages**: on the server PC (and your network when you opened them there) unless `--admin-public` puts
  them at `https://NAME:4731/`; then an admin's sign-in, over HTTPS, slowed down after wrong passwords as the site's
  is.
- **The API**: on the site's port, a named token on every request, an admin's for the admin calls ([The API](api.md)).
- **The game's port**: the game's own protocol, which carries a player's card number and no password, as the
  original service's did. A card number logs its player in by itself: [What to keep private](server.md#what-to-keep-private).
