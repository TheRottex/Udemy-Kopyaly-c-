"""Platform kayıt defteri: adaptör modülleri + JSON profilleri.

Yükleme sırası: (1) bu pakette `ADAPTERS` listesi tanımlayan modüller,
(2) platforms/profiles/*.json (depoyla gelen örnekler), (3) data/profiles/*.json (kullanıcı profilleri,
arayüzden de oluşturulur). 'generic' her zaman vardır."""
import importlib
import json
import pkgutil
import re

from .generic import CONFIG_KEYS, GenericAdapter

PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


def _read(path):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def load_registry(paths) -> dict:
    reg: dict = {}
    for m in pkgutil.iter_modules(__path__):
        if m.name in ("generic",):
            continue
        mod = importlib.import_module(f"{__name__}.{m.name}")
        for a in getattr(mod, "ADAPTERS", []):
            reg[a.id] = a
    from pathlib import Path
    dirs = [Path(__file__).parent / "profiles", paths.profiles]
    for d in dirs:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.json")):
            cfg = _read(f)
            if isinstance(cfg, dict) and PROFILE_ID_RE.match(f.stem):
                reg[f.stem] = GenericAdapter(f.stem, cfg)
    reg.setdefault("generic", GenericAdapter("generic", {}))
    return dict(sorted(reg.items(), key=lambda kv: (kv[0] != "generic", kv[0])))


def save_profile(paths, profile_id: str, cfg: dict) -> None:
    if not PROFILE_ID_RE.match(profile_id):
        raise ValueError("Geçersiz profil kimliği (küçük harf, rakam, - _)")
    clean = {}
    for k, v in cfg.items():
        if k not in CONFIG_KEYS:
            raise ValueError(f"Bilinmeyen anahtar: {k}")
        if v in (None, ""):
            continue
        if k == "video_wait":
            v = float(v)
            if not 1 <= v <= 120:
                raise ValueError("video_wait 1-120 olmalı")
        elif not isinstance(v, str) or len(v) > 500:
            raise ValueError(f"{k} metin olmalı")
        elif k.endswith("_url") and not v.startswith(("http://", "https://")):
            raise ValueError(f"{k} http(s) olmalı")
        clean[k] = v
    paths.profiles.mkdir(parents=True, exist_ok=True)
    (paths.profiles / f"{profile_id}.json").write_text(json.dumps(clean, ensure_ascii=False, indent=2), "utf-8")
