"""Selected geographic data and editable single-entry custom scene authoring."""

from __future__ import annotations

import copy
import json
import math
from itertools import pairwise
from pathlib import Path

from .graphics_facts import facts_readiness
from .ledger import digest

KINDS = ("map", "custom")
MAX_LAYERS = 6
MAX_POINTS = 10000
FIRST_PRINTABLE = 32
BBOX_SIZE = 4
POSITION_SIZE = 2
LONGITUDE_LIMIT = 180
LATITUDE_LIMIT = 90
SHA256_LENGTH = 64
CUSTOM_DATA_LIMIT = 64000
SOURCE_JSON_LIMIT = 2000000


def _text(value, limit=140):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > limit
        or any(ord(c) < FIRST_PRINTABLE for c in value)
    ):
        raise ValueError("Scene text must be bounded nonempty single-line text.")


def _number(value):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError("Scene coordinates and times must be finite numbers.")
    return value


def _bbox(bounds):
    if not isinstance(bounds, list) or len(bounds) != BBOX_SIZE:
        raise ValueError("Map bounds must be [west, south, east, north].")
    west, south, east, north = [_number(n) for n in bounds]
    if not -LONGITUDE_LIMIT <= west < east <= LONGITUDE_LIMIT or not -LATITUDE_LIMIT <= south < north <= LATITUDE_LIMIT:
        raise ValueError("Use ordered WGS84 bounds without an antimeridian crossing.")


def _point(point):
    if not isinstance(point, list) or len(point) != POSITION_SIZE:
        raise ValueError("Use two-dimensional WGS84 positions.")
    lon, lat = [_number(n) for n in point]
    if not -LONGITUDE_LIMIT <= lon <= LONGITUDE_LIMIT or not -LATITUDE_LIMIT <= lat <= LATITUDE_LIMIT:
        raise ValueError("WGS84 position is outside longitude/latitude bounds.")


def _geometry(geometry):
    if not isinstance(geometry, dict) or set(geometry) != {"type", "coordinates"}:
        raise ValueError("Selected geometry needs type and coordinates only.")
    kind = geometry["type"]
    coordinates = geometry["coordinates"]
    if kind == "Point":
        _point(coordinates)
        return
    if kind not in ("Polygon", "MultiPolygon") or not isinstance(coordinates, list) or not coordinates:
        raise ValueError("Maps support selected Polygon, MultiPolygon or illustrative Point features.")
    polygons = [coordinates] if kind == "Polygon" else coordinates
    count = 0
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise ValueError("Selected polygons must contain rings.")
        for ring in polygon:
            _ring(ring)
            count += len(ring)
            if count > MAX_POINTS:
                raise ValueError("Simplify selected geometry to at most 10000 positions per layer.")


def _ring(ring):
    if not isinstance(ring, list) or len(ring) < BBOX_SIZE or ring[0] != ring[-1]:
        raise ValueError("Polygon rings must be closed and contain at least four positions.")
    for point in ring:
        _point(point)
    if any(abs(a[0] - b[0]) > LONGITUDE_LIMIT for a, b in pairwise(ring)):
        raise ValueError("Split antimeridian-crossing rings before selected map authoring.")


def _hash(value):
    if not isinstance(value, str) or len(value) != SHA256_LENGTH or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Scene source sha256 must identify the actual selected bytes.")


def _source_ref(ref):
    from .graphics import relative_artifact

    relative_artifact(ref, prefixes=("graphics-data/",))


def validate_scene(record):
    if not isinstance(record, dict) or type(record.get("schema_version")) is not int or record["schema_version"] != 1:
        raise ValueError("Scene schema_version must be integer 1.")
    if record.get("kind") not in KINDS:
        raise ValueError("Scene kind must be map or custom.")
    for key in ("title", "caption"):
        _text(record.get(key))
    _validate_beats(record.get("beats"))
    if record["kind"] == "map":
        _validate_map(record)
    else:
        _validate_custom(record)
    return record


