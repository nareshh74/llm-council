import runpy
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "models, expected",
    [
        ("provider/alpha, provider/beta", ["provider/alpha", "provider/beta"]),
        ("provider/solo", ["provider/solo"]),
    ],
)
def test_local_model_overrides(monkeypatch, models, expected):
    monkeypatch.setenv("COUNCIL_MODELS", models)
    monkeypatch.setenv("CHAIRMAN_MODEL", "provider/chair")

    config = runpy.run_path(str(Path(__file__).resolve().parents[2] / "backend" / "config.py"))

    assert config["COUNCIL_MODELS"] == expected
    assert config["CHAIRMAN_MODEL"] == "provider/chair"
