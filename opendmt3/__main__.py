"""python -m opendmt3 check|setup|restore: the game folder's command line, which lives in opendmt3/core/cli.py."""

import sys

# The command stays where people type it; the code is core's, shared by the server and the client.
from opendmt3.core.cli import main

sys.exit(main())
