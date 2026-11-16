"""Deterministic local PNG core; not an HTTP adapter or publication approval."""

from .renderer import (
    PosterRenderError, RenderScope, VerifiedAsset, QuoteAuthorization,
    RenderAuthorization, PosterRequest, PNGPage, PosterResult,
    canonical_hash, asset_metadata_hash, render_poster,
)

__all__ = [
    "PosterRenderError", "RenderScope", "VerifiedAsset", "QuoteAuthorization",
    "RenderAuthorization", "PosterRequest", "PNGPage", "PosterResult",
    "canonical_hash", "asset_metadata_hash", "render_poster",
]
