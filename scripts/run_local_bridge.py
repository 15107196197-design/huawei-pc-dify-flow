#!/usr/bin/env python3
"""Configure/run the loopback development bridge. Never prints credentials."""
import argparse
import json
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / '.local' / 'knowledge-bridge'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['setup', 'serve', 'status'])
    parser.add_argument('--kb-root', type=Path)
    args = parser.parse_args()
    if PRIVATE.is_symlink():
        parser.error('Private configuration directory must not be a symlink.')
    if args.command == 'setup':
        if args.kb_root is None or args.kb_root.is_symlink() or not args.kb_root.is_dir():
            parser.error('An authorized real --kb-root directory is required.')
        PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
        PRIVATE.chmod(0o700)
        token_path = PRIVATE / 'service-token'
        config_path = PRIVATE / 'config.json'
        for path in [token_path, config_path]:
            if path.is_symlink():
                parser.error('Private files must not be symlinks.')
        if not token_path.exists():
            fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as output:
                output.write(secrets.token_urlsafe(32))
        if not config_path.exists():
            fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as output:
                json.dump({'kb_root': str(args.kb_root.resolve()), 'allowed_model_destinations': []}, output)
        else:
            saved = json.loads(config_path.read_text())
            if Path(saved['kb_root']) != args.kb_root.resolve():
                parser.error('Existing source binding differs; review the private configuration before changing it.')
        token_path.chmod(0o600)
        config_path.chmod(0o600)
        print('Private local configuration prepared; model disclosure remains disabled.')
        return
    config_path, token_path = PRIVATE / 'config.json', PRIVATE / 'service-token'
    if any(path.is_symlink() or not path.is_file() for path in [config_path, token_path]):
        parser.error('Run setup first; private files must be real files.')
    if any(path.stat().st_mode & 0o077 for path in [config_path, token_path]):
        parser.error('Private files require mode 0600.')
    config = json.loads(config_path.read_text())
    if args.command == 'status':
        print(json.dumps({'configuration_present': True, 'source_present': Path(config['kb_root']).is_dir(),
                          'model_destinations_configured': bool(config.get('allowed_model_destinations')),
                          'default_source_mode': config.get('default_source_mode', 'local_snapshot'),
                          'ima_verification_enabled': config.get('enable_ima_verification', False),
                          'bind': '127.0.0.1:8765', 'multi_store_ready': False}))
        return
    os.environ['HUAWEI_KB_ROOT'] = config['kb_root']
    os.environ['HUAWEI_TOOL_TOKEN'] = token_path.read_text().strip()
    os.environ['HUAWEI_ALLOWED_MODEL_DESTINATIONS_JSON'] = json.dumps(config.get('allowed_model_destinations', []))
    os.environ['HUAWEI_SOURCE_MODE'] = config.get('default_source_mode', 'local_snapshot')
    enabled = config.get('enable_ima_verification', False)
    if type(enabled) is not bool:
        parser.error('IMA verification enablement must be a boolean.')
    os.environ['HUAWEI_ENABLE_IMA_VERIFICATION'] = '1' if enabled else '0'
    os.chdir(ROOT)
    os.execv(sys.executable, [sys.executable, '-m', 'services.knowledge_bridge', 'serve'])


if __name__ == '__main__':
    main()
