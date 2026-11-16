#!/usr/bin/env python3
"""Generate a reviewable, exact local bridge ACL from Dify 1.17.1 template.

No Docker/Lima calls, environment reads, or network operations. Rejects upstream
template drift rather than broadening access on an unreviewed configuration.
"""
from __future__ import annotations

import argparse
from pathlib import Path


UPSTREAM = """include /etc/squid/dify_common.conf

acl allowed_domains dstdomain .marketplace.dify.ai

http_port ${HTTP_PORT}

http_access deny !Safe_ports
http_access deny CONNECT !SSL_ports
http_access allow localhost manager
http_access deny manager
include /etc/squid/dify_sandbox_proxy.conf
include /etc/squid/dify_allow_private.conf
http_access deny to_private_networks
http_access allow allowed_domains
http_access allow client_localnet
http_access allow localhost
http_access deny all
"""


def generate(source: str) -> str:
    candidate = (
        "# Reviewed local bridge exception for Dify 1.17.1. Not applied automatically.\n"
        "# Keep the upstream common and sandbox includes. The generated broad private-IP\n"
        "# allowlist is deliberately not included: only this destination/port/path tuple\n"
        "# may reach the Mac knowledge bridge through this proxy.\n"
        + UPSTREAM.replace(
            "acl allowed_domains dstdomain .marketplace.dify.ai\n",
            "acl allowed_domains dstdomain .marketplace.dify.ai\n"
            "acl huawei_bridge_dst dst 192.168.5.2/32\n"
            "acl huawei_bridge_port port 8765\n"
            "acl huawei_bridge_method method POST\n"
            "acl huawei_bridge_path urlpath_regex ^/v1/(contexts/resolve|kb/evidence|quotes/solve)$\n"
        ).replace("include /etc/squid/dify_allow_private.conf\n", "").replace(
            "http_access deny to_private_networks\n",
            "http_access allow client_localnet huawei_bridge_dst huawei_bridge_port huawei_bridge_method huawei_bridge_path\n"
            "http_access deny to_private_networks\n"
        )
    )
    if source == candidate:
        return candidate
    if source != UPSTREAM:
        raise ValueError("Dify SSRF template differs from reviewed 1.17.1 input; review drift before applying.")
    return candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        content = generate(args.source.read_text())
    except ValueError as error:
        parser.error(str(error))
    args.output.write_text(content)
    print("Generated reviewed POST-only three-endpoint bridge policy.")


if __name__ == "__main__":
    main()
