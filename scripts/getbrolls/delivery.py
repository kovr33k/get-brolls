"""`entrega/`: a mesma coleta, organizada por beat, em nomes que uma pessoa lê.

`brolls/` continua canônico — nada aqui apaga, renomeia ou move o que está lá. Esta
camada é derivada e regenerável: cada arquivo de `clips/` aparece em `entrega/` por
hardlink (ou symlink, ou cópia, nessa ordem), com o contact sheet ao lado e um
`ORIGEM.md` dizendo de onde veio. Rodar de novo não estraga nada, e um arquivo que a
pessoa editou à mão nunca é sobrescrito: o comando termina o trabalho e então falha
nomeando todos os arquivos em conflito.

Hardlink é o padrão porque vídeo pesa e duas cópias de cada corte dobram o projeto —
mas hardlink é o *mesmo* arquivo, com dois nomes: editar em `entrega/` editaria o
original em `brolls/clips/`. Por isso a mídia entregue nasce somente-leitura (a
proteção vale para o inode compartilhado, e nenhum comando reescreve esse arquivo no
lugar: `fetch` grava um `-r<N>` novo e `verify` só lê) e tanto o `README.md` quanto o
`ORIGEM.md` dizem isso em uma frase. Quem quiser editar dentro de `entrega/` define
`GB_DELIVERY_COPY=1` e recebe cópias independentes.

`c["delivery"]["path"]` é relativo à **raiz do projeto** (começa em `entrega/`), ao
contrário de `c["output"]["path"]`, que é relativo a `brolls/`.
"""

import hashlib
import json
import logging
import os
import re
import shutil
import stat
import unicodedata
from collections import namedtuple
from datetime import date
from pathlib import Path

from . import logs
from .runtime import record_warning

log = logs.get("delivery")

# Pasta derivada, na raiz do projeto — irmã de `brolls/`, nunca dentro dela.
DELIVERY_DIR = "entrega"
GRAPHICS_DIR = "graphics"
# Onde ficam os trechos coletados que nenhum beat reivindicou.
NO_BEAT = "00-sem-beat"
INDEX = "README.md"
ORIGIN = "ORIGEM.md"
SHEET = "contact-sheet"
# Nome de pasta que ainda cabe num Finder/Explorer sem virar reticências.
MAX_NAME = 60
# Só o que o gerador escreve pode ser apagado quando vira órfão.
GENERATED = re.compile(r"^(ORIGEM(-\d+)?\.md|contact-sheet(-\d+)?\.[a-z0-9]+)$")
BEAT_DIR_RE = re.compile(r"^\d{2}-[a-z0-9-]*$")
# Aviso do ORIGEM.md quando o arquivo é uma cópia independente.
COPY_NOTE = (
    "**Esta é uma cópia independente** (`GB_DELIVERY_COPY`, ou porque o sistema não "
    "deixou criar link): edite à vontade, o original em `brolls/` não é afetado. Rodar "
    "`deliver` de novo não mexe numa cópia que você editou — ele para e diz o nome dela."
)

# Aviso que vai no README.md e em cada ORIGEM.md: hardlink é o mesmo arquivo.
EDIT_WARNING = (
    "**Editar aqui é editar o original.** Estes arquivos são o mesmo arquivo de "
    "`brolls/` com outro nome (hardlink), e por isso vêm marcados como somente-leitura: "
    "copie antes de mexer. Se você quiser editar dentro de `entrega/`, rode o `deliver` "
    "com `GB_DELIVERY_COPY=1` e receba cópias independentes."
)


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def slug(text):
    """Texto humano vira pedaço de caminho: ASCII, minúsculo, só letras/números/hífen."""
    normal = unicodedata.normalize("NFKD", str(text or ""))
    ascii_only = normal.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", ascii_only)).strip("-")


def _safe(value, field):
    """Recusa qualquer coisa que tentaria sair da pasta de entrega."""
    text = str(value or "")
    if ".." in text or "/" in text or "\\" in text or os.sep in text:
        raise ValueError(
            f'Valor inválido para o nome da pasta de entrega ({field}): "{text}". '
            "Ids de beat usam só letras minúsculas, números e hífen; corrija o BRIEF.md "
            "ou o --shot do candidato."
        )
    return text


def beat_dir_name(nn, beat_id, target):
    """`NN-<beat.id>-<slug(alvo)>`: estável entre execuções e seguro como caminho."""
    _safe(beat_id, "id do beat")
    _safe(target, "alvo do beat")
    prefix = f"{int(nn):02d}"
    parts = [prefix, slug(beat_id), slug(target)]
    name = "-".join(p for p in parts if p)
    name = re.sub(r"-+", "-", name).strip("-")[:MAX_NAME].rstrip("-")
    if not name or name in (".", "..") or not BEAT_DIR_RE.match(name):
        raise ValueError(
            f'Não consegui montar um nome de pasta seguro para o beat "{beat_id}". '
            "Use um id com letras minúsculas, números e hífen."
        )
    return name


class _CompareError(Exception):
    """Raised when a comparison could not complete because of an OSError.

    Kept distinct from a real content difference: `link_or_copy` must never report
    "parece edição sua" when it simply failed to read one of the two files.
    """


def _same_file(a, b):
    try:
        return os.path.samestat(Path(a).stat(), Path(b).stat())
    except OSError as exc:
        raise _CompareError(str(exc)) from exc


def _same_bytes(a, b, block=1024 * 1024):
    """Compara em blocos, nunca carregando um vídeo inteiro na memória."""
    try:
        if Path(a).stat().st_size != Path(b).stat().st_size:
            return False
        with Path(a).open("rb") as left, Path(b).open("rb") as right:
            while True:
                chunk = left.read(block)
                if chunk != right.read(block):
                    return False
                if not chunk:
                    return True
    except OSError as exc:
        raise _CompareError(str(exc)) from exc


def _compared(compare, dest, src):
    """Run one comparison; an I/O failure is reported as such, never as a user edit."""
    try:
        return compare(dest, src)
    except _CompareError as exc:
        raise ValueError(
            f"Não consegui comparar {dest} com o arquivo coletado ({exc}): confira "
            "permissão ou disponibilidade do arquivo e rode `deliver` de novo."
        ) from exc


