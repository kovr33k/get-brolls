"""Argument contract and structured command output."""

import argparse
import contextlib
import json
import logging
import sys
import time
import traceback
from pathlib import Path

from . import __version__, logs
from .presets import PERMIT_PRESETS
from .runtime import READ_ONLY_ACTIONS, READ_ONLY_COMMANDS, OperationError, audited

# Named so a caller (script, test, or someone scripting the CLI) never has to hardcode 2/3.
EXIT_OPERATION_ERROR = 2
EXIT_INTERNAL_ERROR = 3

# Uma linha por subcomando: o que ele faz no fluxo coleta → revisão → entrega.
SUMMARIES = {
    "providers": "Listar fontes disponíveis, transporte e chaves configuradas",
    "doctor": "Diagnosticar dependências, caminhos fixados e fontes utilizáveis",
    "telegram-login": "Authorize the private Telegram user session in a local interactive terminal, including 2FA",
    "x-access": "Inspect retained Grok OAuth prerequisite metadata without invoking Grok, refreshing tokens or using API billing",
    "status": "Resumir onde o projeto está por etapa, sem alterar arquivos",
    "search": "Pesquisar candidatos numa fonte e registrá-los no projeto (--shot liga ao beat; --dry-run não grava)",
    "search-plan": "Save an ordered catalog chain for a BRIEF fragment without resetting query allowances",
    "search-assess": "Record the managing agent's assessment of a fragment search attempt",
    "search-confirm": "Record that a fragment option was actually viewed and whether it matches",
    "search-browser": "Reserve a fragment query before the managing agent searches an authorized browser",
    "search-import": "Complete a reserved browser attempt with observed public results or an access limitation",
    "resolve": "Registrar um candidato a partir de URL pública ou arquivo local",
    "inspect": "Analisar a fonte (duração, capítulos, legendas) antes de coletar",
    "preview": "Gerar prévia (GIF/contact sheet) do intervalo escolhido",
    "approve": "Registrar aprovação humana já recebida para o intervalo atual",
    "permit": "Registrar as condições reais de uso do trecho antes da coleta",
    "access": "Record an explicit EC/UN access decision for this asset and current brief; separate from rights and approval",
    "reject": "Marcar candidatos como rejeitados e invalidar suas revisões (--candidate repetível)",
    "fetch": "Produzir o corte final aprovado e permitido em clips/",
    "verify": "Conferir integridade e decodificação dos arquivos coletados",
    "review": "Gerar o Storyboard local em brolls/review.html",
    "import-review": "Importar o JSON de decisões exportado pelo Storyboard",
    "init-rules": "Criar um RULES.md editável no projeto (--format muda o formato-alvo)",
    "rules": "Mostrar as regras editoriais em vigor no projeto",
    "init-brief": "Criar um BRIEF.md editável com o plano deste vídeo",
    "brief": "Mostrar os beats do vídeo e o comando pronto de cada um",
    "remember": "Registrar referência aprovada ou rejeitada na memória do projeto",
    "references": "Consultar as referências memorizadas do projeto",
    "learn": "Guardar busca, preferência ou trecho útil na biblioteca entre projetos",
    "library": "Consultar a biblioteca entre projetos antes de sair buscando",
    "browser-plan": "Planejar a captura de uma página pelo navegador autorizado",
    "queue": "Enfileirar URLs sociais e ditar o ritmo do lote (add, next, mark, status)",
    "serve": "Servir brolls/review.html em 127.0.0.1 para abrir o Storyboard no navegador",
    "deliver": "Organize collected clips, approved graphics and permitted reviewed AI coverage in entrega/",
    "graphics-doctor": "Diagnose the optional local Remotion graphics runtime without changing a project",
    "graphics-style": "Record a proposed documentary graphics style revision; does not approve a scene",
    "graphics-assign": "Register an explicit graphics occurrence from original scenario fields",
    "graphics-render": "Render one graphics occurrence into a new immutable version for review",
    "graphics-continue": "Continue saved graphics sequentially, verifying dependencies and reusing intact results",
    "graphics-checkpoint": "Save actual research, authoring or waiting work without declaring a finished render",
    "graphics-timeline": "Save editable dated milestones and narration-clock emphasis for one timeline occurrence",
    "graphics-content": "Save selected geographic data or editable authored custom scene content",
    "graphics-handoff": "Save one specialist context packet for host delegation or recovery; never launch an agent",
    "graphics-approve": "Record an explicit human approval of one complete graphics version; render is not approval",
    "graphics-select": "Select an existing complete graphics version without rewriting frozen files",
    "graphics-request-complete": "Record chat-authorized processing of a saved graphics revision request",
    "graphics-reference-apply": "Bind inspected saved references and actual analysis to graphics authoring; never render",
    "graphics-reference-inspect": "Sample an explicitly resolved saved video interval for temporal inspection; never render",
    "graphics-reference-scope": "Freeze concrete shared reference targets and per-scene instructions; never render",
    "graphics-facts": "Attach researched displayed-fact evidence to one graphics occurrence from bounded --file JSON",
    "graphics-fact-resolve": "Record an already received editorial decision for one saved fact conflict; does not invent approval",
    "graphics-audio": "Attach confined sound cues and optional VO source clocks to one graphics occurrence from bounded --file JSON",
    "graphics-sound-import": "Materialize or reuse one named permitted CC0 effect into project sounds/; viewing does not download",
    "narration-analyze": "Submit or reuse complete-recording Inworld transcription; does not match scenes",
    "narration-resume": "Resume a saved narration analysis identity without silently resubmitting",
    "graphics-background": "Attach confined project video or photograph background to one graphics occurrence from bounded --file JSON",
    "narration-match": "Match assigned graphics passages to a completed narration analysis without retranscribing",
    "graphics-timing-resolve": "Record an explicit candidate confirmation or bounded time override for one occurrence; does not retranscribe",
    "ai-plan": "Register original-scenario routing and three textual AI alternatives; does not generate media",
    "ai-select": "Save an AI beat's selected alternative, comment and comparison mode; does not generate",
    "ai-generate-still": "Create one durable subscription still job from the selected economy scene after explicit launch",
    "ai-generate-comparison": "Create three durable GPT-subscription still jobs, one per saved treatment, after an explicit three-output launch",
    "ai-approve": "Record an explicit human decision on one saved AI still; generation is not approval",
    "ai-timing": "Match one AI beat to a completed narration analysis; does not transcribe or generate",
    "ai-timing-resolve": "Record an explicit candidate or bounded interval correction; does not pick the first candidate",
    "ai-generate-video": "Freeze one exact approved still and the resolved narration interval into one native video job",
    "ai-resume": "Recover a saved AI image/video job without resubmitting an unknown outcome",
    "ai-material-use": "Record material-use conditions for one exact AI video or sequence, separately from editorial approval",
}

