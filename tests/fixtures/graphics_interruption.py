"""Process interruption at the public CLI seam; not a production fault switch."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from getbrolls import graphics, ledger
from getbrolls.cli import entrypoint
from getbrolls.ledger import Ledger

fault = sys.argv.pop(1)
original_save = Ledger.save
original_copy = graphics._copy_checked
original_atomic = ledger.atomic_write


def atomic_write(path, text):
    original_atomic(path, text)
    if fault == "after-journal" and Path(path).name == ".pending-transaction.json":
        raise SystemExit(91)
    if fault == "after-manifest" and Path(path).name == "manifest.json":
        raise SystemExit(91)


def save(self, operation, c=None):
    if fault == "before-staging" and operation == "graphics-render-staging":
        raise SystemExit(91)
    original_save(self, operation, c)
    if fault == "after-" + operation.removeprefix("graphics-render-"):
        raise SystemExit(91)


def copy_file(source, dest, expected=None):
    value = original_copy(source, dest, expected)
    if fault == "after-preview" and dest.name.startswith("graphics-") and dest.suffix == ".mp4":
        raise SystemExit(91)
    return value


Ledger.save = save
graphics._copy_checked = copy_file
ledger.atomic_write = atomic_write
raise SystemExit(entrypoint())
