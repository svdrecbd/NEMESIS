import pytest
from pathlib import Path
from app.core.configio import save_config, load_config

def test_config_save_load(tmp_path):
    cfg_path = tmp_path / "test_config.json"
    cfg = {"param1": 10, "param2": "value"}
    
    save_config(cfg, cfg_path)
    assert cfg_path.exists()
    
    loaded = load_config(cfg_path)
    assert loaded == cfg

def test_load_nonexistent_config(tmp_path):
    assert load_config(tmp_path / "nope.json") is None
