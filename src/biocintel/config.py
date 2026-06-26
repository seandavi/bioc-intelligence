"""Static configuration: source URLs, the four repos, and release metadata.

The repo table encodes the two-name quirk in Bioconductor's layout (confirmed
against ``BiocPkgTools``): the VIEWS path, the download-stats *directory*, and
the download-stats *filename prefix* are not always the same string
(e.g. ``data-experiment`` directory holds ``experiment_pkg_stats.tab``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from .http import get_text

BIOC_BASE = os.getenv("BIOCINTEL_BIOC_BASE", "https://bioconductor.org")
CONFIG_YAML_URL = f"{BIOC_BASE}/config.yaml"

# Default on-disk locations (override via env for CI / alternate data roots).
DATA_ROOT = Path(os.getenv("BIOCINTEL_DATA_ROOT", "data"))
DB_PATH = Path(os.getenv("BIOCINTEL_DB_PATH", str(DATA_ROOT / "biocintel.duckdb")))
MART_DIR = Path(os.getenv("BIOCINTEL_MART_DIR", str(DATA_ROOT / "marts")))

# Download-stat collection methodology changed around Oct 2015 (spec §6); rows on
# either side of this boundary are not silently comparable.
METHODOLOGY_ERA_BOUNDARY = (2015, 10)


@dataclass(frozen=True)
class Repo:
    """One Bioconductor package repository and its (sometimes divergent) paths."""

    key: str  # canonical key used throughout the data model (matches spec)
    views_path: str  # under /packages/<release|devel>/<views_path>/VIEWS
    stats_dir: str  # under /packages/stats/<stats_dir>/
    stats_file: str  # <stats_file>_pkg_stats.tab
    tier: int  # 1 = bioc (eager), 2 = the rest (lazy)


REPOS: dict[str, Repo] = {
    "bioc": Repo("bioc", "bioc", "bioc", "bioc", tier=1),
    "data-experiment": Repo(
        "data-experiment", "data/experiment", "data-experiment", "experiment", tier=2
    ),
    "data-annotation": Repo(
        "data-annotation", "data/annotation", "data-annotation", "annotation", tier=2
    ),
    "workflows": Repo("workflows", "workflows", "workflows", "workflows", tier=2),
}


def views_url(repo: Repo, *, devel: bool = False) -> str:
    channel = "devel" if devel else "release"
    return f"{BIOC_BASE}/packages/{channel}/{repo.views_path}/VIEWS"


def stats_url(repo: Repo) -> str:
    return f"{BIOC_BASE}/packages/stats/{repo.stats_dir}/{repo.stats_file}_pkg_stats.tab"


def methodology_era(year: int, month: int) -> str:
    """Label a download (year, month) by collection era (spec §6)."""
    return "pre_2015_10" if (year, month) < METHODOLOGY_ERA_BOUNDARY else "modern"


@dataclass(frozen=True)
class ReleaseConfig:
    """Release-level facts parsed from Bioconductor's ``config.yaml``."""

    release_version: str  # e.g. "3.23"
    devel_version: str  # e.g. "3.24"
    release_dates: dict[str, str]  # bioc_release -> human date string
    r_versions: dict[str, str]  # bioc_release -> R version


def fetch_release_config() -> ReleaseConfig:
    """Fetch + parse ``config.yaml`` for release/devel versions and dates."""
    doc = yaml.safe_load(get_text(CONFIG_YAML_URL))
    return ReleaseConfig(
        release_version=str(doc["release_version"]),
        devel_version=str(doc["devel_version"]),
        release_dates={str(k): str(v) for k, v in (doc.get("release_dates") or {}).items()},
        r_versions={str(k): str(v) for k, v in (doc.get("r_ver_for_bioc_ver") or {}).items()},
    )
