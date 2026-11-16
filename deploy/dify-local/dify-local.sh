#!/bin/sh
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_dir=$(CDPATH= cd -- "$script_dir/../.." && pwd)
unset LIMA_SSH_OVER_VSOCK
export LIMA_HOME="$project_dir/.local/lima"
lima="$project_dir/.local/toolchain/bin/limactl"
case "${1:-status}" in
  resume-install)
    python3 "$script_dir/preflight.py" --resume
    rm -f "$project_dir/.local/dify-local-disk-guard.json"
    python3 -u "$script_dir/disk_guard.py" &
    guard_pid=$!
    trap 'kill "$guard_pid" 2>/dev/null || true' EXIT INT TERM
    "$lima" start huawei-dify --tty=false
    "$lima" shell huawei-dify bash -lc 'cd ~/dify-docker && COMPOSE_PARALLEL_LIMIT=2 docker compose pull --quiet && docker compose up -d'
    if [ -f "$project_dir/.local/dify-local-disk-guard.json" ]; then
      echo 'Installation stopped by disk reserve guard.' >&2; exit 1
    fi
    "$lima" shell huawei-dify bash -lc 'cd ~/dify-docker && docker compose ps'
    echo 'Containers requested. Verify HTTP and health status before marking deployment complete.'
    ;;
  status) "$lima" list huawei-dify; "$lima" shell huawei-dify bash -lc 'cd ~/dify-docker && docker compose ps' ;;
  start) python3 "$script_dir/preflight.py"; "$lima" start huawei-dify --tty=false; "$lima" shell huawei-dify bash -lc 'cd ~/dify-docker && docker compose up -d' ;;
  stop) "$lima" shell huawei-dify bash -lc 'cd ~/dify-docker && docker compose stop' || true; "$lima" stop huawei-dify ;;
  logs) "$lima" shell huawei-dify bash -lc 'cd ~/dify-docker && docker compose logs --tail=60' ;;
  verify-runtime) python3 "$script_dir/runtime-check.py" ;;
  *) echo 'Usage: dify-local.sh status|verify-runtime|resume-install|start|stop|logs' >&2; exit 2 ;;
esac
