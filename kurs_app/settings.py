import json
import threading
from pathlib import Path

PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]
ENCODERS = ["x265", "x264"]

DEFAULTS = {
    "encode_enabled": True,
    "encoder": "x265",
    "crf": 22,
    "preset": "medium",
    "parallel": 2,
    "handbrake_path": "HandBrakeCLI",
}


def validate(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if k not in DEFAULTS:
            raise ValueError(f"Bilinmeyen ayar: {k}")
        if k == "encode_enabled":
            if not isinstance(v, bool):
                raise ValueError("encode_enabled bool olmalı")
        elif k == "encoder":
            if v not in ENCODERS:
                raise ValueError(f"encoder şunlardan biri olmalı: {ENCODERS}")
        elif k == "preset":
            if v not in PRESETS:
                raise ValueError(f"preset şunlardan biri olmalı: {PRESETS}")
        elif k == "crf":
            if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 51:
                raise ValueError("crf 0-51 arası tam sayı olmalı")
        elif k == "parallel":
            if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 8:
                raise ValueError("parallel 1-8 arası tam sayı olmalı")
        elif k == "handbrake_path":
            if not isinstance(v, str) or not v.strip() or len(v) > 500 or "\n" in v:
                raise ValueError("handbrake_path geçersiz")
            v = v.strip()
        out[k] = v
    return out


class SettingsStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data = dict(DEFAULTS)
        if self.path.exists():
            try:
                self._data.update(validate(json.loads(self.path.read_text("utf-8"))))
            except (ValueError, OSError):
                pass

    def get(self) -> dict:
        with self._lock:
            return dict(self._data)

    def update(self, partial: dict) -> dict:
        clean = validate(partial)
        with self._lock:
            self._data.update(clean)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=2), "utf-8")
            return dict(self._data)
