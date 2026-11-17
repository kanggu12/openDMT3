"""The program PyInstaller freezes into the Windows server package's opendmt3-server.exe: the server's own command
line for a PC of its own (opendmt3/server/standalone.py), with the 7-Zip the package brings for the client data's
archives."""

import os
import sys

# The package's 7-Zip (server.spec puts it here, inside the program's folder): the song list's reading looks where
# OPENDMT3_7ZIP says (server/services/sources.py), and a 7-Zip of the PC's own may be another release, or none.
HERE = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
SEVEN_ZIP = os.path.join(getattr(sys, "_MEIPASS", HERE), "opendmt3", "server", "bin", "7-Zip", "7z.exe")
if os.path.isfile(SEVEN_ZIP):
    os.environ.setdefault("OPENDMT3_7ZIP", SEVEN_ZIP)

from opendmt3.server.standalone import main  # noqa: E402  (imported once the 7-Zip is named, as a rule)

sys.exit(main())
