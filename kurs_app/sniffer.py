"""Sayfa ağ trafiğinden video kaynağı (m3u8/mpd/mp4) yakalar ve DRM sinyallerini toplar."""
from dataclasses import dataclass, field

from .drm import DRM_URL_RE, analyze_manifest, analyze_signals

EME_JS = """(() => { if (window.__kiDrm) return; window.__kiDrm = [];
 const o = navigator.requestMediaKeySystemAccess; if (!o) return;
 navigator.requestMediaKeySystemAccess = function(ks) {
   try { window.__kiDrm.push(String(ks)); } catch (e) {}
   return o.apply(this, arguments); }; })();"""

MANIFEST_TYPES = ("mpegurl", "dash+xml")


@dataclass
class VideoSource:
    url: str | None = None
    kind: str | None = None          # hls | dash | file
    drm: bool = False
    reason: str = ""
    subtitles: list = field(default_factory=list)   # [{"lang":..,"url":..}]


def choose_source(manifests: list, media: list, signals: list, eme: list = ()) -> VideoSource:
    """manifests: [{"url","text"}]; media: doğrudan video URL'leri."""
    chosen = None
    hls = [m for m in manifests if ".m3u8" in m["url"].split("?")[0].lower() or "#EXTM3U" in m["text"][:20]]
    master = [m for m in hls if "#EXT-X-STREAM-INF" in m["text"]]
    dash = [m for m in manifests if m not in hls]
    for group, kind in ((master, "hls"), (hls, "hls"), (dash, "dash")):
        if group:
            chosen = (group[0], kind)
            break
    sig = analyze_signals([m["url"] for m in manifests] + list(media) + list(signals), eme)
    if chosen:
        m, kind = chosen
        res = analyze_manifest(m["text"])
        if res.protected:
            return VideoSource(m["url"], kind, True, res.reason)
        if sig.protected:
            return VideoSource(m["url"], kind, True, sig.reason)
        return VideoSource(m["url"], kind)
    if media:
        if sig.protected:
            return VideoSource(media[0], "file", True, sig.reason)
        return VideoSource(media[0], "file")
    if sig.protected:
        return VideoSource(None, None, True, sig.reason)
    return VideoSource()


class MediaSniffer:
    def __init__(self, page):
        self.page = page
        self.manifests, self.media, self.signals = [], [], []
        page.add_init_script(EME_JS)
        page.on("response", self._on)

    def _on(self, resp):
        try:
            url = resp.url
            path = url.split("?")[0].lower()
            ctype = (resp.headers.get("content-type") or "").lower()
            if DRM_URL_RE.search(path):
                self.signals.append(url)
            if path.endswith((".m3u8", ".mpd")) or any(t in ctype for t in MANIFEST_TYPES):
                try:
                    text = resp.text()[:2_000_000]
                except Exception:
                    text = ""
                self.manifests.append({"url": url, "text": text})
            elif ctype.startswith("video/") or path.endswith((".mp4", ".webm")):
                if url not in self.media:
                    self.media.append(url)
        except Exception:
            pass

    @property
    def found(self) -> bool:
        return bool(self.manifests or self.media or self.signals)

    def eme(self) -> list:
        try:
            return list(self.page.evaluate("window.__kiDrm || []"))
        except Exception:
            return []

    def result(self) -> VideoSource:
        return choose_source(self.manifests, self.media, self.signals, self.eme())
