"""DRM TESPİTİ. Bu modül yalnızca korumalı akışı fark edip atlamak içindir;
şifre çözme/lisans alma/atlatma ile ilgili hiçbir şey içermez."""
import re
from dataclasses import dataclass

DRM_UUIDS = {
    "edef8ba9-79d6-4ace-a3c8-27dcd51d21ed": "Widevine",
    "9a04f079-9840-4286-ab92-e65be0885f95": "PlayReady",
    "94ce86fb-07ff-4f43-adb8-93d2fa968ca2": "FairPlay",
}
# Lisans sunucusu / DRM hizmeti isteği izleri
DRM_URL_RE = re.compile(r"widevine|playready|fairplay|drmtoday|buydrm|ezdrm|licenseserver|/wv/|/drm/", re.I)

DRM_MESSAGE = "DRM korumalı, indirilemez"


@dataclass
class DrmResult:
    protected: bool
    reason: str = ""


def _attrs(line: str) -> dict:
    return {k.upper(): v.strip('"') for k, v in re.findall(r'([A-Za-z0-9-]+)=("[^"]*"|[^,]*)', line)}


def analyze_manifest(text: str) -> DrmResult:
    if not text:
        return DrmResult(False)
    low = text.lower()
    if "<contentprotection" in low:
        for uuid, name in DRM_UUIDS.items():
            if uuid in low:
                return DrmResult(True, f"DASH ContentProtection ({name})")
        return DrmResult(True, "DASH ContentProtection (şifreli içerik)")
    for line in text.splitlines():
        if line.startswith(("#EXT-X-KEY", "#EXT-X-SESSION-KEY")):
            a = _attrs(line)
            method = a.get("METHOD", "").upper()
            fmt = a.get("KEYFORMAT", "identity").lower()
            if fmt != "identity":
                label = next((n for u, n in DRM_UUIDS.items() if u in fmt), None)
                if "streamingkeydelivery" in fmt:
                    label = "FairPlay"
                return DrmResult(True, f"HLS KEYFORMAT={fmt} ({label or 'lisanslı anahtar'})")
            if method.startswith("SAMPLE-AES"):
                return DrmResult(True, f"HLS METHOD={method}")
    return DrmResult(False)


def analyze_signals(urls=(), eme_systems=()) -> DrmResult:
    for s in eme_systems:
        if s and "clearkey" not in s.lower():
            return DrmResult(True, f"EME anahtar sistemi: {s}")
    for u in urls:
        if DRM_URL_RE.search(u.split("?")[0]):
            return DrmResult(True, "DRM lisans sunucusu isteği")
    return DrmResult(False)


YTDLP_DRM_RE = re.compile(r"\bDRM\b", re.I)
