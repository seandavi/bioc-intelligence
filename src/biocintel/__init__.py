"""Bioconductor Intelligence Platform — extract/enrich pipeline.

Framework-free extract modules (the omicidx pattern) write into a single DuckDB
file; ``build_marts`` exports Parquet marts for the zero-backend frontend. See
``bioc-intelligence-spec.md`` for the architecture and ``CLAUDE.md`` for orientation.
"""

__version__ = "0.1.0"
