"""Social acquisition using the existing yt-dlp/FFmpeg engine, without API keys."""

import hashlib
import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import logs
from .config import executable_override, venv_override
from .http import ProviderError
from .runtime import record_warning, redact, stderr_tail

_log = logs.get("social")

LAYOUTS = ("Scripts/yt-dlp.exe", "Scripts/yt-dlp", "bin/yt-dlp")
# Pauses between yt-dlp requests: (--sleep-requests, --sleep-interval, --max-sleep-interval).
DEFAULT_SLEEP = (1, 3, 8)
# `ytdlp_sleep` is logged once per process, not once per invocation, to avoid drowning
# the log in an identical DEBUG line for every one of possibly hundreds of yt-dlp calls.
_sleep_logged = False


def sleep_settings():
    """GB_YTDLP_SLEEP as "requests,min,max" seconds; defaults keep the source unhurried."""
    raw = (os.environ.get("GB_YTDLP_SLEEP") or "").strip()
    if not raw:
        return DEFAULT_SLEEP
    parts = raw.split(",")
    try:
        values = tuple(int(part.strip()) for part in parts)
    except ValueError:
        values = ()
    if len(values) != 3 or any(v < 0 for v in values) or values[1] > values[2]:  # noqa: PLR2004 - "requests,min,max": exatamente 3 campos
        raise ValueError('GB_YTDLP_SLEEP: use "requests,min,max" em segundos inteiros, com min <= max.')
    return values


def local_ytdlp(root=None):
    pinned = executable_override("GB_YTDLP_PATH")
    if pinned:
        return Path(pinned)
    base = venv_override()
    explicit = base is not None
    if not explicit:
        root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
        base = root / ".venv"
    for relative in LAYOUTS:
        candidate = base / relative
        if candidate.is_file():
            return candidate
    if explicit:
        # Pin explícito é promessa: sem yt-dlp dentro, nada de voltar ao PATH.
        raise ValueError(
            f"GB_VENV_PATH: {base} não contém yt-dlp (procurado em "
            + ", ".join(LAYOUTS)
            + "). Instale o yt-dlp nessa venv ou remova a variável."
        )
    return None


def _log_tool_path(source):
    logs.event(_log, logging.DEBUG, "tool_path", tool="yt-dlp", source=source)


def _log_sleep_settings_once(requests, low, high):
    """`ytdlp_sleep` once per process: every `command()` call would repeat the same line."""
    global _sleep_logged  # noqa: PLW0603 - module-level once-per-process cache, intentional
    if _sleep_logged:
        return
    _sleep_logged = True
    logs.event(_log, logging.DEBUG, "ytdlp_sleep", requests=requests, min=low, max=high)


def command():
    # Same lookup order `local_ytdlp()` uses internally (env pin, then venv, then PATH);
    # read here too only to classify which one supplied the binary, for `tool_path`.
    pinned = executable_override("GB_YTDLP_PATH")
    local = local_ytdlp()
    exe = str(local) if local else shutil.which("yt-dlp")
    if not exe:
        raise ProviderError(
            "yt-dlp ausente: execute bash scripts/install.sh (ou install.ps1) na raiz da skill/plugin; "
            "após /plugin update é preciso reinstalar. Confira com python3 scripts/gb.py doctor."
        )
    _log_tool_path("env" if pinned else "venv" if local else "path")
    requests, low, high = sleep_settings()
    _log_sleep_settings_once(requests, low, high)
    # --no-warnings would hide exactly the rate-limit/PO-token/fallback warnings we want to surface.
    args = [
        exe,
        "--ignore-config",
        "--no-playlist",
        "--no-progress",
        "--socket-timeout",
        "20",
        "--retries",
        "1",
        "--fragment-retries",
        "1",
        "--sleep-requests",
        str(requests),
        "--sleep-interval",
        str(low),
        "--max-sleep-interval",
        str(high),
    ]
    if shutil.which("deno"):
        args += ["--js-runtimes", "deno"]
    elif shutil.which("node"):
        args += ["--js-runtimes", "node"]
    return args


def _with_tail(message, stderr):
    tail = stderr_tail(stderr)
    return f"{message}; stderr: {tail}" if tail else message


