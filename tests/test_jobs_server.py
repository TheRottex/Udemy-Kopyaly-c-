from urllib.parse import quote

from conftest import BLOB, run_job

SLUG = "Test Kursu"


def test_job_pipeline_layout_and_drm_skip(env):
    paths, mgr, _ = env
    job = run_job(mgr)
    l1, l2 = job["lessons"]
    assert l1["status"] == "done" and l2["status"] == "drm"
    assert job["status"] == "done"
    # ayrı depolama düzeni
    assert (paths.raw / SLUG / "001 - Giriş.mp4").exists()
    assert (paths.final / SLUG / "001 - Giriş.mp4").exists()
    assert not (paths.raw / SLUG / "002 - DRM ders.mp4").exists()          # DRM atlandı
    assert (paths.resources / SLUG / "00 - Kurs kaynakları" / "Kurs.pdf").exists()
    assert (paths.resources / SLUG / "001 - Giriş" / "ek.zip").exists()
    assert "https://x.test/ek.zip" in (paths.resources / SLUG / "001 - Giriş" / "kaynaklar_url.txt").read_text()
    urls = (paths.video_urls / f"{SLUG}.txt").read_text()
    assert "https://x.test/v1.m3u8" in urls and "https://x.test/l1" in urls
    assert (paths.final / SLUG / "metadata.json").exists()


def test_encode_disabled_serves_raw(env):
    paths, mgr, _ = env
    mgr.settings.update({"encode_enabled": False})
    run_job(mgr)
    assert (paths.raw / SLUG / "001 - Giriş.mp4").exists() and not (paths.final / SLUG / "001 - Giriş.mp4").exists()


def test_library_api_and_range(env):
    paths, mgr, c = env
    run_job(mgr)
    lib = c.get("/api/library").json()
    assert lib[0]["slug"] == SLUG and lib[0]["playable"] == 1 and lib[0]["first_lesson"] == "001"
    meta = c.get(f"/api/library/{quote(SLUG)}").json()
    assert meta["sections"][0]["lessons"][1]["status"] == "drm"
    assert meta["course_resources"][0]["name"] == "Kurs.pdf"
    v = f"/api/media/{quote(SLUG)}/001/video"
    r = c.get(v, headers={"Range": "bytes=10-19"})
    assert r.status_code == 206 and r.content == BLOB[10:20] and r.headers["content-range"] == "bytes 10-19/1024"
    assert c.get(v).content == BLOB
    assert c.get(v, headers={"Range": "bytes=5000-"}).status_code == 416
    assert c.get(f"/api/media/{quote(SLUG)}/002/video").status_code == 404   # DRM'li dersin videosu yok


def test_resource_file_download_headers(env):
    _, mgr, c = env
    run_job(mgr)
    r = c.get(f"/api/files/{quote(SLUG)}/001/0")
    assert r.status_code == 200 and r.content == b"icerik"
    assert r.headers["content-disposition"].startswith("attachment") and r.headers["content-security-policy"] == "sandbox"
    assert c.get(f"/api/files/{quote(SLUG)}/course/0").status_code == 200
    assert c.get(f"/api/files/{quote(SLUG)}/001/9").status_code == 404


def test_progress_and_notes(env):
    _, mgr, c = env
    run_job(mgr)
    s = quote(SLUG)
    assert c.put(f"/api/progress/{s}/001", json={"position": 58, "duration": 60}).status_code == 200
    assert c.get(f"/api/library/{s}").json()["progress"]["001"]["completed"] is True   # >= %95
    nid = c.post(f"/api/notes/{s}/001", json={"t": 12.5, "text": "önemli"}).json()["id"]
    assert c.get(f"/api/notes/{s}/001").json()[0]["text"] == "önemli"
    c.delete(f"/api/notes/{s}/{nid}")
    assert c.get(f"/api/notes/{s}/001").json() == []
    assert c.post(f"/api/notes/{s}/001", json={"t": 1, "text": ""}).status_code == 422


def test_security_csrf_host_traversal(env):
    paths, mgr, c = env
    run_job(mgr)
    from fastapi.testclient import TestClient
    bare = TestClient(c.app, base_url="http://127.0.0.1")                      # CSRF başlığı yok
    assert bare.post("/api/jobs", json={"platform": "fake", "courses": [{"url": "https://x.test/c"}]}).status_code == 403
    assert bare.put("/api/settings", json={"crf": 18}).status_code == 403
    evil = TestClient(c.app, base_url="http://evil.example", headers={"X-Requested-With": "kurs-indirici"})
    assert evil.get("/api/library").status_code == 400                         # DNS rebinding
    for bad in ("..", "%2e%2e", "..%2f..%2fetc", "a/../b"):
        assert c.get(f"/api/library/{bad}").status_code in (404, 405, 307, 308)
    assert paths.resolve_inside("../../etc/passwd") is None
    assert paths.resolve_inside("data/app.db") is None                         # depolama dışı


def test_settings_endpoint_and_index(env):
    _, _, c = env
    assert c.put("/api/settings", json={"crf": 18}).json()["crf"] == 18
    assert c.put("/api/settings", json={"crf": 70}).status_code == 400
    r = c.get("/")
    assert r.status_code == 200 and "Kurs" in r.text and r.headers["cache-control"] == "no-store"


def test_pause_resume_retry_remove(env):
    _, mgr, c = env
    job = mgr.add_course("fake", "https://x.test/course", "Test Kursu")
    jid = job["id"]
    assert c.post(f"/api/jobs/{jid}/pause").status_code == 200
    assert mgr.jobs[jid]["status"] == "paused"
    assert c.post(f"/api/jobs/{jid}/nope").status_code in (404, 405)
    assert c.delete(f"/api/jobs/{jid}").status_code == 200 and jid not in mgr.jobs
    assert c.post("/api/jobs/yok/pause").status_code == 404
    assert c.post("/api/jobs", json={"platform": "yok", "courses": [{"url": "https://a"}]}).status_code == 400
    assert c.post("/api/jobs", json={"platform": "fake", "courses": [{"url": "file:///etc/passwd"}]}).status_code == 400
