import re


def slug(s: str, maxlen: int = 110) -> str:
    """Dosya sistemi için güvenli ad üretir (yol ayracı içermez)."""
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", s or "")
    s = re.sub(r"\s+", " ", s).strip(" .-")
    return s[:maxlen].rstrip(" .-") or "adsiz"


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


_URL_Q = re.compile(r"(https?://[^\s?#'\"]+)[?#][^\s'\"]*")


def redact(s: str) -> str:
    """Loglara token/imza taşıyabilecek URL sorgu kısımlarını yazmaz."""
    return _URL_Q.sub(r"\1?…", s)


def srt_to_vtt(text: str) -> str:
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", text)
    return "WEBVTT\n\n" + text
