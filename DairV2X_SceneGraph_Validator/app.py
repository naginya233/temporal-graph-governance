import glob
import importlib
import json
import math
import os
import subprocess
import sys
import threading
from collections import Counter, OrderedDict, deque
from datetime import datetime
from io import BytesIO
from typing import Any, Deque, Dict, List, Optional, Tuple

from flask import Flask, jsonify, render_template, request, send_file

app = Flask(__name__)

# ================= 基础配置 =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "web_config.json")
INDEX_FILE = os.path.join(BASE_DIR, "validation_index.json")
GOV_INDEX_FILE = os.path.join(BASE_DIR, "governance_validation_index.json")


def _default_traffic_system_dir() -> str:
    return os.path.normpath(os.path.join(BASE_DIR, "..", "traffic_agent_system"))


def _default_governance_outputs_dir() -> str:
    return os.path.normpath(os.path.join(_default_traffic_system_dir(), "outputs"))


def _default_dair_root_dir() -> str:
    return os.path.normpath(os.path.join(BASE_DIR, "..", "..", "dairv2xspd", "dairv2xspd"))


def _default_label_virtuallidar_dir() -> str:
    return os.path.normpath(os.path.join(_default_dair_root_dir(), "label", "virtuallidar"))


def _default_label_camera_dir() -> str:
    return os.path.normpath(os.path.join(_default_dair_root_dir(), "label", "camera"))


def _default_calib_virtuallidar_to_world_dir() -> str:
    return os.path.normpath(os.path.join(_default_dair_root_dir(), "calib", "virtuallidar_to_world"))


def _default_map_elements_dir() -> str:
    return os.path.normpath(
        os.path.join(BASE_DIR, "..", "..", "infrastructure", "data", "infrastructure-side", "map_elements_results")
    )


# 默认路径与运行配置
config: Dict[str, Any] = {
    "sg_dir": "",
    "img_dir": "",
    "schematic_dir": "",
    "gov_outputs_dir": _default_governance_outputs_dir(),
    "selected_run": "",
    "traffic_system_dir": _default_traffic_system_dir(),
    "pipeline_script": "",
    "pipeline_python": sys.executable,
    "pipeline_data_dir": "",
    "pipeline_bev_dir": "",
    "pipeline_raw_image_dir": "",
    "pipeline_label_virtuallidar_dir": _default_label_virtuallidar_dir(),
    "pipeline_label_camera_dir": _default_label_camera_dir(),
    "pipeline_calib_virtuallidar_to_world_dir": _default_calib_virtuallidar_to_world_dir(),
    "pipeline_map_elements_dir": _default_map_elements_dir(),
    "pipeline_model": "qwen3-vl:4b",
    "pipeline_max_frames": 20,
    "pipeline_use_llm": True,
    "pipeline_generate_report": True,
    "pipeline_following_filter_enabled": True,
    "pipeline_following_min_longitudinal_gap": 1.5,
    "pipeline_following_max_longitudinal_gap": 35.0,
    "pipeline_following_max_lateral_offset": 3.2,
    "pipeline_following_min_heading_cos": 0.35,
    "pipeline_following_require_same_lane": True,
    "pipeline_pedestrian_window_frames": 60,
    "pipeline_pedestrian_busy_threshold": 8,
    "pipeline_pedestrian_saturated_threshold": 14,
}

TARGET_RELATIONS = [
    "overtaking",
    "crossing",
    "yielding_to",
    "conflict_with",
    "come_into",
    "leave_from",
]

LEVEL_WEIGHT = {
    "low": 0,
    "medium": 1,
    "high": 2,
}
# 向后兼容旧变量名
RISK_WEIGHT = LEVEL_WEIGHT

index_data: List[Dict[str, Any]] = []
gov_index_data: List[Dict[str, Any]] = []
gov_meta: Dict[str, Any] = {
    "runs": [],
    "selected_run": "",
    "summary": {},
    "event_segments": [],
}

pipeline_lock = threading.Lock()
pipeline_runtime: Dict[str, Any] = {
    "running": False,
    "pid": None,
    "started_at": "",
    "finished_at": "",
    "exit_code": None,
    "error": "",
    "stop_requested": False,
    "last_run_path": "",
    "last_command": [],
    "process": None,
    "logs": deque(maxlen=500),
}

DYNAMIC_BEV_CACHE_LIMIT = 120
dynamic_bev_cache_lock = threading.Lock()
dynamic_bev_cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()

plt: Any = None
Patch: Any = None
_matplotlib_ready: Optional[bool] = None

BEV_OBJECT_TYPE_STYLE: Dict[str, Dict[str, str]] = {
    "car": {"label": "Car", "color": "limegreen"},
    "truck": {"label": "Truck", "color": "deepskyblue"},
    "bus": {"label": "Bus", "color": "mediumorchid"},
    "van": {"label": "Van", "color": "steelblue"},
    "cyclist": {"label": "Cyclist", "color": "deepskyblue"},
    "bicycle": {"label": "Bicycle", "color": "deepskyblue"},
    "motorcycle": {"label": "Motorcycle", "color": "gold"},
    "pedestrian": {"label": "Pedestrian", "color": "darkorange"},
    "unknown": {"label": "Unknown", "color": "dimgray"},
}

BEV_MAP_STYLE: Dict[str, Any] = {
    "figure_bg": "#dfe3e8",
    "axes_bg": "#f3f4f6",
    "grid_color": "#bcc4d1",
    "junction_fill": "#f7f7f7",
    "junction_edge": "#cccccc",
    "junction_alpha": 0.5,
    "selected_junction_fill": "#fff2a8",
    "selected_junction_edge": "#b59b00",
    "selected_junction_alpha": 0.7,
    "lane_fill": "#d9d9d9",
    "lane_edge": "#9e9e9e",
    "lane_alpha": 0.45,
    "crosswalk_fill": "white",
    "crosswalk_edge": "black",
    "crosswalk_hatch": "///",
    "crosswalk_hatch_stroke": "#2f2f2f",
    "stopline_color": "firebrick",
    "island_fill": "#9be39b",
    "island_edge": "#2e7d32",
    "island_alpha": 0.8,
    "camera_color": "magenta",
}


