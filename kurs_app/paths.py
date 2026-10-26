import os
from pathlib import Path


class Paths:
    """Tüm depolama yolları tek yerde; testlerde kök değiştirilebilir."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root or os.environ.get("KURS_ROOT") or Path(__file__).resolve().parent.parent).resolve()
        self.raw = self.root / "indirilen"
        self.final = self.root / "final"
        self.resources = self.root / "kaynaklar"
        self.video_urls = self.root / "video_url_listesi"
        self.profile = self.root / "profil"
        self.data = self.root / "data"
        self.jobs = self.data / "jobs"
        self.profiles = self.data / "profiles"
        self.db = self.data / "app.db"
        self.settings = self.data / "settings.json"

    def ensure(self):
        for p in (self.raw, self.final, self.resources, self.video_urls, self.profile,
                  self.data, self.jobs, self.profiles):
            p.mkdir(parents=True, exist_ok=True)

    def rel(self, p: Path) -> str:
        return Path(p).resolve().relative_to(self.root).as_posix()

    def resolve_inside(self, rel: str) -> Path | None:
        """metadata'daki göreli yolu çözer; yalnızca depolama klasörleri içindeyse döner."""
        p = (self.root / rel).resolve()
        for base in (self.raw, self.final, self.resources):
            if p.is_relative_to(base.resolve()):
                return p
        return None

    def cookie_file(self, platform_id: str) -> Path:
        return self.profile / platform_id / "cookies.txt"

    def browser_dir(self, platform_id: str) -> Path:
        return self.profile / platform_id / "browser"
