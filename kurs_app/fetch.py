"""Kaynak dosyalarını (PDF, zip vb.) oturum çerezleriyle indirir."""
import http.cookiejar
import re
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

from .util import slug


def _filename(resp, fallback: str) -> str:
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r"filename\*=(?:UTF-8|utf-8)''([^;]+)", cd) or re.search(r'filename="?([^";]+)"?', cd)
    if m:
        return urllib.parse.unquote(m.group(1))
    name = urllib.parse.unquote(Path(urllib.parse.urlparse(resp.geturl()).path).name)
    return name or fallback


def fetch_resource(url: str, dest_dir: Path, referer: str, cookie_file: Path | None,
                   fallback_name: str = "dosya", timeout: int = 60) -> dict:
    """Dosyayı indirir; {"name","path","size","url"} döner. Aynı ada sahip dosya varsa atlar."""
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        raise ValueError("Yalnızca http/https desteklenir")
    handlers = []
    if cookie_file and Path(cookie_file).exists():
        cj = http.cookiejar.MozillaCookieJar(str(cookie_file))
        try:
            cj.load(ignore_discard=True, ignore_expires=True)
            for c in cj:   # cookies.txt'de oturum çerezi expires=0; urllib bunu "süresi dolmuş" sayıp göndermez
                if c.expires == 0:
                    c.expires, c.discard = None, True
            handlers.append(urllib.request.HTTPCookieProcessor(cj))
        except Exception:
            pass
    opener = urllib.request.build_opener(*handlers)
    opener.addheaders = [("User-Agent", "Mozilla/5.0"), ("Referer", referer)]
    dest_dir.mkdir(parents=True, exist_ok=True)
    with opener.open(url, timeout=timeout) as resp:
        name = slug(_filename(resp, fallback_name))
        dst = dest_dir / name
        if not dst.exists():
            tmp = dst.with_name(dst.name + ".part")
            with open(tmp, "wb") as f:
                shutil.copyfileobj(resp, f)
            tmp.replace(dst)
    return {"name": name, "path": dst, "size": dst.stat().st_size, "url": url}
