"""Controlled public-command failure; never a production fault switch."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from getbrolls import commands, ledger
from getbrolls.cli import entrypoint

fault = sys.argv.pop(1)
original = ledger.atomic_write


def write(path, text):
    if fault == "before-journal" and Path(path).name == ".pending-transaction.json":
        raise SystemExit(91)
    original(path, text)
    if fault == "after-journal" and Path(path).name == ".pending-transaction.json":
        raise SystemExit(91)
    if fault == "after-manifest" and Path(path).name == "manifest.json":
        raise SystemExit(91)


def failed_page(*args, **kwargs):
    raise OSError("Synthetic review regeneration failure after the committed import.")


ledger.atomic_write = write
if fault == "review-regeneration":
    commands.render = failed_page
raise SystemExit(entrypoint())
