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

## Docker

Build image:

```bash
docker build -t traffic-governance-web:latest .
```

Run container:

```bash
docker run --rm -p 5000:5000 traffic-governance-web:latest
```

Run with compose:

```bash
docker compose up -d --build
```

Then open:

- http://127.0.0.1:5000
- http://127.0.0.1:5000/showcase

Notes:

- Container persists web config/index files through mounts in `docker-compose.yml`.
- If datasets are outside the repository, add host path mounts in `docker-compose.yml` and set paths in the web settings page.

## Linux Edge One-Click Deploy (No Docker)

Snapshot `df2e518` has been pushed to GitHub branch `snapshot-df2e518`.

On the edge Linux device:

```bash
git clone https://github.com/naginya233/temporal-graph-governance.git
cd temporal-graph-governance
bash scripts/deploy_df2e518_linux.sh --with-service --install-dir /opt/temporal-graph-governance
```

After deploy:

- Web: `http://<edge-ip>:5000`
- Showcase: `http://<edge-ip>:5000/showcase`

Useful options:

```bash
# no systemd, manual run mode
bash scripts/deploy_df2e518_linux.sh --install-dir /opt/temporal-graph-governance

# skip unit tests for faster install
bash scripts/deploy_df2e518_linux.sh --with-service --skip-tests

# force clean reinstall
bash scripts/deploy_df2e518_linux.sh --with-service --force-recreate
```

## Notes

- This package intentionally excludes local runtime outputs and machine-specific config files.
- Set your local data paths in the web console settings after first start.
