"""The program PyInstaller freezes into the launcher's installer: the installer's dialogs around Velopack's setup.

run() ends an error nothing caught in the installer's own error window, never in PyInstaller's plain one."""

import sys

from opendmt3.client.installer import run

sys.exit(run())
