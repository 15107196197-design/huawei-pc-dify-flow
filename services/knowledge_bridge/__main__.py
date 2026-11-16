"""CLI: python -m services.knowledge_bridge audit|search|serve."""
import argparse
import ipaddress
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys
import uuid

from .bridge import Bridge, BridgeError, Config


def envelope(status, data=None, error=None):
    return {"request_id": str(uuid.uuid4()), "status": status, "data": data, "error": error}


def make_server(bridge, host="127.0.0.1", port=8765):
    if not ipaddress.ip_address(host).is_loopback:
        raise BridgeError("INVALID_BIND", "This development service only binds to loopback.")

    class Handler(BaseHTTPRequestHandler):
        server_version = "LocalKnowledgeBridge/0.1"
        sys_version = ""

        def log_message(self, *args):
            pass  # Never log credentials, proof, request paths, or business bodies.

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def process(self):
            code = 200
            try:
                bridge.authenticate(self.headers.get("Authorization"))
                length = self.headers.get("Content-Length", "0")
                if not length.isdigit() or int(length) > 65536 or self.headers.get("Transfer-Encoding"):
                    raise BridgeError("INVALID_BODY", "A bounded JSON body is required.", http_status=413)
                raw = self.rfile.read(int(length))
                try:
                    body = json.loads(raw) if raw else {}
                except (ValueError, UnicodeError):
                    raise BridgeError("INVALID_JSON", "Request is not valid JSON.") from None
                status, data = bridge.handle(self.command, self.path, body, self.headers.get("Authorization"),
                                             self.headers.get("X-Source-Context-Proof"))
                response = envelope(status, data)
            except BridgeError as exc:
                code = exc.http_status
                response = envelope(exc.status, error={"code": exc.code, "message": exc.message})
            except Exception:
                code = 500
                response = envelope("error", error={"code": "INTERNAL_ERROR", "message": "Local service failed safely."})
            encoded = json.dumps(response, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        do_POST = process
        do_GET = process
        do_PUT = process
        do_DELETE = process
        do_PATCH = process
        do_OPTIONS = process
        do_HEAD = process

    return ThreadingHTTPServer((host, port), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("audit")
    search = sub.add_parser("search")
    search.add_argument("query")
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    try:
        config = Config.from_env()
        verifier = None
        if args.command == "serve" and (config.enable_ima_verification or config.default_source_mode == "hybrid_verified"):
            # Construction is lazy: local-only requests never read ima secrets
            # or open a connection, even when both modes are enabled.
            from services.ima_adapter.runtime import LazyHybridVerifier
            verifier = LazyHybridVerifier()
        bridge = Bridge(config, hybrid_verifier=verifier)
        if args.command == "audit":
            print(json.dumps(bridge.audit(), ensure_ascii=False, indent=2))
        elif args.command == "search":
            before = bridge.source.snapshot()
            model, candidates = bridge.source.resolve_model(args.query)
            if not model:
                print(json.dumps({"status": "needs_input", "candidates": candidates}, ensure_ascii=False))
                return 2
            facts, refs, omitted = bridge.source.facts(model)
            if before != bridge.source.snapshot():
                raise BridgeError("SOURCE_CHANGED", "Source changed during retrieval.", "needs_source", 409)
            print(json.dumps({"status": "ready", "source_mode": "local_snapshot", "competition_eligible": False,
                              "facts": facts, "source_refs": refs, "omitted_fact_fields": omitted}, ensure_ascii=False, indent=2))
        else:
            server = make_server(bridge, args.host, args.port)
            print(f"Local development bridge listening on {args.host}:{server.server_port}", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
        return 0
    except (BridgeError, OSError) as exc:
        code = exc.code if isinstance(exc, BridgeError) else "LOCAL_IO_ERROR"
        message = exc.message if isinstance(exc, BridgeError) else "Local source or listener is unavailable."
        print(json.dumps({"status": "error", "error": {"code": code, "message": message}}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
