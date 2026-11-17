# The API

Everything the site shows and does can be read and done through this API too: the launcher uses it to sign players in
and out, and a program of your own can make accounts, back the database up or post the newest records. It lives on
the site's port under `/api/v1/`, takes JSON bodies and answers JSON, or a file where a call hands one out.
What each admin page shows and does, beside its calls here: [admin.md](admin.md).

## Signing in and out

`POST /api/v1/session` with `{"login_id": "NOVA", "password": "..."}` answers the account and a token:

```json
{"login_id": "NOVA", "dj_name": "DJ NOVA", "card": "...", "is_admin": false, "player": 2, "dj_card": {...}, "token": "..."}
```

Send the token with every other call as `Authorization: Bearer <token>`. It lasts 30 days, and stops working sooner
when the account's password changes or the account is banned (for good: lifting the ban does not bring it back),
while the account is disabled, or when the token is signed out:
`DELETE /api/v1/session`, sent with a token, ends that token and no other (the launcher's **Sign out** does so, and a
launcher signed in on another PC stays signed in). Signing out on the site ends the site's sign-ins, not the tokens.

Sign-ins answer `429` (`too_many_tries`) for a few minutes after too many wrong passwords from one address (the
addresses of one IPv6 /64 count as one) or for one ID, and past 20 sign-ins a minute from one address, right or wrong;
its `Retry-After` says how many seconds to wait. A sign-in from the server PC itself never waits for its ID.

```sh
TOKEN=$(curl -s -X POST http://SERVER:4730/api/v1/session -H 'Content-Type: application/json' \
  -d '{"login_id": "NOVA", "password": "pass1234"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
curl -s -H "Authorization: Bearer $TOKEN" http://SERVER:4730/api/v1/rankings
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" http://SERVER:4730/api/v1/session
```

## The OpenAPI document

