import json
import os

import pytest


@pytest.fixture(autouse=True)
def data_folder(tmp_path, monkeypatch):
    """Every test in a data folder of its own, where a robot's default worktable file goes."""
    monkeypatch.setenv("IVORYOS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("IVORYOS_EDGE_HOME", raising=False)
    return tmp_path


def write(folder, config, name="worktable.json") -> str:
    path = os.path.join(str(folder), name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f)
    return path
