"""Read-only local/hybrid source bridge; real pricing remains blocked."""

from .bridge import Bridge, BridgeError, Config

__all__ = ["Bridge", "BridgeError", "Config"]
