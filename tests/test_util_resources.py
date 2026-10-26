from kurs_app.resources import is_file_link, label_matches
from kurs_app.util import human_size, redact, slug, srt_to_vtt


def test_slug_is_path_safe():
    s = slug("../../etc/passwd: a*b?")
    assert "/" not in s and "\\" not in s and not s.startswith(".")
    assert slug("") == "adsiz" and len(slug("x" * 500)) <= 110


def test_redact_hides_query():
    assert "SECRET" not in redact("GET https://a.b/c.m3u8?token=SECRET ok")


def test_srt_to_vtt():
    out = srt_to_vtt("1\n00:00:01,500 --> 00:00:02,000\nmerhaba")
    assert out.startswith("WEBVTT") and "00:00:01.500" in out


def test_human_size():
    assert human_size(512) == "512 B" and human_size(2048) == "2.0 KB"


def test_resource_labels_tr_en():
    for t in ["Kaynaklar", "KAYNAKLAR", "Resources", "Materials", "Ekler", "Dosyalar", "Attachments", "Downloads", "İndirilenler"]:
        assert label_matches(t), t
    for t in ["Genel Bakış", "Notlar", "Sorular", "", "Bu çok uzun bir başlıktır ve kaynaklar kelimesi içerir ama sekme değildir"]:
        assert not label_matches(t), t


def test_is_file_link():
    assert is_file_link("https://a/b/ders.pdf") and is_file_link("https://a/download/12")
    assert is_file_link("https://a/x", has_download_attr=True)
    assert not is_file_link("https://a/video.m3u8") and not is_file_link("javascript:void(0)")
