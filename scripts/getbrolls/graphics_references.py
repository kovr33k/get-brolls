"""Saved image instructions shared by initial graphics authoring and revisions."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

from .config import tool_path
from .ledger import Ledger, digest
from .runtime import project_lock

UPLOAD_PATH = "/__graphics-reference"
NAME_HEADER = "X-GetBrolls-Reference"
MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_NAME = 300
MAX_REVIEW_BYTES = 2_000_000
REF_RE = re.compile(r"graphics-data/references/([0-9a-f]{64})\.(png|jpg)\Z")


def _g():
    from . import graphics

    return graphics


def assignment_signature(occ):
    g = _g()
    return g._payload_hash({key: occ.get(key) for key in g.ASSIGNMENT_FIELDS if key != "reference_context"})


def validate_reference(ref):
    if not isinstance(ref, dict) or set(ref) != {"ref", "sha256", "name", "bytes", "width", "height", "kind"}:
        raise ValueError("Invalid saved image reference.")
    match = REF_RE.fullmatch(ref.get("ref", "")) if isinstance(ref.get("ref"), str) else None
    if not match or match[1] != ref.get("sha256") or ref.get("kind") != "image":
        raise ValueError("Invalid image reference identity.")
    name = ref.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME or re.search(r"[\x00-\x1f\x7f]", name):
        raise ValueError("The reference needs a valid display name (at most 300 characters).")
    for key in ("bytes", "width", "height"):
        if type(ref.get(key)) is not int or ref[key] <= 0:
            raise ValueError("Invalid image reference measurements.")
    if ref["bytes"] > MAX_IMAGE_BYTES or ref["width"] * ref["height"] > MAX_IMAGE_PIXELS:
        raise ValueError("Image reference exceeds the supported size.")


def checked_image(root, ref):
    validate_reference(ref)
    path = _g()._confine_existing(root, ref["ref"], prefixes=("graphics-data/",))
    if path.stat().st_size != ref["bytes"] or digest(path) != ref["sha256"]:
        raise ValueError("Saved reference bytes changed; preserve the request and supply the correct image.")
    return path


def validate_context(context):
    if context is None:
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
    validate_reference(context["reference"])


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
                "reference": latest.get("reference"),
                "scope": "scene",
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


def upload(directory, stream, length, metadata):
    """Bounded raw media transfer; no request, analysis or manifest mutation."""
    if not 0 < length <= MAX_IMAGE_BYTES:
        raise ValueError("Supply one PNG/JPEG image up to 16 MiB.")
    directory = Path(directory)
    with project_lock(directory.parent):
        ledger = Ledger(directory.parent, recover=False)
        if ledger.pending.exists():
            raise ValueError("A project write is pending. Finish it with the CLI before saving references.")
        target(ledger, metadata)
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
                        raise ValueError("Incomplete image transfer; the request was not saved.")
                    output.write(chunk)
                    sha.update(chunk)
                    remaining -= len(chunk)
                output.flush()
                os.fsync(output.fileno())
            header = staged.read_bytes()[:8]
            extension = (
                "png" if header == b"\x89PNG\r\n\x1a\n" else "jpg" if header.startswith(b"\xff\xd8\xff") else None
            )
            if extension is None:
                raise ValueError("Supply an actual PNG or JPEG still image.")
            width, height = _probe(staged, extension)
            sha256 = sha.hexdigest()
            ref = {
                "ref": f"graphics-data/references/{sha256}.{extension}",
                "sha256": sha256,
                "kind": "image",
                "name": name,
                "bytes": length,
                "width": width,
                "height": height,
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
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                "Image transfer/probe failed; preserve the draft and retry with a supported image."
            ) from exc
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)


def save_review(directory, data, save):
    """Validate complete image submissions, retaining the ordinary JSON exchange."""
    graphics_rows = data.get("graphics")
    if not isinstance(graphics_rows, list):
        return save(directory, data)
    rows = [
        row
        for row in graphics_rows
        if isinstance(row, dict) and (row.get("reference") is not None or row.get("initial"))
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
        for row in rows:
            if row.get("state") == "pending" and row.get("reference") is None:
                continue
            if (
                row.get("state") != "changes"
                or not _g()._bounded_prose(row.get("comment"))
                or row.get("scope", "scene") != "scene"
            ):
                raise ValueError("A saved image reference needs a scene-local change request and a nonblank prompt.")
            checked_image(directory, row.get("reference"))
            target(ledger, row)

        return _existing_review(directory, data) or save(directory, data)


def _existing_review(directory, data):
    folder = _g()._confine_planned(directory, Path(directory) / "reviews")
    canonical = {k: v for k, v in data.items() if k != "exportedAt"}
    for path in sorted(folder.glob("*.json"), reverse=True)[:32]:
        if path.is_symlink() or path.stat().st_size > MAX_REVIEW_BYTES:
            continue
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(previous, dict) and {k: v for k, v in previous.items() if k != "exportedAt"} == canonical:
                return path
        except (ValueError, OSError):
            continue
    return None


def served_image(directory, filename):
    """Only images claimed by this project's saved reviews/manifest are public."""
    refpath = "graphics-data/references/" + filename
    if not REF_RE.fullmatch(refpath):
        raise ValueError("Unknown image reference.")
    ledger = Ledger(Path(directory).parent, recover=False)
    records = list((ledger.data.get("graphics") or {}).get("requests") or [])
    folder = _g()._confine_planned(directory, Path(directory) / "reviews")
    for path in sorted(folder.glob("*.json"), reverse=True)[:32]:
        if path.is_symlink() or path.stat().st_size > MAX_REVIEW_BYTES:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("project") == ledger.data.get("project_id") and isinstance(payload.get("graphics"), list):
                records.extend(payload.get("graphics", []))
        except (ValueError, OSError, AttributeError):
            continue
    for row in records:
        ref = row.get("reference") if isinstance(row, dict) else None
        if isinstance(ref, dict) and ref.get("ref") == refpath:
            return checked_image(directory, ref)
    raise ValueError("The image has not been saved with a project request.")


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
            raise ValueError("Initial authoring needs a scene-local prompt and saved image, not approval.")
        ref = row.get("reference")
        checked_image(ctx["root"], ref)
        payload = {
            "project_id": ctx["project_id"],
            "scene_id": row.get("scene_id"),
            "occurrence_id": row.get("occurrence_id"),
            "reviewed_version": None,
            "content_sha256": row.get("signature"),
            "text": row["comment"].strip(),
            "scope": "scene",
            "kind": "authoring",
            "reference": copy.deepcopy(ref),
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
    if assignment_signature(occ) != req.get("content_sha256"):
        return "assignment_mismatch"
    return None


def apply_command(ledger, args):
    g = _g()
    graphics = ledger.data.get("graphics") or {}
    req = g._find_request(graphics, args.request)
    if not isinstance(req.get("reference"), dict) or req.get("state") == "processed":
        raise ValueError("Select an unprocessed saved image-reference request.")
    checked_image(ledger.root, req["reference"])
    if not g._bounded_prose(args.analysis):
        raise ValueError("Record --analysis after inspecting the actual saved image.")
    occ = graphics["occurrences"][req["occurrence_id"]]
    context = {
        "request_id": req["id"],
        "prompt": req["text"],
        "analysis": args.analysis.strip(),
        "reference": copy.deepcopy(req["reference"]),
    }
    validate_context(context)
    if occ.get("reference_context") == context:
        return {"reference_context": context, "idempotent": True, "render_started": False}
    if g._request_stale_reason(req, graphics):
        raise ValueError("Reference request is stale; restore its actual target before authoring.")
    occ["reference_context"] = context
    ledger.save("graphics-reference-apply")
    return {"reference_context": context, "idempotent": False, "render_started": False}


def freeze(root, version_dir, context):
    validate_context(context)
    source = checked_image(root, context["reference"])
    rel = "references/" + source.name
    destination = version_dir / rel
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as output, source.open("rb") as stream:
        shutil.copyfileobj(stream, output)
    if digest(destination) != context["reference"]["sha256"]:
        raise ValueError("Reference changed while freezing; the version remains incomplete.")
    return frozen_record(context)


def frozen_record(context):
    validate_context(context)
    return {
        "context_sha256": _g()._payload_hash(context),
        "files": [
            {
                "frozen_ref": "references/" + Path(context["reference"]["ref"]).name,
                "sha256": context["reference"]["sha256"],
            }
        ],
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
        raise ValueError("Frozen reference context does not match its saved image.")
