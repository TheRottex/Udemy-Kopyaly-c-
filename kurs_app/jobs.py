"""İndirme kuyruğu: listeleme -> ders başına (keşif, indirme, yeniden kodlama, kaynaklar) -> metadata.
Duraklat/devam, yeniden deneme, paralel çalışma, diskten devam."""
import copy
import json
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from . import library
from .drm import DRM_MESSAGE, YTDLP_DRM_RE
from .fetch import fetch_resource
from .util import redact, slug


class Interrupted(Exception):
    pass


class DrmDetected(Exception):
    pass


def run_process(cmd, on_line, should_stop) -> int:
    """Alt süreci çalıştırır; satırları (\\r ve \\n ayırır) on_line'a verir; durdurulursa Interrupted."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)

    def reader():
        buf = b""
        while True:
            chunk = p.stdout.read(512)
            if not chunk:
                break
            buf += chunk
            parts = re.split(rb"[\r\n]", buf)
            buf = parts.pop()
            for part in parts:
                if part.strip():
                    on_line(part.decode("utf-8", "replace"))
        if buf.strip():
            on_line(buf.decode("utf-8", "replace"))

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    while p.poll() is None:
        if should_stop():
            p.terminate()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
            t.join(2)
            raise Interrupted()
        time.sleep(0.3)
    t.join(5)
    return p.returncode


DL_RE = re.compile(r"\[download\]\s+([\d.]+)%")
HB_RE = re.compile(r"Encoding:.*?([\d.]+)\s*%")
ACTIVE = ("queued", "listing", "running")


class JobManager:
    def __init__(self, paths, settings, browser, registry, runner=run_process,
                 probe=library.probe_duration, fetcher=fetch_resource):
        self.paths, self.settings, self.browser, self.registry = paths, settings, browser, registry
        self.runner, self.probe, self.fetcher = runner, probe, fetcher
        self.lock = threading.RLock()
        self.jobs: dict = {}
        self.version = 0
        self.tasks: queue.Queue = queue.Queue()
        self.list_q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._workers = 0
        self._last_save: dict = {}

    # ------------------------------------------------------------ yaşam döngüsü
    def start(self):
        self._load()
        threading.Thread(target=self._lister, daemon=True).start()
        self.ensure_workers()

    def stop(self):
        self._stop.set()

    def ensure_workers(self):
        with self.lock:
            while self._workers < self.settings.get()["parallel"]:
                self._workers += 1
                threading.Thread(target=self._worker, daemon=True).start()

    def _load(self):
        self.paths.jobs.mkdir(parents=True, exist_ok=True)
        for f in self.paths.jobs.glob("*.json"):
            try:
                job = json.loads(f.read_text("utf-8"))
            except (OSError, ValueError):
                continue
            if job.get("status") in ACTIVE:
                job["status"] = "paused"   # yarıda kalanlar kullanıcı 'Devam' diyene kadar bekler
                for l in job["lessons"]:
                    if l["status"] == "running":
                        l["status"] = "pending"
                    l["queued"] = False
            self.jobs[job["id"]] = job

    def _save(self, job, force=True):
        now = time.time()
        if not force and now - self._last_save.get(job["id"], 0) < 2:
            return
        self._last_save[job["id"]] = now
        p = self.paths.jobs / f"{job['id']}.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(job, ensure_ascii=False), "utf-8")
        tmp.replace(p)

    def _touch(self):
        self.version += 1

    def log(self, job, msg, level="info"):
        with self.lock:
            job["logs"].append({"t": time.time(), "level": level, "msg": redact(msg)})
            del job["logs"][:-300]
            self._touch()

    def snapshot(self) -> list:
        with self.lock:
            out = []
            for j in self.jobs.values():
                c = copy.deepcopy(j)
                c["logs"] = c["logs"][-120:]
                out.append(c)
            return sorted(out, key=lambda j: j["created"])

    # ------------------------------------------------------------ dış API
    def add_course(self, platform_id: str, course_url: str, title: str | None = None) -> dict:
        if platform_id not in self.registry:
            raise ValueError("Bilinmeyen platform")
        if not course_url.startswith(("http://", "https://")):
            raise ValueError("Kurs URL'si http(s) olmalı")
        with self.lock:
            for j in self.jobs.values():
                if j["platform"] == platform_id and j["course_url"] == course_url and j["status"] != "done":
                    self.resume(j["id"])
                    return j
            job = {"id": uuid.uuid4().hex[:8], "platform": platform_id, "course_url": course_url,
                   "title": title or course_url, "slug": slug(title or "kurs"), "status": "queued",
                   "created": time.time(), "error": "", "lessons": [], "course_resources": [], "logs": []}
            self.jobs[job["id"]] = job
            self._save(job)
            self._touch()
        self.list_q.put(job["id"])
        return job

    def pause(self, jid):
        with self.lock:
            j = self.jobs[jid]
            if j["status"] in ACTIVE:
                j["status"] = "paused"
                self._save(j)
                self._touch()

    def resume(self, jid):
        with self.lock:
            j = self.jobs[jid]
            if j["status"] not in ("paused", "partial", "error"):
                return
            j["status"] = "running" if j["lessons"] else "queued"
            self._save(j)
            self._touch()
            if not j["lessons"]:
                self.list_q.put(jid)
            else:
                self._enqueue_pending(j)

    def retry_failed(self, jid):
        with self.lock:
            j = self.jobs[jid]
            if not j["lessons"]:
                j["status"] = "queued"
                j["error"] = ""
                self.list_q.put(jid)
            for l in j["lessons"]:
                if l["status"] == "error":
                    l.update(status="pending", error="", progress=0, video_url=None)
            j["status"] = "running"
            self._save(j)
            self._touch()
            self._enqueue_pending(j)

    def remove(self, jid):
        with self.lock:
            j = self.jobs.pop(jid, None)
            if j:
                j["status"] = "removed"
            (self.paths.jobs / f"{jid}.json").unlink(missing_ok=True)
            self._touch()

    def _enqueue_pending(self, job):
        for l in job["lessons"]:
            if l["status"] == "pending" and not l.get("queued"):
                l["queued"] = True
                self.tasks.put((job["id"], l["index"]))

    # ------------------------------------------------------------ listeleme
    def _lister(self):
        while not self._stop.is_set():
            try:
                jid = self.list_q.get(timeout=1)
            except queue.Empty:
                continue
            job = self.jobs.get(jid)
            if job and job["status"] in ("queued", "running"):
                self._list_job(job)

    def _list_job(self, job):
        adapter = self.registry[job["platform"]]
        with self.lock:
            job["status"] = "listing"
            self._touch()
        self.log(job, "Kurs yapısı çıkarılıyor…")
        try:
            with self.browser.session(job["platform"]) as ctx:
                info = adapter.list_course(ctx, job["course_url"])
        except Exception as e:
            with self.lock:
                job.update(status="error", error=f"Listeleme hatası: {e}")
            self.log(job, f"Listeleme hatası: {e}", "error")
            self._save(job)
            return
        with self.lock:
            if job["status"] != "listing":   # kullanıcı bu sırada duraklattı/sildi
                return
            if not job["title"] or job["title"] == job["course_url"] or job["title"] == "kurs":
                job["title"] = info.title
            job["slug"] = slug(job["title"])
            idx = 0
            for s in info.sections:
                for l in s.lessons:
                    idx += 1
                    job["lessons"].append({"index": idx, "title": l.title, "section": s.title, "url": l.url,
                                           "status": "pending", "stage": "", "progress": 0, "error": "",
                                           "video_url": None, "resources": [], "queued": False,
                                           "duration": None})
            job["course_resources"] = [{"name": r.name, "url": r.url, "path": None} for r in info.course_resources]
            if not job["lessons"]:
                job.update(status="error", error="Hiç ders bulunamadı (lesson_selector'ı kontrol edin)")
                self._save(job)
                self._touch()
                return
            job["status"] = "running"
        self.log(job, f"{idx} ders bulundu, {len(job['course_resources'])} kurs kaynağı")
        self._fetch_all(job, job["course_resources"], self.paths.resources / job["slug"] / "00 - Kurs kaynakları",
                        job["course_url"])
        with self.lock:
            library.write_resource_url_files(self.paths, job)
            library.write_metadata(self.paths, job, self.probe)
            self._save(job)
            self._enqueue_pending(job)
            self._touch()

    def _fetch_all(self, job, items, folder, referer):
        cookie = self.paths.cookie_file(job["platform"])
        for r in items:
            if r.get("path"):
                continue
            try:
                res = self.fetcher(r["url"], folder, referer, cookie, r.get("name") or "dosya")
                r["path"] = self.paths.rel(Path(res["path"]))
                r["name"] = res["name"] if not r.get("name") or r["name"] == "dosya" else r["name"]
            except Exception as e:
                self.log(job, f"Kaynak indirilemedi ({r.get('name')}): {e}", "warn")

    # ------------------------------------------------------------ çalışanlar
    def _worker(self):
        while not self._stop.is_set():
            with self.lock:
                if self._workers > self.settings.get()["parallel"]:
                    self._workers -= 1
                    return
            try:
                jid, idx = self.tasks.get(timeout=1)
            except queue.Empty:
                continue
            try:
                self._process(jid, idx)
            except Exception as e:   # çalışan asla ölmesin
                j = self.jobs.get(jid)
                if j:
                    self.log(j, f"Beklenmeyen hata: {type(e).__name__}: {e}", "error")

    def _lesson(self, job, idx):
        return job["lessons"][idx - 1]

    def _set(self, lesson, job=None, **kw):
        with self.lock:
            lesson.update(kw)
            if job is not None:
                self._save(job, force=False)
            self._touch()

    def _process(self, jid, idx):
        job = self.jobs.get(jid)
        if not job:
            return
        lesson = self._lesson(job, idx)
        with self.lock:
            lesson["queued"] = False
            if job["status"] != "running" or lesson["status"] != "pending":
                return
            lesson.update(status="running", error="", stage="discover")
            self._touch()
        stop = lambda: job["status"] != "running" or self._stop.is_set()
        title = f"{idx:03d} - {lesson['title']}"
        try:
            self._run_lesson(job, lesson, stop)
            self._set(lesson, status="done", stage="", progress=100)
            self.log(job, f"Tamamlandı: {title}")
        except Interrupted:
            self._set(lesson, status="pending", stage="")
        except DrmDetected as e:
            self._set(lesson, status="drm", stage="", error=DRM_MESSAGE)
            self.log(job, f"⚠ {title}: {DRM_MESSAGE} ({e}) — atlandı", "warn")
        except Exception as e:
            self._set(lesson, status="error", stage="", error=redact(str(e))[:300])
            self.log(job, f"Hata: {title}: {e}", "error")
        self._after_lesson(job)

    def _after_lesson(self, job):
        with self.lock:
            try:
                library.write_video_urls(self.paths, job)
                library.write_resource_url_files(self.paths, job)
                library.write_metadata(self.paths, job, self.probe)
            except Exception as e:
                self.log(job, f"metadata yazılamadı: {e}", "error")
            sts = [l["status"] for l in job["lessons"]]
            if job["status"] == "running" and not any(s in ("pending", "running") for s in sts):
                job["status"] = "partial" if "error" in sts else "done"
                self.log(job, "Kurs işlendi: " + ", ".join(f"{sts.count(s)} {s}" for s in sorted(set(sts))))
            self._save(job)
            self._touch()

    def _run_lesson(self, job, lesson, stop):
        cfg = self.settings.get()
        idx, cslug = lesson["index"], job["slug"]
        base = library.lesson_base(idx, lesson["title"])
        raw_dir, fin_dir = self.paths.raw / cslug, self.paths.final / cslug
        raw = library.find_video(raw_dir, base)
        enc = cfg["encode_enabled"]
        lo, hi = (0, 60) if enc else (0, 100)

        if raw is None or not lesson.get("resources_done"):
            adapter = self.registry[job["platform"]]
            self._set(lesson, stage="discover", progress=2)
            with self.browser.session(job["platform"]) as ctx:
                info = adapter.inspect_lesson(ctx, lesson["url"])
            lesson["video_url"] = info.video.url
            lesson["resources"] = [{"name": r.name, "url": r.url, "path": None} for r in info.resources]
            self._fetch_all(job, lesson["resources"], self.paths.resources / cslug / base, lesson["url"])
            lesson["resources_done"] = True
            if raw is None:
                if info.video.drm:
                    raise DrmDetected(info.video.reason)
                if not info.video.url:
                    raise RuntimeError("Video kaynağı bulunamadı")
                self._download(job, lesson, info.video, raw_dir, base, lo, hi, stop)
                raw = library.find_video(raw_dir, base)
                if raw is None:
                    raise RuntimeError("İndirme sonrası video dosyası bulunamadı")

        if enc:
            final = fin_dir / (base + ".mp4")
            if not final.exists():
                self._encode(job, lesson, raw, final, cfg, hi, stop)
            for s in library.find_subtitles(raw):
                dst = fin_dir / s["path"].name
                if not dst.exists():
                    shutil.copy2(s["path"], dst)

    def _download(self, job, lesson, video, raw_dir, base, lo, hi, stop):
        raw_dir.mkdir(parents=True, exist_ok=True)
        cookie = self.paths.cookie_file(job["platform"])
        cmd = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--newline",
               "--add-header", f"Referer:{lesson['url']}",
               "-f", "bv*+ba/b", "-S", "res,br", "--merge-output-format", "mp4",
               "--concurrent-fragments", "8", "--retries", "10", "--continue",
               "--write-subs", "--sub-langs", "all,-live_chat", "--convert-subs", "vtt",
               "-o", str(raw_dir / base) + ".%(ext)s", video.url]
        if cookie.exists():
            cmd[3:3] = ["--cookies", str(cookie)]
        tail: list = []

        def on_line(line):
            m = DL_RE.search(line)
            if m:
                self._set(lesson, job, stage="download",
                          progress=round(lo + float(m.group(1)) * (hi - lo) / 100, 1))
            elif line.startswith(("ERROR", "WARNING")) or "DRM" in line:
                tail.append(line)
                del tail[:-8]

        self._set(lesson, job, stage="download")
        rc = self.runner(cmd, on_line, stop)
        if rc != 0:
            if any(YTDLP_DRM_RE.search(t) for t in tail):
                raise DrmDetected("yt-dlp: DRM korumalı akış")
            raise RuntimeError("yt-dlp başarısız: " + (tail[-1] if tail else f"kod {rc}"))

    def _hb(self, cfg) -> str:
        exe = shutil.which(cfg["handbrake_path"]) or (cfg["handbrake_path"] if Path(cfg["handbrake_path"]).is_file() else None)
        if not exe:
            raise RuntimeError("HandBrakeCLI bulunamadı (Ayarlar'dan yolu verin ya da yeniden kodlamayı kapatın)")
        return exe

    def _encode(self, job, lesson, raw, final, cfg, hi, stop):
        exe = self._hb(cfg)
        final.parent.mkdir(parents=True, exist_ok=True)
        tmp = final.with_name(final.stem + ".partial.mp4")
        tmp.unlink(missing_ok=True)
        cmd = [exe, "-i", str(raw), "-o", str(tmp), "-e", cfg["encoder"], "-q", str(cfg["crf"]),
               "--encoder-preset", cfg["preset"], "-E", "av_aac", "-B", "160", "--optimize"]

        def on_line(line):
            m = HB_RE.search(line)
            if m:
                self._set(lesson, job, stage="encode", progress=round(60 + float(m.group(1)) * (hi - 60) / 100, 1))

        self._set(lesson, job, stage="encode", progress=60)
        try:
            rc = self.runner(cmd, on_line, stop)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        if rc != 0 or not tmp.exists():
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"HandBrake başarısız (kod {rc})")
        tmp.replace(final)
