# Troubleshooting

The launcher says what is wrong in its status line, at the bottom of the window, and the **Play** page shows a ready
check: a red line there is what to fix first. Its log is `%AppData%\openDMT3\logs\launcher.log`; **Help**, **The
launcher's log** opens the folder. **Help**, **Report**, **Save** puts the log and the game's settings in a zip on the
desktop for an issue, with your Windows user name, your sign-in and your card number taken out.

## The installer

- **Windows protected your PC**, for an installer downloaded with a browser: the installer is not signed. **More
  info**, then **Run anyway**.
- **Windows blocks it with no Run anyway**: Smart App Control is on ([Install](install.md#install), step 2).
- **The game is open**: the installer does not go on while a game the launcher started is open. Finish it and close
  the game, then press **Try again**.
- **It failed**: the dialog shows what the setup said, and offers its log.

## The launcher does not find the game

- The guide looks up to four folders below the Desktop, Downloads, Documents and the top of each drive. Anywhere
  else, **Choose a folder...** (the folder holding the client data, or any folder above it) or **Choose an
  archive...**.
- **The cabinet's client: does not work here, the PC client is needed.** The folder has only the cabinet's client,
  which needs the cabinet's security keys.
- **The file with the tutorial is missing**, or **the file with the charts**: the game stops when the tutorial, or a
  song, starts. Copy the client data again, or unpack the archive again. Without the videos or the previews the game
  plays: songs without their videos, the song select without previews.
- **Songs have no charts**: the card says how many of the songs the game offers have none, in any of its modes (a song
  no mode offers is never shown, so the card counts it nowhere); the game stops if one of them starts. When it is the
  first song the game shows, the client data does not play here. Copy the client data again, or unpack the archive
  again.

[The client data](client-data.md#what-a-card-says) has the lines a card says, each with the one thing to do, and
[which client data plays](client-data.md#which-client-data).

## PLAY does not start the game

- **The game is open**: close it first. The launcher makes its copies for the game only while the game is closed.
- **Choose the client data first**, or a red line in the ready check on **Play**: the line says what to fix, with a
  way to its page.
- **Cannot reach** a server: playing on another server, the launcher asks it for your card at every PLAY. Check that
  the server is running and its address on **Online**; or choose **Offline** to play without it.
- **The server no longer takes your sign-in**: its owner set a new password, or disabled the account. Sign in again on
  **Online**.
- **Port 4725 on this PC is taken**: another server runs on this PC. Close it, or play on it as another server.
- **The server's database cannot be opened**: the file with this PC's players and records is damaged. **Play** and
  **Online** say so where the players are listed, and **Open the folder** shows it. Its daily backups are in the
  `backups` folder beside it. To put the newest one back, close the launcher, rename `openDMT3.sqlite` (and
  `openDMT3.sqlite-wal` and `openDMT3.sqlite-shm`, if they are there) to keep them aside, copy the newest
  `openDMT3-…-daily.sqlite` from `backups` next to them, and name the copy `openDMT3.sqlite`.
- **The server's database is from a newer openDMT3**: install the newer launcher again; the file itself is whole.

## The game closes by itself

PLAY says **The game closed by itself** when the game wrote a crash dump, or ended with an error within its first half
minute. **Help** lists what to try:

1. Play in a window once (**Screen**). If that works, update the graphics driver.
2. Turn **Background videos** off (**Screen**) if it closes when a song starts.
3. Save a report and attach it to an issue.

## The picture or the mouse

- **Bars on two sides of the picture**: the game's own 5:3 shape is kept (**Screen**, **Picture shape**, **Keep**).
  **Fill** stretches it over the whole screen.
- **The picture is small or blurred**: choose **Full screen** on **Screen**, a borderless window over the main monitor
  at any Windows scaling; **Upscale filter** chooses how the picture is enlarged.
- **The mouse hits the wrong place**: start the game from the launcher (PLAY, or its desktop shortcut). PLAY starts
  a fixed copy of the client that reads the mouse at the right place; the original client started on its own does not.
- **On a touch screen**: choose **Touch screen** on **Controls**: the pointer hides. The game takes one finger at a
  time.

## No sound

The game plays on the device chosen on **Sound**, **Device**: **Windows' default output** unless you chose another,
and also when the chosen one is not connected (the page says so). Check the volumes on **Sound** too.

## The game does not log in

- **NET** stays red in the game: the game does not reach the server. Playing on this PC, the launcher's server runs
  while the launcher does. On another server, its game port (TCP 4725) must be open on that PC and on the way to it.
- The game shows **NO ID CARD**: offline, or a guest was chosen on **Play**.
- **Membership authentication failed**: the server does not know the card. Its owner may have set a new password or
  disabled the account; PLAY fetches the new card, or asks to sign in again. A server in maintenance refuses every
  card the same way until its admin ends it.

## Records are missing

- The game reports only the stages a player clears, at the end of a session: a failed stage is not kept, and a
  guest's stages are not kept.
- Offline keeps nothing. Records are kept playing on this PC or on another server.
- **Records** and **My records** show the player chosen on **Play**.

## The other PCs on your network cannot connect

- The PC that keeps the players turns on **Online**, **Open this PC's server**, and stays open while they play.
- Windows marks a new network as Public, and keeps other PCs out. Set the network to Private (Settings, Network &
  internet), and allow openDMT3 on private networks when Windows asks.
- Type an address exactly as the page lists it, on a PC on the same network (not a guest Wi-Fi).

## The server

With Docker, start with `./dmt3 doctor`: Docker, the server's image, the two ports and the data folder, each problem
with its fix. `./dmt3 status` shows the container's state, whether the site and the game's port answer, and the site's
address; `./dmt3 logs` shows the server's log.

- **No account to sign in with**, in Docker: the page that makes the owner's account shows only to visits from the
  server PC itself, and Docker's network hides them. Make it with `./dmt3 add-player ID --admin`
  ([Players](server.md#players)).
- **Other PCs cannot reach the site or the game**: ports 4730 (the site) and 4725 (the game) must be open on the server
  PC's firewall and on the way to it, and the players need the server PC's own address on the network
  (`./dmt3 setup --address ADDRESS` puts it in the message to send a player).
- **Other PCs cannot reach a server in WSL 2**: in WSL's default networking (NAT), WSL has an address of its own inside
  the PC (`172.x`) that other PCs cannot reach. Set `networkingMode=mirrored` under `[wsl2]` in
  `%UserProfile%\.wslconfig`, run `wsl --shutdown`, then `./dmt3 setup` again. With Docker Desktop, which publishes the
  ports on Windows itself, give Windows' own address on the network instead (`ipconfig` shows it):
  `./dmt3 setup --address 192.168.0.5`.
- **A newer database**: a server refuses a database made by a newer openDMT3, and leaves it alone. Run the newer
  server, or put back a backup.
- **Too many failed sign-ins**: wrong passwords hold back their own address for a few minutes, and ten wrong passwords
  for one ID within ten minutes hold back that ID from every address but the server PC's, until ten minutes after the
  first of them. Any address can sign in 20 times a minute, right or wrong. Behind a proxy, start the server with
  `--proxy` and the proxy's own address, so the server tells visitors apart.
- **The song list was not imported**: the import says its one line
  ([The client data](client-data.md#what-a-card-says)); the details of a part that could not be read are in
  `catalog.log` in the data folder.

## Putting everything back

PLAY changes nothing in the client data. Client data an older openDMT3 changed: **Help**, **Game files**, **Put back**
(or `openDMT3-cmd.exe --put-back`) puts every original back from its `backup\` folder and removes the files the older
openDMT3 added. **Help**, **Uninstall** does the same, then takes openDMT3 off this PC
([Removing openDMT3](install.md#removing-opendmt3)).

If openDMT3 was removed while the game was open, the note it left in `backup\` (`README-openDMT3.txt`) names each
file to copy back over the one in the client data, and each file to delete.
