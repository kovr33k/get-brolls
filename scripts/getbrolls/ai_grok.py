"""Native grok headless media adapter.

`produce` does not start a process. Installed streaming-json, SessionFolder,
media-model entitlement and ToolOutput serialization are not established for
grok 1.0.52, so the result is unverified. Account JSON is not account
discovery. Static API keys are refused. No other model is selected.
"""

from __future__ import annotations

import os

IMAGE_TOOL = "image_gen"
VIDEO_TOOLS = ("reference_to_video", "image_to_video")


def produce(project, job, workdir, *, timeout, on_submitted):
    """Refuse native media before any process starts.

    ``--model`` selects a reasoning turn; it does not pin or prove the image model.
    """
    _ = (project, workdir, timeout, on_submitted)
    request = job.get("request") if isinstance(job, dict) else None
    if not isinstance(request, dict):
        return _status("unsupported", "The frozen native request is missing.", "unsupported")
    kind = request.get("kind")
    tool = request.get("tool") or (IMAGE_TOOL if kind == "image" else "reference_to_video")
    if kind == "image" and tool != IMAGE_TOOL:
        return _status("unsupported", "The frozen image tool is not image_gen.", "unsupported")
    if kind == "video" and tool not in VIDEO_TOOLS:
        return _status("unsupported", "The frozen video tool is not a first-frame native tool.", "unsupported")
    if os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY"):
        return _status(
            "auth",
            "Static XAI_API_KEY or GROK_API_KEY is set. Native media will not fall back to an API key or another model.",
            "auth",
        )
    return _status(
        "unsupported",
        "Native Grok image and video capability is unverified for this installation. No request was sent.",
        "unverified",
    )


def _status(status, message, code):
    return {"status": status, "error": message, "code": code}
