"""Playwright oturumu. Şifre ASLA işlenmez: kullanıcı görünür tarayıcıda kendisi giriş yapar,
oturum yalnızca profil/<platform>/ klasöründe (tarayıcı profili + cookies.txt) kalır."""
import os
import threading
import time
from contextlib import contextmanager


class BusyError(Exception):
    pass


def write_cookies_txt(cookies: list, path) -> None:
    """Netscape biçimi (yt-dlp + urllib için). İçerik asla loglanmaz."""
    lines = ["# Netscape HTTP Cookie File"]
    for c in cookies:
        dom = c["domain"]
        exp = int(c["expires"]) if c.get("expires", -1) and c["expires"] > 0 else 0
        prefix = "#HttpOnly_" if c.get("httpOnly") else ""
        lines.append("\t".join([prefix + dom, "TRUE" if dom.startswith(".") else "FALSE", c["path"],
                                "TRUE" if c.get("secure") else "FALSE", str(exp), c["name"], c["value"]]))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


class BrowserManager:
    def __init__(self, paths):
        self.paths = paths
        self.lock = threading.RLock()
        self.login_state: dict = {}
        self._finish: dict = {}

    @contextmanager
    def session(self, platform_id: str, headless: bool = True):
        if self.login_state.get(platform_id, {}).get("active"):
            raise BusyError("Giriş penceresi açık; önce tarayıcıyı kapatın veya 'Giriş tamamlandı'ya basın.")
        from playwright.sync_api import sync_playwright
        with self.lock:
            with sync_playwright() as p:
                d = self.paths.browser_dir(platform_id)
                d.mkdir(parents=True, exist_ok=True)
                ctx = p.chromium.launch_persistent_context(str(d), headless=headless)
                try:
                    yield ctx
                finally:
                    try:
                        write_cookies_txt(ctx.cookies(), self.paths.cookie_file(platform_id))
                    except Exception:
                        pass
                    ctx.close()

    def start_login(self, platform_id: str, login_url: str):
        st = self.login_state.setdefault(platform_id, {})
        if st.get("active"):
            raise BusyError("Giriş zaten açık")
        st.update(active=True, message="Tarayıcı açılıyor…")
        self._finish[platform_id] = threading.Event()
        threading.Thread(target=self._login, args=(platform_id, login_url), daemon=True).start()

    def finish_login(self, platform_id: str):
        ev = self._finish.get(platform_id)
        if ev:
            ev.set()

    def _login(self, platform_id, login_url):
        st = self.login_state[platform_id]
        try:
            from playwright.sync_api import sync_playwright
            with self.lock, sync_playwright() as p:
                d = self.paths.browser_dir(platform_id)
                d.mkdir(parents=True, exist_ok=True)
                ctx = p.chromium.launch_persistent_context(str(d), headless=False)
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                if login_url:
                    page.goto(login_url)
                st["message"] = "Tarayıcıda giriş yapın, sonra 'Giriş tamamlandı'ya basın."
                snapshot, last = [], 0.0
                ev = self._finish[platform_id]
                while not ev.is_set():
                    try:
                        if not ctx.pages:
                            break
                        if time.time() - last > 2:
                            snapshot, last = ctx.cookies(), time.time()
                    except Exception:
                        break
                    time.sleep(0.4)
                try:
                    snapshot = ctx.cookies()
                except Exception:
                    pass
                if snapshot:
                    write_cookies_txt(snapshot, self.paths.cookie_file(platform_id))
                try:
                    ctx.close()
                except Exception:
                    pass
            st["message"] = "Oturum kaydedildi."
        except Exception as e:
            st["message"] = f"Giriş penceresi hatası: {type(e).__name__}"
        finally:
            st["active"] = False

    def has_session(self, platform_id: str) -> bool:
        f = self.paths.cookie_file(platform_id)
        return f.exists() and f.stat().st_size > 40
