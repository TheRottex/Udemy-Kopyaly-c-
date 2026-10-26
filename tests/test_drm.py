from kurs_app.drm import analyze_manifest, analyze_signals
from kurs_app.sniffer import choose_source

CLEAR = "#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI=\"https://x/key\"\n#EXTINF:4,\nseg.ts\n"
WIDEVINE = '#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES-CTR,KEYFORMAT="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"\n'
FAIRPLAY = '#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,KEYFORMAT="com.apple.streamingkeydelivery",URI="skd://x"\n'
DASH_DRM = '<MPD><ContentProtection schemeIdUri="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"/></MPD>'


def test_clear_hls_is_not_drm():
    assert not analyze_manifest(CLEAR).protected


def test_widevine_fairplay_dash_detected():
    assert analyze_manifest(WIDEVINE).protected
    assert analyze_manifest(FAIRPLAY).protected
    assert analyze_manifest(DASH_DRM).protected


def test_signals():
    assert analyze_signals(eme_systems=["com.widevine.alpha"]).protected
    assert not analyze_signals(eme_systems=["org.w3.clearkey"]).protected
    assert analyze_signals(urls=["https://lic.example/widevine/license"]).protected
    assert not analyze_signals(urls=["https://cdn.example/video/seg1.ts"]).protected


def test_choose_source_skips_drm_and_prefers_master():
    master = {"url": "https://c/master.m3u8", "text": "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nv.m3u8"}
    media = {"url": "https://c/v.m3u8", "text": "#EXTM3U\n#EXTINF:4,\ns.ts"}
    s = choose_source([media, master], [], [])
    assert s.url.endswith("master.m3u8") and not s.drm
    drm = choose_source([{"url": "https://c/a.m3u8", "text": WIDEVINE}], [], [])
    assert drm.drm and drm.reason
    assert not choose_source([], [], []).url
