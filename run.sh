#!/usr/bin/env bash
# Tek komutla kurulum + çalıştırma:  ./run.sh   (arayüz: http://127.0.0.1:8765)
set -euo pipefail
cd "$(dirname "$0")"

command -v python3 >/dev/null || { echo "python3 gerekli: sudo apt install python3 python3-venv python3-pip"; exit 1; }
[ -d venv ] || python3 -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate
pip install -q -r requirements.txt

if [ ! -f venv/.chromium_ok ]; then
  playwright install chromium || { echo "Chromium kurulamadı. Gerekirse: playwright install-deps chromium (sudo)"; exit 1; }
  touch venv/.chromium_ok
fi

command -v ffmpeg >/dev/null        || echo "UYARI: ffmpeg yok  ->  sudo apt install ffmpeg"
command -v HandBrakeCLI >/dev/null  || echo "UYARI: HandBrakeCLI yok  ->  sudo apt install handbrake-cli  (ya da Ayarlar'dan yeniden kodlamayı kapat)"

exec python -m kurs_app "$@"
