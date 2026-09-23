#!/usr/bin/env python3
"""Compatibility launcher for the marketplace website and canonical API.

Both ``python3 backend/server.py`` and ``python3 -m backend.server`` use the
same persistence, authorization, workflow, and configuration as backend.api.
"""

if __package__:
    from .api import main
else:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from backend.api import main


if __name__ == "__main__":
    main()
