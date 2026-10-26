"""metadata.json üretimi/okuma ve kütüphane taraması."""
import json
import shutil
import subprocess
import time
from pathlib import Path

from .util import human_size, slug

VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".mov")


def probe_duration(path: Path):
    """ffprobe varsa süreyi (sn) döner; yoksa None."""
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        return round(float(out), 1)
    except Exception:
        return None


def lesson_base(index: int, title: str) -> str:
    return f"{index:03d} - {slug(title)}"


def find_video(folder: Path, base: str):
    for ext in VIDEO_EXTS:
        p = folder / (base + ext)
        if p.exists():
            return p
    return None


def find_subtitles(video: Path) -> list:
    out = []
    if not video:
        return out
    for p in sorted(video.parent.glob(glob_escape(video.stem) + ".*")):
        if p.suffix.lower() in (".vtt", ".srt"):
            lang = p.name[len(video.stem) + 1:-len(p.suffix)] or "und"
            out.append({"lang": lang, "path": p})
    return out


def glob_escape(s: str) -> str:
    return "".join(f"[{c}]" if c in "*?[" else c for c in s)


def _res(paths, items):
    out = []
    for r in items:
        p = paths.root / r["path"] if r.get("path") else None   # göreli yol (job'larda kökten)
        out.append({"name": r["name"], "url": r["url"],
                    "path": paths.rel(p) if p and p.exists() else None,
                    "size": p.stat().st_size if p and p.exists() else None,
                    "size_h": human_size(p.stat().st_size) if p and p.exists() else None})
    return out


def build_metadata(paths, job: dict, probe=probe_duration) -> dict:
    cslug = job["slug"]
    sections, cur = [], None
    for l in job["lessons"]:
        if cur is None or cur["title"] != l["section"]:
            cur = {"title": l["section"], "lessons": []}
            sections.append(cur)
        base = lesson_base(l["index"], l["title"])
        raw = find_video(paths.raw / cslug, base)
        fin = find_video(paths.final / cslug, base)
        main = fin or raw
        duration = l.get("duration")
        if duration is None and main:
            duration = probe(main)
            l["duration"] = duration
        subs = find_subtitles(fin) or find_subtitles(raw)
        cur["lessons"].append({
            "id": f"{l['index']:03d}", "index": l["index"], "title": l["title"],
            "status": l["status"], "duration": duration,
            "video": paths.rel(main) if main else None,
            "raw_video": paths.rel(raw) if raw else None,
            "final_video": paths.rel(fin) if fin else None,
            "subtitles": [{"lang": s["lang"], "path": paths.rel(s["path"])} for s in subs],
            "page_url": l["url"], "video_source_url": l.get("video_url"),
            "error": l.get("error") or None,
            "resources": _res(paths, l.get("resources", [])),
        })
    return {"version": 1, "title": job["title"], "slug": cslug, "platform": job["platform"],
            "source_url": job["course_url"], "updated": time.time(),
            "sections": sections, "course_resources": _res(paths, job.get("course_resources", []))}


def metadata_path(paths, cslug: str) -> Path:
    return paths.final / cslug / "metadata.json"


def write_metadata(paths, job: dict, probe=probe_duration) -> dict:
    meta = build_metadata(paths, job, probe)
    p = metadata_path(paths, job["slug"])
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(p)
    return meta


def write_resource_url_files(paths, job: dict):
    """kaynaklar/<kurs>/<ders>/kaynaklar_url.txt ve kurs kaynakları için aynısı."""
    def dump(folder: Path, items):
        items = [r for r in items if r.get("url")]
        if items:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "kaynaklar_url.txt").write_text("\n".join(r["url"] for r in items) + "\n", "utf-8")
    dump(paths.resources / job["slug"] / "00 - Kurs kaynakları", job.get("course_resources", []))
    for l in job["lessons"]:
        dump(paths.resources / job["slug"] / lesson_base(l["index"], l["title"]), l.get("resources", []))


def write_video_urls(paths, job: dict):
    paths.video_urls.mkdir(parents=True, exist_ok=True)
    blocks = [f"{lesson_base(l['index'], l['title'])}\n  video: {l.get('video_url') or 'BULUNAMADI'}\n"
              f"  ders sayfası: {l['url']}\n" for l in job["lessons"]]
    (paths.video_urls / f"{job['slug']}.txt").write_text("\n".join(blocks), "utf-8")


def load_metadata(paths, cslug: str):
    if Path(cslug).name != cslug or cslug in ("", ".", ".."):
        return None
    p = metadata_path(paths, cslug)
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def list_courses(paths, db) -> list:
    out = []
    if not paths.final.exists():
        return out
    for d in sorted(paths.final.iterdir()):
        meta = load_metadata(paths, d.name) if d.is_dir() else None
        if not meta:
            continue
        lessons = [l for s in meta["sections"] for l in s["lessons"]]
        prog = db.progress(meta["slug"])
        playable = [l for l in lessons if l["video"]]
        out.append({"slug": meta["slug"], "title": meta["title"], "platform": meta["platform"],
                    "lessons": len(lessons), "playable": len(playable),
                    "watched": sum(1 for l in lessons if prog.get(l["id"], {}).get("completed")),
                    "duration": sum(l["duration"] or 0 for l in lessons),
                    "first_lesson": playable[0]["id"] if playable else None})
    return out


def lesson_of(meta: dict, lesson_id: str):
    for s in meta["sections"]:
        for l in s["lessons"]:
            if l["id"] == lesson_id:
                return l
    return None
