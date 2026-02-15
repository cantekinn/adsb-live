"""Konfigurasyon - tum sabit ayarlar burada."""

# --- SDR ---
SAMPLE_RATE = 2_000_000        # 2 MS/s -> 1 us Mode-S chip basina 2 ornek
CENTER_FREQ = 1_090_000_000    # 1090 MHz ADS-B
SDR_GAIN = 'auto'              # ya da 40.2, 49.6 vb (R820T2 icin)
SDR_PPM = 0                    # frekans hatasi (kristal) ppm

# Capture chunk - asenkron callback'e ne kadar IQ gelsin
# 256k complex sample = 128 ms IQ @ 2 MS/s
CAPTURE_CHUNK = 256 * 1024

# Decoder kuyrugu - dolarsa eski paketler atilir
QUEUE_MAX = 8

# --- Preamble dedektoru ---
# 2 MS/s ornekleme -> 1 us = 2 ornek, 8 us preamble = 16 ornek
PREAMBLE_LEN = 16
# Mode-S preamble: 1 us'lik dort darbe; 0.5 us darbe genisligi
# 2 ornek/us oldugu icin "yuksek" olmasi gereken ornek indeksleri:
PREAMBLE_HIGH_IDX = (0, 2, 7, 9)
PREAMBLE_LOW_IDX = (1, 3, 4, 5, 6, 8, 10, 11, 12, 13, 14, 15)
# Yuksek/dusuk magnitude orani esigi
PREAMBLE_THRESHOLD = 2.0

# --- Mesaj ---
LONG_MSG_BITS = 112           # DF17 ADS-B
LONG_MSG_SAMPLES = LONG_MSG_BITS * 2   # PPM, 2 ornek/bit

# --- Tracker ---
AIRCRAFT_TIMEOUT_S = 60.0     # bu surede mesaj gelmezse listeden dus
CPR_PAIR_TIMEOUT_S = 10.0     # even+odd CPR pair gecerlilik penceresi

# --- Web ---
WEB_HOST = '0.0.0.0'
WEB_PORT = 5000
EMIT_INTERVAL_S = 1.0         # SocketIO update frekansi
