#!/bin/sh
# The openDMT3 server @VERSION@ for @SYSTEM@: this package's own Python (lib/python) running the server's command
# line (opendmt3/server/standalone.py, in lib/), with the package's 7-Zip for the client data's archives. Nothing of
# this machine's Python or Docker is used. Every command is the Windows package's opendmt3-server.exe's:
#
#   ./opendmt3-server                 run here until Ctrl+C (or ./opendmt3-server stop from another terminal)
#   ./opendmt3-server start | stop | status | logs | setup | catalog | firewall | ... (--help lists them)
#
# packaging/server/bundle.py writes this file into each package, with the version and the system put in.
set -e
# This file's own place, through any link to it (a link on PATH): the package's folder is the one this file is in.
self=$0
while [ -h "$self" ]; do
  link=$(readlink "$self")
  # A link's target is read from the link's own folder unless it is a whole path.
  case $link in
    /*) self=$link ;;
    *) self=$(dirname "$self")/$link ;;
  esac
done
here=$(cd "$(dirname "$self")" && pwd -P)
# The server runs from a release's package: its data folder beside this file (unless --data or OPENDMT3_DATA names
# another), the installer it brings for the Download page, its list of files for repair, and this file to start
# itself again with (standalone.py reads this).
OPENDMT3_SERVER_PACKAGE=$here
export OPENDMT3_SERVER_PACKAGE
# The package's own 7-Zip, unless another is named: the release that was tested with the server.
if [ -z "${OPENDMT3_7ZIP:-}" ]; then
  OPENDMT3_7ZIP=$here/lib/7-zip/7zz
  export OPENDMT3_7ZIP
fi
# -I: none of this machine's Python settings (PYTHONPATH, PYTHONHOME, a user's site folder) reaches the package's
# Python, which finds the server's code by the path file in its site-packages; -B: nothing is written into the
# package (its bytecode was made when it was built).
exec "$here/lib/python/bin/python3" -I -B -m opendmt3.server.standalone "$@"