def copies_forced():
    """`GB_DELIVERY_COPY=1`: cópias independentes para quem quer editar em `entrega/`."""
    return (os.environ.get("GB_DELIVERY_COPY") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _freeze(path, method):
    """Tira a escrita só de quem compartilha bytes com o original.

    Hardlink e symlink são o mesmo arquivo com outro nome: editar ali editaria
    `brolls/`. Uma cópia é independente — congelá-la quebraria a promessa de
    `GB_DELIVERY_COPY=1`, que existe justamente para quem quer editar em `entrega/`.

    Uma falha aqui fica não fatal (o resto da entrega continua), mas nunca some: vai
    para `record_warning`, o mesmo canal de aviso que o resto do projeto usa, para que
    a promessa de "somente-leitura" não fique silenciosamente falsa.
    """
    if method not in ("hardlink", "symlink"):
        return
    try:
        mode = Path(path).stat().st_mode
        Path(path).chmod(mode & ~0o222)
    except OSError as exc:
        record_warning(
            "DELIVERY_FREEZE_FAILED",
            f"Não consegui deixar {path} somente-leitura ({exc}): o arquivo entregue "
            "compartilha o inode com o original em brolls/, mas ficou editável.",
        )


def _thaw_unlink(path):
    """Apaga o que este gerador congelou, inclusive no Windows.

    `_freeze` tira o bit de escrita; no Windows isso vira o atributo somente-leitura
    e `unlink` levanta `PermissionError`. Devolver a escrita antes é o único jeito de
    `deliver` regenerar `entrega/` depois de um beat renomeado.
    """
    path = Path(path)
    try:
        path.unlink()
        return
    except PermissionError:
        pass
    path.chmod(stat.S_IWRITE | stat.S_IREAD)
    path.unlink()


def link_or_copy(src, dest, read_only=False):  # noqa: C901 - existing size; hardlink/reflink/copy fallback ladder across OSes
    """Liga `dest` a `src` pelo jeito mais barato que o sistema aceitar.

    Hardlink primeiro (não ocupa disco e não quebra ao mover a pasta de dentro),
    symlink depois (no Windows pode faltar privilégio) e cópia por último. Devolve o
    método usado. Se `dest` já é o mesmo arquivo, não faz nada; se é um arquivo comum
    com conteúdo diferente, é obra da pessoa e o erro nomeia o arquivo.
    """
    src, dest = Path(src), Path(dest)
    methods = (
        (("copy", shutil.copy2),)
        if copies_forced()
        else (
            ("hardlink", os.link),
            ("symlink", os.symlink),
            ("copy", shutil.copy2),
        )
    )
    if dest.is_symlink():
        try:
            if dest.resolve() == src.resolve():
                return "symlink"
        except OSError:
            pass
        _thaw_unlink(dest)
    elif dest.exists():
        if _compared(_same_file, dest, src):
            if read_only:
                _freeze(dest, "hardlink")
            return "hardlink"
        if _compared(_same_bytes, dest, src):
            return "copy"
        raise ValueError(
            f"{dest} já existe com conteúdo diferente do arquivo coletado: parece edição "
            "sua e eu não sobrescrevo. Renomeie ou apague esse arquivo e rode `deliver` "
            "de novo."
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    for method, make in methods:
        try:
            make(str(src), str(dest))
            if read_only:
                _freeze(dest, method)
            return method
        except (OSError, NotImplementedError, AttributeError):
            if dest.is_symlink() or dest.exists():
                _thaw_unlink(dest)
    raise OSError(
        f"Não consegui ligar nem copiar {src} para {dest}. Confira espaço e permissão de escrita na pasta do projeto."
    )


def _frontmatter(kind, created, tags, updated=None):
    today = date.today().isoformat()  # noqa: DTZ011 - local date in the frontmatter; timezone-aware would shift the day near midnight
    return [
        "---",
        f"type: {kind}",
        "status: current",
        f"created: {created or today}",
        f"updated: {updated or today}",
        f"tags: [{', '.join(tags)}]",
        "---",
        "",
    ]


def _frontmatter_field(path, name):
    try:
        prefix = name + ":"
        for line in path.read_text(encoding="utf-8").splitlines()[:8]:
            if line.startswith(prefix):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return None


def _created_in(path):
    """Preserva o `created` de um arquivo já gerado: repetir não muda o histórico."""
    return _frontmatter_field(path, "created")


def _segment_label(c):
    start = (c.get("segment") or {}).get("start_s")
    end = (c.get("segment") or {}).get("end_s")
    if start is None or end is None:
        return "não definido"
    return f"{start:g}s → {end:g}s"


def _author(c):
    """Quem assina a fonte: `creator.name` quando existe, senão o canal/uploader bruto.

    Provedores de vídeo costumam devolver só `channel`/`uploader`; dizer "não
    informado" com o nome do canal na mão esconde crédito que existe.
    """
    for value in (
        (c.get("creator") or {}).get("name"),
        c.get("channel"),
        c.get("uploader"),
        (c.get("media") or {}).get("channel"),
        (c.get("media") or {}).get("uploader"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "não informado"


def render_origin(c, media_name, created=None, method="hardlink"):
    """`ORIGEM.md` do trecho: fonte, autor, intervalo, direitos e sha256 do arquivo."""
    rights = c.get("rights") or {}
    approval = c.get("approval") or {}
    lines = _frontmatter("delivery-origin", created, ["get-brolls", "entrega"])
    lines += [
        f"# Origem de {media_name}",
        "",
        f"- Arquivo: `{media_name}`",
        f"- Candidato: `{c['id']}`",
        f"- Título na fonte: {c.get('title') or 'não informado'}",
        f"- Fonte: {c.get('source_url') or 'original local'}",
        f"- Autor: {_author(c)}",
        f"- Trecho usado: {_segment_label(c)}",
        f"- Direitos: {rights.get('status') or 'unknown'}",
        f"- Licença: {rights.get('license_name') or 'ver evidência'}",
        f"- Licença URL: {rights.get('license_url') or 'não informada'}",
        "- Evidência: " + ("; ".join(rights.get("evidence") or []) or "não registrada"),
        f"- Aprovado por: {approval.get('by') or 'não registrado'}"
        + (f" ({approval.get('channel')})" if approval.get("channel") else ""),
        f"- sha256 do arquivo coletado: `{(c.get('output') or {}).get('sha256') or 'não calculado'}`",
        f"- Original canônico: `brolls/{(c.get('output') or {}).get('path')}`",
        "",
        EDIT_WARNING if method in ("hardlink", "symlink") else COPY_NOTE,
        "",
        (
            "Este arquivo é gerado por `deliver`. A pasta `entrega/` inteira pode ser apagada "
            "e refeita: o que vale é `brolls/`."
        ),
        "",
    ]
    reference = c.get("source_reference") or {}
    if reference:
        lines += [
            "## Archive locator provenance",
            "",
            f"- Locator: {reference.get('source_url')}",
            f"- Locator identity: `{reference.get('provider')}:{reference.get('source_id')}`",
            f"- Observed original interval: {reference.get('source_interval') or 'unknown'}",
            f"- Supplied conditions: {reference.get('conditions') or 'not recorded; rights evidence remains separate'}",
            f"- Acquired item/file: `{c.get('source_id')}` / `{(c.get('archive') or {}).get('selected_file') or 'local original'}`",
            "",
        ]
    return "\n".join(lines)


# Numa entrega misturada (parte link, parte cópia), nenhum aviso global é verdade: um
# diz "editar aqui é editar o original" sobre arquivos que são cópias independentes, o
# outro diz o contrário sobre hardlinks. A resposta vira coluna, linha a linha.
MIXED_NOTE = (
    "**Esta entrega tem os dois casos.** Parte dos arquivos é o mesmo arquivo de "
    "`brolls/` com outro nome (hardlink) e parte é cópia independente — o sistema não "
    "deixou criar link para todos. A coluna **Edição** diz qual é qual: "
    "`original compartilhado` vem somente-leitura e editar ali edita o original "
    "(copie antes de mexer); `editável` você muda à vontade. Para receber tudo como "
    "cópia, rode o `deliver` com `GB_DELIVERY_COPY=1`."
)
# Rótulo por linha quando a entrega é misturada.
EDIT_LABELS = {"copy": "editável", "hardlink": "original compartilhado", "symlink": "original compartilhado"}


def _mixed(rows):
    """A entrega tem cópia e link ao mesmo tempo? Aí nenhum aviso global serve."""
    kinds = {"copy" if row.get("method") == "copy" else "link" for row in rows if row.get("method")}
    return len(kinds) > 1


def _graphics_readme_lines(graphics_rows, graphics_skipped):
    if not (graphics_rows or graphics_skipped):
        return []
    keys = ("scene", "occurrence", "version", "file", "timing", "state")
    lines = [
        "",
        "## Graphics",
        "",
        (
            "Approved Full HD H.264 clips with timing metadata and editable sources. "
            "Narration is not embedded; there is no automatic alpha, master or stem. "
            "The source package is **not self-contained**. Restricted raw assets stay "
            "separately held, including restricted public/audio cue and public/media background bytes reconstructed "
            "with one `--held-ref` original into every frozen destination. Rerun with `python rerender.py --browser-executable <prepared>` "
            "after `npm ci --ignore-scripts` at the package root (or a `node_modules` "
            "junction to a pinned 4.0.534 tree). `python rerender.py --check` validates "
            "paths, object props, browser path, `--held-ref` mappings and installed "
            "package.json versions for every pinned Remotion/React/font dependency without rendering."
        ),
        "",
        "| scene | occurrence | version | file | timing | state |",
        "|---|---|---|---|---|---|",
    ]
    lines.extend(
        "| " + " | ".join(str(row.get(key) or "—").replace("|", "/").replace("\n", " ") for key in keys) + " |"
        for row in graphics_rows
    )
    if not graphics_rows:
        lines.append("| — | — | — | none delivered this run | — | — |")
    if graphics_skipped:
        lines += ["", "Skipped graphics (not delivered; existing valid deliveries were kept):", ""]
        lines.extend(
            f"- `{item.get('scene_id')}/{item.get('occurrence_id')}/{item.get('version') or '—'}`: "
            f"{item.get('reason') or 'not_deliverable'}"
            for item in graphics_skipped
        )
    return lines


def _delivery_index_preamble(rows, created, copies):
    mixed = _mixed(rows)
    columns = ["beat", "narration", "target", "file", "state", "rights"]
    headers = ["Beat", "Narração", "Alvo", "Arquivo", "Estado", "Direitos"]
    if mixed:
        columns.append("edit")
        headers.append("Edição")
    lines = _frontmatter("delivery-index", created, ["get-brolls", "entrega"])
    lines += [
        "# Seus trechos",
        "",
        (
            "Cada pasta é um trecho do vídeo, na ordem do BRIEF.md. É só arrastar o `.mp4` "
            "para o seu editor; o `ORIGEM.md` ao lado diz de onde ele veio e o que você me "
            "disse sobre poder usar."
        ),
        "",
        MIXED_NOTE if mixed else (COPY_NOTE if copies else EDIT_WARNING),
        "",
        "| " + " | ".join(headers) + " |",
        "|" + "---|" * len(headers),
    ]
    for row in rows:
        cells = dict(row)
        if mixed:
            cells["edit"] = EDIT_LABELS.get(row.get("method") or "", "—")
        lines.append(
            "| " + " | ".join(str(cells.get(key) or "—").replace("|", "/").replace("\n", " ") for key in columns) + " |"
        )
    if not rows:
        # A linha vazia sai das mesmas colunas do cabeçalho: contar células à mão
        # deixava a tabela torta (5 células para 6 colunas) em todo projeto sem clipe.
        empty = dict.fromkeys(columns, "—")
        empty["file"] = "nenhum trecho coletado ainda"
        lines.append("| " + " | ".join(empty[key] for key in columns) + " |")
    return lines


def _delivery_index_tail(conflicts, for_human):
    lines = []
    if conflicts:
        lines += [
            "",
            "## Conflitos",
            "",
            (
                "Estes trechos não foram refeitos porque o arquivo em `entrega/` tem conteúdo "
                "diferente do que está em `brolls/` — parece edição sua e eu não sobrescrevo. "
                "Renomeie ou apague o arquivo e rode `deliver` de novo:"
            ),
            "",
        ]
        lines += [f"- `{item}`" for item in conflicts]
    lines += ["", "## Próximo passo", "", for_human or "Nada pendente por aqui.", ""]
    return lines


def render_index(rows, for_human=None, created=None, conflicts=(), copies=False):
    """`entrega/README.md`: a tabela que responde “onde estão meus arquivos”."""
    lines = _delivery_index_preamble(rows, created, copies)
    lines += _delivery_index_tail(conflicts, for_human)
    return "\n".join(lines)


def _brief_beats(project):
    """Beats do BRIEF.md quando ele existe e é válido; lista vazia quando não dá."""
    try:
        from .brief import load_brief, validate_brief

        data, _ = validate_brief(load_brief(project))
        return [b["resolved"] for b in data["beats"]]
    except (ValueError, OSError):
        return []


def _plan(project, items):
    """Um grupo por beat, na ordem do brief; sem brief, na ordem do manifesto.

    Fica de fora quem não tem `output.path`, quem tem a chave `output.verified`
    presente com um valor falso (`False`, `0`, `None` — verificação de sha256 que
    falhou ou nunca rodou) e quem foi rejeitado na aprovação — mesmo que `reject` já
    limpe `output` nesses casos, a checagem aqui é defesa extra. Um item sem a chave
    `verified` (manifesto antigo) segue endereçado normalmente; a mesma regra que
    `STAGE_TESTS["verified"]` usa em `commands.py`.
    """
    collected, skipped = [], []
    for c in items:
        output = c.get("output") or {}
        if not output.get("path"):
            continue
        if "verified" in output and not output["verified"]:
            skipped.append(
                {
                    "id": c["id"],
                    "reason": (
                        "o arquivo em brolls/ não confere mais com o que foi coletado: restaure o "
                        "original, ou apague esse arquivo e rode `fetch` de novo; depois, `verify`."
                    ),
                }
            )
            logs.event(log, logging.INFO, "deliver_skipped", candidate=c["id"], reason="unverified")
            continue
        if (c.get("approval") or {}).get("status") == "rejected":
            skipped.append({"id": c["id"], "reason": "candidato foi rejeitado: não entra na entrega."})
            logs.event(log, logging.INFO, "deliver_skipped", candidate=c["id"], reason="rejected")
            continue
        collected.append(c)
    beats = _brief_beats(project)
    order = [b["id"] for b in beats]
    meta = {b["id"]: b for b in beats}
    for c in collected:
        shot = c.get("shot")
        if shot and shot not in order:
            order.append(shot)
    groups = []
    for position, beat_id in enumerate(order, start=1):
        beat = meta.get(beat_id) or {}
        members = [c for c in collected if c.get("shot") == beat_id]
        if not members:
            continue
        target = beat.get("target") or members[0].get("title") or beat_id
        groups.append(
            {
                "beat": beat_id,
                "narration": beat.get("narration"),
                "target": target,
                "dir": beat_dir_name(position, beat_id, target),
                "items": members,
            }
        )
    orphans = [c for c in collected if not c.get("shot")]
    if orphans:
        groups.append(
            {
                "beat": None,
                "narration": None,
                "target": "trechos sem beat no brief",
                "dir": NO_BEAT,
                "items": orphans,
            }
        )
    return groups, skipped


def _names(group_dir, index, source_suffix, sheet_suffix):
    tail = "" if index == 1 else f"-{index}"
    return {
        "media": f"{group_dir}{tail}{source_suffix}",
        "sheet": f"{SHEET}{tail}{sheet_suffix}",
        "origin": ORIGIN if index == 1 else f"ORIGEM{tail}.md",
    }


def _symlink_targets_brolls(path, brolls_root):
    """Um symlink só é nosso quando aponta para um clipe dentro do `brolls/` deste projeto.

    Um link que a pessoa criou (para a própria mídia, um atalho, outra pasta) não bate
    com isso e não pode ser tratado como órfão do gerador.
    """
    try:
        target = path.resolve()
        brolls_real = Path(brolls_root).resolve()
    except OSError:
        return False
    return target == brolls_real or brolls_real in target.parents


def _ours(rel, path, owned, brolls_root):
    """Só é órfão o que este gerador escreveu; o resto é da pessoa e fica.

    Reconhecemos três assinaturas: um caminho que o próprio manifesto registra em
    `c["delivery"]`, os nomes que o gerador usa (`README.md`, `ORIGEM*.md`,
    `contact-sheet*.*` e a mídia, que repete o nome da pasta do beat) e, só quando o
    nome já bateu com uma dessas assinaturas, um symlink que resolve para dentro de
    `brolls/`. Um bilhete — ou um link — que a pessoa deixou dentro da pasta não casa
    com nada disso e é preservado.

    Files under `graphics/` are never generator-owned by ORIGEM/contact-sheet name
    alone: a later candidate-only deliver must not sweep a retained graphics package.
    """
    if rel in owned or rel == INDEX:
        return True
    if rel.split("/", 1)[0] in {GRAPHICS_DIR, "ai"}:
        return False
    name = path.name
    parent = path.parent.name
    name_matches = bool(GENERATED.match(name)) or (
        bool(BEAT_DIR_RE.match(parent)) and re.fullmatch(re.escape(parent) + r"(-\d+)?\.[A-Za-z0-9]+", name) is not None
    )
    if not name_matches:
        return False
    if path.is_symlink():
        return _symlink_targets_brolls(path, brolls_root)
    return True


def _confined(path, real_root):
    """A exclusão só é segura quando o local real de `path` está dentro de `real_root`.

    `entrega/` em si já foi recusada como symlink em `build_delivery`, mas uma pasta de
    beat marcada à mão como link ainda poderia levar `rglob` para fora do projeto — esta
    checagem confirma o caminho físico antes de qualquer `unlink`/`rmdir`.
    """
    try:
        parent_real = path.parent.resolve()
    except OSError:
        return False
    return parent_real == real_root or real_root in parent_real.parents


_SweepContext = namedtuple("_SweepContext", "expected dry_run owned brolls_root real_root")


def _sweep_empty_directory(path, rel, ctx):
    """One orphaned-beat-directory candidate for `_sweep`: `"removed"`, `"kept"`, or
    `None` (not a candidate at all — same gate `_sweep` used to apply inline).

    A symlinked "directory" needs its own removal path: `rmdir` on a symlink to an
    empty directory raises `NotADirectoryError` on POSIX, and blindly removing it
    could take someone else's folder with it. It is only `unlink()`'d (never
    `rmdir()`'d) when the same rules that already cover a symlinked FILE — `_ours`
    and `_symlink_targets_brolls` — recognize it as this generator's own; otherwise
    it is foreign and stays. A real empty directory that fails to `rmdir`
    (permissions, a race) is left in place and reported as a warning, never an
    aborted delivery.
    """
    if not (
        BEAT_DIR_RE.match(path.name)
        and not any(path.iterdir())
        and rel not in ctx.expected
        and _confined(path, ctx.real_root)
    ):
        return None
    if path.is_symlink():
        if not _ours(rel, path, ctx.owned, ctx.brolls_root):
            return "kept"
        if not ctx.dry_run:
            _thaw_unlink(path)
        return "removed"
    if not ctx.dry_run:
        try:
            path.rmdir()
        except OSError as exc:
            record_warning(
                "DELIVERY_SWEEP_RMDIR_FAILED",
                f"Não consegui apagar a pasta vazia {path} ({exc}); ela continua em entrega/.",
            )
            return None
    return "removed"


def _sweep(root, expected, dry_run, owned=(), brolls_root=None):
    """Apaga só o que este gerador escreveu e que deixou de existir no plano."""
    removed, kept = [], []
    owned = set(owned)
    if not root.is_dir():
        return removed, kept
    ctx = _SweepContext(expected, dry_run, owned, brolls_root, root.resolve())
    for path in sorted(root.rglob("*"), reverse=True):
        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            outcome = _sweep_empty_directory(path, rel, ctx)
            if outcome == "removed":
                removed.append(rel)
            elif outcome == "kept":
                kept.append(rel)
            continue
        if rel in expected:
            continue
        if _ours(rel, path, owned, brolls_root) and _confined(path, ctx.real_root):
            if not dry_run:
                _thaw_unlink(path)
            removed.append(rel)
        else:
            kept.append(rel)
    logs.event(log, logging.INFO, "sweep", removed=len(removed), kept_foreign=len(kept))
    return removed, kept


def _is_link_or_junction(path):
    """True for symlinks and Windows junctions/reparse points that Path.is_symlink misses."""
    path = Path(path)
    try:
        if path.is_symlink():
            return True
    except OSError:
        return True
    if os.name != "nt":
        return False
    try:
        attrs = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _assert_graphics_dest_safe(entrega_root, dest):
    """Refuse symlink/junction destinations and ancestors before any helper writes."""
    entrega_root = Path(entrega_root)
    dest = Path(dest)
    try:
        root_real = entrega_root.resolve()
    except OSError as exc:
        raise ValueError(f"Não consegui resolver a pasta de entrega {entrega_root} ({exc}).") from exc
    cursor = dest
    while True:
        if cursor.exists() or cursor.is_symlink():
            if _is_link_or_junction(cursor):
                raise ValueError(
                    f"{cursor} is a symlink or junction on the graphics delivery path; "
                    "refusing to follow or overwrite it."
                )
            try:
                resolved = cursor.resolve()
            except OSError as exc:
                raise ValueError(f"Não consegui resolver {cursor} no caminho de entrega de gráficos ({exc}).") from exc
            if resolved != root_real and root_real not in resolved.parents:
                raise ValueError(
                    f"{cursor} resolves outside {entrega_root}; graphics delivery will not follow that path."
                )
        if cursor in (entrega_root, root_real):
            break
        if cursor.parent == cursor:
            break
        cursor = cursor.parent


def copy_independent(src, dest):
    """Byte copy for editable graphics sources. Never hardlink: that would mutate frozen originals."""
    src, dest = Path(src), Path(dest)
    if dest.exists() or dest.is_symlink():
        if _is_link_or_junction(dest) or dest.is_dir():
            raise ValueError(f"{dest} is a symlink, junction or directory; graphics delivery will not replace it.")
        if _compared(_same_bytes, dest, src):
            return "copy"
        raise ValueError(
            f"{dest} já existe com conteúdo diferente do arquivo coletado: parece edição "
            "sua e eu não sobrescrevo. Renomeie ou apague esse arquivo e rode `deliver` "
            "de novo."
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return "copy"


def _ancestor_rels(rel):
    parts = [part for part in str(rel).split("/") if part]
    return ["/".join(parts[:index]) for index in range(1, len(parts))]


def graphics_package_rel(scene_id, occurrence_id, version_id):
    _safe(scene_id, "scene_id")
    _safe(occurrence_id, "occurrence_id")
    _safe(version_id, "version_id")
    return f"{GRAPHICS_DIR}/{scene_id}/{occurrence_id}/{version_id}"


def _entrega_rel(project_relative):
    prefix = DELIVERY_DIR + "/"
    if not isinstance(project_relative, str) or not project_relative.startswith(prefix):
        return None
    return project_relative[len(prefix) :]


def _retained_graphics_rels(graphics, folder=GRAPHICS_DIR):
    rels = set()
    versions = graphics.get("versions") if isinstance(graphics, dict) else None
    if not isinstance(versions, dict):
        return rels
    for version in versions.values():
        delivery = version.get("delivery") if isinstance(version, dict) else None
        if not isinstance(delivery, dict):
            continue
        package_rel = _entrega_rel(delivery.get("package_dir"))
        media_rel = _entrega_rel(delivery.get("path"))
        if package_rel:
            rels.add(package_rel)
            rels.update(_ancestor_rels(package_rel))
            for name in delivery.get("files") or {}:
                if isinstance(name, str) and name and ".." not in name.split("/"):
                    file_rel = f"{package_rel}/{name}"
                    rels.add(file_rel)
                    rels.update(_ancestor_rels(file_rel))
        if media_rel:
            rels.add(media_rel)
            rels.update(_ancestor_rels(media_rel))
    if rels:
        rels.add(folder)
    return rels


def _plan_graphics(ledger):
    from .graphics import version_readiness

    eligible, skipped = [], []
    graphics = ledger.data.get("graphics")
    if not isinstance(graphics, dict):
        return eligible, skipped
    versions = _as_dict(graphics.get("versions"))
    items = ledger.data.get("items")
    project_id = ledger.data.get("project_id")
    for occ in (_as_dict(graphics.get("occurrences"))).values():
        if not isinstance(occ, dict):
            continue
        version = versions.get(occ.get("current_version") or "")
        ident = {
            "occurrence_id": occ.get("occurrence_id"),
            "scene_id": occ.get("scene_id"),
            "version": occ.get("current_version"),
        }
        if not isinstance(version, dict) or version.get("status") != "complete":
            skipped.append({**ident, "reason": "incomplete_version", "reasons": ["incomplete_version"]})
            continue
        ident["version"] = version.get("id")
        readiness = version_readiness(ledger.root, version, occ, project_id, items, data=ledger.data)
        if not readiness.get("deliverable"):
            reason = (readiness.get("reasons") or ["not_deliverable"])[0]
            skipped.append({**ident, "reason": reason, "reasons": list(readiness.get("reasons") or [])})
            logs.event(
                log,
                logging.INFO,
                "deliver_graphics_skipped",
                occurrence=ident["occurrence_id"],
                version=ident["version"],
                reason=reason,
            )
            continue
        eligible.append({"occurrence": occ, "version": version, "readiness": readiness})
    return eligible, skipped


def _iso_date(value):
    text = str(value or "")
    match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    if match:
        return match.group(1)
    return date.today().isoformat()  # noqa: DTZ011 - fallback only when approval/version timestamps are absent


def _graphics_origin_dates(version, dest_root):
    origin = Path(dest_root) / ORIGIN if dest_root is not None else None
    if origin is not None and origin.is_file() and not origin.is_symlink():
        created = _created_in(origin)
        updated = _frontmatter_field(origin, "updated")
        if created and updated:
            return created, updated
    approval = _as_dict(version.get("approval"))
    stamp = _iso_date(approval.get("at") or version.get("at"))
    return stamp, stamp


GRAPHICS_RUNTIME_PINS = {
    "remotion": "4.0.534",
    "@remotion/renderer": "4.0.534",
    "@remotion/bundler": "4.0.534",
    "react": "19.3.0",
    "react-dom": "19.3.0",
    "@fontsource/ibm-plex-sans": "5.3.0",
}


RERENDER_ADAPTER = '''#!/usr/bin/env python3
"""Package-local rerender adapter. Frozen originals stay in brolls/graphics/.

This package is not self-contained. It loads props as an object, resolves
entry/publicDir/output relative to THIS package, and invokes the copied worker.
Install the pinned Node/Remotion runtime at this package root with
`npm ci --ignore-scripts`, or junction/symlink ./node_modules to an existing
pinned 4.0.534 tree so inputs/render.mjs and source/*.jsx both resolve
@remotion/* from ./node_modules. Pass --browser-executable to a prepared
browser file; this adapter never downloads a browser. Restricted raw
dependencies in separately-held.json require --held-ref ref=<file> with
matching sha256 bytes; acknowledgement is not the required bytes.
Restricted public/audio cue and public/media background bytes stay out of this package. Matching
--held-ref files are copied into owned temporary render media at every
frozen destination that references those bytes for this process only
and are not written into the package.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent


def _load(name):
    path = PACKAGE / name
    if not path.is_file():
        raise SystemExit("missing " + name)
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _confined(rel, kind):
    dest = (PACKAGE / str(rel or "")).resolve()
    if dest != PACKAGE and PACKAGE not in dest.parents:
        raise SystemExit(kind + " escapes this package: " + str(rel))
    return dest


def _parse_held(values):
    mapping = {}
    for raw in values or []:
        if "=" not in str(raw):
            raise SystemExit("--held-ref requires ref=path for a separately held original.")
        ref, path = str(raw).split("=", 1)
        ref = ref.strip()
        if not ref:
            raise SystemExit("--held-ref is missing the ref path.")
        mapping[ref] = Path(path)
    return mapping


def _posix_rel(value):
    return str(value or "").replace("\\\\", "/").strip("/")


def _load_optional(name):
    path = PACKAGE / name
    if not path.is_file() or path.is_symlink():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None


def _safe_audio_rel(value):
    text = _posix_rel(value)
    prefix = "public/audio/"
    if text.startswith(prefix):
        text = "audio/" + text[len(prefix) :]
    if not text.startswith("audio/"):
        return None
    name = text[len("audio/") :]
    if not name or name in (".", "..") or "/" in name:
        return None
    return "audio/" + name


def _safe_media_rel(value):
    text = _posix_rel(value)
    prefix = "public/media/"
    if text.startswith(prefix):
        text = "media/" + text[len(prefix) :]
    if not text.startswith("media/"):
        return None
    name = text[len("media/") :]
    if not name or name in (".", "..") or "/" in name:
        return None
    return "media/" + name


def _frozen_cue_rel(item):
    if not isinstance(item, dict):
        return None
    frozen = _posix_rel(item.get("frozen_ref"))
    if not frozen.startswith("public/audio/"):
        return None
    return _safe_audio_rel(frozen)


def _frozen_media_rel(item):
    if not isinstance(item, dict):
        return None
    frozen = _posix_rel(item.get("frozen_ref"))
    if not frozen.startswith("public/media/"):
        return None
    return _safe_media_rel(frozen)


def _add_rel(bucket, rel):
    if rel and rel not in bucket:
        bucket.append(rel)


def _reconstruction_rels(held, fingerprints, props):
    by_ref = {}
    for item in held:
        if not isinstance(item, dict):
            continue
        ref = item.get("ref")
        if not isinstance(ref, str) or not ref:
            continue
        bucket = by_ref.setdefault(ref, [])
        _add_rel(bucket, _frozen_cue_rel(item))
        _add_rel(bucket, _frozen_media_rel(item))
        extra = item.get("frozen_refs")
        if isinstance(extra, list):
            for frozen in extra:
                _add_rel(bucket, _safe_audio_rel(frozen))
                _add_rel(bucket, _safe_media_rel(frozen))
    audio = fingerprints.get("audio") if isinstance(fingerprints, dict) else None
    assets = audio.get("assets") if isinstance(audio, dict) else None
    cues = props.get("sound_cues") if isinstance(props, dict) else None
    src_by_id = {}
    if isinstance(cues, list):
        for cue in cues:
            if isinstance(cue, dict) and isinstance(cue.get("id"), str):
                rel = _safe_audio_rel(cue.get("src"))
                if rel:
                    src_by_id[cue["id"]] = rel
    if isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            ref = asset.get("ref")
            if ref not in by_ref:
                continue
            rel = _safe_audio_rel(asset.get("frozen_ref"))
            if rel is None and isinstance(asset.get("id"), str):
                rel = src_by_id.get(asset["id"])
            _add_rel(by_ref[ref], rel)
    background = fingerprints.get("background") if isinstance(fingerprints, dict) else None
    bg_assets = background.get("assets") if isinstance(background, dict) else None
    bg_src = None
    if isinstance(props, dict) and isinstance(props.get("background"), dict):
        bg_src = _safe_media_rel(props.get("background").get("src"))
    if isinstance(bg_assets, list):
        for asset in bg_assets:
            if not isinstance(asset, dict):
                continue
            ref = asset.get("ref")
            if ref not in by_ref:
                continue
            rel = _safe_media_rel(asset.get("frozen_ref"))
            if rel is None:
                rel = bg_src
            _add_rel(by_ref[ref], rel)
    return by_ref


def _cue_gap_errors(props, public_dir, reconstructable):
    errors = []
    cues = props.get("sound_cues") if isinstance(props, dict) else None
    if not isinstance(cues, list):
        return errors
    available = set(reconstructable)
    for cue in cues:
        if not isinstance(cue, dict):
            continue
        src = cue.get("src")
        if src is None or src == "":
            continue
        rel = _safe_audio_rel(src)
        if rel is None:
            errors.append("sound cue src must be audio/<cue-file> for reconstruction: " + str(src))
            continue
        on_disk = public_dir.joinpath(*rel.split("/"))
        if on_disk.is_file() and not on_disk.is_symlink():
            continue
        if rel in available:
            continue
        ident = cue.get("id") or rel
        errors.append(
            "missing cue dependency "
            + str(ident)
            + " ("
            + rel
            + "); pass --held-ref for the separately held original that reconstructs this frozen cue"
        )
    return errors


def _background_gap_errors(props, public_dir, reconstructable):
    errors = []
    background = props.get("background") if isinstance(props, dict) else None
    if not isinstance(background, dict):
        return errors
    src = background.get("src")
    if src is None or src == "":
        return errors
    rel = _safe_media_rel(src)
    if rel is None:
        errors.append("background src must be media/<file> for reconstruction: " + str(src))
        return errors
    on_disk = public_dir.joinpath(*rel.split("/"))
    if on_disk.is_file() and not on_disk.is_symlink():
        return errors
    if rel in reconstructable:
        return errors
    errors.append(
        "missing background dependency ("
        + rel
        + "); pass --held-ref for the separately held original that reconstructs this frozen media"
    )
    return errors


def _copy_regular_tree(src, dest, skip):
    src = Path(src)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for path in src.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(src).as_posix()
        if rel in skip:
            continue
        target = dest.joinpath(*rel.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())


def _stage_held_public(package_public, held, mapping, rels_by_ref):
    placements = []
    skip = set()
    seen = set()
    for item in held:
        if not isinstance(item, dict):
            continue
        ref = item.get("ref")
        src = mapping.get(ref)
        if src is None:
            continue
        dests = list(rels_by_ref.get(ref) or [])
        fallback = _frozen_cue_rel(item) or _frozen_media_rel(item)
        if fallback and fallback not in dests:
            dests.append(fallback)
        for rel in dests:
            key = (rel, ref)
            if not rel or key in seen:
                continue
            seen.add(key)
            placements.append((rel, ref, src, item.get("sha256")))
            skip.add(rel)
    if not placements:
        return package_public, None
    tmp = tempfile.TemporaryDirectory(prefix="gb-held-cues-")
    try:
        staged = Path(tmp.name) / "public"
        if package_public.is_dir():
            _copy_regular_tree(package_public, staged, skip)
        else:
            staged.mkdir(parents=True, exist_ok=True)
        for rel, ref, src, expected in placements:
            dest = staged.joinpath(*rel.split("/"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            candidate = Path(src).expanduser()
            if candidate.is_symlink() or candidate.is_dir():
                raise SystemExit(
                    "--held-ref " + str(ref) + " must be a regular file, not a symlink or directory."
                )
            try:
                real = candidate.resolve()
            except OSError as exc:
                raise SystemExit("--held-ref " + str(ref) + " could not be resolved: " + str(exc)) from exc
            if not real.is_file():
                raise SystemExit("--held-ref " + str(ref) + " is not an existing file: " + str(real))
            data = real.read_bytes()
            actual = hashlib.sha256(data).hexdigest()
            if expected and actual != expected:
                raise SystemExit(
                    "--held-ref "
                    + str(ref)
                    + " sha256 "
                    + actual
                    + " does not match separately-held.json "
                    + str(expected)
                )
            dest.write_bytes(data)
        return staged, tmp
    except BaseException:
        tmp.cleanup()
        raise


def _resolve_browser(path):
    if not path:
        return None
    target = Path(path).expanduser()
    try:
        real = target.resolve()
    except OSError as exc:
        raise SystemExit("browser executable could not be resolved: " + str(exc)) from exc
    if not real.is_file():
        raise SystemExit("browser executable is not an existing file: " + str(real))
    return real


_PINNED_RUNTIME = {
    "remotion": "4.0.534",
    "@remotion/renderer": "4.0.534",
    "@remotion/bundler": "4.0.534",
    "react": "19.3.0",
    "react-dom": "19.3.0",
    "@fontsource/ibm-plex-sans": "5.3.0",
}


def _pin_version(value):
    return str(value or "").strip().lstrip("=^~")


def _installed_version(name):
    manifest = PACKAGE.joinpath("node_modules", *str(name).split("/"), "package.json")
    if not manifest.is_file():
        return "missing"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return "malformed"
    version = _pin_version(data.get("version")) if isinstance(data, dict) else ""
    return version or "malformed"


def _expected_pins(runtime):
    expected = dict(_PINNED_RUNTIME)
    pins = runtime.get("pins") if isinstance(runtime.get("pins"), dict) else {}
    for name, version in pins.items():
        pinned = _pin_version(version)
        if pinned:
            expected[str(name)] = pinned
    extra = []
    manifest_path = PACKAGE / "package.json"
    if not manifest_path.is_file():
        return expected, extra
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        extra.append("package.json is malformed; cannot read pinned dependencies.")
        return expected, extra
    deps = data.get("dependencies") if isinstance(data, dict) else None
    if not isinstance(deps, dict):
        extra.append("package.json dependencies must be an object of pinned package versions.")
        return expected, extra
    for name, version in deps.items():
        name = str(name)
        pinned = _pin_version(version)
        if name in expected and pinned and expected[name] != pinned:
            extra.append("package.json " + name + " expected " + expected[name] + ", actual " + pinned)
            continue
        if pinned:
            expected[name] = pinned
    return expected, extra


def _held_errors(held, mapping):
    errors = []
    seen = set()
    for item in held:
        ref = item.get("ref")
        seen.add(ref)
        src = mapping.get(ref)
        if src is None:
            errors.append(
                "restricted ref "
                + str(ref)
                + " is separately held; pass --held-ref "
                + str(ref)
                + "=<file> with those exact bytes (acknowledgement is not the required bytes)."
            )
            continue
        candidate = src.expanduser()
        if candidate.is_symlink() or candidate.is_dir():
            errors.append("--held-ref " + str(ref) + " must be a regular file, not a symlink or directory.")
            continue
        try:
            real = candidate.resolve()
        except OSError as exc:
            errors.append("--held-ref " + str(ref) + " could not be resolved: " + str(exc))
            continue
        if not real.is_file():
            errors.append("--held-ref " + str(ref) + " is not an existing file: " + str(real))
            continue
        expected = item.get("sha256")
        actual = _digest(real)
        if expected and actual != expected:
            errors.append(
                "--held-ref " + str(ref) + " sha256 " + actual + " does not match separately-held.json " + str(expected)
            )
        if item.get("frozen_ref") is not None and _frozen_cue_rel(item) is None and _frozen_media_rel(item) is None:
            errors.append(
                "separately-held frozen_ref must be public/audio/<cue-file> or public/media/<file> "
                "for reconstruction: " + str(item.get("frozen_ref"))
            )
    extra = [ref for ref in mapping if ref not in seen]
    if extra:
        errors.append("unknown --held-ref not listed in separately-held.json: " + ", ".join(extra))
    return errors


def _runtime_errors(kind, worker_path, browser, runtime):
    errors = []
    installed = {}
    if not worker_path.is_file():
        errors.append("Copied worker is missing: " + str(worker_path))
    if kind != "remotion":
        return errors, {}, installed
    if not (PACKAGE / "package.json").is_file() or not (PACKAGE / "package-lock.json").is_file():
        errors.append(
            "package.json and package-lock.json must sit at this package root (independent copies of the "
            "frozen pinned lock) so `npm ci --ignore-scripts` can install ./node_modules."
        )
    expected, extra = _expected_pins(runtime)
    errors.extend(extra)
    for name, wanted in expected.items():
        actual = _installed_version(name)
        installed[name] = actual
        if actual != wanted:
            errors.append(
                name
                + " expected "
                + wanted
                + ", actual "
                + actual
                + ". Directory presence is not enough; read installed package.json. "
                "From this directory run `npm ci --ignore-scripts`, or junction/symlink node_modules "
                "to an existing tree that already has these exact versions. Do not copy browser binaries."
            )
    if browser is None:
        errors.append(
            "Remotion rerender needs --browser-executable <prepared-browser-file>; the copied worker will "
            "not download a browser."
        )
    return errors, expected, installed


def _preflight(config, props, held, held_map, browser, output):
    errors = []
    if not isinstance(props, dict):
        errors.append("props.json must be a JSON object; frozen render.mjs consumes props as an object.")
    if not isinstance(held, list):
        errors.append("separately-held.json must be a JSON array.")
        held = []
    entry = _confined(config.get("entry") or "source/index.jsx", "entry")
    public_dir = _confined(config.get("publicDir") or "public", "publicDir")
    output = _confined(str(output or config.get("output") or "rerender-out.mp4"), "output")
    runtime = config.get("runtime") if isinstance(config.get("runtime"), dict) else {}
    kind = runtime.get("kind")
    worker = runtime.get("worker")
    if not worker:
        errors.append("rerender.json runtime.worker is missing.")
        worker_path = PACKAGE / "missing-worker"
    else:
        worker_path = _confined(worker, "worker")
    if not entry.is_file():
        errors.append("Package-local entry is missing: " + str(entry))
    if not public_dir.is_dir() and kind == "remotion":
        errors.append("Package-local publicDir is missing: " + str(public_dir))
    fingerprints = _load_optional("fingerprints.json")
    rels_by_ref = _reconstruction_rels(held, fingerprints, props)
    errors.extend(_held_errors(held, held_map))
    reconstructable = []
    for ref, dests in rels_by_ref.items():
        if ref in held_map:
            reconstructable.extend(dests)
    errors.extend(_cue_gap_errors(props, public_dir, reconstructable))
    errors.extend(_background_gap_errors(props, public_dir, reconstructable))
    runtime_errors, pins, installed = _runtime_errors(kind, worker_path, browser, runtime)
    errors.extend(runtime_errors)
    report = {
        "ok": not errors,
        "self_contained": False,
        "kind": kind,
        "entry": str(entry),
        "publicDir": str(public_dir),
        "output": str(output),
        "worker": str(worker_path),
        "fonts": str(public_dir / "fonts"),
        "browserExecutable": str(browser) if browser else None,
        "held": [
            {
                "ref": item.get("ref"),
                "sha256": item.get("sha256"),
                "frozen_ref": item.get("frozen_ref"),
                "frozen_cues": list(rels_by_ref.get(item.get("ref")) or []),
                "supplied": item.get("ref") in held_map,
            }
            for item in held
        ],
        "runtime": {
            "package_json": str(PACKAGE / "package.json"),
            "package_lock": str(PACKAGE / "package-lock.json"),
            "node_modules": str(PACKAGE / "node_modules"),
            "install": "npm ci --ignore-scripts",
            "pins": pins,
            "installed": installed,
        },
        "errors": errors,
    }
    return report, entry, public_dir, output, worker_path, kind, rels_by_ref


def main(argv=None):
    parser = argparse.ArgumentParser(description="Rerender from this delivered graphics package.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate package-local paths, object props, pinned installed package.json versions, browser path and held-ref mappings without rendering.",
    )
    parser.add_argument(
        "--acknowledge-separately-held",
        action="store_true",
        help="Not sufficient. Supply --held-ref ref=<file> for each separately-held.json item.",
    )
    parser.add_argument(
        "--held-ref",
        action="append",
        help="ref=path mapping for one separately held original; repeat as needed.",
    )
    parser.add_argument(
        "--browser-executable",
        help="Prepared browser executable path, resolved and passed as job.browserExecutable.",
    )
    parser.add_argument("--output", help="Package-relative output path (default: rerender.json output).")
    args = parser.parse_args(argv)
    config = _load("rerender.json")
    props = _load("props.json")
    held = _load("separately-held.json")
    held_map = _parse_held(args.held_ref)
    browser = _resolve_browser(args.browser_executable)
    report, entry, public_dir, output, worker_path, kind, rels_by_ref = _preflight(
        config, props, held, held_map, browser, args.output
    )
    if args.acknowledge_separately_held and held and not held_map:
        report["errors"].append(
            "acknowledgement is not the required bytes; pass --held-ref ref=<file> for each separately-held item."
        )
        report["ok"] = False
    if args.check:
        json.dump(report, sys.stdout)
        sys.stdout.write("\\n")
        return 0 if report["ok"] else 2
    if not report["ok"]:
        sys.stderr.write("\\n".join(report["errors"]) + "\\n")
        raise SystemExit(2)
    staged_public, staged_tmp = _stage_held_public(public_dir, held, held_map, rels_by_ref)
    job = {
        "composition": config.get("composition"),
        "entry": str(entry),
        "publicDir": str(staged_public),
        "output": str(output),
        "width": config.get("width"),
        "height": config.get("height"),
        "fps": config.get("fps"),
        "durationInFrames": config.get("durationInFrames"),
        "codec": config.get("codec") or "h264",
        "pixelFormat": config.get("pixelFormat") or "yuv420p",
        "colorSpace": config.get("colorSpace") or "bt709",
        "imageFormat": config.get("imageFormat") or "png",
        "crf": config.get("crf") or 18,
        "concurrency": config.get("concurrency") or 1,
        "props": props,
        "heldRefs": {ref: str(Path(path).expanduser().resolve()) for ref, path in held_map.items()},
    }
    if browser is not None:
        job["browserExecutable"] = str(browser)
    if isinstance(config.get("audio"), dict):
        job["audio"] = config["audio"]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        json.dump(job, handle)
        job_path = handle.name
    env = os.environ.copy()
    env.pop("GB_GRAPHICS_PREPARE_BROWSER", None)
    try:
        if kind == "test-worker":
            cmd = [sys.executable, str(worker_path), "--job", job_path]
        else:
            cmd = ["node", str(worker_path), "--job", job_path]
        return subprocess.run(cmd, check=False, cwd=str(PACKAGE), env=env).returncode
    finally:
        Path(job_path).unlink(missing_ok=True)
        if staged_tmp is not None:
            staged_tmp.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _graphics_timing_payload(ledger, version):
    from .graphics import graphics_content_sha256

    timing = _as_dict(version.get("timing"))
    profile = _as_dict(version.get("profile"))
    artifact = _as_dict(version.get("artifact"))
    approval = _as_dict(version.get("approval"))
    return {
        "project_id": ledger.data.get("project_id"),
        "scene_id": version.get("scene_id"),
        "occurrence_id": version.get("occurrence_id"),
        "version": version.get("id"),
        "parent": version.get("parent"),
        "content_sha256": graphics_content_sha256(version),
        "video_sha256": artifact.get("sha256"),
        "narration": {
            "start_s": timing.get("start_s"),
            "end_s": timing.get("end_s"),
            "duration_s": timing.get("duration_s"),
        },
        "frames": {
            "start_frame": timing.get("start_frame"),
            "end_frame": timing.get("end_frame"),
            "duration_in_frames": timing.get("duration_in_frames"),
        },
        "fps": profile.get("fps"),
        "timing_basis": timing.get("basis"),
        "approval": {
            "project_id": approval.get("project_id"),
            "version_id": approval.get("version_id"),
            "content_sha256": approval.get("content_sha256"),
            "by": approval.get("by"),
            "at": approval.get("at"),
            "channel": approval.get("channel"),
        },
        "embedded_voice_over": False,
        "automatic_alpha": False,
        "master_or_stem": False,
    }


def _graphics_rerender_config(version):
    timing = _as_dict(version.get("timing"))
    profile = _as_dict(version.get("profile"))
    fingerprints = _as_dict(version.get("fingerprints"))
    runtime = _as_dict(fingerprints.get("runtime"))
    worker_name = Path(str(runtime.get("worker") or "")).name
    props = version.get("props") if isinstance(version.get("props"), dict) else {}
    remotion = runtime.get("kind") == "remotion"
    config = {
        "note": (
            "Package-local rerender configuration. Frozen job.json in the version directory was not "
            "modified. This package is not self-contained: a JSON placeholder is not enough to "
            "rerender. package.json/package-lock.json at this root are independent copies of the "
            "frozen pinned lock. Run `npm ci --ignore-scripts` here, or junction/symlink "
            "./node_modules to an existing 4.0.534 tree, then `python rerender.py "
            "--browser-executable <prepared>`. Restricted originals need `--held-ref ref=<file>`."
        ),
        "invocation": {
            "command": "python rerender.py --browser-executable <prepared-browser-file>",
            "check": "python rerender.py --check",
            "held_ref": "python rerender.py --held-ref <ref>=<file>",
            "note": (
                "rerender.py loads props.json as an object, resolves entry/publicDir/output "
                "relative to this package, and invokes the copied worker with cwd at the package "
                "root. Restricted refs in separately-held.json are not copied, including frozen "
                "public/audio cue and public/media background bytes. --held-ref must supply the exact sha256 bytes, which are "
                "reconstructed into owned temporary render media at every frozen destination "
                "that references those bytes. Acknowledgement is not those bytes."
            ),
        },
        "composition": version.get("composition"),
        "entry": "source/index.jsx",
        "publicDir": "public",
        "output": "rerender-out.mp4",
        "width": profile.get("width"),
        "height": profile.get("height"),
        "fps": profile.get("fps"),
        "durationInFrames": timing.get("duration_in_frames"),
        "codec": "h264",
        "pixelFormat": "yuv420p",
        "colorSpace": "bt709",
        "imageFormat": "png",
        "crf": 18,
        "concurrency": 1,
        "props": props,
        "runtime": {
            "kind": runtime.get("kind"),
            "worker": ("inputs/" + worker_name) if worker_name else None,
            "package_json": "package.json" if remotion else None,
            "package_lock": "package-lock.json" if remotion else None,
            "inputs_package_json": "inputs/package.json" if remotion else None,
            "inputs_package_lock": "inputs/package-lock.json" if remotion else None,
            "node_modules": "node_modules" if remotion else None,
            "pins": dict(GRAPHICS_RUNTIME_PINS) if remotion else None,
            "install": {
                "command": "npm ci --ignore-scripts",
                "cwd": ".",
                "note": (
                    "Do not copy node_modules, browser binaries, venv, staging or private "
                    "voice-over into this package. External route: mklink /J node_modules "
                    "<pinned-node_modules> (Windows) or ln -s <pinned-node_modules> node_modules. "
                    "`rerender.py --check` reads each installed package.json version; a bundler "
                    "directory alone is not enough."
                ),
            },
            "browser": {
                "option": "--browser-executable",
                "job_field": "browserExecutable",
                "note": "Resolved to the supplied file and passed in the job. The copied worker will not download a browser.",
            },
        },
        "separately_held": "separately-held.json",
        "permitted_refs": "refs/<original-previews-or-clips-path>",
        "fonts": "public/fonts",
    }
    cues = props.get("sound_cues") if isinstance(props, dict) else None
    audio_fp = fingerprints.get("audio") if isinstance(fingerprints.get("audio"), dict) else None
    if (isinstance(cues, list) and cues) or (isinstance(audio_fp, dict) and audio_fp.get("mode") == "effects"):
        config["audio"] = {"mode": "effects", "codec": "aac"}
    return config


def _graphics_package_dir(ledger, package_rel):
    return Path(ledger.root).resolve().parent / DELIVERY_DIR / package_rel


def _graphics_generated_payloads(ledger, version, material, video_name, package_rel):
    created, updated = _graphics_origin_dates(version, _graphics_package_dir(ledger, package_rel))
    origin = render_graphics_origin(version, video_name, material, package_rel, dates=(created, updated))
    cues = _as_dict(version.get("props")).get("sound_cues")
    clip_audio = (
        "Full HD H.264 with AAC effects (voice-over is not embedded)."
        if isinstance(cues, list) and cues
        else "Full HD H.264, no embedded voice-over."
    )
    package_note = (
        "# Editable graphics sources\n\n"
        "This folder is an independent copy of the frozen authored scene. Editing files here "
        "does not change `brolls/graphics/` originals.\n\n"
        "- Finished clip: `" + video_name + "` (" + clip_audio + ").\n"
        "- Timing: `timing.json` (original narration seconds and derived frames).\n"
        "- Rerun: `python rerender.py --browser-executable <prepared>` (props as an object; "
        "paths are package-relative).\n"
        "- Preflight: `python rerender.py --check` (no render; reads installed package.json versions).\n"
        "- Runtime: `npm ci --ignore-scripts` at this package root using the copied "
        "package.json/package-lock.json, or a node_modules junction to a pinned 4.0.534 tree; "
        "see `rerender.json`.\n"
        "- Restricted raw dependencies: `separately-held.json`; supply `--held-ref ref=<file>` "
        "with matching sha256. Restricted public/audio cue and public/media background bytes are omitted and reconstructed "
        "into temporary render media at every frozen destination that references those "
        "bytes. Acknowledgement is not those bytes.\n"
        '- Fonts live under `public/fonts/` for `staticFile("fonts/...")` plus `inputs/fonts/`, '
        "with the actual license bytes when the Remotion runtime froze them.\n"
        "- `node_modules`, browser binaries, venv, staging and private VO are not copied.\n"
        "- This package is not self-contained. A passing synthetic test-worker rerender is not "
        "Remotion renderer success.\n"
    )
    return {
        "timing.json": json.dumps(
            _graphics_timing_payload(ledger, version), ensure_ascii=False, indent=2, sort_keys=True
        )
        + "\n",
        "rerender.json": json.dumps(_graphics_rerender_config(version), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        "separately-held.json": json.dumps(
            material.get("separately_held") or [], ensure_ascii=False, indent=2, sort_keys=True
        )
        + "\n",
        "rerender.py": RERENDER_ADAPTER,
        "ORIGEM.md": origin,
        "PACKAGE.md": package_note,
    }


def render_graphics_origin(version, video_name, material, package_rel, *, dates=None):
    created, updated = dates or (None, None)
    approval = _as_dict(version.get("approval"))
    artifact = _as_dict(version.get("artifact"))
    timing = _as_dict(version.get("timing"))
    lines = _frontmatter("delivery-origin", created, ["get-brolls", "entrega", "graphics"], updated=updated)
    lines += [
        f"# Origem de {video_name}",
        "",
        f"- Arquivo: `{video_name}`",
        f"- Scene: `{version.get('scene_id')}`",
        f"- Occurrence: `{version.get('occurrence_id')}`",
        f"- Version: `{version.get('id')}`",
        f"- Parent: `{version.get('parent') or 'none'}`",
        f"- Timing basis: `{timing.get('basis')}`",
        f"- Aprovado por: {approval.get('by') or 'não registrado'}"
        + (f" ({approval.get('channel')})" if approval.get("channel") else ""),
        f"- sha256 do arquivo: `{artifact.get('sha256') or 'não calculado'}`",
        f"- Pacote: `{package_rel}`",
        "",
        COPY_NOTE,
        "",
        "Editable sources in this package are independent copies. The frozen originals stay in `brolls/graphics/`.",
        "This package is not self-contained. Restricted raw references are listed in `separately-held.json` and need `--held-ref ref=<file>` with matching sha256. Restricted public/audio cue and public/media background bytes are omitted and reconstructed into temporary render media at every frozen destination that references those bytes.",
        "",
    ]
    held = material.get("separately_held") or []
    if held:
        lines += ["## Separately held raw dependencies", ""]
        for item in held:
            lines.append(
                f"- `{item.get('ref')}` sha256 `{item.get('sha256') or 'unknown'}` "
                f"({item.get('raw_redistribution') or 'unknown'}): {item.get('conditions') or ''}"
            )
        lines.append("")
    return "\n".join(lines)


def _graphics_font_copies(version_dir, fingerprints):
    copies = []
    fonts = fingerprints.get("fonts") if isinstance(fingerprints.get("fonts"), dict) else {}
    for font_name in fonts:
        src = version_dir / "inputs" / "fonts" / font_name
        copies.append((f"inputs/fonts/{font_name}", src))
        public_src = version_dir / "public" / "fonts" / font_name
        copies.append((f"public/fonts/{font_name}", public_src if public_src.is_file() else src))
    license_path = version_dir / "inputs" / "fonts" / "OFL-1.1.txt"
    if license_path.is_file():
        copies.append(("inputs/fonts/OFL-1.1.txt", license_path))
        copies.append(("public/fonts/OFL-1.1.txt", license_path))
    return copies


def _held_audio_destinations(version):
    """Frozen public/audio destinations grouped by the original effect ref."""
    audio_fp = _as_dict(_as_dict(version.get("fingerprints")).get("audio"))
    by_ref = {}
    for item in audio_fp.get("assets") or []:
        if not isinstance(item, dict):
            continue
        ref = item.get("ref")
        frozen = str(item.get("frozen_ref") or "").replace("\\", "/")
        if not isinstance(ref, str) or not frozen.startswith("public/audio/"):
            continue
        name = frozen[len("public/audio/") :]
        if not name or name in (".", "..") or "/" in name:
            continue
        bucket = by_ref.setdefault(ref, [])
        if frozen not in bucket:
            bucket.append(frozen)
    return by_ref


def _held_media_destinations(version):
    """Frozen public/media destinations grouped by the original background ref."""
    background_fp = _as_dict(_as_dict(version.get("fingerprints")).get("background"))
    by_ref = {}
    for item in background_fp.get("assets") or []:
        if not isinstance(item, dict):
            continue
        ref = item.get("ref")
        frozen = str(item.get("frozen_ref") or "").replace("\\", "/")
        if not isinstance(ref, str) or not frozen.startswith("public/media/"):
            continue
        name = frozen[len("public/media/") :]
        if not name or name in (".", "..") or "/" in name:
            continue
        bucket = by_ref.setdefault(ref, [])
        if frozen not in bucket:
            bucket.append(frozen)
    return by_ref


def _held_destination_pools(version, held_refs):
    remaining = {ref: list(dests) for ref, dests in _held_audio_destinations(version).items() if ref in held_refs}
    for ref, dests in _held_media_destinations(version).items():
        if ref not in held_refs:
            continue
        bucket = remaining.setdefault(ref, [])
        for dest in dests:
            if dest not in bucket:
                bucket.append(dest)
    return remaining


def _rebind_held_items(held, remaining):
    rebound = []
    for item in held:
        ref = item.get("ref")
        pool = remaining.get(ref)
        if pool:
            current = str(item.get("frozen_ref") or "").replace("\\", "/")
            if current in pool:
                pool.remove(current)
                item["frozen_ref"] = current
            else:
                item["frozen_ref"] = pool.pop(0)
        rebound.append(item)
    for ref, pool in remaining.items():
        template = next((item for item in rebound if item.get("ref") == ref), None)
        if template is None:
            continue
        for dest in pool:
            extra = dict(template)
            extra["frozen_ref"] = dest
            rebound.append(extra)
    return rebound


def _bind_held_frozen_cues(version, material):
    """One held original keeps every frozen cue; restriction outranks earlier permitted."""
    held = [dict(item) for item in material.get("separately_held") or [] if isinstance(item, dict)]
    permitted = [item for item in material.get("permitted_raw") or [] if isinstance(item, dict)]
    held_refs = {item.get("ref") for item in held if isinstance(item.get("ref"), str)}
    material["separately_held"] = _rebind_held_items(held, _held_destination_pools(version, held_refs))
    material["permitted_raw"] = [item for item in permitted if item.get("ref") not in held_refs]
    return material


def _runtime_package_copies(version_dir, runtime):
    copies = []
    worker_name = Path(str(runtime.get("worker") or "")).name
    if worker_name:
        copies.append((f"inputs/{worker_name}", version_dir / "inputs" / worker_name))
    if runtime.get("kind") != "remotion":
        return copies
    pkg_json = version_dir / "inputs" / "package.json"
    pkg_lock = version_dir / "inputs" / "package-lock.json"
    copies.append(("inputs/package.json", pkg_json))
    copies.append(("inputs/package-lock.json", pkg_lock))
    copies.append(("package.json", pkg_json))
    copies.append(("package-lock.json", pkg_lock))
    return copies


def _permitted_fingerprint_asset_copies(assets, version_dir, held_refs, prefix):
    copies = []
    by_ref = {}
    for item in assets or []:
        if not isinstance(item, dict):
            continue
        frozen_ref = item.get("frozen_ref")
        orig = item.get("ref")
        posix_frozen = frozen_ref.replace("\\", "/") if isinstance(frozen_ref, str) else ""
        if posix_frozen.startswith(prefix) and item.get("raw_redistribution") == "permitted" and orig not in held_refs:
            copies.append((posix_frozen, version_dir.joinpath(*posix_frozen.split("/"))))
        if isinstance(orig, str):
            by_ref[orig] = item
    return copies, by_ref


def _frozen_path_for_permitted_ref(rel, inputs, audio_by_ref, media_by_ref):
    spec = inputs.get(rel) if isinstance(rel, str) else None
    frozen = spec.get("frozen") if isinstance(spec, dict) else None
    if isinstance(frozen, str):
        return frozen
    audio_item = audio_by_ref.get(rel) if isinstance(rel, str) else None
    frozen_ref = audio_item.get("frozen_ref") if isinstance(audio_item, dict) else None
    if isinstance(frozen_ref, str):
        return frozen_ref
    media_item = media_by_ref.get(rel) if isinstance(rel, str) else None
    frozen_ref = media_item.get("frozen_ref") if isinstance(media_item, dict) else None
    if isinstance(frozen_ref, str):
        return frozen_ref
    return None


def _graphics_binary_copies(ledger, version, material):
    version_dir = Path(ledger.root) / "graphics" / version["scene_id"] / version["id"]
    copies = []
    video_name = f"{version['scene_id']}-{version['occurrence_id']}-{version['id']}.mp4"
    copies.append((video_name, version_dir / "preview.mp4"))
    fingerprints = _as_dict(version.get("fingerprints"))
    source_raw = fingerprints.get("source")
    source = source_raw if isinstance(source_raw, dict) else {}
    copies.extend((f"source/{name}", version_dir / "source" / name) for name in source)
    copies.extend(
        (name, version_dir / name) for name in ("assignment.json", "style.json", "props.json", "fingerprints.json")
    )
    copies.extend(_runtime_package_copies(version_dir, _as_dict(fingerprints.get("runtime"))))
    copies.extend(_graphics_font_copies(version_dir, fingerprints))
    held_refs = {
        item.get("ref")
        for item in material.get("separately_held") or []
        if isinstance(item, dict) and isinstance(item.get("ref"), str)
    }
    audio_copies, audio_by_ref = _permitted_fingerprint_asset_copies(
        _as_dict(fingerprints.get("audio")).get("assets"), version_dir, held_refs, "public/audio/"
    )
    media_copies, media_by_ref = _permitted_fingerprint_asset_copies(
        _as_dict(fingerprints.get("background")).get("assets"), version_dir, held_refs, "public/media/"
    )
    copies.extend(audio_copies)
    copies.extend(media_copies)
    inputs = _as_dict(fingerprints.get("inputs"))
    for entry in material.get("permitted_raw") or []:
        rel = entry.get("ref")
        frozen = _frozen_path_for_permitted_ref(rel, inputs, audio_by_ref, media_by_ref)
        if not isinstance(frozen, str):
            raise ValueError("Permitted raw ref is missing its frozen path: " + str(rel))
        copies.append((f"refs/{rel}", version_dir.joinpath(*frozen.split("/"))))
    return video_name, copies


def _text_same(dest, text):
    try:
        return dest.is_file() and dest.read_bytes() == text.encode("utf-8")
    except OSError as exc:
        raise _CompareError(str(exc)) from exc


def _put_generated_text(dest, text):
    if dest.exists() or dest.is_symlink():
        if _is_link_or_junction(dest) or dest.is_dir():
            raise ValueError(f"{dest} is a symlink, junction or directory; graphics delivery will not replace it.")
        if _compared(_text_same, dest, text):
            return "copy"
        raise ValueError(
            f"{dest} já existe com conteúdo diferente do arquivo coletado: parece edição "
            "sua e eu não sobrescrevo. Renomeie ou apague esse arquivo e rode `deliver` "
            "de novo."
        )
    from .ledger import atomic_write

    dest.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(dest, text, newline="\n")
    return "copy"


def _source_confined(brolls_root, src):
    src = Path(src)
    if src.is_symlink() or not src.is_file():
        raise ValueError("missing_declared_file")
    try:
        brolls = Path(brolls_root).resolve()
        real = src.resolve()
    except OSError as exc:
        raise ValueError("missing_declared_file") from exc
    brolls_s = os.path.normcase(str(brolls)).rstrip("\\/")
    real_s = os.path.normcase(str(real))
    if real_s != brolls_s and not real_s.startswith(brolls_s + os.sep):
        raise ValueError("missing_declared_file")


def _preflight_graphics_dest(entrega_root, dest, *, same):
    _assert_graphics_dest_safe(entrega_root, dest)
    if not (dest.exists() or dest.is_symlink()):
        return
    if _is_link_or_junction(dest) or dest.is_dir():
        raise ValueError(f"{dest} is a symlink, junction or directory; graphics delivery will not replace it.")
    if not same():
        raise ValueError(
            f"{dest} já existe com conteúdo diferente do arquivo coletado: parece edição "
            "sua e eu não sobrescrevo. Renomeie ou apague esse arquivo e rode `deliver` "
            "de novo."
        )


def _preflight_graphics_package(brolls_root, entrega_root, package_dir, copies, generated):
    for rel, src in copies:
        _source_confined(brolls_root, src)
        dest = package_dir / rel
        _preflight_graphics_dest(entrega_root, dest, same=lambda dest=dest, src=src: _compared(_same_bytes, dest, src))
    for rel, text in generated.items():
        dest = package_dir / rel
        _preflight_graphics_dest(
            entrega_root, dest, same=lambda dest=dest, text=text: _compared(_text_same, dest, text)
        )


def _write_graphics_copies(package_dir, copies, video_name):
    from .ledger import digest as file_digest

    files = {}
    for rel, src in copies:
        dest = package_dir / rel
        copy_independent(src, dest)
        files[rel] = file_digest(dest)
        if rel == video_name:
            try:
                dest.chmod(dest.stat().st_mode & ~0o222)
            except OSError as exc:
                record_warning(
                    "DELIVERY_FREEZE_FAILED",
                    f"Não consegui deixar {dest} somente-leitura ({exc}).",
                )
    return files


def _write_graphics_generated(package_dir, generated):
    from .ledger import digest as file_digest

    files = {}
    for rel, text in generated.items():
        dest = package_dir / rel
        _put_generated_text(dest, text)
        files[rel] = file_digest(dest)
    return files


def _planned_graphics_hashes(copies, generated):
    from .ledger import digest as file_digest

    files = {rel: file_digest(src) for rel, src in copies}
    for rel, text in generated.items():
        files[rel] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return files


def _graphics_expected_rels(package_rel, video_name, copies, generated):
    expected = {package_rel, GRAPHICS_DIR, f"{package_rel}/{video_name}"}
    expected.update(_ancestor_rels(package_rel))
    for rel, _src in copies:
        file_rel = f"{package_rel}/{rel}"
        expected.add(file_rel)
        expected.update(_ancestor_rels(file_rel))
    for rel in generated:
        file_rel = f"{package_rel}/{rel}"
        expected.add(file_rel)
        expected.update(_ancestor_rels(file_rel))
    return expected


def _recorded_package_rels(package_rel, video_name, files):
    expected = {package_rel, GRAPHICS_DIR, f"{package_rel}/{video_name}"}
    expected.update(_ancestor_rels(package_rel))
    for name in files or {}:
        if isinstance(name, str) and name and ".." not in name.split("/"):
            file_rel = f"{package_rel}/{name}"
            expected.add(file_rel)
            expected.update(_ancestor_rels(file_rel))
    return expected


def _recorded_delivery_reusable(ledger, version):
    from .graphics import graphics_content_sha256

    delivery = version.get("delivery") if isinstance(version.get("delivery"), dict) else None
    if delivery is None:
        return None
    if (
        delivery.get("version_id") != version.get("id")
        or delivery.get("occurrence_id") != version.get("occurrence_id")
        or delivery.get("scene_id") != version.get("scene_id")
        or delivery.get("content_sha256") != graphics_content_sha256(version)
        or delivery.get("video_sha256") != _as_dict(version.get("artifact")).get("sha256")
    ):
        return None
    if not graphics_package_intact(ledger.root, delivery):
        return None
    return delivery


def _listed_graphic(version, occ, record, *, dry_run):
    video_name = Path(str(record.get("path") or "")).name
    package_rel = _entrega_rel(record.get("package_dir")) or ""
    listed = {
        "id": f"graphics:{occ.get('occurrence_id')}:{version.get('id')}",
        "scene": version.get("scene_id"),
        "occurrence": version.get("occurrence_id"),
        "version": version.get("id"),
        "parent": version.get("parent"),
        "path": record["path"],
        "method": "planned" if dry_run else "copy",
        "content_sha256": record.get("content_sha256"),
        "video_sha256": record.get("video_sha256"),
    }
    row = {
        "scene": version.get("scene_id"),
        "occurrence": version.get("occurrence_id"),
        "version": version.get("id"),
        "file": f"{package_rel}/{video_name}",
        "timing": _as_dict(version.get("timing")).get("basis"),
        "state": "planned" if dry_run else "delivered",
    }
    return listed, row


def _reuse_recorded_graphic(version, occ, recorded, dry_run):
    listed, row = _listed_graphic(version, occ, recorded, dry_run=dry_run)
    video_name = Path(str(recorded.get("path") or "")).name
    package_rel = _entrega_rel(recorded.get("package_dir")) or ""
    expected = _recorded_package_rels(package_rel, video_name, recorded.get("files"))
    return listed, row, recorded, expected, package_rel


def _deliver_one_graphic(ledger, root, item, dry_run):
    from .graphics import classify_material_use, graphics_content_sha256

    version = item["version"]
    occ = item["occurrence"]
    material = classify_material_use(ledger.root, version, ledger.data.get("items"))
    if material.get("reasons"):
        raise ValueError("unresolved_material_use")
    material = _bind_held_frozen_cues(version, material)
    package_rel = graphics_package_rel(version["scene_id"], version["occurrence_id"], version["id"])
    recorded = _recorded_delivery_reusable(ledger, version)
    if recorded:
        return _reuse_recorded_graphic(version, occ, recorded, dry_run)
    video_name, copies = _graphics_binary_copies(ledger, version, material)
    package_dir = root / package_rel
    generated = _graphics_generated_payloads(ledger, version, material, video_name, package_rel)
    _preflight_graphics_package(ledger.root, root, package_dir, copies, generated)
    if dry_run:
        files = _planned_graphics_hashes(copies, generated)
    else:
        copy_files = _write_graphics_copies(package_dir, copies, video_name)
        generated_files = _write_graphics_generated(package_dir, generated)
        files = {**copy_files, **generated_files}
    record = {
        "path": f"{DELIVERY_DIR}/{package_rel}/{video_name}",
        "package_dir": f"{DELIVERY_DIR}/{package_rel}",
        "method": "copy",
        "version_id": version.get("id"),
        "occurrence_id": version.get("occurrence_id"),
        "scene_id": version.get("scene_id"),
        "parent": version.get("parent"),
        "content_sha256": graphics_content_sha256(version),
        "video_sha256": _as_dict(version.get("artifact")).get("sha256"),
        "files": files,
    }
    listed, row = _listed_graphic(version, occ, record, dry_run=dry_run)
    expected = _graphics_expected_rels(package_rel, video_name, copies, generated)
    return listed, row, record, expected, package_rel


def graphics_package_intact(brolls_root, delivery):
    """Read-only: recorded package files exist, stay confined, and match recorded hashes."""
    from .ledger import digest as file_digest

    try:
        project = Path(brolls_root).resolve().parent
        entrega = project / DELIVERY_DIR
        files = delivery.get("files") if isinstance(delivery.get("files"), dict) else {}
        package_dir = delivery.get("package_dir")
        path = delivery.get("path")
        if not isinstance(package_dir, str) or not isinstance(path, str) or not files:
            return False
        for rel, expected in files.items():
            dest = project.joinpath(*package_dir.split("/"), *str(rel).split("/"))
            _assert_graphics_dest_safe(entrega, dest)
            if dest.is_symlink() or dest.is_dir() or not dest.is_file():
                return False
            if file_digest(dest) != expected:
                return False
        video = project.joinpath(*path.split("/"))
        _assert_graphics_dest_safe(entrega, video)
        if video.is_symlink() or not video.is_file() or file_digest(video) != delivery.get("video_sha256"):
            return False
    except (ValueError, OSError, TypeError, KeyError):
        return False
    return True


def _deliver_graphics(ledger, root, dry_run, expected):
    listed, skipped, rows, changed, conflicts, conflicted = [], [], [], [], [], []
    eligible, skipped = _plan_graphics(ledger)
    expected.update(_retained_graphics_rels(ledger.data.get("graphics")))
    for item in eligible:
        version = item["version"]
        try:
            listed_item, row, record, rels, _package = _deliver_one_graphic(ledger, root, item, dry_run)
        except ValueError as exc:
            detail = str(exc)
            conflicts.append(detail)
            ident = graphics_package_rel(version["scene_id"], version["occurrence_id"], version["id"])
            conflicted.append(ident)
            skipped.append(
                {
                    "occurrence_id": version.get("occurrence_id"),
                    "scene_id": version.get("scene_id"),
                    "version": version.get("id"),
                    "reason": "conflict"
                    if "parece edição sua" in detail or "symlink" in detail.lower() or "junction" in detail.lower()
                    else detail,
                    "reasons": [detail],
                }
            )
            logs.event(
                log,
                logging.WARNING,
                "deliver_graphics_conflict",
                occurrence=version.get("occurrence_id"),
                version=version.get("id"),
            )
            continue
        expected.update(rels)
        listed.append(listed_item)
        rows.append(row)
        if dry_run:
            continue
        if version.get("delivery") != record:
            version["delivery"] = record
            changed.append(version)
    return listed, skipped, rows, changed, conflicts, conflicted


def build_delivery(project, dry_run=False, ledger=None, for_human=None):  # noqa: C901, PLR0912, PLR0915 - existing size; rebuilds `entrega/` through every item/state combination
    """Refaz `entrega/` a partir do que já está coletado em `brolls/`.

    Não toca em `brolls/`, não decide nada e não inventa direito de uso: só reorganiza
    o que `fetch` já produziu. Com `dry_run`, devolve o mesmo relatório sem escrever
    um byte — nem na pasta, nem no manifesto, e o método de cada item sai como
    `"planned"`, porque só a escrita diz qual o sistema aceita.

    `for_human` pode ser um texto ou uma função sem argumentos: ela é chamada **depois**
    da materialização, para que o "próximo passo" do índice fale do estado novo e não do
    passo que acabou de ser executado.

    Um arquivo que a pessoa editou não interrompe o trabalho pela metade: o conflito é
    anotado, os demais itens são materializados, o índice e o manifesto são gravados, a
    varredura roda, e só então o comando falha nomeando todos os arquivos em conflito.

    `entrega/` precisa ser uma pasta real: se o caminho já existe como link simbólico,
    seguir ele poderia varrer e apagar arquivos de outro lugar (o alvo do link), então o
    comando recusa antes de tocar em qualquer arquivo, mesmo em `dry_run`.
    """
    from .ledger import Ledger, atomic_write

    ledger = ledger or Ledger(project, recover=False)
    items = ledger.data["items"]
    root = Path(project).expanduser().resolve() / DELIVERY_DIR
    if root.exists() and (root.is_symlink() or _is_link_or_junction(root)):
        logs.event(log, logging.WARNING, "deliver_refusal", reason="entrega_is_symlink")
        raise ValueError(
            f"{root} é um link simbólico: apague o link antes de rodar `deliver`. A pasta "
            "de entrega precisa ser uma pasta real dentro do projeto, nunca um atalho para "
            "outro lugar."
        )
    groups, skipped = _plan(project, items)
    expected, listed, rows, changed = set(), [], [], []
    conflicts, conflicted = [], []
    for group in groups:
        expected.add(group["dir"])
        for index, c in enumerate(group["items"], start=1):
            source = ledger.root / c["output"]["path"]
            sheet_rel = (c.get("preview") or {}).get("contact_sheet_path")
            sheet = ledger.root / sheet_rel if sheet_rel else None
            names = _names(
                group["dir"],
                index,
                Path(c["output"]["path"]).suffix or ".mp4",
                Path(sheet_rel).suffix if sheet_rel else ".jpg",
            )
            media_rel = f"{group['dir']}/{names['media']}"
            expected.add(media_rel)
            method = "planned" if dry_run else None
            sheet_rel_out = f"{group['dir']}/{names['sheet']}" if sheet else None
            if sheet_rel_out:
                expected.add(sheet_rel_out)
            conflict = None
            if not dry_run:
                try:
                    if source.is_file():
                        # Só hardlink/symlink são congelados: cópia é independente.
                        method = link_or_copy(source, root / media_rel, read_only=True)
                        logs.event(
                            log,
                            logging.INFO,
                            "deliver_item",
                            beat=group["beat"] or "no_beat",
                            mode=method,
                            # `link_or_copy` doesn't report a per-attempt failure reason
                            # (its signature is shared with tests that stub it out with a
                            # 3-arg fake), so only the one fallback cause this call site
                            # can know for certain — a forced copy — is named here.
                            reason="env_copy" if copies_forced() else None,
                        )
                    if sheet and sheet_rel_out and sheet.is_file():
                        # O contact sheet não é congelado: `preview` regrava o arquivo
                        # de origem no mesmo caminho quando a pessoa muda o intervalo.
                        link_or_copy(sheet, root / sheet_rel_out)
                except ValueError as exc:
                    conflict = str(exc)
                    conflicts.append(conflict)
                    conflicted.append(media_rel)
                    logs.event(
                        log,
                        logging.WARNING,
                        "deliver_conflict",
                        beat=group["beat"] or "no_beat",
                        kind="foreign_file" if "parece edição sua" in conflict else "io_error",
                    )
            origin_rel = f"{group['dir']}/{names['origin']}"
            expected.add(origin_rel)
            if not dry_run and not conflict:
                target = root / origin_rel
                atomic_write(
                    target,
                    render_origin(c, names["media"], _created_in(target), method or "hardlink"),
                )
            record = {"path": f"{DELIVERY_DIR}/{media_rel}", "method": method}
            if conflict:
                # Não entregamos este: manter o registro antigo (ou nenhum) é o que
                # mantém o item fora de "entregue" no `status` e fora da tabela.
                continue
            if not dry_run and c.get("delivery") != record:
                c["delivery"] = record
                changed.append(c)
            listed.append(
                {
                    "id": c["id"],
                    "beat": group["beat"],
                    "path": f"{DELIVERY_DIR}/{media_rel}",
                    "method": method,
                }
            )
            rows.append(
                {
                    "beat": group["beat"] or "sem beat",
                    "narration": group["narration"],
                    "target": group["target"],
                    "file": f"{group['dir']}/{names['media']}",
                    "state": c.get("state"),
                    "rights": (c.get("rights") or {}).get("status"),
                    # Como este arquivo chegou aqui: é o que decide se editar nele
                    # editaria o original.
                    "method": method,
                }
            )
    graphics_items, graphics_skipped, graphics_rows, graphics_changed, graphics_conflicts, graphics_conflicted = (
        _deliver_graphics(ledger, root, dry_run, expected)
    )
    from .ai_delivery import deliver as deliver_ai
    from .ai_delivery import readme_lines as ai_readme_lines

    ai_items, ai_skipped, ai_conflicts, ai_changed = deliver_ai(ledger, root, dry_run, expected)
    conflicts.extend(ai_conflicts)
    conflicts.extend(graphics_conflicts)
    conflicted.extend(graphics_conflicted)
    expected.add(INDEX)
    if not dry_run:
        root.mkdir(parents=True, exist_ok=True)
        index = root / INDEX
        # O "próximo passo" é lido agora, com `c["delivery"]` já preenchido: senão o
        # índice mandaria a pessoa rodar exatamente o comando que acabou de rodar.
        text = for_human() if callable(for_human) else for_human
        copies = bool(listed) and all(i["method"] == "copy" for i in listed)
        lines = _delivery_index_preamble(rows, _created_in(index), copies)
        lines += _graphics_readme_lines(graphics_rows, graphics_skipped)
        lines += ai_readme_lines(ai_items, ai_skipped)
        lines += _delivery_index_tail(conflicted, text)
        atomic_write(index, "\n".join(lines))
    owned = {
        (c.get("delivery") or {}).get("path", "")[len(DELIVERY_DIR) + 1 :]
        for c in items
        if (c.get("delivery") or {}).get("path", "").startswith(DELIVERY_DIR + "/")
    }
    owned.update(_retained_graphics_rels(ledger.data.get("graphics")))
    removed, kept = _sweep(root, expected, dry_run, owned, ledger.root)
    if changed or graphics_changed or ai_changed:
        ledger.save_many("deliver", changed)
    if conflicts:
        raise ValueError(" ".join(conflicts))
    return {
        "delivery": str(root),
        "readme": str(root / INDEX),
        "dry_run": bool(dry_run),
        "items": listed,
        "rows": rows,
        "removed": removed,
        "kept": kept,
        "skipped": skipped,
        "graphics": graphics_items,
        "graphics_skipped": graphics_skipped,
        "ai": ai_items,
        "ai_skipped": ai_skipped,
    }
