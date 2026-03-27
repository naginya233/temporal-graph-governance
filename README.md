# Integrated Traffic Governance + Review Console

This package combines two integrated components:

1. `traffic_agent_system`: scene-graph traffic governance pipeline.
2. `DairV2X_SceneGraph_Validator`: governance-first web console (with relation validation as secondary mode).

## What is included

- Temporal consistency calibration integrated in pipeline.
- Governance run control from web UI (start/stop/status/logs).
- Risk review flow with raw image + BEV + governance report.
- Research ops assets (suite configs, ablation matrix, scripts).

## Repository structure

- `traffic_agent_system/`
- `DairV2X_SceneGraph_Validator/`
- `requirements.txt` (installs both components)

## Quick start

### 1) Create env and install

```bash
python -m venv .venv
.venv\\Scripts\\activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

### 2) Run governance pipeline (example)

```bash
cd traffic_agent_system
python pipeline.py --max-frames 20 --no-llm
```

### 3) Run web console

```bash
cd DairV2X_SceneGraph_Validator
python app.py
```

Open: http://127.0.0.1:5000

## Notes

- This package intentionally excludes local runtime outputs and machine-specific config files.
- Set your local data paths in the web console settings after first start.
