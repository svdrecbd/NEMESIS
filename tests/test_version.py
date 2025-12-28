from __future__ import annotations

from app.core import version as version_module


def test_get_app_version_reads_version(tmp_path, monkeypatch):
    version_file = tmp_path / "VERSION"
    version_file.write_text("1.2.3\n", encoding="utf-8")
    monkeypatch.setattr(version_module, "get_resource_path", lambda rel: tmp_path / rel)
    assert version_module.get_app_version(default="0.0.0") == "1.2.3"


def test_get_app_version_falls_back_on_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(version_module, "get_resource_path", lambda rel: tmp_path / rel)
    assert version_module.get_app_version(default="9.9.9") == "9.9.9"


def test_get_app_version_falls_back_on_empty(tmp_path, monkeypatch):
    version_file = tmp_path / "VERSION"
    version_file.write_text("   \n", encoding="utf-8")
    monkeypatch.setattr(version_module, "get_resource_path", lambda rel: tmp_path / rel)
    assert version_module.get_app_version(default="2.0.0") == "2.0.0"
