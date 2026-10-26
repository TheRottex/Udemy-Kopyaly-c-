#!/usr/bin/env python3
"""
Kurs indirici: giriş -> keşif -> indirme (HLS) -> yeniden kodlama (HandBrake)

Kurulum (Linux):
  sudo apt install ffmpeg handbrake-cli python3-pip
  pip install yt-dlp playwright
  playwright install chromium

Kullanım:
  1) python3 kurs_indirici.py login  https://site.com/giris
  2) python3 kurs_indirici.py discover https://site.com/kurs/1 https://site.com/kurs/2 \
        --lesson-selector "a.lesson-link"
  3) python3 kurs_indirici.py download
  4) python3 kurs_indirici.py encode --crf 22
  (hepsi: python3 kurs_indirici.py all ...)

Not: DRM korumalı (Widevine/FairPlay vb.) akışlar desteklenmez.
Sadece kendi hesabınla erişebildiğin, kişisel offline izleme amaçlı içerikler için kullan
ve sitenin kullanım şartlarını kontrol et.
"""
import argparse
import json
import http.cookiejar
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# Kaynak olarak kabul edilen dosya uzantıları (varsayılan "a" seçicisi için)
FILE_EXTS = {".pdf", ".zip", ".rar", ".7z", ".tar", ".gz", ".doc", ".docx", ".ppt", ".pptx",
             ".xls", ".xlsx", ".csv", ".txt", ".md", ".json", ".sql", ".py", ".ipynb", ".srt",
             ".vtt", ".epub", ".mp3", ".psd", ".ai", ".fig", ".odt", ".odp", ".ods"}

ROOT = Path(__file__).resolve().parent
PROFILE = ROOT / "profil"          # tarayıcı oturumu burada saklanır
MANIFEST = ROOT / "manifest.json"
COOKIES = ROOT / "cookies.txt"
DL = ROOT / "indirilen"            # ham (yüksek kalite) videolar
FINAL = ROOT / "final"             # HandBrake çıktısı
KAYNAK = ROOT / "kaynaklar"        # yayımcının paylaştığı dosyalar (videolardan ayrı)
VIDEO_URL = ROOT / "video_url_listesi"   # videoların indirildiği adresler (ayrı saklanır)
COURSE_RES = ROOT / "kurs_kaynaklari.json"  # kurs sayfasındaki "Kaynaklar" bölümü


def slug(s: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\n\r\t]+', "-", s).strip(" .-")
    return s[:110] or "adsiz"


def save_cookies(ctx):
    lines = ["# Netscape HTTP Cookie File"]
    for c in ctx.cookies():
        dom = c["domain"]
        sub = "TRUE" if dom.startswith(".") else "FALSE"
        exp = int(c.get("expires", 0)) if c.get("expires", -1) > 0 else 0
        lines.append("\t".join([dom, sub, c["path"], "TRUE" if c["secure"] else "FALSE",
                                str(exp), c["name"], c["value"]]))
    COOKIES.write_text("\n".join(lines) + "\n")


def launch(p, headless):
    return p.chromium.launch_persistent_context(str(PROFILE), headless=headless)


