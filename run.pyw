"""Double-click launcher (no console window). Use `uv run python -m flow` to see logs."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flow.__main__ import main  # noqa: E402

sys.exit(main())