# ================= 工具函数 =================
def _safe_read_json(path: str, default: Any) -> Any:
    if not path or not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _safe_write_json(path: str, payload: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def _normalize_path(value: Optional[str]) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    normalized = os.path.normpath(text)
    return "" if normalized == "." else normalized


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _as_int(value: Any, default: int, minimum: int = 1, maximum: int = 200000) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(minimum, min(maximum, parsed))


def _as_float(value: Any, default: float, minimum: float = -1e12, maximum: float = 1e12) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    return max(minimum, min(maximum, parsed))


def _iso_mtime(path: str) -> str:
    try:
        ts = os.path.getmtime(path)
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _run_summary_path(run_jsonl: str) -> str:
    stem = os.path.splitext(run_jsonl)[0]
    return f"{stem}_summary.json"


def _run_review_html_path(run_jsonl: str) -> str:
    stem = os.path.splitext(run_jsonl)[0]
    return f"{stem}_review.html"


def _list_governance_runs() -> List[Dict[str, str]]:
    outputs_dir = _normalize_path(config.get("gov_outputs_dir", ""))
    if not outputs_dir or not os.path.isdir(outputs_dir):
        return []

    paths = glob.glob(os.path.join(outputs_dir, "run_*.jsonl"))
    paths = sorted(paths, key=lambda p: os.path.getmtime(p), reverse=True)

    runs: List[Dict[str, str]] = []
    for p in paths:
        runs.append(
            {
                "name": os.path.basename(p),
                "path": os.path.normpath(p),
                "mtime": _iso_mtime(p),
            }
        )
    return runs


def _normalize_frame_id(frame_id: Any) -> str:
    if frame_id is None:
        return ""
    value = str(frame_id)
    if value.isdigit():
        return value.zfill(6)
    return value


def _extract_slowdown_from_event(event_analysis: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(event_analysis, dict):
        return {}

    # 统一展示口径为 raw（未时序校准）分数。
    for key in ("raw_slowdown", "raw_risk", "slowdown", "risk", "calibrated_slowdown", "calibrated_risk"):
        payload = event_analysis.get(key)
        if isinstance(payload, dict):
            return payload
    return {}


def _dominant_causes_from_slowdown(slowdown: Dict[str, Any]) -> List[str]:
    explicit = slowdown.get("causes")
    if isinstance(explicit, list):
        normalized = [str(item) for item in explicit if str(item).strip()]
        if normalized:
            return normalized

    causes: List[str] = []
    if int(slowdown.get("max_chain", 0)) >= 6:
        causes.append("long_convoy")
    if int(slowdown.get("convoy_cnt", 0)) >= 2:
        causes.append("multi_convoy")
    elif int(slowdown.get("convoy_cnt", 0)) >= 1:
        causes.append("single_convoy")
    if int(slowdown.get("merge_cnt", 0)) > 0:
        causes.append("merge_bottleneck")
    if float(slowdown.get("queue_density", 0.0)) >= 1.0:
        causes.append("dense_following")
    if bool(slowdown.get("cycle_detected", False)):
        causes.append("following_cycle")
    if not causes and int(slowdown.get("score", 0)) > 0:
        causes.append("other_slowdown")
    if not causes:
        causes.append("controlled_queue")
    return causes


def _dominant_causes_from_risk(risk: Dict[str, Any]) -> List[str]:
    # 向后兼容旧函数名
    return _dominant_causes_from_slowdown(risk)


def _extract_world_bounds_from_map_elements(frame_id: str) -> Dict[str, float]:
    map_dir = _normalize_path(config.get("pipeline_map_elements_dir", ""))
    if not map_dir or not os.path.isdir(map_dir):
        return {}

    normalized = _normalize_frame_id(frame_id)
    map_path = os.path.join(map_dir, f"{normalized}.json")
    if not os.path.exists(map_path):
        return {}

    payload = _safe_read_json(map_path, {})
    if not isinstance(payload, dict):
        return {}

    min_x = float("inf")
    max_x = float("-inf")
    min_y = float("inf")
    max_y = float("-inf")

    def _scan_polygon(poly: Any) -> None:
        nonlocal min_x, max_x, min_y, max_y
        if not isinstance(poly, list):
            return
        for pt in poly:
            if not isinstance(pt, list) or len(pt) < 2:
                continue
            try:
                x = float(pt[0])
                y = float(pt[1])
            except Exception:
                continue
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)

    def _scan_group(group_name: str, min_points: int = 3) -> None:
        group = payload.get(group_name)
        if isinstance(group, dict):
            iterable = list(group.values())
        elif isinstance(group, list):
            iterable = group
        else:
            iterable = []

        for item in iterable:
            pts = _map_item_points(item)
            if len(pts) >= min_points:
                _scan_polygon(pts)

    for group_key in ("lane", "crosswalk", "junction", "island"):
        _scan_group(group_key, min_points=3)
    _scan_group("stopline", min_points=2)

    if not (min_x < max_x and min_y < max_y):
        return {}

    return {
        "min_x": min_x,
        "max_x": max_x,
        "min_y": min_y,
        "max_y": max_y,
    }


def _extract_bev_overlay_from_scene_graph(scene_graph_path: str, fixed_world_bounds: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """提取 BEV 叠加所需的实体多边形（世界坐标系）。"""
    path = _normalize_path(scene_graph_path)
    if not path or not os.path.exists(path):
        return {"entity_polygons": {}, "world_bounds": {}}

    payload = _safe_read_json(path, {})
    triples = payload.get("object_map_triples") if isinstance(payload, dict) else []
    if not isinstance(triples, list):
        return {"entity_polygons": {}, "world_bounds": {}}

    entity_polygons: Dict[str, List[List[List[float]]]] = {}
    entity_types: Dict[str, str] = {}
    seen: Dict[str, set] = {}
    min_x = float("inf")
    max_x = float("-inf")
    min_y = float("inf")
    max_y = float("-inf")

    for item in triples:
        if not isinstance(item, dict):
            continue
        entity = str(item.get("subject", "")).strip()
        if not entity:
            continue

        subject_type = str(item.get("subject_type", "")).strip().upper()
        if subject_type and entity not in entity_types:
            entity_types[entity] = subject_type

        meta = item.get("object_meta")
        polygon = meta.get("polygon") if isinstance(meta, dict) else None
        if not isinstance(polygon, list):
            continue

        pts: List[List[float]] = []
        for pt in polygon:
            if not isinstance(pt, list) or len(pt) < 2:
                continue
            try:
                x = float(pt[0])
                y = float(pt[1])
            except Exception:
                continue
            pts.append([x, y])
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)

        if len(pts) < 3:
            continue

        encoded = "|".join(f"{x:.6f},{y:.6f}" for x, y in pts)
        bucket = seen.setdefault(entity, set())
        if encoded in bucket:
            continue
        bucket.add(encoded)

        entity_polygons.setdefault(entity, []).append(pts)

    if not entity_polygons:
        return {"entity_polygons": {}, "world_bounds": {}}

    use_fixed_bounds = (
        isinstance(fixed_world_bounds, dict)
        and float(fixed_world_bounds.get("max_x", 0.0)) > float(fixed_world_bounds.get("min_x", 0.0))
        and float(fixed_world_bounds.get("max_y", 0.0)) > float(fixed_world_bounds.get("min_y", 0.0))
    )

    if use_fixed_bounds:
        assert isinstance(fixed_world_bounds, dict)
        world_bounds = {
            "min_x": float(fixed_world_bounds.get("min_x", min_x)),
            "max_x": float(fixed_world_bounds.get("max_x", max_x)),
            "min_y": float(fixed_world_bounds.get("min_y", min_y)),
            "max_y": float(fixed_world_bounds.get("max_y", max_y)),
        }
    else:
        world_bounds = {
            "min_x": min_x,
            "max_x": max_x,
            "min_y": min_y,
            "max_y": max_y,
        }

    return {
        "entity_polygons": entity_polygons,
        "entity_types": entity_types,
        "world_bounds": world_bounds,
    }


def _load_map_elements_payload(frame_id: str) -> Dict[str, Any]:
    map_dir = _normalize_path(config.get("pipeline_map_elements_dir", ""))
    if not map_dir or not os.path.isdir(map_dir):
        return {}

    map_path = os.path.join(map_dir, f"{_normalize_frame_id(frame_id)}.json")
    if not os.path.exists(map_path):
        return {}
    payload = _safe_read_json(map_path, {})
    return payload if isinstance(payload, dict) else {}


def _load_label_virtuallidar_payload(frame_id: str) -> List[Dict[str, Any]]:
    label_dir = _normalize_path(config.get("pipeline_label_virtuallidar_dir", ""))
    if not label_dir or not os.path.isdir(label_dir):
        return []

    label_path = os.path.join(label_dir, f"{_normalize_frame_id(frame_id)}.json")
    if not os.path.exists(label_path):
        return []

    payload = _safe_read_json(label_path, [])
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _load_virtuallidar_to_world_calib(frame_id: str) -> Dict[str, Any]:
    calib_dir = _normalize_path(config.get("pipeline_calib_virtuallidar_to_world_dir", ""))
    if not calib_dir or not os.path.isdir(calib_dir):
        return {}

    calib_path = os.path.join(calib_dir, f"{_normalize_frame_id(frame_id)}.json")
    if not os.path.exists(calib_path):
        return {}

    payload = _safe_read_json(calib_path, {})
    if not isinstance(payload, dict):
        return {}

    rotation = payload.get("rotation")
    translation = payload.get("translation")
    if not isinstance(rotation, list) or not isinstance(translation, list):
        return {}
    if len(rotation) < 3 or len(translation) < 3:
        return {}

    try:
        r00, r01, r02 = float(rotation[0][0]), float(rotation[0][1]), float(rotation[0][2])
        r10, r11, r12 = float(rotation[1][0]), float(rotation[1][1]), float(rotation[1][2])
        r20, r21, r22 = float(rotation[2][0]), float(rotation[2][1]), float(rotation[2][2])

        tx = float(translation[0][0] if isinstance(translation[0], list) else translation[0])
        ty = float(translation[1][0] if isinstance(translation[1], list) else translation[1])
        tz = float(translation[2][0] if isinstance(translation[2], list) else translation[2])
    except Exception:
        return {}

    return {
        "r00": r00,
        "r01": r01,
        "r02": r02,
        "r10": r10,
        "r11": r11,
        "r12": r12,
        "r20": r20,
        "r21": r21,
        "r22": r22,
        "tx": tx,
        "ty": ty,
        "tz": tz,
    }


def _lidar_to_world_xy(x: float, y: float, z: float, calib: Dict[str, Any]) -> List[float]:
    if not calib:
        return [x, y]

    wx = calib["r00"] * x + calib["r01"] * y + calib["r02"] * z + calib["tx"]
    wy = calib["r10"] * x + calib["r11"] * y + calib["r12"] * z + calib["ty"]
    return [wx, wy]


def _object_type_key(raw_type: Any) -> str:
    text = str(raw_type or "").strip().lower()
    if text in {"car", "truck", "bus", "van", "cyclist", "bicycle", "pedestrian"}:
        return text
    if text in {"motorcycle", "motorcyclist", "motor"}:
        return "motorcycle"
    return "unknown"


def _is_pedestrian_type(raw_type: Any) -> bool:
    text = str(raw_type or "").strip().upper()
    if not text:
        return False
    return any(token in text for token in ("PEDESTRIAN", "PERSON", "WALKER"))


def _is_crossing_relation(raw_relation: Any) -> bool:
    text = str(raw_relation or "").strip().lower()
    if not text:
        return False
    if "cross" in text:
        return True
    return text in {
        "walking_across",
        "walk_across",
        "on_crosswalk",
        "in_crosswalk",
        "entering_crosswalk",
        "leaving_crosswalk",
        "traversing_crosswalk",
    }


def _is_crossing_target_type(raw_type: Any) -> bool:
    text = str(raw_type or "").strip().upper()
    if not text:
        return False
    return any(token in text for token in ("CROSSWALK", "LANE", "JUNCTION", "ROAD"))


def _is_crosswalk_target_type(raw_type: Any) -> bool:
    text = str(raw_type or "").strip().upper()
    if not text:
        return False
    return "CROSSWALK" in text


def _extract_pedestrian_crossing_snapshot(scene_graph_path: str) -> Dict[str, Any]:
    path = _normalize_path(scene_graph_path)
    if not path or not os.path.exists(path):
        return {
            "entities": [],
            "targets": [],
            "edge_count": 0,
        }

    payload = _safe_read_json(path, {})
    triples = payload.get("object_map_triples") if isinstance(payload, dict) else []
    if not isinstance(triples, list):
        return {
            "entities": [],
            "targets": [],
            "edge_count": 0,
        }

    entities: set = set()
    targets: set = set()
    edge_count = 0

    for triple in triples:
        if not isinstance(triple, dict):
            continue

        subject = str(triple.get("subject", "")).strip()
        if not subject:
            continue

        if not _is_pedestrian_type(triple.get("subject_type")):
            continue

        relation_text = str(triple.get("relation", "")).strip().lower()
        relation_is_crossing = _is_crossing_relation(relation_text)
        object_type = triple.get("object_type")

        # 放宽规则：若行人在斑马线上（in/on/inside），也记为过街活动。
        crosswalk_presence = relation_text in {"in", "on", "inside", "overlap", "intersect"} and _is_crosswalk_target_type(object_type)
        if not (relation_is_crossing or crosswalk_presence):
            continue

        if relation_is_crossing and object_type and not _is_crossing_target_type(object_type):
            continue

        edge_count += 1
        entities.add(subject)

        target = str(triple.get("object", "")).strip()
        if target:
            targets.add(target)

    return {
        "entities": sorted(entities),
        "targets": sorted(targets),
        "edge_count": int(edge_count),
    }


def _pedestrian_saturation_level(events_in_window: int, busy_threshold: int, saturated_threshold: int) -> str:
    if events_in_window >= saturated_threshold:
        return "saturated"
    if events_in_window >= busy_threshold:
        return "busy"
    return "normal"


def _pedestrian_saturation_text(
    level: str,
    events_in_window: int,
    window_frames: int,
    busy_threshold: int,
    saturated_threshold: int,
) -> str:
    if level == "saturated":
        return (
            f"近{window_frames}帧行人过街事件{events_in_window}次，超过饱和阈值{saturated_threshold}，"
            f"判定为饱和过街。"
        )
    if level == "busy":
        return (
            f"近{window_frames}帧行人过街事件{events_in_window}次，达到繁忙阈值{busy_threshold}，"
            f"判定为繁忙过街。"
        )
    return (
        f"近{window_frames}帧行人过街事件{events_in_window}次，低于繁忙阈值{busy_threshold}，"
        f"判定为正常过街。"
    )


def _attach_pedestrian_crossing_summaries(records: List[Dict[str, Any]]) -> None:
    if not records:
        return

    window_frames = _as_int(config.get("pipeline_pedestrian_window_frames", 60), default=60, minimum=5, maximum=5000)
    busy_threshold = _as_int(config.get("pipeline_pedestrian_busy_threshold", 8), default=8, minimum=1, maximum=5000)
    saturated_threshold = _as_int(
        config.get("pipeline_pedestrian_saturated_threshold", 14),
        default=14,
        minimum=max(2, busy_threshold + 1),
        maximum=10000,
    )

    prev_active: set = set()
    frame_queue: Deque[Dict[str, Any]] = deque()
    active_counter: Counter = Counter()
    event_counter: Counter = Counter()

    window_event_count = 0
    window_edge_count = 0

    for row in records:
        assets = row.get("assets", {}) if isinstance(row.get("assets"), dict) else {}
        scene_graph_path = str(assets.get("scene_graph_json", ""))
        snapshot = _extract_pedestrian_crossing_snapshot(scene_graph_path)

        active_entities = set(str(item) for item in snapshot.get("entities", []) if str(item).strip())
        active_targets = set(str(item) for item in snapshot.get("targets", []) if str(item).strip())
        edge_count = int(snapshot.get("edge_count", 0) or 0)

        new_event_entities = active_entities - prev_active
        frame_entry = {
            "active_entities": active_entities,
            "new_event_entities": set(new_event_entities),
            "edge_count": edge_count,
        }

        frame_queue.append(frame_entry)
        window_event_count += len(new_event_entities)
        window_edge_count += edge_count

        for entity in active_entities:
            active_counter[entity] += 1
        for entity in new_event_entities:
            event_counter[entity] += 1

        while len(frame_queue) > window_frames:
            expired = frame_queue.popleft()
            expired_active = expired.get("active_entities", set())
            expired_new = expired.get("new_event_entities", set())
            expired_edge = int(expired.get("edge_count", 0) or 0)

            window_event_count -= len(expired_new)
            window_edge_count -= expired_edge

            for entity in expired_active:
                active_counter[entity] -= 1
                if active_counter[entity] <= 0:
                    active_counter.pop(entity, None)

            for entity in expired_new:
                event_counter[entity] -= 1
                if event_counter[entity] <= 0:
                    event_counter.pop(entity, None)

        level = _pedestrian_saturation_level(
            events_in_window=window_event_count,
            busy_threshold=busy_threshold,
            saturated_threshold=saturated_threshold,
        )

        row["pedestrian_crossing_summary"] = {
            "window_frames": window_frames,
            "crossing_event_count": int(window_event_count),
            "crossing_edge_count": int(window_edge_count),
            "unique_active_pedestrian_count": int(len(active_counter)),
            "unique_event_pedestrian_count": int(len(event_counter)),
            "active_crossing_count": int(len(active_entities)),
            "active_entities": sorted(active_entities),
            "active_targets": sorted(active_targets),
            "new_crossing_entities": sorted(new_event_entities),
            "saturation_level": level,
            "thresholds": {
                "busy": int(busy_threshold),
                "saturated": int(saturated_threshold),
            },
            "insight": _pedestrian_saturation_text(
                level=level,
                events_in_window=window_event_count,
                window_frames=window_frames,
                busy_threshold=busy_threshold,
                saturated_threshold=saturated_threshold,
            ),
        }

        prev_active = active_entities


def _pedestrian_summaries_need_refresh(records: List[Dict[str, Any]]) -> bool:
    if not records:
        return False

    expected_window = _as_int(config.get("pipeline_pedestrian_window_frames", 60), default=60, minimum=5, maximum=5000)
    expected_busy = _as_int(config.get("pipeline_pedestrian_busy_threshold", 8), default=8, minimum=1, maximum=5000)
    expected_saturated = _as_int(
        config.get("pipeline_pedestrian_saturated_threshold", 14),
        default=14,
        minimum=max(2, expected_busy + 1),
        maximum=10000,
    )

    for row in records:
        if not isinstance(row, dict):
            return True

        summary = row.get("pedestrian_crossing_summary")
        if not isinstance(summary, dict):
            return True

        summary_window = _as_int(summary.get("window_frames", -1), default=-1, minimum=-1, maximum=5000)
        thresholds_raw = summary.get("thresholds")
        thresholds: Dict[str, Any] = thresholds_raw if isinstance(thresholds_raw, dict) else {}
        summary_busy = _as_int(thresholds.get("busy", -1), default=-1, minimum=-1, maximum=10000)
        summary_saturated = _as_int(thresholds.get("saturated", -1), default=-1, minimum=-1, maximum=10000)

        if summary_window != expected_window:
            return True
        if summary_busy != expected_busy or summary_saturated != expected_saturated:
            return True

    return False


def _as_polygon_points(raw_polygon: Any) -> List[List[float]]:
    if not isinstance(raw_polygon, list):
        return []
    pts: List[List[float]] = []
    for pt in raw_polygon:
        if not isinstance(pt, list) or len(pt) < 2:
            continue
        try:
            x = float(pt[0])
            y = float(pt[1])
        except Exception:
            continue
        pts.append([x, y])
    return pts


def _map_item_points(item: Any) -> List[List[float]]:
    if isinstance(item, dict):
        for key in ("polygon", "points", "polyline", "coords"):
            pts = _as_polygon_points(item.get(key))
            if pts:
                return pts
        return []
    return _as_polygon_points(item)


def _iter_group_points(group: Any, min_points: int = 3) -> List[Tuple[Dict[str, Any], List[List[float]]]]:
    result: List[Tuple[Dict[str, Any], List[List[float]]]] = []
    if isinstance(group, dict):
        iterable = list(group.items())
    elif isinstance(group, list):
        iterable = [(None, item) for item in group]
    else:
        iterable = []

    for key, item in iterable:
        pts = _map_item_points(item)
        if len(pts) < min_points:
            continue
        meta = dict(item) if isinstance(item, dict) else {}
        if key is not None and not meta.get("id") and not meta.get("junction_id"):
            meta["id"] = str(key)
        result.append((meta, pts))
    return result


def _as_single_point(raw_point: Any) -> List[List[float]]:
    if isinstance(raw_point, list) and len(raw_point) >= 2 and not isinstance(raw_point[0], (list, dict)):
        try:
            return [[float(raw_point[0]), float(raw_point[1])]]
        except Exception:
            return []
    return _as_polygon_points(raw_point)


def _object_world_polygon(obj: Dict[str, Any], calib: Optional[Dict[str, Any]] = None) -> List[List[float]]:
    loc_raw = obj.get("3d_location")
    dims_raw = obj.get("3d_dimensions")
    if not isinstance(loc_raw, dict) or not isinstance(dims_raw, dict):
        return []

    loc: Dict[str, Any] = loc_raw
    dims: Dict[str, Any] = dims_raw

    try:
        cx = float(loc.get("x", 0.0))
        cy = float(loc.get("y", 0.0))
        length = float(dims.get("l", 0.0))
        width = float(dims.get("w", 0.0))
        yaw = float(obj.get("rotation", 0.0) or 0.0)
    except Exception:
        return []

    if length <= 0.0 or width <= 0.0:
        half = 0.8
        return [
            [cx - half, cy - half],
            [cx + half, cy - half],
            [cx + half, cy + half],
            [cx - half, cy + half],
        ]

    half_l = length * 0.5
    half_w = width * 0.5
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)
    corners = [
        [half_l, half_w],
        [half_l, -half_w],
        [-half_l, -half_w],
        [-half_l, half_w],
    ]

    world_poly: List[List[float]] = []
    for dx, dy in corners:
        lx = cx + dx * cos_yaw - dy * sin_yaw
        ly = cy + dx * sin_yaw + dy * cos_yaw
        world_poly.append(_lidar_to_world_xy(lx, ly, float(loc.get("z", 0.0)), calib or {}))
    return world_poly


