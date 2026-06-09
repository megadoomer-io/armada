"""Shared fixtures for Armada tests."""

import pathlib

import pytest


@pytest.fixture
def tmp_config_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    config_dir = tmp_path / "config" / "armada"
    config_dir.mkdir(parents=True)
    return config_dir


@pytest.fixture
def tmp_state_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    state_dir = tmp_path / "state" / "armada"
    state_dir.mkdir(parents=True)
    (state_dir / "grains").mkdir()
    (state_dir / "queues").mkdir()
    return state_dir


@pytest.fixture
def tmp_cache_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    cache_dir = tmp_path / "cache" / "armada"
    cache_dir.mkdir(parents=True)
    (cache_dir / "repos").mkdir()
    (cache_dir / "comparisons").mkdir()
    return cache_dir


@pytest.fixture
def xdg_dirs(
    tmp_config_dir: pathlib.Path,
    tmp_state_dir: pathlib.Path,
    tmp_cache_dir: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, pathlib.Path]:
    monkeypatch.setenv("ARMADA_CONFIG_DIR", str(tmp_config_dir))
    monkeypatch.setenv("ARMADA_STATE_DIR", str(tmp_state_dir))
    monkeypatch.setenv("ARMADA_CACHE_DIR", str(tmp_cache_dir))
    return {
        "config": tmp_config_dir,
        "state": tmp_state_dir,
        "cache": tmp_cache_dir,
    }
