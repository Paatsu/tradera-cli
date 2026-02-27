from __future__ import annotations

import runpy

import pytest


def test_package_main_invokes_cli_main(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"value": False}

    def fake_main() -> None:
        called["value"] = True

    monkeypatch.setattr("tradera_cli.cli.main", fake_main)

    runpy.run_module("tradera_cli", run_name="__main__")

    assert called["value"] is True
