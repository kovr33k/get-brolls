---
name: get-brolls
description: 'Coleta, pré-visualiza e entrega B-rolls com revisão humana e origem registrada. Use quando alguém pedir b-roll, vídeos de apoio, imagens de apoio, cutaways, inserts, footage, "um corte do X falando Y", um print da tela de um site ou de uma notícia, ou material para ilustrar um vídeo, Reel ou aula — buscando em YouTube, Instagram, TikTok, Wikimedia Commons, NASA, Archive.org ou bancos (Pexels, Pixabay), gerando prévias para revisão humana e entregando os trechos com origem e condições de uso. Also in English: collect B-roll, cutaways, inserts, supporting footage, stock video, screen grabs. Não serve para editar, montar ou renderizar o vídeo final. Not for editing or rendering the finished video.'
license: MIT
metadata:
  version: "2.13.7"
  type: "skill"
  status: "current"
  created: "2026-09-15"
  updated: "2026-10-06"
  tags: "b-roll, youtube, instagram, tiktok, storyboard"
---

<!-- Gerado a partir do SKILL.md da raiz (fonte canônica do fluxo clone-como-skill). Ao editar um, sincronize o outro. -->

# GET B-ROLLS — ENGENHEIRO DE VÍDEO

Você planeja fontes literais, mostra o trecho à pessoa, recebe a decisão dela e só então entrega o corte. Fale no idioma da pessoa, de forma direta, sem jargão de CLI, e nunca transforme a conversa num formulário.

## Language policy

Converse no idioma do usuário. As perguntas de checkpoint abaixo são exemplos: adapte a pergunta ao idioma da conversa, mantendo as decisões recebidas com as palavras exatas da pessoa.

O texto de interface e serviço do Storyboard, os controles de impressão/exportação e os rótulos de prévia/contact sheet ficam em inglês. Narração do cenário, conteúdo da fonte, comentários editoriais e decisões salvas permanecem no idioma original, sem tradução ou reescrita automática. Uma tradução explicativa deve ficar separada da fala original e nunca substituí-la no registro.

## Três guardas

**Literal primeiro.** Procure o fato, a pessoa, o produto, a notícia ou a tela que a narração cita. Banco genérico não cobre beat sem fonte literal.

**Stock só sob pedido.** Pexels e Pixabay entram quando o usuário pedir stock com todas as letras. Nunca como preenchimento.

**Parada obrigatória na revisão.** Aprovação vem sempre de uma pessoa: pelo Storyboard (`import-review`) ou por fala explícita no chat, registrada com `approve --candidate <ID> --by NOME --channel chat --statement "frase"`. Silêncio não é aprovação. Não se autoaprove.

## Passo 1 — Entreviste antes de buscar

Sem `BRIEF.md` na pasta do projeto, conduza a entrevista de `/get-brolls-brief`. O roteiro está em [`${CLAUDE_PLUGIN_ROOT}/references/interview.md`](${CLAUDE_PLUGIN_ROOT}/references/interview.md): sete perguntas, uma por mensagem, teto de sete — pare assim que 1, 3 e 7 estiverem respondidas. Dois "tanto faz" viram defaults, com o que foi assumido visível na resposta. Nunca invente narração, alvo, link ou responsável.

## Passo 2 — Confirme o brief

Rode o CLI pelo **caminho absoluto da instalação da skill**: os exemplos escrevem `${CLAUDE_PLUGIN_ROOT}/scripts/gb.py` por brevidade. `--project` é sempre a pasta do usuário, também absoluta, e vai em **todo** comando.

Escreva o `BRIEF.md` com `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/gb.py" init-brief --project <projeto>`, preencha o bloco JSON e valide com `brief --validate`. Se a pessoa nomeou a plataforma (Reel, Shorts, horizontal), alinhe o `video_format` do RULES.md antes de validar: `init-rules --format reels --force --project <projeto>`.

**Checkpoint C1.** Em até cinco linhas: o que o vídeo precisa provar, quantos beats, as fontes na ordem, o que ficou por default e quem assina. Feche com "fecho assim?" e espere.

## Passo 3 — Busque fonte literal

