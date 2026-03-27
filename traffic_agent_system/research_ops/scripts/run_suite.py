import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from glob import glob
from typing import Dict, List, Set


def read_json(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def list_runs(output_dir: str) -> Set[str]:
    return set(glob(os.path.join(output_dir, "run_*.jsonl")))


def newest(paths: Set[str]) -> str:
    if not paths:
        return ""
    return sorted(paths, key=lambda p: os.path.getmtime(p), reverse=True)[0]


def build_command(python_exe: str, pipeline_script: str, exp_output_dir: str, common: Dict, params: Dict) -> List[str]:
    merged = dict(common)
    merged.update(params or {})

    cmd = [
        python_exe,
        pipeline_script,
        "--data-dir",
        merged["data_dir"],
        "--bev-dir",
        merged["bev_dir"],
        "--raw-image-dir",
        merged["raw_image_dir"],
        "--max-frames",
        str(int(merged.get("max_frames", 100))),
        "--model",
        str(merged.get("model", "qwen3-vl:4b")),
        "--output-dir",
        exp_output_dir,
    ]

    if bool(merged.get("no_llm", False)):
        cmd.append("--no-llm")
    if bool(merged.get("no_report", False)):
        cmd.append("--no-report")
    if bool(merged.get("disable_temporal_calibration", False)):
        cmd.append("--disable-temporal-calibration")

    extra_args = merged.get("extra_args", [])
    if isinstance(extra_args, list):
        cmd.extend([str(x) for x in extra_args])

    return cmd


def run_experiment(python_exe: str, pipeline_script: str, output_root: str, common: Dict, exp: Dict) -> Dict:
    exp_name = exp["name"]
    exp_dir = os.path.join(output_root, exp_name)
    ensure_dir(exp_dir)

    before = list_runs(exp_dir)

    cmd = build_command(
        python_exe=python_exe,
        pipeline_script=pipeline_script,
        exp_output_dir=exp_dir,
        common=common,
        params=exp.get("params", {}),
    )

    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    t0 = time.time()

    proc = subprocess.run(cmd, cwd=os.path.dirname(pipeline_script), capture_output=True, text=True)

    duration = time.time() - t0
    finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    after = list_runs(exp_dir)
    new_runs = after - before
    run_jsonl = newest(new_runs) or newest(after)
    summary_json = os.path.splitext(run_jsonl)[0] + "_summary.json" if run_jsonl else ""

    stdout_path = os.path.join(exp_dir, "stdout.log")
    stderr_path = os.path.join(exp_dir, "stderr.log")
    with open(stdout_path, "w", encoding="utf-8") as f:
        f.write(proc.stdout or "")
    with open(stderr_path, "w", encoding="utf-8") as f:
        f.write(proc.stderr or "")

    manifest = {
        "experiment": exp_name,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_sec": round(duration, 3),
        "return_code": proc.returncode,
        "command": cmd,
        "run_jsonl": run_jsonl,
        "summary_json": summary_json,
        "stdout_log": stdout_path,
        "stderr_log": stderr_path,
    }

    manifest_path = os.path.join(exp_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"[DONE] {exp_name}: return_code={proc.returncode}, duration={duration:.2f}s")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Run experiment suite for traffic_agent_system")
    parser.add_argument("--suite", required=True, help="Path to suite json config")
    parser.add_argument("--fail-fast", action="store_true", help="Stop on first failed run")
    args = parser.parse_args()

    suite = read_json(args.suite)

    python_exe = suite.get("python_executable") or sys.executable
    pipeline_script = suite["pipeline_script"]
    output_root = suite["output_root"]
    common = suite.get("common", {})
    experiments = suite.get("experiments", [])

    ensure_dir(output_root)

    results = []
    for exp in experiments:
        manifest = run_experiment(python_exe, pipeline_script, output_root, common, exp)
        results.append(manifest)
        if args.fail_fast and int(manifest["return_code"]) != 0:
            break

    suite_manifest = {
        "suite_name": suite.get("suite_name", "unnamed_suite"),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "suite_config": os.path.abspath(args.suite),
        "experiments": results,
    }

    suite_manifest_path = os.path.join(output_root, "suite_manifest.json")
    with open(suite_manifest_path, "w", encoding="utf-8") as f:
        json.dump(suite_manifest, f, ensure_ascii=False, indent=2)

    print(f"[SUITE] manifest written: {suite_manifest_path}")


if __name__ == "__main__":
    main()