def _dynamic_bev_cache_get(key: str) -> Optional[Dict[str, Any]]:
    with dynamic_bev_cache_lock:
        value = dynamic_bev_cache.get(key)
        if value is None:
            return None
        dynamic_bev_cache.move_to_end(key)
        return value


def _dynamic_bev_cache_set(key: str, mime: str, data: bytes) -> None:
    with dynamic_bev_cache_lock:
        dynamic_bev_cache[key] = {
            "mime": str(mime or "image/png"),
            "data": data,
        }
        dynamic_bev_cache.move_to_end(key)
        while len(dynamic_bev_cache) > DYNAMIC_BEV_CACHE_LIMIT:
            dynamic_bev_cache.popitem(last=False)


def _ensure_matplotlib_ready() -> bool:
    global _matplotlib_ready, plt, Patch
    if _matplotlib_ready is not None:
        return _matplotlib_ready

    try:
        mpl = importlib.import_module("matplotlib")
        mpl.use("Agg")
        plt = importlib.import_module("matplotlib.pyplot")
        patches_mod = importlib.import_module("matplotlib.patches")
        Patch = getattr(patches_mod, "Patch")
        _matplotlib_ready = True
    except Exception:
        _matplotlib_ready = False
    return _matplotlib_ready


def _svg_escape(text: Any) -> str:
    value = str(text or "")
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _render_dynamic_bev(frame_id: str, highlight_entities: List[str]) -> bytes:
    if not _ensure_matplotlib_ready():
        raise RuntimeError("matplotlib 未安装，无法动态渲染 BEV")

    map_payload = _load_map_elements_payload(frame_id)
    labels = _load_label_virtuallidar_payload(frame_id)
    calib = _load_virtuallidar_to_world_calib(frame_id)
    bounds = _extract_world_bounds_from_map_elements(frame_id)

    fig, ax = plt.subplots(figsize=(10.8, 9.2), dpi=120)
    fig.patch.set_facecolor(str(BEV_MAP_STYLE["figure_bg"]))
    ax.set_facecolor(str(BEV_MAP_STYLE["axes_bg"]))

    lane_data = map_payload.get("lane", {}) if isinstance(map_payload, dict) else {}
    crosswalk_data = map_payload.get("crosswalk", {}) if isinstance(map_payload, dict) else {}
    junction_data = map_payload.get("junction", {}) if isinstance(map_payload, dict) else {}
    stopline_data = map_payload.get("stopline", {}) if isinstance(map_payload, dict) else {}
    island_data = map_payload.get("island", {}) if isinstance(map_payload, dict) else {}
    selected_junction_id = str(map_payload.get("selected_junction_id", "")).strip() if isinstance(map_payload, dict) else ""
    camera_center = map_payload.get("camera_center_world") if isinstance(map_payload, dict) else None

    for _, pts in _iter_group_points(junction_data, min_points=3):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        ax.fill(
            xs,
            ys,
            facecolor=str(BEV_MAP_STYLE["junction_fill"]),
            edgecolor=str(BEV_MAP_STYLE["junction_edge"]),
            linewidth=1.0,
            alpha=float(BEV_MAP_STYLE["junction_alpha"]),
            zorder=0,
        )

    for item, pts in _iter_group_points(junction_data, min_points=3):
        junction_id = str(item.get("id", item.get("junction_id", item.get("uid", "")))).strip() if isinstance(item, dict) else ""
        if selected_junction_id and junction_id and junction_id == selected_junction_id:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            ax.fill(
                xs,
                ys,
                facecolor=str(BEV_MAP_STYLE["selected_junction_fill"]),
                edgecolor=str(BEV_MAP_STYLE["selected_junction_edge"]),
                linewidth=2.0,
                alpha=float(BEV_MAP_STYLE["selected_junction_alpha"]),
                zorder=1,
            )

    for lane_meta, pts in _iter_group_points(lane_data, min_points=3):
        if isinstance(lane_meta, dict) and lane_meta.get("is_intersection") is False:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        ax.fill(
            xs,
            ys,
            facecolor=str(BEV_MAP_STYLE["lane_fill"]),
            edgecolor=str(BEV_MAP_STYLE["lane_edge"]),
            linewidth=0.8,
            alpha=float(BEV_MAP_STYLE["lane_alpha"]),
            zorder=2,
        )

    for _, pts in _iter_group_points(island_data, min_points=3):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        ax.fill(
            xs,
            ys,
            facecolor=str(BEV_MAP_STYLE["island_fill"]),
            edgecolor=str(BEV_MAP_STYLE["island_edge"]),
            linewidth=1.4,
            alpha=float(BEV_MAP_STYLE["island_alpha"]),
            zorder=3,
        )

    for _, pts in _iter_group_points(crosswalk_data, min_points=3):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        ax.fill(
            xs,
            ys,
            facecolor=str(BEV_MAP_STYLE["crosswalk_fill"]),
            edgecolor=str(BEV_MAP_STYLE["crosswalk_edge"]),
            linewidth=1.2,
            hatch=str(BEV_MAP_STYLE["crosswalk_hatch"]),
            alpha=0.95,
            zorder=4,
        )

    for _, pts in _iter_group_points(stopline_data, min_points=2):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        ax.plot(xs, ys, color=str(BEV_MAP_STYLE["stopline_color"]), linewidth=2.5, zorder=5)

    cam_pts = _as_single_point(camera_center)
    if len(cam_pts) >= 1:
        cam_x, cam_y = cam_pts[0][0], cam_pts[0][1]
        ax.plot(cam_x, cam_y, marker="*", color=str(BEV_MAP_STYLE["camera_color"]), markersize=16, zorder=10)
        ax.text(
            cam_x,
            cam_y + 1.3,
            "Camera",
            color=str(BEV_MAP_STYLE["camera_color"]),
            fontsize=9,
            ha="center",
            va="bottom",
            zorder=10,
        )

    highlighted = set(str(x).strip() for x in highlight_entities if str(x).strip())
    all_x: List[float] = []
    all_y: List[float] = []

    for obj in labels:
        track_id = str(obj.get("track_id", "")).strip()
        poly = _object_world_polygon(obj, calib=calib)
        if len(poly) < 3:
            continue

        style_key = _object_type_key(obj.get("type", ""))
        style = BEV_OBJECT_TYPE_STYLE.get(style_key, BEV_OBJECT_TYPE_STYLE["unknown"])
        color = style["color"]

        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        all_x.extend(xs)
        all_y.extend(ys)

        is_focus = track_id in highlighted
        ax.fill(
            xs,
            ys,
            facecolor=(color if is_focus else "none"),
            edgecolor=color,
            linewidth=(2.8 if is_focus else 1.8),
            alpha=(0.33 if is_focus else 0.96),
            zorder=(7 if is_focus else 4),
        )

        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        ax.text(
            cx,
            cy,
            track_id,
            fontsize=(8 if is_focus else 7),
            color=("#0b1220" if is_focus else color),
            weight=("bold" if is_focus else "normal"),
            ha="center",
            va="center",
            zorder=(8 if is_focus else 5),
        )

    if bounds:
        min_x = float(bounds.get("min_x", 0.0))
        max_x = float(bounds.get("max_x", 1.0))
        min_y = float(bounds.get("min_y", 0.0))
        max_y = float(bounds.get("max_y", 1.0))
    elif all_x and all_y:
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)
    else:
        min_x, max_x = 0.0, 100.0
        min_y, max_y = 0.0, 100.0

    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    margin_x = max(span_x * 0.03, 5.0)
    margin_y = max(span_y * 0.03, 5.0)

    ax.set_xlim(min_x - margin_x, max_x + margin_x)
    ax.set_ylim(min_y - margin_y, max_y + margin_y)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linestyle="--", linewidth=0.8, color=str(BEV_MAP_STYLE["grid_color"]), alpha=0.65)
    ax.set_xlabel("X (world)")
    ax.set_ylabel("Y (world)")
    ax.set_title(f"Intersection Map - {_normalize_frame_id(frame_id)}", fontsize=16)

    legend_order = ["car", "truck", "bus", "van", "cyclist", "bicycle", "motorcycle", "pedestrian", "unknown"]
    legend_handles = [
        Patch(facecolor=BEV_OBJECT_TYPE_STYLE[k]["color"], edgecolor=BEV_OBJECT_TYPE_STYLE[k]["color"], label=BEV_OBJECT_TYPE_STYLE[k]["label"])
        for k in legend_order
    ]
    ax.legend(handles=legend_handles, loc="upper right", frameon=False, fontsize=9)

    out = BytesIO()
    fig.savefig(out, format="png", dpi=120, bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)
    return out.getvalue()