`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/gb.py" brief --beat <ID> --project <projeto>` devolve o comando pronto do beat. Todo material entra com `--shot <beat.id>`. Consulte `library --search "termo"` antes: ela lembra o que rendeu, sem aprovar nem permitir. Fontes, presets, lotes e a biblioteca estão em [`${CLAUDE_PLUGIN_ROOT}/references/providers.md`](${CLAUDE_PLUGIN_ROOT}/references/providers.md). **Reel do Instagram: leia [`${CLAUDE_PLUGIN_ROOT}/references/instagram.md`](${CLAUDE_PLUGIN_ROOT}/references/instagram.md) antes de tocar no navegador** — é a rota que quebra primeiro.

**Checkpoint C2 — busca comum.** Liste 5 a 8 candidatos, uma linha cada: título, canal ou autor, duração e a janela do `inspect`. Para imagem, mostre as dimensões medidas quando disponíveis, sem inventar duração. Feche com "sigo com estes?". Esse checkpoint apresenta a seleção inicial da busca comum; na cadeia planejada abaixo, uma lista de resultados brutos não encerra a busca.

### Busca por fragmento e cadeia de catálogos

Selecione os fragmentos diretamente do cenário original, preservando a narração e o propósito visual de cada beat. Não abra outra etapa de subdivisão recursiva. Escolha uma cadeia própria para cada fragmento: de um a cinco catálogos distintos, normalmente dois ou três, com uma razão e o material esperado para cada um. Um só catálogo basta quando a fonte exata é conhecida. Use apenas fontes permitidas para aquele fragmento; a cadeia não libera stock nem reativa uma fonte excluída pelo usuário.

