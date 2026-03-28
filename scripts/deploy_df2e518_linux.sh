#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="https://github.com/naginya233/temporal-graph-governance.git"
REF="snapshot-df2e518"
TARGET_COMMIT="df2e518"
INSTALL_DIR="/opt/temporal-graph-governance"
SERVICE_NAME="traffic-governance-web"
HOST="0.0.0.0"
PORT="5000"
WITH_SERVICE="0"
SKIP_TESTS="0"
FORCE_RECREATE="0"

log() {
  echo "[deploy] $*"
}

die() {
  echo "[deploy][error] $*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage:
  bash scripts/deploy_df2e518_linux.sh [options]

Options:
  --repo-url <url>         Git repo url (default: official github repo)
  --ref <ref>              Git branch/tag/ref to fetch (default: snapshot-df2e518)
  --commit <sha>           Target commit to checkout (default: df2e518)
  --install-dir <path>     Install directory (default: /opt/temporal-graph-governance)
  --service-name <name>    systemd service name (default: traffic-governance-web)
  --host <host>            Web host bind (default: 0.0.0.0)
  --port <port>            Web port (default: 5000)
  --with-service           Install and start systemd service
  --skip-tests             Skip unittest validation
  --force-recreate         Delete install-dir and re-clone
  -h, --help               Show this help

Examples:
  # one-click deploy, manual run
  bash scripts/deploy_df2e518_linux.sh

  # deploy and install service
  bash scripts/deploy_df2e518_linux.sh --with-service --install-dir /opt/tg
EOF
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "command not found: $1"
}

as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

write_file_root() {
  local target="$1"
  shift
  if [ "$(id -u)" -eq 0 ]; then
    cat >"$target"
  else
    cat | sudo tee "$target" >/dev/null
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo-url)
      REPO_URL="$2"
      shift 2
      ;;
    --ref)
      REF="$2"
      shift 2
      ;;
    --commit)
      TARGET_COMMIT="$2"
      shift 2
      ;;
    --install-dir)
      INSTALL_DIR="$2"
      shift 2
      ;;
    --service-name)
      SERVICE_NAME="$2"
      shift 2
      ;;
    --host)
      HOST="$2"
      shift 2
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    --with-service)
      WITH_SERVICE="1"
      shift
      ;;
    --skip-tests)
      SKIP_TESTS="1"
      shift
      ;;
    --force-recreate)
      FORCE_RECREATE="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

need_cmd git
need_cmd python3
need_cmd bash

if [ "$WITH_SERVICE" = "1" ]; then
  need_cmd systemctl
fi

log "repo-url: $REPO_URL"
log "ref: $REF"
log "target-commit: $TARGET_COMMIT"
log "install-dir: $INSTALL_DIR"

if [ "$FORCE_RECREATE" = "1" ] && [ -d "$INSTALL_DIR" ]; then
  log "removing existing install dir: $INSTALL_DIR"
  as_root rm -rf "$INSTALL_DIR"
fi

if [ -d "$INSTALL_DIR/.git" ]; then
  log "existing repo detected, fetching updates"
  git -C "$INSTALL_DIR" fetch --all --tags --prune
else
  log "cloning repository"
  parent_dir="$(dirname "$INSTALL_DIR")"
  as_root mkdir -p "$parent_dir"
  if [ "$(id -u)" -eq 0 ]; then
    git clone "$REPO_URL" "$INSTALL_DIR"
  else
    sudo git clone "$REPO_URL" "$INSTALL_DIR"
    sudo chown -R "$USER":"$(id -gn "$USER")" "$INSTALL_DIR"
  fi
fi

log "fetching ref: $REF"
git -C "$INSTALL_DIR" fetch origin "$REF" --prune

log "checking out target commit: $TARGET_COMMIT"
git -C "$INSTALL_DIR" checkout -f "$TARGET_COMMIT"
current_commit="$(git -C "$INSTALL_DIR" rev-parse --short HEAD)"
if [ "$current_commit" != "$TARGET_COMMIT" ]; then
  die "checkout mismatch, got $current_commit expected $TARGET_COMMIT"
fi

PY_BIN="$INSTALL_DIR/.venv/bin/python"
PIP_BIN="$INSTALL_DIR/.venv/bin/pip"

log "creating virtual environment"
python3 -m venv "$INSTALL_DIR/.venv"
"$PY_BIN" -m ensurepip --upgrade >/dev/null 2>&1 || true

log "installing dependencies"
"$PIP_BIN" install --upgrade pip wheel
"$PIP_BIN" install -r "$INSTALL_DIR/requirements.txt" gunicorn

log "running syntax check"
"$PY_BIN" -m py_compile "$INSTALL_DIR/DairV2X_SceneGraph_Validator/app.py"

if [ "$SKIP_TESTS" != "1" ]; then
  log "running unit tests"
  (
    cd "$INSTALL_DIR/traffic_agent_system"
    "$PY_BIN" -m unittest discover -s tests -p "test_*.py"
  )
else
  log "skip-tests enabled, not running unit tests"
fi

log "writing runtime env file"
cat > "$INSTALL_DIR/.edge.env" <<EOF
HOST=$HOST
PORT=$PORT
FLASK_DEBUG=0
EOF

log "writing manual start script"
cat > "$INSTALL_DIR/run_web.sh" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$ROOT_DIR/.edge.env"
exec "$ROOT_DIR/.venv/bin/gunicorn" -w 2 -b "${HOST}:${PORT}" DairV2X_SceneGraph_Validator.app:app
EOF
chmod +x "$INSTALL_DIR/run_web.sh"

if [ "$WITH_SERVICE" = "1" ]; then
  run_user="${SUDO_USER:-$USER}"
  run_group="$(id -gn "$run_user")"
  unit_path="/etc/systemd/system/${SERVICE_NAME}.service"

  log "installing systemd service: $SERVICE_NAME"
  cat <<EOF | write_file_root "$unit_path"
[Unit]
Description=Traffic Governance Web (${TARGET_COMMIT})
After=network.target

[Service]
Type=simple
User=${run_user}
Group=${run_group}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.edge.env
ExecStart=${INSTALL_DIR}/.venv/bin/gunicorn -w 2 -b \${HOST}:\${PORT} DairV2X_SceneGraph_Validator.app:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

  as_root systemctl daemon-reload
  as_root systemctl enable "$SERVICE_NAME"
  as_root systemctl restart "$SERVICE_NAME"
  as_root systemctl --no-pager --full status "$SERVICE_NAME" || true

  log "service installed and started"
  log "open: http://${HOST}:${PORT}"
  log "showcase: http://${HOST}:${PORT}/showcase"
else
  log "deployment finished (service not installed)"
  log "manual start:"
  echo "  cd $INSTALL_DIR && ./run_web.sh"
  log "open: http://${HOST}:${PORT}"
  log "showcase: http://${HOST}:${PORT}/showcase"
fi