def _render_dynamic_bev_svg(frame_id: str, highlight_entities: List[str]) -> bytes:
    map_payload = _load_map_elements_payload(frame_id)
    labels = _load_label_virtuallidar_payload(frame_id)
    calib = _load_virtuallidar_to_world_calib(frame_id)
    bounds = _extract_world_bounds_from_map_elements(frame_id)

    lane_data = map_payload.get("lane", {}) if isinstance(map_payload, dict) else {}
    crosswalk_data = map_payload.get("crosswalk", {}) if isinstance(map_payload, dict) else {}
    junction_data = map_payload.get("junction", {}) if isinstance(map_payload, dict) else {}
    stopline_data = map_payload.get("stopline", {}) if isinstance(map_payload, dict) else {}
    island_data = map_payload.get("island", {}) if isinstance(map_payload, dict) else {}
    selected_junction_id = str(map_payload.get("selected_junction_id", "")).strip() if isinstance(map_payload, dict) else ""
    camera_center = map_payload.get("camera_center_world") if isinstance(map_payload, dict) else None

    width = 1280.0
    height = 920.0
    pad_l = 66.0
    pad_r = 190.0
    pad_t = 44.0
    pad_b = 54.0
    canvas_w = width - pad_l - pad_r
    canvas_h = height - pad_t - pad_b

    min_x = float(bounds.get("min_x", 0.0)) if bounds else float("inf")
    max_x = float(bounds.get("max_x", 0.0)) if bounds else float("-inf")
    min_y = float(bounds.get("min_y", 0.0)) if bounds else float("inf")
    max_y = float(bounds.get("max_y", 0.0)) if bounds else float("-inf")

    def _update_bounds(points: List[List[float]]) -> None:
        nonlocal min_x, max_x, min_y, max_y
        for x, y in points:
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)

    for group in (lane_data, crosswalk_data, junction_data, island_data):
        for _, pts in _iter_group_points(group, min_points=3):
            _update_bounds(pts)

    for _, pts in _iter_group_points(stopline_data, min_points=2):
        _update_bounds(pts)

    cam_pts = _as_single_point(camera_center)
    if len(cam_pts) >= 1:
        _update_bounds([cam_pts[0]])

    object_polygons: List[Dict[str, Any]] = []
    highlighted = set(str(x).strip() for x in highlight_entities if str(x).strip())
    for obj in labels:
        track_id = str(obj.get("track_id", "")).strip()
        if not track_id:
            continue
        poly = _object_world_polygon(obj, calib=calib)
        if len(poly) < 3:
            continue
        _update_bounds(poly)
        style_key = _object_type_key(obj.get("type", ""))
        style = BEV_OBJECT_TYPE_STYLE.get(style_key, BEV_OBJECT_TYPE_STYLE["unknown"])
        object_polygons.append(
            {
                "track_id": track_id,
                "poly": poly,
                "color": style["color"],
                "is_focus": track_id in highlighted,
            }
        )

    if not (min_x < max_x and min_y < max_y):
        min_x, max_x, min_y, max_y = 0.0, 100.0, 0.0, 100.0

    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    margin_x = span_x * 0.03
    margin_y = span_y * 0.03
    min_x -= margin_x
    max_x += margin_x
    min_y -= margin_y
    max_y += margin_y
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)

    def _project(pt: List[float]) -> List[float]:
        x, y = float(pt[0]), float(pt[1])
        px = pad_l + (x - min_x) / span_x * canvas_w
        py = pad_t + (max_y - y) / span_y * canvas_h
        return [px, py]

    def _poly_points_attr(points: List[List[float]]) -> str:
        proj = [_project(p) for p in points]
        return " ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in proj)

    lines: List[str] = []
    lines.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{int(width)}" height="{int(height)}" viewBox="0 0 {int(width)} {int(height)}">')
    lines.append(
        f'<defs><pattern id="cw-hatch" patternUnits="userSpaceOnUse" width="8" height="8" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="8" stroke="{_svg_escape(str(BEV_MAP_STYLE["crosswalk_hatch_stroke"]))}" stroke-width="1.0"/></pattern></defs>'
    )
    lines.append(f'<rect x="0" y="0" width="100%" height="100%" fill="{_svg_escape(str(BEV_MAP_STYLE["figure_bg"]))}"/>')
    lines.append(
        f'<rect x="{pad_l:.1f}" y="{pad_t:.1f}" width="{canvas_w:.1f}" height="{canvas_h:.1f}" fill="{_svg_escape(str(BEV_MAP_STYLE["axes_bg"]))}" stroke="#9aa4b2" stroke-width="1"/>'
    )

    for i in range(1, 10):
        gx = pad_l + canvas_w * i / 10.0
        gy = pad_t + canvas_h * i / 10.0
        lines.append(f'<line x1="{gx:.1f}" y1="{pad_t:.1f}" x2="{gx:.1f}" y2="{pad_t + canvas_h:.1f}" stroke="#d0d6df" stroke-width="1" stroke-dasharray="4 4"/>')
        lines.append(f'<line x1="{pad_l:.1f}" y1="{gy:.1f}" x2="{pad_l + canvas_w:.1f}" y2="{gy:.1f}" stroke="#d0d6df" stroke-width="1" stroke-dasharray="4 4"/>')

    for _, pts in _iter_group_points(junction_data, min_points=3):
        lines.append(
            f'<polygon points="{_poly_points_attr(pts)}" fill="{_svg_escape(str(BEV_MAP_STYLE["junction_fill"]))}" stroke="{_svg_escape(str(BEV_MAP_STYLE["junction_edge"]))}" stroke-width="1.0" fill-opacity="{float(BEV_MAP_STYLE["junction_alpha"]):.2f}"/>'
        )

    for item, pts in _iter_group_points(junction_data, min_points=3):
        junction_id = str(item.get("id", item.get("junction_id", item.get("uid", "")))).strip() if isinstance(item, dict) else ""
        if selected_junction_id and junction_id and junction_id == selected_junction_id:
            lines.append(
                f'<polygon points="{_poly_points_attr(pts)}" fill="{_svg_escape(str(BEV_MAP_STYLE["selected_junction_fill"]))}" stroke="{_svg_escape(str(BEV_MAP_STYLE["selected_junction_edge"]))}" stroke-width="2.0" fill-opacity="{float(BEV_MAP_STYLE["selected_junction_alpha"]):.2f}"/>'
            )

    for lane_meta, pts in _iter_group_points(lane_data, min_points=3):
        if isinstance(lane_meta, dict) and lane_meta.get("is_intersection") is False:
            continue
        lines.append(
            f'<polygon points="{_poly_points_attr(pts)}" fill="{_svg_escape(str(BEV_MAP_STYLE["lane_fill"]))}" stroke="{_svg_escape(str(BEV_MAP_STYLE["lane_edge"]))}" stroke-width="0.8" fill-opacity="{float(BEV_MAP_STYLE["lane_alpha"]):.2f}"/>'
        )

    for _, pts in _iter_group_points(island_data, min_points=3):
        lines.append(
            f'<polygon points="{_poly_points_attr(pts)}" fill="{_svg_escape(str(BEV_MAP_STYLE["island_fill"]))}" stroke="{_svg_escape(str(BEV_MAP_STYLE["island_edge"]))}" stroke-width="1.4" fill-opacity="{float(BEV_MAP_STYLE["island_alpha"]):.2f}"/>'
        )

    for _, pts in _iter_group_points(crosswalk_data, min_points=3):
        pts_attr = _poly_points_attr(pts)
        lines.append(
            f'<polygon points="{pts_attr}" fill="{_svg_escape(str(BEV_MAP_STYLE["crosswalk_fill"]))}" stroke="{_svg_escape(str(BEV_MAP_STYLE["crosswalk_edge"]))}" stroke-width="1.2" fill-opacity="0.95"/>'
        )
        lines.append(
            f'<polygon points="{pts_attr}" fill="url(#cw-hatch)" stroke="none" fill-opacity="0.45"/>'
        )

    for _, pts in _iter_group_points(stopline_data, min_points=2):
        proj = [_project(p) for p in pts]
        d = " ".join(f"L {p[0]:.1f} {p[1]:.1f}" if i > 0 else f"M {p[0]:.1f} {p[1]:.1f}" for i, p in enumerate(proj))
        lines.append(
            f'<path d="{d}" fill="none" stroke="{_svg_escape(str(BEV_MAP_STYLE["stopline_color"]))}" stroke-width="2.5" stroke-linecap="round"/>'
        )

    if len(cam_pts) >= 1:
        cam_px, cam_py = _project(cam_pts[0])
        lines.append(f'<circle cx="{cam_px:.1f}" cy="{cam_py:.1f}" r="6" fill="{_svg_escape(str(BEV_MAP_STYLE["camera_color"]))}"/>')
        lines.append(
            f'<text x="{cam_px:.1f}" y="{cam_py-13:.1f}" text-anchor="middle" font-size="11" font-weight="700" fill="{_svg_escape(str(BEV_MAP_STYLE["camera_color"]))}">Camera</text>'
        )

    for obj in object_polygons:
        pts_attr = _poly_points_attr(obj["poly"])
        color = obj["color"]
        is_focus = bool(obj["is_focus"])
        fill = color if is_focus else "none"
        fill_opacity = "0.30" if is_focus else "0"
        stroke_width = "2.8" if is_focus else "1.8"
        lines.append(
            f'<polygon points="{pts_attr}" fill="{fill}" fill-opacity="{fill_opacity}" stroke="{color}" stroke-width="{stroke_width}"/>'
        )

        center_x = sum(pt[0] for pt in obj["poly"]) / len(obj["poly"])
        center_y = sum(pt[1] for pt in obj["poly"]) / len(obj["poly"])
        tx, ty = _project([center_x, center_y])
        text_color = "#0b1220" if is_focus else color
        font_w = "700" if is_focus else "500"
        lines.append(
            f'<text x="{tx:.1f}" y="{ty:.1f}" font-size="11" font-weight="{font_w}" text-anchor="middle" dominant-baseline="middle" fill="{text_color}">{_svg_escape(obj["track_id"])}</text>'
        )

    lines.append(f'<text x="{width/2:.1f}" y="28" text-anchor="middle" font-size="20" font-weight="600" fill="#111827">Intersection Map - {_svg_escape(_normalize_frame_id(frame_id))}</text>')
    lines.append(f'<text x="{width/2:.1f}" y="{height-14:.1f}" text-anchor="middle" font-size="20" fill="#111827">X (world)</text>')
    lines.append(f'<text x="20" y="{height/2:.1f}" text-anchor="middle" font-size="20" fill="#111827" transform="rotate(-90 20 {height/2:.1f})">Y (world)</text>')

    legend_x = width - pad_r + 20.0
    legend_y = 62.0
    lines.append(f'<rect x="{legend_x-12:.1f}" y="{legend_y-24:.1f}" width="170" height="260" fill="#ffffff" fill-opacity="0.65" rx="8"/>')
    for idx, key in enumerate(["car", "truck", "bus", "van", "cyclist", "bicycle", "motorcycle", "pedestrian", "unknown"]):
        info = BEV_OBJECT_TYPE_STYLE[key]
        y = legend_y + idx * 24.0
        lines.append(f'<rect x="{legend_x:.1f}" y="{y:.1f}" width="34" height="12" fill="{info["color"]}"/>')
        lines.append(f'<text x="{legend_x + 46:.1f}" y="{y + 10:.1f}" font-size="13" fill="#111827">{_svg_escape(info["label"])}</text>')

    lines.append("</svg>")
    return "\n".join(lines).encode("utf-8")


