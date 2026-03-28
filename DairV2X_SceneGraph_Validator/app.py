import glob
import json
import os
import subprocess
import sys
import threading
from collections import Counter, deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

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

    for key in ("slowdown", "risk", "calibrated_slowdown", "calibrated_risk", "raw_slowdown", "raw_risk"):
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
                gov_index_data = old_records
                gov_meta = {
                    "runs": old_payload.get("runs", []),
                    "selected_run": old_selected_run,
                    "summary": old_payload.get("summary", {}),
                    "event_segments": old_payload.get("event_segments", []),
                }
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


@app.route("/api/governance/next", methods=["GET"])
def get_next_governance():
    for idx, record in enumerate(gov_index_data):
        if record.get("status") == "pending":
            assets = record.get("assets", {})
            return jsonify(
                {
                    "task": record,
                    "index": idx,
                    "img_path": assets.get("raw_image", ""),
                    "schematic_path": assets.get("bev_image", ""),
                }
            )
    return jsonify({"task": None})


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