`GET /api/v1/openapi.json` answers without a token: it holds no data. It is OpenAPI 3.1, for tools that read it (Swagger
UI, code generators): each call's method and path, who may make it (`x-who`: `anyone`, `signed in` or `admin`), its
parameters, its body, the main fields of its answer or the file it gives, and its errors. It is made from the table of
calls in `opendmt3/server/web/calls.py`, and `tests/server/test_api.py` checks that table against the routes the server
serves, against this guide (each call's who, what it takes and its errors) and against each call's real answer. This
guide stays the one written for people.

## Named tokens

A program of your own can sign in with a named token instead of a password: make one on **My account**, **API tokens**
(or with `POST /api/v1/tokens`), with a name that says what it is for and a scope. `read` makes `GET` calls only, and
none of an admin's; `write` makes every call its account may. The token (it starts with `odt3_`) shows once; the
server keeps only a hash of it, so a lost one cannot be shown again: make another. Send it as any token,
`Authorization: Bearer <token>`.

A named token does not expire. It acts as its account, with the account's rights at each call: it stops while the
account is disabled and goes with the account. Revoking it (on the page, with `DELETE /api/v1/tokens/{id}`, or with
`DELETE /api/v1/session` sent with it) ends it for good, and so do a new password for the account and a ban. What a call
changes goes into the change log under the ID with the token's name: `NOVA (token nightly backup)`. A read-only token
gets `403 read_only` for anything but a `GET` and for an admin's call, and no admin's part of an answer (the cabinets'
addresses, who set the notice). A restore puts the tokens back as the backup has them, as it does the passwords.

```sh
curl -s -H "Authorization: Bearer odt3_..." 'http://SERVER:4730/api/v1/plays?records=1'
```

## Calls

**Who** may call: `anyone`, without a token; `signed in`, with the token of any account; `admin`, with an admin
account's token. **Takes** is what a call reads: the fields of its JSON body (`{"name"}`) or of its query (`?mode=`);
a `{name}` in a path is part of the address. **Errors** are the call's own. Besides them, a call that needs a token
answers `401 sign_in` without one that works, an admin's call answers `403 admin_only` to another account's token,
and a read-only named token gets `403 read_only` for anything but a `GET` and for an admin's call
([Errors](#errors)). Words meant for people in an answer (a message to send, a line to look at, a font's faces) are in
English, or in Korean with `?lang=ko`. What a call changes goes into the change log (**Admin**, **Logs**) under the
caller's ID, as the same change on the site does.

### The server, signing in and out

| Call | Who | Takes | Answers | Errors | The page |
|---|---|---|---|---|---|
| `GET /health` | anyone | | `{"ok": true, "version", "run"}` (`run` a mark of this run of the server, new at each start), or `503` with `{"ok": false, "version", "reason"}` while the database cannot be opened or written (what the Docker image's health check reads) | | (none) |
| `GET /api/v1/status` | anyone | | `{"server": "openDMT3", "version", "game_port", "updates"}`; `updates` is whether `/updates/` hands out the launcher's update packages | | (the launcher's server check) |
| `GET /api/v1/openapi.json` | anyone | | the OpenAPI 3.1 document of every call under `/api/v1/` (below) | | (programs that read OpenAPI) |
| `GET /updates/{name}` | anyone | | one file of the launcher's update feed in `data/updates/`: `releases.win.json`, a `.nupkg` or its `.sig` | `404` (as text) for any other name | (the launcher's updates) |
| `POST /api/v1/session` | anyone | `{"login_id", "password"}` | the account and a token (above) | `400 bad_request`, `401 wrong_sign_in`, `403 banned` (the right password of a banned account: the error has the ban's `reason` beside its `message`), `429 too_many_tries` | Sign in |
| `DELETE /api/v1/session` | signed in | | `{"signed_out": true}`: the token sent no longer works (a named token is revoked); the account's other tokens and its sign-ins on the site go on | | Sign out |
| `GET /api/v1/licenses` | anyone | `?lang=` | `{"own": {"name", "text"}, "parts": [{"part", "used_for", "license"}], "licenses": [{"name", "faces", "text"}]}`: openDMT3's own license (its text `null` when the server has no `LICENSE` beside the package), the parts the server and the launcher it hands out are made with, each with what it is used for and its license, and the fonts the site serves, each license with the faces it covers and its text in full | | Licenses |

### Your account

| Call | Who | Takes | Answers | Errors | The page |
|---|---|---|---|---|---|
| `GET /api/v1/me` | signed in | | the account: `login_id`, `dj_name`, `card` (the number the game logs in with), `is_admin`, `player` (its number), `dj_card` (below) | | Home, your DJ |
| `POST /api/v1/me/dj_name` | signed in | `{"dj_name"}` | the account, renamed | `400 bad_request`, `400 refused` (1 to 8 characters) | My account, DJ name |
| `POST /api/v1/me/password` | signed in | `{"password": <current>, "new_password"}` | the account and a new token: a new password gives a new card, and the old tokens end | `400 bad_request`, `400 refused` (6 to 16 letters and digits), `403 wrong_password`, `429 too_many_tries` | My account, password |
| `POST /api/v1/me/dj_card` | signed in | any of `{"icon", "plate", "pattern", "comment"}` | the account with its card: numbers from `GET /api/v1/dj_cards`, a comment of up to 12 characters | `400 bad_request`, `400 refused` (a number without a picture, a longer comment) | My account, DJ card |
| `GET /api/v1/dj_cards` | signed in | | the choices this server has pictures for: `{"icon": [{"number", "grade"}], "plate": [...], "pattern": [...], "comment_max": 12}`; empty lists before it read them from its owner's game files | | My account, DJ card |
| `GET /api/v1/dj_cards/{kind}/{number}.png` | signed in | `kind`: `icon`, `plate` or `pattern` | one choice's picture (PNG) | `404 not_found` | My account, DJ card |
| `GET /api/v1/tokens` | signed in | | `{"tokens": [{"id", "name", "scope", "created_at", "used_at"}]}`: your named tokens, newest first, with when each was made and last used (null: never); never the tokens themselves | | My account, API tokens |
| `POST /api/v1/tokens` | signed in | `{"name", "scope"}`, `scope` `read` or `write` | `201` with the token's `id`, `name`, `scope`, `created_at`, `used_at` and `token`, the token itself, which this answer alone has | `400 bad_request`, `400 refused` (a name of 1 to 40 characters on one line, a scope of `read` or `write`, 20 tokens at most) | My account, make a token |
| `DELETE /api/v1/tokens/{id}` | signed in | | `{"revoked": id, "name"}`: the token ends for good (it may be the one calling) | `404 unknown_token` | My account, revoke a token |
| `POST /api/v1/me/picture` | signed in | the picture itself as the body: PNG, JPEG, WebP or GIF, up to 2 MB and 4096 × 4096 pixels | the account with `picture`, how many pictures it has had (its address `/pictures/{player}.png?v={picture}` changes with each); the server keeps a square of 256 pixels cut from the middle, made again from its pixels alone. The site's own: the game shows the DJ icon | `400 refused` (not a picture), `413 too_large` | My account, Profile, picture |
| `DELETE /api/v1/me/picture` | signed in | | the account with `picture` 0 | | My account, Profile, remove the picture |
| `DELETE /api/v1/me/sign_ins` | signed in | | `{"signed_out": true}`: every sign-in on the site ends; the launcher's tokens and the token calling go on | | My account, Security, sign out everywhere else |
| `DELETE /api/v1/me` | signed in | `{"password"}` | `{"deleted": login_id}`: the account goes with its plays, DJ card and picture, and its card stops logging in | `400 bad_request`, `400 refused` (the server's only enabled admin), `403 wrong_password`, `429 too_many_tries` | My account, Security, delete the account |

### Records

| Call | Who | Takes | Answers | Errors | The page |
|---|---|---|---|---|---|
| `GET /api/v1/plays` | signed in | `?everyone=1`, `?records=1` | `{"plays", "total"}`: your 50 newest cleared stages, or the server's with `everyone`, and how many there are in all. Each play has `before` (the player's best on its chart before it, null before their first play of the chart), `new` (it beat that best: NEW) and `gain` (by how much). With `records`, `{"plays"}`: the server's 50 newest records, plays that beat their player's best on a chart (a first play never does) | | Home: your recent plays, recent plays on this server, new records |
| `GET /api/v1/rankings` | signed in | `?mode=` (0 to 255, 0 is STAR; without it, the first mode played), `?by=` (`total`, `best30` or `month`) | one mode's ranking (below). By `total`, each player's best scores added up; by `best30`, the average of each player's 30 best charts (charts not cleared count as 0; `charts` is how many of the 30); by `month`, this calendar month's totals on the server's clock, with `start` (the month's first moment) and `past` (the first three of each of the 12 months before it that anybody played in, `[{"start", "rows"}]`, newest first) | `400 bad_request` | Rankings; Home, top DJs (the first five rows by total) |
| `GET /api/v1/songs` | signed in | `?q=` | `{"songs", "total"}`: every song with its plays, players, best score and whether it has a jacket (`jacket`), the most played first; with `q`, only those whose title or composer has it in any case, or whose number it is. `total` counts every song | | Songs, and its Find |
| `GET /api/v1/songs/{number}` | signed in | | one song's boards, one per chart (below) | `404 unknown_song` | A song |
| `GET /api/v1/songs/{number}/jacket.png` | signed in | | the song's jacket (PNG), read from its owner's game files | `404 not_found` | Songs and a song (`/jackets/{number}.png`) |
| `GET /api/v1/djs/{player}` | signed in | | a player's records (below): `dj_card`, counts, best scores, recent plays, `activity` (stages per week for 12 weeks, per mode, most played songs, sessions, seconds played) and `places`, their place in each mode's ranking by total (`[{"mode", "mode_name", "place", "of"}]`) | `404 unknown_player` | A DJ (`/dj/{player}`) |
| `GET /api/v1/djs/{player}/picture.png` | signed in | | a player's picture (PNG, 256 × 256) | `404 not_found` (none, or a disabled account's) | A DJ, My account (`/pictures/{player}.png`) |
| `GET /api/v1/cabinets` | signed in | `?all=1` (an admin's) | the cabinets connected now: `{"cabinets": [{"player"}]}`, `player` the DJ name on each (null when free); an admin's token also gets each one's `address`, `version` and `login_id`. With `all`, every cabinet seen: `id`, `host`, `name`, `version`, `first_seen`, `last_seen`, `sessions`, `plays`, `connected`, `player` | `403 admin_only` (`all` with a player's token), `403 read_only` (`all` with a read-only token) | Home, cabinets; Admin, cabinets |

### Downloads

| Call | Who | Takes | Answers | Errors | The page |
|---|---|---|---|---|---|
| `GET /api/v1/download` | signed in | | `{"installer", "address", "file"}`: the installer's `size`, `at` (when it was put there) and `version` (null when the file has none), or null without an installer; the address the launcher asks for, and the name the installer comes under, both from the address the call came to | | Download |
| `GET /api/v1/download/windows` | signed in | | the installer with this server's address on its end, so the launcher it installs starts on this server, named after that address | `404 no_installer` | Download, the button |

### The admin's players

| Call | Who | Takes | Answers | Errors | The page |
|---|---|---|---|---|---|
| `GET /api/v1/players` | admin | `?sort=` (`id`, `dj`, `last`, `played`, `days` or `plays`; `id` when not given), `?order=` (`asc` or `desc`) | `{"players", "sort", "order", "days_from"}`: every account as `GET /api/v1/me` gives one, with `disabled`, `last_login`, `last_play` (null: never), `plays` (every stage it cleared) and `days`, its stages each day of the last 14 (oldest first, today last), sorted by the column `sort` names (`last` the last login, `played` the last play, `days` the 14 days' sum) in its first order (names from A, times and counts from the highest) or `order`'s; `days_from` is the first day's start | | Admin, players |
| `GET /api/v1/players.csv` | admin | | every account as CSV (UTF-8 with its mark, times in ISO 8601 with the server's offset): `login_id`, `dj_name`, `admin`, `disabled` (1 or 0), `last_sign_in`, `last_play`, `plays`, `plays_14_days` | | Admin, players, CSV |
| `POST /api/v1/players` | admin | `{"login_id", "password", "dj_name", "is_admin"}`, `?lang=` | `201` with the account made, its `password` (made by the server when none is sent: 8 letters and digits) and `message`, the message to send the player: the address the call came to, the ID, the password and the steps. The password shows this once | `400 bad_request`, `400 refused` (the rules for an ID, a password and a DJ name; an ID taken) | Admin, make an account |
| `POST /api/v1/players/{login_id}/password` | admin | `?lang=` | `{"login_id", "password", "message"}`: a new password (and card) made by the server, and the message to send | `404 unknown_player` | Admin, new password |
| `POST /api/v1/players/{login_id}/dj_name` | admin | `{"dj_name"}` | `{"login_id", "dj_name"}` | `400 bad_request`, `400 refused` (1 to 8 characters), `404 unknown_player` | Admin, rename |
| `POST /api/v1/players/{login_id}/admin` | admin | | `{"login_id", "is_admin": true}`: the account opens the admin pages too | `404 unknown_player` | Admin, give admin rights |
| `DELETE /api/v1/players/{login_id}/admin` | admin | | `{"login_id", "is_admin": false}` | `400 refused` (the only enabled admin keeps the rights), `404 unknown_player` | Admin, take admin rights |
| `POST /api/v1/players/{login_id}/disable` | admin | | `{"login_id", "disabled": true}`: the account cannot log in at the cabinet or sign in, and leaves the rankings | `400 refused` (the only enabled admin stays enabled), `404 unknown_player` | Admin, disable |
| `POST /api/v1/players/{login_id}/enable` | admin | | `{"login_id", "disabled": false}` | `404 unknown_player` | Admin, enable |
| `DELETE /api/v1/players/{login_id}` | admin | | `{"deleted": login_id}`; the account's plays go with it | `400 refused` (your own account), `404 unknown_player` | Admin, delete |
| `DELETE /api/v1/players/{login_id}/plays` | admin | | `{"login_id", "plays", "kept_as"}`: the player's plays go (`plays`, how many), after a backup of the database (`kept_as`, a backup of the kind `reset`); the account, its DJ card and its settings stay | `404 unknown_player` | Admin, players, reset plays |
| `DELETE /api/v1/plays` | admin | | `{"plays", "kept_as"}`: every player's plays go, after a backup of the database, as for one player | | Admin, players, reset every play |
| `GET /api/v1/players/{login_id}` | admin | | one player as their page shows them (below) | `404 unknown_player` | Admin, a player (`/admin/players/{login_id}`) |
| `POST /api/v1/players/{login_id}/max_points` | admin | one of `{"amount"}` (the balance, 0 to 999999), `{"add"}` (added, below 0 taken, kept within 0 to 999999) or `{"unlimited"}` (true or false) | the player (below). MAX points are the game's currency: the game shows the balance beside the DJ name on the song select from the next card login, adds what each session earns (the server keeps what the game reports, at most 4,000 a login), and with `unlimited` shows 999999 | `400 bad_request`, `400 refused`, `404 unknown_player` | Admin, a player, MAX points |
| `POST /api/v1/players/max_points` | admin | `{"add", "login_ids"}`, `login_ids` a list of IDs (without it: every player) | `{"players"}`: how many balances changed, each kept within 0 to 999999 | `400 bad_request`, `400 refused`, `404 unknown_player` | (programs: MAX points for many players) |
| `POST /api/v1/players/{login_id}/level` | admin | `{"level"}`, 1 to the game's last (99) | the player: the game shows that level from the next card login, and it grows from there as they clear stages (`exp_extra`, the change on top of `exp_plays`) | `400 bad_request`, `400 refused` (no table of levels before the song list is read), `404 unknown_player` | Admin, a player, level |
| `DELETE /api/v1/players/{login_id}/level` | admin | | the player, the level of their cleared stages again | `404 unknown_player` | Admin, a player, back to the level of their plays |
| `POST /api/v1/players/{login_id}/ban` | admin | `{"reason"}`, one line of 1 to 120 characters | the player, banned: the game refuses their card, the site and the launcher their sign-in (telling them the reason), and they leave the rankings. Their sign-ins on the site, their sign-in tokens and their named tokens end at once, as a new password ends them; the card number stays | `400 bad_request`, `400 refused` (a reason's rules, the only enabled admin), `404 unknown_player` | Admin, a player, ban |
| `DELETE /api/v1/players/{login_id}/ban` | admin | | the player, enabled again: their card logs in again, and they sign in anew (what the ban ended stays ended) | `404 unknown_player` | Admin, a player, lift the ban |
| `POST /api/v1/players/{login_id}/dj_card` | admin | any of `{"icon", "plate", "pattern", "comment"}` | the player with their card, by the rules of `POST /api/v1/me/dj_card` | `400 bad_request`, `400 refused`, `404 unknown_player` | Admin, a player, DJ card |
| `DELETE /api/v1/players/{login_id}/picture` | admin | | the player, without their picture | `404 unknown_player` | Admin, a player, remove the picture |

### The admin's cabinets, status, notice and logs

| Call | Who | Takes | Answers | Errors | The page |
|---|---|---|---|---|---|
| `POST /api/v1/cabinets/{id}/name` | admin | `{"name"}` (empty: its address again) | `{"cabinets"}`: every cabinet, as `GET /api/v1/cabinets?all=1` | `400 bad_request`, `404 unknown_cabinet` | Admin, cabinets, name |
| `GET /api/v1/server` | admin | `?lang=` | version, start time, connected cabinets, accounts, plays, players, sessions and time played today, in 7 days and in 30 days, database size, last backup, `maintenance` (whether it is on), and `look`, what may want a look (each only while it is so): `[{"key", "values", "href", "text"}]`, `key` one of `backup` (none in 7 days), `songs` (no song list), `installer` (none to hand out) and `accounts` (every account but yours disabled), `href` the page that fixes it, and `song_list`, the Song list card: `songs`, `jackets` and `cards`, each `{"count", "at"}` (`at` when it was last read, or null; the cards' `count` is `{"icon", "plate", "pattern"}`), `missing`, `[{"part", "why", "key"}]` for each part with nothing in it or not read the last time (`why` the last reading's reason as a sentence, `key` its words' key, or null), `read_at`, `source` (where the last reading came from: `{"from", "path", "made"}`, `from` one of `folder`, `archive` and `file`, `made` when a song list was saved), `read_again` (whether the server was given client data to read again), `folder` and `command`, the command that imports it on the server PC; `hours`, when players play: `{"days": 30, "grid", "most"}`, `grid` 7 rows (Monday first) of 24 counts, the stages cleared in each hour of the server's clock over the last 30 days; and `runner`, who started the server: `{"kind", "can", "commands", "asked", "can_stop", "command", "stopping"}`, `kind` one of `python` (the server's own command), `standalone` (the server's program, `opendmt3-server`), `launcher`, `docker` (Docker Compose), `kubernetes` (a cluster, the Helm chart's; its `commands` the helm and kubectl ones with the release's names), `container` (a container started by hand; Docker's own commands by its name) and `other`, `can` what these pages can ask it (`stop`, `restart`, `remove`), `commands` the commands that do the rest on the server PC (`start`, `stop`, `restart`, `remove`, `remove_data`; null where there is none), `asked` what it was asked (null before), `command` the stop command | | Admin, status |
| `GET /api/v1/server/invite` | admin | `?format=svg` (the QR code itself, `image/svg+xml`) | `{"address", "reached", "svg"}`: the site's address for players (the one the server was given, `--site-address`, else the one this request came to), whether another PC reaches it (not `127.0.0.1` or `localhost`), and its QR code as an SVG picture, dark on white | | Admin, players, invite |
| `GET /api/v1/status/machine` | admin | | the machine now and over the last day: `cores`, `uptime` (seconds, null where not known), `cpu` (percent in use now, null while measuring or where not known), `memory` and `disk` (`{"total", "used"}` in bytes, the disk's `free` too; the disk is the data folder's), `load` (1, 5 and 15 minutes; null on Windows), `since` (when the day's points begin), `every` (seconds a point covers: 300) and `points`, oldest first, at most a day's 288: `[{"at", "cpu", "peak", "memory", "disk", "cabinets"}]` (average and peak processor use, memory and disk in use in percent, cabinets connected), and `disk_parts`, what takes the disk: `[{"part", "bytes"}]`, `part` one of `database`, `backups`, `song_list`, `downloads`, `logs`, `other` (files that are not the server's) and `free` | | Admin, status, resources |
| `POST /api/v1/server/stop` | admin | | `202` with `{"asked": "stop", "stopping": true, "runner"}`: the one that started the server is asked to stop it (`runner` as `GET /api/v1/server` gives it), half a second after this answer; the change log says who | `409 not_here` (the server's runner cannot be asked from here: Docker Compose, which starts it again when it ends, a Kubernetes cluster, a container started by hand, the launcher, or a way it cannot tell; the message and `runner.commands` say how), `409 asked_already` (it is doing what it was asked) | Admin, server, stop |
| `POST /api/v1/server/restart` | admin | | `202` with `{"asked": "restart", "stopping": true, "runner"}`: the one that started the server is asked to stop it and start it again (the server's own command runs itself again in the same process); `GET /health` answers again once it is back | `409 not_here`, `409 asked_already` | Admin, server, restart |
| `POST /api/v1/server/remove` | admin | `{"delete_data"}` (`false` when not sent) | `202` with `{"asked": "remove", "delete_data", "stopping": true, "runner"}`: the one that started the server is asked to stop it and remove it; with `delete_data` its data folder goes too, after a last copy of the database beside it (`<folder>-last-<time>.sqlite`) | `400 bad_request` (a body that is not `{"delete_data": true or false}`), `409 not_here` (removed by what installed it: `runner.commands.remove` and `remove_data` name the commands), `409 asked_already` | Admin, server, remove |
| `GET /api/v1/jobs` | admin | `?lang=` | `{"jobs"}`: the long jobs (song list imports, restores) of the last hour, newest first, each as `GET /api/v1/jobs/{id}` gives it | | Admin, song list and backups, the progress card |
| `GET /api/v1/jobs/{id}` | admin | `?lang=` | one job: `id`, `kind` (`song_list` or `restore`), `who`, `state` (`running`, `done` or `failed`), `started`, `ended`, `step` (the step it is on, null before the first), `steps` (the job's steps in order), `done` and `total` (how far into the step, when it counts: jackets saved, pages copied), `share` (how far the whole job has come, 0 to 1), `details`, `result` (once done: the import's report, or `{"restored", "kept_as"}`), `error` (once failed: `{"code", "message"}`), and in the words asked for `title`, `step_text`, `count_text` and `text` (the step, or how it ended) | `404 unknown_job` (never started, or ended more than an hour ago) | Admin, the progress card |
| `GET /api/v1/server/song_list` | admin | `?lang=` | the Song list tab: `song_list` as `GET /api/v1/server` gives it, `found`, the game's files found on the server PC (`[{"path", "kind", "ready", "line", "key", "values", "text"}]`: `kind` one of `folder`, `archive`, `song list`, `part` and `file`, `line` its one line in English and `text` in the words asked for), `places`, the folders looked in, and `browse`, whether the server shows its PC's other folders (not in Docker, where it sees only the folder kept for it) | | Admin, song list |
| `POST /api/v1/server/song_list` | admin | nothing (the client data the server was given), `{"path"}` (the client data in a folder or an archive, or a song list, on the server PC), or a song list itself as the body (`Content-Type: application/zip`), up to 64 MB; `?wait=0` | `{"song_list", "lines", "job"}`: the song list (with its jackets and the DJ cards) imported, `song_list` as `GET /api/v1/server` gives it, `lines` the reading's own, one per part, and `job` the job's id. The import runs as a job: the call waits for its end, or with `?wait=0` answers `202` with `{"job"}` at once, to follow at `GET /api/v1/jobs/{id}`. A song list is checked as an upload from anyone: only its own names and kinds, sizes capped, its tables' shapes, every picture decoded and encoded again; nothing changes until all of it passed | `400 bad_request` (a JSON body without a path), `400 refused` (the path or the file is not what the server takes; its one line in the message), `404 no_game_folder` (no body, and no client data given: `--game`, in Docker `GAME_DIR`), `409 busy` (another import is going), `409 not_read` (the song list cannot be read; the reason in the message), `413 too_large` (past 64 MB) | Admin, song list, import and upload |
| `GET /api/v1/server/folders` | admin | `?path=` (the top, `/`, when not given) | `{"path", "up", "folders"}`: a folder of the server PC, the one above it (null at the top) and the folders in it by name (hidden ones, and the folder in the client data that holds the game's files, left out) | `400 refused` (a folder the server cannot read) | Admin, song list, another folder |
| `GET /api/v1/notice` | signed in | | `{"notice": {"text", "at"}}`, the line at the top of every page, or `{"notice": null}`; an admin's token also gets `by`, who set it | | The notice on every page |
| `POST /api/v1/notice` | admin | `{"text"}` (empty: cleared) | the notice as `GET` gives it | `400 bad_request`, `400 refused` (one line of up to 200 characters) | Admin, status, notice |
| `DELETE /api/v1/notice` | admin | | `{"notice": null}` | | Admin, status, clear the notice |
| `GET /api/v1/maintenance` | signed in | | `{"on": false}`, or `{"on": true, "at"}` while the server is in maintenance (the game server refuses card logins); an admin's token also gets `by`, who turned it on | | The maintenance line on every page |
| `POST /api/v1/maintenance` | admin | | maintenance on, as `GET` gives it: from now the game server answers every card login as a failed one, while the cabinets online stay connected and a game being played keeps its results; on already, nothing changes | | Admin, status, start maintenance |
| `DELETE /api/v1/maintenance` | admin | | `{"on": false}`: the cabinets log in again | | Admin, status, end maintenance |
| `GET /api/v1/log` | admin | | `{"changes": [{"at", "who", "what"}], "messages": [{"at", "cabinet", "header", "name", "size", "handled", "bytes"}], "counts": {"changes", "messages"}}`: the newest 100 changes and 200 messages, and how many there are in all; `bytes` (the start of the message, in hex) is empty for messages with a handler | | Admin, logs |
| `GET /api/v1/log/plays` | admin | `?player=` (an account number), `?days=` (1, 7 or 30), `?q=` (a word of the song's title, or its number), `?page=` (from 1) | every play the filter leaves, 50 a page, newest first: `{"plays": [{"id", "at", "player", "dj", "login_id", "mode", "mode_name", "song", "title", "pattern", "level", "score"}], "totals": {"plays", "players", "charts"}, "older", "newer", "page", "people"}`. `totals` counts the plays, players and charts of every page the filter leaves, `older` and `newer` say whether there are older and newer pages, `people` are the accounts to filter by (`id`, `login_id`, `dj_name`) | `400 bad_request` (a value that cannot be read) | Admin, logs, plays |
| `GET /api/v1/log/requests` | admin | `?q=` (a word of the path, the address or the account's ID), `?kind=` (`ok`, `moved`, `refused` or `failed`: 2xx, 3xx, 4xx or 5xx, or a status itself) | the requests log: `{"chart": [{"at", "ok", "bad"}], "most", "day": {"ok", "bad"}, "requests": [{"at", "method", "path", "status", "ms", "address", "who"}], "found", "kept", "bytes"}`. `chart` is the last day in 48 half hours (`at` each one's start; `ok` answered or sent on, `bad` refused or failed), `requests` the newest 200 the filter leaves of the newest `kept` (5000) the log's files hold, newest first, `found` how many of those it leaves, `bytes` what the log's files take. `who` is the ID signed in on the site (null for the API's tokens and visitors); a one-use sign-in link's path is kept without its token | `400 bad_request` (a kind that cannot be read) | Admin, logs, requests |
| `GET /api/v1/log/requests.csv` | admin | `?q=`, `?kind=`, as `GET /api/v1/log/requests` | every request the log's files keep that the filter leaves, oldest first, as CSV (UTF-8 with its mark, times in ISO 8601 with the server's offset): `at`, `method`, `path`, `status`, `ms`, `address`, `who` | `400 bad_request` | Admin, logs, requests, CSV |
| `GET /api/v1/log/plays.csv` | admin | `?player=`, `?days=`, `?q=`, as `GET /api/v1/log/plays` (every page) | every play the filter leaves, all of its pages, as CSV (UTF-8 with its mark, times in ISO 8601 with the server's offset): `when`, `dj`, `mode`, `song`, `title`, `pattern`, `score` | `400 bad_request` | Admin, logs, plays, CSV |

### The admin's backups

| Call | Who | Takes | Answers | Errors | The page |
|---|---|---|---|---|---|
| `GET /api/v1/backups` | admin | | `{"backups": [{"name", "kind", "at", "size"}], "keep"}`, newest first; `kind` is `daily`, `manual` (backed up now), `restore` (before a restore), `reset` (before plays were reset) or `upload`, and `keep` how many of each kind stay | | Admin, backups |
| `POST /api/v1/backups` | admin | | backs the database up now: `201` with `{"made": name}` | | Admin, back up now |
| `POST /api/v1/backups/upload` | admin | the database file itself as the body (`Content-Type: application/octet-stream`), up to 256 MB | `201` with `{"uploaded": name}`: the file is checked (an SQLite file whose integrity check passes, with this project's tables at a version this server opens) and kept as a backup of the kind `upload`, to restore as any other | `400 refused` (not an SQLite file, damaged, not an openDMT3 database, from a newer openDMT3, an empty body), `413 too_large` (past 256 MB) | Admin, backups, upload |
| `GET /api/v1/backups/{name}` | admin | | the backup's SQLite file | `404 unknown_backup` | Admin, download |
| `DELETE /api/v1/backups/{name}` | admin | | `{"deleted": name}` | `404 unknown_backup` | Admin, delete |
| `POST /api/v1/backups/{name}/restore` | admin | `?wait=0` | puts the database back to it, backing the current one up first: `{"restored", "kept_as"}`. The restore runs as a job: the call waits for its end, or with `?wait=0` answers `202` with `{"job"}` at once, to follow at `GET /api/v1/jobs/{id}` | `400 refused` (a backup from a newer openDMT3), `404 unknown_backup` | Admin, restore |

A backup kept elsewhere goes back on the server as an upload, then a restore:

```sh
NAME=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/octet-stream' \
  --data-binary @openDMT3-20261101-040000-daily.sqlite http://SERVER:4730/api/v1/backups/upload \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["uploaded"])')
curl -s -X POST -H "Authorization: Bearer $TOKEN" http://SERVER:4730/api/v1/backups/$NAME/restore
```

Pages and calls about other players name them by their account number (`player`), never by their login ID,
which is half of what signs them in. The cabinets' addresses and the login IDs on them are for admins only. The
owner's first account, made on the server PC's own page while the server has none, has its twin on the command line:
`--add-player ID --admin` ([server.md](server.md)).

### Shapes

A ranking (`mode` is 0 to 255, 0 is STAR; without it, the first mode played; the modes played are in `modes`).
Equal totals share a place:

```json
{"mode": 0, "name": "STAR", "modes": [0], "by": "total",
 "rows": [{"place": 1, "player": 2, "dj_name": "DJ NOVA", "total": 1400, "charts": 2}]}
```

By `month`, the same with this month's rows, and the months before it (here on a server whose clock is UTC):

```json
{"mode": 0, "name": "STAR", "modes": [0], "by": "month", "start": 1793491200,
 "rows": [{"place": 1, "player": 2, "dj_name": "DJ NOVA", "total": 900, "charts": 1}],
 "past": [{"start": 1790812800, "rows": [{"place": 1, "player": 3, "dj_name": "RIO", "total": 1300, "charts": 1}]}]}
```

A play, as `GET /api/v1/plays` lists it:

```json
{"song": 1, "title": "...", "pattern": 1, "score": 1300, "mode": 0, "mode_name": "STAR", "dj": "RIO", "player": 3,
 "level": 7, "at": 1762560600, "before": 1200, "new": true, "gain": 100}
```

A song. A chart is one pattern of the song in one mode; each board has every player's best on it, with when it
was set (seconds since 1970). Songs come from the server's song list (imported on the Song list tab, or with
`--catalog`);
a song that was played but is not in the list has `#` and its number as its title (`#2`):

```json
{"number": 1, "title": "...", "genre": "...", "composer": "...",
 "charts": [{"mode": 0, "mode_name": "STAR", "pattern": 1,
             "rows": [{"place": 1, "player": 3, "dj_name": "RIO", "score": 1300, "at": 1762560600}]}]}
```

A player's records:

```json
{"player": 3, "dj_name": "RIO", "summary": {"plays": 1, "songs": 1, "charts": 1, "last": 1762560600},
 "bests": [{"song": 1, "title": "...", "mode": 0, "mode_name": "STAR", "pattern": 1, "score": 1300, "at": 1762560600}],
 "recent": [{"song": 1, "title": "...", "pattern": 1, "score": 1300, "mode": 0, "mode_name": "STAR", "dj": "RIO",
             "player": 3, "at": 1762560600}],
 "places": [{"mode": 0, "mode_name": "STAR", "place": 1, "of": 2}]}
```

A DJ card, as `dj_card` in the account and a player's records:

```json
{"icon": 6, "plate": 32768, "pattern": 7, "comment": "HELLO", "exp": 1000, "level": 10, "pictures": true,
 "max_points": 4200}
```

`exp` is the experience the game is sent: that of the stages the player cleared, with an admin's change of the level
on top. `level` is the level the game shows for it (null before the server read its owner's game files).
`pictures` is whether the server has the pictures to show the card. `max_points` is what the song select shows beside
the name: the balance, or 999999 while it is unlimited.

A player, as `GET /api/v1/players/{login_id}` and each change to them answer (`history`: the newest changes made to
the account, by anyone, newest first; `card_end`: the card number's last four digits):

```json
{"login_id": "NOVA", "dj_name": "DJ NOVA", "player": 2, "is_admin": false, "disabled": false, "banned": false,
 "ban_reason": null, "created_at": 1762560000, "last_login": 1762560600, "card_end": "0417",
 "dj_card": {"icon": 6, "plate": 32768, "pattern": 7, "comment": "HELLO", "exp": 1013, "level": 11,
             "pictures": true, "max_points": 4200},
 "exp_plays": 13, "exp_extra": 1000, "max_points": 4200, "unlimited_points": false, "points_shown": 4200,
 "levels": 99, "picture": 1, "summary": {"plays": 1, "songs": 1, "charts": 1, "last": 1762560600},
 "recent": [{"song": 1, "title": "...", "pattern": 1, "score": 1300, "mode": 0, "mode_name": "STAR", "dj": "DJ NOVA",
             "player": 2, "level": 7, "at": 1762560600}],
 "history": [{"at": 1762560700, "who": "BOSS", "what": "set the level of NOVA to 11"}]}
```

Disabled accounts are in no ranking, board or list of everyone's plays, and have no DJ page.

The song list's state, as `song_list` in `GET /api/v1/server` (here a server whose DJ cards were not there the last
time it read the client data):

```json
{"songs": {"count": 177, "at": 1762560600}, "jackets": {"count": 176, "at": 1762560600},
 "cards": {"count": {"icon": 0, "plate": 0, "pattern": 0}, "at": null},
 "missing": [{"part": "cards", "why": "The game's files have no DJ cards.", "key": "error.card.tables"}],
 "read_at": 1762560600, "source": {"from": "folder", "path": "/games/technika", "made": null},
 "read_again": true, "folder": "/games/technika", "command": "./dmt3 catalog"}
```

A song list saved by the launcher goes to a server through the same call, as its body:

```sh
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/zip' \
  --data-binary @openDMT3-song-list.zip http://SERVER:4730/api/v1/server/song_list
```

## Errors

Every error under `/api/`, a wrong path or method included, answers its HTTP status and
`{"error": {"code": "...", "message": "..."}}`: `bad_request` (400, such as a mode outside 0 to 255),
`refused` (400, a change the rules refuse, with the reason), `wrong_sign_in` (401), `sign_in` (401, no token, or
one that no longer works), `admin_only`, `read_only` (a read-only named token), `wrong_password` (403, the current
password on a change) and `banned` (403, a banned account's sign-in, with its `reason`), `unknown_song`, `unknown_player`, `unknown_backup`, `unknown_cabinet`, `unknown_token`,
`no_installer`, `no_game_folder` and `not_found` (404), `method_not_allowed` (405, with `Allow`, the methods the path
takes), `busy` and `not_read` (409, the song list imported while another import goes, or a song list that cannot be
read),
`too_large` (413, an upload past its limit), `too_many_tries` (429, with `Retry-After`, the seconds to wait). Every
answer under `/api/`, an error or a file too, carries `Cache-Control: no-store`.

Any call may also answer `too_many_requests` (429, with `Retry-After`) when its caller asked for more than its share of
the server's work: a token (or a sign-in) has 1 call answered at once and 30 seconds of the server's processor time a
minute, an address 8 and 90, and up to 32 more calls of each wait their turn, a call that waited being refused when the
seconds were spent meanwhile ([server.md](server.md#many-players-at-once)). A program that waits as `Retry-After` says
never loses a call.
