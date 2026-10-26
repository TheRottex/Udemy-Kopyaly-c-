"""FastAPI sunucusu: yalnızca 127.0.0.1'e bağlanır."""
import asyncio
import json
import mimetypes
import re
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

import platforms as platforms_pkg
from . import library
from .browser import BrowserManager, BusyError
from .db import Db
from .jobs import JobManager
from .paths import Paths
from .platform_base import ConfigError
from .settings import SettingsStore
from .util import srt_to_vtt

WEB = Path(__file__).resolve().parent.parent / "web"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "kurs-indirici"
INLINE_OK = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".txt", ".md", ".py", ".json", ".csv", ".mp3", ".mp4"}
TEXT_EXTS = {".txt", ".md", ".py", ".json", ".csv"}
CHUNK = 1024 * 1024


def range_response(request: Request, path: Path, media_type: str, headers: dict | None = None) -> Response:
    """HTTP Range destekli dosya sunumu (video arama/ileri sarma için)."""
    size = path.stat().st_size
    hdr = {"Accept-Ranges": "bytes", "X-Content-Type-Options": "nosniff", **(headers or {})}
    rng = request.headers.get("range")
    start, end, status = 0, size - 1, 200
    if rng:
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng.strip())
        if not m or (not m.group(1) and not m.group(2)):
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        if m.group(1):
            start = int(m.group(1))
            end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
        else:
            start, end = max(size - int(m.group(2)), 0), size - 1
        if start >= size or start > end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        status = 206
        hdr["Content-Range"] = f"bytes {start}-{end}/{size}"
    length = end - start + 1
    hdr["Content-Length"] = str(length)

    def gen():
        with open(path, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                data = f.read(min(CHUNK, left))
                if not data:
                    break
                left -= len(data)
                yield data

    if request.method == "HEAD":
        return Response(status_code=status, headers=hdr, media_type=media_type)
    return StreamingResponse(gen(), status_code=status, headers=hdr, media_type=media_type)


class SettingsIn(BaseModel):
    encode_enabled: bool | None = None
    encoder: str | None = None
    crf: int | None = None
    preset: str | None = None
    parallel: int | None = None
    handbrake_path: str | None = None


class CourseIn(BaseModel):
    url: str
    title: str = ""


class JobsIn(BaseModel):
    platform: str
    courses: list[CourseIn] = Field(min_length=1, max_length=50)


class ProfileIn(BaseModel):
    id: str
    config: dict = {}


class ProgressIn(BaseModel):
    position: float = Field(ge=0)
    duration: float = Field(default=0, ge=0)
    completed: bool = False


class NoteIn(BaseModel):
    t: float = Field(ge=0)
    text: str = Field(min_length=1, max_length=5000)


def create_app(paths: Paths | None = None, manager: JobManager | None = None, browser=None,
               start_workers: bool = True) -> FastAPI:
    paths = paths or Paths()
    paths.ensure()
    settings = SettingsStore(paths.settings)
    db = Db(paths.db)
    browser = browser or BrowserManager(paths)
    registry_holder = {"reg": platforms_pkg.load_registry(paths)}
    registry = registry_holder["reg"]
    mgr = manager or JobManager(paths, settings, browser, registry)

    @asynccontextmanager
    async def lifespan(app):
        if start_workers:
            mgr.start()
        yield
        mgr.stop()

    app = FastAPI(title="Kurs İndirici", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    app.state.mgr, app.state.settings, app.state.db, app.state.paths = mgr, settings, db, paths

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        # DNS rebinding / çapraz site isteklerine karşı: değiştiren isteklerde özel başlık şart
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
            return JSONResponse({"detail": "CSRF başlığı eksik"}, status_code=403)
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        return resp

    def adapter(pid):
        a = registry.get(pid)
        if not a:
            raise HTTPException(404, "Platform yok")
        return a

    # -------------------------------------------------------------- sayfa
    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-store"})

    # -------------------------------------------------------------- platformlar
    @app.get("/api/platforms")
    def list_platforms():
        return [{"id": a.id, "name": a.name, "configurable": a.configurable, "login_url": a.login_url,
                 "session": browser.has_session(a.id)} for a in registry.values()]

    @app.post("/api/platforms")
    def create_profile(body: ProfileIn):
        try:
            platforms_pkg.save_profile(paths, body.id, body.config)
        except ValueError as e:
            raise HTTPException(400, str(e))
        registry.update(platforms_pkg.load_registry(paths))
        return {"ok": True}

    @app.get("/api/platforms/{pid}/config")
    def get_config(pid: str):
        a = adapter(pid)
        if not a.configurable:
            raise HTTPException(400, "Bu platform ayarlanamaz")
        return {"config": a.cfg, "keys": __import__("platforms.generic", fromlist=["x"]).CONFIG_KEYS}

    @app.put("/api/platforms/{pid}/config")
    def put_config(pid: str, body: dict):
        a = adapter(pid)
        if not a.configurable:
            raise HTTPException(400, "Bu platform ayarlanamaz")
        try:
            platforms_pkg.save_profile(paths, pid, body)
        except (ValueError, TypeError) as e:
            raise HTTPException(400, str(e))
        registry.update(platforms_pkg.load_registry(paths))
        return {"ok": True}

    @app.post("/api/platforms/{pid}/login")
    def login(pid: str):
        a = adapter(pid)
        if not a.login_url:
            raise HTTPException(400, "Bu platformda login_url tanımlı değil")
        try:
            browser.start_login(pid, a.login_url)
        except BusyError as e:
            raise HTTPException(409, str(e))
        return {"ok": True}

    @app.post("/api/platforms/{pid}/login/finish")
    def login_finish(pid: str):
        adapter(pid)
        browser.finish_login(pid)
        return {"ok": True}

    @app.get("/api/platforms/{pid}/session")
    def session_state(pid: str):
        adapter(pid)
        st = browser.login_state.get(pid, {})
        return {"active": bool(st.get("active")), "message": st.get("message", ""),
                "has_session": browser.has_session(pid)}

    @app.get("/api/platforms/{pid}/courses")
    async def search(pid: str, q: str = ""):
        a = adapter(pid)

        def work():
            with browser.session(pid) as ctx:
                return a.search_courses(ctx, q.strip())

        try:
            res = await asyncio.to_thread(work)
        except (BusyError, ConfigError) as e:
            raise HTTPException(409, str(e))
        except Exception as e:
            raise HTTPException(502, f"Arama başarısız: {type(e).__name__}: {e}")
        return [c.__dict__ for c in res]

    # -------------------------------------------------------------- işler
    @app.get("/api/jobs")
    def jobs():
        return mgr.snapshot()

    @app.post("/api/jobs")
    def add_jobs(body: JobsIn):
        try:
            return [mgr.add_course(body.platform, c.url, c.title or None)["id"] for c in body.courses]
        except ValueError as e:
            raise HTTPException(400, str(e))

    def job_action(fn, jid):
        if jid not in mgr.jobs:
            raise HTTPException(404, "İş yok")
        fn(jid)
        return {"ok": True}

    @app.post("/api/jobs/{jid}/pause")
    def pause(jid: str):
        return job_action(mgr.pause, jid)

    @app.post("/api/jobs/{jid}/resume")
    def resume(jid: str):
        return job_action(mgr.resume, jid)

    @app.post("/api/jobs/{jid}/retry")
    def retry(jid: str):
        return job_action(mgr.retry_failed, jid)

    @app.delete("/api/jobs/{jid}")
    def remove(jid: str):
        return job_action(mgr.remove, jid)

    @app.get("/api/events")
    async def events(request: Request):
        async def gen():
            last, idle = -1, 0
            while not await request.is_disconnected():
                if mgr.version != last:
                    last, idle = mgr.version, 0
                    yield f"event: jobs\ndata: {json.dumps(mgr.snapshot(), ensure_ascii=False)}\n\n"
                elif idle >= 30:
                    idle = 0
                    yield ": ping\n\n"
                idle += 1
                await asyncio.sleep(0.5)
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    # -------------------------------------------------------------- ayarlar
    @app.get("/api/settings")
    def get_settings():
        return settings.get()

    @app.put("/api/settings")
    def put_settings(body: SettingsIn):
        try:
            res = settings.update(body.model_dump(exclude_none=True))
        except ValueError as e:
            raise HTTPException(400, str(e))
        mgr.ensure_workers()
        return res

    # -------------------------------------------------------------- kütüphane
    @app.get("/api/library")
    def lib():
        return library.list_courses(paths, db)

    def meta_or_404(slug):
        m = library.load_metadata(paths, slug)
        if not m:
            raise HTTPException(404, "Kurs yok")
        return m

    @app.get("/api/library/{slug}")
    def lib_course(slug: str):
        m = meta_or_404(slug)
        m["progress"] = db.progress(slug)
        return m

    def lesson_or_404(slug, lid):
        m = meta_or_404(slug)
        l = library.lesson_of(m, lid)
        if not l:
            raise HTTPException(404, "Ders yok")
        return m, l

    def safe(rel):
        p = paths.resolve_inside(rel) if rel else None
        if not p or not p.is_file():
            raise HTTPException(404, "Dosya yok")
        return p

    @app.api_route("/api/media/{slug}/{lid}/video", methods=["GET", "HEAD"])
    def video(request: Request, slug: str, lid: str):
        _, l = lesson_or_404(slug, lid)
        p = safe(l["video"])
        return range_response(request, p, mimetypes.guess_type(p.name)[0] or "video/mp4")

    @app.get("/api/media/{slug}/{lid}/subtitle/{n}")
    def subtitle(slug: str, lid: str, n: int):
        _, l = lesson_or_404(slug, lid)
        if not 0 <= n < len(l["subtitles"]):
            raise HTTPException(404, "Altyazı yok")
        p = safe(l["subtitles"][n]["path"])
        text = p.read_text("utf-8", errors="replace")
        if p.suffix.lower() == ".srt":
            text = srt_to_vtt(text)
        return Response(text, media_type="text/vtt; charset=utf-8")

    @app.api_route("/api/files/{slug}/{lid}/{n}", methods=["GET", "HEAD"])
    def resource_file(request: Request, slug: str, lid: str, n: int, inline: int = 0):
        m = meta_or_404(slug)
        items = m["course_resources"] if lid == "course" else (library.lesson_of(m, lid) or {}).get("resources", [])
        if not 0 <= n < len(items):
            raise HTTPException(404, "Dosya yok")
        p = safe(items[n]["path"])
        ext = p.suffix.lower()
        ctype = "text/plain; charset=utf-8" if ext in TEXT_EXTS else (mimetypes.guess_type(p.name)[0] or "application/octet-stream")
        disp = "inline" if inline and ext in INLINE_OK else "attachment"
        name = urllib.parse.quote(p.name)
        return range_response(request, p, ctype, {"Content-Disposition": f"{disp}; filename*=UTF-8''{name}",
                                                  "Content-Security-Policy": "sandbox"})

    @app.put("/api/progress/{slug}/{lid}")
    def set_progress(slug: str, lid: str, body: ProgressIn):
        lesson_or_404(slug, lid)
        done = body.completed or (body.duration > 0 and body.position / body.duration >= 0.95)
        db.set_progress(slug, lid, body.position, body.duration, done)
        return {"ok": True}

    @app.get("/api/notes/{slug}/{lid}")
    def get_notes(slug: str, lid: str):
        lesson_or_404(slug, lid)
        return db.notes(slug, lid)

    @app.post("/api/notes/{slug}/{lid}")
    def add_note(slug: str, lid: str, body: NoteIn):
        lesson_or_404(slug, lid)
        return {"id": db.add_note(slug, lid, body.t, body.text)}

    @app.delete("/api/notes/{slug}/{note_id}")
    def del_note(slug: str, note_id: int):
        db.delete_note(slug, note_id)
        return {"ok": True}

    return app
