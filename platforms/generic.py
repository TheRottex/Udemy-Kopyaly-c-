"""Genel adaptör: tüm site mantığı CSS seçicilerle (JSON profil ya da arayüz) tanımlanır."""
import re
import urllib.parse

from kurs_app.platform_base import (ConfigError, Course, CourseInfo, Lesson, PlatformAdapter, Section)
from kurs_app.resources import find_resources
from kurs_app.sniffer import MediaSniffer, VideoSource

CONFIG_KEYS = {
    "name": "Görünen ad",
    "login_url": "Giriş sayfası URL'si",
    "course_list_url": "Hesabımdaki kurslar sayfası URL'si",
    "search_url_template": "Arama URL'si, {q} yer tutucusuyla (opsiyonel)",
    "course_card_selector": "Kurs kartı/linki seçicisi",
    "course_title_selector": "Kart içindeki başlık seçicisi (opsiyonel)",
    "course_title_page_selector": "Kurs sayfasındaki başlık seçicisi (opsiyonel; yoksa <title>)",
    "section_selector": "Bölüm kapsayıcısı seçicisi (opsiyonel)",
    "section_title_selector": "Bölüm başlığı seçicisi (bölüm içinde)",
    "lesson_selector": "Ders linki seçicisi",
    "play_selector": "Oynat butonu seçicisi (opsiyonel)",
    "video_wait": "Video bekleme süresi (sn)",
    "resource_tab_selector": "Ders 'Kaynaklar' sekmesi seçicisi (elle; opsiyonel)",
    "resource_selector": "Ders kaynak linkleri seçicisi (elle; opsiyonel)",
    "course_resource_tab_selector": "Kurs 'Kaynaklar' sekmesi seçicisi (elle; opsiyonel)",
    "course_resource_selector": "Kurs kaynak linkleri seçicisi (elle; opsiyonel)",
}

LIST_JS = """(a) => {
  const linkOf = e => e.tagName === 'A' ? e : (e.querySelector('a[href]') || e.closest('a[href]'));
  const first = e => ((e.innerText || '').split('\\n').map(s => s.trim()).find(Boolean)) || '';
  const lessons = root => [...root.querySelectorAll(a.lesson)].map(e => {
    const l = linkOf(e); return l ? {title: first(e) || first(l), url: l.href} : null; }).filter(Boolean);
  if (a.section) {
    return [...document.querySelectorAll(a.section)].map((s, i) => {
      const t = a.sectionTitle ? s.querySelector(a.sectionTitle) : null;
      return {title: (t ? t.innerText.trim() : first(s)) || ('Bölüm ' + (i + 1)), lessons: lessons(s)};
    });
  }
  return [{title: 'Dersler', lessons: lessons(document)}];
}"""

CARDS_JS = """(a) => [...document.querySelectorAll(a.card)].map(e => {
  const l = e.tagName === 'A' ? e : (e.querySelector('a[href]') || e.closest('a[href]'));
  if (!l) return null;
  const t = a.title ? e.querySelector(a.title) : null;
  const img = e.querySelector('img');
  const first = ((e.innerText || '').split('\\n').map(s => s.trim()).find(Boolean)) || '';
  return {title: (t ? t.innerText.trim() : first) || l.href, url: l.href, thumb: img ? img.src : ''};
}).filter(Boolean)"""


def _settle(page):
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass


class GenericAdapter(PlatformAdapter):
    configurable = True

    def __init__(self, profile_id: str = "generic", config: dict | None = None):
        self.id = profile_id
        self.cfg = {k: v for k, v in (config or {}).items() if k in CONFIG_KEYS}
        self.name = self.cfg.get("name") or ("Genel (CSS seçicili)" if profile_id == "generic" else profile_id)
        self.login_url = self.cfg.get("login_url", "")

    def _need(self, key):
        v = self.cfg.get(key)
        if not v:
            raise ConfigError(f"'{key}' ayarı gerekli ({CONFIG_KEYS[key]})")
        return v

    def search_courses(self, ctx, query: str) -> list:
        card = self._need("course_card_selector")
        tpl = self.cfg.get("search_url_template")
        url = tpl.replace("{q}", urllib.parse.quote(query)) if tpl and "{q}" in tpl else self._need("course_list_url")
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded")
            _settle(page)
            raw = page.evaluate(CARDS_JS, {"card": card, "title": self.cfg.get("course_title_selector")})
        finally:
            page.close()
        out, seen = [], set()
        server_side = bool(tpl and "{q}" in tpl)
        for c in raw:
            if c["url"] in seen:
                continue
            if query and not server_side and query.casefold() not in c["title"].casefold():
                continue
            seen.add(c["url"])
            out.append(Course(c["title"], c["url"], c["thumb"]))
        return out

    def list_course(self, ctx, course_url: str) -> CourseInfo:
        lesson_sel = self._need("lesson_selector")
        page = ctx.new_page()
        try:
            page.goto(course_url, wait_until="domcontentloaded")
            _settle(page)
            title = ""
            ts = self.cfg.get("course_title_page_selector")
            if ts:
                try:
                    title = page.inner_text(ts, timeout=3000).strip()
                except Exception:
                    pass
            title = title or page.title() or "kurs"
            raw = page.evaluate(LIST_JS, {"lesson": lesson_sel, "section": self.cfg.get("section_selector"),
                                          "sectionTitle": self.cfg.get("section_title_selector")})
            seen, sections = set(), []
            for s in raw:
                lessons = []
                for l in s["lessons"]:
                    if l["url"] not in seen:
                        seen.add(l["url"])
                        lessons.append(Lesson(l["title"], l["url"]))
                if lessons:
                    sections.append(Section(s["title"], lessons))
            cres = find_resources(page, self.cfg.get("course_resource_tab_selector"),
                                  self.cfg.get("course_resource_selector"))
        finally:
            page.close()
        return CourseInfo(title, sections, cres)

    def find_video(self, page, sniffer: MediaSniffer) -> VideoSource:
        wait = float(self.cfg.get("video_wait") or 20)
        ps = self.cfg.get("play_selector")
        if ps:
            try:
                page.click(ps, timeout=5000)
            except Exception:
                pass
        else:
            try:  # sessiz otomatik oynatma tetikleme (en iyi çaba)
                page.evaluate("document.querySelectorAll('video').forEach(v => { v.muted = true; v.play().catch(()=>{}); })")
            except Exception:
                pass
        waited = 0.0
        while waited < wait and not sniffer.found:
            page.wait_for_timeout(500)
            waited += 0.5
        page.wait_for_timeout(500)
        src = sniffer.result()
        if not src.url and not src.drm:
            try:
                cur = page.evaluate("(document.querySelector('video')||{}).currentSrc || ''")
                if re.match(r"https?://", cur or ""):
                    src = VideoSource(cur, "file")
            except Exception:
                pass
        try:
            tracks = page.evaluate("[...document.querySelectorAll('video track[src]')].map(t => ({lang: t.srclang || t.label || 'und', url: t.src}))")
            src.subtitles = [t for t in tracks if t["url"].startswith("http")]
        except Exception:
            pass
        return src

    def find_resources(self, page) -> list:
        return find_resources(page, self.cfg.get("resource_tab_selector"), self.cfg.get("resource_selector"))
