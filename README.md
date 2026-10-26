# Kurs İndirici + İzleme Arayüzü

Kendi hesabınla erişebildiğin, **DRM ile korunmayan** (HLS/mp4) çevrimiçi kurs videolarını yerel olarak
indirip, yeniden kodlayıp, tarayıcıda düzenli bir oynatıcıyla izlemeni sağlayan yerel bir araçtır.

> **Önemli / sorumluluk:** Yalnızca kendi hesabınla yasal olarak erişebildiğin ve kişisel çevrimdışı
> kullanım amacıyla indirmene izin verilen içerikler için kullan. Birçok platformun kullanım şartları
> indirmeyi yasaklar; bunu kontrol etmek **senin sorumluluğundadır**. Araç DRM'li (Widevine, PlayReady,
> FairPlay, lisanslı SAMPLE-AES) akışları **tespit edip atlar**; DRM'i aşmaya yönelik hiçbir kod içermez.

## Özellikler
- Platform seçimi (adaptör mimarisi) + CSS seçicili **generic** adaptör (JSON profil ya da arayüzden)
- Şifre yok: giriş **görünür tarayıcıda sen yaparsın**; yalnızca oturum çerezi `profil/` altında kalır (0600)
- Hesaptaki kursları arama/listeleme, çoklu seçim, kuyruk
- Canlı ilerleme (SSE), duraklat / devam / hatalıları yeniden dene, günlük; yarıda kalan işler diskten devam eder
- Otomatik **"Kaynaklar" sekmesi bulma** (Kaynaklar, Resources, Materials, Ekler, Dosyalar…) + elle seçici seçeneği
- yt-dlp ile en yüksek kalite, HandBrakeCLI ile yeniden kodlama (x265/x264, CRF, preset)
- İzleme arayüzü: müfredat, HTTP Range destekli oynatıcı, hız, klavye kısayolları, kaldığı yerden devam,
  altyazı (.vtt/.srt), Genel Bakış / Kaynaklar / Notlar sekmeleri
- Sunucu yalnızca `127.0.0.1`'e bağlanır; CSRF başlığı ve Host denetimi vardır

## Kurulum ve çalıştırma (Ubuntu/Debian)
```bash
sudo apt install python3 python3-venv python3-pip ffmpeg handbrake-cli
./run.sh                 # venv + bağımlılıklar + Chromium + sunucu (http://127.0.0.1:8765)
```
Chromium eksik kütüphane isterse: `source venv/bin/activate && playwright install-deps chromium`.
HandBrakeCLI Flatpak ile kuruluysa Ayarlar'da yol olarak sarmalayıcı betiğini ver ya da yeniden kodlamayı kapat.

## Kullanım
1. **İndir** → platform seç → *Giriş yap* → açılan tarayıcıda kendin giriş yap → *Giriş tamamlandı*.
2. Kurs ara/listele, seç, *Kuyruğa ekle* (ya da doğrudan kurs URL'si yapıştır).
3. **Kuyruk**'tan ilerlemeyi izle. **Kütüphane**'den kursu aç ve izle.
4. İlk kullanımda siten için **generic profil** gerekir: *Yeni profil* → seçicileri doldur
   (bkz. `platforms/profiles/ornek.json`). "Kaynaklar" alanlarını boş bırakırsan otomatik aranır.

## Depolama düzeni
```
indirilen/<kurs>/NNN - ders.mp4          ham video
final/<kurs>/NNN - ders.mp4              HandBrake çıktısı (+ metadata.json, altyazılar)
kaynaklar/<kurs>/00 - Kurs kaynakları/   kursun genel dosyaları
kaynaklar/<kurs>/NNN - ders/             derse ait ekler (+ kaynaklar_url.txt)
video_url_listesi/<kurs>.txt             videoların indirildiği adresler
data/                                    kuyruk, ayarlar, ilerleme/notlar (SQLite)
profil/<platform>/                       tarayıcı profili + cookies.txt (git'e girmez)
```

## Yeni platform adaptörü
`platforms/<ad>.py` içinde `kurs_app.platform_base.PlatformAdapter`'dan türet ve `ADAPTERS = [Sinifin()]` tanımla.
Uygulanacak metotlar: `search_courses`, `list_course`, `find_video` (+ isteğe bağlı `find_resources`).
DRM tespiti `kurs_app/sniffer.py` ve `kurs_app/drm.py` içinde ortaktır; adaptörün bunu atlamaması gerekir.

## Testler
```bash
pip install -r requirements-dev.txt && python -m pytest
```
Testler yt-dlp/HandBrake/tarayıcıyı **sahte** bileşenlerle taklit eder.

## Bilinen sınırlar (dürüst not)
- Gerçek bir kurs sitesine karşı **test edilmedi**; CSS seçicileri siteye göre senin ayarlaman gerekir.
- "Kaynaklar" sekmesi sezgiseldir; her sitede çalışmayabilir (elle seçici alanı bunun içindir).
- Arayüz tarayıcıda otomatik test edilmedi (yalnızca JS sözdizimi ve API testleri yapıldı).
- JS ile tetiklenen (tıklayınca oluşan) indirme bağlantıları yakalanmaz; yalnızca gerçek href'ler toplanır.
- `legacy/kurs_indirici.py` projenin ilk, komut satırı sürümüdür ve referans için tutulur.
