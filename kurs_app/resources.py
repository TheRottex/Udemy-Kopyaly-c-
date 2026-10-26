"""'Kaynaklar' sekme/bölümlerini sezgisel bulma ve dosya linklerini toplama."""
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass
from pathlib import PurePosixPath

FILE_EXTS = {".pdf", ".zip", ".rar", ".7z", ".tar", ".gz", ".doc", ".docx", ".ppt", ".pptx",
             ".xls", ".xlsx", ".csv", ".txt", ".md", ".json", ".sql", ".py", ".ipynb", ".srt",
             ".vtt", ".epub", ".mp3", ".psd", ".ai", ".fig", ".odt", ".odp", ".ods", ".png",
             ".jpg", ".jpeg", ".svg", ".xd", ".sketch", ".exe", ".dmg", ".apk"}
URL_HINT_RE = re.compile(r"/(download|downloads|attachment|attachments|files?)/", re.I)

STEMS = ("kaynak", "resource", "material", "materyal", "attachment", "dosya", "download", "indirilenler",
         "indirmeler", "ekler", "ekstra dosya")
EXACT = {"ek", "ekler", "files", "file", "extras"}


@dataclass
class ResourceLink:
    name: str
    url: str


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").replace("İ", "i").replace("I", "ı"))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.casefold().replace("ı", "i")


def label_matches(text: str) -> bool:
    """Metin/aria-label 'Kaynaklar, Resources, Materials...' gibi bir sekmeyi ifade ediyor mu?"""
    t = _norm(text).strip()
    if not t or len(t) > 40:
        return False
    tokens = re.findall(r"[a-z0-9]+", t)
    return any(tok in EXACT or any(tok.startswith(_norm(s).split()[0]) for s in STEMS) for tok in tokens)


def is_file_link(url: str, has_download_attr: bool = False) -> bool:
    if not url.startswith(("http://", "https://")):
        return False
    p = urllib.parse.urlparse(url)
    ext = PurePosixPath(urllib.parse.unquote(p.path)).suffix.lower()
    if ext in (".m3u8", ".mpd"):
        return False
    return has_download_attr or ext in FILE_EXTS or bool(URL_HINT_RE.search(p.path))


CANDIDATES_JS = """() => {
  const sel = '[role=tab],button,summary,a,li,[role=button],[aria-controls],h2,h3,div[tabindex]';
  const out = []; let i = 0;
  for (const e of document.querySelectorAll(sel)) {
    const r = e.getBoundingClientRect();
    if (!r.width && !r.height) continue;
    const text = (e.innerText || '').trim().slice(0, 80);
    const aria = e.getAttribute('aria-label') || e.getAttribute('title') || '';
    if (!text && !aria) continue;
    e.setAttribute('data-ki-idx', String(i));
    out.push({idx: i, tag: e.tagName.toLowerCase(), text, aria,
              href: e.tagName === 'A' ? (e.getAttribute('href') || '') : '',
              controls: e.getAttribute('aria-controls') || ''});
    i++;
  }
  return out;
}"""

LINKS_JS = """(args) => {
  const root = args.sel ? document.querySelectorAll(args.sel) : [document];
  const out = [];
  for (const r of root) for (const a of r.querySelectorAll(r === document ? 'a[href]' : 'a[href]')) {
    out.push({url: a.href, text: (a.innerText || a.getAttribute('download') || a.getAttribute('aria-label') || '').trim(),
              dl: a.hasAttribute('download')});
  }
  if (args.sel) for (const r of root) if (r.matches && r.matches('a[href]'))
    out.push({url: r.href, text: (r.innerText || '').trim(), dl: r.hasAttribute('download')});
  return out;
}"""


def _name(text: str, url: str) -> str:
    text = " ".join((text or "").split())
    if text:
        return text[:120]
    return urllib.parse.unquote(PurePosixPath(urllib.parse.urlparse(url).path).name) or "dosya"


def collect_links(page, selector: str | None, strict: bool) -> list:
    try:
        raw = page.evaluate(LINKS_JS, {"sel": selector})
    except Exception:
        return []
    out, seen = [], set()
    for h in raw:
        u = h["url"]
        if u in seen or not u.startswith(("http://", "https://")) or ".m3u8" in u.split("?")[0]:
            continue
        if strict and not is_file_link(u, h["dl"]):
            continue
        seen.add(u)
        out.append(ResourceLink(_name(h["text"], u), u))
    return out


def find_resources(page, tab_selector: str | None = None, resource_selector: str | None = None,
                   settle_ms: int = 800) -> list:
    """Elle seçici verilmişse onu kullanır; yoksa sezgisel olarak 'Kaynaklar' sekme/bölümlerini açar."""
    found: dict = {}

    def add(items):
        for r in items:
            found.setdefault(r.url, r)

    if tab_selector:
        try:
            page.click(tab_selector, timeout=4000)
            page.wait_for_timeout(settle_ms)
        except Exception:
            pass
    if resource_selector:
        add(collect_links(page, resource_selector, strict=False))
        return list(found.values())

    try:
        cands = page.evaluate(CANDIDATES_JS)
    except Exception:
        cands = []
    for c in cands:
        if not (label_matches(c["text"]) or label_matches(c["aria"])):
            continue
        href = c["href"]
        if c["tag"] == "a" and href and not href.startswith(("#", "javascript:")):
            continue  # başka sayfaya götürür; sekme değil
        try:
            page.click(f'[data-ki-idx="{c["idx"]}"]', timeout=2000)
            page.wait_for_timeout(settle_ms)
        except Exception:
            continue
        if c["controls"] and re.fullmatch(r"[A-Za-z0-9_:.-]+", c["controls"]):
            add(collect_links(page, f'[id="{c["controls"]}"]', strict=False))
    add(collect_links(page, None, strict=True))
    return list(found.values())
