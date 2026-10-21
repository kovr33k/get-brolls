---
type: documentation
status: current
created: 2026-09-15
updated: 2026-10-21
tags: [get-brolls, guide, installation, providers, storyboard, graphics, ai]
---

# Guia completo — Get B-rolls

Este é o manual operacional único do **GET B-ROLLS — ENGENHEIRO DE VÍDEO**: instalação, compatibilidade, fluxo editorial, provedores, navegador, Instagram, tipos de asset e Storyboard.

## Navegação rápida

- [Instalação](#instalação)
- [Compatibilidade](#compatibilidade)
- [Fluxo editorial](#fluxo-editorial)
- [Estado do projeto e progresso](#estado-do-projeto-e-progresso)
- [Fontes e transportes](#fontes-e-transportes)
- [Catalog selection, access, and researched special routes](SOURCE-CATALOGS.md)
- [Archive.org and resumable fragment search](#provider--archiveorg-and-fragment-search)
- [Browser attempts, UN and Destockd imports](#browser-attempts-and-archive-locators)
- [Tipos de assets](#tipos-de-assets-e-formatos)
- [Captura pelo navegador](#captura-de-notícias-e-páginas-pelo-navegador)
- [Instagram](#instagram--navegadorplaywright-dois-streams-e-mp4)
- [Graphics](#graphics)
- [Narration analysis](#narration-analysis)
- [AI stills](#ai-stills)
- [Storyboard](#storyboard)
- [Apêndice — utilitários legados](#apêndice--utilitários-legados)

## Instalação

Instale a stack inteira antes de rodar o instalador: Python 3.11+, FFmpeg/ffprobe com libfreetype (`drawtext`), Node 22+ com npm/npx, curl e Git. O README traz o comando por sistema; `doctor` confirma com `summary.missing` vazio e `contact_sheet.labels: true`.

### Dependências por capacidade

| Componente | Necessário para |
|---|---|
| Python 3.11+ | CLI e coletor de pares Instagram |
| FFmpeg e ffprobe, executáveis | Prévia, cortes, vídeo+áudio e validação |
| yt-dlp com extras `default` (inclui EJS) | Busca YouTube e aquisição de URLs sociais |
| Node 22+ | Playwright CLI e EJS do yt-dlp; Deno 2.3+ é alternativa apenas ao runtime EJS |
| Node/npm/npx + Playwright CLI + navegador | Captura de streams Instagram e inspeção pelo navegador |
| curl | Baixar os dois streams Instagram capturados |
| Bash e awk | Somente os helpers opcionais em `scripts/getbrolls/tools/youtube/`; a CLI principal não depende deles |
| FFmpeg com `drawtext` (libfreetype) + fonte DejaVu, Liberation ou Arial | Índice por célula e banner (título, ID, janela) no contact sheet da CLI e dos helpers Bash; use `GB_FONT_FILE` para indicar outra fonte TrueType. Sem `drawtext`, o sheet sai sem rótulos e o Storyboard imprime a legenda de tempos; `doctor` mostra o estado em `contact_sheet` |
| Optional Remotion 4.0.534, `@remotion/renderer`, `@remotion/bundler`, React 19.3.0 and `@fontsource/ibm-plex-sans` 5.3.0 in `scripts/graphics` | Local numeric graphics render only. Collection, `search`, `help` and `status` work without this package. Diagnose with `graphics-doctor`. |

Git é opcional. API key YouTube não é necessária. Pexels/Pixabay usam apenas suas próprias chaves opcionais. `curl-cffi` é extra opcional do yt-dlp, não requisito universal.

### macOS

Instale Python, FFmpeg, curl e Node pelo gerenciador de pacotes do sistema. Em macOS com Homebrew:

```sh
brew install python ffmpeg node
```

Dentro da pasta da skill `get-brolls/`:

```sh
bash scripts/install.sh --check
bash scripts/install.sh
```

O instalador cria `.venv` e instala `yt-dlp[default]`/EJS do PyPI via `requirements.txt`; instala também `@playwright/cli@0.1.21` do npm em `.tools`. Valida Python 3.11+, Node 22+, npm/npx e os executáveis base. Essas pastas de dependências ficam somente na máquina de quem instala e não fazem parte do repositório. Não instala executáveis do sistema nem altera a instalação do agente. A CLI procura primeiro o yt-dlp da `.venv`, depois o `PATH`. Ativar a venv é opcional:

```sh
source .venv/bin/activate
python scripts/gb.py doctor
```

### Windows

Instale Python 3.11+, FFmpeg e Node 22+ pelos instaladores oficiais ou pelo gerenciador de pacotes da sua preferência. Durante a instalação, habilite o `PATH`. Abra PowerShell na pasta `get-brolls/` e execute:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install.ps1 -Check
powershell -ExecutionPolicy Bypass -File scripts/install.ps1
python scripts/gb.py doctor
```

O instalador usa `.venv\Scripts\python.exe` e o launcher `.cmd` do Playwright; não exige Git Bash nem WSL. Se a política local já permite scripts, também é possível executar `& .\scripts\install.ps1`. Os helpers `.sh` de YouTube são opcionais; no Windows, use `search`, `preview`, `fetch` e `verify` pela CLI principal.

Linux continua compatível como plataforma secundária. Em Ubuntu/Debian, instale `python3`, `python3-venv`, `ffmpeg` e `curl`, além de Node 22+, e use `scripts/install.sh` como no macOS.

`doctor` lista executáveis e transporte; não certifica login, acesso a cada site ou extração ao vivo. `doctor --live` faz buscas remotas explicitamente e pode consumir quota dos bancos configurados.

### Navegador / Instagram

Use primeiro o navegador autorizado já conectado ao agente. Se o usuário indicou Chrome logado, selecione esse Chrome no plugin e abra o Reel ali; não troque silenciosamente para navegador integrado sem login.

Alternativa com a extensão oficial Playwright já instalada no Chrome:

```sh
bash scripts/playwright.sh -s=getbrolls-instagram attach --extension=chrome
bash scripts/playwright.sh -s=getbrolls-instagram tab-list
bash scripts/playwright.sh -s=getbrolls-instagram tab-select INDICE_OBSERVADO
```

No Windows PowerShell, use os mesmos argumentos pelo launcher nativo:

```powershell
& .\scripts\playwright.ps1 -s=getbrolls-instagram attach --extension=chrome
& .\scripts\playwright.ps1 -s=getbrolls-instagram tab-list
& .\scripts\playwright.ps1 -s=getbrolls-instagram tab-select INDICE_OBSERVADO
```

A extensão Playwright e o plugin de navegador do agente são integrações diferentes. Use a que estiver disponível; não tente conectar a extensão de uma ferramenta com a CLI da outra. A instalação da CLI não instala extensões nem importa cookies. Consulte a [documentação oficial da extensão](https://github.com/microsoft/playwright/blob/main/packages/extension/README.md) quando precisar configurar essa alternativa.

Sem navegador existente, crie sessão própria:

```sh
bash scripts/playwright.sh -s=getbrolls-instagram open https://www.instagram.com/ --headed
```

Se faltar o navegador, execute `bash scripts/playwright.sh install-browser chrome` no macOS ou `& .\scripts\playwright.ps1 install-browser chrome` no Windows, conforme `--help` da CLI. Login ocorre nessa sessão e depende da conta do usuário. Nunca distribua perfis, cookies ou sessões de outra pessoa.

O método completo está na seção [Instagram pelo navegador](#instagram--navegadorplaywright-dois-streams-e-mp4): navegador → streams vídeo/áudio → configs privados → curl → FFmpeg → ffprobe. O script de pares não substitui a etapa de captura operada pelo agente.

Referências de instalação: [yt-dlp/EJS](https://github.com/yt-dlp/yt-dlp/wiki/EJS), [Playwright CLI](https://github.com/microsoft/playwright-cli). Não há bibliotecas dessas ferramentas distribuídas junto da skill; o instalador obtém as distribuições oficiais.

### Configuração

Copiar `.env.example` para `.env` é opcional (`cp .env.example .env` no macOS; `Copy-Item .env.example .env` no PowerShell). O mesmo arquivo existe comentado em português, `.env.example.pt-BR`: as variáveis e os valores são idênticos, só os comentários mudam de língua. O `.env` pertence à raiz da skill, independentemente da pasta atual. Ambiente do processo prevalece. `--env-file` é opção da raiz do parser e vem antes do subcomando: `python3 scripts/gb.py --env-file CAMINHO <subcomando> …`. Nunca distribua `.env`, cookies, configs CDN ou perfis do navegador.

#### Caminhos explícitos de ferramentas

Quatro variáveis opcionais fixam onde cada ferramenta está, úteis quando há mais de uma instalação na máquina, quando o `PATH` do agente difere do seu ou quando a venv fica fora da pasta da skill. Valem pelo ambiente do processo, pelo `.env` da skill ou por `python3 scripts/gb.py --env-file CAMINHO <subcomando> …`, como as demais `GB_*`.

| Variável | Fixa | Descoberta padrão quando ausente |
|---|---|---|
| `GB_YTDLP_PATH` | Executável do yt-dlp | `.venv/Scripts/yt-dlp.exe`, `.venv/Scripts/yt-dlp`, `.venv/bin/yt-dlp` e depois o `PATH` |
| `GB_VENV_PATH` | Pasta `.venv` usada para localizar o yt-dlp | `.venv/` na raiz da skill |
| `GB_FFMPEG_PATH` | Executável do FFmpeg | `ffmpeg` no `PATH` |
| `GB_FFPROBE_PATH` | Executável do ffprobe | `ffprobe` no `PATH` |

Precedência: a variável explícita vence a descoberta. Ausente ou vazia, o comportamento é exatamente o anterior. O valor é resolvido para caminho absoluto antes de qualquer validação, então um pin relativo não muda de significado conforme a pasta atual. Definida e apontando para um caminho inexistente, para algo que não é arquivo executável, sem permissão de execução ou — no caso de `GB_VENV_PATH` — que não seja diretório, o comando falha nomeando a variável e o caminho, em vez de voltar em silêncio à descoberta. `GB_VENV_PATH` apontando para uma venv **sem** yt-dlp também falha nomeando a variável, a pasta e os layouts procurados: o pin é uma promessa, não uma sugestão, e não há queda silenciosa para o `PATH`. `doctor` lista os pins ativos em `tool_paths`, uma linha por variável, mostra `{}` quando nenhum está definido e publica em `resolved` o executável absoluto realmente usado por ferramenta. Um pin inválido não derruba o `doctor`: ele aparece em `summary.missing` com a mensagem do erro, para que o diagnóstico continue legível. Não existe variável para o interpretador Python: a skill não reinvoca o Python em nenhum ponto.

```sh
GB_FFMPEG_PATH=/opt/homebrew/bin/ffmpeg python3 scripts/gb.py doctor
```

#### Brief e regras fora da pasta do projeto

`GB_BRIEF_FILE` e `GB_RULES_FILE` podem apontar para **qualquer lugar** da máquina — fora do projeto e fora da pasta da skill: um cofre de notas, um repositório de cliente, uma pasta sincronizada. Caminho relativo é resolvido a partir da pasta atual, e `~` é expandido. Como qualquer `GB_*`, valem pelo ambiente do processo, pelo `.env` da skill ou por `--env-file`.

`init-brief` escreve exatamente no arquivo que o `brief` vai ler, `GB_BRIEF_FILE` incluído, e **cria as pastas-mãe** que faltarem: `GB_BRIEF_FILE=~/clientes/acme/briefs/reel-01.md python3 scripts/gb.py init-brief --project .` funciona mesmo que `~/clientes/acme/briefs/` ainda não exista.

`GB_RULES_FILE` é outra coisa: não é o RULES.md do projeto, é uma **camada intermediária** entre o RULES.md global (`~/.getbrolls/RULES.md`) e o do projeto, e vem de fora do projeto — por isso os campos de responsabilidade (quem assina, a declaração) são descartados dela, com aviso. Ela precisa existir: apontando para um arquivo inexistente, o comando falha nomeando a variável. `init-rules` sempre grava o `RULES.md` da pasta do projeto (criando as pastas-mãe que faltarem), nunca o arquivo de `GB_RULES_FILE` — para preparar essa camada, copie `docs/RULES.md` para lá à mão e edite o bloco ```json.

### Codex e Claude Code

Use o repositório oficial [engenheirodevideo/get-brolls](https://github.com/engenheirodevideo/get-brolls): `git clone https://github.com/engenheirodevideo/get-brolls.git`. Clone ou copie a pasta completa da skill para **um** dos destinos abaixo. Escolha instalação pessoal ou por projeto para evitar duplicatas com o mesmo nome. Exclua `.venv/`, `.tools/`, `__pycache__/`, projetos e arquivos privados ao copiar uma árvore de desenvolvimento. Execute o instalador no destino final; não mova uma venv entre pastas:

| Agente | Pessoal | Projeto | Invocação |
|---|---|---|---|
| Codex | `~/.agents/skills/get-brolls/` | `.agents/skills/get-brolls/` | `$get-brolls` |
| Claude Code | `~/.claude/skills/get-brolls/` | `.claude/skills/get-brolls/` | `/get-brolls` |

Preserve cópias anteriores antes de substituir. Abra nova sessão para verificar descoberta. Use caminhos absolutos quando executar de outra pasta:

```sh
python3 "$GB_SKILL_DIR/scripts/gb.py" doctor
python3 "$GB_SKILL_DIR/scripts/gb.py" search --provider youtube --query "NASA Artemis" --limit 3 --project "$GB_PROJECT"
```

Defina `GB_SKILL_DIR` e `GB_PROJECT` com os caminhos reais. A trava de projeto usa o mecanismo nativo de cada sistema (`flock` em macOS/Linux e `msvcrt` no Windows). A CLI principal funciona sem Bash; Bash fica restrito aos helpers opcionais de YouTube.

### Verificação e atualização

Após instalar, confirme `yt-dlp` e `playwright-cli` em `doctor`. Para a CLI Playwright local, execute `bash scripts/playwright.sh --version` no macOS ou `& .\scripts\playwright.ps1 --version` no Windows. Um status positivo indica disponibilidade, não que todas as URLs serão acessíveis.

O conjunto de referência é yt-dlp 2026.08.19, EJS 0.8.0 e Playwright CLI 0.1.21. A partir da 2.3.5, `requirements.txt` fixa também as dependências Python transitivas nas versões instaladas pela CI macOS/Windows da 2.3.4. `package.json` e `package-lock.json` registram o conjunto npm; o instalador copia esses manifestos para `.tools/` e executa `npm ci --ignore-scripts`. Nenhuma biblioteca é incluída no repositório. Os executáveis Python, Node, FFmpeg e curl continuam sendo instalados pelo usuário.

Atualizações de dependências devem entrar por PR, com instalação completa e testes; o Dependabot está configurado para propor essas mudanças semanalmente. Preserve configurações privadas antes de atualizar a skill e repita um ensaio da rota utilizada se as dependências mudarem. Se você personalizou `.tools/node_modules`, `npm ci` substituirá essa árvore pela versão registrada no lockfile; mantenha ferramentas próprias fora da pasta gerenciada da skill.

Se `--check` falhar, instale o executável/versão apontado. Se a extração falhar, confirme primeiro que a URL abre no navegador autorizado; confira instalação, sessão e disponibilidade do post. Não peça chave YouTube. Para URL CDN Instagram expirada, recapture os dois canais e siga o guia de recuperação. Os testes reais documentados estão em [Qualidade e evidências](QUALITY.md).

## Compatibilidade

- Python 3.11+, FFmpeg/ffprobe; yt-dlp[default]/EJS e runtime JS para fontes sociais. Navegador/Playwright e curl no processo Instagram.
- O Storyboard usa navegador moderno com JavaScript, Blob e localStorage. Se armazenamento local falhar, exporte o JSON antes de fechar.
- Caminhos de prévias são relativos: compartilhe `brolls/` completo.
- CLI preserva schema do manifest v1 e adiciona `project_id`, metadados de prévia e revisão. Exportação de revisão usa `templateVersion: 2`.
- Artefatos do protótipo anterior não têm assinatura de fonte/intervalo; não podem ser importados. Regenere o storyboard com `review`.
- `--shot` permite múltiplos inserts da mesma fonte; sem ele, a resolução deduplica por fonte.
- Utilitários YouTube e coletor Instagram fazem parte do mesmo núcleo `scripts/getbrolls/`. Review usa GIF/imagens, sem player remoto incorporado.
- Projeto local confiável, uso serial. Comandos simultâneos no mesmo projeto são recusados. Não há colaboração multiusuário; evidências remotas por fonte estão em QUALITY.

Versão 2.3: asset_type/image, RULES e biblioteca de referências por projeto. APIs pesquisam vídeos; imagens e screenshots entram por arquivo local. Regras usam JSON embutido em Markdown; nenhum parser YAML externo é necessário.

2.3.1 centraliza a assinatura incluindo o escopo da prévia e arquivos de contexto. Regenere o storyboard de versões anteriores e solicite nova revisão; JSON antigo pode ser recusado como desatualizado. A trava local tem backend nativo para macOS, Windows e Linux.

### Agentes — revisão 2.3.2

Entrada no padrão Agent Skills (`name`, `description`, `license`, `metadata`). Metadados operacionais do vault ficam em `metadata`, sem campos próprios no nível superior do SKILL.md. Os demais documentos mantêm seu frontmatter operacional.

Codex e Claude Code usam a mesma pasta, com destinos e invocações descritos em GUIDE.md. `agents/openai.yaml` é opcional e específico do Codex. `CLAUDE.md` e `GEMINI.md` na raiz apenas roteiam para SKILL.md (operação) e AGENTS.md (manutenção), cobrindo a descoberta de contexto do Claude Code e do Gemini CLI sem duplicar instruções. Não há dependência de hooks, MCP, permissões preaprovadas ou sintaxe de interpolação exclusiva do Claude. Validação estrutural não equivale a teste de descoberta em uma sessão nativa de cada produto.

### Plugin do Claude Code — 2.3.6

A partir da 2.3.6, o repositório também é um marketplace de plugin do Claude Code (`.claude-plugin/plugin.json` e `.claude-plugin/marketplace.json`). A instalação usa dois comandos na sessão do Claude Code:

```text
/plugin marketplace add engenheirodevideo/get-brolls
/plugin install get-brolls@engenheirodevideo
```

Na primeira sessão, execute `/get-brolls-setup`: o comando em `commands/get-brolls-setup.md` roda `scripts/install.sh --check`, o instalador completo do sistema e o `doctor` pela raiz do plugin, e devolve o veredito em uma linha. A skill é acionada pelo contexto do pedido; a forma explícita é `/get-brolls:get-brolls`.

A skill do plugin fica em `skills/get-brolls/SKILL.md` e referencia os arquivos por `${CLAUDE_PLUGIN_ROOT}`, a raiz do plugin instalado — um diretório de cache versionado (`~/.claude/plugins/cache/engenheirodevideo/get-brolls/<versão>/`). Execute o instalador e o `doctor` pelo caminho absoluto dessa pasta, de qualquer cwd. As dependências ficam em `.venv/` e `.tools/` dentro da pasta do plugin: repita o instalador após cada `/plugin update` ou reinstalação, e prefira variáveis de ambiente ou um `.env` fora da pasta gerenciada para as chaves opcionais, apontado na raiz do parser: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/gb.py" --env-file CAMINHO <subcomando> …`. O fluxo clone-como-skill continua suportado sem mudanças para Codex e instalações manuais, com o SKILL.md da raiz como fonte canônica.

#### Permissões (opcional)

Se você não quiser confirmar cada execução do CLI, registre uma permissão própria com `/permissions` na sessão do Claude Code:

```text
/permissions
Allow → Bash
python3 */gb.py *
```

É uma escolha do usuário, não um requisito da skill: sem ela, cada comando é apenas confirmado na hora. A regra vale para o CLI do plugin em qualquer pasta; não conceda permissão ampla de shell.

### Migração para 2.3.5

Preserve `.env`, projetos, originais e `.getbrolls-sources/`. Atualize a pasta da skill e repita o instalador do seu sistema para aplicar o conjunto de dependências registrado. Gere novamente o Storyboard com `review`, confira as decisões e exporte um novo JSON. O importador agora confere `reviewEpoch`: um JSON sem esse campo ou baseado numa decisão substituída é recusado, mesmo que vídeo e intervalo sejam os mesmos. Isso também impede reimportar o mesmo JSON depois de sua primeira importação; exporte novamente do Storyboard atualizado. Nenhum item é salvo quando o lote contém uma decisão obsoleta. A atribuição `--by` continua sendo humana e não autentica o revisor.

O transporte HTTP de APIs e bancos conecta diretamente aos IPs públicos validados, mantendo a validação normal do certificado e hostname HTTPS. Redirecionamentos continuam bloqueados. Proxies configurados automaticamente no ambiente ou sistema não são usados por esse transporte; redes corporativas que exigem proxy precisam de uma conexão direta autorizada. Isso não configura nem altera os transportes externos de yt-dlp, curl ou navegador.

### Migração para 2.3.4

A prévia remota agora pode adquirir um trecho e guardar `local_start_s` junto ao hash da fonte. A assinatura inclui esse offset. Preserve o projeto e as decisões antigas como histórico, gere nova prévia/review e solicite nova decisão quando a revisão anterior for recusada por assinatura desatualizada. Não edite hashes/assinaturas para forçar uma aprovação antiga.

Projetos que já possuíam arquivo local continuam usando esse arquivo. Preserve os caminhos dos originais e `.getbrolls-sources/` para regenerar prévias; compartilhar só `brolls/` permite visualizar o storyboard, não continuar toda a edição em outro computador.

As plataformas ensaiadas na 2.3.4 permanecem registradas em QUALITY. A validação mantida atualmente usa um único job Windows com Python 3.14.4, incluindo testes, lint e tipos; a configuração está em `.github/workflows/test.yml`. O Windows usa instalador PowerShell, layout `.venv\Scripts` e trava nativa; os helpers Bash opcionais não fazem parte do caminho principal nesse sistema. Cada atualização deve passar pelo check do próprio PR antes do merge. As versões de dependências ensaiadas estão na seção [Instalação](#instalação).

## Fluxo editorial

Coleta B-roll dirigida pelo contrato de edição. Confirma no navegador antes de baixar; nunca autora vídeo.

### Fluxo
> **Literal primeiro.** O material padrão é footage, print ou imagem real do fato, da pessoa, do produto, da notícia ou da tela que a narração cita. Bancos de stock (Pexels/Pixabay) entram **somente quando o usuário pedir stock explicitamente** — nunca como preenchimento automático de um beat sem fonte literal. A responsabilidade pelas condições de uso do material é de quem produz o vídeo; a skill responde pela fidelidade/literalidade e pelo registro de origem de cada asset, feito por `permit` e pela proveniência gravada no ledger.
>
> **Meta editorial: 8+ clipes literais por roteiro quando o conteúdo comportar.** Se os beats óbvios não fecham 8, amplie: mais empresas/pessoas citadas, cobertura de telejornal do mesmo fato, produto nomeado, pregão/mercado real ou segmentos extras da mesma fonte forte. Prefira 1080p quando disponível e confirme com ffprobe; não faça upscale para simular qualidade.
1. **plan** — dos beats de `BRIEF.md` (substituiu `clips[].bloco_roteiro` na 2.4) ou da fala do roteiro, derive N beats visuais (query em inglês). Prefira **entidade literal nomeada** (pessoa/produto/logo do que a fala cita: Sam Altman, OpenAI, SoftBank, Codex…) — é onde o YouTube dá material real e limpo. Beats abstratos (back-office, "dev", "automação") caem em tutorial/vlog/stock/desenho; use no máximo um demo de produto real (ex.: dashboard ERP) ou deixe no rosto do talento.
2. **search** — candidato registrado no projeto, sem baixar: `python3 scripts/gb.py search --project <PROJETO> --query "<query>" --intent literal`. Acrescente `--shot <beat.id>` para já ligar cada candidato ao beat do `BRIEF.md` (mesma semântica do `resolve --shot`: o beat vira sufixo do id). Para sondar uma query sem sujar as contagens do projeto, use `--dry-run`: a fonte responde, a lista sai, e nada é gravado.
3. **confirm** — preview por **contact sheet** (não um frame solto): `python3 scripts/gb.py preview --project <PROJETO> --candidate <ID> --start <INICIO> --end <FIM> --narration "<fala>" --reason "<motivo>"` amostra quadros igualmente espaçados numa grade numerada para ler movimento, sequência e overlays antes de baixar. **Gate: o usuário ou revisor aprova antes do corte final** (`review`/`import-review` ou `approve --channel chat`).
4. **download** — segmento trimado 1080p, após aprovação e `permit`: `python3 scripts/gb.py fetch --project <PROJETO> --candidate <ID>`.
5. **verify** — `python3 scripts/gb.py verify --project <PROJETO>` (tabela ffprobe + tamanho).
6. **deliver** — `python3 scripts/gb.py deliver --project <PROJETO>` organiza o que já foi coletado em `entrega/`, uma pasta por beat (`NN-<beat.id>-<slug do alvo>`) com o `.mp4`, o contact sheet e um `ORIGEM.md` (fonte, autor, intervalo, direitos, sha256), mais um `entrega/README.md` com a tabela de tudo. Gráficos humanos aprovados com timing explícito e material resolvido saem em `entrega/graphics/<scene>/<occurrence>/<version>/`: clipe Full HD H.264 independente, `timing.json` (projeto/cena/ocorrência/versão/pai e hashes de conteúdo/vídeo), fontes editáveis, `public/fonts/` com a licença real quando o runtime Remotion congelou as fontes, refs brutas só quando `raw_redistribution` é `permitted`, e `separately-held.json` para o que permanece fora do pacote. O recorte local é `python rerender.py --browser-executable <navegador preparado>` (props como objeto, caminhos relativos ao pacote). Pacotes Remotion trazem `package.json`/`package-lock.json` na raiz do pacote: rode `npm ci --ignore-scripts` ali, ou crie um junction/symlink `node_modules` para uma árvore 4.0.534 já instalada, para `inputs/render.mjs` e `source/*.jsx` resolverem `@remotion/*` em `./node_modules`. `python rerender.py --check` valida caminhos, props-objeto, caminho do browser, `--held-ref` e as versões em cada `node_modules/<pacote>/package.json` contra os pins do `package.json` raiz (Remotion 4.0.534, React/dom 19.3.0, `@fontsource/ibm-plex-sans` 5.3.0); a existência de um diretório `node_modules/@remotion/bundler` não basta. `--check` não executa o worker, o browser nem prova aceitação visual. Refs brutas `restricted` exigem `--held-ref ref=<arquivo>` com o sha256 gravado; um reconhecimento sem esses bytes não basta. Isso vale também para cópias congeladas em `public/audio/`: bytes de efeito com `raw_redistribution` restricted/unknown não entram no pacote; um `--held-ref` do original reconstrói cada destino de cue congelado que referencia esses bytes em mídia temporária e não grava esses bytes no pacote. `--check` nomeia cada cue ausente e recusa sucesso só com acknowledgement. O pacote **não** é auto-contido; um `test-worker` sintético que rerenderiza não é sucesso do renderer Remotion. Repeat de um pacote íntegro reutiliza os arquivos gravados daquela versão quando identidade/conteúdo/vídeo e hashes continuam válidos, e não os reescreve só porque o gerador mudou. A pasta é derivada e regenerável: o `verify` a refaz sozinho ao terminar, `brolls/` continua sendo a verdade e nada lá é apagado ou renomeado. Os arquivos entram por **hardlink** (symlink e depois cópia, quando o sistema não deixar), então não ocupam disco duas vezes — mas hardlink é o *mesmo* arquivo com outro nome: **editar em `entrega/` é editar o original**. Gráficos entram por **cópia independente** (nunca hardlink). Por isso a mídia entregue nasce somente-leitura, e o `README.md` e cada `ORIGEM.md` dizem isso. Para receber cópias independentes e editáveis dos trechos, rode com `GB_DELIVERY_COPY=1`. Rodar de novo é seguro: nada muda, a data de `ORIGEM.md` dos gráficos permanece a da aprovação, links órfãos somem, e o que você criou dentro de `entrega/` é preservado e listado em `kept`. Um arquivo entregue que você editou não é sobrescrito — o comando termina o resto e falha no fim nomeando todos os conflitos. `--dry-run` mostra o plano sem escrever nada (nem na pasta, nem no manifesto) e reporta o método como `planned`.

### Imagens de notícia (manchete/dado)
- **Rota completa do print de tela** (capturar, registrar, revisar) em [`references/providers.md`](../references/providers.md).
- **Print de site precisa virar arquivo local verificável.** Use a captura do navegador autorizado, confira o arquivo visualmente e importe com URL, manchete, autor e data reais. Se a integração só devolver um identificador interno sem caminho acessível, registre a limitação em vez de prometer o asset.
- **Prefira notícia em VÍDEO**: cobertura real (Reuters/CNBC/Bloomberg) no YouTube pelo mesmo fluxo (vira mp4 no projeto).
- **Estático** = entregar **lista de links + o que grifar** num `BROLL-MAP.md`, pro humano printar. Alguns sites (PYMNTS) caem em Cloudflare; Benzinga abre normal.

### Engine
Motor: `yt-dlp` + FFmpeg pela CLI (`scripts/gb.py`). Capturas de página usam a integração de navegador autorizada ou o launcher Playwright do sistema. Os helpers `.sh` que existiam antes da CLI unificada continuam disponíveis só como utilitários avulsos — ver [Apêndice — utilitários legados](#apêndice--utilitários-legados).

### Saída
`<PROJETO>/brolls/NN_entity_context.mp4`. Registrar no ledger (`step: get-brolls`, outputs = arquivos baixados).

### Medição editorial deste fluxo

Se a pergunta é "esse fluxo está achando fonte literal de verdade?", a resposta não vem da suíte de testes: vem dos **testes cegos** em [eval/README.md](../eval/README.md). Um agente executor recebe só o roteiro, roda `search` → `preview` → `review` e para na revisão humana; outro agente (ou o humano) pontua cada beat pela rubrica — alcance literal, literalidade do asset, qualidade da prévia e disciplina (nada de stock sem pedido, nada aprovado sozinho). Os relatórios ficam em `eval/runs/`, e o comando `/get-brolls-eval` roda um caso do corpus de ponta a ponta.

## Estado do projeto e progresso

`status` responde "onde estamos?" para um projeto, sem alterar nada. Ele lê o que já está gravado — manifesto, candidatos, decisões e journal — e devolve contagem e lista de IDs por etapa: candidatos encontrados, prévias geradas, decisões pendentes/aprovadas/rejeitadas, itens com `permit` registrado, itens entregues e itens verificados.

```sh
python3 scripts/gb.py status --project /caminho/meu-video
```

O JSON segue a convenção dos demais comandos e traz, como no `doctor`, um objeto `summary` na frente: `line` (uma frase com as contagens), `stages` (rótulo, contagem e IDs de cada etapa) e `next` (o próximo passo real do fluxo). Abaixo dele vêm `counts`, `stages`, `items` (um resumo por candidato: estado, aprovação, direitos, prévia e arquivo final), `references`, `review_page` e `journal` (eventos registrados, último evento e se houve recuperação de gravação).

`status` é somente leitura: não grava manifesto, candidatos, prévias, clipes nem eventos, e não cria a árvore `brolls/` — num projeto inexistente ele responde "Projeto não encontrado em …; nenhum arquivo foi criado." sem escrever nada. O único arquivo tocado num projeto existente é o `brolls/diagnostics.jsonl` da auditoria. Também **não pega a trava exclusiva do projeto**: pode ser executado enquanto um `fetch` longo está em andamento, sem esperar nem falhar. Uma regressão offline compara o conteúdo e o mtime de todos os arquivos do projeto antes e depois da execução.

Mensagens de erro de `yt-dlp`, `curl`, `ffmpeg`/`ffprobe` e HTTP agora trazem o código de saída/HTTP e as últimas linhas do stderr/corpo da resposta (sempre redigidas: sem URL assinada, chave ou token) em vez de uma frase genérica — use esse trecho para diagnosticar antes de repetir o comando. Um bug interno (não um problema de dados/rede) sai com `error_code: "INTERNAL_ERROR"` e a mensagem pede para reportar `brolls/diagnostics.jsonl`, onde ficam `type`, `repr` e o traceback (também redigido) daquela execução; qualquer exceção não tratada na CLI também vira esse mesmo envelope JSON, nunca um traceback cru no terminal.

Como só lê, `status` nunca completa uma gravação interrompida: quando existe `.pending-transaction.json`, ele reporta `journal.recovered_write: "pending"`, avisa na linha do resumo e deixa a pendência para o próximo comando de escrita. Pelo mesmo motivo ele não aplica `sync_formats`: se as regras editoriais passaram a mirar outro formato, o relatório traz `format_pending` (total e por item) e `next` avisa quantas aprovações o próximo comando invalidará. `RULES.md` ilegível vira `rules_error` no lugar de uma falha, e `events.jsonl` ou `references.json` corrompidos degradam para contagem com `error`, preservando os arquivos.

### Convenção do campo `summary`

Workflow commands (`search`, `resolve`, `preview`, `review`, `import-review`, `permit`, `fetch`, and `verify`) add a `summary` field to their JSON output. `preview`, `review`, and `import-review` use English summaries; other routes may still use Portuguese during migration. The summary states the action, object, and result. This is an additive field: existing JSON keys and types remain unchanged. Use this line to explain the completed action and `status` for the complete collection state.

## Fontes e transportes

| Fonte | Descoberta | Aquisição |
|---|---|---|
| YouTube | ytsearch sem chave | yt-dlp, intervalo via FFmpeg |
| Instagram | navegador/URL | navegador captura vídeo+áudio; coletor de pares incluído; yt-dlp como outra rota |
| TikTok | navegador/URL completa | yt-dlp |
| Pexels | API, PEXELS_API_KEY | HTTPS e cache de original para prévia |
| Pixabay | API, PIXABAY_API_KEY; cache 24 h | HTTPS e cache de original para prévia |
| Commons / NASA | APIs sem chave; imagem e vídeo | HTTPS |
| Archive.org | Public search and item/file metadata | Selected public file via HTTPS; restrictions remain explicit |
| Local | resolve --file | arquivo local |

Fluxo único: descobrir → obter mídia de trabalho/mostrar sequência → revisão humana → corte final → verify. Prévia não equivale a aprovação. `--reference-only` é opção explícita para não adquirir mídia. Consulte o guia da fonte; Instagram começa na seção [Instagram pelo navegador](#instagram--navegadorplaywright-dois-streams-e-mp4).

`providers` declara transporte/capacidades implementadas e configuração, não garantia de acesso universal. `auto` segue a ordem de fontes das regras e o intent. Prefira entidades literais quando o roteiro citar pessoa/produto/fato.

## Inspeção de idioma e momento dentro do vídeo

Escolha o idioma para cada vídeo conforme a fala original e as faixas disponíveis. O idioma do roteiro ou da busca no catálogo pode ser diferente; `search --language` não define automaticamente o idioma de `inspect`. Escreva a consulta no idioma da faixa desejada e passe-o explicitamente:

```sh
python scripts/gb.py inspect --candidate ID --query "eclipse parcial" --language es --project PROJECT
python scripts/gb.py inspect --candidate ID --query "оранжевое небо" --language ru --project PROJECT
python scripts/gb.py inspect --candidate ID --query "північний Київ" --language uk --project PROJECT
```

`--url URL` pode substituir `--candidate ID`. Códigos regionais como `es-419`, `ru-RU`, `uk-UA`, `pt-BR` e `en-US` são aceitos. Um código seleciona uma faixa adequada daquela língua; códigos de região e o sufixo `-orig` são considerados. Nomes próprios curtos não determinam o idioma com segurança. A tokenização preserva letras cirílicas, inclusive `й`, `ї` e `ё`, mantendo a normalização de acentos latinos.

Na rota yt-dlp, primeiro vêm os metadados; um JSON privado é reutilizado para obter somente as faixas selecionadas, sem outra extração da página nem download de vídeo. Prefira uma legenda autoral adequada, depois uma automática original. Sem `--language`, a língua original declarada tem prioridade; só quando ela é desconhecida entram as alternativas PT/EN existentes ou uma única faixa de amostra. Um pedido explícito pode obter a faixa desse idioma e a original, com no máximo três tentativas de faixa no total. Uma legenda autoral original sem texto permite uma única tentativa de reserva na automática original. As centenas de traduções anunciadas não são baixadas. Se houver várias faixas `*-orig`, use a língua de áudio declarada; sem essa informação, mantenha a original desconhecida.

`subtitle_langs` lista faixas anunciadas; `obtained_subtitle_langs` lista as que realmente deram texto. `subtitle_tracks` registra `language`, `kind` (`manual`/`automatic`), `is_original` (ou `null`), `status` (`obtained`/`empty`/`unavailable`) e `cue_count`. Falhas e ausência do idioma pedido aparecem em `warnings`; o texto de outra língua não comprova ausência do assunto. `original_lang` e `query_language` preservam a distinção entre fonte e consulta. As rotas de captions de Archive.org/LoC e de transcritos UN continuam próprias; idioma desconhecido permanece `und`, sem tradução, modelo pago ou reconhecimento de áudio adicional.

Cada janela de legenda traz `language`, `subtitle_kind` e `is_original`. A CLI pontua todas as faixas antes de escolher uma representação de intervalos iguais; em empate, prefere a língua da consulta e a proveniência original/autoral. Capítulos, timestamps e pontos igualmente espaçados continuam disponíveis quando não há texto útil. `preview --scan` pede apenas os metadados de duração nessa rota, sem obter legendas. Uma correspondência textual orienta o próximo `preview`: abra o contact sheet ou a mídia real para confirmar o que aparece antes da revisão humana e dos direitos.

Os flags de legendas seguem a [documentação oficial do yt-dlp](https://github.com/yt-dlp/yt-dlp#subtitle-options): legendas autorais e automáticas são opções distintas; a seleção de idiomas é restrita aos códigos escolhidos.

## Provedor — YouTube

Motor: yt-dlp + FFmpeg, **sem API key**. `search --provider youtube` usa ytsearch. `resolve --url` aceita URL de vídeo/shorts; `preview` obtém o intervalo e gera GIF/contact sheet, mantendo aprovação pendente. `fetch` publica os bytes revisados após decisão humana e registro de condições do projeto. Canal, id do vídeo e o intervalo escolhido ficam no candidato. `inspect` lê capítulos e legendas quando o yt-dlp as entrega. Se a página reportar disponibilidade diferente de pública, limite de idade ou transmissão ao vivo, isso entra em `limitations`; campo ausente continua desconhecido. `--media image` neste provedor é recusado: YouTube não faz busca de foto.

Fluxo: `search --provider youtube --query "..."` → `preview --candidate ID --start ... --end ...` → `fetch --candidate ID` → `verify --project ...`. Configure EJS/runtime conforme este guia. Se o site exigir sessão ou negar mídia, reporte o erro real; não troque silenciosamente para API com chave. Os scripts `.sh` de `scripts/getbrolls/tools/youtube/` que usam `VIDEO_ID` direto continuam existindo como utilitários avulsos, fora do ledger/revisão — ver [Apêndice — utilitários legados](#apêndice--utilitários-legados).

## Provedor — Instagram

Rota principal: **navegador/Playwright → URL CDN de vídeo + URL CDN de áudio → curl → FFmpeg → ffprobe**. Leia a seção [Instagram pelo navegador](#instagram--navegadorplaywright-dois-streams-e-mp4) e use o coletor incluído em `scripts/getbrolls/instagram_pairs.py`.

O MP4 unido entra com `resolve --file --source-url --creator --shot`; depois preview/review/fetch. O browser captura os streams; o script baixa/junta. Não exige chave da API oficial Instagram. A página pode exigir sessão. yt-dlp também está disponível via URL completa, se funcionar para aquele post; falha dessa rota não remove o fluxo de navegador.

## Provedor — TikTok

Recebe URL completa `https://www.tiktok.com/@usuario/video/ID` e usa o extrator TikTok do yt-dlp para obter o intervalo. `resolve --url`, `preview`, revisão e `fetch` seguem o mesmo fluxo. Sem API key da plataforma.

The installer includes pinned `curl-cffi` and its dependencies for yt-dlp's TikTok web transport. A working authenticated browser does not establish that a separate yt-dlp process has the required transport or access. On extraction failure, confirm the installed dependencies before attributing the failure to the post; keep unavailable/session/rate-limit outcomes explicit. No browser cookies are exported by this route.

Descubra a URL pelo navegador; não há busca global TikTok por palavra-chave implementada. Links encurtados precisam ser abertos no navegador para obter URL canônica. A existência do extrator não garante acesso a todo vídeo; teste a URL real e registre eventual exigência de sessão/indisponibilidade. Consulte [Qualidade e evidências](QUALITY.md) para a evidência desta versão.

Desde a 2.4.0, `resolve --url` de um post do TikTok faz **um** pedido de metadados ao yt-dlp (`--dump-single-json --skip-download`) e já grava `title`, `creator.name`, `creator.handle` (o `@usuario`) e `media.duration_s`. Antes disso o candidato entrava como `TikTok · <id>` com autoria e duração nulas, e o checkpoint C2 — "título, canal, duração" — não tinha o que listar. O pedido é opcional por construção: se a página recusar (post privado, região bloqueada, 429), o candidato é registrado do mesmo jeito, com os campos vazios e um aviso no diagnóstico.

**Como achar os posts recentes de um perfil.** A grade pública de `tiktok.com/@usuario` não serve para visitante: ela carrega por JavaScript atrás de checagem de sessão, e um visitante deslogado recebe uma página vazia ou um desafio. A rota que funciona sem sessão é a página de incorporação — `https://www.tiktok.com/embed/@usuario` —, que lista os posts recentes do perfil com os ids de cada um no HTML. Abra essa página no navegador, colete os ids que interessam e monte a URL canônica de cada um (`https://www.tiktok.com/@usuario/video/<id>`) para passar ao `resolve --url`. Continua valendo o de sempre: a página de incorporação é ponto de partida para achar o endereço, não autorização de uso — as condições do post seguem pelo `permit`, como em qualquer outra fonte.

## Browser attempts and archive locators

Instagram, TikTok, `un_avlibrary` and `destockd` use agent-operated browser discovery. Save the fragment's `search-plan` first, with its catalog allowed in `BRIEF.md`. Reserve **before** the external query or profile/card browsing:

```sh
python scripts/gb.py search-browser --shot opening --query "factory" --language en --media video --project PROJECT
```

The returned `attempt.id` identifies a durable reservation, not a completed search. The agent performs the actual search in the available authorized browser, then records the observed outcome:

```sh
python scripts/gb.py search-import --shot opening --attempt ATTEMPT_ID --outcome results --results public-results.json --assessment "Observed cards reviewed for this fragment" --coverage incomplete --project PROJECT
python scripts/gb.py search-import --shot opening --attempt ATTEMPT_ID --outcome empty --assessment "The actual search returned no results" --project PROJECT
python scripts/gb.py search-import --shot opening --attempt ATTEMPT_ID --outcome access-failure --assessment "The page requires an authorized session" --project PROJECT
```

Choose one outcome. An access failure has no coverage verdict and does not establish absent footage. Reservation spends one of the existing three queries per catalog/pass. Language changes and normalized replay do not create extra allowance. Restart preserves uncertain attempts; complete their known outcome, or use `search-assess` to explain an interruption before continuing. Importing the identical outcome is idempotent; rewriting a completed outcome is refused. Both commands support `--dry-run`, preserving manifest and event history. They do not execute browser searches or call website APIs.

`public-results.json` is an array of 1–50 observed rows (maximum 512 KiB). Each row uses `url`, with optional public `title`, `creator`, `account`, `date`, `description`, `language` and `poster_url`. UN also accepts `asset_id` without a URL. Locator rows additionally accept `preview_url` (an observed public media file), `request_url`, `shotlist`, `shotlist_url`, and `source_interval` with original-film `start_s`/`end_s`. Destockd can retain observed `film_title`, `archive_url` and `archive_file`. Include only observed values; omit unknown fields. Signed transport URLs, credentials, cookies, blob URLs and unrecognized fields are refused.

```json
[
  {
    "url": "https://destockd.com/#/shot/SYMPHONY%20IN%20F/shot_080",
    "film_title": "SYMPHONY IN F",
    "archive_url": "https://archive.org/details/fc-fc-4355_HD_2Mbps",
    "preview_url": "https://clips.destockd.com/clips/SYMPHONY%20IN%20F/shot_080.mp4"
  }
]
```

This dated example records an observed card; its original-film interval was not shown. Shot numbers, film keys and preview duration are not timing evidence. Imported social posts retain their canonical identity and observed caption/account context. Instagram stream pairs stay in the existing private capture/collector route; TikTok short links need browser resolution to the complete post URL before import. Global social keyword APIs remain unimplemented.

**UN Audiovisual Library.** `resolve --url CARD_URL` or `resolve --un-asset-id d2313786` registers an archive reference without a search request. UNifeed asset IDs use this same provider. `license_required` remains visible; the archive is not automatically public domain. A player or blob reference alone supplies no downloadable editing original.

For a known UN or Destockd card, `resolve --locator-metadata observed-card.json` imports one observed public metadata object using the same fields and validation as `search-import`. Its URL/Asset ID must match the selected card. This direct import does not reserve or claim a browser search, consume a query, or replace changed metadata on an existing candidate. Use another fragment record for changed context. Cookies, signed transport URLs and blob URLs remain forbidden in that JSON.

For an actually available UN player, `preview_url` may equal its canonical asset card. `inspect` and `preview` then use yt-dlp on that public card; extracted transport details stay private. This supports the observed Kaltura sample, not every historical player. Failure remains an explicit access limitation. Direct public MP4/WebM/MOV/M4V previews retain their HTTPS-file route. Both player and file previews remain viewing references, deferred from the suitable-option target and blocked from final acquisition as editing originals.

```sh
python scripts/gb.py resolve --un-asset-id d2313786 --locator-metadata observed-card.json --shot opening --project PROJECT
```

The metadata object uses the observed `asset_id`, title/date/description, optional script/shotlist reference and request link, with `preview_url` set to the canonical card only after confirming its player. Keep unavailable original timing and authorship unknown. Supplied originals continue to use the separate command below:

```sh
python scripts/gb.py resolve --file SUPPLIED_ORIGINAL --original-for LOCATOR_ID --original-conditions "Recorded supplied-file conditions" --project PROJECT
```

The new candidate retains the locator, observed original interval and conditions. These conditions do not grant rights. The command does not send a footage request, accept terms, pay fees or make a licensing declaration.

**Destockd.** The website and complete `#/shot/<film>/<shot>` link are supported. Only the website UI is used for discovery; the CLI does not call the undocumented `/api/` route. When the page supplies an Archive.org original, use its actual item/file:

```sh
python scripts/gb.py resolve --url ARCHIVE_ITEM_URL --archive-file ACTUAL_FILE --original-for LOCATOR_ID --project PROJECT
```

The observed source-film link/file must match. A supplied local original is another explicit route. Destockd shot identity and Archive item/file identity stay separate. Original times remain provenance; `preview --start/--end` always selects times in the newly acquired representation, without adding the locator's offset again. When the original mapping is unknown, keep it unknown and inspect the source before selecting a cut.

Public locator previews can pass `inspect`, `preview` and Storyboard when a supported media file was actually observed. They remain deferred in the suitable-option count and cannot be fetched as cleared originals. Linked originals use the common viewing/confirmation, human review, rights, fetch and delivery gates. A general public-domain label on a search website does not clear the actual original or third-party inserts.

## Provedor — Pexels

PEXELS_API_KEY no ambiente. API de vídeos, poster e variante MP4 até 1080p. A busca não usa o cache de um dia. Reconsulta o id na prévia e no fetch, troca a URL e as dimensões anunciadas, e preserva aprovação e intervalo. `video_pictures[].nr` é índice de quadro de poster, não um segundo do vídeo. O candidato fica `stock: true` e `match.kind: illustrative`: a correspondência visual não está confirmada e a licença não é permissão de uso. `--media image` é recusado. https://www.pexels.com/api/documentation/

Diagnóstico: `python3 scripts/gb.py providers`. Falha de credencial não ativa scraping ou outra conta.

## Provedor — Pixabay

PIXABAY_API_KEY no ambiente. Busca de vídeos com cache de 24 horas, também na reconsulta por id. A miniatura da variante escolhida é cartaz; não é um segundo do vídeo. O candidato fica `stock: true` e `match.kind: illustrative`. `--media image` é recusado. Verifique licença e autoria. https://pixabay.com/api/docs/

Diagnóstico: `python3 scripts/gb.py providers`. Falha de credencial não ativa scraping ou outra conta.

## Provedor — Wikimedia Commons

Action API pública aceita imagem e vídeo. A busca, o resolve e o refresh pedem `mediatype` no `imageinfo`, junto com URL, tamanho e MIME; busca e resolve também pedem `extmetadata`. `VIDEO` entra como vídeo. `BITMAP` e `DRAWING` entram como imagem. `AUDIO`, office, texto, executável e os demais tipos declarados ficam de fora, mesmo quando o MIME parece imagem ou vídeo. Sem `mediatype`, só MIME que começa com `video/` ou `image/` entra, então `application/ogg` sozinho não vira vídeo. O MIME gravado continua o valor da API. O nome do arquivo não escolhe o tipo. A busca usa um `imageinfo` e escolhe a URL do arquivo; `thumburl`, mesmo com `time=`, é só cartaz e não prova corte no servidor. A busca não pede `videoinfo`. O `resolve` de um vídeo grava derivatives com `transcodekey` e faixas com `srclang` nesse candidato. A prévia baixa de novo o arquivo original e não copia esse detalhe para o candidato salvo na busca. Ao resolver ou atualizar um vídeo, derivatives e timed text entram só se `videoinfo` responder. A lista `derivatives` pode repetir o arquivo original sem `transcodekey`, às vezes só com parâmetros de rastreio na URL: esse arquivo continua um único `original`. Linha com `transcodekey` é um transcode e guarda essa chave. Um vídeo que não é o original e não tem `transcodekey` fica como representação utilizável, sem um papel inventado. Imagem nessa lista continua cartaz. O TimedMediaHandler publica cada faixa com `srclang`, `src`, `kind`, `type`, `label` e `dir`. O candidato guarda `srclang` em `commons.timed_text[].lang` e o `src` em `url`, mais esses campos quando vêm preenchidos; `lang` e `language` continuam aceitos como apelidos. Isso é o endereço da faixa descoberta: a CLI não baixa nem lê o VTT e não inventa tempos de legenda. Se o módulo faltar, a resposta vier vazia ou o metadado opcional vier malformado, o arquivo original continua utilizável e `videoinfo` fica `absent` quando a consulta não responde. Autor, licença e atribuição são os da página do arquivo. Licença desconhecida nunca vira domínio público. https://commons.wikimedia.org/wiki/Commons:API/MediaWiki e https://www.mediawiki.org/wiki/Extension:TimedMediaHandler/API

Diagnóstico: `python3 scripts/gb.py providers`. Falha de credencial não ativa scraping ou outra conta.

## Provedor — NASA

Images API pública, sem chave geral de desenvolvedor, resolve imagem e vídeo pelo `nasa_id` e pela lista `/asset/`. Essa lista publica os arquivos de `images-assets.nasa.gov` em `http://`. O `get_json` já troca `http` por `https` só nesse host, sem usuário e sem porta, ao limpar o JSON, antes de devolver o corpo e antes da validação de URL pública. Outro host, credencial ou consulta assinada continua rejeitado. A miniatura de busca é cartaz, mesmo quando o link de preview já é `https://`. O candidato guarda centro, data e autoria de terceiros em `nasa`; `creator.name` usa o terceiro quando existe, senão o centro. Direitos ficam `unknown` até `permit`. A descrição do item não é evidência de uso. Essa troca de esquema no transporte não baixa nem decodifica o arquivo. https://images.nasa.gov/docs/images.nasa.gov_api_docs.pdf

Diagnóstico: `python3 scripts/gb.py providers`. Falha de credencial não ativa scraping ou outra conta.

## Providers — LoC, DVIDS, Europeana and NARA

`loc`, `dvids`, `europeana`, and `nara` use the same fragment chains, saved three-query allowance, preview, visual confirmation, Storyboard, human approval, and separate rights/acquisition gates described below. Both images and videos are supported. One search requests one bounded page; the returned items are not complete catalog coverage. Detailed metadata is refreshed for the selected original. Multiple independent resources/digital objects require an explicit `resolve --catalog-file <file-URL-or-NARA-object-ID>`; refresh never substitutes a missing selected file. An explicit representation change for the same original/fragment replaces the saved choice, clears its cached-media/preview references, and invalidates prior review, output and reuse decisions; existing files and events remain preserved. An ordinary resolve/import rerun still cannot silently replace provenance. Search posters are references, not originals. A record with no supported public original remains visible with `acquisition.method: manual` and its access limitation.

| Provider | Access and original selection | Search filters |
|---|---|---|
| `loc` | Public [JSON API](https://www.loc.gov/apis/json-and-yaml/). Item/resource variants preserve page/resource identity, dimensions, item rights and access advisories. Highest reported usable quality is selected; absent geometry stays unknown. Official legacy LoC HTTP identifiers become HTTPS. | `fa` accepts combined facets for format, collection, contributor, place or language (separated with `\|`); `dates=1900/1920`. `--media` adds an online-format facet. |
| `dvids` | `DVIDS_API_KEY`, with optional `DVIDS_CLIENT_SECRET` used as the server `api_key` without a browser Referer, per [API documentation](https://api.dvidshub.net/docs). No upload OAuth scope. Actual image/MP4 files retain asset ID, unit, creator, location, capture date and separate publication date. | `category=B-Roll`, `branch=Army`, `country=United States`, `city=Fort Riley`, `state`, `unit`, `unit_name`, `unit_id`, `from_date`, `to_date`, `from_publishdate`, `to_publishdate`, `from_duration`, `to_duration`, `hd=1`. |
| `europeana` | `EUROPEANA_API_KEY` and confirmed `EUROPEANA_KEY_TYPE`: `personal` for development experiments, `project` for operational use, following the [issued key terms](https://www.europeana.eu/en/how-to-register-for-and-manage-an-api-key). An unset/invalid type refuses network access. The record retains institution, original record/media link, creator/date and resource rights. An institution HTML page or thumbnail alone is a manual locator. | `qf=LANGUAGE:en`, `qf=YEAR:1910`, `qf=DATA_PROVIDER:"Institution name"`, `theme=map`, `reusability=open`, `media=true`, `landingpage=true`. `--media` refines TYPE. |
| `nara` | `NARA_API_KEY` in a private `x-api-key` header, using [Catalog API v2](https://github.com/usnationalarchives/Catalog-API). One candidate per digital object retains NAID, object ID/file, collection, date, creator and use/access restrictions. API access does not grant rights to every object. | `ancestorNaId`, `recordGroupNumber`, `collectionIdentifier`, `creators`, `geographicReference`, `startDate`, `endDate`, `objectType`, `typeOfMaterials`, `availableOnline`, `levelOfDescription`. |

Pass `--catalog-filter KEY=VALUE` repeatedly for different fields. Duplicate/unknown fields and credential, limit, or paging overrides are refused. Changed filters consume another meaningful query within the saved allowance; the same normalized query/media/filter set replays without spending one. Use the same filters with `search-assess` when otherwise identical attempts need distinguishing. Choose an explicit provider for catalog-specific filters; auto routes diagnose incompatible filters per catalog. NARA image selection includes supported scans/maps in textual collections rather than forcing the photographic record type; returned digital objects are filtered by actual file kind.

Examples (replace project paths and record identifiers):

```bash
python3 scripts/gb.py search --provider loc --query "Brooklyn bridge" --media image --limit 3 --catalog-filter "dates=1900/1920" --project <project>
python3 scripts/gb.py search --provider dvids --query bridge --media video --catalog-filter "category=B-Roll" --catalog-filter "hd=1" --limit 3 --project <project>
python3 scripts/gb.py resolve --url https://catalog.archives.gov/id/<NAID> --catalog-file <OBJECT_ID> --project <project>
```

`inspect` reads supplied, credential-free SRT/VTT captions through the existing bounded reader (three files, 2 MiB each). LoC plain `.txt` transcripts appear in `source_transcripts` with a 32,768-character excerpt and explicit truncation; untimed text never becomes invented timed cues. Inspection of a catalog search asset records the actual selected file before cache reuse; changed source context invalidates stale approval without approving anything. HLS-only, credential-bearing links and unconfirmed LoC streaming services remain unsupported/manual. Missing keys, rejected access, empty results and incomplete coverage stay distinct. `providers` separates implementation, configuration and dated live evidence; see [QUALITY.md](QUALITY.md).

**LoC browser verification.** A recognized CAPTCHA/Cloudflare challenge reports `BROWSER_VERIFICATION_REQUIRED`, not invalid credentials or an empty catalog. Complete the challenge yourself in the authorized browser. Its clearance belongs to that browser; the CLI does not export cookies or bypass protection. For a planned query, run `search-browser` with the same fragment, query, language, media and catalog filters, then perform the browser search and use `search-import`. The failed API attempt becomes the browser reservation without spending another query, even when it was the third attempt; a closed fragment/catalog stays closed. The original API error remains in the history. Browser imports require an observed canonical LoC `/item/<id>/` URL and `media_kind: image` or `video`, with public title/creator/date/description when observed. They are manual locators, not API-resolved originals. Download the actual selected file through its normal item-page control and import it with `resolve --file <file> --original-for <locator-id> --original-conditions "<observed file/source conditions>"`. Preview, visual confirmation, human review and rights gates stay separate. Replaying the reservation/import does not reset allowance or rewrite the saved outcome.

**Europeana manual institution file.** When the selected record lacks a supported direct media URL, obtain the actual observed institution representation through its normal page/file control. Use `resolve --file <file> --original-for <europeana-candidate-id> --original-conditions "<actual institution file, source and limitations>"`. This keeps the original record reference and saved fragment narration while the file's own hash and measured media remain separate. A different Archive.org item cannot be supplied as this institution file. A thumbnail or IIIF reference alone does not prove an original; record conflicting record/resource rights and keep permission unknown. Prepared images and original news/web screenshots use their poster in `review --ready-only`.

**Known LoC card and supplied master.** When the canonical item is already known and its normal page/file controls were observed, use `resolve --url <canonical-item> --locator-metadata <observed.json>` without inventing another keyword search or dispatching the blocked API. The JSON contains that same `url`, an observed `media_kind` (`image` or `video`), and only the documented public title/creator/date/description/poster fields; unknown fields stay unknown. The result is a manual locator, not an API-resolved file. Native `--catalog-file`/`--archive-file` selectors cannot be combined with this import. Link the actually obtained master with `resolve --file <master> --original-for <locator-id> --original-conditions "<observed source and file limitations>"`. Both `.tif` and `.tiff` are still images: their actual dimensions are measured, while duration and frame rate remain unknown. Preserve the public item/resource identity and the local file hash; a successful browser page or thumbnail does not establish original quality, rights or approval.

## Providers — GDELT TV, EC Audiovisual and UN Web TV

These three providers reuse `search-plan`, `search --planned`, visual confirmation and the existing Storyboard. Every language or filter change shares the catalog's three-query allowance. Discovery is credential-free; an actual file, decoded preview, suitable option, access decision, usage rights and human approval are separate facts.

**EC Audiovisual (`ec_audiovisual`).** Video search requests `VIDEOSHOT` before `VIDEO`; `--media image` requests `PHOTO`/`REPORTAGE`, and `any` permits all four. One query returns at most five candidates. `--catalog-filter type=VIDEO` selects whole recordings, or choose one other actual record type. The read-only AV Portal client uses `kwgg` for keywords, a one-hour cache and a bounded fallback endpoint. Unversioned endpoint/schema failures are access errors. There is no embedded bearer or new API key.

The candidate ID retains the exact shot; the public URL identifies its parent recording. `catalog.provider_source_start` and `provider_shot_duration` retain the provider's source-clock window. `preview` uses that window when times are omitted. `--source-start` is an alias for `--start` and overrides the provider start; an omitted end uses the shot duration. All explicit times refer to the parent source. Direct MP4 caches start at zero; an HLS section cache records its nonzero source offset. The final cut subtracts that cache offset once. Long shots still need a shorter end within the preview limit.

```sh
python scripts/gb.py search --planned --shot opening --query "climate" --media video --limit 2 --project PROJECT
python scripts/gb.py preview --candidate EC_SHOT_ID --end 9.36 --project PROJECT
python scripts/gb.py preview --candidate EC_SHOT_ID --source-start 10 --end 13 --project PROJECT
```

Real representations prefer H.264 1080p, 720p, 480p, legacy high/low, then HLS; photos prefer `ORIGINAL`. Available metadata/media language prefers EN, INT, FR, then the first available language. Dimensions remain unknown until measured. `resolve --url EC_RECORD_URL --catalog-file PUBLIC_MEDIA_URL` pins an actual offered variant. Refresh refuses a missing shot/file and invalidates review when the parent, timing or conditions change. Copyright holder/year, location, scope and exceptions are retained; a numeric `cc_by` grants no license.

**Independent access.** Restricted EC records (`download_enabled=N` or `isDownloadable=false`) remain visible. All UN Web TV media acquisitions require an explicit decision already supplied by the person responsible for access:

```sh
python scripts/gb.py access --candidate ID --by "PERSON" --evidence "Actual supplied access decision and conditions" --project PROJECT
```

This records the decision for the exact asset and current brief, without approval or a reuse grant. A changed brief or relevant source conditions requires a new decision. It gates cached media as well as new downloads. Restricted EC inspection may acquire a complete direct file and therefore also requires access; UN player metadata and public transcript inspection can run before media acquisition. `permit` and human `approve` remain separate requirements for `fetch`.

**UN Web TV (`un_webtv`).** Full-text search uses public UN Transcripts `ft=1`. Select `--language en|fr|es|ar|zh|ru`; it becomes the effective `locale` filter and replay identity. Default locale is `en`; a conflicting `--catalog-filter locale=...` is refused. Queries need at least two characters. Other filters are `category`, `date`, `from`, `to`, `sort`. One bounded first page produces at most five selected meetings. Matching text/speaker/start/deep links and meeting date are retained. Automatically generated transcripts are not official records or documents of the United Nations.

```sh
python scripts/gb.py search --planned --shot opening --query "climate" --language en --media video --limit 1 --project PROJECT
python scripts/gb.py inspect --candidate UN_ID --query "climate" --project PROJECT
python scripts/gb.py resolve --url https://webtv.un.org/en/asset/k14/k140iyou7p --project PROJECT
```

Recent meeting search covers the last 365 days. Find older pages through the Web TV catalog/browser and resolve their complete asset URL; missing recent transcripts do not prove an older video is absent. Inspection checks the actual yt-dlp/Kaltura player and separately reads timed transcripts. Player failure leaves representation access unverified even when speech timing exists. Preview times use the recording's clock. For a better original, use the UN Audiovisual Library's request route and record the actual supplied file/conditions; its availability and clearance are not assumed.

Working Web TV acquisition prefers an identified video HLS representation up to 1080p with the audio track matching the canonical page's locale. Kaltura may advertise a direct 1080p MP4 with incomplete codec/geometry metadata that actually delivers audio only. The existing direct-file selection remains the fallback when the matching HLS pair is unavailable; the result must still contain video, match the requested duration and decode successfully. Record measured dimensions rather than the advertised rendition label. This preference neither grants access nor clears reuse rights.

**GDELT TV (`gdelt_tv`).** Caption search returns a broadcast/time locator with station, program, broadcast and match dates, snippet and public Archive viewing URL. It has no visual/AI search or direct media-download capability. The observed API requires a station; use an actual `station:CODE` query operator or `--catalog-filter station=CODE`. Other filters are `STARTDATETIME`, `ENDDATETIME`, `timespan`. StationDetails supplies the actual channel date range when available; unknown coverage stays unknown. A recent empty search can lie outside an archive's coverage.

```sh
python scripts/gb.py search --planned --shot opening --query "trump" --limit 1 --catalog-filter station=CNN --catalog-filter STARTDATETIME=20170829120000 --catalog-filter ENDDATETIME=20171007120000 --project PROJECT
python scripts/gb.py resolve --url ARCHIVE_ITEM_URL --archive-file ACTUAL_FILE --original-for GDELT_ID --project PROJECT
python scripts/gb.py resolve --file SUPPLIED_ORIGINAL --original-for GDELT_ID --original-conditions "Actual supplied-file conditions" --project PROJECT
```

The locator's `#start/START/end/END` viewing reference retains its source interval; this is not acquired editing media. Open the reference or separately resolve a real Archive file. Restricted/unavailable originals remain visible and cannot be inspected/fetched as available media. Linked originals retain both identities and timing provenance, then follow common preview, `search-confirm`, Storyboard, human and rights gates. Specify actual original times explicitly; the locator offset is not added again. A caption match alone does not establish visual suitability. Dated observations are in [QUALITY.md](QUALITY.md).

## Provider — Archive.org and fragment search

`archive` supports public video/image discovery and explicit item/file resolution without an API key. An item may contain several independent assets; representations of the same original are grouped while their file names, hashes, quality metadata, and access restrictions remain visible. Search thumbnails are excluded. Rights stay unknown until the separate `permit` step; an archive collection name is not permission.

An ordinary `search --provider archive --query "collection:prelinger factory" --limit 3 --media video --shot <beat.id> --project <project>` keeps the existing single-provider behavior. For resumable search, select one existing beat from the original scenario and save its catalog rationale:

```sh
python3 scripts/gb.py search-plan --shot opening --provider archive --reason "Historical factory footage" --expected-material "Factory production line" --project <project>
python3 scripts/gb.py search-plan --shot opening --provider archive --reason "Historical factory footage" --expected-material "Factory production line" --provider nasa --reason "Space and science stills" --expected-material "Dated NASA images" --project <project>
python3 scripts/gb.py search --planned --shot opening --query "collection:prelinger factory" --language en --media video --limit 3 --project <project>
python3 scripts/gb.py inspect --candidate <ID> --query "factory" --project <project>
python3 scripts/gb.py preview --candidate <ID> --start <START> --end <END> --project <project>
python3 scripts/gb.py preview --candidate <ID> --option opening --start <START> --end <END> --project <project>
python3 scripts/gb.py search-confirm --shot opening --candidate <ID> --viewed preview --preview contact-sheet --observation "Workers and machinery are visible" --match "The viewed frames show the narrated factory" --project <project>
python3 scripts/gb.py search-assess --shot opening --query "collection:prelinger factory" --assessment "Inspected returned material; need a closer production shot" --project <project>
python3 scripts/gb.py status --project <project>
```

Use the beat's actual `--intent` when it is illustrative; the default is literal. Record an assessment after inspecting results and before dispatching a different query. There are three meaningful queries per catalog, including translated queries and automatic shortening after an empty long query. Transport retries are bounded inside the same attempt. Repeating a completed query returns its saved candidate IDs and does not replenish the allowance. An interrupted dispatch remains consumed and uncertain; assess it before another formulation, leaving the catalog, opening the additional pass, or recording a shortfall. Restart and journal recovery preserve the budget. Reusing a plan, advancing a catalog, opening the additional pass, or changing narration does not reset it or erase attempts. Viewing candidates does not spend a query. A query assessment describes the attempt; it is not viewing evidence.

`search-plan` accepts one to five distinct catalogs. Repeat `--provider`, `--reason`, and `--expected-material` in the same order. One catalog is the right plan when the source is known. Two or three is the usual plan. Four or five are for a difficult search. The command does not add catalogs to fill the chain. Each catalog must be allowed for that fragment and compatible with the project media policy. A catalog whose retained route is not keyword search can still be planned. `search --planned` then reports that limitation and does not invent an API call or a browser search. Close that catalog with `search-plan --advance --provider <catalog> --because route-unimplemented --reason "<why>"`.

Close the current catalog with `--advance` after its three queries (`--because allowance-exhausted`) or earlier (`--because unavailable-access` or `unsuitable-source`). The reason is kept. A repeated advance of the same catalog, with the same reason, does not move again. Confirmed options and earlier attempts stay. The next `search --planned` uses the next catalog's own three-query allowance. Reaching three current suitable options refuses later dispatches, advances, and the additional pass. Replaying a recorded query still returns its saved result.

When every catalog in the initial chain is exhausted or skipped, its returned results and interrupted dispatches are assessed, and the target is still open, `search-plan --pass 2` may name one to five other catalogs. A catalog from the first chain is rejected. There is no third pass. The same assessment is required before `search-plan --no-further-catalog --reason "<why>"`, which records that no other suitable catalog remains. Assessment does not add a query or move the attempt to another catalog or pass. After both passes are exhausted, status shows the actual zero, one, or two suitable options and the shortfall. Empty results, access failures, and incomplete coverage stay separate. `search-assess --coverage incomplete` records incomplete date or collection coverage. None of those outcomes establishes that matching footage is absent.

An ordinary `search` without `--planned`, including `search --dry-run`, stays a single-provider command. It does not read the chain or start another pass.

Changing `--media` changes the source query and uses the same allowance. If identical wording was recorded with multiple media filters, select the attempt with `search-assess --media video|image|any`. A pending journal makes status report an unknown remaining allowance until a writing command recovers it; status itself never performs that recovery.

`search --planned --dry-run` validates the prospective query without network access or ledger changes. Ordinary `search --dry-run` retains its existing diagnostic search behavior. `status.search_progress` reports the pass, current catalog, ordered chain, rationale, original narration/target, attempts, per-catalog allowance, fragment query total, raw hits, suitable options, viewing evidence, deferred options, outcomes, shortfall, and pending human decisions. The fragment query limit is thirty meaningful queries across two five-catalog chains, not thirty HTTP requests and not a preview-byte limit. Status does this without recovery, tree creation, format synchronization, or a project lock.

`search-confirm` records that the managing agent actually viewed a generated preview (`--viewed preview`) or the acquired representation (`--viewed material`). `--viewed preview` requires `--preview gif`, `contact-sheet`, or `poster`: the generated file that was opened. The saved evidence is that file's project-relative path and hash, or the acquired file's hash for material. An arbitrary disk path is rejected, and `--preview` is omitted for material. The record also stores the representation (provider, source, original asset, selected file, and hashes when present), the interval or still, the visual observation, and why it matches the fragment. Metadata alone, or a named preview that is missing or not on disk, does not count. `--verdict unsuitable` stays in the history and does not count. Reposts, near-identical trims (overlap at least 0.8 of the combined span), and small boundary shifts (both edges within 1.0s) of the same shot count as one option. The same original is the same provider item and original asset, a shared file hash, or the same provider and source id when no file hash is available. Identical stills count once across repost ids, file names, and representations of that original; a metadata key does not split a known duplicate. Different stills that only share an item page stay separate. Different relevant scenes, angles, actions, or moments of one recording can count separately when their intervals are clearly apart (overlap below 0.35 or a gap of at least 1.0s) and the confirmation says why. Ambiguous overlaps stay separate and the distinctness claim is marked unsupported. An explicit `--duplicate-of` groups that pair; a claim that clearly different moments are the same shot stays visible as unsupported. Original identities, intervals, and hashes remain on the grouped option.

`preview --option <name>` creates or reuses one interval selection of the source you already resolved. Repeating the name edits that selection and does not add a candidate. A preview without `--option` still edits the named candidate. The selection keeps the original source and representation, including a local file hash when one exists, and does not inherit approval, rejection, verified output, or rights permission from the source candidate. `--option` cannot be combined with `--scan`. Status and the Storyboard count one raw hit for each returned, resolved, or imported source. A scene selection stays visible as a suitable option, viewing evidence, and a pending human decision, and it does not add another raw hit. Separate returned recordings, including reposts of the same shot, remain separate raw hits even when suitability groups them.

Three current suitable distinct options set the target and refuse additional search queries, including a prospective dry-run. Replaying a recorded query does not count as an additional query. Confirmation is bound to the fragment context, representation, and interval. Changing that context, representation, or interval removes the record from the current count until `search-confirm` is recorded again for the current material. Rejecting the candidate, with `reject` or a Storyboard `import-review`, does the same: a later human approval does not make the old viewing count again. Restoring the same context makes the matching record current again. A later confirmation supersedes the older one. Human approval invalidation stays independent: a format change that only bumps `segment.revision` does not drop suitability.

YouTube, Wikimedia Commons, NASA, Pexels, and Pixabay use the same bounded fragment commands and catalog chains. A still records measured width and height and keeps duration, frame rate, and the interval empty. Planned Pexels and Pixabay hits stay `stock: true` and illustrative. YouTube, Pexels, and Pixabay have no photo search, so a planned `--media image` request is refused before a query is spent. Image-only project rules likewise refuse a saved video-only catalog before a query is spent.

Visual confirmation never sets approval, rights, or fetch permission. `fetch` still requires a valid human approval signature, permit evidence, and available acquisition. A preview-confirmed option whose original needs separate access is stored and shown, and whether it counts toward the three options stays deferred. The planned chain stops at three confirmed suitable options. A raw-hit count does not stop it and does not fulfill it. The Storyboard review lists raw hits, confirmed suitable options, viewing evidence, the pass and current catalog, a shortfall when the search is finished short of three, and pending human decisions in English, keeps the original scenario narration, and still limits `--ready-only` gallery shots to prepared previews. The search block is a short summary; identities, intervals, and hashes stay in an optional details section.

For a multi-file page, select a real asset with `resolve --url https://archive.org/details/<item> --archive-file <filename> --shot <beat.id> --project <project>`; complete `https://archive.org/download/<item>/<filename>` URLs also select that file. Refresh keeps this representation rather than silently replacing it. Prefer actual high-quality files when available, respecting the download ceiling; inspect/preview decode the acquired representation and report real dimensions. Associated SRT/VTT captions are read when present; absent captions stay absent. Restricted/private files have explicit unavailable acquisition and do not become usable because their metadata can be viewed.

Prepared previews enter `review --ready-only` with their original narration. Human approval and rights evidence remain independent prerequisites for `fetch`, then `verify` and `deliver`. See [source contracts](SOURCE-CATALOGS.md#internet-archive--archiveorg) and [dated quality observations](QUALITY.md).

`providers` lists twenty retained catalogs plus local import. `implementation`, operation flags, `configured`, and `live_observation` express separate facts. A configured key or session reference is not authenticated access. Unverified adapters never advertise working discovery. The private configuration allowlist accepts DVIDS, Europeana, NARA, Mapillary, Telegram, and optional AI settings shown in `.env.example`; process values still win and unknown names are rejected. Optional Gemini/xAI keys do not select API billing. The account routes below distinguish geographic discovery, local user authorization, public-channel scope and retained OAuth access.

`live_observation` records a dated, bounded source sample: the version used, operations actually exercised, selected media and remaining limits. A decoded working window or linked institution file does not establish current access, a complete recording or editing master, exact original cut boundaries, editorial suitability, human approval or reuse permission. Read its date and limitations alongside the implemented capabilities and current access result. Later media acquisition can update an earlier metadata-only observation without enabling another transport; see [dated source evidence](QUALITY.md).

`doctor` reports installed executables and local configuration. A missing standalone Playwright CLI does not determine whether the managing agent has another authorized browser/session for capture; neither result proves live platform access. Check the actual browser and acquisition route separately.

## Providers — Mapillary, Telegram and X access

Mapillary uses `MAPILLARY_TOKEN` and a real geographic request. Supply `--catalog-filter bbox=west,south,east,north`, in degrees; split boxes that cross the dateline. Topic wording is a label for the agent and is not sent as keyword search. Missing/invalid geography is rejected before spending a planned attempt. Identical normalized geography/media/date filters replay the same attempt even if the label changes. Optional `captured_after`/`captured_before` use `YYYY-MM-DD`. Only still images are returned.

```sh
python scripts/gb.py search --planned --shot place --provider mapillary --query "Plaza Mayor Madrid" --media image --catalog-filter bbox=-3.7085,40.414,-3.7065,40.416 --limit 5 --project <project>
python scripts/gb.py resolve --url "https://www.mapillary.com/app/?pKey=<image-id>" --catalog-file thumb_original_url --shot place --project <project>
python scripts/gb.py inspect --candidate <id> --project <project>
python scripts/gb.py preview --candidate <id> --project <project>
```

Use the existing BRIEF/search-plan before `--planned`. Images preserve image/sequence and creator identity when supplied, coordinates, capture date, source page, selected representation and conditions. Signed CDN URLs are refreshed only inside private acquisition and do not enter the ledger or Storyboard. `inspect` measures the acquired still without duration, frame rate or temporal windows; it may download the complete image. Actually open its poster or original before confirming a place match. A location tag, generated preview, or neighboring street is insufficient. Equal acquired hashes group duplicate images under the existing distinctness rules. Human approval and item rights remain separate before `fetch`.

Telegram is an optional route: install `requirements-telegram.txt` in the private Python runtime. Configure `TELEGRAM_API_ID`, the 32-character hexadecimal `TELEGRAM_API_HASH`, `TELEGRAM_SESSION` and `BROLL_TELEGRAM_CHANNELS`. The whitelist accepts a JSON username array (`["public_channel","another_channel"]`) or the supplied comma-separated inline form (`public_channel,@another_channel`). It accepts at most 1000 explicit public usernames; private links, numeric chat IDs, DMs, bots and subscription enumeration are outside the route. Credentials and session files stay private. Absolute session paths must be outside the repository, including the primary checkout when running a worktree. A simple name resolves under `~/.getbrolls/sessions`; a relative path such as `sessions/broll` resolves under `~/.getbrolls`. Parent traversal is refused.

```sh
python scripts/gb.py telegram-login
python scripts/gb.py search --planned --shot event --provider telegram --query "bridge" --media video --catalog-filter channel=public_channel --catalog-filter from_date=2026-10-01 --catalog-filter to_date=2026-10-04 --limit 5 --project <project>
python scripts/gb.py search --planned --shot event --provider telegram --query "bridge" --media video --catalog-filter channel=public_channel --catalog-filter from_date=2026-10-01 --catalog-filter to_date=2026-10-04 --limit 10 --resume-history --project <project>
python scripts/gb.py resolve --url https://t.me/public_channel/123 --catalog-file document:<attachment-id> --shot event --project <project>
```

Run `telegram-login` in a local interactive terminal; it prompts privately for phone, login code and account 2FA. Enter the account's full international phone number as `+country-code` followed by the number, preferably without spaces. Typed characters stay hidden. Use the latest code for the current login request; Telegram may deliver it as a service notification to another logged-in Telegram app or through another delivery method selected by Telegram. The separate 2FA prompt takes the account's two-step verification password, not that code. Phone/code input trims surrounding whitespace; password whitespace is preserved. A rejected number, code, expired code or 2FA password produces a specific safe explanation. Exhausted code retries require running `telegram-login` again with the new request's code. Expected login errors omit the terminal traceback and project-review advice, retaining redacted diagnostics in a private project log when a project is supplied. Interrupting login disconnects without deleting the session. Never put those values on command lines or in review data. See [Telegram's authorization flow](https://core.telegram.org/api/auth) and [Telethon's login contract](https://docs.telethon.dev/en/stable/modules/client.html#telethon.client.auth.AuthMethods.start).

Search verifies a user session and that each target is the whitelisted public broadcast channel. Both UTC date filters are required, inclusive; they select message publication dates, not filming dates. `catalog.published_at` preserves that date; actual capture time stays unknown unless independently supplied. Storyboard labels legacy message dates as publication rather than capture. `channel` optionally selects one whitelist member. Each run traverses at most 100 matching messages and has a bounded connection/search timeout. Cursor, public results and fragment/query association are saved together. Repeating a query returns saved results; `--resume-history` explicitly continues the same query after restart, without another allowance. Increase `--limit` to request more attachments, up to 50. Closed fragments/catalogs and completed targets cannot resume history. Dry-run never writes history.

Print/export records use the same publication-versus-capture distinction as the Storyboard card, including legacy Telegram projects. Printed notes include publication separately; unknown capture time stays unknown. Regenerating review does not rewrite historical dates or saved human decisions.

One short FloodWait of at most three seconds can be waited out. Longer/repeated waits persist `next_eligible_at`; access is deferred for the Telegram session across other queries so another catalog can continue. Inaccessible channels and partial history remain incomplete coverage. Message ID/permalink, date, caption, selected attachment and album grouping remain distinct. A Telegram album contains individual messages: choose the exact message permalink and attachment; no first-album-item substitution occurs. Forwarded material preserves the fact of forwarding without exposing private peer details; its original source remains unverified until established separately. Text discovery, authorization, metadata, image/video viewing and actual attachment retrieval are separate facts. Selected SDK media is bounded to 512 MiB. Cached attachments still require current session/channel access and the same attachment identity before preview or fetch.

X search uses the retained Grok OIDC account from the installed client's private `~/.grok/auth.json`. It reads the current selected model from `[models].default` or the legacy top-level `model`; only the actually exercised `grok-4.7` model/tool pair is enabled. Missing, ambiguous or invalid selection/expiry and other models stay unverified. Expired access refreshes the same OIDC account through its issuer when refresh metadata exists; otherwise use the retained client's local login. A concurrent account change is preserved. The route uses the actual installed client version and documented CLI proxy headers, without a coding-agent prompt, `XAI_API_KEY`, model substitution or billing fallback. The [dated CLI evidence](archive/quality-evidence-through-2026-10-07.md#catalog-acceptance-follow-up--2026-10-05-2132-candidate) is separate from configuration presence.

Supply both `from_date` and `to_date` in `YYYY-MM-DD`. Optional `allowed_x_handles` or `excluded_x_handles` takes up to twenty comma-separated public handles; inclusion and exclusion cannot be combined. Each request permits one native `x_search` call. Planned queries share the saved catalog allowance, including automatic shorter wording; identical normalized queries replay saved outcomes. Durable completed results can resume after interruption without another inference or allowance. Both planned and explicit X dry-runs validate filters without contacting Grok or refreshing OAuth. Returned account permalinks must match tool citations and supplied filters. Search excerpts, reported dates and language remain unverified search metadata; citations alone never count as suitable material or verified quotations.

`x-access` still reads local prerequisite metadata only. It never invokes Grok or refreshes credentials, and cannot establish current tool access by itself. Original-post viewing, screenshots and attachment download remain separate from search. The managing agent may use an independently verified normal browser/downloader route and explicitly import the resulting file; automatic remote X media acquisition is not implemented.

```sh
python scripts/gb.py x-access
python scripts/gb.py search --planned --shot quotation --provider x --query Maduro --media any --limit 2 --catalog-filter allowed_x_handles=WhiteHouse --catalog-filter from_date=2026-01-03 --catalog-filter to_date=2026-01-07 --project <project>
python scripts/gb.py resolve --url https://x.com/public_author/status/<post-id> --shot quotation --project <project>
python scripts/gb.py resolve --file <actually-viewed-original-capture> --asset-type web_screenshot --source-url https://x.com/public_author/status/<post-id> --original-for <x-locator-id> --original-conditions "Observed original-post capture and its actual conditions" --project <project>
```

X URLs record original post/account identity; they do not invent post text, date, attached media or quotation verification. Original-post viewing, screenshots and media retrieval have separate capability/access results. A separately supplied local original can enter the common preview, suitability, Storyboard and rights gates through `--original-for`. Verify exact quotations against the original; translations and styled quotation cards remain separate representations. A raw URL or OAuth record does not count as a suitable option. Direct CLI inspection/download of the post still refuses the unsupported remote media route. See [dated evidence](QUALITY.md).

## Provedor — arquivo local

Importe com resolve --file. Sem upload. Verifique direitos e aprove intervalo antes do corte. Hash detecta alteração da fonte.

Diagnóstico: `python3 scripts/gb.py providers`. Falha de credencial não ativa scraping ou outra conta.

## Bancos — busca, prévia e coleta

Bancos são rota opcional, acionada **somente quando o usuário pedir stock explicitamente**; o padrão editorial continua sendo a fonte literal do que a narração cita. Pexels/Pixabay usam suas próprias chaves no ambiente ou `.env` privado da skill. YouTube não depende delas. Execute `search --provider pexels|pixabay --query coffee --limit 2 --intent illustrative --project /projeto`.

`preview --candidate ID --start 0 --end 5 --project /projeto` atualiza a URL de mídia, obtém o original em `.getbrolls-sources/` e gera GIF/contact sheet. Preserva o ID remoto, fonte e autoria; não precisa aprovar um poster antes de ver o movimento. Aprovação fica pendente. Depois de review/decisão/condições, fetch usa a fonte revisada.

Também pode obter o original pela página oficial e usar resolve --file --source-url --creator. Nesse caso o ID local é novo. API indisponível não autoriza inventar candidato ou afirmar teste bem-sucedido.

## Tipos de assets e formatos

| Tipo | Origem implementada | Prévia | Entrega final |
|---|---|---|---|
| `video` | Arquivo local; busca de vídeos nos provedores configurados | GIF ou poster/sheet; remoto pode ser só referência | MP4 do intervalo aprovado |
| `image` | PNG/JPG/JPEG/WebP/BMP/TIFF local | Imagem estática | Original estático copiado após aprovação |
| `news_screenshot` | Captura Playwright importada localmente com URL | Imagem estática | PNG/JPG original com procedência no ledger |
| `web_screenshot` | Captura de página importada localmente com URL | Imagem estática | Original estático com procedência |

Local still imports preserve measured dimensions; duration and FPS remain unknown. A one-frame ffprobe clock is not capture metadata. This also applies to institution files supplied with `--original-for`.

Busca de imagens via API, áudio isolado como asset final e SVG não estão implementados. Download social usa os transportes do ROUTER. Não anuncie a capacidade só porque existe um nome de tipo. GIF animado é a prévia de um vídeo; não substitui o arquivo final de edição.

### Formato editorial

`RULES.md` aceita `native`, `reels` (9:16) ou `horizontal` (16:9). O ledger registra dimensões nativas, destino e `fit`: matches, needs_layout_review ou unknown. Um vídeo horizontal pode ser referência para Reels, mas precisa de decisão de layout. A ferramenta não recorta rostos ou textos, não amplia baixa resolução nem converte todos os assets para quadrados.

Mudar formato nas regras atualiza o relatório e invalida aprovação anterior. Arquivos de cortes anteriores são preservados; nova revisão usa outra revisão do insert.

No storyboard, imagem/GIF mantém proporção. Captura móvel padrão é 390×844, não 9:16 exato; a composição do vídeo é uma decisão posterior. Fonte, fala, motivo, autor e data de captura acompanham o asset.

### Organização do projeto

```text
video-01/
├── RULES.md
├── output/playwright/       # screenshots e snapshots de trabalho
└── brolls/
    ├── manifest.json        # tipo, formato, contexto e procedência
    ├── references.json      # referências explícitas e seus motivos
    ├── events.jsonl
    ├── candidates/
    ├── previews/            # poster, contact sheet, GIF
    ├── clips/               # vídeo ou imagem final
    ├── credits.md
    └── review.html
```

A memória é por projeto. Para consultar referências de outro projeto, use `references --project /caminho/anterior` com autorização do usuário. Os exemplos orientam a próxima busca; nunca transferem aprovação/licença automaticamente.

## Captura de notícias e páginas pelo navegador

Workflow opcional do agente com [Playwright CLI oficial](https://github.com/microsoft/playwright-cli). Requer Node.js/npm/npx e navegador disponível. A skill não inclui navegador nem cookies. O plano usa listas de argumentos, não eval de conteúdo do usuário.

### Preparar

```sh
python3 scripts/gb.py rules --project ./video-01
python3 scripts/gb.py references --project ./video-01
python3 scripts/gb.py browser-plan --url https://www.nasa.gov/news/recently-published/ --project ./video-01
```

Windows PowerShell:

```powershell
python scripts/gb.py rules --project .\video-01
python scripts/gb.py references --project .\video-01
python scripts/gb.py browser-plan --url https://www.nasa.gov/news/recently-published/ --project .\video-01
```

Leia primeiro as regras editoriais e referências aprovadas/rejeitadas. Priorize `preferred_domains` nas pesquisas do navegador e não use `blocked_domains`. Exemplos de queries: assunto + entidade + site preferido. Confira a URL real encontrada; não invente resultados.

Defina `GB_SKILL_DIR` com a pasta instalada. Os exemplos abaixo usam a CLI local preparada conforme a seção [Instalação](#instalação). `browser-plan` também pode emitir a forma equivalente via `npx`, que obtém a CLI do npm quando necessário.

Os blocos desta seção mostram a forma macOS. No Windows PowerShell, troque `bash "$GB_SKILL_DIR/scripts/playwright.sh"` por `& "$env:GB_SKILL_DIR\scripts\playwright.ps1"`; os argumentos seguintes são os mesmos. Use caminhos do seu sistema para o projeto.

O plano devolve comandos `open`, `resize`, `snapshot` e `screenshot`, caminho único e tipo habilitado para a captura. Execute em ordem e inspecione o snapshot antes de interações. Exemplo operacional:

```sh
bash "$GB_SKILL_DIR/scripts/playwright.sh" -s=getbrolls open https://www.nasa.gov/news/recently-published/ --headed
bash "$GB_SKILL_DIR/scripts/playwright.sh" -s=getbrolls resize 390 844
bash "$GB_SKILL_DIR/scripts/playwright.sh" -s=getbrolls snapshot
# Depois de selecionar a notícia por uma referência do snapshot atual:
# ... click REF_REAL
# ... snapshot
# Use o caminho de captura fornecido por browser-plan:
bash "$GB_SKILL_DIR/scripts/playwright.sh" -s=getbrolls screenshot --filename=./video-01/output/playwright/news.png
```

Windows PowerShell:

```powershell
& "$env:GB_SKILL_DIR\scripts\playwright.ps1" -s=getbrolls open https://www.nasa.gov/news/recently-published/ --headed
& "$env:GB_SKILL_DIR\scripts\playwright.ps1" -s=getbrolls resize 390 844
& "$env:GB_SKILL_DIR\scripts\playwright.ps1" -s=getbrolls snapshot
& "$env:GB_SKILL_DIR\scripts\playwright.ps1" -s=getbrolls screenshot --filename="$env:GB_PROJECT\output\playwright\news.png"
```

`resize` muda a área visível para layout móvel. Não é emulação completa de dispositivo/touch/user-agent. Para horizontal, configure viewport desktop no RULES. Full-page é configurável, mas prints longos não cabem automaticamente num insert 9:16: selecione trecho legível, mantendo a origem. Não distorça a página para preencher o frame.

### Inspeção e importação

- Confira manchete, autor, data da notícia, URL final e carregamento de imagens. Registre data de captura separada da publicação.
- Se conteúdo estiver atrás de login/paywall, registre indisponibilidade; não tente contornar. O agente só usa acessos autorizados pelo usuário.
- Tire novo snapshot após navegar ou alterar significativamente a página. Nunca reutilize referências obsoletas.
- Confira o screenshot visualmente antes de importar. Não transforme banner de erro/cookies em asset aprovado.

```sh
python3 scripts/gb.py resolve --file ./video-01/output/playwright/news.png --asset-type news_screenshot --source-url URL_REAL --title "Manchete real" --creator "Autor informado" --captured-at "2026-09-15T12:00:00-03:00" --shot news-01 --project ./video-01
python3 scripts/gb.py preview --candidate ID --narration "Fala do roteiro" --reason "Notícia comprova o evento citado" --project ./video-01
python3 scripts/gb.py review --project ./video-01
```

No Windows, use `python` e caminhos PowerShell, por exemplo `python scripts/gb.py resolve --file "$env:GB_PROJECT\output\playwright\news.png" ... --project "$env:GB_PROJECT"`.

Substitua os metadados de exemplo pelos dados reais. Imagem estática não exige `--start/--end`. Se apenas `web_screenshot` estiver habilitado, use esse tipo. Revisão, decisão de direitos, fetch e referência seguem o fluxo normal.

Não execute `close-all` nem feche abas de outros projetos. Encerre somente a sessão criada para a captura quando terminar. Se o ambiente do agente exigir outro transporte de navegador, mantenha a mesma sequência e metadados usando suas ferramentas autorizadas.

## Instagram — navegador/Playwright, dois streams e MP4

O fluxo Instagram usa o módulo `scripts/getbrolls/instagram_pairs.py`. A captura acontece na sessão do navegador autorizada pelo usuário; o módulo consome os pares de vídeo e áudio capturados. Consulte também [recuperação e auditoria](#instagram--recuperação-e-auditoria).

### 1. Abrir o Reel e capturar as fontes

Use a URL real do Reel na sessão autorizada. **Se há Chrome logado indicado pelo usuário, reutilize esse Chrome pelo plugin do agente.** Não abra outra sessão sem necessidade. Com a extensão oficial Playwright disponível, a alternativa executável é:

Os exemplos abaixo usam macOS. No Windows PowerShell, substitua o início `bash "$GB_SKILL_DIR/scripts/playwright.sh"` por `& "$env:GB_SKILL_DIR\scripts\playwright.ps1"`, mantendo os argumentos.

```sh
bash "$GB_SKILL_DIR/scripts/playwright.sh" -s=getbrolls-instagram attach --extension=chrome
bash "$GB_SKILL_DIR/scripts/playwright.sh" -s=getbrolls-instagram tab-list
bash "$GB_SKILL_DIR/scripts/playwright.sh" -s=getbrolls-instagram tab-select INDICE_OBSERVADO
bash "$GB_SKILL_DIR/scripts/playwright.sh" -s=getbrolls-instagram goto "$REEL_URL"
bash "$GB_SKILL_DIR/scripts/playwright.sh" -s=getbrolls-instagram snapshot
```

Windows PowerShell:

```powershell
& "$env:GB_SKILL_DIR\scripts\playwright.ps1" -s=getbrolls-instagram attach --extension=chrome
& "$env:GB_SKILL_DIR\scripts\playwright.ps1" -s=getbrolls-instagram tab-list
& "$env:GB_SKILL_DIR\scripts\playwright.ps1" -s=getbrolls-instagram tab-select INDICE_OBSERVADO
& "$env:GB_SKILL_DIR\scripts\playwright.ps1" -s=getbrolls-instagram goto "$env:REEL_URL"
& "$env:GB_SKILL_DIR\scripts\playwright.ps1" -s=getbrolls-instagram snapshot
```

`INDICE_OBSERVADO` vem de `tab-list`. A extensão Playwright não é a extensão do plugin Codex; quando só esta estiver conectada, controle o Chrome por ela. Sem sessão existente, `open "$REEL_URL" --headed` cria uma sessão própria. Login necessário é realizado pelo humano nessa sessão.

#### Captura pela rede da página

1. Confira no snapshot a URL/código do Reel, perfil e legenda. Inspecione apenas esse post.
2. Registre as respostas antes de reproduzir/recarregar o Reel. No plugin com CDP: obtenha a capacidade `cdp`, leia sua documentação, envie `Network.enable`, guarde o cursor de `readEvents` e observe `Network.responseReceived` após a reprodução. No Playwright CLI instalado, os comandos são `requests` e `response-body` (não `network`).
3. Examine as respostas da página e do manifesto DASH que contêm o **mesmo código/ID do Reel**. Use a resposta/documento observado; não invente endpoints. Se o manifesto estiver em JSON, decodifique o campo de manifesto e depois seu XML. Identifique `AdaptationSet` de vídeo/áudio por `mimeType`/`contentType`, selecione suas `Representation` e `BaseURL`, preservando os parâmetros assinados. Prefira vídeo até 1080p quando disponível.
4. Se só houver requests de segmentos, relacione as representações ao mesmo Reel. No ensaio real, o parâmetro `efg` em base64 JSON identificou o mesmo `xpv_asset_id`, duração e `vencode_tag` de vídeo/áudio; isso distinguiu o Reel ativo de recomendações pré-carregadas. Compare também duração/dimensões do player e inspecione o conteúdo baixado.
5. Os URLs observados nesse formato tinham `bytestart`/`byteend`, seletores explícitos de faixa. Para obter o arquivo completo, remova **somente esses dois parâmetros de faixa**, preservando todos os demais parâmetros e assinatura exatamente como capturados. Não remova `oh`, `oe` ou parâmetros desconhecidos. Valide duração e decodificação completa; um fragmento/HTTP 206 não comprova download integral. Se a CDN rejeitar a URL completa, recapture a representação pelo manifesto; não altere assinatura nem credenciais.
6. Grave somente as duas URLs selecionadas em configs privados. Nunca exporte cookies, headers de autenticação ou todo o perfil para o pacote.

No navegador integrado, consulte as capacidades disponíveis na aba autorizada. Se houver `pageAssets`, leia sua documentação e use `list()` para obter os recursos já observados. Selecione apenas as duas representações do Reel confirmado, relacionando `efg`, duração/dimensões do player e conteúdo conforme os passos acima. Use `bundle()` com os dois IDs e o ID daquele inventário para salvar um manifesto local privado; ele pode preservar as URLs observadas mesmo quando a ferramenta não consegue baixar os bytes. Entregue somente esse par ao coletor. Inventários/manifestos e configs contêm URLs assinadas e ficam fora da fonte, logs públicos e exemplos. O ensaio de [2026-10-05](archive/quality-evidence-through-2026-10-07.md#instagram-two-stream-acquisition--2026-10-05-2131-candidate) validou essa captura e o download completo pelo coletor.

Exemplo de inspeção CLI, com saída sensível retida no projeto:

```sh
umask 077
mkdir -p "$GB_PROJECT/work/instagram-configs"
bash "$GB_SKILL_DIR/scripts/playwright.sh" -s=getbrolls-instagram requests > "$GB_PROJECT/work/instagram-configs/requests.private.txt"
# O agente inspeciona o arquivo local e escolhe o índice da resposta do Reel.
bash "$GB_SKILL_DIR/scripts/playwright.sh" -s=getbrolls-instagram --raw response-body INDICE_OBSERVADO > "$GB_PROJECT/work/instagram-configs/reel-response.private.txt"
```

Windows PowerShell cria a pasta dentro do projeto e restringe sua ACL ao usuário atual antes de gravar as respostas:

```powershell
$ConfigDir = Join-Path $env:GB_PROJECT 'work\instagram-configs'
New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
icacls $ConfigDir /inheritance:r /grant:r "${env:USERNAME}:(OI)(CI)F" | Out-Null
& "$env:GB_SKILL_DIR\scripts\playwright.ps1" -s=getbrolls-instagram requests |
  Set-Content -Encoding UTF8 (Join-Path $ConfigDir 'requests.private.txt')
& "$env:GB_SKILL_DIR\scripts\playwright.ps1" -s=getbrolls-instagram --raw response-body INDICE_OBSERVADO |
  Set-Content -Encoding UTF8 (Join-Path $ConfigDir 'reel-response.private.txt')
```

`response-body` salva corpos binários em arquivo e informa o caminho. Em resposta textual, o agente analisa JSON/XML observado e escreve os configs a seguir; não há parser de captura automática embutido. Se a ferramenta não oferece respostas/manifesto, informe essa limitação e use a integração autorizada que ofereça, sem substituir a origem por stock.

Escolha as duas representações **do mesmo Reel** pelo manifesto/identificador e conteúdo, não simplesmente os dois primeiros MP4 da página. Recomendações e pré-carregamento podem pertencer a outros vídeos. URL `blob:` é referência interna do player e não serve ao curl; use a URL HTTPS real de CDN que a página requisitou. Preserve query assinada necessária à requisição.

Salve os configs em `<projeto>/work/instagram-configs`, com permissão privada; capture URL de vídeo e URL de áudio separadamente. Este exemplo descreve o formato, não contém URLs utilizáveis:

```text
# 01_REEL_video.conf
url = "URL_HTTPS_REAL_DO_STREAM_DE_VIDEO"
# 01_REEL_audio.conf
url = "URL_HTTPS_REAL_DO_STREAM_DE_AUDIO"
```

São **dois arquivos**, com o mesmo prefixo e sufixos `_video.conf` / `_audio.conf`. O coletor lê `url` e opcionalmente `output`; aceita somente HTTPS público, sem credenciais, host local ou IP privado, resolve todos os endereços do host e fixa o curl num IP público validado. Redirecionamentos são recusados. `output` fica confinado à raiz configurada e outputs batch ficam confinados ao diretório pedido; arquivos existentes não são sobrescritos. Ele não repassa headers arbitrários ao curl. Se a fonte exigir headers/cookies além da URL, não invente suporte: registre a necessidade e use a ferramenta de navegador autorizada para obter as partes dentro do projeto, registrando `output` no config para reaproveitá-las. Não exponha cookies ou URLs assinadas nos relatórios e no Storyboard.

### 2. Baixar os dois canais, juntar e verificar

```sh
python3 "$GB_SKILL_DIR/scripts/getbrolls/instagram_pairs.py"   --video-config "$GB_PROJECT/work/instagram-configs/01_REEL_video.conf"   --audio-config "$GB_PROJECT/work/instagram-configs/01_REEL_audio.conf"   --output "$GB_PROJECT/sources/instagram/01_REEL.mp4"   --parts-dir "$GB_PROJECT/work/instagram-parts"   --project "$GB_PROJECT"   --config-output-root "$GB_PROJECT"   --summary-json "$GB_PROJECT/work/instagram-summary.json"
```

Windows PowerShell:

```powershell
python "$env:GB_SKILL_DIR\scripts\getbrolls\instagram_pairs.py" `
  --video-config "$env:GB_PROJECT\work\instagram-configs\01_REEL_video.conf" `
  --audio-config "$env:GB_PROJECT\work\instagram-configs\01_REEL_audio.conf" `
  --output "$env:GB_PROJECT\sources\instagram\01_REEL.mp4" `
  --parts-dir "$env:GB_PROJECT\work\instagram-parts" `
  --project "$env:GB_PROJECT" `
  --config-output-root "$env:GB_PROJECT" `
  --summary-json "$env:GB_PROJECT\work\instagram-summary.json"
```

O script baixa com curl, mapeia vídeo do primeiro input e áudio do segundo, normaliza H.264/yuv420p + AAC e verifica streams via ffprobe. Informe `--project` para persistir o cooldown se houver HTTP 403/429. Se a URL expirou, recapture no navegador. Um erro de acesso não significa que a plataforma é somente referência.

### 3. Batch e áudio duplicado

```sh
python3 "$GB_SKILL_DIR/scripts/getbrolls/instagram_pairs.py"   --config-dir "$GB_PROJECT/work/instagram-configs"   --output-dir "$GB_PROJECT/sources/instagram"   --parts-dir "$GB_PROJECT/work/instagram-parts"   --project "$GB_PROJECT"   --config-output-root "$GB_PROJECT"   --layout flat --fail-on-duplicate-audio   --summary-json "$GB_PROJECT/work/instagram-summary.json"
```

Windows PowerShell:

```powershell
python "$env:GB_SKILL_DIR\scripts\getbrolls\instagram_pairs.py" `
  --config-dir "$env:GB_PROJECT\work\instagram-configs" `
  --output-dir "$env:GB_PROJECT\sources\instagram" `
  --parts-dir "$env:GB_PROJECT\work\instagram-parts" `
  --project "$env:GB_PROJECT" `
  --config-output-root "$env:GB_PROJECT" `
  --layout flat --fail-on-duplicate-audio `
  --summary-json "$env:GB_PROJECT\work\instagram-summary.json"
```

Em batch, mantenha o gate de hash de áudio. Dois Reels podem ter áudio igual legitimamente; uma colisão exige conferir o par correto, não ignorar a detecção automaticamente. `--force-download` obtém novamente; `--no-prefer-config-output` evita somente o arquivo apontado no config; ainda pode reutilizar `parts-dir`. Para descartar uma parte suspeita, use `--force-download` após recapturar os URLs ou um novo diretório de partes. Preserve arquivos anteriores antes de substituir.

### Lotes e ritmo

Cem Reels de uma vez, sem pausa, são o jeito mais rápido de perder a conta. A CLI não dorme: ela diz **quanto** esperar e o agente espera. O estado fica em `<projeto>/work/queue.json` (privado, gravação atômica, permissão 0600) e nunca contém URL assinada — só a URL pública normalizada de cada post.

```sh
python3 "$GB_SKILL_DIR/scripts/gb.py" queue --action add --provider instagram --project "$GB_PROJECT" "$REEL_URL_1" "$REEL_URL_2" --url "$REEL_URL_3"
python3 "$GB_SKILL_DIR/scripts/gb.py" queue --action next --project "$GB_PROJECT"
# {"item": {...}} → capture os pares desse Reel e rode instagram_pairs.py
# {"item": null, "wait_seconds": 83, "resume_at": "..."} → aguarde 83 s e chame next de novo
python3 "$GB_SKILL_DIR/scripts/gb.py" queue --action mark --id instagram:CODIGO --done --project "$GB_PROJECT"
python3 "$GB_SKILL_DIR/scripts/gb.py" queue --action mark --id instagram:CODIGO --failed --reason "curl 22 HTTP 429" --project "$GB_PROJECT"
python3 "$GB_SKILL_DIR/scripts/gb.py" queue --action status --project "$GB_PROJECT"
```

Windows PowerShell usa os mesmos argumentos com `python "$env:GB_SKILL_DIR\scripts\gb.py"` e `$env:GB_PROJECT`.

- `add` aceita `--provider instagram|tiktok|youtube`, URLs posicionais e `--url` repetido; a URL é normalizada pelo mesmo resolvedor de `resolve` e repetidas são ignoradas. Cada item nasce `pending`.
- `next` devolve um item quando o ritmo permite ou quando já existe um item `active` aguardando `mark` — nesse segundo caso ele repete o mesmo item, sem reiniciar o relógio (`reason: "active"`). Ao devolver um item novo, marca-o `active`. Quando não há nada para devolver, responde `wait_seconds`, `resume_at` e `reason` com saída 0 e `item: null`; `reason` pode ser `pace`, `cooldown`, `max_per_hour`, `max_per_day` (aguarde) ou `empty` (fila sem pendentes, nada a esperar). `--provider` limita a fila a uma fonte.
- `mark --id ID --done|--failed|--skipped [--reason "..."]` fecha o item. Um motivo contendo `403`, `429`, `challenge`, `login` ou `rate` abre **cooldown**: 30 min, dobrando a cada disparo consecutivo (1 h, 2 h, 4 h — teto 4 h); um `--done` zera a contagem.
- `status` lista contagens (`pending`, `active`, `done`, `failed`, `skipped`), o cooldown e o próximo horário permitido por provedor. O `status` do projeto também mostra uma linha da fila e a chave `queue`, sem gravar nada.

Padrões por provedor — quando nenhuma variável nem regra é definida, o intervalo entre itens é sorteado no intervalo abaixo e contado a partir do item devolvido; os tetos contam itens `done`/`failed` na última hora e nas últimas 24 h:

| Variável | Instagram (padrão) | TikTok / YouTube (padrão) |
|---|---|---|
| `GB_PACE_MIN_S` / `GB_PACE_MAX_S` | 45 / 120 s | 15 / 40 s |
| `GB_MAX_PER_HOUR` | 20 | 20 |
| `GB_MAX_PER_DAY` | 60 | 60 |

`GB_PACE_MIN_S`, `GB_PACE_MAX_S`, `GB_MAX_PER_HOUR` e `GB_MAX_PER_DAY` são **globais**: uma vez definidas, o mesmo valor vale para todos os provedores, substituindo os padrões acima por igual. Para diferenciar o ritmo por provedor, use o bloco opcional `pacing` em RULES.md, `"pacing": {"instagram": {"min_s": 60, "max_s": 180, "max_per_hour": 15, "max_per_day": 40}, "tiktok": {...}}`; a variável de ambiente, quando definida, vence a regra do projeto.

No coletor, rode o lote com `--pace 20-60 --max-per-run 25 --continue-on-error --project "$GB_PROJECT"`: pausa aleatória entre pares (nunca antes do primeiro; `--pace 0` desliga), no máximo 25 pares por execução (o restante sai como `skipped`, motivo `max-per-run`) e falha por stem registrada sem interromper os demais. O summary JSON é reescrito após cada stem com `status` `done|failed|skipped` e o processo sai com 1 quando houver falha. O curl faz até 2 retentativas com 5 s de espera; um HTTP 403/429 encerra o lote na hora, marca o restante como `skipped` com motivo `cooldown` e, com `--project` informado e `work/queue.json` existente nele, registra o cooldown na fila — **use sempre `--project "$GB_PROJECT"` no coletor**, não `--config-output-root`, para que o cooldown vá para o projeto certo. Ao ver isso, pare: espere o `resume_at`, recapture as URLs no navegador e só então volte.

Para as rotas yt-dlp, o comando base já inclui `--sleep-requests 1 --sleep-interval 3 --max-sleep-interval 8`; `GB_YTDLP_SLEEP=req,min,max` ajusta. Nas APIs de bancos, um HTTP 429 com `Retry-After` de até 60 s é respeitado uma vez; acima disso o erro informa a espera pedida.

### 4. Entrar no fluxo comum de B-roll

```sh
python3 "$GB_SKILL_DIR/scripts/gb.py" resolve --file "$GB_PROJECT/sources/instagram/01_REEL.mp4" --source-url "$REEL_URL" --creator "$CREATOR" --shot instagram-01 --project "$GB_PROJECT"
python3 "$GB_SKILL_DIR/scripts/gb.py" preview --candidate "$LOCAL_ID" --start 0 --end 5 --reason "Trecho do Reel selecionado para revisão" --project "$GB_PROJECT"
python3 "$GB_SKILL_DIR/scripts/gb.py" review --project "$GB_PROJECT"
```

Windows PowerShell usa os mesmos argumentos com `python "$env:GB_SKILL_DIR\scripts\gb.py"`, `$env:GB_PROJECT`, `$env:REEL_URL` e `$env:CREATOR`.

For a Reel already imported through a reserved fragment browser attempt, associate the collector's merged MP4 with that record instead of dropping its discovery context:

```sh
python scripts/gb.py resolve --file MERGED_MP4 --source-url CANONICAL_REEL_URL --original-for IMPORTED_REEL_ID --original-conditions "Observed matching video/audio asset and duration; working representation only" --project PROJECT
```

The source URL must identify the same canonical Reel and the pair conditions must describe the actual capture. The local representation keeps its own measured quality/hash, the original Reel identity, public account/caption/date/language, query and fragment narration. Inspect and preview the returned local candidate. Linking records does not verify pairing automatically, grant rights or supply human approval. Existing unlinked local imports remain supported.

Use o ID local retornado e um intervalo que caiba no vídeo. Confira visualmente sincronização, identidade e conteúdo; áudio presente não comprova que é o áudio correto. O candidato fica pendente; não se autoaprove. Aprovação vem sempre de uma pessoa: pelo Storyboard (`import-review`) ou por fala explícita no chat (`approve --by NOME --channel chat --statement "frase"`, com `--statement` obrigatório no canal chat). Nunca inferir de silêncio. O download das partes para inspecionar a mídia é preparação, distinta do corte final aprovado.

### Teste de instalação

`python3 scripts/getbrolls/instagram_pairs.py --help` no macOS ou `python scripts/getbrolls/instagram_pairs.py --help` no Windows precisa funcionar a partir da pasta da skill. A suíte testa pares locais distintos, junção real, confinamento de caminhos, pinagem DNS pública e detecção de áudio duplicado. Teste local não prova captura/login/CDN ao vivo; [Qualidade e evidências](QUALITY.md) identifica separadamente essa evidência.

### Evidência ao vivo desta versão

Em 15/09/2026, a sessão Chrome indicada pelo usuário abriu o Reel `DcMXl1IPNtB`. Vídeo e áudio compartilhavam o asset `1474399414721222`; o coletor desta pasta baixou ambos por curl, mesclou e verificou MP4 de 50,226009 s, 1076×1912, H.264/yuv420p e AAC. Decodificação integral FFmpeg passou, quadro visual foi inspecionado e a CLI gerou prévia de 5 s com decisão pendente. URLs assinadas/configs ficaram somente em temporário privado, fora da skill. Essa evidência substitui a pendência anterior causada pela UI de extensão.

## Instagram — recuperação e auditoria

Baixar e organizar Reels no fluxo Get B-rolls: capturar URLs diretas de CDN como pares `*_video.conf` + `*_audio.conf`, baixar as partes separadas, mesclar com `ffmpeg` e validar que o MP4 final tem vídeo e áudio corretos.

### Quando usar

Usar quando:

- `yt-dlp` falhar no Instagram com `empty media response` mesmo com cookies.
- Existirem curl configs gerados por navegador/devtools para Reels.
- Houver suspeita de áudio duplicado/trocado em MP4 local.
- For necessário redownload organizado de Reels antes de transcrever, fazer curated/tagged ou aprender formato/motion.

### Referência operacional

O processo completo está documentado em:

[Processo de captura e download](#instagram--navegadorplaywright-dois-streams-e-mp4)

Consulte a referência antes de mudar o módulo. Os arquivos privados ficam na pasta de trabalho do projeto:

`<projeto>/work`

Não copiar signed CDN URLs para a skill. Elas expiram, podem carregar sessão/assinatura e pertencem ao material de trabalho, não ao runtime da skill.

### Script principal

Usar:

`$GB_SKILL_DIR/scripts/getbrolls/instagram_pairs.py`

Dependências:

- Python 3.11+ (`python3` no macOS; `python` no Windows)
- `curl`
- `ffmpeg`
- `ffprobe`

O script nunca imprime a URL assinada; ele só mostra o arquivo `.conf` de origem e o destino.

### Fluxo single reel

Para um par de configs:

```bash
python3 "$GB_SKILL_DIR/scripts/getbrolls/instagram_pairs.py" \
  --video-config /path/to/01_CODE_video.conf \
  --audio-config /path/to/01_CODE_audio.conf \
  --output /path/to/output/01_CODE.mp4 \
  --parts-dir /path/to/work/instagram_parts \
  --project /path/to/project \
  --config-output-root /path/to/root_that_resolves_conf_output_lines \
  --summary-json /path/to/output/01_CODE.summary.json
```

### Fluxo batch

Para uma pasta de configs:

```bash
python3 "$GB_SKILL_DIR/scripts/getbrolls/instagram_pairs.py" \
  --config-dir /path/to/curl_configs \
  --output-dir /path/to/outputs \
  --parts-dir /path/to/work/instagram_parts \
  --project /path/to/project \
  --config-output-root /path/to/root_that_resolves_conf_output_lines \
  --layout auto \
  --fail-on-duplicate-audio \
  --summary-json /path/to/outputs/instagram-download-summary.json
```

Layouts:

- `auto`: mantém subpasta de username para stems no formato `<username>_<rank>_<code>` e usa output plano para stems `<rank>_<code>`.
- `student`: força output `<output-dir>/<username>/<rank>_<code>.mp4`.
- `flat`: escreve sempre `<output-dir>/<stem>.mp4`.

### Reuso dos outputs dos configs

O config pode gravar `output = "work/..."`. Por padrão, o módulo tenta reaproveitar esse arquivo se ele já existir, resolvendo o caminho via `--config-output-root`. Se não existir, baixa pela URL assinada do `.conf`.

Usar `--force-download` quando for obrigatório redownloadar a partir da URL assinada.

Usar `--no-prefer-config-output` (para invalidar também partes já salvas, use `--force-download` ou nova parts-dir) quando o arquivo apontado por `output =` for suspeito e não deve ser reaproveitado.

### Gate anti-áudio-duplicado

Sempre use `--fail-on-duplicate-audio` em batch. Esse gate extrai o AAC dos outputs e falha se dois MP4 finais tiverem o mesmo SHA-256 de áudio, evitando que vídeos diferentes recebam por engano o mesmo stream.

Para auditoria manual:

```bash
for f in /path/to/videos/*.mp4; do
  tmp="$(mktemp -d /tmp/getbrolls-audiohash-XXXXXX)"
  ffmpeg -nostdin -v error -i "$f" -map 0:a:0 -c copy "$tmp/audio.aac"
  shasum -a 256 "$tmp/audio.aac"
  rm -rf "$tmp"
done
```

### Organização recomendada no projeto

Guardar a mídia final em uma pasta de fonte, nunca sobrescrever sem backup:

```text
<projeto>/sources/instagram/<perfil>/<rank>_<code>.mp4
<projeto>/sources/instagram/<perfil>/<rank>_<code>.summary.json
<projeto>/work/instagram_parts/<stem>_video.mp4
<projeto>/work/instagram_parts/<stem>_audio.mp4
```

Quando a mídia substituir uma versão bugada, primeiro criar backup com timestamp/slug dentro da track ou ao lado do arquivo:

```text
<arquivo>.backup-audio-bug-YYYYMMDD-HHMMSS.mp4
```

### Depois do download

Executar nesta ordem:

1. `ffprobe`/summary JSON: confirmar stream de vídeo e áudio.
2. Gate de hash: confirmar que áudios que deveriam ser distintos não duplicaram.
3. Transcrição: `etapa de transcrição configurada no projeto` ou fluxo específico do corpus.
4. Curadoria/tagging: recriar derivados a partir do transcript correto.
5. Registro: salvar summary, comandos e evidências no journal da track.

### Segurança

Não ler nem imprimir cookies, `.env`, browser credential stores ou tokens. Usar signed CDN URLs já capturadas em `.conf` como fonte operacional temporária. A solicitação de coleta autoriza a captura das URLs do post na sessão indicada. Reutilize essa autorização; peça acesso somente se faltar sessão/autorização necessária. A captura é temporária e operada pelo agente, conforme a seção [Instagram pelo navegador](#instagram--navegadorplaywright-dois-streams-e-mp4).

## Graphics

### Saved image references

Open Storyboard through the local `serve` command. On a planned scene choose **Prepare first version**; on the current preview choose **Needs changes** or **Edit references / instructions**. Describe what to adopt in **What to change**, optionally choose **References**, confirm the request and click **Save decisions**. One request accepts up to eight PNG/JPEG images or MP4/H.264 videos, with stable labels **R1**, **R2**, etc., including when filenames repeat. Explain their intended use and any video interval in the prompt. A directly opened HTML page keeps ordinary JSON review, but cannot transfer new media into the project.

The editor shows the **active references for future changes**, with earlier original instructions available on demand. A text-only follow-up retains the active files and unrelated instructions. **Remove Rn** changes the future set; **Replace Rn** preserves that label while binding the replacement's actual SHA-256, even when filenames match. Add files without replacing the others, or remove all files explicitly. Each instruction keeps its original label/hash bindings. New prose supersedes only the requirements it actually addresses in its stated scope: the managing agent records the effective resolution, retaining unrelated constraints and exceptions. There is no automatic local-over-shared or shared-over-local priority. Existing factual, narration, timing and media declarations continue through their normal workflows.

An old displayed version shows its own **frozen references and instructions** with editing disabled. Viewing it does not restore an old active set or move a draft. Select the current version to edit, or explicitly select an older saved version through `graphics-select` before restoring that context. New drafts bind the active-state SHA as well as the assignment/version and review epoch; upload, save and import refuse a stale base rather than overwriting a newer edit. The active history lives outside the frozen assignment. Unchanged saves/imports retain the original request identity. Existing approvals on other scenes are not resubmitted merely by saving this request.

Each image may be at most 16 MiB / 20 megapixels; each video at most 64 MiB, 3840×2160 (either orientation) and 120 fps; the request total is 128 MiB. Actual content, container, codec and measurements are checked, with a complete decode before admission. Video probing has a 15-second timeout and full decoding a 120-second timeout; temporal sampling uses the existing bounded media worker (180 seconds). These are finite processing limits, not a one-minute duration rule. Supported originals are copied unchanged: no silent trim, downsize or re-encode. Browser videos have native playback and range requests; a decoding failure shows an explicit preview limitation. The agent can still inspect the copied original with the local media tools.

The previews first say **selected, not saved**, then distinguish uploaded bytes from a request saved in the project. You can remove a selected file before saving; remaining labels keep their identities, including gaps, so an instruction about R3 still names the same video. A transfer/save failure retains the draft and successful transfers for retry; the request becomes saved only after every selected attachment and the review JSON have been committed. Downloading ordinary JSON is not a substitute for media transfer. A repeated identical save/import reuses the same request. The copied originals survive moving the external files. Changed/missing project bytes, changed assignments, stale versions and foreign targets are refused without retargeting.

After saving, ask the managing agent in chat to process the request. `import-review` and `status` expose its original prompt and content-bound `references`, preserving the legacy singular `reference` format. A pre-render request has `kind: authoring`, the assignment signature and no reviewed version; a revision retains its actual reviewed version. Inspect every saved file first. For each video, resolve the prompt's original source interval or explicit whole-clip request. If its meaning materially affects the result and is ambiguous, clarify it in chat; do not substitute the first seconds, a poster or a shorter interval.

Run `graphics-reference-inspect --request ID --label R2 --wording "exact original interval wording" --start 3 --end 5 --project PROJECT`, or use `--whole` for an explicitly requested whole clip. It saves a timestamped contact sheet, source hash, resolved bounds, original wording, sample cadence and limitations; `--frames` accepts 3–24 samples (default 12). Open and inspect the actual sheet and, where needed, play the original video or request closer samples. The reported times are sampling targets; frame-rate rounding applies. A sparse contact sheet does not establish fine motion between its samples or audio meaning. The deterministic record can be reused only while its evidence remains intact.

Then save a bounded analysis JSON (up to 2 MB) and use `graphics-reference-apply --request ID --file ANALYSIS_JSON --project PROJECT`. Context-aware requests (`reference_change` in status) require `effective_instructions`, the actual resolution of the original instruction history, current prompt and any scoped exceptions. Its ordered `analyses` array needs one entry per label with `label`, actual `analysis`, and explicit `limitations`; every video also needs `inspection` naming its generated project-relative `inspection.json`. For example:

```json
{"effective_instructions":"Blue accents and the inspected motion interval; preserve our facts and narration.","analyses":[
  {"label":"R1","analysis":"Adopt the inspected blue accents; retain our values.","limitations":"Still image; no motion inferred."},
  {"label":"R2","analysis":"Use the observed pacing of the selected interval.","limitations":"Twelve low-resolution samples; inspect playback for motion between samples.","inspection":"graphics-data/reference-inspections/RECORD_SHA256/inspection.json"}
]}
```

Use `{"label":"R1","reuse":true}` for an unchanged file with intact actual earlier analysis. A text-only follow-up can use `--analysis "effective instructions retaining unrelated requirements"` to reuse all such analyses. New/replaced files require actual inspection; a new requested video interval needs a new inspection. Inherited temporal evidence keeps its original request, prompt, source SHA and interval rather than being relabelled as a fresh inspection. Legacy singular images retain their original `--analysis` contract, and legacy plural requests use the earlier JSON without `effective_instructions`. Older exchange files keep their identities; an unbound legacy edit after context-aware changes must be reconciled through a freshly generated Storyboard. The analysis command saves actual host inspection without a semantic service or render. Continue authoring without a routine analysis-approval step, run `graphics-render`, then `graphics-request-complete --request ID --version VERSION --outcome "actual result" --project PROJECT`.

The new version freezes all reference bytes, original prompt, per-file analysis, resolved intervals and sample sheets independently of the rendered composition. A reference is a design example by default and does not supply factual values or grant usage rights. Existing narration, verified data, old versions and their signatures remain intact, and the new result needs its own human approval. Saving/uploading/importing or opening the page never starts semantic analysis, rendering, paid requests or delegation. Technical file checks, actual agent inspection, and human visual acceptance remain separate evidence.

For explicit inclusion (for example, “Put R2 behind our graphics”), reuse the existing local media path: `resolve --file` the saved project original, create the requested `preview`, record the actual received human selection and use conditions with `approve`/`permit`, and obtain the selected `fetch` output. Uploading a design example alone grants none of these decisions. Use the existing [background payload](#graphics) and normal source/local clock and material-use gates; the current composition-media limits still apply. The requested interval must fit the scene and the existing media path; do not silently shorten it.

Add optional `composition` to the analysis JSON with `label`, the exact original inclusion `instruction`, and the existing `background` payload. The command checks the registered candidate's original SHA-256 against that labelled copied file, validates its actual local bytes, normalizes the background through the existing permission/provenance path, and requires its source bounds to equal the inspected video interval. It binds both atomically. Subsequent rendering/completion refuses a different background binding. Design-only originals and inspection sheets stay out of editable delivery. Only permitted composition dependencies enter the source package; restricted raw composition media keep the existing separately-held reconstruction workflow. These checks do not replace viewing the actual rendered inclusion or approving the exact resulting version.

An unchanged explicitly included background remains bound to its original bytes, source clock, permission and inclusion instruction during later style/text edits. Removing a file from the future design-reference set does not silently remove independently registered composition media. If the prompt changes that inclusion, update the normal background declaration and record the actual new composition binding; `composition:null` detaches the old reference association and leaves the independently registered background declaration intact.

### Shared reference changes

Scene scope is the default. Check **Apply to other scenes as described in the prompt** only for an explicit shared request. Saving/importing leaves it unresolved and idle. After chat activation, the managing agent resolves the prompt's concrete affected occurrences and exceptions, clarifying material ambiguity in chat. It records them once with `graphics-reference-scope --request ID --file SCOPE_JSON --project PROJECT`. The bounded JSON (2 MB) contains `resolution` and unique `targets`; each target has `occurrence_id`, its complete intended `references` array (copy the actual descriptors from status, retaining unrelated files and resolving label conflicts), and the actual `instruction` for that scene. Include the source occurrence with exactly its saved effective references. Synthetic no-reference example:

```json
{"resolution":"Change labels in these two scenes; keep the second title large.","targets":[
  {"occurrence_id":"stat-01","references":[],"instruction":"Use neutral labels."},
  {"occurrence_id":"stat-02","references":[],"instruction":"Use neutral labels; preserve the larger title."}
]}
```

Resolution saves exact target versions or initial-assignment signatures, context bases, original prompt, per-target applications and deterministic requests atomically. It performs no analysis or rendering. Process targets sequentially, recording effective instructions and actual per-file analysis, then a separate descendant/version outcome for each. Reuse intact completed work and unchanged narration analysis. `status.graphics.reference_scopes` and the reference editor show `unresolved`, `incomplete`, `conflict` or `complete`, plus each concrete target and outcome. Completing the source alone cannot complete the group. Retry/import/continuation reuses this fixed list; later scenes are not added and newer versions are not substituted. A changed scope needs a new request. A target conflict stays visible while independent targets can continue. Every changed result still needs its own human approval.

### Recover interrupted reference work

Keep the browser draft after a transfer or save error and retry the same request. Successful attachment transfers are retained. A request is saved only when every selected attachment and its complete decision JSON are committed. If the connection breaks after publication, the page says the save was **not confirmed**: it may already exist. The identical retry returns the same durable submission file, ignoring only the export timestamp, even after later saves or target changes. It acknowledges that original target; it does not move the request to the current version. A conflicting or changed saved file is preserved and refused. Private staging files are neither saved requests nor served originals.

If a writer holds the project lock or a journal transaction is pending, saving refuses without recovering or overwriting it. Finish the interrupted write with the original CLI operation, then retry. CLI failures distinguish `state_committed` from `recovery_pending`: a saved transaction can be recovered once by the next write command. `status` reports the visible committed state and `graphics.reference_recovery_pending` without acquiring the writer lock, replaying the journal or creating project files. If import committed but page regeneration failed, regenerate `review`; preserve the originals, events and journal rather than resetting the project.

After chat activation, use `graphics-continue --request ID --project PROJECT` to continue one exact saved reference request, or only the concrete targets already fixed for its shared scope. Read `status.graphics.reference_work` first: `analysis_required` needs actual saved file analysis, `scope_unresolved` needs a concrete shared resolution, and `stale` needs reconciliation of its original assignment/version/context. `blocked` identifies changed/missing/unsafe originals, temporal evidence or saved output. Preserve those files and recover the known originals or create an explicit new request; continuation does not silently adopt replacement bytes or create a duplicate result to hide corruption. The reference editor also shows an attention message for blocked evidence.

`ready_to_continue` means the request's context was applied. Continuation can recover a durably verified render into the same version, or return `result_ready`/`processed` with `action: reused` for an intact matching result. It does not rerender completed targets, reset repair counts, submit/poll narration, or launch a semantic analysis service. When `completion_required` is true, record the actual matching result and outcome with `graphics-request-complete`; reuse alone does not invent an outcome or human approval. Independent shared targets can proceed while another waits, and changed evidence makes the group conflicted even if an earlier outcome recorded completion. The project retains original prompts, reference hashes, intervals, effective instructions and per-target results for a later context to reconstruct.

### Selected maps and custom authoring

Local rendering and source-package rerendering use the prepared browser for both composition selection and frame rendering. Neither step downloads a browser. If the recorded executable is missing, prepare it explicitly before retrying; a package path does not select another browser silently.

Assign `--template map` or `--template custom`, then save `graphics-content --occurrence ID --file JSON --project PROJECT`. Both use the existing facts, timing, effects, retained versions, Storyboard and delivery gates. Content fields are defined in `schemas/graphics-content.schema.json`; runtime validation additionally binds source bytes, selected geometry, label facts and narration clocks.

Every content record has integer `schema_version: 1`, `kind`, bounded `title` and `caption`, and one to six `beats` with unique `id`, `label`, `fact_id`, and increasing `at_s`. For explicit occurrence timing, `at_s` uses the original narration clock and stays inside its start/end. When VO is unavailable, assign `--timing estimated --duration SECONDS`; beat times use a draft clock from zero up to, but excluding, that duration. These renders show an estimated-draft label, retain null narration bounds and cannot be delivered even after visual approval. Supply explicit timing and rebind the beats to the narration clock for a subsequent version. Saving content does not approve it; unresolved facts and questions stop only that occurrence. Each sourced beat label must equal its saved fact definition. New content or source bytes require a new version and renewed approval; old snapshots stay intact.

For a map, save a selected WGS84 GeoJSON FeatureCollection under `graphics-data/`, with unique string feature ids. Declare its `data_ref`, actual `data_sha256`, ordered `[west,south,east,north]` `bounds` and contained `focus`, plus one `layers` entry per beat (`feature_id`, `label_point`, `geometry`, `treatment`). Embedded geometry must exactly match the selected file. Polygon rings are closed, bounded to 10000 points per layer; MultiPolygon holes are retained. Antimeridian-crossing bounds are refused. The editable equirectangular camera interpolates to the focus; it is not an area or distance measurement. Declare `geography`, `recognized`, `claim` or `illustrative` from the actual evidence. Claims receive dashed amber outlines. Hollow Point markers are illustrative, never actual facilities. Research the legal/reference-date basis before calling a border recognized; a de facto dataset does not supply that conclusion.

For custom authoring, save one locally authored, reviewed JSX entry exporting `AuthorScene`. Declare its `source_ref`, actual `source_sha256` and editable JSON `data`; the framework passes the saved scene, local beat frames and other frozen props. The entry is executable authoring code, not a sandbox: review imports and side effects, use the installed React/Remotion runtime and frozen local assets, and keep credentials and originals out of it. `references/graphics/ProcessScene.jsx` and `RelationshipScene.jsx` are editable starting examples with four-stage and three-node layouts. Copy an example explicitly into the project's `graphics-data/` before editing it. They remain custom compositions, not generalized process/network templates. Qualitative motion is labelled conceptual; record source-backed labels and arrow meaning without unsupported ratios, speeds, equipment layouts or amounts.

Attach the selected data/code as `--asset-ref` at assignment and register its content-bound `--material-use` declaration with `rendered_use`, `raw_redistribution`, `evidence` and `conditions`. This editable route requires explicit permitted finished-video use and raw code/data redistribution; an unknown or restricted raw dataset is refused rather than copied into props/source packages. Other media/effects retain their independent held-asset workflow. Preserve provenance, reference dates and terms in graphics facts. Source input changes require explicit rebinding of the actual hash and permission; continuation never adopts occupied foreign files.

### Specialist context and acceptance

Follow [Sequential graphics production](../references/graphics-workflow.md) in one managing context; subagents and host delegation are not required. `graphics-handoff --occurrence ID` can save an immutable recovery packet and a content-bound checkpoint, without launching an agent or rendering. It contains the original assignment, shared style/profile, versions, input hashes, questions and consumed repair count. Existing `--host-context` labels remain historical evidence; recover from the packet and current status without inventing a new context. `--request ID` binds an unprocessed saved revision to its exact current reviewed version; older versions must be explicitly selected first. Saved requests are processed only after chat instruction. Status and page viewing remain read-only; handoff/review CLI commands save state under the project writer lock.

The five concept types are checked with separate evidence: numeric, timeline, geographic map, custom process and custom relationships; saved versions/VO/effects and editable sources; sequential continuation; editorial decisions; full-recording live Inworld; actual Windows Resolve import, playback and placement. The accepted bounded pilot uses the supplied narration for one numeric and two timeline occurrences. Map/process/relationship outputs retain estimated timing and visual approval only. The [pilot checkpoint](GRAPHICS-PILOT-ACCEPTANCE.md) records that boundary; missing VO does not become invented audio or final delivery eligibility. Synthetic worker tests and synthetic Remotion renders establish technical behavior only. Keep private recordings and pilot evidence outside the source tree. Do not infer human approval, paid authentication, live STT, Resolve acceptance or GitHub CI from local tests.


Optional local Remotion rendering for numeric and timeline scenes. Graphics are explicit project records in `manifest.json`, never invented candidates or providers. Ordinary collection does not require Node modules under `scripts/graphics`.

Tested pins: `remotion`, `@remotion/renderer` and `@remotion/bundler` **4.0.534**; `react` and `react-dom` **19.3.0**; optional `@fontsource/ibm-plex-sans` **5.3.0** (OFL-1.1). Coordinator installs that optional tree with `npm ci --ignore-scripts --prefix scripts/graphics` after the worker is stable. Do not add `@remotion/cli` when the Node renderer API is enough.

`--scene` is the authored scene identity: different numeric concepts are different scenes, and the same scene may recur on several occurrences. `--template numeric-stat` selects the `NumericStat` composition and is independent of that scene id. Original chapter context and narration keep harmless line breaks.

To revise an existing occurrence into another composition, repeat `graphics-assign` with the same `--scene` and `--occurrence`, the new `--template` and explicit `--replace-template`. Retained versions keep their original compositions, sources, timing and decisions; rendering creates a descendant version requiring fresh approval. The pending assignment drops incompatible timeline/custom/map content and waits for the new content, preserving common facts, audio, alignment and consumed repair attempts. Without this flag, a template change is refused. Selecting an earlier version still selects that version's own frozen composition.

```powershell
python scripts/gb.py graphics-doctor
python scripts/gb.py graphics-doctor --prepare-browser
python scripts/gb.py graphics-style --project "$env:GB_PROJECT" --family documentary --note "proposed documentary draft"
python scripts/gb.py graphics-assign --project "$env:GB_PROJECT" --scene units-count --template numeric-stat --occurrence stat-01 --chapter ch-1 --chapter-context "surrounding chapter text" --purpose "show the count" --narration "original scenario line" --timing estimated --duration 3 --value 12 --unit units --label "Synthetic count" --claim-status synthetic --asset-ref clips/bound.mp4 --material-use '{"ref":"clips/bound.mp4","rendered_use":"permitted","raw_redistribution":"restricted","evidence":["license excerpt"],"conditions":"Finished-video use only"}'
python scripts/gb.py graphics-render --project "$env:GB_PROJECT" --occurrence stat-01
python scripts/gb.py review --project "$env:GB_PROJECT"
python scripts/gb.py graphics-approve --project "$env:GB_PROJECT" --occurrence stat-01 --version v1 --by NAME --statement "exact human sentence"
python scripts/gb.py graphics-select --project "$env:GB_PROJECT" --occurrence stat-01 --version v1
python scripts/gb.py graphics-request-complete --project "$env:GB_PROJECT" --request REQUEST_ID --version v2 --outcome "what the specialist did after chat instruction"
python scripts/gb.py graphics-facts --project "$env:GB_PROJECT" --occurrence stat-01 --file "brolls/facts-stat-01.json"
python scripts/gb.py graphics-fact-resolve --project "$env:GB_PROJECT" --occurrence stat-01 --conflict c-bridge --decision accept_correction --by NAME --statement "exact editorial sentence already received"
python scripts/gb.py graphics-sound-import --project "$env:GB_PROJECT" --sfx whip --asset whip-1
python scripts/gb.py graphics-audio --project "$env:GB_PROJECT" --occurrence stat-01 --file "brolls/audio-stat-01.json"
python scripts/gb.py graphics-background --project "$env:GB_PROJECT" --occurrence stat-01 --file "brolls/background-stat-01.json"
python scripts/gb.py graphics-timing-resolve --project "$env:GB_PROJECT" --occurrence stat-01 --candidate c0 --by NAME --statement "exact human sentence already received"
python scripts/gb.py graphics-timing-resolve --project "$env:GB_PROJECT" --occurrence stat-01 --start 12.0 --end 15.5 --by NAME --statement "exact human sentence already received"
```

`graphics-doctor` is read-only like `doctor`: it does not create `brolls/` or take the exclusive lock. `--prepare-browser` is the explicit step that may download the chosen local Remotion browser and records the actual executable. `graphics-render` probes that prepared runtime, refuses downloads even after a stale marker, and will not use a network font. Local clip fonts load with Remotion `staticFile` from the frozen `publicDir`; a font load failure cancels the render. Missing packages fail with the `npm ci --ignore-scripts --prefix scripts/graphics` command before any version directory is created.

A new project defaults to 1920×1080 at 30 fps. An existing project that already has collection records must pass `--confirm-fps`; fps is never inferred from footage. Estimated timing stores duration only and is marked as an estimated draft; it does not invent VO start/end. Explicit timing keeps the supplied narration seconds and stores frames with one convention: `frame = floor(t * fps + 0.5)` for `t >= 0`, error at most one frame. Remotion receives those integers.

`graphics-style` appends a proposed documentary revision (dark ink/paper, restrained accent, large tabular numerals, editorial labels, calm sequential reveals). It never overwrites the only shared style record and never marks the proposal approved. `graphics-assign` still records `synthetic` or `unverified_scenario` display values. `graphics-facts` attaches researched evidence from a bounded project JSON file (`values`, `sources`, optional `conflicts`). The primary researched value/unit and `claim_status=sourced` are applied only when evidence and conflict requirements are ready. Draft `status` and Storyboard still list `facts_not_ready` and unresolved conflict blockers for that occurrence before a complete version exists. When previously sourced evidence later becomes unresolved, displayed props return to the original assignment values (the CLI default `—` unless `--value` was supplied); narration text is not parsed for a number. `accept_correction` uses that researched number without rewriting original narration. `keep_scenario` keeps the original displayed value and shows researched figures as visible context, not proof the narration agrees. `defer`, unresolved and stale conflict decisions always block delivery for that occurrence, including when `facts.required` is false. Optional incomplete research without a contradiction cannot claim sourced and does not by itself block delivery. `graphics-fact-resolve` records an already received editorial choice; it does not invent approval. These commands do not crawl the web, launch a researcher, or treat a synthetic fixture decision as live editorial acceptance.

Numeric sourced clips display the primary value's recorded source titles as the on-screen caption; sourced timelines display their recorded source titles. Include the publication date and an appropriate source acknowledgment in those titles; keep reference periods and units explicit. Workflow status remains available in Storyboard metadata. Changing a source caption affects the next saved version and preserves the captions and original narration of earlier versions.

`--material-use` is repeatable JSON, one object per `--asset-ref`/`--evidence-ref`. `rendered_use` is finished-clip appearance (`permitted`/`restricted`/`unknown`). `raw_redistribution` is whether the original bytes may be copied into `entrega/` (`permitted` copies under `refs/`; `restricted` stays in `separately-held.json` and needs `--held-ref` at rerender). Include `evidence` and `conditions`; optional `sha256` must match the confined file; optional `candidate_id` binds a project candidate. Path presence is not permission.

`graphics-background --occurrence ID --file JSON` attaches one confined project video or photograph to the current assignment. Reuse a saved project candidate first. A missing background is an affected-scene need that names the existing search, inspect and preview route; it does not start a new provider, substitute generic footage, or claim native 1080p source quality. `--file` is the same 2 MB regular-file bound as facts/audio and must stay inside the project tree. The JSON object requires `candidate_id` and `ref` (`previews/` or `clips/` only). Optional video `source_start_s`/`source_end_s` select an original-source interval already present in that cut. `fit` is `contain` when omitted, or explicit `cover`. Optional `sha256` must match the actual confined bytes; a wrong hash fails rather than adopting changed media. Optional `suitability` is an already received `{by,statement,at}` decision. Optional `material_use` uses the same `rendered_use`/`raw_redistribution`/`evidence`/`conditions` object as `--material-use`; optional `sha256` there must equal the selected file. Missing suitability or permission remains a labelled draft. Working preview access, visual suitability, candidate human approval and permitted final use stay separate facts; composition rendering does not invent any of them.

Synthetic example only (placeholders; not an actual editorial or license approval):

```json
{
  "candidate_id": "local:SYNTHETIC-BG-VIDEO",
  "ref": "previews/synthetic-bg.mp4",
  "fit": "contain",
  "source_start_s": 3,
  "source_end_s": 5,
  "suitability": {
    "by": "NAME",
    "statement": "Synthetic fixture suitability only; preview access is not final use.",
    "at": "2026-10-11T00:00:00Z"
  },
  "material_use": {
    "rendered_use": "permitted",
    "raw_redistribution": "restricted",
    "evidence": ["Synthetic fixture rights evidence; not an actual license approval."],
    "conditions": "Finished-video use of the selected background."
  }
}
```

Omit `source_start_s`/`source_end_s` for a still photograph. The saved record stores probed `kind` (`video` or `image`), actual `width`/`height`/`bytes`/`sha256`, representation size, original provider/`source_id`/`source_url`, and clocks: `source_start_s`/`source_end_s` on the original recording, `representation_source_start_s` as the recorded start of an already-cut output, and `local_start_s`/`local_end_s` as offsets on the selected file. Do not confuse source, local-media, narration and scene clocks. Unknown mapping is `clock_state=unresolved` and blocks that occurrence. Still images keep `clock_state=not_applicable` with no fabricated interval. FullHD composition size is not proof that the source is native 1080p. Unsafe refs (lexical traversal, absolute/drive/UNC/URL, alternate streams, reserved names, symlink/junction/reparse ancestors) are refused before any copy. `status` reports saved hash, clock and permission facts read-only (`recover=False`) without mkdir, recovery or the writer lock. Opening the generated Storyboard page is read-only: it does not extract, match or transcribe, and it does not recheck those facts merely because HTML is opened. The public `review` CLI regenerates `brolls/review.html` and uses the existing write-command lock/journal.

`graphics-timing-resolve --occurrence ID` records an already received alignment correction on a saved match: either `--candidate ID` (a stable candidate such as `c0`) or both `--start S` and `--end S` as a narration-clock override, plus required `--by` and `--statement`. Do not pass a candidate and an interval together. The command does not transcribe, invent timing approval, or retarget a frozen version. Binding is occurrence, scenario, recording, result, profile and review fingerprint; a stale or imported decision that does not match those identities is refused. The same actor, statement and choice against the same fingerprints is a no-op (`idempotent: true`, `retranscribed: false`) and does not duplicate journal events. Accepted explicit timing updates the pending assignment's scene duration. Scene-local cues and full-recording VO clocks must keep their declared semantics: a same-duration shift of full-recording VO still requires `graphics-audio` when `source_start_s`/`source_end_s` no longer match the new interval, and background coverage may need `graphics-background`. If remapping cannot preserve those declarations, the result reports an affected-scene repair (`audio_duration_repair_required` and related blockers) rather than silently dropping or clamping audio, effects or background. Earlier frozen versions, journal rows and files stay intact. A later `graphics-render` creates a new immutable version for review.

Each render persists a staging version first, then copies frozen templates, original assignment, style, referenced inputs, local font bytes/terms, `package.json`, `package-lock.json`, worker bytes and the verified Node/browser identity under `brolls/graphics/<scene>/<version>/`. Referenced `previews/` and `clips/` files keep their original relative paths under `inputs/refs/`; a copy that would overwrite another frozen input fails. The verified frozen worker is the process that runs, resolving optional packages from `scripts/graphics`. Render does not download a browser or a network font. It writes H.264 yuv420p CRF 18 Full HD using frozen `colorSpace` bt709 and `imageFormat` png for limited-range conversion, concurrency 1, into staging. Silent jobs omit `job.audio` and keep zero audio streams. Every new freeze includes `GraphicsAudio.jsx` and `GraphicsBackground.jsx` in declared source hashes, including silent, VO-only and absent-background jobs, because NumericStat imports them. When a background record is present, freeze copies the exact selected bytes to version-local `public/media/<safe-file>`, verifies the hash, and stores renderer props `{kind, src: "media/<safe-file>", fit, width, height, trim_before, duration_in_frames, muted: true}`. `trim_before` and `duration_in_frames` use the composition fps and `frame = floor(t * fps + 0.5)` (`frame_rounding=half_up_nonnegative`), not source fps or global narration time. The background is always muted; no scene background audio or VO may enter the rendered clip. Occupied frozen destinations are preserved. Asset rows keep the original `ref`, `frozen_ref` (`public/media/<safe-file>`), `sha256`, `kind=background`, `candidate_id` and retained provenance/use terms. When confined effect cues exist, freeze copies them to version-local `public/audio/`, `job.audio` is `{mode:effects,codec:aac}`, and verification requires exactly one H.264 stream plus one AAC stream, Full HD, yuv420p, bt709 and `ffmpeg -xerror`. A bounded VO excerpt may be published under `previews/` for Storyboard listening; it is never copied into `sound_cues`, job props, the delivered clip, source-package audio, or rerender config. Private VO paths stay out of public HTML. Core decode uses the decoded frame count, matching `r_frame_rate`/`avg_frame_rate`, exact fps and at most one frame of duration tolerance before copying `previews/graphics-<occurrence>-<version>.mp4`. Old three-file silent versions and four-file audio versions keep their own declared hashes. Viewing the Storyboard does not download effects and does not extract alignment excerpts; `graphics-sound-import` is the explicit command that materializes a named CC0 whip/whoosh/uiSwitch asset into `sounds/`, and `narration-match` / `graphics-timing-resolve` are the write commands that may publish bounded alignment previews. Public CLI audio tests use an offline worker that muxes the frozen cue files at their start/trim/gain; that is not Remotion renderer acceptance. Freeze or publish filesystem errors stay incomplete with diagnostics and do not reuse that version identity. Orphan version directories are skipped, never reused. Previous complete versions are never overwritten. A completed version records its parent in the same occurrence, without cycles or self-parenting, and is not human approval or delivery. Storyboard keeps a saved video paired with the frozen assignment from render time, shows original anchors beside that narration, and lists declared duration/frames plus explicit start/end and frame interval when present; estimated drafts keep duration only, without invented VO times. Background cards show selected provenance, actual dimensions, source/local clocks, suitability and use conditions. Alignment cards show state, original text, candidates with textual/anchor/order evidence and bounded playback, plus a matching override preview when a manual interval was accepted. Frozen version forms stay disabled and bound to that version's alignment; the current assignment exposes exactly one separately context-bound correction form (candidate id or start/end plus the exact statement already received) even when there is no pending delta. Current unrendered assignment changes, including new questions, anchors, background and alignment, appear separately. `status` does not label a changed unrendered assignment ready; `complete_versions` counts retained complete versions.

Input paths are resolved, including parent junctions/symlinks, Windows colon/ADS forms and case-insensitive collisions; outside files stay outside. `status` validates persisted graphics fields, bool identities, full frozen assignment/style/props, hash-to-payload consistency, required hash maps, safe reference mappings, hex SHA-256 hashes and parent/current-version relationships, and returns a controlled error without rewriting history or inventing missing frozen metadata. Missing, unreadable or racing narration result/recording files, a JSON array/null where a result object is required, or a confidence-bearing artifact are affected-scene blockers or CLI `ValueError`; they do not crash status or review. Relevant complete result identity keeps the exact boolean `timing_resolved`. Candidate review, `GETBROLLS_REVIEW.items`, the session token and the `previews/` + `clips/` allowlist stay unchanged. Authoring files under `brolls/graphics/` are not served. `status` remains `recover=False`: no tree creation, exclusive lock, journal recovery, rendering or network.

`graphics-approve` records an explicit human statement for one complete version (channel always chat) bound to the ledger `project_id`. A completed render still stores `approval: null`. Estimated drafts can be reviewed and approved; `status.graphics` distinguishes complete / reviewable / approved / deliverable and still blocks delivery for estimated timing, unresolved questions, assignment drift, missing or changed declared files (including frozen `job.json` composition/profile/duration/props/encoding and both the served and frozen `preview.mp4`), missing approval, a fresh changes request on that version, a project-identity mismatch, unclassified `asset_refs`, or required facts/audio that are not ready, or an explicit unresolved/deferred/stale facts conflict even when research is optional, or a background that is missing, changed, unsafe, duration-short, clock-unresolved, unsuitable or not permitted for finished use, or an alignment that is uncertain, missing, stale, truncated, or bound to a drifted recording/result/scenario/profile/correction. A later changes import keeps the former approval as a full historical decision and blocks delivery until a new explicit human approval of that same version; the saved request is not processed automatically. Unrelated occurrences keep their own decisions. `graphics-select` points `current_version` at an existing complete version of that occurrence without rewriting frozen code, video or inputs and without inventing approval or restoring the current assignment. Saved revision requests travel in the existing `import-review` exchange as optional `graphics[]` beside candidate `items[]`; graphics-only files may use empty `items[]`. Optional `alignment[]` rows bind to `id` `alignment:<occurrence>`, `signature`/`reviewEpoch`, occurrence, analysis/recording/result fingerprints and either `candidate_id` or `start_s`/`end_s` plus the exact statement already received. Mixed rejected and valid rows skip stale, oversized or mismatched alignment entries in one recoverable transaction; they do not retarget another occurrence or fabricate timing approval. Identical actor/statement/choice replay is unchanged. A request against a retained older version keeps its original target/text/scope and is reported stale when current_version or assignment no longer match; it is not retargeted. Identical processed reimports remain no-ops. Storyboard and chat approvals append the full immutable decision (project, scene, occurrence, version, statement, content, actor, channel, time) to `review_history`. Graphics comments/statements/request text share the 8000-character bound; an oversized graphics row is skipped while valid candidate rows in the same file still import. Saving, importing, listing or viewing a comment does not launch an agent or render. `status.graphics.requests` exposes saved requests. After the editor asks in chat, `graphics-request-complete` records the actual outcome against a complete descendant of the reviewed version in the original occurrence.

The Storyboard lists every retained complete graphics version on mixed and graphics-only boards. Each card shows version, parent and current-saved status, frozen video/narration/timing/anchors/context, current delivery readiness, and saved request target/state/outcome (including stale or ambiguous older targets). Historical approval is not labelled as current delivery readiness. Viewing or comparing versions is read-only: it does not restore assignments, record approval, or change the saved `current_version` (use `graphics-select` for that). The visible timing badge follows the selected frozen version (estimated draft vs explicit narration), while comparison labels keep each version's original seconds and frame intervals. Switching the displayed version resets an unconfirmed change-request confirmation; stored per-version text drafts and confirmed decisions stay separate, so an unrelated unconfirmed draft is never recorded as a request against another version. Pending or failed assignments cannot be approved; a changed result starts unapproved. Graphics decisions are pending, approved or changes (not candidate rejected/alternative). A concrete click records the exact-version decision; an optional comment is retained as the approval statement. Playback does not record approval. A revision request needs a nonempty comment of at most 8000 characters and defaults to scene scope; shared scope is explicit. Decisions are stored separately per row id, signature and `reviewEpoch`, so a changed result does not inherit another version's browser draft. Export writes the existing `templateVersion` 2 file with candidate `items[]` unchanged plus applicable `graphics[]` and `alignment[]`, keeping `requestId` when the request text/scope/target are unchanged and clearing it when those change. Graphics-only boards omit the candidate empty-state and still expose Save decisions, including `POST /__save` and the download fallback. If the project save fails, the storage status keeps “Could not save to the project; downloaded the file instead.” while the file downloads. The saved file is a request/decision record, not an approval import or job launch. Save decisions, then ask in chat to process revision requests. `deliver` writes the independent Full HD package, `timing.json`, editable sources and package-local `rerender.py`; restricted or unknown raw effect and background bytes, including frozen `public/audio/` cue copies and frozen `public/media/` background copies, stay out of the package and are reconstructed at rerender with one `--held-ref` original into temporary cue or media destinations that reference those bytes; a later restricted declaration for a shared original keeps the strictest raw restriction, while wholly permitted raw effect bytes remain under `public/audio/` and permitted background originals remain available as editable sources. Unresolved matching, estimated timing and unsettled background rights block that occurrence's delivery. `status` remains read-only (`recover=False`) and counts a graphic delivered only while that recorded package stays intact. Resolve import/playback, human mix, live listening and live STT remain subsequent work. Complete-recording transcription is `narration-analyze` / `narration-resume`. Full-track matching is `narration-match`; explicit correction is `graphics-timing-resolve`. The proposed documentary style remains a proposal, not human approval of a scene. A successful synthetic facts/audio/background/alignment render is not editorial, rights, mix, matching-quality or Resolve acceptance.

The default graphics card shows a readable scene title, the preview, paired VO when available, the full original scene passage and Approve / Needs changes actions. Every card keeps Version / Compare with controls; a comparison with no alternative version is disabled, while pending previews keep a disabled Version placeholder. A `Без озвучки` (no VO) badge beside the title follows the displayed version's actual paired audio preview, independently of its timing basis or sound effects. Estimated timing remains available in Details. Open the single `Details` panel for the selected/compared versions' context, sources, sound declarations, technical metadata, readiness and saved requests, or the current assignment's context-bound timing correction form. An optional comment can also be opened there; Needs changes opens a full-width comment field below its label and requires confirmation. Pending-decision boilerplate, repeated workflow instructions and internal scene/template identifiers are absent from the main card. Complete transcription records remain in their own closed section. These disclosures change presentation only: full text, exact-version decisions and retained media remain intact. Printing temporarily expands the details, includes every retained version and restores their previous open/closed state afterwards.

Passages longer than 240 characters show a short preview with `Читать целиком` (read in full); opening it reveals the complete unchanged passage. `Свернуть` (collapse) returns to the preview. This is a display choice and does not alter the saved assignment or its duration. Printing includes the full passage and restores the prior expanded/collapsed state afterwards.

Version numbers shown in a graphics card are local to that continuous occurrence: its first complete saved preview is `v1`, its next is `v2`, independently of other pieces or recurring uses of the same scene. Version / Compare with, preview captions, parent labels and comparison/request descriptions use this same numbering. Failed render attempts do not consume a displayed saved-version number; retained complete previews follow numeric creation order even after the project reaches ten renders. `Saved ID` in Details and the CLI/exported decisions keep the original project-wide identity. Renumbering the display does not rename files, change frozen inputs, reset approvals or retarget saved requests.

The summary counts each graphics piece once, using its current complete saved version (or the first retained complete version when none is current). Historical approvals and pending decisions remain available in Version / Compare with and exported decisions without affecting the current queue. Graphics shows one piece at a time: use Piece, the previous/next arrows and the position counter to navigate without changing the page address. Leaving a piece pauses its video, VO and alignment auditions, while retaining its selected versions, comments and decisions. Next pending advances through pending candidate clips and graphics pieces, selects the piece's current saved preview and displays its card. It skips reviewed items, wraps after the last item and is disabled when the queue is empty. Print/PDF and Save decisions include every piece and retained version; without JavaScript all cards remain accessible.

Review generation may use local FFmpeg to cache a representative poster from each unchanged saved graphics video. Before Play, the poster shows the animation's contents instead of its potentially empty first frame. Playback still starts from the original beginning with the same paired VO. Posters are derived preview images keyed by the video's actual hash, outside its frozen inputs; they do not change its approval or version. Existing posters are reused; missing or changed videos do not reuse stale images. If the optional decoder is unavailable, the native video controls remain usable. Opening the page does not run FFmpeg or alter the project.

### Continue saved graphics

`graphics-continue --project <PROJECT> [--occurrence <ID> | --request <ID>]` explicitly inspects assignments one at a time under the existing writer lock. `--request` selects the exact saved reference request or its fixed shared targets as described in [reference recovery](#recover-interrupted-reference-work). Without it, existing assignment continuation remains available. It reuses a complete version only after checking frozen artifacts, current assignment/timing/context/style, data bytes, template sources, worker and runtime/profile dependencies. It never submits or polls narration analysis. Unchanged transcript analysis stays saved; known pending or unknown paid outcomes still use the separate narration commands and never trigger blind resubmission.

A verified render interrupted during publication can finish the same version without executing the worker again. An interruption before a durable verified result retains the partial files and reports `repair_required`; it does not call them complete. A foreign publication destination or changed snapshot is preserved and reported. Local changes create a new version only for their dependent occurrence. `graphics-style` appends a shared revision and updates pending assignments to it; old versions and approvals remain historical. A changed version always needs fresh human approval.

Save partial work with `graphics-checkpoint --occurrence <ID> --stage research|authoring|waiting|error --outcome "<actual outcome>" --ref graphics-data/<file> --project <PROJECT>`. Research/authoring needs actual saved files; their hashes and assignment context appear in `status.graphics.items[].work`. A checkpoint preserves work and evidence, rather than executing an arbitrary source file or proving a finished render. Waiting/error checkpoints and unresolved questions pause only that occurrence. Resume after explicitly updating the assignment or saving the next work stage.

After fixing a technical scene-code error, `graphics-render --occurrence <ID> --repair --project <PROJECT>` reserves a repair before execution. The existing manual `graphics-render` retry also consumes this allowance when the last render failed for the same assignment. At most two attempts are retained for the occurrence; continuation and reassignment do not reset them. The narrative assignment must stay unchanged for an explicit repair. There are no automatic code repairs or revision-request processing in continuation. A processed request retains its exact identity/outcome and remains a no-op on reimport. `status` and viewing saved review pages do not render, recover or acquire the writer lock. Write commands may append normal CLI diagnostics even when a result is reused.

### Dated timeline occurrences

Each occurrence has one to six milestones and a title of at most 90 characters. To keep context legible at Full HD, date/label limits are 60/120 characters for one or two milestones, 30/80 for three, 20/80 for four, and 20/50 for five or six. Longer text is refused before saving; shorten a label or use separate occurrences rather than hiding overflow.

Assign `--template timeline` with the same `graphics-assign` context/timing flags, then attach `graphics-timeline --occurrence <ID> --file <PROJECT>/brolls/graphics-data/timeline.json --project <PROJECT>`. The bounded file follows [graphics-timeline.schema.json](../schemas/graphics-timeline.schema.json):

```json
{
  "schema_version": 1,
  "title": "Synthetic chronology",
  "milestones": [
    {"id": "early", "date": "1900", "label": "First synthetic event", "fact_id": "early", "at_s": 10.4},
    {"id": "later", "date": "1950", "label": "Later synthetic event", "fact_id": "later", "at_s": null}
  ]
}
```

For an occurrence at narration 10–12 seconds, `at_s: 10.4` emphasizes its milestone at local frame 12 at 30 fps. These are narration-clock instants, not event durations. Context milestones use null; display spacing is illustrative and claims no proportional duration. One to six editable milestones keep labels legible. Preserve authored milestone order; timed emphasis must be distinct, ordered and inside this occurrence. Estimated drafts keep null instants and their visible estimated label. Retiming outside existing emphasis bounds requires an explicit new timeline file.

Non-synthetic dates and labels require existing `graphics-facts` evidence: each `fact_id` points to a saved value whose `value` is the displayed date and `definition` is the displayed label. Source references, reference dates, saved data hashes and permissions use the normal facts contract. Missing, changed or conflicting evidence pauses only that scene; original narration is retained after a correction. Synthetic test dates are visibly synthetic and are not research evidence. Storyboard labels a milestone with no `at_s` as context only (no narrated emphasis); timed milestones retain their actual narration seconds, including zero.

A recurring motif at distant narration passages receives distinct occurrence ids and independent versions/timing, even when `--scene` and milestone context are shared. Render, compare, request corrections, approve and deliver through the existing workflow. Timeline packages retain the exact template sources, editable milestone props, data/evidence, permitted media/effects and original placement times. Effects stay inside the Full HD clip and VO stays separate. Real pilot appearance, timing quality, listening and Resolve placement remain human acceptance gates.

## Narration analysis

Complete local voice-over transcription through Inworld's documented asynchronous STT route. This slice saves original recognized text and word timestamps. Analysis does not match scenes, invent confidence scores, or treat a fixture transcript as live acceptance. Passage matching is the separate write command `narration-match`.

Use the already formatted `INWORLD_API_KEY` environment value as HTTP Basic. Do not base64-encode it again. Collection search does not use this key. Only `narration-analyze` and `narration-resume` contact the provider. `status`, `review`, `serve`, saving a comment and `import-review` never submit, poll, download, match or extract.

```powershell
python scripts/gb.py narration-analyze --project "$env:GB_PROJECT" --recording "C:\path\to\complete-vo.wav"
python scripts/gb.py narration-analyze --project "$env:GB_PROJECT" --recording "C:\path\to\complete-vo.wav" --language pt-BR
python scripts/gb.py narration-resume --project "$env:GB_PROJECT" --analysis na-1
python scripts/gb.py narration-match --project "$env:GB_PROJECT" --analysis na-1
python scripts/gb.py narration-match --project "$env:GB_PROJECT" --analysis na-1 --occurrence stat-01 --occurrence stat-02
python scripts/gb.py status --project "$env:GB_PROJECT"
python scripts/gb.py review --project "$env:GB_PROJECT"
```

`--recording` is a complete local headered audio file. This slice validates WAV headered PCM identity (`RIFF`/`WAVE`), RIFF chunk bounds and the actual complete PCM data payload before any provider call; header-only or truncated audio is refused. Duration comes from the validated payload. Other encodings are refused. Bounds: nonempty, at most 512 MB, `audioEncoding=AUTO_DETECT`. `--language` is an optional hint. `--analysis` is a saved identity (`na-N` when omitted). After a known failed job, a separate explicitly authorized attempt of the same recording and settings needs a new `--analysis`; completed history is not overwritten. A pending or unknown attempt blocks resubmission of the same recording/settings even under a new analysis name. Preserve it and use its saved operation for recovery when available. `narration-match --analysis` is a completed analysis identity from `narration-analyze`; matching does not assign `na-N`, transcribe, or contact the provider.

The command validates the recording, private snapshot and credential/config, then durably records submit intent before `POST https://api.inworld.ai/stt/v1/transcribe:async`. Multipart sends `transcribeConfig` JSON first (`modelId=inworld/inworld-stt-1`, `includeWordTimestamps=true`), then streams the file with its exact multipart `Content-Length`, without chunked transfer encoding. There is no public upload and no whole-file base64 body. A returned operation name is saved immediately. `narration-resume` polls `GET https://api.inworld.ai/lro/v1alpha/{operation-name}` and downloads the signed transcript without Authorization.

`status.narration` reports recording identity (hash, duration, codec), analysis state, original text, word-timing summary and controlled errors. Storyboard shows the same public fields. Credentials, signed result URLs and private audio/receipt paths stay out of review JSON, logs, diagnostics and examples.

**Reuse and errors.** Unchanged recording bytes and provider settings reuse an intact completed analysis without a provider call and without requiring `INWORLD_API_KEY` merely to read local results. A changed recording or `--language` starts a separate analysis and keeps the old result. Pending, unknown, failed or completed attempts are not silently resubmitted. Timeout, disconnect or an invalid operation handle after intent is `unknown`; resume never POSTs. Known rejection is `failed`. Missing, expired or corrupt results stay unresolved and do not start a new paid job. When a completed analysis has a known operation and its local result file is absent, resume may restore that file through the saved operation; an existing corrupt file is preserved and reported as `ARTIFACT_CORRUPT`. Omitted zero-valued word times mean 0; bool, nonfinite, negative, reversed, out-of-recording bounds or globally backwards start/end times leave timing unresolved while keeping recognized text. Provider language and usage metadata accept only bounded safe scalar fields; nested objects, signed URLs and authorization material are omitted. Confidence is ignored. There is no exactly-once billing promise.

**Matching.** `narration-match --analysis ID` matches assigned original scenario passages to a completed full-track saved result `{transcript, words:[{word,start_ms,end_ms,segment}], artifact_sha256, timing_resolved}`. It does not call the provider, rewrite frozen versions, or copy a confidence field. Repeat `--occurrence ID` in the explicit narrative order to match, including a subset. That listed order is the matching-group context and is not replaced by dictionary insertion order. Omit `--occurrence` only when every assigned occurrence should match in stored order. Rematching or reordering an affected group invalidates obsolete group context without STT. Original scenario and recognized text are preserved; matching uses normalized copies, including Cyrillic punctuation and case, with neighboring anchors and sequence evidence.

States are `resolved`, `uncertain`, `missing` and `stale`. Repeated, omitted, reordered and competing passages stay visible as candidates or uncertainty rather than first-hit selection or a squeeze into chronological order. Only a uniquely supported, high-quality, order-consistent match may auto-resolve under the documented conservative domain rule. Candidates keep stable `c0`, `c1`, … ids, exact source `start_s`/`end_s`, original recognized text, word index bounds, textual/anchor/order evidence and a local matching `score` in [0, 1]. That score is not Inworld confidence. `transcript_sha256` is the complete recognized-result identity (original transcript, each word's original text/`start_ms`/`end_ms`/`segment`, `artifact_sha256`, and the exact boolean `timing_resolved`), kept separate from `scenario_sha256`. Scenario edits, occurrence-order changes or timing overrides rematch without retranscribing unchanged audio. A changed recording or result invalidates only its dependents. Malformed result JSON (array or null where an object is required), missing/unreadable/racing artifacts, or a confidence-bearing payload are actionable blockers or CLI `ValueError`.

Frame conversion uses one convention: `frame = floor(t * fps + 0.5)` for `t >= 0`, `duration_in_frames = max(1, end_frame - start_frame)`, original seconds retained, `frame_rounding=half_up_nonnegative`, error at most one frame. Explicit and estimated bases stay distinct; unresolved matching is not scene timing and blocks that occurrence's delivery.

Bounded candidate VO excerpts, and the matching override excerpt for an accepted manual interval, may be published under `previews/alignment-<occurrence>-<identity>.wav` only during `narration-match` or `graphics-timing-resolve`. Same-context reuse verifies the confined file, hash and bounded duration. Extraction, missing or occupied failures stay explicit; old bytes are preserved and are not served as a current candidate. Frozen evidence does not borrow current audio. The original recording is never served. `status` and Storyboard viewing never extract.

Storyboard offers play/seek of those bounded candidate and override previews with the existing mute/version/end/mobile/print protections. They are exclusive auditions of their own source intervals, which can differ from the rendered version: they pause competing media and are not synchronized to that version's effects video. Frozen version forms stay disabled and context-bound. The current assignment exposes exactly one separately context-bound correction form even when there is no pending delta. `graphics-timing-resolve` and `import-review` `alignment[]` record the human correction with the recording/scenario revision; stale fingerprints do not retarget. Public metadata never includes private paths, credentials or signed URLs. Examples in this guide are labelled synthetic placeholders. Live paid Inworld, actual VO matching quality on the pilot, Remotion renderer, Resolve and human editorial approval remain separate gates.

**Offline vs live.** Public CLI tests use a synthetic WAV and an explicit loopback HTTP fixture (`GETBROLLS_INWORLD_STT_TEST_MODE=1` with `GETBROLLS_INWORLD_STT_TEST_BASE` as a loopback origin). Those variables are not `GB_*` keys and are not loaded from `.env`. Test mode without a loopback origin fails closed; `TEST_BASE` is ignored unless test mode is exactly `1`, so production credentials cannot be silently routed to an arbitrary host. Fixture success is not live Inworld quality, not actual VO alignment, and not ticket-58 acceptance. A real `INWORLD_API_KEY` and the actual complete narration remain a separate human/live gate. Mock worker and synthetic matching proof is offline only; it is not paid transcription, fictional actual approval, or Resolve acceptance.

Private audio lives under `brolls/narration/private/audio/` and is denied by the review server allowlist (`previews/` and `clips/` only). Result artifacts are project-relative under `brolls/narration/results/`.

Storage paths are checked against the resolved project root and refuse symlinks or junctions. Before a new attempt writes a snapshot or submits audio, it checks the planned snapshot, result, receipt and temporary siblings. Occupied result/receipt or temporary files are preserved and block the attempt before any provider request. An identical existing snapshot can be reused. Existing invalid narration history is reported without replacing it.

## AI stills

One Storyboard can contain both AI stills and Remotion graphics. Their reference contexts and decisions keep their exact media/version targets when saved or imported together. Retrying an unconfirmed save or explicit AI launch keeps the original request identity; after a server restart, reopen the page for the current session. The earlier versions and pending requests remain available. Incomplete or ambiguously framed transfers are refused before applying an AI action or publishing a review submission.

The managing agent records original-scenario routing with `ai-plan --file JSON --project PROJECT`. Beat text must occur in the original scenario. Each AI beat needs a visual purpose and exactly three distinct textual scene alternatives. Economy mode is the default: descriptions first, then one still after an explicit launch. Images mode does not generate by itself. Changing comparison mode, choosing a description, typing, or saving does not call a provider and does not lower quality or switch billing. GPT subscription video is not available. Grok uses a bounded OAuth Imagine transport with the installed client's retained xAI account, independently of the selected reasoning model. Actual account media access must be established by a separately authorized generation; login metadata alone is insufficient.

To use Grok from the ordinary Storyboard buttons, record `"still_provider": {"route": "grok-subscription", "model": "grok-imagine-image-quality"}` in the plan. Omitting this setup preserves GPT as the default. An explicit agent launch can instead use `ai-generate-still --beat ID --request-id NONCE --route grok-subscription --model grok-imagine-image-quality --project PROJECT`. The frozen image request records the profile aspect ratio and native `1k` output request; actual retained dimensions remain the evidence of output quality. Video setup is `"native_video": {"model": "grok-imagine-video-1.5", "tool": "reference_to_video"}`. The alternative `image_to_video` tool restricts duration to six or ten seconds. Unsupported model/tool/profile combinations fail without substitution. The adapter sends one fixed-endpoint media POST, never a reasoning-agent loop, and does not use environment, per-model or cached static API keys. No endpoint override or API billing fallback is available.

`ai-select` stores the chosen alternative, an optional comment and the comparison mode. Opening the Storyboard, typing a comment or selecting a description does not call a provider. Unfinished choices on other beats do not block a selected beat.

`ai-generate-still --beat ID --request-id NONCE --project PROJECT` freezes the selected scene, comment and agreed style, then starts one native ChatGPT subscription still through `codex app-server` JSON-RPC (`initialize`, `account/read`, `modelProvider/capabilities/read`, `thread/start`, `turn/start`). Completion requires a local `imageGeneration` item with `savedPath` and a decodable project copy plus original hash. A text answer, process exit or remote handle is not a still. Missing ChatGPT login, `imageGeneration: false` or `usageLimitExceeded` stay visible and never fall back to OpenRouter or API keys. A repeated identical `--request-id` reuses the saved job; changed inputs cannot reuse it. An unknown submit is recorded and `ai-resume` does not send it again.

Native image notifications can include duplicate inline base64 as well as the saved file. The transport admits up to 32 MiB of image bytes, drops that duplicate before queuing, and retains the 1 MiB control-message bound. Originals saved by Codex are accepted only from the exact recorded thread/item PNG location under its home directory, copied into the private job directory and validated without moving or overwriting the native original.

For an unknown native still with a retained thread identity, **Recover saved result; no new generation** or `ai-resume --job JOB_ID --project PROJECT` reads that existing thread with `thread/read`. It starts no thread, inference turn or image-tool call. Recovery requires an exact prompt/turn match and one completed image; absent or ambiguous history stays unknown. Reference and Apply jobs also require the recorded production-phase prompt binding, so an inspection result cannot become a production still. Once a local original and hash are recorded, recovery validates those bytes; a damaged original is refused. Storyboard watches status for a bounded interval after an explicit recovery and displays a completed handoff without another generation request.

`ai-generate-comparison --beat ID --request-id NONCE --project PROJECT` is the explicit three-output launch. The beat must already be in images mode. The command freezes three still jobs on the project's recorded subscription route (GPT by default), one per saved treatment, with the same agreed style and quality. A repeated identical `--request-id` returns the same three jobs. Changed scene, comment, style, provider setup or treatments cannot reuse that identity. Each still completes, fails, or stays unknown on its own; a sibling is not replayed to fill a gap. Switching mode keeps completed stills.

Background AI workers wait up to ten seconds for brief competing project writes before claiming a job or saving provider progress/results. This wait repeats only local lock acquisition, never the provider request. Normal CLI writes still report a busy project immediately; a job remains exclusive to one worker. If an interrupted launch left an intact job `queued` with `not_sent`, explicit recovery dispatches that same unsent job rather than creating another comparison.

After returning to economy mode, retained comparison slots remain available and a later single still can offer **Show the new still**. Opening that offer changes the displayed review target only; the old exact-version decision remains saved and the new still awaits its own decision.

`ai-timing --beat ID --analysis ID --project PROJECT` matches that beat to one completed narration analysis. It does not transcribe, call a narration provider, or create a generation job. A unique recorded interval can resolve; repeated or ambiguous speech stays unresolved until an explicit candidate or bounded correction. Ambiguous candidates show the safe recognized passage and its actual start and end, not only an internal id. `ai-timing-resolve` records one explicit candidate or one bounded start/end correction, with the reviewer and the statement. It does not choose the first candidate. Preparation before a recording exists leaves the stills untouched. A bounded preview, when the interval is resolved and the excerpt checks out, is a short file under `previews/ai-vo-`. Reuse requires the same recording, interval, and profile, a confined regular file, the frozen hash, and a decoded duration within one frame of that interval. Occupied, corrupt, altered, linked, or junction paths stay in place and return an explicit error; they are not served as the preview. `status` and Storyboard viewing recheck that identity and do not extract, repair, or replace audio. The private recording under `narration/private/audio/` stays off static responses and status metadata.

`ai-generate-video --beat ID --version ID --request-id NONCE --model NAME --project PROJECT` is the explicit agent launch. It freezes one exact approved still, the current resolved interval, motion, sound flags, and the native `grok-subscription` route, model, and tool before any work. The Storyboard does not ask the editor to type a model or choose an internal tool for every clip. It uses the model and tool recorded in the project plan as `native_video`, or the model and tool already frozen by an explicit command. Details shows that provenance. When no setup is recorded, Generate video does not post and explains that the native route is unverified; it does not guess a model, switch to a paid API, or create a new starting still. Omitted speech, music, atmosphere, and effects mean those are not requested; atmosphere and effects stay separate from the project narration. The requested picture is 480p or 720p, which is not native Full HD. A short clip does not claim to cover the whole interval. The same request identity reuses the saved job; a changed still, interval, model, tool, resolution, or sound flag cannot. Unknown submit is not sent again. Still review and video review are different decisions: approving the still does not approve the clip, and reviewing the clip does not change the still. A video note and decision belong to that clip's id and signature. Polling and switching clips keep the exact target and any unsent note. The public synthetic workflow can freeze and review that request. The Grok adapter submits the exact first-frame data URL through the retained xAI OAuth account, records the remote video identity before polling, and validates the saved MP4 before publishing a pending-review version. A known request can be retrieved with ai-resume or the authenticated resume action; retrieval never creates another generation. Lost image responses and unknown video submissions are not resubmitted. Authentication, quota and invalid media errors remain attached to the same job. Embedded cover art is distinct from the single moving-video stream.

`ai-approve` and the Storyboard review buttons bind the decision to the exact displayed still (bytes and signature). Selecting a description, a comparison slot, or a successful generation does not approve the image, delete the other stills, or start video. Generated stills are identified as generated, not documentary evidence. The Storyboard shows all three slots, with each image path and per-slot progress or error, without reloading or replacing the unsent comment. Review this still pins that exact image; Show the new still remains the explicit switch for a newer economy result. Generate video and the video decision buttons are separate from those still controls. The video note is a different field from the still comment. Paired narration preview and the retained clip stay paused until the editor plays one of them; starting one pauses the other. Print keeps the timing line, recognized bounds, and the unverified-setup sentence, and hides the players, launch controls, and comment editors. Narrow screens stack those controls.

The authenticated local Storyboard posts `/__ai` for select/generate/review and polls `/__ai/state` without reload, keeping the selected beat and unsent comment. Images mode posts `outputs: 3` only from Generate three stills. A paid OpenRouter route is refused by this HTTP launch; a future paid three-still set still has to be confirmed as a whole before any member can run. Live actions are disabled on a portable HTML file. `status.ai` is read-only: no recovery, tree creation or exclusive lock. Diagnostics stay in the card's Details panel. Full private narration audio stays off ordinary static and status responses.

Use **Instruction → Apply** to revise the exact displayed still. Describe the requested correction, refinement or replacement in ordinary language; no edit/regenerate selector is needed. The earlier result and its original inputs remain available, and the new still starts without approval. Uploading a reference or changing its context never starts generation. **Keep reference** saves guidance before the first generation; **Apply** can save a selected file and launch the requested revision in one action. Generate refuses an unsent selected attachment instead of silently omitting it. A portable page cannot transfer files or launch work; after reopening, reselect any file still marked as unsent.

Optional PNG/JPEG images (up to 16 MiB) and MP4/H.264 video (up to 64 MiB) are copied into the private project with the original name, SHA-256 and measured metadata. Describe the reference's purpose in Instruction. Reference options can override its role or give exact video bounds. A single explicit interval in the instruction, such as `3–5 seconds`, `00:03–00:05`, or `с 3 до 5 секунд`, also supplies those bounds. Missing, ambiguous, out-of-range or undecodable intervals are refused; the opening is never substituted. The byte limit is a processing limit, not a product duration rule. The saved video, interval frames, contact sheet, times and hashes remain tied to that source. Native GPT inspection receives actual derived images, and its observations must match the attached bytes, roles and order before production can use them. Analysis cannot generate an image. Grok image_edit receives the actual frozen target and reference images, including selected video-interval frames; raw video input is not implied. A bounded spatial/format derivative fits the native 400 KiB reference limit, preserving the original and recording both hashes. Direct reference transfer does not mark a reference inspected or fabricate observations. Analysis-only Grok inspection is refused without generation. OpenRouter reference production remains unavailable.

Active guidance persists across text-only revisions until explicitly replaced or removed. Remove acts on the reference shown: beat guidance is canceled at the beat, while an inherited still reference is canceled only for the displayed retained result. Its ancestor and frozen job inputs remain intact. Late upload/preview results cannot erase a newer selected file or change the still captured when Apply was clicked. Changed visible contexts are refused on replace/remove. Private previews require the current server-session token and intact hashes; ordinary file URLs cannot expose the original reference store.

References default to **This beat**. Choose **Shared style** only when explicitly requesting project-wide AI guidance; its scope instruction is retained, and future explicit image launches on other AI beats also use that reference. The original owner, media, still binding and frozen history stay intact. Shared-reference notes appear on the other AI cards; manage the attachment in its original scene. Uploading does not regenerate other scenes or approve any media. Removing the shared source removes it from later launches while retaining earlier job inputs.

Public tests use a synthetic native-transport fixture and synthetic PNG/JPEG/MP4. That is not live ChatGPT entitlement, image quality or Resolve acceptance. Do not run `codex login`/`logout` or paid image jobs from this workflow until a separately authorized pilot.

### Explicit native GPT session model

For native GPT stills, an optional explicit session model can be recorded in the AI plan as `"still_provider": {"route": "gpt-subscription", "session_model": "MODEL_FROM_YOUR_NATIVE_CATALOG"}`. This selects the Codex model that operates the native image tool; it does not name or replace the image model behind that tool. Read the installed client's `model/list` for a candidate and verify actual access with a separately authorized generation. A catalog entry or `imageGeneration=true` is not proof of account entitlement. If omitted, the existing CLI session default remains in use.

The selection is frozen into economy, comparison and Apply requests, shown in Storyboard and retained in delivery provenance. Inspection and production use the same frozen choice. The adapter passes it only to `thread/start`, leaves global CLI configuration untouched, disables provider/model fallback and refuses a changed returned session model before starting a turn. Changing the project setting does not change saved jobs; a replay with changed frozen scope is refused. A rejected or unsupported model does not select another model or start another generation. Keep exact launch authorization and the saved failure when preparing a new model choice.

Storyboard includes the selected subscription route, image-model setting and explicit session-model setting in the identity of economy, comparison and Apply launches. After a setup change, reopen the regenerated review before making a new explicitly authorized launch. Unchanged setup preserves the identity across reopening and duplicate clicks; changing setup never starts work by itself or resubmits a saved job.

### Explicit paid OpenRouter launches

OpenRouter is a separate paid choice. Keep `OPENROUTER_API_KEY` in the private environment or `.env`, never in an AI plan. For a separate private file, pass `--env-file /path/to/private.env` before the command; an already exported value takes precedence. Loading a key does not authorize generation or change a subscription route. Add explicit model profiles to that plan before running `ai-plan`; for example:

```json
"openrouter": {
  "image": {"model": "bytedance-seed/seedream-4.5", "resolution": "2K"},
  "video": {"model": "google/veo-3.1", "resolution": "1080p", "duration": 6}
}
```

These are example model choices, not access or quality guarantees. Preparation checks current public model/endpoint capabilities and freezes the requested profile. Normal subscription buttons keep their existing route; subscription errors never press the paid buttons. Missing configuration stays unavailable.

For `serve --background`, pass the private file explicitly before `serve`, for example `python scripts/gb.py --env-file PROJECT/private.env serve --background --project PROJECT`. The detached server receives the absolute file path and reloads it; raw exported API keys/tokens/secrets remain excluded from its inherited environment. A foreground command keeps normal exported-value precedence. Stop and restart an existing server after changing its selected configuration; reopening Storyboard does not replace a running server's environment.

In Storyboard, **Prepare paid still launch** freezes one selected economy image or all three comparison alternatives. **Prepare paid video launch** requires an exact approved still and resolved recorded narration; it freezes that first frame, narration identity/interval, motion, sound flags, model, duration and resolution. Preparation performs capability GETs only. Inspect the displayed frozen prompt, reference identities, profile, output count and estimate, then use **Confirm this paid …-output launch**. A simple image-unit tariff can yield a provider estimate; tiered/token/video or absent pricing remains explicitly unknown. An estimate is not a spending cap. Changed/later launches require their own confirmation. Reloading or viewing a prepared launch never confirms it; duplicate preparation/confirmation reuses the intended jobs. Completed and failed attempts remain in history.

The adapter uses the dedicated [Images API](https://openrouter.ai/docs/api/api-reference/images/generate-an-image) and [Videos API](https://openrouter.ai/docs/api/api-reference/video-generation/submit-a-video-generation-request). Three alternatives are three separately journaled one-image requests under one three-output confirmation, retaining partial results. Image/interval-frame references are frozen and staged as actual pixels; raw reference videos are not sent. An advertised input-count/profile shortfall blocks the launch instead of dropping guidance. Video uses `frame_images` with `first_frame`, preserving the exact approved original bytes. Scene soundtrack and project narration remain separate, and still approval never approves a resulting video.

Image requests explicitly select PNG only when the frozen endpoint advertises that format. Otherwise the provider's default applies; the returned original must still validate as PNG or JPEG. This does not change the selected model, provider, resolution, aspect ratio or output count.

Known video requests can use **Recover saved result; no new generation** or `ai-resume --project PROJECT --job JOB_ID`. This polls and retrieves the retained handle without another generation POST. Unknown submissions with no handle remain uncertain and cannot auto-regenerate. The [current retrieval contract](https://openrouter.ai/docs/api/api-reference/video-generation/poll-video-generation-status) distinguishes authenticated content from signed URLs: credentials go only to the fixed API origin and the locally constructed content path for that handle; signed downloads use no bearer. Redirects are refused. Keys, remote error bodies and signed URLs stay out of public state and logs. Actual local decoding/hash/dimensions/duration/FPS/audio determine reviewability; requested 1080p does not turn smaller output into native Full HD. Review each retained result explicitly.

This implementation has synthetic/mocked transport and browser checks. It does not establish paid account access, real OpenRouter quality/reference fidelity or Resolve acceptance. Live spending requires a separately authorized concrete pilot.

### Recover AI work and correct an observed defect

Open **Attempts, recovery and observed defects** on the beat. Every retained attempt shows its result, state and corrective lineage. **Recover saved result; no new generation** retrieves the same known provider handle or publishes the recorded local original. `ai-resume --project PROJECT --job JOB_ID` is the agent equivalent. A request saved before submission offers **Continue this authorized request**: it sends that original frozen operation once. Unknown submission without a usable result identity stays uncertain; recovery cannot turn it into another generation. Provider rejection, interrupted retrieval, changed inputs and missing or changed media remain distinct. Refresh does not recover, generate, confirm or approve.

For a launched partial sequence, **Recover saved clips and assembly** retrieves only recoverable members and reuses intact completed clips. It also finishes local composition after a crash between the last clip commit and sequence publication. Earlier originals, jobs, journal and decisions remain saved. An unfinished download does not consume a corrective attempt. Concurrent recovery of the same job reports that it is already running; wait for that attempt to finish. Missing or changed committed bytes require restoring the exact original or reviewing a new explicitly requested version; they are not silently regenerated. The local server refuses uncommitted, damaged or stale AI output.

If a completed result has an observed visible defect, enter **Observed defect** and the desired correction beside that exact attempt. **Generate one correction of this defect** records the original version, defect, intent and frozen route before generating one additional result. A comparison or sequence shares one allowance across its original members. Reloading, another member or a corrective child cannot reset it. For a sequence, only the selected defective clip is replaced for a new pending-review assembly; other clips and earlier sequence versions remain retained. Ordinary editorial revisions still use the existing prompt/reference revision flow and are distinct from this bounded correction.

**Prepare one paid correction for confirmation** only saves its new scope. Inspect the new frozen prompt, inputs and known or unknown estimate, then confirm that specific paid launch; the original confirmation never authorizes it. Capability or quota errors do not choose another route. Video correction retains the exact approved first-frame bytes and recorded interval: a different scene or starting image must return through still generation/revision and exact still approval. Corrective output and a newly composed sequence need their own human review. Unsent correction text, scene comments and selected reference files stay in the browser during recovery and polling; an unsent file must still be explicitly kept before it becomes input to a new operation.

### Ordered AI sequences

After approving a still and resolving its recorded narration interval, open **Ordered AI sequence** in that beat. Choose Grok subscription or the explicitly configured OpenRouter video profile. **Prepare ordered clip plan** saves a bounded plan without generating video: contiguous frame placements, exact approved first frames, model, resolution, motion and soundtrack flags. The native clip limit must be supported by the recorded tool (image-to-video: 6 or 10 seconds; reference-to-video: 1–15 seconds). The paid route uses its configured supported duration. A plan contains at most 32 clips; longer work needs another explicit plan rather than an unbounded generation loop.

The initial plan repeats the timing-bound approved still. For distinct shots, choose another already approved still of this beat for each later clip, then prepare the changed order. New/unseen images must first pass the ordinary still preparation and exact approval workflow. These ordered shots are separate from the three scene alternatives. First-frame choices and sequence comments survive refresh and reopening. Launch always uses the displayed frozen plan, not later edits to controls.

For the subscription route, **Generate these … clips** explicitly launches that exact set. OpenRouter instead displays all frozen jobs and a total estimate or an explicit unknown cost; **Confirm this paid …-output launch** confirms the entire sequence. A partial set or changed scope is refused. Viewing, reloading, repeated confirmation or retrying a lost response never grants a new launch. Successful originals remain available beside failed/unknown jobs. Recover a known interrupted request through its saved handle, without another generation POST; unknown submissions without a handle remain uncertain.

When every clip is retained and decodable, local FFmpeg composition conforms frame rate, trims each original from frame zero to its planned placement, preserves order and scene sound, and verifies the exact total frame count. Original bytes, hashes, actual dimensions/durations, source job/still, placements and trims remain recorded. A short clip leaves `coverage_shortfall`; it is not stretched to hide missing coverage. Smaller originals are not enlarged to claim native Full HD. `profile_shortfall` remains visible even when temporal coverage is complete.

The sequence preview mixes the corresponding saved narration excerpt with scene sound. **Sequence for editing** opens the separate video with scene sound and no project narration; speech/music generation remains explicitly controlled by its launch flags. Review this sequence independently with **Approve this sequence**, changes or rejection. Its exact bytes, component originals, approved stills, timing, recording and profile bind that decision. Changed inputs make readiness stale while preserving earlier media and decisions. `status` reports the current sequence state, coverage and shortfalls without recovery or generation, preserving the ledger, journal and media. Portable review export/import carries the exact sequence version/signature and comments. This is synthetic-tested sequence production and review; live provider/Resolve acceptance remains a separate gate.

### Shared AI handoff for Resolve

`deliver` includes current AI coverage alongside documentary clips and authored graphics, in separate `entrega/ai/BEAT/VERSION-CONTEXT/` packages. An AI video or composed sequence needs its own exact-version human approval and a separate material-use declaration. In the live Storyboard, open **AI handoff**, record the responsible editor, conditions covering output and guided inputs, and the basis for that declaration. Choose `permitted`, `blocked` or `unresolved`, then **Save conditions for this version**. This saves conditions only; it does not approve media, generate, or publish a package. Unsent fields remain bound to that version through polling and reopening. A portable review shows a frozen readiness snapshot; editorial decisions still use the existing export/import workflow, while use conditions require the live server or CLI.

The CLI equivalent, after an explicit human declaration, is:

```sh
python scripts/gb.py ai-material-use --project PROJECT --version VERSION --signature DISPLAYED_SIGNATURE --state permitted --by EDITOR --conditions "Recorded project-use conditions for output and guided inputs" --evidence "Basis for the declaration"
python scripts/gb.py deliver --project PROJECT --dry-run
python scripts/gb.py deliver --project PROJECT
```

Reference access or editorial approval does not establish reuse permission. Native profile, coverage, exact saved bytes, approved starting stills and their revision/reference ancestry, current recording/timing/profile, editorial approval and use conditions are checked separately. Below-profile or stale output stays listed in `ai_skipped` with reasons; an affected AI beat does not prevent unrelated source or graphics delivery. A changed profile requires a new declaration and compatible media. `status.ai.delivery` and Storyboard distinguish ready, pending, delivered and modified/missing packages without recovery, generation, extraction, project locking or state writes. An AI-only project uses its saved AI plan for handoff guidance instead of asking for documentary candidates.

Each package contains the unchanged production `video.mp4`, separate bounded `narration.wav`, `timing.json`, `provenance.json` and `ORIGEM.md`. A sequence also keeps ordered original clips in `originals/`. Follow the recorded project frame placements and source trim boundaries when importing into Resolve; a single provider clip can extend beyond its used interval. Production video retains scene sound; the project narration is not baked into it. Provenance records actual dimensions, frame rate, duration, hashes, exact review/use decisions, approved source stills, prompts/instructions and available provider input hashes. Raw reference media is not redistributed. No upscale or fill disguises unmet coverage or native Full HD requirements.

Repeat delivery reuses identical bytes. New versions or changed declarations use distinct package destinations; earlier packages and foreign files remain. A destination link/junction, changed metadata, occupied file or mismatching media reports a conflict before copying that AI package. Restore the exact expected bytes or resolve the destination manually; `deliver` does not overwrite an editor's changes. The current `entrega/README.md` lists current coverage and omissions; an older retained package is not evidence of current readiness. Technical handoff does not establish successful Resolve import, editorial acceptance or complete-module readiness; those remain issue #91 acceptance.

## Storyboard

For scenario review, use `review --ready-only --project <PROJECT>` after preparing and visually checking each candidate with `preview --narration "<exact scenario line>" --reason "<observed match and limitations>"`. This view includes only candidates with narration and an existing motion GIF (or a prepared image asset). The search journal is collapsed under **Search options and shortfalls**, keeping the prepared previews in view; expand it to inspect raw hits, counts, viewing evidence and limitations. Search thumbnails and failed previews remain in the ledger and in the default full view; filtering does not change decisions. Regenerate the ready view after adding candidates. A scenario quote identifies the intended beat; it is not a verified quotation from the source. Record source speech in its original language and distinguish it from the scenario.

The Storyboard interface, preview/contact-sheet labels, and print/export controls are in English. Scenario narration and source material remain in their original language. The operational language policy is defined in [SKILL.md](../SKILL.md#language-policy). Refreshing a review page preserves existing content and decisions, including CLI rejections. An untouched browser default cannot replace a recorded rejection; an explicit new browser choice remains available for review and import. Changing the relevant source/interval/context invalidates stale decisions as usual. The selector and previous/next controls remain usable after switching clips. Other CLI routes and documentation may still contain Portuguese during the gradual migration.

A standalone review artifact, independent of the landing page. `gb.py review` generates `brolls/review.html` with embedded CSS and JavaScript, system fonts, and images/GIFs in `previews/`.

To serve that generated page locally, start the background server and open a returned URL. Stop it when review is finished. Windows PowerShell:

```powershell
python "$env:GB_SKILL_DIR\scripts\gb.py" serve --background --project "$env:GB_PROJECT"
python "$env:GB_SKILL_DIR\scripts\gb.py" serve --stop --project "$env:GB_PROJECT"
```

`serve --stop` checks the saved server-session identity before terminating the process. On Windows, a successful `stopped: true` waits for complete process termination and release of its log handles. The next start retains the previous log through the existing rotation.

For media files already allowed under `previews/` and `clips/`, GET with a single `Range: bytes` returns `206` with `Accept-Ranges: bytes`, `Content-Range` and the exact requested bytes. This lets the browser seek the effects video, bounded VO preview and bounded alignment excerpts. GET without Range returns the complete file with `200`; HEAD ignores Range and returns only the complete-file headers. Unsatisfiable ranges return `416`. Private narration originals, manifests and directory listings remain inaccessible.

1. Resolve the authorized original and use a distinct `--shot` for each insert.
2. Run `preview` with the interval, `--narration` (the exact supplied script line; omit when absent), and `--reason` (why this source was selected).
3. The selected insert keeps its original aspect ratio; its source and review controls appear alongside it. Gallery animation offers Static, GIF on hover, and GIF on modes. Click the selected preview to pause or play its GIF. Reduced-motion preferences are respected.
4. Choose Approve, Request changes, or Reject. Change requests require a comment; the request can ask for another source. Click Save decisions to save inside the project when using the local server, or download JSON when opened as a portable page. Save decisions does not create a PDF. If the local save cannot complete, the storage status keeps “Could not save to the project; downloaded the file instead.” and the file still downloads. Print / PDF waits for the print images to decode before opening the browser's print dialog; choose its PDF destination and save a static version with sources, narration, decisions and comments. Print images also load during review for native browser printing. An unavailable image does not prevent printing the source and review notes. Graphics cards on the same board list every retained complete version for comparison; their controls are Approve or Request changes, never candidate Reject. Selecting a version updates the timing badge from that frozen context and does not copy an unconfirmed change request onto another version. Frozen alignment forms stay disabled; the current assignment still shows one context-bound correction form. A graphics-only board omits “Nothing here yet. Return to the chat and request clips.” and still exposes Save decisions without a candidate player. Print hides graphics video, bounded VO preview, alignment candidate/override audio and interactive controls while keeping frozen context and recorded decisions. Explicit play/pause/seek/ended and version switches keep the effects video and frozen VO preview within one frame; there is no autoplay and a mute toggle does not record approval. Alignment candidate and manual-override previews are bounded independent auditions with source intervals that can differ from the rendered version; they offer play/seek, pause competing media, and are not synchronized to that version's effects video. Viewing does not extract a new alignment preview or start matching.
5. Import with `import-review --by`. Project identity, item IDs, interval/source signatures, and decision versions (`reviewEpoch`) are validated. Changed intervals or decisions invalidate earlier exports. Optional `alignment[]` rows bind to occurrence/recording/result fingerprints; stale or mismatched corrections skip without retargeting. Regenerate, review, and export again when a review is stale. A pre-2.4 export may use `legacy_review_epoch` while the item remains unchanged; stale decisions never overwrite newer ones.
6. Fetch the final clip after explicit human approval and recorded usage permission. Final MP4s are separate from the Storyboard.

See the [README](../README.md) for configuration, presets, and limitations. `preview` may acquire remote working media through supported acquisition routes; browser-based Instagram requires importing the joined MP4 first. A poster alone, including `--reference-only`, does not demonstrate motion.

The default is `GB_GIF_SCOPE=broll`. An optional presenter screenshot stays static. To review a completed composition of the same insert, use `full` with `--full-preview-file`. The purpose remains reviewing collection choices; no additional editing is required.

## Apêndice — utilitários legados

O fluxo principal é `python3 scripts/gb.py <subcomando>` (ver [Fluxo editorial](#fluxo-editorial)). Os scripts abaixo, em `${GB_SKILL_DIR}/scripts/getbrolls/tools/youtube/`, são anteriores à CLI unificada e continuam no repositório como utilitários avulsos de linha de comando — não fazem parte do caminho recomendado nem do fluxo revisado pelo Storyboard:

- `search.sh "<query>" [n]` → `ID | DURATION | TITLE` no YouTube, sem baixar.
- `contact.sh <id> <START-END> <out.jpg> [interval_seg=1.5] [cols=4]` gera um contact sheet manual.
- `frame.sh` extrai um still isolado (fallback do contact sheet).
- `fetch.sh <id> <START-END> <NN_entity_context> <PROJETO>/brolls` baixa o segmento trimado direto, fora do ledger/revisão da CLI.
- `verify.sh <PROJETO>/brolls` roda ffprobe/tamanho manualmente.
- `vertical.sh <in>` reformata um clipe existente para 9:16 com fundo borrado; não tem equivalente em `gb.py`.

Dependências: `yt-dlp` + FFmpeg. Usar esses scripts pula o registro em `events.jsonl`, a assinatura de revisão e o `permit`; prefira `gb.py` para qualquer material que vá para `clips/` ou para o Storyboard.
