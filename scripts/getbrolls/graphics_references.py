"""Saved media instructions shared by initial graphics authoring and revisions."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

from .config import tool_path
from .graphics_reference_video import MAX_VIDEO_BYTES, validate_measurements
from .ledger import Ledger, digest
from .runtime import project_lock

UPLOAD_PATH = "/__graphics-reference"
NAME_HEADER = "X-GetBrolls-Reference"
MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_NAME = 300
MAX_REVIEW_BYTES = 2_000_000
MAX_FILES = 8
MAX_REQUEST_BYTES = 128 * 1024 * 1024
CONTEXT_SCHEMA = 2
ACTIVE_CONTEXT_SCHEMA = 3
INTERVAL_TOLERANCE = 0.02
REF_RE = re.compile(r"graphics-data/references/([0-9a-f]{64})\.(png|jpg|mp4)\Z")


def _g():
    from . import graphics

    return graphics


def assignment_signature(occ):
    g = _g()
    return g._payload_hash({key: occ.get(key) for key in g.ASSIGNMENT_FIELDS if key != "reference_context"})


def validate_reference(ref):  # noqa: C901 - legacy shape and typed image/video measurements share one identity boundary.
    keys = {"ref", "sha256", "name", "bytes", "width", "height", "kind"}
    if isinstance(ref, dict) and ref.get("kind") == "video":
        keys |= {"duration_s", "fps", "codec"}
    if isinstance(ref, dict) and "label" in ref:
        keys.add("label")
        if not isinstance(ref["label"], str) or not re.fullmatch(r"R[1-8]", ref["label"]):
            raise ValueError("Invalid reference label.")
    if not isinstance(ref, dict) or set(ref) != keys:
        raise ValueError("Invalid saved media reference.")
    match = REF_RE.fullmatch(ref.get("ref", "")) if isinstance(ref.get("ref"), str) else None
    if (
        not match
        or match[1] != ref.get("sha256")
        or ref.get("kind") not in ("image", "video")
        or (match[2] == "mp4") != (ref["kind"] == "video")
    ):
        raise ValueError("Invalid media reference identity.")
    name = ref.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME or re.search(r"[\x00-\x1f\x7f]", name):
        raise ValueError("The reference needs a valid display name (at most 300 characters).")
    for key in ("bytes", "width", "height"):
        if type(ref.get(key)) is not int or ref[key] <= 0:
            raise ValueError("Invalid image reference measurements.")
    if ref["kind"] == "video":
        if ref["bytes"] > MAX_VIDEO_BYTES:
            raise ValueError("Video reference exceeds 64 MiB.")
        validate_measurements(ref)
    elif ref["bytes"] > MAX_IMAGE_BYTES or ref["width"] * ref["height"] > MAX_IMAGE_PIXELS:
        raise ValueError("Image reference exceeds the supported size.")


def reference_fields(record):
    """Preserve absent and singular legacy identities exactly."""
    return {key: copy.deepcopy(record[key]) for key in ("reference", "references") if record.get(key) is not None}


def references(record):
    fields = reference_fields(record)
    if len(fields) > 1:
        raise ValueError("Use one canonical reference collection, not both legacy and plural fields.")
    if "reference" in fields:
        validate_reference(fields["reference"])
        if fields["reference"]["kind"] != "image" or "label" in fields["reference"]:
            raise ValueError(
                "Legacy singular references support only unlabelled still images; use references for video."
            )
        return [fields["reference"]]
    if not fields:
        return []
    values = fields["references"]
    minimum = (
        0
        if "reference_change" in record
        or "referenceBase" in record
        or record.get("schema_version") == ACTIVE_CONTEXT_SCHEMA
        else 1
    )
    if not isinstance(values, list) or not minimum <= len(values) <= MAX_FILES:
        raise ValueError("A reference request needs 1–8 attachments.")
    labels = set()
    for ref in values:
        validate_reference(ref)
        if not ref.get("label") or ref["label"] in labels:
            raise ValueError("Preserve unique stable reference labels, including gaps after draft removal.")
        labels.add(ref["label"])
    if sum(ref["bytes"] for ref in values) > MAX_REQUEST_BYTES:
        raise ValueError("A reference request may contain at most 128 MiB in total.")
    return values


def checked_references(root, record):
    values = references(record)
    for ref in values:
        checked_image(root, ref)
    return values


def checked_image(root, ref):
    validate_reference(ref)
    path = _g()._confine_existing(root, ref["ref"], prefixes=("graphics-data/",))
    if path.stat().st_size != ref["bytes"] or digest(path) != ref["sha256"]:
        raise ValueError("Saved reference bytes changed; preserve the request and supply the correct media.")
    if ref["kind"] == "video":
        from .graphics_reference_video import probe

        try:
            measured = probe(path, decode=False)
        except (OSError, subprocess.SubprocessError, ZeroDivisionError) as exc:
            raise ValueError("The saved video cannot be measured within the processing limit.") from exc
        if any(ref[key] != value for key, value in measured.items()):
            raise ValueError("Saved video measurements no longer match its actual original bytes.")
    return path


def validate_context(context):
    if context is None:
        return
    if isinstance(context, dict) and context.get("schema_version") == ACTIVE_CONTEXT_SCHEMA:
        from .graphics_reference_context import validate_context as validate_active_context

        validate_active_context(context)
        return
    if isinstance(context, dict) and context.get("schema_version") == CONTEXT_SCHEMA:
        _validate_plural_context(context)
        return
    if not isinstance(context, dict) or set(context) != {"request_id", "prompt", "analysis", "reference"}:
        raise ValueError("Invalid graphics reference context.")
    g = _g()
    if (
        not g._valid_id(context["request_id"])
        or not g._bounded_prose(context["prompt"])
        or not g._bounded_prose(context["analysis"])
    ):
        raise ValueError("A reference context needs its request, prompt and actual analysis.")
    references(context)


def _validate_plural_context(context):
    g = _g()
    keys = {"schema_version", "request_id", "prompt", "references", "analyses"}
    if "composition" in context:
        keys.add("composition")
    if (
        set(context) != keys
        or not g._valid_id(context.get("request_id"))
        or not g._bounded_prose(context.get("prompt"))
    ):
        raise ValueError("Invalid mixed-reference context.")
    refs = references(context)
    analyses = context.get("analyses")
    if not isinstance(analyses, list) or len(analyses) != len(refs):
        raise ValueError("Explain the use and inspection limits of every labelled reference.")
    for ref, analysis in zip(refs, analyses, strict=True):
        expected = {"label", "analysis", "limitations"} | ({"inspection"} if ref["kind"] == "video" else set())
        if (
            not isinstance(analysis, dict)
            or set(analysis) != expected
            or analysis.get("label") != ref["label"]
            or not g._bounded_prose(analysis.get("analysis"))
            or not g._bounded_prose(analysis.get("limitations"))
        ):
            raise ValueError("Every reference needs its own actual analysis and stated inspection limits.")
        if ref["kind"] == "video":
            from .graphics_reference_video import validate_inspection

            inspection = analysis["inspection"]
            validate_inspection(inspection)
            if (
                not isinstance(inspection, dict)
                or inspection.get("request_id") != context["request_id"]
                or inspection.get("label") != ref["label"]
                or inspection.get("source_sha256") != ref["sha256"]
                or not g._bounded_prose(inspection.get("wording"))
                or inspection["wording"] not in context["prompt"]
                or not all(
                    type(inspection.get(k)) in (float, int) and math.isfinite(inspection[k])
                    for k in ("start_s", "end_s")
                )
                or not 0 <= inspection["start_s"] < inspection["end_s"] <= ref["duration_s"]
                or (inspection["whole"] and (inspection["start_s"] != 0 or inspection["end_s"] != ref["duration_s"]))
            ):
                raise ValueError("Video analysis must bind actual temporal evidence for the requested interval.")
    if "composition" in context:
        item = context["composition"]
        if (
            not isinstance(item, dict)
            or set(item) != {"label", "instruction", "background"}
            or item.get("label") not in [r["label"] for r in refs]
            or not g._bounded_prose(item.get("instruction"))
            or item["instruction"] not in context["prompt"]
            or not isinstance(item.get("background"), dict)
        ):
            raise ValueError("Actual inclusion needs a specific saved reference and explicit original instruction.")


def context_matches(request, assignment):
    context = assignment.get("reference_context") or {}
    if not reference_fields(request):
        return True
    if request.get("reference_change") and context.get("active_state_sha256") != request["reference_change"]["result"]:
        return False
    shared_id = request.get("shared_request_id") or (
        request["id"] if request.get("reference_change") and request.get("scope") == "shared" else None
    )
    if shared_id and (context.get("shared_scope") or {}).get("request_id") != shared_id:
        return False
    if (
        request.get("reference_application")
        and (context.get("shared_scope") or {}).get("application") != request["reference_application"]
    ):
        return False
    if (
        context.get("request_id") != request["id"]
        or context.get("prompt") != request["text"]
        or reference_fields(context) != reference_fields(request)
    ):
        return False
    composition = context.get("composition")
    return not composition or assignment.get("background") == composition["background"]


def initial_rows(graphics, project):
    g = _g()
    rows = []
    for occ in graphics.get("occurrences", {}).values():
        if any(
            v.get("status") == "complete" and v.get("occurrence_id") == occ["occurrence_id"]
            for v in graphics.get("versions", {}).values()
        ):
            continue
        signature = assignment_signature(occ)
        requests = [
            r
            for r in g._public_requests(graphics)
            if r.get("occurrence_id") == occ["occurrence_id"]
            and r.get("kind") == "authoring"
            and r.get("content_sha256") == signature
        ]
        latest = requests[-1] if requests else {}
        rows.append(
            {
                "id": "graphics:" + occ["occurrence_id"] + ":initial",
                "project": project,
                "scene_id": occ["scene_id"],
                "occurrence_id": occ["occurrence_id"],
                "version": None,
                "initial": True,
                "current": True,
                "signature": signature,
                "reviewEpoch": signature,
                "state": "changes" if latest else "pending",
                "comment": latest.get("text", ""),
                **({"requestId": latest["id"]} if latest else {}),
                **reference_fields(latest),
                **(
                    {
                        key: latest[key]
                        for key in ("reference_change", "reference_application", "shared_request_id")
                        if key in latest
                    }
                ),
                **({"referenceBase": latest["reference_change"]["base"]} if latest.get("reference_change") else {}),
                "scope": latest.get("scope", "scene"),
                "requests": requests,
                "context": {"narration": occ.get("narration"), "timing": occ.get("timing")},
            }
        )
    return rows


def target(ledger, row, *, epoch=True):
    g = _g()
    if row.get("project") != ledger.data.get("project_id"):
        raise ValueError("Reference belongs to another project. Regenerate this Storyboard.")
    graphics = ledger.data.get("graphics") or {}
    occ = (
        graphics.get("occurrences", {}).get(row["occurrence_id"]) if isinstance(row.get("occurrence_id"), str) else None
    )
    if not isinstance(occ, dict) or occ.get("scene_id") != row.get("scene_id"):
        raise ValueError("Reference target no longer exists.")
    if row.get("initial") is True:
        if occ.get("current_version") or assignment_signature(occ) != row.get("signature"):
            raise ValueError(
                "Planned scene changed or now has a version. Regenerate Storyboard; no retargeting occurred."
            )
        if row.get("version") is not None or row.get("id") != "graphics:" + occ["occurrence_id"] + ":initial":
            raise ValueError("Invalid initial reference target.")
    else:
        version = graphics.get("versions", {}).get(row["version"]) if isinstance(row.get("version"), str) else None
        if (
            not isinstance(version, dict)
            or version.get("status") != "complete"
            or version.get("occurrence_id") != occ["occurrence_id"]
        ):
            raise ValueError("Reviewed reference version is missing or incomplete.")
        if g.graphics_content_sha256(version) != row.get("signature"):
            raise ValueError("Reviewed version content changed.")
        if epoch and g.graphics_review_epoch(version) != row.get("reviewEpoch"):
            raise ValueError("Version review changed. Regenerate Storyboard before adding a reference.")
        if occ.get("current_version") != version["id"] or g._assignment_changed(version["assignment"], occ):
            raise ValueError("Reference target is stale. Select the actual version/context before processing.")
    return occ


def _probe(path, extension):
    result = subprocess.run(  # noqa: S603 - pinned executable, fixed argv; input is a confined staged file.
        [tool_path("ffprobe"), "-v", "error", "-show_streams", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    streams = json.loads(result.stdout).get("streams", [])
    if len(streams) != 1 or streams[0].get("codec_name") != {"png": "png", "jpg": "mjpeg"}[extension]:
        raise ValueError("Supply a PNG or JPEG still image.")
    width, height = streams[0].get("width", 0), streams[0].get("height", 0)
    if not width or not height or width * height > MAX_IMAGE_PIXELS:
        raise ValueError("Image reference must contain at most 20 megapixels.")
    subprocess.run(  # noqa: S603 - pinned decoder and fixed flags, no shell or user-provided options.
        [tool_path("ffmpeg"), "-v", "error", "-xerror", "-i", str(path), "-frames:v", "1", "-f", "null", "-"],
        check=True,
        capture_output=True,
        timeout=15,
    )
    return width, height


def upload(directory, stream, length, metadata):  # noqa: C901, PLR0912, PLR0915 - serialized bounded transfer, target/base checks, decode and atomic publication.
    """Bounded raw media transfer; no request, analysis or manifest mutation."""
    kind = metadata.get("kind", "image")
    if kind not in ("image", "video") or not 0 < length <= (MAX_VIDEO_BYTES if kind == "video" else MAX_IMAGE_BYTES):
        raise ValueError("Supply PNG/JPEG up to 16 MiB or MP4/H.264 up to 64 MiB.")
    directory = Path(directory)
    with project_lock(directory.parent):
        ledger = Ledger(directory.parent, recover=False)
        if ledger.pending.exists():
            raise ValueError("A project write is pending. Finish it with the CLI before saving references.")
        target(ledger, metadata)
        if "referenceBase" in metadata:
            from .graphics_reference_context import active

            if active(ledger.data["graphics"], metadata["occurrence_id"])[0] != metadata["referenceBase"]:
                raise ValueError("Active references changed. Reopen the scene before uploading this draft.")
        name = metadata.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME or re.search(r"[\x00-\x1f\x7f]", name):
            raise ValueError("Invalid reference display name.")
        folder = _g()._confine_planned(directory, directory / "graphics-data" / "references")
        folder.mkdir(parents=True, exist_ok=True)
        staged = None
        try:
            with tempfile.NamedTemporaryFile(dir=folder, prefix=".upload-", delete=False) as output:
                staged = Path(output.name)
                remaining = length
                sha = hashlib.sha256()
                while remaining:
                    chunk = stream.read(min(65536, remaining))
                    if not chunk:
                        raise ValueError("Incomplete media transfer; the request was not saved.")
                    output.write(chunk)
                    sha.update(chunk)
                    remaining -= len(chunk)
                output.flush()
                os.fsync(output.fileno())
            with staged.open("rb") as source:
                header = source.read(32)
            extension = (
                "png"
                if header.startswith(b"\x89PNG\r\n\x1a\n")
                else "jpg"
                if header.startswith(b"\xff\xd8\xff")
                else "mp4"
                if header[4:8] == b"ftyp"
                else None
            )
            if extension is None or (extension == "mp4") != (kind == "video"):
                raise ValueError("The actual media must match the declared image or MP4 kind.")
            if kind == "video":
                from .graphics_reference_video import probe

                measurements = probe(staged)
            else:
                width, height = _probe(staged, extension)
                measurements = {"width": width, "height": height}
            sha256 = sha.hexdigest()
            ref = {
                "ref": f"graphics-data/references/{sha256}.{extension}",
                "sha256": sha256,
                "kind": kind,
                "name": name,
                "bytes": length,
                **measurements,
            }
            validate_reference(ref)
            destination = _g()._confine_planned(directory, directory / ref["ref"])
            # Same-directory hard link publishes complete bytes without overwriting
            # an existing identity or leaving a partially copied canonical asset.
            try:
                os.link(staged, destination)
            except FileExistsError:
                checked_image(directory, ref)
            checked_image(directory, ref)
            return ref
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError, ZeroDivisionError) as exc:
            raise ValueError(
                "Media transfer/probe failed or exceeded its processing limit; preserve the draft and retry with supported media."
            ) from exc
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)


def save_review(directory, data, save):
    """Validate complete reference submissions, retaining the ordinary JSON exchange."""
    graphics_rows = data.get("graphics")
    if not isinstance(graphics_rows, list):
        return save(directory, data)
    rows = [
        row
        for row in graphics_rows
        if isinstance(row, dict) and (reference_fields(row) or row.get("initial") or "referenceBase" in row)
    ]
    if not rows:
        return save(directory, data)
    with project_lock(Path(directory).parent):
        ledger = Ledger(Path(directory).parent, recover=False)
        from .review import REVIEW_TEMPLATE_VERSION

        if (
            data.get("project") != ledger.data.get("project_id")
            or data.get("type") != "getbrolls-review"
            or data.get("templateVersion") != REVIEW_TEMPLATE_VERSION
        ):
            raise ValueError("Reference review envelope belongs to another project or format.")
        if ledger.pending.exists():
            raise ValueError("A project write is pending; finish it before saving references.")
        existing = _existing_review(directory, data)
        if existing:
            for row in rows:
                checked_references(directory, row)
            return existing
        _validate_review_rows(ledger, rows)
        return save(directory, data, identity=_submission_identity(data))


def _validate_review_rows(ledger, rows):
    for row in rows:
        if "referenceBase" in row and row.get("state") == "changes":
            from .graphics_reference_context import check_row

            check_row(ledger, row, replay=True)
            continue
        if row.get("state") == "pending" and not reference_fields(row):
            continue
        if (
            row.get("state") != "changes"
            or not _g()._bounded_prose(row.get("comment"))
            or row.get("scope", "scene") != "scene"
        ):
            raise ValueError("A saved reference needs a scene-local change request and a nonblank prompt.")
        if not checked_references(ledger.root, row):
            raise ValueError("Save at least one reference with this authoring request.")
        target(ledger, row)


def _submission_identity(data):
    return _g()._payload_hash({k: v for k, v in data.items() if k != "exportedAt"})


def _existing_review(directory, data):
    folder = _g()._confine_planned(directory, Path(directory) / "reviews")
    canonical = {k: v for k, v in data.items() if k != "exportedAt"}
    stable = folder / ("references-" + _submission_identity(data) + ".json")
    if stable.exists() or stable.is_symlink():
        stable = _g()._confine_existing(
            Path(directory), stable.relative_to(directory).as_posix(), prefixes=("reviews/",)
        )
        if stable.stat().st_size > MAX_REVIEW_BYTES:
            raise ValueError("Saved submission changed; preserve it before retrying.")
        previous = json.loads(stable.read_text(encoding="utf-8"))
        if not isinstance(previous, dict) or {k: v for k, v in previous.items() if k != "exportedAt"} != canonical:
            raise ValueError("Conflicting saved submission; nothing was overwritten.")
        return stable
    for path in sorted(folder.glob("[0-9]*.json"), reverse=True)[:32]:
        if path.is_symlink() or path.stat().st_size > MAX_REVIEW_BYTES:
            continue
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(previous, dict) and {k: v for k, v in previous.items() if k != "exportedAt"} == canonical:
                return path
        except (ValueError, OSError):
            continue
    return None


def served_image(directory, filename):  # noqa: C901 - manifest and durable/legacy submission claims share one narrow original-file alias.
    """Only originals claimed by this project's saved reviews/manifest are public."""
    refpath = "graphics-data/references/" + filename
    if not REF_RE.fullmatch(refpath):
        raise ValueError("Unknown saved reference.")
    ledger = Ledger(Path(directory).parent, recover=False)
    records = list((ledger.data.get("graphics") or {}).get("requests") or [])
    folder = _g()._confine_planned(directory, Path(directory) / "reviews")
    for path in [*folder.glob("references-*.json"), *sorted(folder.glob("[0-9]*.json"), reverse=True)[:32]]:
        if path.is_symlink() or path.stat().st_size > MAX_REVIEW_BYTES:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if path.name.startswith("references-") and path.stem != "references-" + _submission_identity(payload):
                continue
            if payload.get("project") == ledger.data.get("project_id") and isinstance(payload.get("graphics"), list):
                records.extend(payload.get("graphics", []))
        except (ValueError, OSError, AttributeError):
            continue
    for row in records:
        try:
            for ref in references(row) if isinstance(row, dict) else []:
                if ref["ref"] == refpath:
                    return checked_image(directory, ref)
        except ValueError:
            continue
    raise ValueError("The media has not been saved with a project request.")