def _validate_beats(beats):
    if not isinstance(beats, list) or not 1 <= len(beats) <= MAX_LAYERS:
        raise ValueError("A scene needs one to six legible, explicitly narrated beats.")
    ids = set()
    previous = -1
    for beat in beats:
        if not isinstance(beat, dict) or set(beat) != {"id", "label", "fact_id", "at_s"}:
            raise ValueError("Each beat needs id, label, fact_id and narration-clock at_s.")
        for key in ("id", "label", "fact_id"):
            _text(beat[key], 100 if key == "label" else 80)
        if beat["id"] in ids or _number(beat["at_s"]) <= previous:
            raise ValueError("Scene beats must have unique ids and increasing narration times.")
        ids.add(beat["id"])
        previous = beat["at_s"]


def _validate_map(record):
    required = {
        "schema_version",
        "kind",
        "title",
        "caption",
        "beats",
        "data_ref",
        "data_sha256",
        "bounds",
        "focus",
        "layers",
    }
    if set(record) != required:
        raise ValueError("Map content has missing or unknown fields.")
    _source_ref(record["data_ref"])
    _hash(record["data_sha256"])
    _bbox(record["bounds"])
    _bbox(record["focus"])
    west, south, east, north = record["bounds"]
    fw, fs, fe, fn = record["focus"]
    if not west <= fw < fe <= east or not south <= fs < fn <= north:
        raise ValueError("Focus must remain inside the declared map bounds.")
    layers = record["layers"]
    if not isinstance(layers, list) or len(layers) != len(record["beats"]):
        raise ValueError("Each map beat must refer to exactly one selected geographic layer.")
    for beat, layer in zip(record["beats"], layers, strict=True):
        if not isinstance(layer, dict) or set(layer) != {"feature_id", "treatment", "label_point", "geometry"}:
            raise ValueError("Map layers need feature_id, treatment, label_point and selected geometry.")
        _text(layer["feature_id"], 80)
        if layer["treatment"] not in ("geography", "recognized", "claim", "illustrative"):
            raise ValueError("Declare geography, recognized boundary, claim or illustrative marker explicitly.")
        _point(layer["label_point"])
        _geometry(layer["geometry"])
        if (layer["geometry"]["type"] == "Point") != (layer["treatment"] == "illustrative"):
            raise ValueError("Point markers are illustrations, never asserted real facilities.")
        if layer["feature_id"] != beat["id"]:
            raise ValueError("Map layer identity must match its beat.")


def _validate_custom(record):
    if set(record) != {"schema_version", "kind", "title", "caption", "beats", "source_ref", "source_sha256", "data"}:
        raise ValueError("Custom content has missing or unknown fields.")
    _source_ref(record["source_ref"])
    if Path(record["source_ref"]).suffix != ".jsx":
        raise ValueError("A custom scene needs one editable JSX entry exporting AuthorScene.")
    _hash(record["source_sha256"])
    if not isinstance(record["data"], dict) or len(json.dumps(record["data"], allow_nan=False)) > CUSTOM_DATA_LIMIT:
        raise ValueError("Custom scene data must be a bounded JSON object.")


def input_refs(record):
    return [record["data_ref"] if record["kind"] == "map" else record["source_ref"]]


def _live_source(root, record):
    from .graphics import _confine_refs

    ref = input_refs(record)[0]
    path = dict(_confine_refs(root, [ref], ("graphics-data/",)))[ref]
    expected = record["data_sha256"] if record["kind"] == "map" else record["source_sha256"]
    if digest(path) != expected:
        raise ValueError("Scene source bytes changed: " + ref)
    return path


