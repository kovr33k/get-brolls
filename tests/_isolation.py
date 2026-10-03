"""Nenhum teste lê ou escreve a pasta pessoal real.

`GB_HOME` aponta para um temporário por rodada, criado no primeiro import e
apagado na saída. Quem já exportou `GB_HOME` no ambiente continua mandando —
mas aí a pasta é dele, não a `~/.getbrolls` de verdade.

`discover -s tests` não importa `tests/__init__.py`, então cada módulo que
toca a biblioteca (direta ou indiretamente, por `next_action`/`search`)
importa este aqui antes de importar `getbrolls`.
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

if not os.environ.get("GB_HOME"):
    _home = tempfile.mkdtemp(prefix="gb-home-")
    os.environ["GB_HOME"] = _home
    atexit.register(shutil.rmtree, _home, ignore_errors=True)

GB_HOME = Path(os.environ["GB_HOME"])
_ERROR_PRIVILEGE_NOT_HELD = 1314


def symlink_or_skip(link, target, *, target_is_directory=False):
    """Skip only when Windows denies the symlink privilege; keep other errors visible."""
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        if os.name == "nt" and getattr(exc, "winerror", None) == _ERROR_PRIVILEGE_NOT_HELD:
            raise unittest.SkipTest("Windows symlink privilege is unavailable") from exc
        raise