def import_initial(ctx, row):
    g = _g()
    ident = g._graphics_row_id(ctx, row)
    if ident is None:
        return
    try:
        if row.get("project") != ctx["project_id"]:
            raise ValueError("Initial reference row belongs to another project.")
        if row.get("state") == "pending":
            # An untouched planned card is not a decision. It must not turn a
            # refused alignment/candidate import into a successful no-op.
            return
        if (
            row.get("state") != "changes"
            or not g._bounded_prose(row.get("comment"))
            or row.get("scope", "scene") != "scene"
        ):
            raise ValueError("Initial authoring needs a scene-local prompt and saved references, not approval.")
        if not checked_references(ctx["root"], row):
            raise ValueError("Initial authoring requires saved references.")
        payload = {
            "project_id": ctx["project_id"],
            "scene_id": row.get("scene_id"),
            "occurrence_id": row.get("occurrence_id"),
            "reviewed_version": None,
            "content_sha256": row.get("signature"),
            "text": row["comment"].strip(),
            "scope": "scene",
            "kind": "authoring",
            **reference_fields(row),
        }
        request_id = g.derive_request_id(payload)
        existing = g._lookup_request(ctx["working"], request_id)
        if existing:
            if g._request_identity(existing) != payload:
                raise ValueError("Conflicting saved reference request identity.")
            ctx["unchanged"].append({"id": ident, "reason": "existing_request"})
            return
        ledger = SimpleNamespace(data={"graphics": ctx["working"], "project_id": ctx["project_id"]})
        target(ledger, row)
        ctx["working"].setdefault("requests", []).append(
            {**payload, "id": request_id, "state": "saved", "processing": None}
        )
        ctx["applied"].append(ident)
    except (ValueError, OSError) as exc:
        g._skip_row(ctx["skipped"], ident, "invalid_reference", str(exc))