def _render_dynamic_bev_content(frame_id: str, highlight_entities: List[str]) -> Dict[str, Any]:
    if _ensure_matplotlib_ready():
        try:
            return {
                "mime": "image/png",
                "data": _render_dynamic_bev(frame_id=frame_id, highlight_entities=highlight_entities),
            }
        except Exception:
            pass

    return {
        "mime": "image/svg+xml",
        "data": _render_dynamic_bev_svg(frame_id=frame_id, highlight_entities=highlight_entities),
    }


def _pick_selected_run(runs: List[Dict[str, str]]) -> str:
    selected_run = _normalize_path(config.get("selected_run", ""))
    valid_paths = {item["path"] for item in runs}

    if selected_run and selected_run in valid_paths:
        return selected_run
    if runs:
        return runs[0]["path"]
    return ""


def _sync_pipeline_defaults() -> None:
    config["gov_outputs_dir"] = _normalize_path(config.get("gov_outputs_dir", "")) or _default_governance_outputs_dir()
    config["traffic_system_dir"] = _normalize_path(config.get("traffic_system_dir", "")) or _default_traffic_system_dir()
    config["pipeline_python"] = _normalize_path(config.get("pipeline_python", "")) or sys.executable
    config["selected_run"] = _normalize_path(config.get("selected_run", ""))

    if not _normalize_path(config.get("pipeline_script", "")):
        config["pipeline_script"] = os.path.join(config["traffic_system_dir"], "pipeline.py")
    else:
        config["pipeline_script"] = _normalize_path(config.get("pipeline_script", ""))

    if not _normalize_path(config.get("pipeline_data_dir", "")):
        config["pipeline_data_dir"] = _normalize_path(config.get("sg_dir", ""))
    if not _normalize_path(config.get("pipeline_bev_dir", "")):
        config["pipeline_bev_dir"] = _normalize_path(config.get("schematic_dir", ""))
    if not _normalize_path(config.get("pipeline_raw_image_dir", "")):
        config["pipeline_raw_image_dir"] = _normalize_path(config.get("img_dir", ""))

    if not _normalize_path(config.get("pipeline_label_virtuallidar_dir", "")):
        config["pipeline_label_virtuallidar_dir"] = _default_label_virtuallidar_dir()
    else:
        config["pipeline_label_virtuallidar_dir"] = _normalize_path(config.get("pipeline_label_virtuallidar_dir", ""))

    if not _normalize_path(config.get("pipeline_label_camera_dir", "")):
        config["pipeline_label_camera_dir"] = _default_label_camera_dir()
    else:
        config["pipeline_label_camera_dir"] = _normalize_path(config.get("pipeline_label_camera_dir", ""))

    if not _normalize_path(config.get("pipeline_calib_virtuallidar_to_world_dir", "")):
        config["pipeline_calib_virtuallidar_to_world_dir"] = _default_calib_virtuallidar_to_world_dir()
    else:
        config["pipeline_calib_virtuallidar_to_world_dir"] = _normalize_path(config.get("pipeline_calib_virtuallidar_to_world_dir", ""))

    if not _normalize_path(config.get("pipeline_map_elements_dir", "")):
        config["pipeline_map_elements_dir"] = _default_map_elements_dir()
    else:
        config["pipeline_map_elements_dir"] = _normalize_path(config.get("pipeline_map_elements_dir", ""))

    config["pipeline_model"] = str(config.get("pipeline_model", "qwen3-vl:4b") or "qwen3-vl:4b")
    config["pipeline_max_frames"] = _as_int(config.get("pipeline_max_frames", 20), default=20)
    config["pipeline_use_llm"] = _as_bool(config.get("pipeline_use_llm", True), default=True)
    config["pipeline_generate_report"] = _as_bool(config.get("pipeline_generate_report", True), default=True)
    config["pipeline_following_filter_enabled"] = _as_bool(config.get("pipeline_following_filter_enabled", True), default=True)
    config["pipeline_following_min_longitudinal_gap"] = _as_float(config.get("pipeline_following_min_longitudinal_gap", 1.5), default=1.5, minimum=0.0, maximum=100.0)
    config["pipeline_following_max_longitudinal_gap"] = _as_float(config.get("pipeline_following_max_longitudinal_gap", 35.0), default=35.0, minimum=1.0, maximum=300.0)
    config["pipeline_following_max_lateral_offset"] = _as_float(config.get("pipeline_following_max_lateral_offset", 3.2), default=3.2, minimum=0.2, maximum=50.0)
    config["pipeline_following_min_heading_cos"] = _as_float(config.get("pipeline_following_min_heading_cos", 0.35), default=0.35, minimum=-1.0, maximum=1.0)
    config["pipeline_following_require_same_lane"] = _as_bool(config.get("pipeline_following_require_same_lane", True), default=True)
    config["pipeline_pedestrian_window_frames"] = _as_int(config.get("pipeline_pedestrian_window_frames", 60), default=60, minimum=5, maximum=5000)
    config["pipeline_pedestrian_busy_threshold"] = _as_int(config.get("pipeline_pedestrian_busy_threshold", 8), default=8, minimum=1, maximum=5000)
    config["pipeline_pedestrian_saturated_threshold"] = _as_int(
        config.get("pipeline_pedestrian_saturated_threshold", 14),
        default=14,
        minimum=max(2, int(config["pipeline_pedestrian_busy_threshold"]) + 1),
        maximum=10000,
    )



def save_config() -> None:
    _safe_write_json(CONFIG_FILE, config)


def save_index() -> None:
    _safe_write_json(INDEX_FILE, index_data)


def save_governance_index() -> None:
    payload = {
        "selected_run": gov_meta.get("selected_run", ""),
        "summary": gov_meta.get("summary", {}),
        "event_segments": gov_meta.get("event_segments", []),
        "runs": gov_meta.get("runs", []),
        "records": gov_index_data,
    }
    _safe_write_json(GOV_INDEX_FILE, payload)


# ================= 初始化配置 =================
if os.path.exists(CONFIG_FILE):
    loaded = _safe_read_json(CONFIG_FILE, {})
    if isinstance(loaded, dict):
        config.update(loaded)

_sync_pipeline_defaults()


# ================= 关系校对索引 =================
def build_or_load_index(force_rebuild: bool = False) -> None:
    global index_data

    old_dict: Dict[str, str] = {}
    if os.path.exists(INDEX_FILE):
        old_data = _safe_read_json(INDEX_FILE, [])
        if isinstance(old_data, list):
            if not force_rebuild:
                index_data = old_data
                return
            old_dict = {
                f"{r.get('frame_id')}++{r.get('subject')}++{r.get('relation')}++{r.get('object')}": r.get("status", "pending")
                for r in old_data
            }

    index_data = []

    sg_dir = _normalize_path(config.get("sg_dir", ""))
    if sg_dir and os.path.isdir(sg_dir):
        files = sorted(glob.glob(os.path.join(sg_dir, "*.json")))
        for f in files:
            try:
                data = _safe_read_json(f, {})
                frame_id = data.get("image_id") or os.path.basename(f).split("_", 1)[0]
                frame_id = _normalize_frame_id(frame_id)
                if not frame_id:
                    continue

                for triple in data.get("object_object_triples", []):
                    rel = triple.get("relation")
                    if rel in TARGET_RELATIONS:
                        key = f"{frame_id}++{triple.get('subject')}++{rel}++{triple.get('object')}"
                        status = old_dict.get(key, "pending")
                        index_data.append(
                            {
                                "frame_id": frame_id,
                                "file_path": f,
                                "relation": rel,
                                "subject": triple.get("subject"),
                                "subject_type": triple.get("subject_type"),
                                "object": triple.get("object"),
                                "object_type": triple.get("object_type"),
                                "status": status,
                            }
                        )
            except Exception as exc:
                print(f"[!] 无法读取文件 {f}: {exc}")

    save_index()


