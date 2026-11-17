# The admin pages

For the server's owner: what each page of the admin site does, what it keeps on disk, and its twin in the
[API](api.md). How to start a server and make its first account: [server.md](server.md).

## The admin site

The admin pages are a site of their own, apart from the players' site: on the server PC at **`http://127.0.0.1:4731/`**
(the server's start banner names it on its **Admin** line; in Docker, `./dmt3 up` and `./dmt3 status` say it), on a
port of their own, `--admin-port` (4731). They listen on the server PC alone unless the owner opens them
(`--admin-host`); where else they can open, on the network, over the internet or in Kubernetes:
[server.md](server.md). `--admin-port 0` turns them off, and `--admin-on-site-port` serves them on the site's own port
too, at `/admin/`, for a setup with one port for everything.

- **Its own sign-in.** The admin site has its own door, with the family's mark (ADMIN beside DMT3, the server's version
  over it). Only an account with admin rights gets in; the right password of an account without them is told
  so ("This account has no admin rights."), and a wrong one gets the one sentence every wrong try gets. Signing in on
  the players' site never opens the admin site, nor the other way round: each keeps its own sign-in (its own cookie).
  Taking an admin's rights ends their sign-in here at once. Signing out on either site ends the account's sign-ins on
  both, as it ends them in every browser.
- **The first run.** On a server with no account yet, the first account (the owner's, with admin rights) is made on the
  admin site, from the server PC: opening the players' site there leads to it. `--add-player ID --admin` makes one
  from the command line.
- **The players' site.** Its menu has no admin pages. For a signed-in admin, its footer has **Admin pages** wherever
  they are within reach of that browser: on the server PC (in Docker too: a browser there opens the site by this PC's
  own name, `127.0.0.1` or `localhost`), on any PC of the network once the owner opened them there, and at their
  public address behind `--admin-public`. The admin pages' old addresses on the site's port
  (`http://<server>:4730/admin/...`) go on to the admin site from the same places (308, a form's POST kept), and are
  a page that is not there anywhere else.
- **The API** answers on both ports with the same tokens ([api.md](api.md)).
- **The launcher's own server** has an admin site of its own too, on this PC alone (`http://127.0.0.1:4731/`, or the
  next free port), which **Online**, **Admin pages** opens signed in as this PC's admin.
- **Their sign-ins**: each site's door counts its own wrong passwords, so guesses at the players' site never hold
  back the admin site's door, and the admin door never holds back a visit that only this PC can make (in Docker,
  with the admin port on this PC alone). No page of either site can be shown inside another site's frame.

**The frame.** The admin site is the server's control room: an opaque band with the mark, the pages across it as the
game's leaning keys (the page showing lit in TECHNIKA 3's blue), the language, who is signed in and **Sign out**; under
it on every page, the **rail**: the game server's lamp (lit while it is on) with its port, the cabinets connected and the
launchers heard in the last ten minutes (each leading to **Connected**), maintenance (pink while it is on, leading to
where it is switched), how long the server has run, and at its right end the players' site's address. Each page has its
name in chrome, and its cards a tab with their own. The footer leads back to the players' site. On a phone the band
keeps the mark, where one is and **MENU**, whose sheet holds the pages, the language, the players' site and **Sign
out**.

The pages: Status (the admin site opens there), Players, Connected (the cabinets and the launchers), Song list,
Backups, Logs, Server. Its links to a player's DJ page or a song go to the players' site.

Every page is in English or Korean (the KOR / ENG buttons in the band; a cookie keeps the choice, one for both sites; on
a phone they are in **MENU**), works with the keyboard alone, and names its charts and their parts for a screen reader. A
question asked before something that cannot be undone (a delete, a reset, a restore, stopping the server) opens in the
site's own dialog, which starts on Cancel. What a change did, or why it did not, is said in a toast in the bar's place
(done goes by itself, a refusal stays until closed), and a form sent from low on a page comes back to its own place; a
field's own mistake is said under that field. A long job (a song list's import, a restore) that ends while you are on
another page is told by a toast with the way to it.