def stale_initial(req, graphics):
    occ = graphics.get("occurrences", {}).get(req.get("occurrence_id"))
    if not isinstance(occ, dict) or occ.get("current_version"):
        return "stale_target"
    if reference_fields(req) and context_matches(req, occ):
        return None
    if assignment_signature(occ) != req.get("content_sha256"):
        return "assignment_mismatch"
    return None


def apply_command(ledger, args):
    g = _g()
    graphics = ledger.data.get("graphics") or {}
    req = g._find_request(graphics, args.request)
    if req.get("reference_change"):
        from .graphics_reference_context import apply_command as apply_active

        return apply_active(ledger, args)
    if not reference_fields(req) or req.get("state") == "processed":
        raise ValueError("Select an unprocessed saved reference request.")
    checked_references(ledger.root, req)
    occ = graphics["occurrences"][req["occurrence_id"]]
    if req.get("references") is not None:
        context = _analysis_context(ledger, req, occ, args)
    else:
        if not g._bounded_prose(args.analysis) or getattr(args, "file", None):
            raise ValueError("Record --analysis after inspecting the actual saved image.")
        context = {
            "request_id": req["id"],
            "prompt": req["text"],
            "analysis": args.analysis.strip(),
            "reference": copy.deepcopy(req["reference"]),
        }
    validate_context(context)
    if occ.get("reference_context") == context and (
        not context.get("composition") or occ.get("background") == context["composition"]["background"]
    ):
        return {"reference_context": context, "idempotent": True, "render_started": False}
    if g._request_stale_reason(req, graphics):
        raise ValueError("Reference request is stale; restore its actual target before authoring.")
    occ["reference_context"] = context
    if context.get("composition"):
        occ["background"] = copy.deepcopy(context["composition"]["background"])
    ledger.save("graphics-reference-apply")
    return {"reference_context": context, "idempotent": False, "render_started": False}


