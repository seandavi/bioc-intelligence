"""Offline guards for enrich_from_lake: import-safety + step validation.

Importing must not require the cdsci-lake client (it is lazy in lake.py), and the
CLI must reject unknown steps.
"""

import pytest

from biocintel.pipeline import enrich_from_lake


def test_imports_without_lake_client():
    assert callable(enrich_from_lake.run)
    assert enrich_from_lake.DEFAULT_STEPS == ("works", "grants")
    assert "citations" in enrich_from_lake.ALL_STEPS


def test_cli_rejects_unknown_step():
    with pytest.raises(SystemExit):
        enrich_from_lake.main(["--steps", "works,bogus"])