# "login"/"sign in" alone is too broad (matches unrelated text); only these phrases mean auth is required.
_LOGIN_RE = re.compile(r"sign in to confirm|login required", re.IGNORECASE)
# Anchored to real HTTP 429 context, not any standalone "429" (e.g. an ffmpeg "fps= 429" counter).
_RATE_RE = re.compile(r"http error 429|429[:\s]+too many requests|rate.?limit", re.IGNORECASE)
# "\bremoved\b" alone also matched yt-dlp's own "removed temporary file" cleanup message;
# require it to describe the video itself, not an unrelated file operation.
_UNAVAILABLE_RE = re.compile(r"\bprivate\b|\bunavailable\b|\bvideo (?:has been |was )?removed\b", re.IGNORECASE)


def _classify_ytdlp_error(exc):
    stderr = exc.stderr or ""
    detail = stderr.lower()
    if _RATE_RE.search(detail):
        category = "rate_limit"
        message = "limite de requisições da fonte (429); aguarde e tente de novo"
    elif "ip address is blocked" in detail:
        category = "ip_blocked"
        message = "A fonte bloqueou o IP desta rede para esse post; download não concluído."
    elif "not available in your country" in detail:
        category = "geo_block"
        message = "Vídeo bloqueado geograficamente (geo-block) para esta região."
    elif "requested format is not available" in detail:
        category = "format_unavailable"
        message = "Formato solicitado não está disponível para esta fonte."
    elif "unsupported url" in detail:
        category = "unsupported_url"
        message = "URL não suportada por yt-dlp."
    elif _LOGIN_RE.search(detail):
        category = "login_required"
        message = "A fonte exige uma sessão de acesso. Use o navegador autorizado conforme o guia da plataforma."
    elif _UNAVAILABLE_RE.search(detail):
        category = "unavailable"
        message = "Vídeo indisponível, privado ou removido."
    else:
        category = "unknown"
        message = "yt-dlp não concluiu a extração; confira disponibilidade do post e siga o guia da plataforma."
    error = ProviderError(_with_tail(message, stderr))
    # Category returned alongside the error (not attached to it — ProviderError is owned
    # by http.py) so `run()` can log it as `class=` without re-parsing stderr or changing
    # the exception's message/type.
    return error, category


def _extract_warnings(stderr):
    """WARNING lines, with indented continuation lines folded into the warning they wrap."""
    warnings = []
    for raw_line in (stderr or "").splitlines():
        if raw_line.strip().upper().startswith("WARNING"):
            warnings.append(raw_line.strip())
        elif raw_line[:1].isspace() and raw_line.strip() and warnings:
            # An indented line with no "WARNING" prefix of its own is a continuation of
            # the previous warning (yt-dlp wraps long warnings this way), not a new one.
            warnings[-1] = f"{warnings[-1]} {raw_line.strip()}"
    return [redact(w) for w in warnings]


def _log_subprocess(op, started, *, status, exit_code):
    logs.event(
        _log,
        logging.INFO if status == "ok" else logging.WARNING,
        "subprocess",
        tool="yt-dlp",
        op=op,
        ms=round((time.monotonic() - started) * 1000),
        status=status,
        exit=exit_code,
    )


def run(arguments, timeout=180, *, op=None):
    """Run one yt-dlp invocation. `op` is an optional short label (e.g. "search",
    "metadata") used only for the `event=subprocess` log line; omitting it changes
    nothing about how the command runs."""
    cmd = command() + arguments
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:
        _log_subprocess(op, started, status="error", exit_code=None)
        raise ProviderError(f"yt-dlp excedeu {timeout}s; a fonte pode estar lenta ou bloqueando.") from exc
    except subprocess.CalledProcessError as exc:
        classified, category = _classify_ytdlp_error(exc)
        logs.event(
            _log,
            logging.WARNING,
            "ytdlp_error",
            **{"class": category},
            provider="yt-dlp",
        )
        _log_subprocess(op, started, status="error", exit_code=exc.returncode)
        raise classified from exc
    except FileNotFoundError as exc:
        _log_subprocess(op, started, status="error", exit_code=None)
        name = exc.filename or (cmd[0] if cmd else "yt-dlp")
        raise ProviderError(
            f"{name} não encontrado: execute bash scripts/install.sh (ou install.ps1) na raiz da skill/plugin."
        ) from exc
    except PermissionError as exc:
        _log_subprocess(op, started, status="error", exit_code=None)
        name = exc.filename or (cmd[0] if cmd else "yt-dlp")
        raise ProviderError(f"Permissão negada ao executar {name}.") from exc
    except (subprocess.SubprocessError, OSError) as exc:
        _log_subprocess(op, started, status="error", exit_code=None)
        raise ProviderError(
            "yt-dlp não concluiu: confira dependências, disponibilidade do vídeo e sessão exigida pela fonte. Para Instagram, use o fluxo navegador → pares CDN descrito em docs/GUIDE.md."
        ) from exc
    _log_subprocess(op, started, status="ok", exit_code=proc.returncode)
    return proc.stdout, _extract_warnings(proc.stderr)


