## O que muda

Descreva a mudança e o problema que ela resolve. Referencie a issue (`Closes #N`) quando houver.

## Verificação

Escolha as verificações conforme CONTRIBUTING.md e informe a evidência real da revisão validada. Os comandos abaixo descrevem a bateria completa:

```sh
bash scripts/install.sh --check
python3 scripts/gb.py doctor
python3 -m unittest discover -s tests -v
```

No Windows PowerShell, troque o primeiro comando por `powershell -ExecutionPolicy Bypass -File scripts/install.ps1 -Check` e use `python` nos dois seguintes.

- [ ] Suíte completa passou para a revisão final, localmente ou no CI (informe a revisão e o total de testes/skips).
- [ ] Regressão adicionada para o defeito corrigido ou para o comportamento novo.
- [ ] `./scripts/check.ps1` ou os checks equivalentes do CI passaram: `ruff`, `pyright`, espelho da skill, âncoras e suíte; reutilize evidência válida sem repetir a mesma bateria.
- [ ] Documentação afetada atualizada (GUIDE, README/README.en, SKILL, QUALITY, CHANGELOG). O espelho em `skills/get-brolls/SKILL.md` é gerado: rode `python3 scripts/gen_skill_mirror.py`, nunca edite à mão.
- [ ] Nenhuma chave, sessão, URL assinada, original ou projeto de cliente no diff.

`--check` valida pré-requisitos do instalador; não instala bibliotecas nem testa sessão/rede. `doctor` informa disponibilidade. Nenhum deles substitui um ensaio real da fonte afetada — descreva abaixo o que foi testado ao vivo, se houver.

## Evidências
