"""Vendored Mosaicker_v2 engine.

The engine is imported lazily by ``MosaickingService`` so its optional
geospatial dependencies do not affect unrelated Image Mate workflows.
"""

from .seamless_mosaic import MosaicError, build_parser, main, run

__all__ = ["MosaicError", "build_parser", "main", "run"]
