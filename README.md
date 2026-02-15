# ADS-B Live Tracker v3

1090 MHz ADS-B / Mode-S decoder ve harita arayüzü. Sıfırdan Python ile yazılmış decoder + canlı OpenSky API entegrasyonu + Leaflet UI.

İki giriş modu:
- **Raw IQ → decode**: RTL-SDR canlı veya `.wav/.bin` dosyası
- **OpenSky API**: SDR olmadan dünya çapındaki anlık trafik

## Hızlı başlangıç

```bash
pip install -r requirements.txt
```

```bash
# 1. OpenSky canlı (SDR/internet hazır olduğunda)
py main.py --opensky --opensky-bbox tr --db data/adsb.db

# 2. Yerel RTL-SDR
py main.py --ref-lat 40.21 --ref-lon 29.07 --db data/adsb.db

# 3. IQ dosya replay
py main.py --iq samples/recording.bin --speed 4 --ref-lat 53 --ref-lon -2

# 4. Sentetik test verisi üret (40 uçak UK havasahası)
py scripts/generate_synthetic_iq.py --duration 600 --out samples/synthetic.bin
```

Tarayıcı: <http://localhost:5000>

## Özellikler

**Decoder (sıfırdan, pyModeS kullanılmadı)**:
- Preamble dedektör + matched filter quality skoru
- PPM demod (112-bit + 56-bit) + multi-offset retry
- CRC-24 (poly 0x1FFF409) + 1-bit ve 2-bit error correction
- DF17 ADS-B: TC 1-4 (identification), 5-8 (surface), 9-22 (airborne), 19 (velocity), 31 (op status)
- DF11 All-Call (whitelist'lenmiş ICAO ile)
- DF20/21 Comm-B: BDS 2,0 (callsign), 4,0 (MCP/FMS alt), 5,0 (roll/track/GS/TAS), 6,0 (heading/IAS/Mach)
- CPR global + local konum çözümü + hız sanity check

**Veri kaynakları**:
- RTL-SDR canlı (pyrtlsdr)
- IQ dosya: .wav (16-bit, herhangi sample rate) + .bin (8-bit unsigned)
- OpenSky Network REST API (anonim 12 sn poll)
- Multi-file feeding + sonsuz loop

**UI**:
- Leaflet harita (dark/light tema toggle)
- Altitude rengi (mor→mavi→yeşil→sarı→kırmızı)
- Uçak tipi ikonu (heli/prop/narrow/heavy)
- Bayraklı liste + ICAO/callsign arama
- Filter panel (alt/spd/country/operator)
- Dashboard (top 10, country dağılımı, fix1/2 sayaçlar)
- Heatmap modu (yoğunluk)
- Polar plot (anten karakterizasyon)
- Detail panel (Comm-B kokpit verileri dahil)
- Track polyline (her uçak için son 100 nokta)
- Havaalanı işaretleri (70 büyük UK/EU/TR)
- Mobile responsive

**Backend**:
- SQLite persistence (aircraft + history tabloları, WAL)
- REST API: `/api/aircraft`, `/api/aircraft/<icao>`, `/api/history/<icao>`, `/api/stats`, `/api/airports`
- Flask + Socket.IO 1 Hz emit

**Akademik**:
- `scripts/snr_crc_analysis.py`: SNR taraması → CRC pass rate eğrisi
- `scripts/lna_impact.py`: Friis NF + LNA katkı karşılaştırması
- BTÜ EEM bitirme projesi (BFP740 3-katlı LNA) tezine veri üretir

## Mimari

```
decoder/                 sıfırdan yazılmış IQ → Mode-S decoder
  preamble.py            8 µs preamble dedektör + matched filter
  ppm.py                 PPM demod (112-bit + 56-bit)
  crc.py                 CRC-24, 1-bit + 2-bit error correction
  modes.py               Mode-S frame parser
  adsb.py                DF17 ME decode (TC 1-31)
  commb.py               DF20/21 BDS 2/4/5/6
  cpr.py                 CPR konum çözümü
  pipeline.py            tüm decode hattı

aircraft/                uçak durum tablosu + DB lookup
sdr/                     RTL-SDR yakalama
opensky/                 OpenSky Network REST feed
storage/                 SQLite persistence
web/                     Flask + Socket.IO + REST API
scripts/                 yardımcı scriptler
tests/                   unit testler
samples/                 IQ test verileri (.gitignore)
```

## Test

```bash
pytest tests/
```

## Notlar

- `pyModeS` **kullanılmadı** — tüm decode kodu sıfırdan yazıldı (BTÜ EEM bitirme projesi pedagojisi)
- Referans: ICAO Annex 10 Vol IV, Junzi Sun "1090 MHz Riddle"
- Önceki sürüm: `github.com/cantekinn/ADSB-Signal-Tracker` (JSON tabanlı, deprecated)

## Lisans

MIT — eğitim amaçlı kullanım.
