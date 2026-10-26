"""Ortak test düzeneği: sahte tarayıcı, sahte adaptör, sahte yt-dlp/HandBrake."""
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kurs_app.jobs import JobManager
from kurs_app.paths import Paths
from kurs_app.platform_base import CourseInfo, Lesson, LessonInfo, PlatformAdapter, Section
from kurs_app.resources import ResourceLink
from kurs_app.server import create_app
from kurs_app.settings import SettingsStore
from kurs_app.sniffer import VideoSource

BLOB = bytes(range(256)) * 4   # 1024 bayt: Range testleri için


class FakeBrowser:
    login_state: dict = {}

    @contextmanager
    def session(self, pid, headless=True):
        yield object()

    def has_session(self, pid):
        return True

    def start_login(self, pid, url):
        self.login_state[pid] = {"active": True, "message": "açık"}

    def finish_login(self, pid):
        self.login_state[pid] = {"active": False, "message": "kaydedildi"}


class FakeAdapter(PlatformAdapter):
    id, name, login_url = "fake", "Sahte", "https://x.test/login"

    def search_courses(self, ctx, query):
        return []

    def list_course(self, ctx, course_url):
        return CourseInfo(
            "Test Kursu",
            [Section("Bölüm 1", [Lesson("Giriş", "https://x.test/l1"), Lesson("DRM ders", "https://x.test/l2")])],
            [ResourceLink("Kurs.pdf", "https://x.test/k.pdf")])

    def inspect_lesson(self, ctx, url):
        if url.endswith("l2"):
            return LessonInfo(VideoSource("https://x.test/v2.m3u8", "hls", True, "Widevine"), [])
        return LessonInfo(VideoSource("https://x.test/v1.m3u8", "hls"), [ResourceLink("ek.zip", "https://x.test/ek.zip")])


def fake_runner(cmd, on_line, stop):
    out = cmd[cmd.index("-o") + 1]
    if "yt_dlp" in " ".join(cmd):
        on_line("[download]  50.0% of 10MiB")
        out = out.replace("%(ext)s", "mp4")
    else:
        on_line("Encoding: task 1 of 1, 50.00 %")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(BLOB)
    return 0


def fake_fetcher(url, folder, referer, cookie, name="dosya", timeout=60):
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    p.write_bytes(b"icerik")
    return {"name": name, "path": p, "size": 6, "url": url}


@pytest.fixture
def paths(tmp_path):
    p = Paths(tmp_path)
    p.ensure()
    return p


@pytest.fixture
def env(paths, tmp_path):
    fake_exe = tmp_path / "HandBrakeCLI"
    fake_exe.write_text("#!/bin/sh\n")
    settings = SettingsStore(paths.settings)
    settings.update({"handbrake_path": str(fake_exe)})
    mgr = JobManager(paths, settings, FakeBrowser(), {"fake": FakeAdapter()},
                     runner=fake_runner, probe=lambda p: 60.0, fetcher=fake_fetcher)
    app = create_app(paths, manager=mgr, browser=FakeBrowser(), start_workers=False)
    client = TestClient(app, base_url="http://127.0.0.1", headers={"X-Requested-With": "kurs-indirici"})
    return paths, mgr, client


def run_job(mgr):
    """Kuyruğu eşzamanlı işler (iş parçacığı olmadan)."""
    job = mgr.add_course("fake", "https://x.test/course", "Test Kursu")
    mgr._list_job(job)
    while not mgr.tasks.empty():
        jid, idx = mgr.tasks.get_nowait()
        mgr._process(jid, idx)
    return job