## Players

Every account, with its role, its last sign-in, its last play, and a row of 14 small cells, one for each of the last
two weeks' days, oldest first, darker on days with more cleared stages (every row on one scale, so rows compare; the
number beside the row is its sum, and a cell's tip names its day). A column's header sorts by it: names from A, times
and counts from the highest first, and a second click the other way. The list starts sorted by the last play.

**Download CSV** gives every account as a spreadsheet: `login_id`, `dj_name`, `admin`, `disabled`, `last_sign_in`,
`last_play`, `plays` (every stage cleared) and `plays_14_days`, in UTF-8 with its mark (a spreadsheet opens Korean
names as they are), times in ISO 8601 on the server's clock.

The list is for looking; every change to a player is on their own page, which a player's ID or name opens
(`/admin/players/<ID>`): MAX points (set, added to, taken from, or unlimited), the level the game shows, a ban with its
reason, their DJ card and picture, a new password, a new DJ name, admin rights, reset plays, delete, and every change
made to them. A new password, a reset and a delete ask first; a reset backs the database up first. Under the list,
reset every play. Its API twin is `GET /api/v1/players/{login_id}` with a call for each control.

A ban ends the player's sign-ins at once, as a new password does: on the site, in the launcher, and their API tokens.
Lifting it does not bring them back: the player signs in again. Their card number stays, so the card logs in at the
cabinet again once the ban is lifted. Disabling an account from the list, without a reason, only holds its sign-ins
back while it is disabled.

API: `GET /api/v1/players` (with `?sort=` and `?order=`, and each player's `days`, `plays` and `last_play`),
`GET /api/v1/players.csv`.

## Connected

Who is on the server (how many now: the rail). Every cabinet seen, by its address or the name given here, and who plays
on each now;
then every launcher that signed in to the server since it started: its player (leading to their page), its PC's
address, its version, and when it was last heard, lit while that was within ten minutes. A launcher names itself in
each call (`openDMT3-launcher/<version>`); since any program can send that name, the calls that came without a
sign-in are only a count under the list (by address, an IPv6 /64 as one, for the last day). The server keeps what it
hears in memory, so a restart starts the list again.

API: `GET /api/v1/cabinets?all=1`, `GET /api/v1/launchers`.

## Status

From the top:

- **To look at**: each line only while it is so (no backup in a week, no song list, no installer, every other account
  disabled), with the tab that fixes it.
- **Who is here** and **the numbers**: when the server started, cabinets connected and seen, accounts, and the stages,
  players, sessions and time played today, in 7 days and in 30 days; the version, the database's size, the last
  backup, the game's port.
- **Resources**: the machine the server runs on. CPU in use now with how many processors, memory and the data
  folder's disk (used of their total, each with a thin meter), how long the machine has been up, and its load (not on
  Windows). Under them one chart each of CPU, memory and disk over the last 24 hours: a point every five minutes (the
  CPU's average over its five minutes; the tip of each hour gives its average and its peak), with a gap where the
  server was not running. While the server has run for less than a day, the card says since when it keeps them.
  **As a table** gives the 24 hours in numbers.
- **What takes the disk**: the data folder's disk as one bar and a table: the database, the backups, the song list
  (with its jackets and the DJ cards), downloads and updates, the logs, the disk's other files (not the server's) and
  what is free. Counted again at most once a minute.
- **When players play**: the stages cleared in the last 30 days as a grid of 7 days (Monday first) by 24 hours of the
  server's clock, darker with more; a cell's tip gives its count, and **As a table** each day's stages and its busiest
  hour.
