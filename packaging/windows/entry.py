"""The program PyInstaller freezes: both openDMT3.exe (window) and openDMT3-cmd.exe (console) start here.

run() ends an error nothing caught in the launcher's own error window, never in PyInstaller's plain one."""

import sys

from opendmt3.client.main import run

sys.exit(run())