def inspect_command(ledger, args):
    from .graphics_reference_video import inspect

    g = _g()
    graphics = ledger.data.get("graphics") or {}
    request = g._find_request(graphics, args.request)
    if request.get("state") == "processed" or g._request_stale_reason(request, graphics):
        raise ValueError("Inspect the actual unprocessed reference target; no retargeting occurred.")
    ref = next((ref for ref in references(request) if ref.get("label") == args.label), None)
    if ref is None or ref["kind"] != "video":
        raise ValueError("Select a saved video label from this request.")
    return {"inspection": inspect(ledger.root, request, ref, args), "render_started": False}


def _analysis_context(ledger, req, occ, args):
    from .graphics_reference_video import checked_inspection

    if not getattr(args, "file", None) or args.analysis:
        raise ValueError("Mixed references require --file with one actual analysis and inspection limits per label.")
    path = Path(args.file)
    if path.stat().st_size > MAX_REVIEW_BYTES:
        raise ValueError("Analysis file exceeds 2 MB.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) - {"analyses", "composition"}:
        raise ValueError("Analysis file accepts analyses and optional explicit composition only.")
    context = {
        "schema_version": CONTEXT_SCHEMA,
        "request_id": req["id"],
        "prompt": req["text"],
        "references": copy.deepcopy(req["references"]),
        "analyses": copy.deepcopy(payload.get("analyses")),
    }
    analyses = context["analyses"]
    if not isinstance(analyses, list) or any(not isinstance(item, dict) for item in analyses):
        raise ValueError("Supply an ordered analyses list for all reference labels.")
    for analysis in analyses:
        if isinstance(analysis, dict) and "inspection" in analysis:
            record = checked_inspection(ledger.root, analysis["inspection"])
            analysis["inspection"] = record
    if "composition" in payload:
        context["composition"] = _composition(ledger, req, occ, payload["composition"], analyses)
    validate_context(context)
    return context


def _composition(ledger, req, occ, payload, analyses):
    from .graphics_media import normalize_background

    if not isinstance(payload, dict) or set(payload) != {"label", "instruction", "background"}:
        raise ValueError("Composition needs label, explicit instruction and the normal background payload.")
    ref = next((r for r in references(req) if r["label"] == payload["label"]), None)
    if ref is None or not _g()._bounded_prose(payload["instruction"]) or payload["instruction"] not in req["text"]:
        raise ValueError("Actual inclusion requires the original explicit instruction and saved reference label.")
    if not isinstance(payload["background"], dict):
        raise ValueError("Supply the normal explicit background payload.")
    candidate = next(
        (item for item in ledger.data.get("items", []) if item.get("id") == payload["background"].get("candidate_id")),
        None,
    )
    if candidate is None or candidate.get("local_sha256") != ref["sha256"]:
        raise ValueError("The background candidate must resolve the actual copied reference bytes.")
    source = Path(candidate.get("local_path") or "")
    if not source.is_file() or digest(source) != ref["sha256"]:
        raise ValueError("The registered local candidate no longer matches the saved original.")
    background = normalize_background(
        ledger.root,
        payload["background"],
        ledger.data["graphics"]["profile"],
        occ["timing"],
        items=ledger.data.get("items", []),
    )
    if background is None:
        raise ValueError("Explicit inclusion requires a saved background binding.")
    if ref["kind"] == "video":
        inspection = next((a.get("inspection") for a in analyses if a.get("label") == ref["label"]), None)
        if (
            not inspection
            or background.get("clock_state") != "resolved"
            or any(
                abs(background["source_" + key] - inspection[other]) > INTERVAL_TOLERANCE
                for key, other in (("start_s", "start_s"), ("end_s", "end_s"))
            )
        ):
            raise ValueError("The composition source interval must equal the explicitly inspected interval.")
    return {**copy.deepcopy(payload), "background": background}


def freeze(root, version_dir, context):
    validate_context(context)
    checked_context(root, context)
    for item, source_ref in _context_files(context):
        source = _g()._confine_existing(root, source_ref, prefixes=("graphics-data/",))
        destination = version_dir / item["frozen_ref"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as output, source.open("rb") as stream:
            shutil.copyfileobj(stream, output)
        if digest(destination) != item["sha256"]:
            raise ValueError("Reference changed while freezing; the version remains incomplete.")
    return frozen_record(context)


def checked_context(root, context, assignment=None):
    from .graphics_reference_video import checked_inspection

    validate_context(context)
    checked_references(root, context)
    for analysis in context.get("analyses", []):
        if "inspection" in analysis:
            record = analysis["inspection"]
            if checked_inspection(root, record["record_ref"]) != record:
                raise ValueError("Saved analysis no longer matches actual temporal evidence.")
    if (
        assignment is not None
        and context.get("composition")
        and assignment.get("background") != context["composition"]["background"]
    ):
        raise ValueError("The composition no longer matches the explicitly included reference and interval.")


def _context_files(context):
    files = {}
    for ref in references(context):
        frozen = "references/" + Path(ref["ref"]).name
        files[frozen] = ({"frozen_ref": frozen, "sha256": ref["sha256"]}, ref["ref"])
    for analysis in context.get("analyses", []):
        record = analysis.get("inspection")
        if record:
            frozen = "references/" + record["label"] + "-temporal.jpg"
            files[frozen] = ({"frozen_ref": frozen, "sha256": record["sheet_sha256"]}, record["sheet_ref"])
    return list(files.values())


def frozen_record(context):
    validate_context(context)
    return {
        "context_sha256": _g()._payload_hash(context),
        "files": [item for item, _ in _context_files(context)],
    }


def validate_frozen(assignment, fingerprints):
    context = assignment.get("reference_context")
    record = fingerprints.get("references")
    if context is None:
        if record is not None:
            raise ValueError("Unexpected frozen reference context.")
        return
    validate_context(context)
    expected = frozen_record(context)
    if record != expected:
        raise ValueError("Frozen reference context does not match its saved media.")
