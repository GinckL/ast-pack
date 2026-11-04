from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "polyglot"


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path_factory, monkeypatch):
    # Never touch the user's real cache from tests.
    monkeypatch.setenv("AST_PACK_CACHE_DIR", str(tmp_path_factory.getbasetemp() / "cache"))


@pytest.fixture(scope="session")
def fixture_root() -> Path:
    return FIXTURE


@pytest.fixture(scope="session")
def index():
    from ast_pack.index import IndexOptions, RepoIndex

    return RepoIndex.build(FIXTURE, IndexOptions(use_cache=False))
