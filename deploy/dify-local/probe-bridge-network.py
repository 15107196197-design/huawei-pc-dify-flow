#!/usr/bin/env python3
"""Probe Mac loopback reachability without knowledge data or credentials.

Starts a random-port, marker-only loopback server and closes it in finally.
Uses only an already-present BusyBox image; no mounts, images pulled, app/env
configuration changes, or persistent containers. Run from the project checkout.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
import time


@contextmanager
def marker_server():
    marker = "bridge-network-marker-" + secrets.token_hex(12)
    path = "/network-probe/" + secrets.token_hex(12)
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != path:
                self.send_error(404)
                return
            hits.append(time.time())
            payload = marker.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, path, marker, hits
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm", default="huawei-dify")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--ssrf-network", help="Existing Dify SSRF network name; optional, no network created")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["LIMA_HOME"] = str(root / ".local/lima")
    env.pop("LIMA_SSH_OVER_VSOCK", None)
    prefix = [str(root / ".local/toolchain/bin/limactl"), "shell", args.vm, "--"]
    results = []

    def probe(name, argv, expected, timeout=15):
        try:
            proc = subprocess.run(prefix + argv, env=env, text=True, capture_output=True, timeout=timeout)
            results.append({"name": name, "exit_code": proc.returncode,
                            "verified": proc.returncode == 0 and proc.stdout.strip() == expected,
                            "stderr": proc.stderr.strip()[-1200:]})
        except subprocess.TimeoutExpired:
            results.append({"name": name, "verified": False, "reason": "timeout"})

    with marker_server() as (port, path, marker, hits):
        ip_url = f"http://192.168.5.2:{port}{path}"
        host_url = f"http://host.lima.internal:{port}{path}"
        probe("guest_to_mac_ip", ["curl", "--noproxy", "*", "--connect-timeout", "4", "--max-time", "6", "-fsS", ip_url], marker)
        probe("guest_to_mac_name", ["curl", "--noproxy", "*", "--connect-timeout", "4", "--max-time", "6", "-fsS", host_url], marker)
        docker = ["docker", "run", "--rm", "--pull", "never", "--network", "bridge"]
        probe("container_to_mac_ip", docker + ["busybox:latest", "wget", "-T", "5", "-q", "-O", "-", ip_url], marker)
        probe("container_to_mac_name_unmapped", docker + ["busybox:latest", "wget", "-T", "5", "-q", "-O", "-", host_url], marker)
        probe("container_to_mac_name_explicit_mapping", docker + ["--add-host", "host.lima.internal:192.168.5.2", "busybox:latest", "wget", "-T", "5", "-q", "-O", "-", host_url], marker)
        if args.ssrf_network:
            probe("container_via_dify_ssrf_proxy", ["docker", "run", "--rm", "--pull", "never",
                  "--network", args.ssrf_network, "--env", "http_proxy=http://ssrf_proxy:3128",
                  "busybox:latest", "wget", "-Y", "on", "-T", "8", "-q", "-O", "-", ip_url], marker)
        hit_count = len(hits)
    report = {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "vm": args.vm,
              "marker_listen": "127.0.0.1", "marker_port": port,
              "marker_server_closed": True, "marker_request_count": hit_count,
              "knowledge_or_credentials_used": False, "results": results,
              "limitations": ["Marker reachability is not knowledge-service authorization or Dify node validation.",
                              "No SSRF allowlist configuration was changed."]}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