def search(query, limit):
    raw, warnings = run(["--flat-playlist", "--dump-single-json", f"ytsearch{limit}:{query}"], timeout=60, op="search")
    for w in warnings:
        record_warning("YTDLP_WARNING", w)
    try:
        data = json.loads(raw)
        return [r for r in data.get("entries", []) if isinstance(r, dict)]
    except (ValueError, AttributeError):
        raise ProviderError("yt-dlp retornou metadados inválidos.") from None


SUBTITLE_LANGS = ("pt", "en")


def _language_from(name):
    """`probe.pt.vtt` → `pt`; `probe.pt-BR.vtt` → `pt-BR`."""
    parts = Path(name).name.split(".")
    return parts[-2] if len(parts) >= 3 else "und"  # noqa: PLR2004 - "nome.idioma.vtt": pelo menos 3 partes (ver exemplo acima)


# Teto da lista de idiomas na resposta: o YouTube anuncia centenas de traduções
# automáticas, e despejar tudo isso afoga a informação que interessa.
MAX_SUBTITLE_LANGS = 10


def _write_private(path, text):
    """Cria o VTT já com 0600 e sem sobrescrever nada: `O_CREAT|O_EXCL`, como na biblioteca.

    Escrever e só depois chamar `chmod` deixaria uma janela de leitura pública, e
    escreveria através de um arquivo (ou link) plantado com esse nome.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with open(  # noqa: PTH123 - wraps an os.open() fd (explicit O_CREAT|O_EXCL flags/mode), no Path equivalent
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
        "w",
        encoding="utf-8",
    ) as stream:
        stream.write(text)


def _original_language(data):
    """Prefer declared audio language; multiple dubbed *-orig tracks are ambiguous."""
    from .inspecting import base_language

    automatic = data.get("automatic_captions") or {}
    originals = [
        code
        for code, tracks in automatic.items()
        if str(code).lower().endswith("-orig")
        or any("original" in str((track or {}).get("name") or "").lower() for track in tracks or [])
    ]
    declared = data.get("language")
    if base_language(declared):
        return next((code for code in originals if base_language(code) == base_language(declared)), declared)
    bases = {base_language(code) for code in originals}
    return originals[0] if len(bases) == 1 and None not in bases else None


MAX_SUBTITLE_DOWNLOADS = 3


def select_subtitle_tracks(data, langs):
    """One track per requested language plus the original; bounded unknown fallback."""
    from .inspecting import base_language

    manual = data.get("subtitles") or {}
    automatic = data.get("automatic_captions") or {}
    original = _original_language(data)
    spoken = base_language(original)
    selected = []

    def pick(wanted):
        base = base_language(wanted)
        for kind, available in (("manual", manual), ("automatic", automatic)):
            matches = [code for code, tracks in available.items() if tracks and base_language(code) == base]
            matches.sort(
                key=lambda code: (
                    code != original,
                    not code.lower().endswith("-orig") if kind == "automatic" else False,
                    code.lower().replace("_", "-") != wanted.lower().replace("_", "-"),
                    code != base,
                    code,
                )
            )
            if matches:
                return {"language": matches[0], "kind": kind, "is_original": base == spoken if spoken else None}
        return None

    # Without an explicit query language, the original takes precedence over PT/EN.
    wanted = [*langs, original] if langs else [original] if original else SUBTITLE_LANGS
    for code in wanted:
        if not code:
            continue
        track = pick(code)
        if track and track not in selected:
            selected.append(track)
    if not selected and not spoken:
        for kind, available in (("manual", manual), ("automatic", automatic)):
            codes = sorted(code for code, tracks in available.items() if tracks and code != "live_chat")
            if codes:
                selected.append({"language": codes[0], "kind": kind, "is_original": None})
                break
    return selected[:MAX_SUBTITLE_DOWNLOADS]


def relevant_langs(data, langs):
    """Idiomas que valem listar, e quantos a fonte anuncia ao todo.

    Os pedidos em `langs` mais o original; nunca as centenas de traduções automáticas
    que o YouTube gera sob demanda. Sem nenhum desses, os primeiros da lista servem
    de amostra, para ninguém achar que a fonte não tem legenda.
    """
    manual = set(data.get("subtitles") or {})
    automatic = set(data.get("automatic_captions") or {})
    every = sorted(manual | automatic)
    from .inspecting import base_language

    listed = []
    for requested in langs:
        listed.extend(code for code in every if base_language(code) == base_language(requested) and code not in listed)
    original = _original_language(data)
    if original in (manual | automatic) and original not in listed:
        listed.append(original)
    if not listed:
        listed = every[:MAX_SUBTITLE_LANGS]
    return listed[:MAX_SUBTITLE_LANGS], len(every)


def source_limitations(data):
    """Item limits yt-dlp actually reports. A missing field stays unknown.

    `age_limit` must be a real int: `bool` is an int subclass, and `True` is not an age.
    """
    if not isinstance(data, dict):
        return []
    found = []
    availability = data.get("availability")
    if isinstance(availability, str) and availability not in ("", "public"):
        found.append(f"availability: {availability}")
    age = data.get("age_limit")
    if type(age) is int and age > 0:
        found.append(f"age_limit: {age}")
    live = data.get("live_status")
    if live in ("is_live", "is_upcoming", "post_live"):
        found.append(f"live_status: {live}")
    return found


def metadata(url):
    """Título, autoria e duração da página, num pedido só e sem baixar mídia.

    É o mínimo que o C2 precisa para listar canal e duração, e `probe_remote` seria
    caro demais aqui: ele ainda escreve as legendas em disco. Falhar não é erro — a
    URL continua registrável —, então o chamador recebe `{}` e segue.
    """
    from .providers import resolve

    # Só páginas reconhecidas, nunca uma URL qualquer vinda do chat.
    resolve(url)
    try:
        raw, warnings = run(["--dump-single-json", "--skip-download", "--", url], timeout=60, op="metadata")
    except (ProviderError, OSError) as exc:
        record_warning("YTDLP_WARNING", f"metadados não vieram desta página: {exc}")
        return {}
    for w in warnings:
        record_warning("YTDLP_WARNING", w)
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    duration = data.get("duration")
    # `uploader_id` do TikTok já vem como `@handle`; o do YouTube é o id do canal.
    handle = data.get("uploader_id") or data.get("channel_id")
    return {
        "title": data.get("title") or data.get("fulltitle") or None,
        "creator": data.get("uploader") or data.get("channel") or None,
        "handle": str(handle) if handle else None,
        "creator_url": data.get("uploader_url") or data.get("channel_url") or None,
        "duration_s": float(duration) if isinstance(duration, (int, float)) else None,
        "limitations": source_limitations(data),
    }


def _validate_transport(url, source_url=None):
    from .providers import resolve

    if source_url is None:
        resolve(url)
    else:
        source = resolve(source_url, catalog_file=url)
        if source["provider"] != "ec_audiovisual" or source.get("media_url") != url:
            raise ProviderError("Transport must match the selected public EC media representation.")


def _obtain_subtitles(raw, tracks, url, cache, *, manual=True):
    """Download exact selected tracks from saved metadata and record actual text."""
    from .inspecting import parse_vtt, parse_vtt_language

    subtitles = {}
    subtitle_warnings = []
    with tempfile.TemporaryDirectory(dir=str(cache) if cache else None) as work:
        info = Path(work) / "probe.info.json"
        _write_private(info, raw)
        try:
            _, warnings = run(
                [
                    "--ignore-errors",
                    "--no-simulate",
                    "--skip-download",
                    "--load-info-json",
                    str(info),
                    "--write-subs" if manual else "--no-write-subs",
                    "--write-auto-subs",
                    "--sub-langs",
                    ",".join(re.escape(track["language"]) for track in tracks),
                    "--sub-format",
                    "vtt",
                    "-o",
                    str(Path(work) / "probe.%(ext)s"),
                    "--quiet",
                    "--no-warnings",
                ],
                timeout=60,
            )
        except (ProviderError, OSError) as error:
            # Metadata and any tracks already written remain useful after a failed batch.
            warnings = [f"Subtitle download failed: {redact(str(error))}"]
            subtitle_warnings.extend(warnings)
        for warning in warnings:
            record_warning("YTDLP_WARNING", warning)
        found = {_language_from(path.name): path for path in Path(work).glob("*.vtt")}
        for track in tracks:
            code = track["language"]
            path = found.get(code)
            cues = []
            if path:
                text = path.read_text(encoding="utf-8", errors="replace")
                language = parse_vtt_language(text) if code == "und" else code
                destination = None
                if cache is not None:
                    stem = hashlib.sha256(url.encode()).hexdigest()[:16]
                    destination = cache / f"{stem}-{code}.vtt"
                    logs.event(
                        _log,
                        logging.DEBUG,
                        "cache_reuse",
                        kind="subtitle",
                        status="hit" if destination.exists() else "miss",
                    )
                    _write_private(destination, text)
                cues = parse_vtt(text)
                subtitles[code] = {
                    **track,
                    "language": language or code,
                    "path": str(destination) if destination else None,
                    "cues": cues,
                }
            track["status"] = "obtained" if cues else "empty" if path else "unavailable"
            track["cue_count"] = len(cues)
            if not cues:
                subtitle_warnings.append(f"No subtitle text obtained for {code} ({track['kind']}).")
    return subtitles, subtitle_warnings


def probe_remote(url, langs=None, cache=None, *, source_url=None):  # noqa: C901 - metadata, bounded track fallback and source fields
    """Metadata first, then at most three selected subtitle tracks, without video.

    Reuse the private info JSON via --load-info-json: selection needs the available
    tracks, but must not extract the same video again or request all translations.
    Existing langs tuples remain supported; omission now prefers the original.
    """
    from .inspecting import base_language, normalize_language

    requested = tuple(normalize_language(code) for code in ((langs,) if isinstance(langs, str) else langs or ()))
    _validate_transport(url, source_url)
    cache = Path(cache) if cache is not None else None
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)
        cache.chmod(0o700)
    raw, warnings = run(["--dump-single-json", "--skip-download", "--", url], timeout=60)
    for warning in warnings:
        record_warning("YTDLP_WARNING", warning)
    try:
        data = json.loads(raw)
    except ValueError:
        raise ProviderError("yt-dlp retornou metadados inválidos.") from None
    if not isinstance(data, dict):
        raise ProviderError("yt-dlp retornou metadados inválidos.")
    tracks = [] if langs is not None and not requested else select_subtitle_tracks(data, requested)
    subtitles, subtitle_warnings = _obtain_subtitles(raw, tracks, url, cache) if tracks else ({}, [])
    # A failed author track may fall back once to the original automatic track.
    # Keep failed acquisition provenance and cap total track attempts at three.
    if len(tracks) < MAX_SUBTITLE_DOWNLOADS and any(
        track["kind"] == "manual" and track["is_original"] is True and not track["cue_count"] for track in tracks
    ):
        automatic = select_subtitle_tracks({**data, "subtitles": {}}, (_original_language(data),))
        fallback = [
            track
            for track in automatic
            if track["is_original"] is True and not subtitles.get(track["language"], {}).get("cues")
        ]
        if fallback:
            fallback = fallback[:1]
            obtained, more = _obtain_subtitles(raw, fallback, url, cache, manual=False)
            subtitles.update(obtained)
            subtitle_warnings.extend(more)
            tracks.extend(fallback)
    subtitle_warnings.extend(
        f"No subtitles advertised for requested language {code}; any fallback is a different or unknown language."
        for code in requested
        if not any(base_language(track["language"]) == base_language(code) for track in tracks)
    )
    original = _original_language(data)
    if original and langs is None and not tracks:
        subtitle_warnings.append(
            f"No subtitles advertised for original language {original}; original text is unavailable."
        )
    if tracks and not original:
        subtitle_warnings.append(
            "Original language is unknown; a fallback subtitle track does not establish the spoken language."
        )
    duration = data.get("duration")
    chapters = []
    for chapter in data.get("chapters") or []:
        if not isinstance(chapter, dict) or chapter.get("start_time") is None:
            continue
        chapters.append(
            {
                "start_s": float(chapter["start_time"]),
                "end_s": float(chapter["end_time"]) if chapter.get("end_time") is not None else None,
                "title": chapter.get("title") or "",
            }
        )
    listed, total = relevant_langs(data, requested or SUBTITLE_LANGS)
    for track in tracks:
        if track["language"] not in listed:
            listed.append(track["language"])
    listed = listed[:MAX_SUBTITLE_LANGS]
    # Qual faixa é a fala de verdade. As outras são tradução automática do YouTube, e
    # comparar a `--query` com uma delas invertia o aviso de idioma: uma fonte em
    # inglês com faixa `pt` traduzida respondia "legenda em PT" para uma query em EN.
    return {
        "url": url,
        "title": data.get("title"),
        "original_lang": str(original) if original else None,
        "duration_s": float(duration) if isinstance(duration, (int, float)) else None,
        "chapters": chapters,
        "subtitle_langs": listed,
        # Quantas faixas a fonte anuncia ao todo; `subtitle_langs` mostra só as úteis.
        "subtitle_langs_total": total,
        "description": data.get("description") or "",
        # Só o que a fonte declara: serve para avisar sobre 360°/VR antes da prévia.
        "tags": [str(tag) for tag in (data.get("tags") or []) if tag],
        "subtitles": subtitles,
        "subtitle_tracks": tracks,
        "subtitle_warnings": subtitle_warnings,
        "limitations": source_limitations(data),
    }


def download_segment(url, target, start, end, *, source_url=None):
    from .media import probe
    from .media import run as media_run

    # Only recognized social pages, never a user-provided command or arbitrary URL.
    _validate_transport(url, source_url)
    selection = "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/b"
    from urllib.parse import urlsplit

    page = urlsplit(source_url or url)
    if page.hostname == "webtv.un.org":
        from .broadcasts import LOCALES

        locale = page.path.strip("/").split("/")[0]
        if locale not in LOCALES:
            raise ProviderError("Use a supported UN Web TV locale for working media.")
        # Some Kaltura MP4 entries advertise a height but deliver audio only.
        # Prefer its identified video HLS and the requested interpretation track;
        # keep the existing direct-file route when HLS is unavailable.
        selection = f"bv[height<=1080][protocol^=m3u8]+ba[protocol^=m3u8][language={locale}]/" + selection
    if not all(math.isfinite(v) for v in (start, end)) or start < 0 or end <= start:
        raise ProviderError("Intervalo inválido para download social.")
    target = Path(target)
    if target.exists():
        raise ProviderError("Destino existente; não foi sobrescrito.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as folder:
        output = Path(folder) / "source.mp4"
        _, warnings = run(
            [
                "-f",
                selection,
                "--download-sections",
                f"*{start}-{end}",
                "--force-keyframes-at-cuts",
                "--merge-output-format",
                "mp4",
                "--remux-video",
                "mp4",
                "-o",
                str(output),
                "--",
                url,
            ],
            op="segment",
        )
        for w in warnings:
            record_warning("YTDLP_WARNING", w)
        info = probe(output)
        if abs(info["duration_s"] - (end - start)) > max(0.25, 2 / (info["fps"] or 10)):
            raise ProviderError("O trecho social não corresponde ao intervalo solicitado.")
        media_run(["ffmpeg", "-v", "error", "-i", str(output), "-f", "null", "-"])
        # Exclusive publication also protects a target created while downloading.
        with output.open("rb") as source, target.open("xb") as dest:
            try:
                shutil.copyfileobj(source, dest)
            except BaseException:
                target.unlink(missing_ok=True)
                raise
    return target


def doctor():
    return {
        "engine": "yt-dlp",
        "installed": bool(local_ytdlp() or shutil.which("yt-dlp")),
        "javascript_runtime": "deno" if shutil.which("deno") else "node" if shutil.which("node") else None,
        "youtube_api_key_required": False,
        "instagram": "Navegador/Playwright → configs vídeo+áudio → scripts/getbrolls/instagram_pairs.py",
        "scope": "Disponibilidade de executáveis; não comprova extração ao vivo nem versão/runtime EJS.",
    }