# ---------------------------------------------------------------- login
def cmd_login(a):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = launch(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(a.url)
        input("\nTarayıcıda giriş yap, sonra buraya dönüp Enter'a bas... ")
        save_cookies(ctx)
        ctx.close()
    print("Oturum kaydedildi.")


# ---------------------------------------------------------------- discover
def collect_resources(pg, selector):
    """Sayfadaki dosya linklerini toplar. Varsayılan 'a' seçicisinde yalnızca dosya
    uzantılı / download özellikli linkler alınır; özel seçici verilirse hepsi alınır."""
    strict = selector == "a"
    out, seen = [], set()
    try:
        hrefs = pg.eval_on_selector_all(
            selector,
            "els => els.map(e => ({href: e.href, "
            "text: (e.innerText || e.getAttribute('download') || '').trim(), "
            "dl: e.hasAttribute('download')}))")
        for h in hrefs:
            u = h["href"]
            if not u.startswith("http") or u in seen or ".m3u8" in u:
                continue
            ext = Path(urllib.parse.urlparse(u).path).suffix.lower()
            if (not strict) or h["dl"] or ext in FILE_EXTS:
                seen.add(u)
                out.append({"url": u, "name": slug(h["text"])})
    except Exception:
        pass
    return out


def cmd_discover(a):
    from playwright.sync_api import sync_playwright
    manifest = []
    course_res = []
    with sync_playwright() as p:
        ctx = launch(p, headless=not a.show)
        page = ctx.new_page()
        for ci, course_url in enumerate(a.course_urls, 1):
            page.goto(course_url, wait_until="networkidle")
            course = slug(page.title())
            links = page.eval_on_selector_all(
                a.lesson_selector,
                "els => els.map(e => ({href: e.href, text: (e.innerText||'').trim()}))")
            seen, lessons = set(), []
            for l in links:
                if l["href"] and l["href"] not in seen:
                    seen.add(l["href"])
                    lessons.append(l)
            print(f"[{course}] {len(lessons)} ders bulundu")

            # Kursun kendi "Kaynaklar" bölümü (yayımcının genel paylaşımları)
            if a.course_resource_tab:
                try:
                    page.click(a.course_resource_tab, timeout=5000)
                    page.wait_for_timeout(1500)
                except Exception:
                    print("  ! Kaynaklar sekmesine tıklanamadı")
            cres = collect_resources(page, a.course_resource_selector)
            print(f"  kurs kaynakları: {len(cres)} dosya")
            course_res.append({"course_index": ci, "course": course,
                               "page": course_url, "resources": cres})

            for li, l in enumerate(lessons, 1):
                found = []
                lp = ctx.new_page()
                lp.on("response", lambda r: found.append(r.url) if ".m3u8" in r.url else None)
                try:
                    lp.goto(l["href"], wait_until="domcontentloaded")
                    if a.play_selector:
                        try:
                            lp.click(a.play_selector, timeout=5000)
                        except Exception:
                            pass
                    t0 = time.time()
                    while not found and time.time() - t0 < a.wait:
                        lp.wait_for_timeout(500)
                except Exception as e:
                    print(f"  ! {l['href']} açılamadı: {e}")
                m3u8 = next((u for u in found if "master" in u or "playlist" in u), found[0] if found else None)

                # Videonun altında paylaşılan dosyalar (ders ekleri)
                resources = collect_resources(lp, a.resource_selector)

                print(f"  {li:03d} {l['text'][:60]!r} -> video: {'OK' if m3u8 else 'yok'}, kaynak: {len(resources)}")
                manifest.append({"course_index": ci, "course": course, "lesson_index": li,
                                 "title": slug(l["text"] or f"ders-{li}"),
                                 "page": l["href"], "m3u8": m3u8, "resources": resources})
                lp.close()
        save_cookies(ctx)
        ctx.close()
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    COURSE_RES.write_text(json.dumps(course_res, ensure_ascii=False, indent=2))
    print(f"\n{MANIFEST} ve {COURSE_RES} yazıldı.")


# ---------------------------------------------------------------- download
def save_video_urls(items):
    """Her kurs için videoların indirildiği adresleri ayrı bir txt dosyasında saklar."""
    VIDEO_URL.mkdir(exist_ok=True)
    per_course = {}
    for it in items:
        key = f"{it['course_index']:02d} - {it['course']}"
        per_course.setdefault(key, []).append(
            f"{it['lesson_index']:03d} - {it['title']}\n"
            f"  video (m3u8): {it['m3u8'] or 'BULUNAMADI'}\n"
            f"  ders sayfası: {it['page']}\n")
    for key, lines in per_course.items():
        (VIDEO_URL / f"{key}.txt").write_text("\n".join(lines))


def fetch_resources(res, rdir, referer):
    """Kaynak dosyalarını rdir altına (videolardan ayrı) indirir, URL'leri de yanına yazar."""
    if not res:
        return
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "kaynaklar_url.txt").write_text("\n".join(r["url"] for r in res) + "\n")

    cj = http.cookiejar.MozillaCookieJar(str(COOKIES))
    cj.load(ignore_discard=True, ignore_expires=True)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = [("User-Agent", "Mozilla/5.0"), ("Referer", referer)]

    for r in res:
        try:
            with opener.open(r["url"], timeout=60) as resp:
                cd = resp.headers.get("Content-Disposition", "")
                m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
                name = urllib.parse.unquote(m.group(1)) if m else \
                    urllib.parse.unquote(Path(urllib.parse.urlparse(resp.geturl()).path).name)
                dst = rdir / slug(name or r["name"] or "dosya")
                if dst.exists():
                    continue
                with open(dst, "wb") as f:
                    shutil.copyfileobj(resp, f)
            print("   kaynak:", dst.name)
        except Exception as e:
            print("   kaynak HATA:", r["url"], e)


