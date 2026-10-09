"""Ler o que a fonte já conta sobre si antes de pedir mídia: onde olhar, e por quê.

Legendas, capítulos e os tempos escritos na descrição dizem, de graça, onde cada
assunto acontece no vídeo. Aqui isso vira janelas candidatas pontuadas contra a
frase do usuário — só biblioteca padrão, nada de rede e nada gravado.
"""

import re
import unicodedata

# Janela de legenda: junta falas vizinhas até esse tanto de segundos.
MAX_SUBTITLE_WINDOW_S = 12.0
# Buraco máximo entre duas falas para elas contarem como a mesma janela.
MAX_CUE_GAP_S = 1.5
# Sem fim conhecido (capítulo aberto, tempo escrito na descrição), use isto.
DEFAULT_WINDOW_S = 12.0
MIN_LANGUAGE_MARKERS = 2

_TIME_RE = re.compile(r"(?:(?P<h>\d{1,3}):)?(?P<m>\d{1,2}):(?P<s>\d{2})(?:[.,](?P<ms>\d{1,3}))?")
_CUE_RE = re.compile(
    r"^(?P<start>(?:\d{1,3}:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*"
    r"(?P<end>(?:\d{1,3}:)?\d{1,2}:\d{2}[.,]\d{1,3})"
)
_TAG_RE = re.compile(r"<[^>]*>")
# "00:10 chegada da poeira" / "1:05 — céu laranja": tempo no começo da linha.
_DESCRIPTION_RE = re.compile(r"^\s*\[?((?:\d{1,3}:)?\d{1,2}:\d{2})\]?\s*[-–—:.)]?\s*(?P<text>.+?)\s*$")


def _seconds(stamp):
    match = _TIME_RE.fullmatch(stamp.strip())
    if not match:
        return None
    hours = int(match.group("h") or 0)
    ms = (match.group("ms") or "0").ljust(3, "0")
    return hours * 3600 + int(match.group("m")) * 60 + int(match.group("s")) + int(ms) / 1000


def parse_vtt(text):
    """Cues `{start_s, end_s, text}` de um WebVTT; lixo vira lista vazia, não exceção."""
    cues = []
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    index = 0
    while index < len(lines):
        match = _CUE_RE.match(lines[index].strip())
        index += 1
        if not match:
            continue
        start = _seconds(match.group("start"))
        end = _seconds(match.group("end"))
        body = []
        # Só a linha realmente vazia fecha o bloco: a legenda automática do YouTube
        # abre e fecha os cues com uma linha de um espaço só, e tratá-la como fim de
        # bloco engolia a primeira fala do vídeo inteiro.
        while index < len(lines) and lines[index] != "":
            body.append(_TAG_RE.sub("", lines[index]).strip())
            index += 1
        spoken = " ".join(part for part in body if part).strip()
        if start is None or end is None or end <= start or not spoken:
            continue
        # Rolagem da legenda automática: o cue seguinte reabre com a linha anterior
        # inteira e só então acrescenta a fala nova. Repetir isso encheria a janela
        # das mesmas palavras e inflaria a nota de `score` sem o vídeo dizer nada a mais.
        if cues:
            previous = cues[-1]["text"]
            if spoken == previous:
                cues[-1]["end_s"] = end
                continue
            if spoken.startswith(previous + " "):
                spoken = spoken[len(previous) + 1 :].strip()
                if not spoken:
                    cues[-1]["end_s"] = end
                    continue
        cues.append({"start_s": start, "end_s": end, "text": spoken})
    return cues


# Cabeçalho opcional do WebVTT: `Language: pt-BR` logo depois do `WEBVTT`.
_VTT_LANGUAGE_RE = re.compile(r"^\s*Language\s*:\s*([A-Za-z]{2,3}(?:[-_][A-Za-z0-9]+)*)\s*$", re.MULTILINE)

