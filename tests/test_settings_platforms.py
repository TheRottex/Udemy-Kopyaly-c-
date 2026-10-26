import json

import pytest

import platforms
from kurs_app.settings import SettingsStore


def test_settings_validation(tmp_path):
    s = SettingsStore(tmp_path / "s.json")
    assert s.get()["crf"] == 22
    s.update({"crf": 20, "encoder": "x264"})
    assert SettingsStore(tmp_path / "s.json").get()["crf"] == 20
    for bad in ({"crf": 99}, {"encoder": "evil"}, {"parallel": 0}, {"nope": 1}, {"crf": True}, {"handbrake_path": "a\nb"}):
        with pytest.raises(ValueError):
            s.update(bad)


def test_registry_has_generic_and_example(paths):
    reg = platforms.load_registry(paths)
    assert "generic" in reg and "ornek" in reg
    assert list(reg)[0] == "generic"


def test_save_profile_validates(paths):
    platforms.save_profile(paths, "siteim", {"login_url": "https://a.b/login", "lesson_selector": "a.l", "video_wait": "15"})
    assert json.loads((paths.profiles / "siteim.json").read_text())["video_wait"] == 15.0
    for pid, cfg in (("../x", {}), ("ok", {"bilinmeyen": "x"}), ("ok", {"login_url": "ftp://x"}), ("ok", {"video_wait": "999"})):
        with pytest.raises(ValueError):
            platforms.save_profile(paths, pid, cfg)
