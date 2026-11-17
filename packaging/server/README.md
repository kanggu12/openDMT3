# openDMT3 server

The openDMT3 server for DJMAX TECHNIKA 3's PC client: the game server for card logins and records, and the site with
rankings, songs, DJ pages, the launcher to download and the admin pages. This folder holds what the server needs and
nothing else: the launcher for Windows is its own download on the release's page.

## Quick start

### With Docker

On Linux, macOS or Windows in WSL 2, with Docker (Compose v2) and Python 3, in this folder:

```sh
./dmt3 setup
```

The wizard asks where your client data is (for the song list) and which installer to hand out, then gives the site's
address and the admin's password.

### With Python

On Linux, with Python 3.10 or newer, in this folder:

```sh
python3 -m venv .venv
.venv/bin/pip install starlette==0.47.3 jinja2==3.1.6 uvicorn==0.35.0 python-multipart==0.0.20 pillow==11.3.0
.venv/bin/python -m opendmt3.server --data data --catalog /path/to/your/client/data --setup-only
.venv/bin/python -m opendmt3.server --data data --host 0.0.0.0
```

## What it runs on

Docker with Compose v2 and Python 3, on Linux, macOS or Windows in WSL 2; or Python 3.10 or newer on Linux. Ports 4725
(the game) and 4730 (the site) open to the players' PCs. It held about 100 MB of memory with 64 cabinets and 20
visitors at once; its site works on two threads, and reading a song list uses up to eight cores. It needs only the
song list from the client data, about 13 MB. The players' launcher runs on 64-bit Windows 10 or 11, or on Linux with
Wine 11 ([Playing on your PC](docs/install.md)).

## Guides

- [Running a server](docs/server.md): every way to run it, the admin pages, backups, updating, over the internet.
- [The API](docs/api.md), [The client data](docs/client-data.md), [License and notice](docs/notice.md).

## License

MIT ([LICENSE](LICENSE)). openDMT3 holds no game files: the song list comes from your own client data.
