---
type: documentation
status: current
created: 2026-09-15
updated: 2026-10-05
tags: [get-brolls, documentation]
---

# Contribuição

Leia [AGENTS](AGENTS.md) antes de alterar o código e [GUIDE](docs/GUIDE.md#instalação) para preparar dependências. O fluxo YouTube sem API key e o processo Instagram de dois canais fazem parte do contrato do produto.

## Alterações

Descreva o problema, o comportamento resultante e a validação realizada. Para bugs, reproduza a falha e adicione regressão relevante. Atualize a referência da rota afetada e o CHANGELOG. Comandos de um mesmo projeto devem ser executados serialmente.

Testes automatizados usam mídia sintética e mocks, sem segredos ou conteúdo privado. Ensaios reais de plataforma ficam fora da pasta da skill e registram resultado técnico em [QUALITY](docs/QUALITY.md); falha de rede não deve ser escondida por fixture.

## Desenvolvimento e verificação

- Uma tarefa ou um lote coerente combinado com o mantenedor usa uma branch e um PR, com uma descrição e uma atualização documental coerentes. Correções, testes, documentação e ajustes da mesma entrega continuam nessa branch enquanto ela aguarda integração. Separe trabalhos independentes.
- Antes de criar uma branch, confira o estado do Git, o diff e as branches/worktrees ativos; reutilize uma branch aberta adequada ao objetivo. Crie outra para uma entrega independente que precise de revisão ou integração separada, ou para a próxima tarefa depois do merge. Parta do `main` atualizado, respeitando dependências explicitamente combinadas.
- Branch e worktree são escolhas distintas. Use um novo worktree quando uma implementação substancial, refatoração ou trabalho paralelo precisar de isolamento; para ajustes pequenos, aproveite o checkout adequado existente. Siga as instruções aplicáveis aos workflows opcionais ao propor e preparar esse isolamento.
- Reúna os ajustes da entrega antes de propor a publicação do PR, salvo pedido explícito para abrir um rascunho antes. Publicação e integração continuam sujeitas à autorização do mantenedor.
- Comece pelo estado do Git, pelo diff e pelas partes afetadas. Use buscas específicas e amplie a leitura para contratos, dependências e chamadores quando necessário; não releia arquivos inteiros apenas por mudança de etapa.
- Durante a implementação, execute lint e testes relevantes às alterações. Amplie a cobertura quando houver impacto compartilhado em estado, recuperação, segurança, dependências ou configuração. Revisões documentais verificam frontmatter, links e exemplos afetados.
- Antes da integração, exija a bateria completa prevista no CI para o estado final. Um CI concluído e aprovado para a revisão atual é evidência suficiente dessa bateria; não a duplique localmente apenas para abrir o PR ou redigir o relatório. Mudanças posteriores exigem nova verificação do que afetarem e os checks obrigatórios do PR atualizado. Preserve os portões de release e a validação real ou humana exigida pela rota.
- Relate comando ou check, revisão verificada, resultado e contagens de testes e skips. Leia o resumo das verificações bem-sucedidas; examine logs detalhados em falhas ou quando o resumo não resolver uma dúvida. Não descreva um teste focado como validação completa.

O tamanho do `SKILL.md` é uma orientação de legibilidade: exceder as referências de palavras emite avisos, sem reprovar testes. Preserve os contratos importantes; reduza repetições e consulte as referências para detalhes. As verificações de conteúdo, frontmatter e sincronização do espelho continuam obrigatórias.

Comandos para a suíte completa e o diagnóstico de disponibilidade:

```sh
python3 -m unittest discover -s tests -v
python3 scripts/gb.py doctor
```

Mudanças na revisão visual exigem conferir aprovação/ajuste/sugestão, exportação/importação, impressão e largura móvel conforme o impacto. Revisões apenas documentais precisam validar frontmatter, links e exemplos de CLI, sem refazer downloads desnecessariamente.

## Lint e type check

`ruff` e `pyright` são as únicas dependências de desenvolvimento e ficam pinadas em `requirements-dev.txt`; o runtime da CLI continua sem dependência nenhuma. A configuração das duas está em `pyproject.toml` (`ruff` com E/F/W/I/B/UP em 120 colunas, `pyright` em `basic` sobre `scripts/` e `tests/`).

```sh
python3 -m pip install -r requirements-dev.txt
bash scripts/check.sh
```

No Windows, `./scripts/check.ps1` roda a mesma bateria. Os dois executam, em ordem, `ruff check`, `ruff format --check`, `pyright`, `python3 scripts/gen_skill_mirror.py --check` (o espelho da skill em `skills/get-brolls/SKILL.md` é gerado a partir do `SKILL.md` da raiz — nunca edite o espelho à mão), `python3 scripts/check_anchors.py` e a suíte de testes. O CI executa uma única bateria no Windows, com a versão de Python fixada em `.github/workflows/test.yml`; lint, tipos e testes compartilham o mesmo job. A bateria completa roda nos PRs; o merge em `main` não inicia uma repetição. O check obrigatório do PR deve passar antes da integração. A sintaxe Bash é conferida pelo Git Bash no runner Windows.

## Dependências e releases

Revise `requirements.txt` e `package-lock.json` junto com mudanças nas dependências. Os instaladores usam o conjunto registrado; não faça atualização global nem incorpore bibliotecas no repositório. O Dependabot propõe atualizações por PR; elas exigem testes e, quando afetarem aquisição, ensaio da rota correspondente. As GitHub Actions ficam fixadas por SHA.

A branch `main` é produção: o plugin instalado por quem usa a skill acompanha essa branch, e cada release baixada por um usuário sai de um commit dela. A branch principal deve exigir `Windows checks` antes do merge — essa proteção é uma configuração do GitHub feita pelo mantenedor, o arquivo do workflow não a ativa; confira o nome do check no PR ao configurar a regra. Siga a política de validação Windows em [AGENTS](AGENTS.md#manutenção). Mudança de comportamento entra por PR com CI verde, nunca por push direto em `main`, e vem acompanhada de entrada no CHANGELOG e de compatibilidade retroativa.

Uma correção de código incrementa a versão com `python3 scripts/bump_version.py X.Y.Z --date AAAA-MM-DD`, que escreve numa passada só `scripts/getbrolls/__init__.py`, `package.json`/`package-lock.json`, `.claude-plugin/plugin.json`/`marketplace.json`, `SKILL.md` (o espelho é regerado junto), READMEs, `docs/QUALITY.md` e o stub do CHANGELOG; `--check` confere as mesmas fontes sem escrever. Antes de empurrar a tag, rode `bash scripts/preflight.sh --version X.Y.Z`: o mesmo portão que o release roda contra o commit da tag — versão coerente, frontmatter, ausência de material interno, espelho da skill, âncoras, suíte completa e seção do CHANGELOG no formato esperado — e sai 0 com `PREFLIGHT OK` ou nomeia o passo que reprovou. Só depois disso empurre uma tag `vX.Y.Z` apontando para o commit aprovado; nunca mova uma tag já distribuída para outro código. **O ato manual do mantenedor é o push da tag.** A partir dele, `.github/workflows/release.yml` publica sozinho: instala FFmpeg, roda `bash scripts/preflight.sh --version "$VERSION"` contra o commit da própria tag, extrai as notas da seção correspondente do CHANGELOG — que precisa começar exatamente com `## <versão> — ` (travessão em em dash, não hífen) — e cria a release com `gh`, marcada como pré-lançamento quando a tag tem hífen (por exemplo `v2.4.0-rc1`). Sem o preflight verde ou com a seção fora do formato esperado, nada é publicado.

## Arquivos publicados

O próprio repositório é a entrega. Inclua skill, AGENTS, documentação, código e interface necessários para um clone funcional. Dependências são instaladas pelos comandos do GUIDE; não incorpore bibliotecas, fontes externas, binários, ambientes virtuais, cookies, configs CDN, mídia de clientes ou exemplos preenchidos com dados reais.

Código próprio sob MIT, conforme LICENSE. Dependências mantêm suas licenças, descritas em THIRD_PARTY_NOTICES. Publicação, push e atualização de instalação pessoal são ações separadas da revisão local.
