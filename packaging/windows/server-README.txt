openDMT3 server @VERSION@ for Windows
=====================================

The openDMT3 server on a Windows PC of its own: the game server the players' launchers connect to, the players' site
with the rankings, the songs, each DJ's page and the launcher to download, and the admin pages, a site of their own
on this PC. It needs no Docker, no Python and no launcher on this PC. No game files are included: the server reads only the song list from your own client
data.

Start
-----

1. Unpack the whole zip into a folder of your own, outside OneDrive and Program Files (for example C:\openDMT3-server).
2. Start opendmt3-server.exe. The server runs in its window, and on the first start your browser opens the admin
   pages on this PC (http://127.0.0.1:4731/), where you make the owner's account.
3. When Windows asks whether opendmt3-server may use the network, allow it on private networks. Or start
   "Open the firewall.cmd", which opens the server's two ports (TCP 4725 for the game, 4730 for the players' site)
   for this network after Windows asks you. The admin pages' port stays closed: they are for this PC.
4. The song list: on the admin pages, Song list, choose your client data (a folder or an archive). Or in a terminal
   in this folder: opendmt3-server catalog D:\path\to\your\client-data
5. Players: the admin pages' Players makes each player's account, with the message to send them, and shows the
   address players open, with a QR code to scan. On their PC they sign in on the players' site, download the
   launcher from the Download page, and connect to this server in its guide.

The server runs while its window is open. To stop it, close the window or press Ctrl+C.

In the background
-----------------

"Start in the background.cmd" starts the server with no window; "Stop the server.cmd" stops it. Both are this same
program: opendmt3-server.exe start and opendmt3-server.exe stop, which also stops a server started in a window.

Commands
--------

Open a terminal in this folder (type cmd in Explorer's address bar, then Enter):

  opendmt3-server status            whether it runs, its health and its addresses
  opendmt3-server logs              the last lines of its log
  opendmt3-server setup --address 192.168.0.5
                                    the address players reach this PC at (the message and the QR code carry it)
  opendmt3-server invite            that address, with its QR code
  opendmt3-server setup --admin-host 0.0.0.0
                                    the admin pages from the other PCs of the network too (Windows asks to open
                                    their port, 4731); setup --admin-host 127.0.0.1 keeps them on this PC again
  opendmt3-server add-player NOVA   an account (its password is printed)
  opendmt3-server backup            a backup now (one is made every day while it runs, a week of them kept)
  opendmt3-server expose dmt3.example.org
                                    the site over HTTPS at that name, behind Caddy on this PC
  opendmt3-server --help            every command

The data
--------

Accounts, plays, backups, the log, the settings and the installer the Download page hands out are in the data
folder beside this program. To move the server to a new version, stop it, unpack the new zip into a new folder,
and move the data folder into it.

This package brings the launcher's installer of the same version: a start puts it in data\downloads, and the site's
Download page hands out the newest installer there.

Guides, and where to report a problem: https://github.com/kanggu12/openDMT3 (docs/server.md)

The programs and parts this package brings, and their licences: licenses\NOTICES.txt. openDMT3 itself: LICENSE.txt
(MIT).
