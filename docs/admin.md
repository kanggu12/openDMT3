# The admin pages

For the server's owner: what each tab of **Admin** on the site does, what it keeps on disk, and its twin in the
[API](api.md). How to start a server and make its first account: [server.md](server.md).

The admin pages are part of the site, at `http://<server>:4730/admin/` (the launcher's built-in server: the address
its window shows). Only an account with admin rights opens them; to anyone else they answer as a page that is not
there. The first account, made on the server PC's own first-run page or with `--add-player ID --admin`, has them.

Every page is in English or Korean (the KOR / ENG buttons at the top; a cookie keeps the choice), works with the
keyboard alone, and names its charts and their parts for a screen reader. A question asked before something that
cannot be undone (a delete, a reset, a restore, stopping the server) opens in the site's own dialog, which starts on
Cancel.

## Players

Every account, with its role, its last sign-in, its last play, and a row of 14 small cells, one for each of the last
two weeks' days, oldest first, darker on days with more cleared stages (every row on one scale, so rows compare; the
number beside the row is its sum, and a cell's tip names its day). A column's header sorts by it: names from A, times
and counts from the highest first, and a second click the other way. The list starts sorted by the last play.

**Download CSV** gives every account as a spreadsheet: `login_id`, `dj_name`, `admin`, `disabled`, `last_sign_in`,
`last_play`, `plays` (every stage cleared) and `plays_14_days`, in UTF-8 with its mark (a spreadsheet opens Korean
names as they are), times in ISO 8601 on the server's clock.

Each row also has a new password, rename, admin rights, disable or enable, reset plays and delete; under the list,
reset every play. A new password, a reset and a delete ask first; a reset backs the database up first.

API: `GET /api/v1/players` (with `?sort=` and `?order=`, and each player's `days`, `plays` and `last_play`),
`GET /api/v1/players/download`.

## Cabinets

Every cabinet seen, by its address or the name given here, and who plays on each now.

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
- **Notice**: one line of up to 200 characters at the top of every page, set or cleared here.
- **Maintenance**: while it is on, the game server refuses card logins; cabinets online stay connected.

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
| The server's program, `opendmt3-server` | Its own `restart` and `stop`, named on the tab. | `opendmt3-server remove`, `--delete-data` with the data. |
| The launcher's built-in server | No buttons: the launcher started it, and its own window stops it. | The launcher's **Help**, **Uninstall**, which asks whether its data goes too. |
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
newest 200 requests the filter leaves, each with when, the method and path, the status, how long the answer took, the
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
