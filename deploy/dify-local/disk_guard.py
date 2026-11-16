#!/usr/bin/env python3
"""Temporary installation guard for the task-owned VM; never deletes user data."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

root = Path(__file__).resolve().parents[2]
parent = os.getppid()
env = dict(os.environ)
env['LIMA_HOME'] = str(root / '.local/lima')
env.pop('LIMA_SSH_OVER_VSOCK', None)
lima = str(root / '.local/toolchain/bin/limactl')
while os.getppid() == parent:
    remaining = shutil.disk_usage(root).free / 2**30
    if remaining < 5:
        marker = root / '.local/dify-local-disk-guard.json'
        marker.write_text(json.dumps({'reason': 'disk_reserve', 'remaining_gib': round(remaining, 2)}) + '\n')
        print(f'Disk guard: {remaining:.2f} GiB remains; stopping huawei-dify.', flush=True)
        try:
            subprocess.run([lima, 'stop', '--tty=false', 'huawei-dify'], env=env, timeout=45, check=True)
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
            subprocess.run([lima, 'stop', '--force', '--tty=false', 'huawei-dify'], env=env, timeout=30, check=False)
        break
    time.sleep(2)
