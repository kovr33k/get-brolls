"""Wrapper único para invocar `scripts/gb.py` como subprocesso nos testes.

Reúne o padrão hoje reimplementado em `test_brief.py`, `test_approve_chat.py`,
`test_env_paths.py`, `test_init_rules_flags.py`, `test_library.py` e
`test_permit_declaration.py`: monta `[sys.executable, CLI, *args]`, roda com
`capture_output=True, text=True, encoding="utf-8"`, confere o código de saída
e devolve o JSON — de `stdout` quando o código esperado é 0 (sucesso), de
`stderr` para qualquer outro código (erro tratado pela CLI, que imprime JSON
de erro lá).

`env` funde variáveis no ambiente herdado, como em `test_env_paths.py` e
`test_library.py`. `project` é conveniência: quando informado, acrescenta
`--project <project>` ao fim dos argumentos, para quem não quer repetir o par
em toda chamada.

Sem `--env-file` explícito, usa um arquivo vazio: o `.env` pessoal da fonte
não pode alterar as expectativas dos testes.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# A pasta pessoal da skill vai para um temporário: nenhum teste toca ~/.getbrolls.
import _isolation  # noqa: F401  (efeito de import: define GB_HOME)
from _paths import CLI

_EMPTY_ENV_DIR = tempfile.TemporaryDirectory(prefix="gb-test-env-")
_EMPTY_ENV_FILE = Path(_EMPTY_ENV_DIR.name) / ".env"
_EMPTY_ENV_FILE.write_text("", encoding="utf-8")


def run_cli(*args, project=None, expect=0, env=None):
    command_args = list(args)
    if not any(str(arg).split("=", 1)[0] == "--env-file" for arg in command_args):
        command_args[:0] = ["--env-file", str(_EMPTY_ENV_FILE)]
    if project is not None:
        command_args += ["--project", str(project)]

    environment = None
    if env is not None:
        environment = dict(os.environ)
        environment.update(env)

    done = subprocess.run(
        [sys.executable, str(CLI), *map(str, command_args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )
    assert done.returncode == expect, done.stderr or done.stdout
    return json.loads(done.stdout if expect == 0 else done.stderr)