def _selected_geometries(path, record):
    if path.stat().st_size > SOURCE_JSON_LIMIT:
        raise ValueError("Selected geographic input exceeds 2 MB.")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if (
        not isinstance(data, dict)
        or data.get("type") != "FeatureCollection"
        or not isinstance(data.get("features"), list)
    ):
        raise ValueError("Map input must be a selected GeoJSON FeatureCollection.")
    features = {}
    for item in data["features"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] in features:
            raise ValueError("Selected geographic features need unique string ids.")
        features[item["id"]] = item.get("geometry")
    for layer in record["layers"]:
        if features.get(layer["feature_id"]) != layer["geometry"]:
            raise ValueError("Embedded map geometry differs from selected source bytes: " + layer["feature_id"])


def normalize_scene(root, payload, timing):
    record = copy.deepcopy(payload)
    validate_scene(record)
    path = _live_source(root, record)
    if record["kind"] == "map":
        _selected_geometries(path, record)
    reasons = timing_reasons(record, timing)
    if reasons:
        raise ValueError("; ".join(reasons))
    return record


def timing_reasons(record, timing):
    estimated = timing["basis"] == "estimated"
    start = 0 if estimated else timing["start_s"]
    end = timing["duration_s"] if estimated else timing["end_s"]
    return [
        ("scene_beat_outside_draft:" if estimated else "scene_beat_outside_narration:") + beat["id"]
        for beat in record["beats"]
        if not start <= beat["at_s"] < end
    ]


def scene_readiness(root, occurrence):
    if occurrence.get("template") not in KINDS:
        return []
    record = occurrence.get("scene_content")
    if not isinstance(record, dict):
        return ["scene_content_missing"]
    reasons = timing_reasons(record, occurrence["timing"])
    try:
        path = _live_source(root, record)
        if record["kind"] == "map":
            _selected_geometries(path, record)
        _source_permission(occurrence, record)
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        reasons.append(str(exc))
    if occurrence["props"]["claim_status"] == "synthetic":
        return reasons
    facts = occurrence.get("facts")
    if not isinstance(facts, dict) or not facts_readiness(root, facts)["ready"]:
        return [*reasons, "scene_facts_not_ready"]
    values = {fact["id"]: fact for fact in facts["values"]}
    for beat in record["beats"]:
        fact = values.get(beat["fact_id"])
        if not fact or fact["definition"] != beat["label"]:
            reasons.append("scene_fact_mismatch:" + beat["id"])
    return reasons


def _source_permission(occurrence, record):
    """Authored code is packaged as executable source, so raw permission is mandatory."""
    ref = input_refs(record)[0]
    sha = record.get("source_sha256", record.get("data_sha256"))
    declarations = occurrence.get("material_use") or []
    match = next((item for item in declarations if item["ref"] == ref), None)
    if ref not in occurrence.get("asset_refs", []) or not match or match["sha256"] != sha:
        raise ValueError("Scene input must be an asset with a content-bound material-use declaration: " + ref)
    if match["rendered_use"] != "permitted":
        raise ValueError("Scene input rendered use is not permitted: " + ref)
    if match["raw_redistribution"] != "permitted":
        raise ValueError("Editable scene code/data needs explicit raw redistribution permission: " + ref)


def clip_scene(record, timing, fps, to_frame):
    scene = copy.deepcopy(record)
    start_frame = 0 if timing["basis"] == "estimated" else timing["start_frame"]
    for beat in scene["beats"]:
        beat["at_frame"] = min(timing["duration_in_frames"] - 1, to_frame(beat["at_s"], fps) - start_frame)
    return scene


def content_command(ledger, args):
    from . import graphics as g

    graphics, occurrence = g._require_occurrence(ledger, args.occurrence)
    if occurrence["template"] not in KINDS:
        raise ValueError("graphics-content requires --template map or custom.")
    record = normalize_scene(ledger.root, g.load_bounded_json_file(ledger.root, args.file), occurrence["timing"])
    if record["kind"] != occurrence["template"]:
        raise ValueError("Content kind must match the occurrence template.")
    _source_permission(occurrence, record)
    occurrence["scene_content"] = record
    g._apply_facts_display(ledger.root, occurrence)
    occurrence["stage"] = "authoring"
    ledger.save("graphics-content")
    return {"occurrence": occurrence, "profile": graphics["profile"]}