# Palavras curtas que só existem em um dos dois idiomas. Não é detector de idioma:
# é o suficiente para perceber que a frase da pessoa e a legenda não se falam.
_PT_MARKERS = frozenset(
    [
        "de",
        "da",
        "do",
        "das",
        "dos",
        "que",
        "nao",
        "para",
        "com",
        "uma",
        "como",
        "quando",
        "onde",
        "porque",
        "isso",
        "essa",
        "esse",
        "pelo",
        "pela",
        "num",
        "numa",
        "mas",
        "ele",
        "ela",
        "eles",
        "elas",
        "voce",
        "nos",
        "entao",
        "ja",
        "tambem",
        "sobre",
        "ate",
        "sem",
        "muito",
        "ser",
        "esta",
        "estao",
        "foi",
        "sao",
        "tem",
    ]
)
_EN_MARKERS = frozenset(
    [
        "the",
        "of",
        "and",
        "to",
        "in",
        "that",
        "for",
        "with",
        "this",
        "these",
        "those",
        "from",
        "have",
        "has",
        "was",
        "were",
        "are",
        "is",
        "it",
        "its",
        "you",
        "we",
        "they",
        "there",
        "here",
        "about",
        "when",
        "where",
        "because",
        "but",
        "also",
        "into",
        "over",
    ]
)


def parse_vtt_language(text):
    """Idioma declarado no cabeçalho `Language:` do WebVTT, ou None quando não há um."""
    match = _VTT_LANGUAGE_RE.search(str(text or "")[:2000])
    return match.group(1).replace("_", "-") if match else None


def base_language(code):
    """`pt-BR` → `pt`; `und`, vazio e lixo → None."""
    head = str(code or "").strip().replace("_", "-").split("-")[0].lower()
    return head if head and head.isalpha() and head not in ("und", "zxx", "mul") else None


def guess_language(text):
    """Conservative function-word hint; explicit video/query language wins."""
    words = set(tokens(text))
    if not words:
        return None
    pt, en = len(words & _PT_MARKERS), len(words & _EN_MARKERS)
    counts = {
        "pt": pt,
        "en": en,
        "es": len(words & {"el", "la", "los", "las", "que", "donde", "cuando", "como", "del", "dice"}),
        "ru": len(words & {"что", "это", "как", "где", "когда", "который", "его", "ему", "говорит"}),
        "uk": len(words & {"що", "це", "як", "де", "коли", "який", "його", "йому", "каже", "він"}),
    }
    best = max(counts, key=lambda code: counts[code])
    if (
        best not in ("pt", "en")
        and counts[best] >= MIN_LANGUAGE_MARKERS
        and list(counts.values()).count(counts[best]) == 1
    ):
        return best
    if pt == en:
        return None
    return "pt" if pt > en else "en"


def source_language(probe):
    """Idioma **falado** da fonte, nunca o de uma tradução automática.

    O YouTube gera faixas traduzidas sob demanda, e `pt` costuma aparecer na frente
    numa fonte em inglês. Ler essa faixa invertia o aviso: a query correta, em
    inglês, era acusada de estar fora do idioma da fonte. A ordem é a de confiança —
    o que o yt-dlp marcou como original, a faixa `<code>-orig`, e só então a única
    faixa que sobrou, que aí não tem com o que ser confundida.
    """
    declared = base_language(probe.get("original_lang"))
    if declared:
        return declared
    if "subtitle_tracks" in probe:
        # The new acquisition report distinguishes an unknown original from fallback.
        return None
    listed = [str(code) for code in (probe.get("subtitle_langs") or [])]
    for code in listed:
        if code.endswith("-orig"):
            return base_language(code[: -len("-orig")])
    bases = [base for base in (base_language(code) for code in listed) if base]
    # Duas faixas sem nada dizendo qual é a fala: uma delas é tradução, e não dá para
    # saber qual. Melhor não avisar nada do que avisar o contrário.
    return bases[0] if len(set(bases)) == 1 and bases else None