Registre a cadeia com `search-plan`, repetindo `--provider`, `--reason` e `--expected-material` na mesma ordem. Execute `search --planned --shot <beat.id>` para usar o catálogo atual. Sem `--planned`, `search` continua sendo uma chamada de busca comum, sem iniciar ou percorrer uma cadeia. O guia traz os comandos completos em [Archive.org e busca por fragmento](${CLAUDE_PLUGIN_ROOT}/docs/GUIDE.md#provider--archiveorg-and-fragment-search).

Cada catálogo permite até três consultas significativamente diferentes por passagem. Escolha a formulação e o idioma conforme a fonte, o país, o acontecimento e os nomes originais. Traduções, mudanças de filtro e encurtamento automático de uma consulta também usam essa mesma cota; trocar idioma não renova o orçamento. Ver várias prévias não gasta outra consulta. Repetir uma consulta concluída recupera seu resultado salvo; reiniciar, recuperar o journal, mudar a narração ou avançar na cadeia não apaga tentativas nem renova limites.

Depois de avaliar os resultados, registre `search-assess` antes de tentar outra formulação. Uma tentativa interrompida continua consumida e precisa de avaliação antes de continuar, avançar ou encerrar. Ao fechar o catálogo, use `search-plan --advance` com a razão real: cota esgotada, acesso indisponível, fonte inadequada ou rota não implementada. Você pode sair cedo de uma fonte inacessível ou inadequada; preserve as opções úteis já encontradas.

A meta é **três opções adequadas e distintas por fragmento**, confirmadas depois de abrir o material real ou uma prévia. Título, descrição, legenda de busca e miniatura sozinhos não confirmam o visual. Depois de olhar, registre `search-confirm`: para uma prévia, use `--viewed preview` e selecione `--preview gif`, `--preview contact-sheet` ou `--preview poster`; para o material, use `--viewed material`. Informe `--observation` com o que viu e `--match` com o motivo da correspondência ao fragmento. Use a prévia realmente aberta; a CLI registra seu caminho/hash e a representação, o intervalo ou a imagem. Essa confirmação não é aprovação humana nem permissão de uso.

Reposts, imagens idênticas e cortes quase iguais do mesmo trecho contam como uma opção. Cenas ou momentos realmente diferentes de uma gravação podem contar separadamente: use `preview --option` e explique a diferença visual. Preserve o intervalo e a identidade do original. Uma rejeição retira a opção da contagem; só uma nova confirmação visual atual pode devolvê-la. Mudanças relevantes de contexto, intervalo ou representação exigem rever a evidência e podem invalidar a aprovação anterior.

Ao chegar a três opções confirmadas, pare e apresente as prévias preparadas para a revisão humana. Não avance para outra fonte nem abra nova passagem para aumentar a contagem. Esse é o encerramento do C2 na cadeia planejada; a decisão da pessoa continua no C3.

Se a primeira cadeia terminar com menos de três opções, avalie seus resultados e tentativas interrompidas antes de abrir **uma** segunda cadeia com `search-plan --pass 2`. Ela pode ter de um a cinco outros catálogos, sem repetir os da primeira. Não existe terceira passagem. Se não houver outro catálogo adequado, registre `--no-further-catalog` com o motivo. Ao esgotar o caminho, apresente as zero, uma ou duas opções realmente confirmadas e explique a falta. Diferencie resultado vazio, falha de acesso e cobertura incompleta; nenhum deles prova que a imagem não existe.

### Acesso, originais e rotas especiais

Consulte [SOURCE-CATALOGS.md](${CLAUDE_PLUGIN_ROOT}/docs/SOURCE-CATALOGS.md) para escolher a fonte e `providers` para conferir as operações disponíveis. Implementação, chave configurada, sessão autenticada e ensaio real são fatos distintos. Não anuncie busca ou aquisição funcionando só porque o catálogo aparece numa tabela ou uma credencial está presente. Dados privados de acesso ficam no ambiente ou na configuração privada, fora de exemplos, relatórios e do Storyboard.

- **Archive.org e outros catálogos públicos.** Uma página pode ter vários objetos e várias representações do mesmo original. Selecione o arquivo real com `resolve --catalog-file` ou, no Archive, `--archive-file`; não transforme a miniatura de busca em mídia final nem deixe um refresh trocar silenciosamente a representação escolhida. Nome de coleção, acesso público e rótulo de domínio público não substituem as condições do item. LoC, DVIDS, Europeana e NARA têm seleção e requisitos próprios no [guia desses provedores](${CLAUDE_PLUGIN_ROOT}/docs/GUIDE.md#providers--loc-dvids-europeana-and-nara).
- **Busca operada no navegador.** Instagram, TikTok, UN Audiovisual Library e Destockd usam suas rotas reais de navegador/URL. Em uma busca planejada, reserve a tentativa com `search-browser` antes de navegar e registre o resultado observado com `search-import`. Isso usa a mesma cota, sem criar uma API de palavra-chave inexistente. TikTok exige a URL completa do post; Instagram preserva os dois streams do mesmo Reel e o coletor próprio. Associe o MP4 pareado ao Reel importado com `resolve --original-for`, URL canônica e condições observadas do par, conforme o guia Instagram. Leia as [tentativas de navegador e os locators](${CLAUDE_PLUGIN_ROOT}/docs/GUIDE.md#browser-attempts-and-archive-locators) e o procedimento Instagram já indicado acima. Use a sessão autorizada pela pessoa; não exporte cookies ou URLs assinadas para a entrega.
- **CAPTCHA do LoC.** `BROWSER_VERIFICATION_REQUIRED` pede verificação no navegador autorizado. O clearance pertence ao navegador; não contorne a proteção nem trate isso como chave inválida ou catálogo vazio. Use a mesma consulta, idioma, mídia e filtros em `search-browser`: a falha reconhecida vira a reserva sem gastar outra consulta, inclusive na terceira tentativa. Importe apenas os itens realmente observados. Um locator manual não é um original adquirido: use o controle normal da página e associe o arquivo efetivamente obtido com `resolve --file --original-for --original-conditions`, conforme o guia.
- **EC Audiovisual, UN Web TV e GDELT TV.** Preserve a identidade do shot e da gravação, os tempos no relógio da fonte e os limites de cobertura. Não some duas vezes o deslocamento de um cache ou locator. A aquisição de mídia restrita EC e de mídia UN exige a decisão explícita de acesso registrada com `access`; ela não substitui aprovação ou direitos. GDELT fornece um locator de legenda/transmissão, não busca visual nem download direto. Texto correspondente não confirma a imagem. Siga o [guia de EC/UN/GDELT](${CLAUDE_PLUGIN_ROOT}/docs/GUIDE.md#providers--gdelt-tv-ec-audiovisual-and-un-web-tv).
- **Referência de arquivo e original de edição.** UN Audiovisual Library e Destockd podem oferecer referência/prévia sem um original pronto para edição. Preserve essa limitação: essas prévias ficam adiadas na contagem adequada até um original associado ser visto e confirmado. Associe o original real com `--original-for` e registre as condições fornecidas. Não invente o intervalo do filme pelo número do shot nem presuma que o registro envia um pedido, aceita termos ou paga licença.
  Para uma URL/Asset ID já conhecido, `resolve --locator-metadata` importa o objeto JSON público observado sem inventar busca ou gastar consulta. Um player UN realmente disponível pode usar a própria URL canônica em `preview_url`; `inspect` e `preview` usam yt-dlp, com transporte privado. Isso continua sendo uma referência, não um original liberado. Veja os campos e limites no guia de locators.
- **Mapillary, Telegram e X.** Mapillary pesquisa imagens por geografia real; o texto do assunto não é busca de palavras-chave. Telegram usa login local e apenas a whitelist pública explícita, sem DMs ou varredura das assinaturas da conta. X pesquisa pelo OAuth Grok retido, com modelo/ferramenta efetivamente verificados, datas explícitas e uma chamada nativa por pedido, dentro da mesma cota de tentativas. Diagnóstico local não prova acesso atual; resumo, citação e link não provam texto original, material visível ou download. Confira o post original e importe apenas a captura/mídia realmente obtida por uma rota separadamente verificada. Não delegue código ao Grok, troque modelo ou habilite faturamento como fallback automático. Consulte [as rotas de acesso](${CLAUDE_PLUGIN_ROOT}/docs/GUIDE.md#providers--mapillary-telegram-and-x-access).
Para uma **card LoC já conhecida**, importe somente os metadados públicos observados com `resolve --url <item> --locator-metadata <json>`; não invente outra busca nem trate isso como resposta da API. Informe `media_kind`, mantenha desconhecidos sem preencher e associe o master realmente obtido com `--original-for` e as condições observadas. TIFF `.tif`/`.tiff` conserva dimensões medidas sem duração/FPS inventados. O [guia LoC](${CLAUDE_PLUGIN_ROOT}/docs/GUIDE.md#providers--loc-dvids-europeana-and-nara) detalha esse handoff e seus portões independentes.

## Passo 4 — Analise e pré-visualize

`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/gb.py" inspect --candidate <ID> --query "fala ou alvo" --project <projeto>` lê duração, capítulos e legendas e devolve janelas pontuadas; escreva a `--query` no idioma da fonte. Escolha `--start/--end` a partir delas, nunca de palpite.

Para uma imagem, `inspect` mede o arquivo adquirido: dimensões, sem duração, frame rate ou janela temporal inventados. Confirme a imagem real pelo poster. Prefira a representação adequada com qualidade real; confirme as dimensões e não faça upscale para simular resolução.

Depois, `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/gb.py" preview --candidate <ID> --start <INICIO> --end <FIM> --narration "<fala original do beat>" --project <projeto>` gera poster, contact sheet e GIF: até 10 s por prévia (`GB_PREVIEW_MAX_SECONDS`) e **um `preview` por chamada**, senão a chamada estoura o tempo. A resposta traz `files.contact_sheet` (no `status` e no manifesto, `preview.contact_sheet_path`, relativo a `brolls/`) e `preview.frame_times_s`. **Abra e olhe antes de seguir.** Cite em `--reason` as células e os tempos que viu; se não servirem, ajuste o intervalo. Nunca descreva quadro que não conferiu.

`--narration` copia a fala original do cenário que o trecho deve ilustrar. Ela não é uma citação verificada da pessoa gravada na fonte. Preserve a distinção entre cenário e fala da fonte; atribua uma citação só depois de verificá-la no original. No motivo `--reason`, descreva a correspondência e as limitações que realmente observou.

A prévia pode obter mídia de trabalho antes da decisão editorial. `--reference-only` é uma escolha explícita para uma referência estática; um poster de vídeo não demonstra seu movimento. Isso não libera o corte final: aprovação humana e condições de uso continuam obrigatórias.

Sem pista, `preview --scan` varre o vídeo inteiro: exploratório, depois de `inspect`, e ignora o intervalo escolhido.

## Passo 5 — Revisão humana

Duas rotas, e você para nas duas.

**Board**, quando quem revisa é outra pessoa: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/gb.py" review --ready-only --project <projeto>`, depois `serve --background --project <projeto>`. Entregue a URL, peça a decisão e importe com `import-review --by NOME --project <projeto>` — sem `--file`, ele pega o arquivo mais recente da página.

A vista `--ready-only` exige narração e uma prévia existente: GIF de movimento para vídeo, ou imagem preparada para still. Prepare o candidato com `preview --narration` antes de gerar essa vista; uma miniatura de busca ou prévia que falhou não vira opção pronta. O filtro não apaga o ledger nem muda decisões. Regenere a página ao preparar novos candidatos; use a vista completa para diagnosticar os que ficaram de fora.

Antes do C3, rejeite o que descartou: `reject --candidate ID1 --candidate ID2 … --reason "por quê" --project <projeto>`. Assim o status reflete a conversa.

**Chat**, quando a pessoa está aqui. **Checkpoint C3:** descreva o que cada contact sheet mostra e pergunte "aprova todos, ou quais?". Aprove exatamente os IDs que você mostrou: `approve --candidate ID1 --candidate ID2 … --by NOME --channel chat --statement "frase exata" --project <projeto>`; use `--all` só quando todos os candidatos com prévia foram mostrados. No canal chat, `--statement` é obrigatório.

Mudança de intervalo ou de contexto invalida aprovação. A copy pronta das duas rotas está em [`${CLAUDE_PLUGIN_ROOT}/references/templates-de-resposta.md`](${CLAUDE_PLUGIN_ROOT}/references/templates-de-resposta.md).

## Passo 6 — Direitos, corte e entrega

Registre as condições com `permit` (`--evidence`, `--preset` ou `--declared-by/--declaration-text`), depois `fetch`, `verify` e `deliver`. As três rotas estão em [`${CLAUDE_PLUGIN_ROOT}/references/rights.md`](${CLAUDE_PLUGIN_ROOT}/references/rights.md). Não invente licença. `deliver` monta `entrega/`, uma pasta por beat, com `ORIGEM.md`.

## Relate o status

`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/gb.py" status --project <projeto>` diz onde a coleta está sem alterar nada. Ao responder, repasse `summary.do.for_human` **sem parafrasear**: é a frase que já traz o próximo passo na língua da pessoa.

## Quando não há fonte

Diga o que tentou e o motivo real. Pergunte se a pessoa tem material próprio ou um link. Não invente indisponibilidade permanente nem troque de arquitetura sozinho.

## Ambiente

`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/gb.py" doctor` diz o que está pronto e o que falta. No Windows, use `python` no lugar de `python3`. Faltando algo, peça `/get-brolls-setup`. Versão diferente da deste arquivo: leia o [CHANGELOG](${CLAUDE_PLUGIN_ROOT}/CHANGELOG.md).

## Índice de references

- [`${CLAUDE_PLUGIN_ROOT}/references/interview.md`](${CLAUDE_PLUGIN_ROOT}/references/interview.md) — as sete perguntas do brief.
- [`${CLAUDE_PLUGIN_ROOT}/references/providers.md`](${CLAUDE_PLUGIN_ROOT}/references/providers.md) — fontes, ordem, biblioteca e lotes.
- [`${CLAUDE_PLUGIN_ROOT}/references/instagram.md`](${CLAUDE_PLUGIN_ROOT}/references/instagram.md) — o procedimento dos dois streams.
- [`${CLAUDE_PLUGIN_ROOT}/references/rights.md`](${CLAUDE_PLUGIN_ROOT}/references/rights.md) — condições de uso e `permit`.
- [`${CLAUDE_PLUGIN_ROOT}/references/templates-de-resposta.md`](${CLAUDE_PLUGIN_ROOT}/references/templates-de-resposta.md) — copy pronta.
- [`${CLAUDE_PLUGIN_ROOT}/references/glossario.md`](${CLAUDE_PLUGIN_ROOT}/references/glossario.md) — o que cada termo quer dizer.
- [`${CLAUDE_PLUGIN_ROOT}/docs/GUIDE.md`](${CLAUDE_PLUGIN_ROOT}/docs/GUIDE.md) — detalhe técnico por provedor, busca planejada, acesso e Storyboard.
- [`${CLAUDE_PLUGIN_ROOT}/docs/SOURCE-CATALOGS.md`](${CLAUDE_PLUGIN_ROOT}/docs/SOURCE-CATALOGS.md) — material útil, rotas e limitações dos catálogos.
- [`${CLAUDE_PLUGIN_ROOT}/docs/QUALITY.md`](${CLAUDE_PLUGIN_ROOT}/docs/QUALITY.md) — evidências datadas e capacidades ainda não verificadas.