- **The song list**: what it holds and when it was read ([server.md](server.md#the-song-list)).
- **Notice**: one line of up to 200 characters at the top of every page of the players' site, set or cleared here.
- **Maintenance**: while it is on, the game server refuses card logins; cabinets online stay connected. Every page of
  the players' site says so, and the admin site's rail shows it in pink.

API: `GET /api/v1/server` (the numbers, `look`, `song_list`, `hours` and `runner`), `GET /api/v1/status/machine` (the
machine now, the day's points and the disk's parts), `POST` and `DELETE /api/v1/notice` and `/api/v1/maintenance`.

## Server

The server itself: its version, since when it runs, the cabinets connected, what started it and its data folder, and
what these pages can ask the one that started it. Whoever starts the server stops it: the pages never end the process
on their own, they ask that one, and name the command where they cannot ask.

| Started by | Restart, Stop | Remove |
| :--- | :--- | :--- |
| The server's own command, `python -m opendmt3.server` | **Restart the server**: the command ends its server as Ctrl+C would (the site finishes the requests it is answering, the game server closes) and runs itself again in the same process, so the window or service that started it keeps it. **Stop the server**: the same, and the command returns. | **Delete the server's data**: the server stops, the database is copied beside the data folder (`data-last-<date>-<time>.sqlite` next to `data/`), then the data folder goes, with its accounts, plays, backups and song list. |
| Docker Compose (`./dmt3 up`) | No buttons: Compose starts the server again whenever its process ends. The tab names `./dmt3 restart` and `./dmt3 down`, for the server PC (the data stays in its volume). | The tab names `./dmt3 remove`, and `./dmt3 remove --delete-data` with the data. |
| The server's program, `opendmt3-server` (`run` in a window, or `start` in the background) | **Restart the server**: the running program ends its server and runs it again in the same process, in its window or in the background as before; `opendmt3-server restart` does the same. **Stop the server**: the same as `opendmt3-server stop`. | **Delete the server's data**: as for the server's own command; the firewall rules a Windows PC was given stay (`opendmt3-server remove` takes them out too). |
| The launcher's built-in server | No buttons: the launcher started it, and its own window stops it. | The launcher's **Help**, **Uninstall**, which asks whether its data goes too. |
| Kubernetes (the Helm chart) | No buttons: the cluster starts the server and keeps it running. The tab names `kubectl -n NAMESPACE rollout restart deployment/NAME` and `kubectl ... scale ... --replicas=0` and `=1`, with the release's names ([On Kubernetes](kubernetes.md#the-admins-server-tab)). | The tab names `helm -n NAMESPACE uninstall RELEASE`, and with the data `kubectl -n NAMESPACE delete pvc CLAIM` after it. |
| A container started by hand (`docker run`) | No buttons. The tab names `docker restart`, `docker stop` and `docker start` with the container's name. | The tab names `docker rm -f NAME`, and `docker rm -f -v NAME` with the volume the image makes for its data. |
| Anything else (a service manager of your own) | Stop it where it was started. | Remove it where it was installed. |

Each button asks first in the site's own dialog, with what goes and the cabinets connected now. Then the page that
answers says what happens next: after a stop or a removal, how to start the server again; after a restart, it waits
for the server and comes back to the tab by itself once it answers. The change log says who asked. A second press
while it is doing what it was asked changes nothing. A backup to keep elsewhere first: **Backups**.

API: `POST /api/v1/server/stop`, `POST /api/v1/server/restart` and `POST /api/v1/server/remove` (with
`{"delete_data": true}` for the data too) answer `202` and ask the runner half a second later, so the answer goes out
first; `409 not_here` names the command where the runner cannot be asked. `GET /api/v1/server`'s `runner` says what
it can be asked and the commands for the rest.

## Song list

Found on the server PC, another folder of it (a path, quick folders and a folder browser; not in Docker), or a song
list the launcher saved, uploaded. What it takes and why: [server.md](server.md#the-song-list).

An import runs as a job. When it is done within a few seconds, the tab says so at once; otherwise a progress card
follows it: a bar of how far the whole import has come, the step it is on (taking an archive's files out, checking an
uploaded song list, reading the songs, the jackets with how many of how many, the DJ cards, putting it in place), and
the steps it goes through. It moves by itself every second; once the import ends, the tab says how it ended. The
import goes on if the page is closed: opening the tab again with the same address follows it again.

## Logs

Three views:

- **Changes and messages**: what was done on these pages and by whom (accounts, cabinets, the notice, maintenance,
  backups, the song list, stopping the server), each in the reader's language, and the game messages the server
  received lately.
- **Plays**: every cleared stage, 50 a page, filtered by player, days and a word of the song's title, with what the
  filter leaves counted, and all of it as a CSV file.
- **Requests**: every page and API call the site answered.

### Requests

At the top, the last 24 hours as 48 half hours: requests answered (or sent on) in blue, those refused or failed in
pink on top of them, with a key, a tip for each half hour, and **As a table**. Under it a filter: a word of the path,
the address or the account's ID, and the kind of answer (answered 2xx, sent on 3xx, refused 4xx, failed 5xx). Then the
newest requests the filter leaves, 50 a page with newer and older pages, each with when, the method and path, the status, how long the answer took, the
address (a click filters by it) and the ID signed in. **Download CSV** gives every request the log keeps that the
filter leaves: `at`, `method`, `path`, `status`, `ms`, `address`, `who`.

What the log keeps:

- Each request is one line of JSON in `data/logs/requests.log`. The files every page loads (the style, the fonts, the
  jackets and the DJ cards' pictures), the health check and the progress card's own asks are left out: they are many
  and say nothing about who used the site.
- A one-use sign-in link from the launcher keeps its path without its token. The API's tokens are never in a line
  (they travel in a header), and `who` is only the ID signed in on the site.
- At 2 MB the file becomes `requests.log.1` (the one before `.2`, and so on), four files in all: 8 MB at most, whatever
  the traffic. A file whose newest line is older than 14 days goes too.
- The list and its filter read the newest 5,000 lines from the files when the tab is opened; the day is counted by
  half hours in memory for the chart, and read back from the files after a restart.
- The site writes the lines at most once a second, on a thread of the log's own after an answer, never on the loop the
  game server shares: the cabinets never wait for the log.

API: `GET /api/v1/log` (changes and messages), `GET /api/v1/log/plays` and `.csv`, `GET /api/v1/log/requests` and
`.csv` (with `?q=` and `?kind=`).

## Backups

The database once a day while the server runs (a week of each kind kept), one now, an upload (a backup from another
server or PC, checked before it is kept), download, restore and delete. A restore backs the current database up first,
and the game server's writes wait while it copies. It runs as a job: done within a few seconds, the tab says so at
once; otherwise the progress card follows it (checking the backup, backing the current one up, copying it in with how
many pages of how many, bringing it up to this version).

API: `GET` and `POST /api/v1/backups`, `POST /api/v1/backups/upload`, `GET` and `DELETE /api/v1/backups/{name}`,
`POST /api/v1/backups/{name}/restore`.

## Jobs

A long job (a song list's import, a restore) runs beside the request that started it, so a page or a program never
waits on an open connection for minutes. The pages follow it with the progress card; a program either waits for the
answer as before, or adds `?wait=0` and gets `202` with the job at once, then asks `GET /api/v1/jobs/{id}` for its
step, how far it has come (`share`, 0 to 1), and how it ended (`result` or `error`). `GET /api/v1/jobs` lists the last
hour's. One import runs at a time; a second is refused as busy while the first runs. Jobs are kept in memory for an
hour after they end: a restart forgets them, as it ends the work they followed.

## What the pages keep on disk

Beside the database, in the data folder:

| File | What | Its size |
| :--- | :--- | :--- |
| `machine.json` | The machine's last day for **Status**: a point every five minutes | A day's points at most, replaced whole: a few tens of KB |
| `logs/requests.log`, `.1` to `.3` | The requests log for **Logs**, **Requests** | 2 MB each, 8 MB in all, 14 days at most |
| `notice.json`, `maintenance.json` | The notice and maintenance | A line each |
| `backups/` | The backups | A week of each kind |

The launcher's **Delete all** takes these too, for its built-in server.