def language_mismatch(probe, query, language=None):
    """(idioma da fonte, idioma da frase) quando os dois são conhecidos e diferentes.

    Buscar uma fala em português dentro de uma legenda em inglês pontua zero em toda
    janela, e o resultado parece "a fonte não fala disso" quando o problema é só o
    idioma da consulta.
    """
    if not query:
        return None
    asked = base_language(language or probe.get("query_language")) or guess_language(query)
    obtained = [base_language(code) for code, entry in (probe.get("subtitles") or {}).items() if entry.get("cues")]
    if asked in obtained:
        return None
    spoken = source_language(probe)
    if not asked or not spoken or spoken == asked:
        return None
    return (spoken, asked)


def tokens(text):
    """Fold Latin accents; preserve meaningful letters such as Cyrillic й/ї/ё."""
    normalized = unicodedata.normalize("NFKC", str(text or "")).lower()
    flat = []
    for ch in normalized:
        if "LATIN" in unicodedata.name(ch, ""):
            flat.extend(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c))
        else:
            flat.append(ch)
    return [word for word in re.split(r"[\W_]+", "".join(flat)) if word]


def normalize_language(code):
    """A concrete language tag, never yt-dlp's regex/all selection syntax."""
    value = str(code or "").strip().replace("_", "-")
    if not re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*", value) or value.lower() in ("all", "und", "mul", "zxx"):
        raise ValueError("Use a concrete subtitle language such as es, ru, uk, pt-BR or en-US.")
    return value


def score(query, text):
    """Fração das palavras da frase do usuário que aparecem na janela (0 sem frase)."""
    wanted = set(tokens(query))
    if not wanted:
        return 0.0
    found = wanted & set(tokens(text))
    return round(len(found) / len(wanted), 4)


def description_timestamps(description):
    """Marcações `mm:ss` escritas na descrição, com o texto que as acompanha."""
    marks = []
    for line in str(description or "").splitlines():
        match = _DESCRIPTION_RE.match(line)
        if not match:
            continue
        start = _seconds(match.group(1))
        text = match.group("text").strip()
        if start is None or not text:
            continue
        marks.append({"start_s": start, "text": text})
    return marks


def _subtitle_windows(cues):
    windows = []
    for cue in cues:
        if (
            windows
            and cue["start_s"] - windows[-1]["end_s"] <= MAX_CUE_GAP_S
            and cue["end_s"] - windows[-1]["start_s"] <= MAX_SUBTITLE_WINDOW_S
        ):
            windows[-1]["end_s"] = cue["end_s"]
            windows[-1]["text"] += " " + cue["text"]
            continue
        windows.append(dict(cue))
    return windows