def cmd_download(a):
    items = json.loads(MANIFEST.read_text())
    save_video_urls(items)

    # 1) Kursun kendi "Kaynaklar" bölümü -> kaynaklar/<kurs>/00 - Kurs kaynakları/
    if COURSE_RES.exists():
        for c in json.loads(COURSE_RES.read_text()):
            kdir = KAYNAK / f"{c['course_index']:02d} - {c['course']}" / "00 - Kurs kaynakları"
            fetch_resources(c["resources"], kdir, c["page"])

    for it in items:
        # 2) Videonun altındaki ek dosyalar -> kaynaklar/<kurs>/<ders>/
        ddir = KAYNAK / f"{it['course_index']:02d} - {it['course']}" / f"{it['lesson_index']:03d} - {it['title']}"
        fetch_resources(it.get("resources") or [], ddir, it["page"])
        # 3) Video -> indirilen/<kurs>/
        if not it["m3u8"]:
            print(f"ATLANDI (m3u8 yok): {it['course']} / {it['title']}")
            continue
        folder = DL / f"{it['course_index']:02d} - {it['course']}"
        folder.mkdir(parents=True, exist_ok=True)
        base = folder / f"{it['lesson_index']:03d} - {it['title']}"
        if base.with_suffix(".mp4").exists():
            continue
        cmd = ["yt-dlp", "--cookies", str(COOKIES),
               "--add-header", f"Referer:{it['page']}",
               "-f", "bv*+ba/b", "-S", "res,br",            # en yüksek kalite
               "--merge-output-format", "mp4",
               "--concurrent-fragments", "8", "--retries", "10",
               "-o", str(base) + ".%(ext)s", it["m3u8"]]
        print(">>", base.name)
        if subprocess.run(cmd).returncode != 0:
            print("   HATA, yt-dlp başarısız:", it["page"])


# ---------------------------------------------------------------- encode
def cmd_encode(a):
    for src in sorted(DL.rglob("*.mp4")):
        dst = FINAL / src.relative_to(DL)
        if dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["HandBrakeCLI", "-i", str(src), "-o", str(dst),
               "-e", a.encoder, "-q", str(a.crf),
               "--encoder-preset", a.preset,
               "-E", "av_aac", "-B", "160", "--optimize"]
        print(">> encode:", src.name)
        if subprocess.run(cmd).returncode != 0:
            print("   HATA:", src)
            dst.unlink(missing_ok=True)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)

    s = sp.add_parser("login"); s.add_argument("url"); s.set_defaults(f=cmd_login)

    def add_discover(s):
        s.add_argument("course_urls", nargs="+")
        s.add_argument("--lesson-selector", default="a", help="Ders linklerini seçen CSS seçici")
        s.add_argument("--play-selector", default=None, help="Oynat butonu CSS seçicisi (gerekirse)")
        s.add_argument("--resource-selector", default="a",
                       help="Videonun altındaki ders eklerini seçen CSS seçici "
                            "(örn. '.attachments a'). Verilirse bu bölümdeki TÜM linkler alınır")
        s.add_argument("--course-resource-selector", default="a",
                       help="Kurs sayfasındaki 'Kaynaklar' bölümü linklerini seçen CSS seçici")
        s.add_argument("--course-resource-tab", default=None,
                       help="Kaynaklar sekmesini açmak için tıklanacak CSS seçici (gerekirse)")
        s.add_argument("--wait", type=int, default=20, help="Ders başına m3u8 bekleme (sn)")
        s.add_argument("--show", action="store_true", help="Tarayıcıyı görünür aç")
        s.set_defaults(f=cmd_discover)
    add_discover(sp.add_parser("discover"))

    sp.add_parser("download").set_defaults(f=cmd_download)

    s = sp.add_parser("encode")
    s.add_argument("--encoder", default="x265")
    s.add_argument("--crf", type=int, default=22)
    s.add_argument("--preset", default="medium")
    s.set_defaults(f=cmd_encode)

    args = ap.parse_args()
    args.f(args)


if __name__ == "__main__":
    sys.exit(main())