# ================= 治理结果索引 =================
def build_or_load_governance_index(force_rebuild: bool = False) -> None:
    global gov_index_data, gov_meta

    old_status_map: Dict[str, str] = {}
    old_payload = _safe_read_json(GOV_INDEX_FILE, {})
    if isinstance(old_payload, dict):
        old_selected_run = _normalize_path(old_payload.get("selected_run", ""))
        old_records = old_payload.get("records", [])
        if isinstance(old_records, list):
            if (
                not force_rebuild
                and old_selected_run
                and old_selected_run == _normalize_path(config.get("selected_run", ""))
            ):
                refreshed = False
                if _pedestrian_summaries_need_refresh(old_records):
                    _attach_pedestrian_crossing_summaries(old_records)
                    refreshed = True

                gov_index_data = old_records
                gov_meta = {
                    "runs": old_payload.get("runs", []),
                    "selected_run": old_selected_run,
                    "summary": old_payload.get("summary", {}),
                    "event_segments": old_payload.get("event_segments", []),
                }

                if refreshed:
                    save_governance_index()
                return

            for r in old_records:
                frame_id = _normalize_frame_id(r.get("frame_id"))
                if frame_id:
                    old_status_map[frame_id] = str(r.get("status", "pending"))

    runs = _list_governance_runs()
    selected_run = _pick_selected_run(runs)

    config["selected_run"] = selected_run
    save_config()

    if not selected_run:
        gov_index_data = []
        gov_meta = {
            "runs": runs,
            "selected_run": "",
            "summary": {},
            "event_segments": [],
        }
        save_governance_index()
        return

    summary_payload = _safe_read_json(_run_summary_path(selected_run), {})
    summary_data = summary_payload.get("summary", {}) if isinstance(summary_payload, dict) else {}
    event_segments = summary_payload.get("event_segments", []) if isinstance(summary_payload, dict) else []

    parsed_records: List[Dict[str, Any]] = []
    try:
        with open(selected_run, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                record = json.loads(line)
                frame_id = _normalize_frame_id(record.get("frame_id"))
                if not frame_id:
                    continue

                event_analysis = record.get("event_analysis") or {}
                slowdown = _extract_slowdown_from_event(event_analysis)
                slowdown_level = str(slowdown.get("level", "low")).lower()
                slowdown_score = int(slowdown.get("score", 0))
                slowdown_class = str(slowdown.get("class", "normal_controlled_queue"))

                raw_slowdown_objects = slowdown.get("slowdown_objects")
                slowdown_objects: List[Dict[str, Any]] = [
                    item for item in raw_slowdown_objects if isinstance(item, dict)
                ] if isinstance(raw_slowdown_objects, list) else []

                raw_individual_entities = slowdown.get("individual_entities")
                slowdown_individual_entities: List[str] = [
                    str(item) for item in raw_individual_entities
                ] if isinstance(raw_individual_entities, list) else []

                raw_source_entities = slowdown.get("source_entities")
                slowdown_source_entities: List[str] = [
                    str(item) for item in raw_source_entities
                ] if isinstance(raw_source_entities, list) else []

                raw_source_summary = slowdown.get("source_summary")
                slowdown_source_summary: Dict[str, Any] = raw_source_summary if isinstance(raw_source_summary, dict) else {}

                raw_object_count = slowdown.get("slowdown_object_count")
                try:
                    slowdown_object_count = int(raw_object_count) if raw_object_count is not None else len(slowdown_objects)
                except Exception:
                    slowdown_object_count = len(slowdown_objects)

                assets = record.get("assets") or {}
                raw_image = assets.get("raw_image") or os.path.join(_normalize_path(config.get("img_dir", "")), f"{frame_id}.jpg")
                bev_image = assets.get("bev_image") or os.path.join(_normalize_path(config.get("schematic_dir", "")), f"{frame_id}_intersection.png")
                scene_graph_json = assets.get("scene_graph_json")

                parsed_records.append(
                    {
                        "frame_id": frame_id,
                        "file": record.get("file", ""),
                        "slowdown_level": slowdown_level,
                        "slowdown_score": slowdown_score,
                        "slowdown_class": slowdown_class,
                        "slowdown_class_label": slowdown.get("class_label", slowdown_class),
                        "slowdown_is_slowdown": bool(slowdown.get("is_slowdown", False)),
                        "slowdown_is_abnormal": bool(slowdown.get("is_abnormal", False)),
                        "slowdown_objects": slowdown_objects,
                        "slowdown_individual_entities": slowdown_individual_entities,
                        "slowdown_source_entities": slowdown_source_entities,
                        "slowdown_source_summary": slowdown_source_summary,
                        "slowdown_object_count": slowdown_object_count,
                        "risk_level": slowdown_level,
                        "risk_score": slowdown_score,
                        "dominant_causes": _dominant_causes_from_slowdown(slowdown),
                        "fast_decision": event_analysis.get("fast_decision", ""),
                        "llm_insight": event_analysis.get("llm_insight", ""),
                        "governance_report": record.get("governance_report", ""),
                        "assets": {
                            "raw_image": raw_image,
                            "bev_image": bev_image,
                            "scene_graph_json": scene_graph_json,
                        },
                        "status": old_status_map.get(frame_id, "pending"),
                    }
                )
    except Exception as exc:
        print(f"[!] 读取治理结果失败: {exc}")

    _attach_pedestrian_crossing_summaries(parsed_records)

    parsed_records.sort(
        key=lambda r: (
            -int(r.get("slowdown_score", r.get("risk_score", 0))),
            -LEVEL_WEIGHT.get(str(r.get("slowdown_level", r.get("risk_level", "low"))), 0),
            str(r.get("frame_id", "")),
        )
    )

    gov_index_data = parsed_records
    gov_meta = {
        "runs": runs,
        "selected_run": selected_run,
        "summary": summary_data,
        "event_segments": event_segments if isinstance(event_segments, list) else [],
    }

    save_governance_index()


# ================= pipeline 运行控制 =================
def _append_pipeline_log(message: str) -> None:
    text = str(message).rstrip("\n")
    with pipeline_lock:
        logs: Deque[str] = pipeline_runtime["logs"]
        logs.append(text)


def _pipeline_snapshot() -> Dict[str, Any]:
    with pipeline_lock:
        logs = list(pipeline_runtime["logs"])
        return {
            "running": bool(pipeline_runtime.get("running", False)),
            "pid": pipeline_runtime.get("pid"),
            "started_at": pipeline_runtime.get("started_at", ""),
            "finished_at": pipeline_runtime.get("finished_at", ""),
            "exit_code": pipeline_runtime.get("exit_code"),
            "error": pipeline_runtime.get("error", ""),
            "stop_requested": bool(pipeline_runtime.get("stop_requested", False)),
            "last_run_path": pipeline_runtime.get("last_run_path", ""),
            "last_command": list(pipeline_runtime.get("last_command", [])),
            "logs": logs,
        }


def _set_pipeline_finished(exit_code: Optional[int], error: str = "") -> None:
    with pipeline_lock:
        pipeline_runtime["running"] = False
        pipeline_runtime["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        pipeline_runtime["exit_code"] = exit_code
        pipeline_runtime["error"] = error
        pipeline_runtime["pid"] = None
        pipeline_runtime["process"] = None


def _run_pipeline_worker(command: List[str], cwd: str) -> None:
    before_runs = {item["path"] for item in _list_governance_runs()}
    process: Optional[subprocess.Popen] = None

    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        with pipeline_lock:
            pipeline_runtime["process"] = process
            pipeline_runtime["pid"] = process.pid

        _append_pipeline_log(f"[启动] PID={process.pid}")

        assert process.stdout is not None
        for line in process.stdout:
            _append_pipeline_log(line)

        exit_code = process.wait()
        _append_pipeline_log(f"[结束] exit_code={exit_code}")
        _set_pipeline_finished(exit_code=exit_code)

        if exit_code == 0:
            build_or_load_governance_index(force_rebuild=True)
            after_runs = {item["path"] for item in _list_governance_runs()}
            new_runs = list(after_runs - before_runs)
            selected = config.get("selected_run", "")
            if new_runs:
                selected = sorted(new_runs, key=lambda p: os.path.getmtime(p), reverse=True)[0]
                config["selected_run"] = selected
                save_config()
                build_or_load_governance_index(force_rebuild=True)
            with pipeline_lock:
                pipeline_runtime["last_run_path"] = selected
        else:
            with pipeline_lock:
                pipeline_runtime["last_run_path"] = _normalize_path(config.get("selected_run", ""))

    except Exception as exc:
        _append_pipeline_log(f"[异常] {exc}")
        _set_pipeline_finished(exit_code=-1, error=str(exc))
    finally:
        if process and process.stdout:
            try:
                process.stdout.close()
            except Exception:
                pass


def _start_pipeline(payload: Dict[str, Any]) -> Dict[str, Any]:
    with pipeline_lock:
        if pipeline_runtime.get("running", False):
            return {"success": False, "message": "pipeline 已在运行中"}

    traffic_system_dir = _normalize_path(payload.get("traffic_system_dir", config.get("traffic_system_dir", "")))
    pipeline_script = _normalize_path(payload.get("pipeline_script", config.get("pipeline_script", "")))
    pipeline_python = _normalize_path(payload.get("pipeline_python", config.get("pipeline_python", "")))

    data_dir = _normalize_path(payload.get("data_dir", config.get("pipeline_data_dir", "")))
    bev_dir = _normalize_path(payload.get("bev_dir", config.get("pipeline_bev_dir", "")))
    raw_image_dir = _normalize_path(payload.get("raw_image_dir", config.get("pipeline_raw_image_dir", "")))
    label_virtuallidar_dir = _normalize_path(payload.get("label_virtuallidar_dir", config.get("pipeline_label_virtuallidar_dir", "")))
    label_camera_dir = _normalize_path(payload.get("label_camera_dir", config.get("pipeline_label_camera_dir", "")))
    calib_virtuallidar_to_world_dir = _normalize_path(payload.get("calib_virtuallidar_to_world_dir", config.get("pipeline_calib_virtuallidar_to_world_dir", "")))
    map_elements_dir = _normalize_path(payload.get("map_elements_dir", config.get("pipeline_map_elements_dir", "")))
    output_dir = _normalize_path(payload.get("output_dir", config.get("gov_outputs_dir", "")))

    max_frames = _as_int(payload.get("max_frames", config.get("pipeline_max_frames", 20)), default=20)
    model = str(payload.get("model", config.get("pipeline_model", "qwen3-vl:4b")) or "qwen3-vl:4b")
    use_llm = _as_bool(payload.get("use_llm", config.get("pipeline_use_llm", True)), default=True)
    generate_report = _as_bool(payload.get("generate_report", config.get("pipeline_generate_report", True)), default=True)
    following_filter_enabled = _as_bool(payload.get("following_filter_enabled", config.get("pipeline_following_filter_enabled", True)), default=True)
    following_min_longitudinal_gap = _as_float(
        payload.get("following_min_longitudinal_gap", config.get("pipeline_following_min_longitudinal_gap", 1.5)),
        default=1.5,
        minimum=0.0,
        maximum=100.0,
    )
    following_max_longitudinal_gap = _as_float(
        payload.get("following_max_longitudinal_gap", config.get("pipeline_following_max_longitudinal_gap", 35.0)),
        default=35.0,
        minimum=1.0,
        maximum=300.0,
    )
    following_max_lateral_offset = _as_float(
        payload.get("following_max_lateral_offset", config.get("pipeline_following_max_lateral_offset", 3.2)),
        default=3.2,
        minimum=0.2,
        maximum=50.0,
    )
    following_min_heading_cos = _as_float(
        payload.get("following_min_heading_cos", config.get("pipeline_following_min_heading_cos", 0.35)),
        default=0.35,
        minimum=-1.0,
        maximum=1.0,
    )
    following_require_same_lane = _as_bool(
        payload.get("following_require_same_lane", config.get("pipeline_following_require_same_lane", True)),
        default=True,
    )

    if not traffic_system_dir:
        traffic_system_dir = _default_traffic_system_dir()
    if not pipeline_script:
        pipeline_script = os.path.join(traffic_system_dir, "pipeline.py")
    if not pipeline_python:
        pipeline_python = sys.executable

    if not os.path.isdir(traffic_system_dir):
        return {"success": False, "message": f"traffic_system_dir 不存在: {traffic_system_dir}"}
    if not os.path.isfile(pipeline_script):
        return {"success": False, "message": f"pipeline_script 不存在: {pipeline_script}"}
    if not os.path.isfile(pipeline_python):
        return {"success": False, "message": f"pipeline_python 不存在: {pipeline_python}"}

    for name, value in {
        "data_dir": data_dir,
        "bev_dir": bev_dir,
        "raw_image_dir": raw_image_dir,
    }.items():
        if not value or not os.path.isdir(value):
            return {"success": False, "message": f"{name} 路径无效: {value}"}

    if not output_dir:
        output_dir = _default_governance_outputs_dir()
    os.makedirs(output_dir, exist_ok=True)

    command = [
        pipeline_python,
        pipeline_script,
        "--data-dir",
        data_dir,
        "--bev-dir",
        bev_dir,
        "--raw-image-dir",
        raw_image_dir,
        "--label-virtuallidar-dir",
        label_virtuallidar_dir,
        "--label-camera-dir",
        label_camera_dir,
        "--calib-virtuallidar-to-world-dir",
        calib_virtuallidar_to_world_dir,
        "--map-elements-dir",
        map_elements_dir,
        "--max-frames",
        str(max_frames),
        "--model",
        model,
        "--output-dir",
        output_dir,
        "--following-min-longitudinal-gap",
        str(following_min_longitudinal_gap),
        "--following-max-longitudinal-gap",
        str(following_max_longitudinal_gap),
        "--following-max-lateral-offset",
        str(following_max_lateral_offset),
        "--following-min-heading-cos",
        str(following_min_heading_cos),
    ]
    if not following_filter_enabled:
        command.append("--disable-following-spatial-filter")
    if following_require_same_lane:
        command.append("--following-require-same-lane")
    if not use_llm:
        command.append("--no-llm")
    if not generate_report:
        command.append("--no-report")

    config["traffic_system_dir"] = traffic_system_dir
    config["pipeline_script"] = pipeline_script
    config["pipeline_python"] = pipeline_python
    config["pipeline_data_dir"] = data_dir
    config["pipeline_bev_dir"] = bev_dir
    config["pipeline_raw_image_dir"] = raw_image_dir
    config["pipeline_label_virtuallidar_dir"] = label_virtuallidar_dir
    config["pipeline_label_camera_dir"] = label_camera_dir
    config["pipeline_calib_virtuallidar_to_world_dir"] = calib_virtuallidar_to_world_dir
    config["pipeline_map_elements_dir"] = map_elements_dir
    config["pipeline_max_frames"] = max_frames
    config["pipeline_model"] = model
    config["pipeline_use_llm"] = use_llm
    config["pipeline_generate_report"] = generate_report
    config["pipeline_following_filter_enabled"] = following_filter_enabled
    config["pipeline_following_min_longitudinal_gap"] = following_min_longitudinal_gap
    config["pipeline_following_max_longitudinal_gap"] = following_max_longitudinal_gap
    config["pipeline_following_max_lateral_offset"] = following_max_lateral_offset
    config["pipeline_following_min_heading_cos"] = following_min_heading_cos
    config["pipeline_following_require_same_lane"] = following_require_same_lane
    config["gov_outputs_dir"] = output_dir
    save_config()

    with pipeline_lock:
        logs: Deque[str] = pipeline_runtime["logs"]
        logs.clear()
        pipeline_runtime["running"] = True
        pipeline_runtime["pid"] = None
        pipeline_runtime["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        pipeline_runtime["finished_at"] = ""
        pipeline_runtime["exit_code"] = None
        pipeline_runtime["error"] = ""
        pipeline_runtime["stop_requested"] = False
        pipeline_runtime["last_command"] = command
        pipeline_runtime["process"] = None

    _append_pipeline_log("[控制台] 已接收运行请求")
    _append_pipeline_log("[命令] " + " ".join(command))

    worker = threading.Thread(target=_run_pipeline_worker, args=(command, traffic_system_dir), daemon=True)
    worker.start()
    return {"success": True, "message": "pipeline 已启动"}


def _stop_pipeline() -> Dict[str, Any]:
    with pipeline_lock:
        running = bool(pipeline_runtime.get("running", False))
        process = pipeline_runtime.get("process")
        if not running or process is None:
            return {"success": False, "message": "当前没有运行中的 pipeline"}
        pipeline_runtime["stop_requested"] = True

    try:
        process.terminate()
        _append_pipeline_log("[控制台] 已发送终止信号")
        return {"success": True, "message": "已请求停止 pipeline"}
    except Exception as exc:
        _append_pipeline_log(f"[控制台] 停止失败: {exc}")
        return {"success": False, "message": str(exc)}


def _build_showcase_payload() -> Dict[str, Any]:
    selected_run = _normalize_path(gov_meta.get("selected_run", ""))
    summary = gov_meta.get("summary", {}) if isinstance(gov_meta.get("summary"), dict) else {}

    total = len(gov_index_data)
    pending = sum(1 for item in gov_index_data if item.get("status") == "pending")
    assessed = total - pending

    level_counter: Counter = Counter()
    class_counter: Counter = Counter()
    cause_counter: Counter = Counter()
    source_type_counter: Counter = Counter()
    source_weight_map: Dict[str, Dict[str, Any]] = {}
    frame_rows: List[Dict[str, Any]] = []
    score_series: List[Dict[str, Any]] = []

    for row in gov_index_data:
        frame_id = str(row.get("frame_id", "")).strip()
        slowdown_level = str(row.get("slowdown_level", row.get("risk_level", "low"))).lower()
        slowdown_class = str(row.get("slowdown_class", "normal_controlled_queue")).strip()
        slowdown_score = int(row.get("slowdown_score", row.get("risk_score", 0)) or 0)

        level_counter.update([slowdown_level])
        class_counter.update([slowdown_class])

        for cause in row.get("dominant_causes", []) or []:
            cause_counter.update([str(cause)])

        slowdown_objects = row.get("slowdown_objects", []) or []
        for obj in slowdown_objects:
            if not isinstance(obj, dict):
                continue
            source_type_counter.update([str(obj.get("source_type", "unknown"))])

        source_summary = row.get("slowdown_source_summary", {}) or {}
        weighted = source_summary.get("source_weighted_ranking", [])
        if not isinstance(weighted, list) or not weighted:
            weighted = [{"entity": src, "weight": 1.0, "object_type": "UNKNOWN"} for src in (row.get("slowdown_source_entities", []) or [])]

        seen_source_in_frame: set = set()
        for item in weighted:
            if not isinstance(item, dict):
                continue
            entity = str(item.get("entity", "")).strip()
            if not entity:
                continue
            weight = float(item.get("weight", 1.0) or 1.0)
            object_type = str(item.get("object_type", "UNKNOWN") or "UNKNOWN").upper()

            holder = source_weight_map.setdefault(
                entity,
                {
                    "entity": entity,
                    "total_weight": 0.0,
                    "frame_count": 0,
                    "object_type": object_type,
                    "max_weight": 0.0,
                },
            )
            holder["total_weight"] += weight
            holder["max_weight"] = max(float(holder["max_weight"]), weight)
            if holder.get("object_type", "UNKNOWN") == "UNKNOWN" and object_type != "UNKNOWN":
                holder["object_type"] = object_type

            if entity not in seen_source_in_frame:
                holder["frame_count"] += 1
                seen_source_in_frame.add(entity)

        assets = row.get("assets", {}) or {}
        frame_rows.append(
            {
                "frame_id": frame_id,
                "slowdown_score": slowdown_score,
                "slowdown_level": slowdown_level,
                "slowdown_class": slowdown_class,
                "slowdown_class_label": row.get("slowdown_class_label", slowdown_class),
                "source_entities": row.get("slowdown_source_entities", []) or [],
                "object_count": int(row.get("slowdown_object_count", 0) or 0),
                "dominant_causes": row.get("dominant_causes", []) or [],
                "raw_image": assets.get("raw_image", ""),
                "bev_image": assets.get("bev_image", ""),
            }
        )

        score_series.append(
            {
                "frame_id": frame_id,
                "score": slowdown_score,
                "level": slowdown_level,
                "class": slowdown_class,
            }
        )

    leaderboard = sorted(
        source_weight_map.values(),
        key=lambda item: (-float(item.get("total_weight", 0.0)), -int(item.get("frame_count", 0)), str(item.get("entity", ""))),
    )

    frame_rows = sorted(
        frame_rows,
        key=lambda item: (-int(item.get("slowdown_score", 0)), str(item.get("frame_id", ""))),
    )
    score_series = sorted(score_series, key=lambda item: str(item.get("frame_id", "")))

    last_run_time = _iso_mtime(selected_run) if selected_run and os.path.exists(selected_run) else ""
    selected_run_name = os.path.basename(selected_run) if selected_run else ""

    return {
        "meta": {
            "selected_run": selected_run,
            "selected_run_name": selected_run_name,
            "last_run_time": last_run_time,
            "total": total,
            "pending": pending,
            "assessed": assessed,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "summary": summary,
        "distributions": {
            "slowdown_levels": {
                "high": int(level_counter.get("high", 0)),
                "medium": int(level_counter.get("medium", 0)),
                "low": int(level_counter.get("low", 0)),
            },
            "slowdown_classes": dict(sorted(class_counter.items(), key=lambda item: item[0])),
            "dominant_causes": dict(cause_counter.most_common(12)),
            "source_types": dict(source_type_counter.most_common(8)),
        },
        "leaderboard": {
            "source_weighted": [
                {
                    "entity": str(item.get("entity", "")),
                    "total_weight": round(float(item.get("total_weight", 0.0)), 3),
                    "frame_count": int(item.get("frame_count", 0)),
                    "object_type": str(item.get("object_type", "UNKNOWN")),
                    "max_weight": round(float(item.get("max_weight", 0.0)), 3),
                }
                for item in leaderboard[:20]
            ]
        },
        "top_frames": frame_rows[:36],
        "score_series": score_series[:240],
        "pipeline_config": {
            "following_filter_enabled": bool(config.get("pipeline_following_filter_enabled", True)),
            "following_require_same_lane": bool(config.get("pipeline_following_require_same_lane", True)),
            "following_min_longitudinal_gap": float(config.get("pipeline_following_min_longitudinal_gap", 1.5)),
            "following_max_longitudinal_gap": float(config.get("pipeline_following_max_longitudinal_gap", 35.0)),
            "following_max_lateral_offset": float(config.get("pipeline_following_max_lateral_offset", 3.2)),
            "following_min_heading_cos": float(config.get("pipeline_following_min_heading_cos", 0.35)),
            "pedestrian_window_frames": int(config.get("pipeline_pedestrian_window_frames", 60)),
            "pedestrian_busy_threshold": int(config.get("pipeline_pedestrian_busy_threshold", 8)),
            "pedestrian_saturated_threshold": int(config.get("pipeline_pedestrian_saturated_threshold", 14)),
        },
    }


# 初始化加载索引
build_or_load_index()
build_or_load_governance_index()


# ================= 路由 =================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/showcase")
def showcase():
    return render_template("showcase.html")


@app.route("/api/state", methods=["GET"])
def get_state():
    total = len(index_data)
    pending = sum(1 for r in index_data if r.get("status") == "pending")
    assessed = total - pending
    return jsonify(
        {
            "config": config,
            "total": total,
            "pending": pending,
            "assessed": assessed,
        }
    )


@app.route("/api/config", methods=["POST"])
def update_config():
    data = request.json or {}

    if "sg_dir" in data:
        config["sg_dir"] = _normalize_path(data.get("sg_dir"))
    if "img_dir" in data:
        config["img_dir"] = _normalize_path(data.get("img_dir"))
    if "schematic_dir" in data:
        config["schematic_dir"] = _normalize_path(data.get("schematic_dir"))

    if "gov_outputs_dir" in data:
        config["gov_outputs_dir"] = _normalize_path(data.get("gov_outputs_dir"))
    if "selected_run" in data:
        config["selected_run"] = _normalize_path(data.get("selected_run"))

    if "traffic_system_dir" in data:
        config["traffic_system_dir"] = _normalize_path(data.get("traffic_system_dir"))
    if "pipeline_script" in data:
        config["pipeline_script"] = _normalize_path(data.get("pipeline_script"))
    if "pipeline_python" in data:
        config["pipeline_python"] = _normalize_path(data.get("pipeline_python"))

    if "pipeline_data_dir" in data:
        config["pipeline_data_dir"] = _normalize_path(data.get("pipeline_data_dir"))
    if "pipeline_bev_dir" in data:
        config["pipeline_bev_dir"] = _normalize_path(data.get("pipeline_bev_dir"))
    if "pipeline_raw_image_dir" in data:
        config["pipeline_raw_image_dir"] = _normalize_path(data.get("pipeline_raw_image_dir"))
    if "pipeline_label_virtuallidar_dir" in data:
        config["pipeline_label_virtuallidar_dir"] = _normalize_path(data.get("pipeline_label_virtuallidar_dir"))
    if "pipeline_label_camera_dir" in data:
        config["pipeline_label_camera_dir"] = _normalize_path(data.get("pipeline_label_camera_dir"))
    if "pipeline_calib_virtuallidar_to_world_dir" in data:
        config["pipeline_calib_virtuallidar_to_world_dir"] = _normalize_path(data.get("pipeline_calib_virtuallidar_to_world_dir"))
    if "pipeline_map_elements_dir" in data:
        config["pipeline_map_elements_dir"] = _normalize_path(data.get("pipeline_map_elements_dir"))

    if "pipeline_model" in data:
        config["pipeline_model"] = str(data.get("pipeline_model") or config.get("pipeline_model", "qwen3-vl:4b"))
    if "pipeline_max_frames" in data:
        config["pipeline_max_frames"] = _as_int(data.get("pipeline_max_frames"), default=config.get("pipeline_max_frames", 20))
    if "pipeline_use_llm" in data:
        config["pipeline_use_llm"] = _as_bool(data.get("pipeline_use_llm"), default=True)
    if "pipeline_generate_report" in data:
        config["pipeline_generate_report"] = _as_bool(data.get("pipeline_generate_report"), default=True)
    if "pipeline_following_filter_enabled" in data:
        config["pipeline_following_filter_enabled"] = _as_bool(data.get("pipeline_following_filter_enabled"), default=True)
    if "pipeline_following_min_longitudinal_gap" in data:
        config["pipeline_following_min_longitudinal_gap"] = _as_float(data.get("pipeline_following_min_longitudinal_gap"), default=1.5, minimum=0.0, maximum=100.0)
    if "pipeline_following_max_longitudinal_gap" in data:
        config["pipeline_following_max_longitudinal_gap"] = _as_float(data.get("pipeline_following_max_longitudinal_gap"), default=35.0, minimum=1.0, maximum=300.0)
    if "pipeline_following_max_lateral_offset" in data:
        config["pipeline_following_max_lateral_offset"] = _as_float(data.get("pipeline_following_max_lateral_offset"), default=3.2, minimum=0.2, maximum=50.0)
    if "pipeline_following_min_heading_cos" in data:
        config["pipeline_following_min_heading_cos"] = _as_float(data.get("pipeline_following_min_heading_cos"), default=0.35, minimum=-1.0, maximum=1.0)
    if "pipeline_following_require_same_lane" in data:
        config["pipeline_following_require_same_lane"] = _as_bool(data.get("pipeline_following_require_same_lane"), default=True)
    if "pipeline_pedestrian_window_frames" in data:
        config["pipeline_pedestrian_window_frames"] = _as_int(data.get("pipeline_pedestrian_window_frames"), default=60, minimum=5, maximum=5000)
    if "pipeline_pedestrian_busy_threshold" in data:
        config["pipeline_pedestrian_busy_threshold"] = _as_int(data.get("pipeline_pedestrian_busy_threshold"), default=8, minimum=1, maximum=5000)
    if "pipeline_pedestrian_saturated_threshold" in data:
        config["pipeline_pedestrian_saturated_threshold"] = _as_int(data.get("pipeline_pedestrian_saturated_threshold"), default=14, minimum=2, maximum=10000)

    _sync_pipeline_defaults()
    save_config()
    build_or_load_index(force_rebuild=True)
    build_or_load_governance_index(force_rebuild=True)
    return jsonify({"success": True})


@app.route("/api/next", methods=["GET"])
def get_next():
    for idx, record in enumerate(index_data):
        if record.get("status") == "pending":
            frame_id = record.get("frame_id", "")
            img_path = os.path.join(_normalize_path(config.get("img_dir", "")), f"{frame_id}.jpg")
            schematic_path = os.path.join(_normalize_path(config.get("schematic_dir", "")), f"{frame_id}_intersection.png")
            return jsonify(
                {
                    "task": record,
                    "index": idx,
                    "img_path": img_path,
                    "schematic_path": schematic_path,
                }
            )
    return jsonify({"task": None})


@app.route("/api/submit", methods=["POST"])
def submit():
    data = request.json or {}
    idx = data.get("index")
    status = data.get("status")

    if idx is not None and 0 <= int(idx) < len(index_data):
        idx = int(idx)
        if status == "skip":
            index_data[idx]["status"] = "pending"
        else:
            index_data[idx]["status"] = str(status)
        save_index()
        return jsonify({"success": True})

    return jsonify({"success": False}), 400


@app.route("/api/governance/state", methods=["GET"])
def get_governance_state():
    total = len(gov_index_data)
    pending = sum(1 for r in gov_index_data if r.get("status") == "pending")
    assessed = total - pending

    slowdown_distribution = {
        "high": sum(1 for r in gov_index_data if r.get("slowdown_level", r.get("risk_level")) == "high"),
        "medium": sum(1 for r in gov_index_data if r.get("slowdown_level", r.get("risk_level")) == "medium"),
        "low": sum(1 for r in gov_index_data if r.get("slowdown_level", r.get("risk_level")) == "low"),
    }

    selected_run = gov_meta.get("selected_run", "")
    summary_path = _run_summary_path(selected_run) if selected_run else ""
    review_html = _run_review_html_path(selected_run) if selected_run else ""

    return jsonify(
        {
            "total": total,
            "pending": pending,
            "assessed": assessed,
            "runs": gov_meta.get("runs", []),
            "selected_run": selected_run,
            "summary": gov_meta.get("summary", {}),
            "event_segments": gov_meta.get("event_segments", []),
            "slowdown_distribution": slowdown_distribution,
            "risk_distribution": slowdown_distribution,
            "pedestrian_config": {
                "window_frames": int(config.get("pipeline_pedestrian_window_frames", 60)),
                "busy_threshold": int(config.get("pipeline_pedestrian_busy_threshold", 8)),
                "saturated_threshold": int(config.get("pipeline_pedestrian_saturated_threshold", 14)),
            },
            "summary_file": summary_path if summary_path and os.path.exists(summary_path) else "",
            "review_html": review_html if review_html and os.path.exists(review_html) else "",
        }
    )


@app.route("/api/showcase/data", methods=["GET"])
def get_showcase_data():
    build_or_load_governance_index(force_rebuild=False)
    return jsonify(_build_showcase_payload())


@app.route("/api/governance/select_run", methods=["POST"])
def select_governance_run():
    data = request.json or {}
    selected_run = _normalize_path(data.get("selected_run"))
    if not selected_run:
        return jsonify({"success": False, "message": "selected_run 不能为空"}), 400

    available = {item["path"] for item in _list_governance_runs()}
    if selected_run not in available:
        return jsonify({"success": False, "message": "selected_run 不在可用运行列表中"}), 400

    config["selected_run"] = selected_run
    save_config()
    build_or_load_governance_index(force_rebuild=True)
    return jsonify({"success": True})


@app.route("/api/governance/rebuild", methods=["POST"])
def rebuild_governance_index():
    build_or_load_governance_index(force_rebuild=True)
    return jsonify({"success": True})


def _build_governance_task_payload(idx: int, record: Dict[str, Any]) -> Dict[str, Any]:
    assets = record.get("assets", {}) if isinstance(record.get("assets"), dict) else {}
    frame_id = str(record.get("frame_id", "")).strip()
    fixed_bounds = _extract_world_bounds_from_map_elements(frame_id)
    bev_overlay = _extract_bev_overlay_from_scene_graph(
        assets.get("scene_graph_json", ""),
        fixed_world_bounds=fixed_bounds,
    )
    return {
        "task": record,
        "index": idx,
        "img_path": assets.get("raw_image", ""),
        "schematic_path": assets.get("bev_image", ""),
        "bev_overlay": bev_overlay,
    }


def _record_has_pedestrian_crossing_data(record: Dict[str, Any]) -> bool:
    summary = record.get("pedestrian_crossing_summary", {})
    if not isinstance(summary, dict):
        return False

    crossing_event_count = int(summary.get("crossing_event_count", 0) or 0)
    crossing_edge_count = int(summary.get("crossing_edge_count", 0) or 0)
    active_crossing_count = int(summary.get("active_crossing_count", 0) or 0)

    return crossing_event_count > 0 or crossing_edge_count > 0 or active_crossing_count > 0


def _pick_governance_index_for_navigation(
    direction: str,
    current_index: int,
    only_with_pedestrian_data: bool,
) -> Optional[int]:
    if not gov_index_data:
        return None

    candidates: List[int] = []
    for idx, record in enumerate(gov_index_data):
        if only_with_pedestrian_data and not _record_has_pedestrian_crossing_data(record):
            continue
        candidates.append(idx)

    if not candidates:
        return None

    normalized_direction = "prev" if str(direction).strip().lower() == "prev" else "next"
    if current_index < 0 or current_index >= len(gov_index_data):
        return candidates[-1] if normalized_direction == "prev" else candidates[0]

    if normalized_direction == "next":
        for idx in candidates:
            if idx > current_index:
                return idx
        return candidates[0]

    for idx in reversed(candidates):
        if idx < current_index:
            return idx
    return candidates[-1]


@app.route("/api/governance/next", methods=["GET"])
def get_next_governance():
    for idx, record in enumerate(gov_index_data):
        if record.get("status") == "pending":
            return jsonify(_build_governance_task_payload(idx, record))
    return jsonify({"task": None})


@app.route("/api/governance/frame", methods=["GET"])
def get_governance_frame():
    frame_id = str(request.args.get("frame_id", "")).strip()
    index_arg = request.args.get("index")

    if frame_id:
        for idx, record in enumerate(gov_index_data):
            if str(record.get("frame_id", "")).strip() == frame_id:
                return jsonify(_build_governance_task_payload(idx, record))
        return jsonify({"task": None, "message": "未找到指定 frame_id。"}), 404

    if index_arg is not None:
        idx = _as_int(index_arg, default=-1, minimum=0, maximum=max(0, len(gov_index_data) - 1))
        if 0 <= idx < len(gov_index_data):
            return jsonify(_build_governance_task_payload(idx, gov_index_data[idx]))
        return jsonify({"task": None, "message": "索引超出范围。"}), 404

    return jsonify({"task": None, "message": "请提供 frame_id 或 index。"}), 400


@app.route("/api/governance/pedestrian_frame", methods=["GET"])
def get_governance_pedestrian_frame():
    direction = str(request.args.get("direction", "next") or "next").strip().lower()
    only_with_data = _as_bool(request.args.get("only_with_data", "1"), default=True)
    current_index = _as_int(request.args.get("current_index", -1), default=-1)

    picked_index = _pick_governance_index_for_navigation(
        direction=direction,
        current_index=current_index,
        only_with_pedestrian_data=only_with_data,
    )
    if picked_index is None:
        if only_with_data:
            return jsonify({"task": None, "message": "未找到包含行人过街数据的帧。"})
        return jsonify({"task": None, "message": "当前无可浏览帧。"})

    return jsonify(_build_governance_task_payload(picked_index, gov_index_data[picked_index]))


@app.route("/api/governance/pedestrian_window", methods=["POST"])
def update_pedestrian_window():
    data = request.json or {}
    window_frames = _as_int(data.get("window_frames", config.get("pipeline_pedestrian_window_frames", 60)), default=60, minimum=5, maximum=5000)
    busy_threshold = _as_int(data.get("busy_threshold", config.get("pipeline_pedestrian_busy_threshold", 8)), default=8, minimum=1, maximum=5000)
    saturated_threshold = _as_int(
        data.get("saturated_threshold", config.get("pipeline_pedestrian_saturated_threshold", 14)),
        default=14,
        minimum=max(2, busy_threshold + 1),
        maximum=10000,
    )

    config["pipeline_pedestrian_window_frames"] = window_frames
    config["pipeline_pedestrian_busy_threshold"] = busy_threshold
    config["pipeline_pedestrian_saturated_threshold"] = saturated_threshold
    _sync_pipeline_defaults()
    save_config()

    # 重建索引以保证按时间顺序重新计算滑动窗统计。
    build_or_load_governance_index(force_rebuild=True)

    return jsonify(
        {
            "success": True,
            "window_frames": int(config.get("pipeline_pedestrian_window_frames", window_frames)),
            "busy_threshold": int(config.get("pipeline_pedestrian_busy_threshold", busy_threshold)),
            "saturated_threshold": int(config.get("pipeline_pedestrian_saturated_threshold", saturated_threshold)),
            "message": (
                f"行人统计参数已更新：窗口 {int(config.get('pipeline_pedestrian_window_frames', window_frames))} 帧，"
                f"繁忙阈值 {int(config.get('pipeline_pedestrian_busy_threshold', busy_threshold))}，"
                f"饱和阈值 {int(config.get('pipeline_pedestrian_saturated_threshold', saturated_threshold))}。"
            ),
        }
    )


@app.route("/api/governance/submit", methods=["POST"])
def submit_governance():
    data = request.json or {}
    idx = data.get("index")
    status = str(data.get("status", "")).strip().lower()
    allowed = {"confirmed", "suspect", "pending", "skip"}

    if status not in allowed:
        return jsonify({"success": False, "message": "非法 status"}), 400

    if idx is not None and 0 <= int(idx) < len(gov_index_data):
        idx = int(idx)
        if status == "skip":
            gov_index_data[idx]["status"] = "pending"
        else:
            gov_index_data[idx]["status"] = status
        save_governance_index()
        return jsonify({"success": True})

    return jsonify({"success": False}), 400


@app.route("/api/governance/render_bev", methods=["GET"])
def render_governance_bev():
    frame_id = str(request.args.get("frame_id", "")).strip()
    if not frame_id:
        return "frame_id 不能为空", 400

    entities_text = str(request.args.get("entities", "")).strip()
    entities = [item.strip() for item in entities_text.split(",") if item.strip()]
    entities_sorted = sorted(set(entities))

    cache_key = f"{_normalize_frame_id(frame_id)}::{','.join(entities_sorted)}"
    cached = _dynamic_bev_cache_get(cache_key)
    if cached is not None:
        return send_file(BytesIO(cached.get("data", b"")), mimetype=str(cached.get("mime", "image/png")))

    try:
        rendered = _render_dynamic_bev_content(frame_id=frame_id, highlight_entities=entities_sorted)
    except Exception as exc:
        return f"动态渲染失败: {exc}", 500

    mime = str(rendered.get("mime", "image/png"))
    data = rendered.get("data", b"")
    if not isinstance(data, (bytes, bytearray)):
        return "动态渲染失败: 输出无效", 500

    payload = bytes(data)
    _dynamic_bev_cache_set(cache_key, mime=mime, data=payload)
    return send_file(BytesIO(payload), mimetype=mime)


@app.route("/api/pipeline/state", methods=["GET"])
def get_pipeline_state():
    return jsonify(_pipeline_snapshot())


@app.route("/api/pipeline/start", methods=["POST"])
def start_pipeline():
    payload = request.json or {}
    result = _start_pipeline(payload)
    code = 200 if result.get("success") else 400
    return jsonify(result), code


@app.route("/api/pipeline/stop", methods=["POST"])
def stop_pipeline():
    result = _stop_pipeline()
    code = 200 if result.get("success") else 400
    return jsonify(result), code


@app.route("/api/image")
def serve_image():
    path = request.args.get("path", "")
    if path and os.path.exists(path):
        return send_file(path)
    return "Image not found", 404


if __name__ == "__main__":
    host = str(os.environ.get("HOST", "0.0.0.0") or "0.0.0.0")
    port = _as_int(os.environ.get("PORT", 5000), default=5000, minimum=1, maximum=65535)
    debug = _as_bool(os.environ.get("FLASK_DEBUG", False), default=False)

    print("====================================")
    print("DairV2X Scene Graph 校对系统已启动")
    print("主功能: 治理运行与可视化审阅")
    print("次功能: 关系校对")
    print(f"请打开: http://{host}:{port}")
    print("====================================")
    app.run(host=host, debug=debug, port=port)
