import pytest

from biocintel import rsec


@pytest.fixture(autouse=True)
def no_rsec_clone(monkeypatch):
    """Keep every test offline: `extract_packages.run()` calls `rsec.refresh_dim_package`,
    which would otherwise `git clone` the RSEc repo. A failed fetch makes the refresh a no-op."""

    def refuse() -> list[str]:
        raise FileNotFoundError("tests must not run git; monkeypatch rsec.fetch_rsec_paths")

    monkeypatch.setattr(rsec, "fetch_rsec_paths", refuse)