def candidate_windows(probe, query=None, max_windows=3, *, language=None):
    """Trechos que valem olhar, do mais parecido com a frase para o menos.

    `probe` é o retorno de `social.probe_remote`. Sem frase, ninguém pontua: a ordem
    passa a ser cronológica. Nada aqui inventa intervalo além da duração conhecida, e
    janelas iguais em tempo e fonte (o mesmo trecho em dois idiomas) contam uma só vez.
    """
    duration = probe.get("duration_s")
    raw = []
    for code, entry in (probe.get("subtitles") or {}).items():
        cues = (entry or {}).get("cues") or []
        raw.extend(
            {
                **window,
                "source": "subtitle",
                "language": entry.get("language") or code,
                "subtitle_kind": entry.get("kind"),
                "is_original": entry.get("is_original"),
            }
            for window in _subtitle_windows(cues)
        )
    for chapter in probe.get("chapters") or []:
        start = chapter.get("start_s")
        end = chapter.get("end_s")
        if start is None:
            continue
        raw.append(
            {
                "start_s": float(start),
                "end_s": float(end if end is not None else start + DEFAULT_WINDOW_S),
                "text": chapter.get("title") or "",
                "source": "chapter",
            }
        )
    marks = description_timestamps(probe.get("description"))
    for position, mark in enumerate(marks):
        following = marks[position + 1]["start_s"] if position + 1 < len(marks) else None
        end = min(x for x in (following, mark["start_s"] + DEFAULT_WINDOW_S) if x is not None)
        raw.append(
            {
                "start_s": mark["start_s"],
                "end_s": end,
                "text": mark["text"],
                "source": "description_timestamp",
            }
        )
    windows = []
    for window in raw:
        start = max(0.0, float(window["start_s"]))
        end = float(window["end_s"])
        if duration:
            start = min(start, float(duration))
            end = min(end, float(duration))
        if end <= start or not (window.get("text") or "").strip():
            continue
        windows.append(
            {
                **window,
                "start_s": round(start, 3),
                "end_s": round(end, 3),
                "text": window["text"].strip(),
                "source": window["source"],
                "score": score(query, window["text"]),
            }
        )
    asked = base_language(language or probe.get("query_language")) or guess_language(query)
    windows.sort(
        key=lambda w: (
            -w["score"],
            w["start_s"],
            -int(bool(asked and base_language(w.get("language")) == asked)),
            -int(w.get("is_original") is True),
            -int(w.get("subtitle_kind") == "manual"),
        )
    )
    # Compare all tracks before selecting one representation of a timed window.
    unique = {}
    for window in windows:
        key = (window["start_s"], window["end_s"], window["source"])
        unique.setdefault(key, window)
    windows = list(unique.values())
    limit = max(1, int(max_windows or 1))
    if not windows:
        # Nenhuma janela nomeada: devolver `[]` deixa o agente sem nada para olhar e
        # empurra para o palpite. Um mapa grosseiro do vídeo é sempre melhor que nada.
        windows = fallback_windows(probe, limit)
    return windows[:limit]


def fallback_windows(probe, max_windows=3):
    """Mapa grosseiro do vídeo quando nada casou: capítulos, senão falas, senão o relógio.

    Sai sempre com `score: 0` e `source` preenchido, para ninguém confundir isto com
    um trecho que a frase do usuário encontrou.
    """
    limit = max(1, int(max_windows or 1))
    duration = probe.get("duration_s")
    out = []
    for chapter in probe.get("chapters") or []:
        start = chapter.get("start_s")
        if start is None:
            continue
        end = chapter.get("end_s")
        out.append(
            {
                "start_s": round(max(0.0, float(start)), 3),
                "end_s": round(float(end if end is not None else float(start) + DEFAULT_WINDOW_S), 3),
                "text": (chapter.get("title") or "").strip() or "Capítulo sem título",
                "source": "chapter",
                "score": 0.0,
            }
        )
    if not out:
        cues = []
        _code = "und"
        entry = {}
        for _code, entry in (probe.get("subtitles") or {}).items():
            cues = (entry or {}).get("cues") or []
            if cues:
                break
        out.extend(
            {
                "start_s": round(float(cue["start_s"]), 3),
                "end_s": round(float(cue["end_s"]), 3),
                "text": cue["text"],
                "source": "subtitle",
                "language": entry.get("language") or _code,
                "subtitle_kind": entry.get("kind"),
                "is_original": entry.get("is_original"),
                "score": 0.0,
            }
            for cue in _evenly(cues, limit)
        )
    if not out and duration:
        # Sem capítulo e sem legenda só resta o relógio: pontos igualmente espaçados,
        # para a pessoa ter por onde começar a varredura.
        total = float(duration)
        step = total / (limit + 1)
        for position in range(1, limit + 1):
            start = min(max(0.0, step * position), max(0.0, total - 0.5))
            out.append(
                {
                    "start_s": round(start, 3),
                    "end_s": round(min(total, start + DEFAULT_WINDOW_S), 3),
                    "text": "",
                    "source": "even_spacing",
                    "score": 0.0,
                }
            )
    return [w for w in out if w["end_s"] > w["start_s"]][:limit]


def _evenly(items, count):
    """`count` itens distribuídos ao longo da lista, sem repetir nem reordenar."""
    if not items:
        return []
    if len(items) <= count:
        return list(items)
    step = len(items) / count
    picked = []
    for position in range(count):
        item = items[int(position * step)]
        if item not in picked:
            picked.append(item)
    return picked
