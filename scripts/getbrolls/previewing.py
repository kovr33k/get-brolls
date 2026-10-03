"""Choose the existing B-roll or supplied composition for the review preview."""

import hashlib
import json

from .ledger import digest
from .media import image_preview, review_preview
from .models import id_stem


def prepare_preview(ledger, c, start, end, config):  # noqa: C901 - existing size; validates staleness/scope then dispatches by media kind
    src = c["local_path"]
    if digest(src) != c["local_sha256"]:
        raise ValueError("Local original changed: import it again.")
    for name in ("context_image", "full_preview"):
        if c.get(name + "_path") and digest(c[name + "_path"]) != c[name + "_sha256"]:
            raise ValueError("Context/composition file changed. Import with another --shot and review again.")
    if c.get("media", {}).get("kind") != "image":
        start -= c.get("local_start_s", 0)
        end -= c.get("local_start_s", 0)
    scope = config["scope"]
    if c["media"].get("kind") == "image":
        scope = "broll"
    if scope == "full":
        if not c.get("full_preview_path"):
            raise ValueError(
                "GB_GIF_SCOPE=full requires --full-preview-file containing the insert composition. Provide this file or use GB_GIF_SCOPE=broll."
            )
        duration = c["full_preview_media"]["duration_s"]
        if abs(duration - (end - start)) > 0.25:  # noqa: PLR2004 - 0.25 s tolerance when comparing the composition length with the segment
            raise ValueError("The composition must contain only the same insert and match the selected clip duration.")
        src = c["full_preview_path"]
        start = 0
        end = duration
    c["preview_scope"] = scope
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:8]
    stem = id_stem(c["id"]) + f"-r{c['segment']['revision']}-{config_hash}"
    if c["media"].get("kind") == "image":
        result = image_preview(src, ledger.root / "previews", stem)
    else:
        result = review_preview(
            src,
            ledger.root / "previews",
            stem,
            start,
            end,
            config,
            # Rótulos e tempos de célula em tempo da fonte, não do arquivo de trabalho.
            label={
                "title": c.get("title"),
                "id": c["id"],
                "offset": c["segment"]["start_s"] - start,
                "duration": c["media"].get("duration_s"),
            },
        )
    if c.get("context_image_path"):
        context = image_preview(c["context_image_path"], ledger.root / "previews", stem + "-context")
        result["context_path"] = context["poster_path"]
    result["scope"] = scope
    c["preview"].update(result)
