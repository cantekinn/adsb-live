# ROADMAP — Sonraki adımlar

Tamamlananlar 1-11 commit'lerde. Aşağıdakiler iskelet/plan olarak hazır,
her biri kendi yarı-projesi.

## 12. Trail heatmap animasyonu (orta zorluk)
**Hedef**: Son N saatlik tüm uçak izlerini zaman dilimine göre animate et.

**Yaklaşım**:
- SQLite'tan `history` tablosundan son 6 saat verisini çek
- 5 dk'lık dilimlere böl, her dilimi heatLayer olarak göster
- Slider ile saatler arasında geçiş
- API: `GET /api/heatmap?from=<ts>&to=<ts>&bin=5min`

**Dosyalar**: `web/heatmap.py`, `web/static/app.js` (slider + replay loop)

## 13. 3D Globe (CesiumJS) (orta zorluk)
**Hedef**: Düz Leaflet harita yerine 3 boyutlu Earth.

**Yaklaşım**:
- Yeni route `/globe` → `index_3d.html`
- CesiumJS CDN: `https://cesium.com/downloads/cesiumjs/releases/1.119/Build/Cesium/Cesium.js`
- Uçakları `Entity.position` ile gerçek altitude'da göster
- Track polyline 3D
- Cesium ION token opsiyonel (yüksek kalite imagery için)

**Sorun**: Cesium ION free tier yeterli ama account gerekli. OpenStreetMap WMS fallback.

## 14. WebGL marker layer (performans)
**Hedef**: 1000+ uçak için Leaflet DivIcon yerine WebGL.

**Yaklaşım**: `leaflet-canvas-markers` veya `Mapbox GL JS`. Şu an 30k+ uçakta
Leaflet 5-10 fps düşer; WebGL 60 fps tutar.

## 15. NOTAM overlay
**Hedef**: FAA / Eurocontrol NOTAM'larından restricted airspace çiz.

**Yaklaşım**:
- FAA: https://api.faa.gov/s/notams (auth gerekli)
- Eurocontrol AIM: anonim feed yok
- Alternatif: opennotam.org JSON
- Polygon çiz, hover tooltip

## 16. VOR/DME / Selected navaid (BDS 5,3)
**Hedef**: Uçağın seçili nav aidini Comm-B'den çek.

**Yaklaşım**:
- BDS 5,3 (Vertical Intention Report) selected MCP yer aldığı için zaten alıyoruz
- BDS 1,7 (Selected Vertical Intention Mode-S features) — gerçek selected navaid yok
- VOR/DME doğrudan ADS-B'de yok; FMS data flow gerek
- Bu yüzden bu özellik **sınırlı** — sadece MCP/FMS altitude gösterimi (zaten yapıyoruz)
- Frontend'de navaid frequency tooltip için VOR position DB ekle

## 17. Pattern of Life (uzun vadeli istatistik)
**Hedef**: Saat/gün bazında trafik desenleri öğren ve sapma tespit et.

**Yaklaşım**:
- SQLite history → saatlik bin
- Her saat için: ortalama uçak sayısı, en sık callsignler, en sık rotalar
- 7+ gün veri biriktikten sonra her dilim için mean+stddev
- Bugün vs ortalama → sapma metriği
- Dashboard'da "saat 14:00 normalde 240 uçak, şu an 380 → +58%"

**Dosyalar**: `analytics/pol.py`, dashboard ekleme

## 18. ACARS decode (131.55 MHz)
**Hedef**: İkinci SDR ile uçak metin mesajlarını yakala.

**Yaklaşım**: `acarsdec` veya `vdlm2dec` mevcut, ama 1090 MHz ile aynı SDR
çalıştıramazsın (farklı frekans). İkinci RTL-SDR + ayrı thread.

**Sorun**: ACARS Türkiye'de cok yaygin değil (VHF, line-of-sight 30 km).
VDL Mode 2 (136.975 MHz) daha aktif.

## 19. 978 MHz UAT decode
**Hedef**: US Genel Havacılık UAT signal'i.

**Yaklaşım**: `dump978-fa` veya kendi UAT decoder.

**Sorun**: Sadece ABD'de yayın yapan UAT donatımlı GA uçakları. Türkiye'de
sinyal yok (FAA mandatı sadece US).

## 20. GPU preamble dedektör (CuPy)
**Hedef**: 10x preamble detection hızı.

**Yaklaşım**:
- `cupy.asarray(mag)` ile numpy array'i GPU'ya kopyala
- `cp.stack + cp.min/max` ile aynı kod çalışır
- 4 GB+ chunklarda anlamlı kazanç

**Dosya**: `decoder/preamble_gpu.py` opsiyonel modül, config flag ile aktif.

## 21. PostgreSQL + PostGIS
**Hedef**: SQLite yerine gerçek jeografik DB.

**Yaklaşım**:
- `aircraft` ve `history` tabloları PostGIS GEOMETRY(POINT, 4326)
- Spatial query: `ST_DWithin(pos, ref, 100_NM)`
- Hex grid hesabı (heatmap için)
- Otomatik migration script: SQLite -> PostgreSQL

**Dosya**: `storage/db_pg.py` alternatif backend, `--db-backend=pg`

## Önerilen sıra (ek 2-3 hafta)

1. **#17 Pattern of Life** — SQLite'tan istatistik (yeni veri toplandıkça anlamlı)
2. **#12 Trail heatmap animasyonu** — Replay slider
3. **#13 3D globe** — sunum etkisi
4. **#15 NOTAM** — operational değer
5. **#20 GPU** — performans (Nvidia kart varsa)
6. **#21 PostgreSQL** — scale (10000+ uçak izleme)

ACARS/UAT/VOR atlanabilir (donanım/coğrafi/protokol kısıtları).
