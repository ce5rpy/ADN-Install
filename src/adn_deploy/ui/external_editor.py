"""Launch a terminal editor without corrupting the Textual TUI."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from textual.app import App


def run_external_editor(app: App, path: Path) -> int:
    """Suspend the TUI, run ``$EDITOR`` on ``path``, then restore the screen."""
    editor = os.environ.get("EDITOR", "nano")
    with app.suspend():
        return subprocess.run([editor, str(path)], check=False).returncode