# Subcomandos que `execute()` (commands.py) de fato leva até
# `sync_formats(ledger, rules, confirm=...)`: os demais retornam antes (serve, queue,
# init-rules, init-brief, brief, learn, library, rules) ou estão em READ_ONLY_CONSULTS
# (references, inspect) — `--confirm-format-change` não tem efeito nenhum lá.
FORMAT_GATE_SUBCOMMANDS = (
    "search",
    "resolve",
    "preview",
    "approve",
    "permit",
    "access",
    "reject",
    "fetch",
    "verify",
    "review",
    "import-review",
    "remember",
    "browser-plan",
    "deliver",
)


def build_parser():  # noqa: C901, PLR0912, PLR0915 - existing size; argparse builder with one branch per subcommand/flag
    parser = argparse.ArgumentParser(
        description="Get B-rolls — pesquisar, revisar e coletar trechos por fonte.",
        epilog="Use `<subcomando> --help` para os argumentos de cada etapa.",
    )
    parser.add_argument("--env-file", help="Arquivo .env explícito; padrão: .env na raiz da skill")
    parser.add_argument(
        "--version",
        action="version",
        version=f"get-brolls {__version__}",
        help="Mostrar a versão instalada da skill e sair",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("providers", "doctor", "graphics-doctor", "telegram-login", "x-access"):
        p = sub.add_parser(name, help=SUMMARIES[name], description=SUMMARIES[name])
        if name == "x-access":
            p.add_argument("--model", help="Already selected retained model; does not choose or invoke another model")
        if name == "graphics-doctor":
            p.add_argument(
                "--project",
                help="Aceito por uniformidade e ignorado: o diagnóstico é da instalação, não do projeto",
            )
            p.add_argument(
                "--prepare-browser",
                action="store_true",
                help="Download or verify the local Remotion browser once; render will not download it by itself",
            )
        if name == "doctor":
            # O SKILL.md diz que `--project` vai em todo comando, e a primeira chamada
            # do fluxo é o `doctor`: recusá-lo ali é contradizer a instrução logo na
            # largada. Aceito e ignorado — o diagnóstico é da instalação, não do projeto.
            p.add_argument(
                "--project",
                help="Aceito por uniformidade e ignorado: o diagnóstico é da instalação, não do projeto",
            )
            p.add_argument(
                "--live",
                action="store_true",
                help="Testar buscas reais/refresh; pode consumir quota de API",
            )
    for name in (
        "status",
        "search",
        "search-plan",
        "search-assess",
        "search-confirm",
        "search-browser",
        "search-import",
        "resolve",
        "inspect",
        "preview",
        "approve",
        "permit",
        "access",
        "reject",
        "fetch",
        "verify",
        "review",
        "import-review",
        "init-rules",
        "rules",
        "init-brief",
        "brief",
        "remember",
        "references",
        "learn",
        "library",
        "browser-plan",
        "queue",
        "serve",
        "deliver",
        "graphics-style",
        "graphics-assign",
        "graphics-render",
        "graphics-continue",
        "graphics-checkpoint",
        "graphics-timeline",
        "graphics-content",
        "graphics-handoff",
        "graphics-approve",
        "graphics-select",
        "graphics-request-complete",
        "graphics-reference-apply",
        "graphics-reference-inspect",
        "graphics-reference-scope",
        "graphics-facts",
        "graphics-fact-resolve",
        "graphics-audio",
        "graphics-sound-import",
        "narration-analyze",
        "narration-resume",
        "graphics-background",
        "narration-match",
        "graphics-timing-resolve",
        "ai-plan",
        "ai-select",
        "ai-generate-still",
        "ai-generate-comparison",
        "ai-approve",
        "ai-timing",
        "ai-timing-resolve",
        "ai-generate-video",
        "ai-resume",
        "ai-material-use",
    ):
        p = sub.add_parser(name, help=SUMMARIES[name], description=SUMMARIES[name])
        p.add_argument(
            "--project",
            required=True,
            help="Pasta do projeto que guarda brolls/, fora da instalação da skill",
        )
        if (
            name != "status"
            and not name.startswith("graphics-")
            and not name.startswith("narration-")
            and not name.startswith("ai-")
        ):
            # Mudar o formato-alvo derruba aprovações humanas; qualquer comando que
            # sincronize formato precisa deste sim explícito antes de apagá-las. Mas
            # `execute()` só chega a `sync_formats` (commands.py) depois de passar
            # pelos retornos antecipados de serve/queue/init-rules/init-brief/brief/
            # learn/library/rules e por cima de READ_ONLY_CONSULTS (references,
            # inspect) — nesses a flag continua aceita (scripts e agentes já a
            # passam para eles) mas some do `--help` porque nunca teve efeito ali.
            # Graphics writes return before sync_formats and are not format-gate commands.
            reaches_sync_formats = name in FORMAT_GATE_SUBCOMMANDS
            p.add_argument(
                "--confirm-format-change",
                action="store_true",
                help="Confirmar que aprovações já dadas podem ser invalidadas pela mudança de formato"
                if reaches_sync_formats
                else argparse.SUPPRESS,
            )
        if name == "serve":
            g = p.add_mutually_exclusive_group()
            g.add_argument(
                "--background",
                action="store_true",
                help="Subir o servidor num processo solto e devolver a URL na hora (PID em brolls/.serve.pid)",
            )
            g.add_argument(
                "--stop",
                action="store_true",
                help="Encerrar o servidor de fundo pelo PID gravado em brolls/.serve.pid",
            )
            p.add_argument(
                "--port",
                type=int,
                default=None,
                help="Porta local para o servidor (padrão 8767; se ocupada, usa uma porta livre)",
            )
        if name == "deliver":
            p.add_argument(
                "--dry-run",
                action="store_true",
                help="Show the entrega/ plan, including approved graphics, without creating, linking, or deleting anything",
            )
        if name == "queue":
            p.add_argument(
                "--action",
                choices=["add", "next", "mark", "status"],
                required=True,
                help="add: enfileirar URLs; next: próximo item ou tempo de espera; mark: registrar resultado; status: contagens e cooldown",
            )
            p.add_argument(
                "--provider",
                choices=["instagram", "tiktok", "youtube"],
                help="Fonte das URLs em add; em next, limita a fila a essa fonte",
            )
            p.add_argument("urls", nargs="*", help="URLs públicas a enfileirar (add); repetidas são ignoradas")
            p.add_argument("--url", action="append", help="URL pública a enfileirar (add); pode repetir")
            p.add_argument("--id", help="ID do item retornado por next (mark)")
            g = p.add_mutually_exclusive_group()
            g.add_argument("--done", action="store_true", help="mark: item coletado com sucesso; zera o cooldown")
            g.add_argument(
                "--failed",
                action="store_true",
                help="mark: item falhou; motivo com 403/429, challenge/login, 'rate limit'/'too many requests' ou as mensagens de bloqueio da própria skill (sessão de acesso, IP bloqueado, limite de requisições) abre cooldown",
            )
            g.add_argument("--skipped", action="store_true", help="mark: item pulado sem tentar")
            p.add_argument("--reason", help="Motivo real registrado no item (mark)")
        if name == "approve":
            # Repetível de propósito: "aprovei todos" do usuário quer dizer "os que
            # você me mostrou", e só quem mostrou sabe quais foram. Listar os IDs é
            # mais barato que descobrir depois que `--all` pegou um descarte com
            # prévia esquecida em disco.
            p.add_argument(
                "--candidate",
                action="append",
                help="ID do candidato a aprovar; repita a flag para aprovar vários (ou use --all)",
            )
        elif name == "reject":
            # Repetível como `approve`, e pelo mesmo motivo: quem descarta descarta em
            # leva, olhando a mesma lista que mostrou. Sem `--all`: rejeitar em massa o
            # que ninguém viu apagaria candidato bom por engano, e aqui não há `--all`
            # que valha o risco.
            p.add_argument(
                "--candidate",
                action="append",
                required=True,
                help="ID do candidato a rejeitar; repita a flag para rejeitar vários",
            )
        elif name in ("preview", "permit", "access", "fetch", "remember"):
            p.add_argument(
                "--candidate",
                required=True,
                help="ID do candidato retornado por search/resolve",
            )
        if name in ("preview", "approve"):
            p.add_argument(
                "--start",
                "--source-start",
                dest="start",
                type=float,
                help="Source-clock start in seconds; overrides an EC shot's suggested provider start",
            )
            p.add_argument("--end", type=float, help="Fim do trecho na origem, em segundos")
        if name == "inspect":
            g = p.add_mutually_exclusive_group(required=True)
            g.add_argument(
                "--candidate",
                help="ID do candidato já registrado; grava só media.duration_s",
            )
            g.add_argument("--url", help="URL pública da fonte, sem registrar candidato")
            p.add_argument(
                "--query",
                help="Fala ou alvo do trecho; pontua as janelas candidatas",
            )
            p.add_argument(
                "--language",
                help="Language of --query and preferred subtitles for this video (es, ru, uk, pt-BR); omission prefers the original",
            )
            p.add_argument(
                "--max-windows",
                type=int,
                default=3,
                help="Quantas janelas candidatas devolver, 1–20 (padrão 3)",
            )
        if name == "preview":
            p.add_argument(
                "--scan",
                action="store_true",
                help="Varrer o vídeo inteiro num contact sheet de baixa resolução, sem definir intervalo",
            )
            p.add_argument(
                "--reference-only",
                action="store_true",
                help="Gerar apenas referência estática, sem obter trecho remoto",
            )
            p.add_argument("--narration", help="Fala exata do roteiro")
            p.add_argument("--reason", help="Decisão de coleta desta fonte")
            p.add_argument(
                "--option",
                help="Create or reuse an independent scene of this source; the same name edits that selection",
            )
        if name == "review":
            p.add_argument(
                "--ready-only",
                action="store_true",
                help="Show only candidates with scenario narration and an existing motion preview (or image asset)",
            )
        if name == "import-review":
            p.add_argument(
                "--file",
                help="JSON de decisões; sem esta flag usa o mais recente de brolls/reviews/",
            )
            p.add_argument("--by", required=True, help="Nome de quem revisou e assinou as decisões")
        if name == "approve":
            p.add_argument(
                "--by",
                required=True,
                help="Nome de quem já aprovou explicitamente o trecho",
            )
            p.add_argument(
                "--all",
                action="store_true",
                help=(
                    "Aplicar a mesma aprovação a todo candidato com prévia gerada e sem "
                    "aprovação válida; use só quando todos eles foram mostrados à pessoa"
                ),
            )
            p.add_argument(
                "--channel",
                choices=["chat", "storyboard"],
                default="chat",
                help="Por onde a decisão humana chegou; padrão chat",
            )
            p.add_argument(
                "--statement",
                help="Frase exata dita por quem aprovou, registrada literalmente",
            )
        if name == "permit":
            p.add_argument(
                "--preset",
                choices=sorted(PERMIT_PRESETS),
                help="Condições genéricas da fonte, sempre com o pedido de conferir a página original",
            )
            g = p.add_mutually_exclusive_group()
            g.add_argument("--evidence", help="Evidência real fornecida ou verificada")
            g.add_argument(
                "--declaration",
                action="store_true",
                help="Registrar declaração que o usuário preencheu em RULES.md",
            )
            p.add_argument(
                "--declared-by",
                help="Nome de quem declarou a responsabilidade pelo uso, dito no chat",
            )
            p.add_argument(
                "--declaration-text",
                help="Frase literal da declaração de responsabilidade, com 20 caracteres ou mais",
            )
        if name == "access":
            p.add_argument("--by", required=True, help="Person who explicitly supplied the access decision")
            p.add_argument("--evidence", required=True, help="Actual access decision and conditions already supplied")
        if name == "remember":
            p.add_argument(
                "--decision",
                choices=["approved", "rejected"],
                required=True,
                help="Decisão humana registrada para esta referência",
            )
            p.add_argument("--reason", required=True, help="Motivo real da decisão registrada")
            p.add_argument("--by", required=True, help="Nome de quem decidiu")
        if name == "learn":
            p.add_argument("--query", help="Busca real que você fez, como digitada na fonte")
            p.add_argument("--provider", help="Fonte onde essa busca rodou (exige --query)")
            p.add_argument(
                "--outcome",
                choices=["hit", "miss"],
                help="hit: a busca rendeu material usável; miss: não rendeu (exige --query)",
            )
            p.add_argument("--preference", help="Preferência editorial dita pela pessoa, literal")
            p.add_argument(
                "--from-candidate",
                help="ID do candidato já memorizado com `remember`, guardado como ponteiro",
            )
            p.add_argument("--shot", help="Beat em que esse trecho foi usado")
            p.add_argument("--note", help="Observação livre, gravada em notes/<sha>.md")
            p.add_argument("--by", help="Nome de quem disse a preferência")
        if name == "library":
            p.add_argument(
                "--search",
                required=True,
                help="Termo procurado entre assets, buscas e preferências guardadas",
            )
            p.add_argument(
                "--limit",
                type=int,
                default=5,
                help="Máximo de resultados por tipo, 1–20 (padrão 5)",
            )
        if name == "init-rules":
            p.add_argument(
                "--mode",
                choices=["per_item_evidence", "user_declaration"],
                help="Modo de direitos gravado no bloco JSON; padrão per_item_evidence",
            )
            p.add_argument(
                "--responsible",
                help="Nome de quem assume a responsabilidade no modo user_declaration",
            )
            p.add_argument(
                "--declaration",
                help="Texto literal da declaração de responsabilidade do usuário",
            )
            p.add_argument(
                "--format",
                dest="video_format",
                choices=["native", "reels", "horizontal"],
                help="Formato-alvo gravado em video_format; regravar exige --force",
            )
            p.add_argument(
                "--force",
                action="store_true",
                help="Regravar o RULES.md existente com as escolhas informadas",
            )
        if name == "brief":
            p.add_argument(
                "--validate",
                action="store_true",
                help="Só conferir o BRIEF.md e dizer o que está errado, sem listar comandos",
            )
            p.add_argument(
                "--beat",
                help="Mostrar apenas este beat, pelo id gravado no BRIEF.md",
            )
        if name == "browser-plan":
            p.add_argument("--url", required=True, help="URL pública da página a capturar")
        if name in ("search-browser", "search-import"):
            p.add_argument("--shot", required=True, help="Existing BRIEF fragment ID")
            p.add_argument("--dry-run", action="store_true", help="Validate without reserving or saving results")
            if name == "search-browser":
                p.add_argument(
                    "--query", required=True, help="Meaningful query the managing agent will use in the browser"
                )
                p.add_argument("--language", help="Source query language; does not renew the allowance")
                p.add_argument("--media", choices=("image", "video", "any"), default="any", help="Requested media type")
            else:
                p.add_argument("--attempt", required=True, help="Attempt ID returned by search-browser")
                p.add_argument(
                    "--outcome",
                    required=True,
                    choices=("results", "empty", "access-failure"),
                    help="Actual observed browser outcome",
                )
                p.add_argument(
                    "--results", help="Private JSON file containing one to fifty observed public result rows"
                )
                p.add_argument(
                    "--assessment", required=True, help="What the browser search established and its limitations"
                )
                p.add_argument(
                    "--coverage", choices=("incomplete", "assessed"), help="Coverage of returned or empty results"
                )
        if name in ("search-plan", "search-assess"):
            p.add_argument("--shot", required=True, help="Existing BRIEF fragment ID")
            if name == "search-plan":
                p.add_argument(
                    "--provider",
                    action="append",
                    help="Catalog in this ordered chain. Repeat once per catalog, from one to five",
                )
                p.add_argument(
                    "--reason",
                    action="append",
                    help="Why this catalog belongs, in the same order. Also the advance or shortfall explanation",
                )
                p.add_argument(
                    "--expected-material",
                    action="append",
                    help="Material expected in this catalog, in the same order",
                )
                p.add_argument(
                    "--pass",
                    dest="search_pass",
                    type=int,
                    choices=(1, 2),
                    help="Pass 1 is the initial chain. Pass 2 is the one additional chain of other catalogs",
                )
                p.add_argument(
                    "--advance",
                    action="store_true",
                    help="Close the named current catalog and keep its attempts, options, and allowance",
                )
                p.add_argument(
                    "--because",
                    choices=(
                        "allowance-exhausted",
                        "unavailable-access",
                        "unsuitable-source",
                        "route-unimplemented",
                    ),
                    help="Why the current catalog is closed: allowance, access, unsuitable source, or unimplemented route",
                )
                p.add_argument(
                    "--no-further-catalog",
                    action="store_true",
                    help="Record that no other suitable catalog remains. This does not prove footage is missing",
                )
                p.add_argument("--dry-run", action="store_true", help="Validate and show the plan without saving it")
            else:
                p.add_argument(
                    "--media",
                    choices=("image", "video", "any"),
                    default=None,
                    help="Recorded media filter when the same wording was used more than once",
                )
                p.add_argument(
                    "--provider",
                    help="Catalog when the same wording was recorded on more than one catalog",
                )
                p.add_argument(
                    "--coverage",
                    choices=("incomplete", "assessed"),
                    help="incomplete: the results do not cover the needed dates or collections",
                )
                p.add_argument("--query", required=True, help="Query wording of the recorded attempt")
                p.add_argument(
                    "--catalog-filter",
                    action="append",
                    default=None,
                    metavar="KEY=VALUE",
                    help="Recorded filters when identical wording/media had different catalog filters",
                )
                p.add_argument(
                    "--assessment", required=True, help="What the returned results established and what to inspect next"
                )
        if name == "search-confirm":
            p.add_argument("--shot", required=True, help="Existing BRIEF fragment ID")
            p.add_argument("--candidate", required=True, help="Candidate whose material or preview was actually viewed")
            p.add_argument(
                "--viewed",
                required=True,
                choices=("preview", "material"),
                help="preview: a generated preview file; material: the acquired representation",
            )
            p.add_argument(
                "--preview",
                choices=("gif", "contact-sheet", "poster"),
                help="Generated preview you opened. Required with --viewed preview; not a disk path",
            )
            p.add_argument("--observation", required=True, help="What is visible in the viewed preview or material")
            p.add_argument("--match", required=True, help="Why the viewed material matches or misses the fragment")
            p.add_argument(
                "--verdict",
                choices=("suitable", "unsuitable"),
                default="suitable",
                help="suitable counts when distinct and current; unsuitable stays search history",
            )
            p.add_argument(
                "--distinctness",
                help="Why this is a different scene, angle, action, or moment from other options of the same recording",
            )
            p.add_argument(
                "--duplicate-of",
                help="Another fragment candidate that is a repost, near-identical trim, or the same shot",
            )
        if name == "search":
            p.add_argument(
                "--resume-history",
                action="store_true",
                help="Continue the same Telegram query from its saved cursor; increase --limit to request more attachments. Does not renew an attempt",
            )
            p.add_argument(
                "--planned",
                action="store_true",
                help="Use the saved fragment chain and the current catalog's three-query allowance",
            )
            p.add_argument("--language", help="Agent-selected source query language; does not renew the allowance")
            p.add_argument(
                "--provider",
                default="auto",
                help="Catalog source or auto (default); Mapillary requires bbox, Telegram requires a public whitelist and date range",
            )
            p.add_argument("--query", required=True, help="Termos da busca na fonte")
            p.add_argument(
                "--catalog-filter",
                action="append",
                default=[],
                metavar="KEY=VALUE",
                help="Catalog-specific filter; repeat for different fields. Filters share the planned query allowance.",
            )
            p.add_argument("--limit", type=int, default=8, help="Máximo de candidatos, 1–50 (padrão 8)")
            p.add_argument(
                "--intent",
                choices=["literal", "illustrative"],
                default="literal",
                help="literal: entidade nomeada; illustrative: ideia genérica",
            )
            p.add_argument(
                "--media",
                choices=["image", "video", "any"],
                default="any",
                help="Source media type: image, video, or any (default); public catalog adapters support both",
            )
            p.add_argument(
                "--shot",
                help="Beat do BRIEF.md a que estes candidatos pertencem, ex.: abertura",
            )
            p.add_argument(
                "--dry-run",
                action="store_true",
                help="Listar o que a fonte devolveu sem registrar nada no projeto",
            )
        if name == "reject":
            p.add_argument(
                "--reason",
                help="Por que este material foi descartado; fica gravado no candidato",
            )
        if name == "resolve":
            p.add_argument(
                "--original-for",
                help="UN, Destockd, GDELT, X or LoC locator, Europeana record or Instagram Reel linked to this supplied original",
            )
            p.add_argument(
                "--original-conditions",
                help="Observed supplied-original conditions; records context without granting rights",
            )
            p.add_argument(
                "--locator-metadata",
                help="Public observed UN/Destockd/LoC card metadata JSON; imports a known locator without a search",
            )
            p.add_argument(
                "--catalog-file", help="Actual file URL or NARA object ID in a multi-resource catalog record"
            )
            p.add_argument(
                "--archive-file", help="Actual file name within the Archive.org item (required for multi-asset items)"
            )
            p.add_argument("--context-image", help="Print opcional da pessoa; permanece estático")
            p.add_argument(
                "--full-preview-file",
                help="Composição pronta contendo apenas este insert, usada em GB_GIF_SCOPE=full",
            )
            p.add_argument(
                "--asset-type",
                choices=["video", "image", "news_screenshot", "web_screenshot"],
                help="Tipo do arquivo local; padrão é inferido pela extensão",
            )
            p.add_argument("--title", help="Título do asset/notícia")
            p.add_argument("--captured-at", help="Data da captura, ISO 8601")
            p.add_argument("--source-url", help="URL pública original do arquivo local")
            p.add_argument("--creator", help="Autor informado da fonte")
            p.add_argument("--shot", help="Identificador único do insert, ex.: insert-02")
            p.add_argument(
                "--intent",
                choices=["literal", "illustrative"],
                default="literal",
                help="literal: entidade nomeada; illustrative: ideia genérica",
            )
            g = p.add_mutually_exclusive_group(required=True)
            g.add_argument(
                "--url",
                help="Public source URL (YouTube, Instagram, TikTok, Commons, NASA, Archive.org, LoC, DVIDS, Europeana, NARA, EC, UN, Destockd)",
            )
            g.add_argument("--file", help="Arquivo local já autorizado para importação")
            g.add_argument("--un-asset-id", help="Observed UN Audiovisual Library Asset ID; imports a request locator")
        if name == "graphics-style":
            p.add_argument(
                "--family",
                default="documentary",
                choices=["documentary"],
                help="Proposed visual family; only documentary is available in this slice",
            )
            p.add_argument("--note", help="Original note recorded with this style revision; history is appended")
            p.add_argument(
                "--confirm-fps",
                type=float,
                help="Editing fps for this project; required when collection records already exist, never inferred from footage",
            )
        if name == "graphics-assign":
            p.add_argument(
                "--scene",
                required=True,
                help="Authored scene identity; distinct numeric concepts are distinct scenes and may recur across occurrences",
            )
            p.add_argument(
                "--template",
                default="numeric-stat",
                choices=["numeric-stat", "timeline", "map", "custom"],
                help="Composition independent of --scene: numeric-stat, timeline, map, or one editable custom JSX scene",
            )
            p.add_argument(
                "--replace-template",
                action="store_true",
                help="Explicitly change this occurrence's composition; retain frozen versions and require new content/approval",
            )
            p.add_argument(
                "--occurrence", required=True, help="Stable occurrence id, 1–80 letters, numbers, hyphen or underscore"
            )
            p.add_argument("--chapter", required=True, help="Chapter identifier retained with the assignment")
            p.add_argument(
                "--chapter-context",
                required=True,
                help="Surrounding chapter text from the scenario, not only a chapter identifier",
            )
            p.add_argument("--purpose", required=True, help="Visual purpose of this occurrence")
            p.add_argument("--narration", required=True, help="Original scenario narration for this occurrence")
            p.add_argument(
                "--timing",
                required=True,
                choices=["estimated", "explicit"],
                help="estimated records duration only; explicit requires narration-clock --start/--end",
            )
            p.add_argument("--duration", type=float, help="Estimated duration in seconds; omit --start/--end")
            p.add_argument("--start", type=float, help="Explicit narration-clock start in seconds")
            p.add_argument("--end", type=float, help="Explicit narration-clock end in seconds")
            p.add_argument("--anchor", action="append", help="Original scenario anchor; repeat as needed")
            p.add_argument("--question", action="append", help="Unresolved question retained with the assignment")
            p.add_argument("--propose-scene", action="append", help="Additional scene proposal text")
            p.add_argument("--asset-ref", action="append", help="Existing project-relative previews/ or clips/ asset")
            p.add_argument(
                "--evidence-ref", action="append", help="Existing project-relative previews/ or clips/ evidence"
            )
            p.add_argument(
                "--material-use",
                action="append",
                help=(
                    "JSON object binding one --asset-ref/--evidence-ref: rendered_use is finished-clip "
                    "appearance (permitted|restricted|unknown); raw_redistribution is whether original "
                    "bytes may be copied into the delivery package. Include evidence, conditions, optional "
                    "sha256 (must match the confined bytes) and optional candidate_id. Path presence is "
                    "not permission; stale candidate approval/signature or unavailable acquisition cannot "
                    "be overridden. Repeat as needed."
                ),
            )
            p.add_argument(
                "--confirm-fps",
                type=float,
                help="Editing fps for this project; required when collection records already exist, never inferred from footage",
            )
            p.add_argument("--value", help="Displayed numeric value; synthetic placeholder if omitted")
            p.add_argument("--unit", help="Displayed unit, kept on a separate row from the number")
            p.add_argument("--label", help="Editorial label shown above the number")
            p.add_argument(
                "--claim-status",
                choices=["synthetic", "unverified_scenario"],
                help="synthetic draft or unverified scenario claim; not researched fact",
            )
        if name == "graphics-render":
            p.add_argument(
                "--occurrence", required=True, help="Occurrence id previously registered with graphics-assign"
            )
            p.add_argument(
                "--repair",
                action="store_true",
                help="Consume one of at most two saved scene-code repair attempts after a failed render",
            )
        if name == "graphics-continue":
            continuation = p.add_mutually_exclusive_group()
            continuation.add_argument(
                "--occurrence",
                help="Continue only this occurrence; omit to inspect and continue all assignments sequentially",
            )
            continuation.add_argument(
                "--request",
                help="Resume this exact saved reference request or its fixed shared targets, reusing intact completed results",
            )
        if name == "graphics-checkpoint":
            p.add_argument(
                "--occurrence", required=True, help="Occurrence id whose actual work or pending question is saved"
            )
            p.add_argument(
                "--stage",
                required=True,
                choices=["research", "authoring", "waiting", "error"],
                help="Actual work stage; saving a checkpoint does not declare a finished render",
            )
            p.add_argument("--outcome", required=True, help="Actual saved work or pending question; not an approval")
            p.add_argument("--ref", action="append", help="Existing confined graphics-data/, previews/ or clips/ file")
        if name == "graphics-handoff":
            p.add_argument("--occurrence", required=True, help="One occurrence delegated or restored by the agent host")
            p.add_argument(
                "--host-context", help="Actual observed scene-specific host context id; omit for reconstruction"
            )
            p.add_argument("--request", help="Exact unprocessed revision request id already authorized in chat")
        if name == "graphics-content":
            p.add_argument("--occurrence", required=True, help="Assigned map or custom occurrence id")
            p.add_argument("--file", required=True, help="Project-local bounded JSON identifying editable scene inputs")
        if name == "graphics-timeline":
            p.add_argument(
                "--occurrence", required=True, help="Assigned timeline occurrence id receiving these milestones"
            )
            p.add_argument(
                "--file", required=True, help="Project-local bounded JSON with title and milestone evidence/times"
            )
        if name == "graphics-approve":
            p.add_argument("--occurrence", required=True, help="Occurrence id of the version being approved")
            p.add_argument("--version", required=True, help="Complete version id, for example v1")
            p.add_argument("--by", required=True, help="Name of the person who already approved this version")
            p.add_argument(
                "--statement",
                required=True,
                help="Exact human approval statement; required, channel is always chat",
            )
        if name == "graphics-select":
            p.add_argument("--occurrence", required=True, help="Occurrence id whose retained version is selected")
            p.add_argument("--version", required=True, help="Existing complete version id to select")
        if name == "graphics-reference-apply":
            p.add_argument("--request", required=True, help="Saved reference request id")
            analysis = p.add_mutually_exclusive_group(required=True)
            analysis.add_argument(
                "--analysis",
                help="Actual still-image analysis, or effective instructions reusing intact earlier analyses",
            )
            analysis.add_argument(
                "--file", help="JSON analyses per reference label, plus optional explicit composition"
            )
        if name == "graphics-reference-inspect":
            p.add_argument("--request", required=True, help="Saved reference request id")
            p.add_argument("--label", required=True, help="Video reference label, for example R2")
            p.add_argument(
                "--wording", required=True, help="Exact original interval or whole-clip wording from the prompt"
            )
            p.add_argument("--whole", action="store_true", help="Inspect the explicitly requested whole video")
            p.add_argument("--start", type=float, help="Resolved start in original source seconds")
            p.add_argument("--end", type=float, help="Resolved end in original source seconds")
            p.add_argument("--frames", type=int, default=12, help="Temporal samples, 3–24 (default 12)")
        if name == "graphics-reference-scope":
            p.add_argument("--request", required=True, help="Saved shared reference request id")
            p.add_argument(
                "--file",
                required=True,
                help="JSON resolution and concrete targets with occurrence_id, references and instruction",
            )
        if name == "graphics-request-complete":
            p.add_argument("--request", required=True, help="Saved revision-request id from status.graphics or review")
            p.add_argument("--version", required=True, help="Complete descendant version produced for that request")
            p.add_argument(
                "--outcome", required=True, help="Actual processing outcome recorded after chat authorization"
            )
        if name == "graphics-facts":
            p.add_argument(
                "--occurrence", required=True, help="Occurrence id previously registered with graphics-assign"
            )
            p.add_argument(
                "--file",
                required=True,
                help="Bounded project JSON object with displayed values, sources and optional conflicts",
            )
        if name == "graphics-fact-resolve":
            p.add_argument("--occurrence", required=True, help="Occurrence id that already has saved fact evidence")
            p.add_argument("--conflict", required=True, help="Saved conflict id from that occurrence's facts record")
            p.add_argument(
                "--decision",
                required=True,
                choices=["accept_correction", "keep_scenario", "defer"],
                help="Already received editorial choice; this command records it and does not invent a decision",
            )
            p.add_argument("--by", required=True, help="Name of the person who already made this decision")
            p.add_argument(
                "--statement",
                required=True,
                help="Exact editorial statement already received; original narration is not rewritten",
            )
        if name == "graphics-audio":
            p.add_argument(
                "--occurrence", required=True, help="Occurrence id previously registered with graphics-assign"
            )
            p.add_argument(
                "--file",
                required=True,
                help="Bounded project JSON object with confined effect cues and optional VO source clocks",
            )
        if name == "graphics-sound-import":
            p.add_argument(
                "--sfx",
                required=True,
                choices=["whip", "whoosh", "uiSwitch"],
                help="Named permitted CC0 effect to reuse or materialize locally",
            )
            p.add_argument("--asset", required=True, help="Safe local identity for the saved project sound")
        if name == "narration-analyze":
            p.add_argument("--retry-of", help="Prepare one deliberate retry of this unknown analysis without a handle")
            p.add_argument("--confirm-retry", help="Confirm the exact retry fingerprint printed by preparation")
            p.add_argument("--by", help="Reviewer who explicitly authorized this separate potentially billable retry")
            p.add_argument(
                "--statement", help="Exact authorization acknowledging that the earlier request may be charged"
            )
            p.add_argument(
                "--sync",
                action="store_true",
                help="Use synchronous Inworld STT for a complete recording up to 8 MiB; no polling or automatic fallback",
            )
            p.add_argument(
                "--recording",
                required=True,
                help="Local complete voice-over file; headered supported audio, validated before any provider call",
            )
            p.add_argument(
                "--language",
                help="Optional language hint for Inworld transcribeConfig; omitted uses the provider default",
            )
            p.add_argument(
                "--analysis",
                help="Saved or new analysis identity; omitted assigns na-N. Unchanged completed results are reused",
            )
        if name == "narration-resume":
            p.add_argument(
                "--analysis",
                required=True,
                help="Saved analysis identity from narration-analyze or status.narration",
            )
        if name == "graphics-background":
            p.add_argument(
                "--occurrence", required=True, help="Occurrence id previously registered with graphics-assign"
            )
            p.add_argument(
                "--file",
                required=True,
                help="Bounded project JSON object with candidate_id or ref, optional source interval, fit, suitability and material_use",
            )
        if name == "narration-match":
            p.add_argument(
                "--analysis",
                required=True,
                help="Completed analysis identity from narration-analyze; matching does not call the provider",
            )
            p.add_argument(
                "--occurrence",
                action="append",
                help="Occurrence id to match; repeat in explicit narrative order. Omitted matches every assigned occurrence in stored order",
            )
        if name == "graphics-timing-resolve":
            p.add_argument(
                "--occurrence", required=True, help="Occurrence id that already has a saved alignment record"
            )
            p.add_argument(
                "--candidate",
                help="Saved alignment candidate id to confirm; mutually exclusive with --start/--end",
            )
            p.add_argument("--start", type=float, help="Explicit narration-clock start in seconds")
            p.add_argument("--end", type=float, help="Explicit narration-clock end in seconds")
            p.add_argument(
                "--by",
                required=True,
                help="Name of the person who already confirmed or corrected this interval",
            )
            p.add_argument(
                "--statement",
                required=True,
                help="Exact human correction statement already received; does not invent timing approval",
            )
        if name == "ai-plan":
            p.add_argument(
                "--file",
                required=True,
                help="JSON object with original scenario, agreed AI visual style and routed narrative beats",
            )
        if name == "ai-select":
            p.add_argument("--beat", required=True, help="AI beat id from ai-plan")
            p.add_argument("--alternative", help="One of the three saved scene alternative ids")
            p.add_argument(
                "--comment",
                help="Optional direction for the selected alternative; does not launch generation",
            )
            p.add_argument(
                "--mode",
                choices=["economy", "images"],
                help="Scene comparison mode; economy is the default and generates one still; images mode does not generate until an explicit three-output launch",
            )
            p.add_argument("--expected", help="Saved beat fingerprint; refuse if the scenario or style changed")
        if name == "ai-generate-still":
            p.add_argument(
                "--route",
                choices=["gpt-subscription", "grok-subscription"],
                help="Subscription still route; defaults to project setup or GPT",
            )
            p.add_argument("--model", help="Explicit native image model for the Grok OAuth route")
            p.add_argument(
                "--beat",
                required=True,
                help="AI beat id whose selected alternative will generate one still",
            )
            p.add_argument(
                "--request-id",
                required=True,
                help="Stable request identity for this launch; a repeated identical click reuses the saved job",
            )
            p.add_argument("--expected", help="Saved beat fingerprint; refuse if the scenario or style changed")
        if name == "ai-generate-comparison":
            p.add_argument("--beat", required=True, help="AI beat id already switched to images mode")
            p.add_argument(
                "--request-id",
                required=True,
                help="Stable identity for this three-still launch; a repeated identical request reuses the saved jobs",
            )
            p.add_argument("--expected", help="Saved beat fingerprint; refuse if the scenario or style changed")
        if name == "ai-material-use":
            p.add_argument("--version", required=True, help="Exact saved AI video or sequence version")
            p.add_argument("--signature", required=True, help="Displayed immutable version signature")
            p.add_argument(
                "--state",
                required=True,
                choices=["permitted", "blocked", "unresolved"],
                help="Explicit material-use declaration for this exact version; independent of editorial approval",
            )
            p.add_argument("--by", required=True, help="Responsible editor")
            p.add_argument("--conditions", required=True, help="Conditions covering generated output and guided inputs")
            p.add_argument(
                "--evidence", required=True, help="Basis for this declaration; reference access is not a reuse license"
            )
        if name == "ai-approve":
            p.add_argument(
                "--version",
                required=True,
                help="Saved AI still version id from status.ai or the Storyboard",
            )
            p.add_argument("--by", required=True, help="Name of the person who reviewed this exact still")
            p.add_argument(
                "--decision",
                required=True,
                choices=["approved", "changes", "rejected"],
                help="Explicit human decision for the displayed still; selecting a description is not approval",
            )
            p.add_argument("--comment", help="Optional review comment bound to this exact version")
            p.add_argument("--signature", help="Displayed version signature; refuse if the still changed")
        if name == "ai-timing":
            p.add_argument("--beat", required=True, help="AI beat id from ai-plan")
            p.add_argument(
                "--analysis",
                required=True,
                help="Completed narration analysis id; matching does not transcribe or generate",
            )
            p.add_argument(
                "--still",
                help="Optional saved still version id to bind; omitted leaves the still unbound",
            )
            p.add_argument("--expected", help="Saved beat fingerprint; refuse if the scenario or style changed")
        if name == "ai-timing-resolve":
            p.add_argument("--beat", required=True, help="AI beat id that already has a saved narration match")
            p.add_argument("--analysis", required=True, help="Same completed analysis id used by ai-timing")
            p.add_argument("--by", required=True, help="Name of the person who confirmed this exact interval")
            p.add_argument(
                "--statement",
                required=True,
                help="Exact correction statement already received; does not pick the first candidate",
            )
            p.add_argument(
                "--candidate",
                help="Saved candidate id to confirm; mutually exclusive with --start and --end",
            )
            p.add_argument("--start", type=float, help="Explicit narration-clock start in seconds")
            p.add_argument("--end", type=float, help="Explicit narration-clock end in seconds")
            p.add_argument("--expected", help="Saved beat fingerprint; refuse if the scenario or style changed")
        if name == "ai-generate-video":
            p.add_argument("--beat", required=True, help="AI beat id with a resolved recorded interval")
            p.add_argument("--version", required=True, help="Exact approved still version id; video uses those bytes")
            p.add_argument(
                "--request-id",
                required=True,
                help="Stable request identity; a repeated identical launch reuses the saved job",
            )
            p.add_argument("--model", required=True, help="Native model name to freeze; the launch will not choose one")
            p.add_argument(
                "--tool",
                choices=["reference_to_video", "image_to_video"],
                default="reference_to_video",
                help="Frozen native video tool",
            )
            p.add_argument(
                "--resolution",
                choices=["480p", "720p"],
                default="480p",
                help="Native resolution; 480p and 720p are not Full HD",
            )
            p.add_argument("--speech", action="store_true", help="Explicitly allow speech; omitted means no speech")
            p.add_argument("--music", action="store_true", help="Explicitly allow music; omitted means no music")
            p.add_argument(
                "--atmosphere",
                action="store_true",
                help="Explicitly allow atmosphere, separate from project narration",
            )
            p.add_argument(
                "--effects",
                action="store_true",
                help="Explicitly allow effects, separate from project narration",
            )
            p.add_argument("--expected", help="Saved beat fingerprint; refuse if the scenario or style changed")
        if name == "ai-resume":
            p.add_argument("--job", required=True, help="Saved AI job id; unknown submissions are not sent again")
    return parser


def parse_args(argv=None):
    return build_parser().parse_args(argv)


def _given_option_names(argv, args):
    """Names of the options passed, never their values (values can be URLs or free text).

    A token only counts when the parsed namespace has that option: a free-text value
    that happens to start with `--` must not reach the log as if it were a flag name.
    """
    names = []
    for token in argv:
        if not token.startswith("--"):
            continue
        name = token[2:].split("=", 1)[0]
        if hasattr(args, name.replace("-", "_")) and name not in names:
            names.append(name)
    return ",".join(names) if names else None


def main(argv=None):
    from .commands import execute, with_summary
    from .config import load_env

    args = parse_args(argv)
    if args.command == "serve" and not (args.background or args.stop):
        # `serve` blocks in serve_forever() and owns its own stdout contract (one JSON
        # line with the URLs, printed by serve.run() itself, then nothing else): it does
        # not go through the JSON-wrapping in entrypoint(), so it exits directly here.
        try:
            raise SystemExit(execute(args))
        except ValueError as exc:
            print(json.dumps({"error": str(exc), "error_code": "INVALID_DATA"}, ensure_ascii=False))
            raise SystemExit(EXIT_OPERATION_ERROR) from None

    project = getattr(args, "project", None)
    read_only = args.command in READ_ONLY_COMMANDS or (args.command, getattr(args, "action", None)) in READ_ONLY_ACTIONS
    # GB_LOG_LEVEL/GB_LOG_STDERR may live only in .env; load it before configuring
    # logging. Harmless to call again inside execute() (setdefault-based); a bad
    # .env here is silently skipped and raised properly by execute() itself.
    with contextlib.suppress(ValueError):
        load_env(args.env_file or Path(__file__).resolve().parents[2] / ".env")
    logs.configure(project, read_only=read_only)

    try:
        log = logs.get("cli")
        logs.event(
            log,
            logging.INFO,
            "command_start",
            command=args.command,
            read_only=read_only,
            options=_given_option_names(sys.argv[1:] if argv is None else argv, args),
        )
        started = time.monotonic()
        try:
            result = audited(args, lambda parsed: with_summary(parsed.command, execute(parsed)))
            if isinstance(result, dict) and result.get("ai_dispatch"):
                from .ai import dispatch_after_audit

                result = dispatch_after_audit(result)
        except OperationError as exc:
            logs.event(
                log,
                logging.INFO,
                "command_end",
                command=args.command,
                status="error",
                error_code=exc.payload.get("error_code"),
                ms=round((time.monotonic() - started) * 1000),
            )
            raise
        logs.event(
            log,
            logging.INFO,
            "command_end",
            command=args.command,
            status="ok",
            error_code=None,
            ms=round((time.monotonic() - started) * 1000),
        )
        return result
    finally:
        logs.shutdown()


def entrypoint():
    for stream in (sys.stdout, sys.stderr):
        # TextIO não declara `reconfigure`; quem não tiver cai no except.
        with contextlib.suppress(AttributeError, OSError):
            stream.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]
    try:
        print(json.dumps(main(), ensure_ascii=False, indent=2))
        return 0
    except OperationError as exc:
        print(
            json.dumps({"error": str(exc), **exc.payload}, ensure_ascii=False),
            file=sys.stderr,
        )
        return EXIT_OPERATION_ERROR
    except BrokenPipeError:
        # The consumer end of a pipe (e.g. `| head`) closed early; this is an ordinary,
        # expected shutdown, not a bug — do not report it as INTERNAL_ERROR.
        with contextlib.suppress(Exception):
            sys.stdout.close()
        return 0
    except Exception as exc:  # noqa: BLE001 - last-resort CLI boundary, must exit as JSON not a raw traceback
        # Anything audited() didn't already turn into an OperationError (e.g. an argparse-time
        # bug) must still exit as JSON, not a raw traceback breaking the CLI's output contract.
        from .runtime import redact, scrub_home, write_diagnostics_log

        project = _project_from_argv()
        event = {
            "operation": None,
            "status": "error",
            "error_code": "INTERNAL_ERROR",
            "type": type(exc).__name__,
            "repr": scrub_home(redact(repr(exc))),
            "traceback": scrub_home(redact(traceback.format_exc())),
        }
        log = write_diagnostics_log(project, event) if project else None
        message = "Erro interno inesperado."
        if log:
            message += f" Detalhes em {log} (diagnostics.jsonl)."
        else:
            message += " Consulte diagnostics.jsonl no projeto (--project), se disponível."
        print(
            json.dumps(
                {
                    "error": message,
                    "error_code": "INTERNAL_ERROR",
                    "type": type(exc).__name__,
                    "message": redact(repr(exc)),
                    "traceback": event["traceback"],
                    "app_log": str(logs.log_path(project)) if logs.log_path(project) else None,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return EXIT_INTERNAL_ERROR


def _project_from_argv():
    """Best-effort --project value from sys.argv, for diagnostics logging before/around parse_args."""
    argv = sys.argv[1:]
    if "--project" in argv:
        index = argv.index("--project")
        if index + 1 < len(argv):
            return argv[index + 1]
    for item in argv:
        if item.startswith("--project="):
            return item.split("=", 1)[1]
    return None
