"""Point frozen Tkinter at the Tcl/Tk files bundled with the EXE."""
from __future__ import annotations

import os
import sys
from pathlib import Path


if getattr(sys, "frozen", False):
    bundle_root = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    os.environ["TCL_LIBRARY"] = str(bundle_root / "tcl" / "tcl8.6")
    os.environ["TK_LIBRARY"] = str(bundle_root / "tcl" / "tk8.6")
