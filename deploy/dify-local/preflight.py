#!/usr/bin/env python3
"""Read-only local resource check. This does not validate the business application."""
import json
import argparse
import platform
import shutil
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--install", action="store_true", help="Require installation headroom, rather than just the runtime reserve")
parser.add_argument("--resume", action="store_true", help="Resume a prepared instance with cached runtime/base disk; retain the 5 GiB live reserve")
args = parser.parse_args()
required_gib = 20 if args.install else 5

root = Path(__file__).resolve().parents[2]
prepared_resume = args.resume and (root / ".local/lima/huawei-dify/disk").is_file() and (root / ".local/dify/upstream/docker/.env").is_file()
if args.resume:
    required_gib = 19.5 if prepared_resume else 20
free = shutil.disk_usage(root).free
memory = int(subprocess.check_output(['sysctl', '-n', 'hw.memsize'], text=True))
result = {
    'architecture': platform.machine(),
    'memory_gib': round(memory / 2**30, 2),
    'available_disk_gib': round(free / 2**30, 2),
    'disk_reserve_gib': 5,
    'recommended_fresh_install_free_gib': 20,
    'prepared_instance_resume': bool(prepared_resume),
    'required_free_gib_for_this_action': required_gib,
    'lima_installed': (root / '.local/toolchain/bin/limactl').is_file(),
    'dify_source_present': (root / '.local/dify/upstream/docker/docker-compose.yaml').is_file(),
    'private_config_present': (root / '.local/dify/upstream/docker/.env').is_file(),
    'mode': 'single_user_development_trial_4gib_guest',
    'official_macos_vm_guidance_gib': 8,
    'fully_supported_resource_configuration': False,
}
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(0 if free >= required_gib * 2**30 and result['lima_installed'] and result['dify_source_present'] else 1)
