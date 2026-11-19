openDMT3 server @VERSION@ for @SYSTEM@
=====================================

The openDMT3 server on a machine of its own: the game server the players' launchers connect to, the players' site
with the rankings, the songs, each DJ's page and the launcher to download, and the admin pages, a site of their own
on this machine. It needs no Docker and no Python on this machine: it brings its own. No game files are included: the
server reads only the song list from your own client data.

Start
-----

In a terminal, in the folder this file is in (@NAME@):

1. ./opendmt3-server setup --admin BOSS
   makes the owner's account, with the admin pages, and prints its password.
2. ./opendmt3-server start
   starts the server in the background. The admin pages are at http://127.0.0.1:4731/ on this machine.
3. The song list: on the admin pages, Song list, choose your client data (a folder or an archive). Or:
   ./opendmt3-server catalog /path/to/your/client-data
4. The server's two ports, TCP 4725 for the game and 4730 for the players' site, open to the players' PCs:
   ./opendmt3-server firewall prints the commands that open them. The admin pages' port stays closed: they are for
   this machine.
5. Players: the admin pages' Players makes each player's account, with the message to send them, and shows the
   address players open, with a QR code to scan. On their PC they sign in on the players' site, download the
   launcher from the Download page, and connect to this server in its guide.
@QUARANTINE@
In the foreground
-----------------

./opendmt3-server runs the server in this terminal until Ctrl+C. ./opendmt3-server stop stops it from another
terminal, and stops a server started in the background the same way.

Commands
--------

  ./opendmt3-server status            whether it runs, its health and its addresses
  ./opendmt3-server logs              the last lines of its log
  ./opendmt3-server setup --address 192.168.0.5
                                      the address players reach this machine at (the message and the QR code carry
                                      it)
  ./opendmt3-server invite            that address, with its QR code
  ./opendmt3-server setup --admin-host 0.0.0.0
                                      the admin pages from the other PCs of the network too (open their port, 4731);
                                      setup --admin-host 127.0.0.1 keeps them on this machine again
  ./opendmt3-server add-player NOVA   an account (its password is printed)
  ./opendmt3-server backup            a backup now (one is made every day while it runs, a week of them kept)
  ./opendmt3-server expose dmt3.example.org
                                      the site over HTTPS at that name, behind Caddy on this machine; with
                                      --admin-public the admin pages too, at https://dmt3.example.org:4731/
  ./opendmt3-server --help            every command

The data
--------

Accounts, plays, backups, the log, the settings and the installer the Download page hands out are in the data
folder beside the program (data/). To move the server to a new version, stop it, unpack the new release's package
beside this folder, and move the data folder into the new one.

This package brings the launcher's installer of the same version: a start puts it in data/downloads, and the site's
Download page hands out the newest installer there.

The one-line install does all of this for you: it keeps the data in ~/.local/share/opendmt3-server/data, puts the
command opendmt3-server in ~/.local/bin, and moves a running server to a newer release. Its line is on the
release's page and in the guide below.

Guides, and where to report a problem: https://github.com/kanggu12/openDMT3 (docs/server.md)

The programs and parts this package brings, and their licences: licenses/NOTICES.txt. openDMT3 itself: LICENSE.txt
(MIT).
