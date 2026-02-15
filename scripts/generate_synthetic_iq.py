"""
Sentetik ADS-B IQ jeneratoru.

UK havasahasinda 40 ucagin 30 dakikalik gercekci hareketini
2 MS/s, 8-bit unsigned IQ formatinda dosyaya yazar. main.py veya
process_wav.py ile decode edilebilir.

Format: rtl_sdr default - interleaved uint8 I,Q,I,Q,...
Center value 127 (DC). Mesaj bolgelerinde I~220, Q~127 (magnitude burst).

Mesaj cadence (her ucak basina):
  - Position even: 0.5 sn
  - Position odd: 0.5 sn (0.25 sn offset)
  - Velocity: 0.5 sn
  - Identification: 5 sn

Boyut: 2 MS/s * 2 byte * süre. 30 dk = 7.2 GB. Default 600 sn (1.2 GB).
"""

import argparse
import math
import os
import random
import struct
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from encode_modes import (build_df17, encode_position,
                          encode_velocity, encode_identification)


FS = 2_000_000                     # sample rate Hz
BIT_SAMPLES = 2                    # 1 us = 2 ornek
PREAMBLE_SAMPLES = 16              # 8 us
MSG_BITS = 112
MSG_SAMPLES = MSG_BITS * BIT_SAMPLES  # 224
TOTAL_SAMPLES_PER_MSG = PREAMBLE_SAMPLES + MSG_SAMPLES   # 240


# ----- realistic fleet -----
AIRLINES = [
    ('BAW', 'British Airways', 0x400000),
    ('VIR', 'Virgin Atlantic',  0x400500),
    ('EZY', 'easyJet',          0x400A00),
    ('EJU', 'easyJet Europe',   0x4402F0),
    ('TOM', 'TUI Airways',      0x401000),
    ('RYR', 'Ryanair',          0x4CA900),
    ('NJE', 'NetJets',          0x490D00),
    ('KLM', 'KLM',              0x480900),
    ('AFR', 'Air France',       0x3946A0),
    ('DLH', 'Lufthansa',        0x3C4B00),
    ('SWR', 'Swiss',            0x4B1500),
    ('AUA', 'Austrian',         0x440000),
    ('THY', 'Turkish Airlines', 0x4BAA00),
    ('PGT', 'Pegasus',          0x4BB500),
    ('IBE', 'Iberia',           0x342000),
    ('AEE', 'Aegean',           0x4691A0),
    ('SAS', 'SAS',              0x46B900),
    ('FIN', 'Finnair',          0x460000),
    ('CFE', 'BA Cityflyer',     0x406500),
    ('GMI', 'Germania',         0x440100),
]


def random_aircraft(rng: random.Random):
    """Tek bir gercekci ucak durumu olustur."""
    airline = rng.choice(AIRLINES)
    code, _, icao_base = airline
    icao = icao_base + rng.randint(0, 255)
    flight_num = rng.randint(1, 9999)
    callsign = f'{code}{flight_num}'
    # UK + cevre havasahasi
    lat = rng.uniform(49.5, 58.0)
    lon = rng.uniform(-7.0, 3.0)
    alt = rng.choice([3000, 5000, 8000, 12000, 18000, 25000, 30000, 33000,
                      35000, 37000, 38000, 41000])
    speed = rng.uniform(220, 480)
    heading = rng.uniform(0, 360)
    vrate = rng.choice([0, 0, 0, 0, -512, 512, -1024, 1024, -1536, 1536])
    return {
        'icao': f'{icao:06X}',
        'callsign': callsign,
        'lat': lat, 'lon': lon, 'alt': alt,
        'speed': speed, 'heading': heading, 'vrate': vrate,
    }


def advance(ac: dict, dt: float) -> None:
    """dt saniye boyunca ucagi ilerlet (great-circle yaklasimi)."""
    # 1 derece enlem = 60 NM. 1 derece boylam = 60*cos(lat) NM
    d_nm = ac['speed'] * dt / 3600.0
    rad = math.radians(ac['heading'])
    dlat = (d_nm * math.cos(rad)) / 60.0
    dlon = (d_nm * math.sin(rad)) / (60.0 * math.cos(math.radians(ac['lat'])))
    ac['lat'] += dlat
    ac['lon'] += dlon
    ac['alt'] += ac['vrate'] * (dt / 60.0)
    # Sinira yaklasinca yumusak donus (rastgele 60-120 derece)
    margin = 0.5  # derece
    if (ac['lat'] < 49.5 + margin or ac['lat'] > 58.0 - margin
            or ac['lon'] < -8 + margin or ac['lon'] > 4 - margin):
        # Merkeze yonel
        cx, cy = -2.5, 53.75  # bant merkezi (lon, lat)
        target = math.degrees(math.atan2(cx - ac['lon'], cy - ac['lat']))
        ac['heading'] = target % 360
    if ac['alt'] < 3000:
        ac['vrate'] = abs(ac['vrate'])
    if ac['alt'] > 41000:
        ac['vrate'] = -abs(ac['vrate'])


def modulate_msg(msg: bytes) -> bytes:
    """14-byte mesaj -> 240 sample x 2 (I,Q) = 480 bytes uint8 interleaved."""
    out = np.full(TOTAL_SAMPLES_PER_MSG * 2, 127, dtype=np.uint8)
    HIGH = 220   # I, magnitude burst
    # Preamble: high @ samples 0, 2, 7, 9
    for p in (0, 2, 7, 9):
        out[p * 2] = HIGH
    # Body
    bits = []
    for byte in msg:
        for i in range(8):
            bits.append((byte >> (7 - i)) & 1)
    for i, b in enumerate(bits):
        base = PREAMBLE_SAMPLES + i * BIT_SAMPLES
        if b == 1:
            out[base * 2] = HIGH         # ilk yariya high
        else:
            out[(base + 1) * 2] = HIGH   # ikinci yariya high
    return bytes(out)


# ----- mesaj uretimi -----
def gen_position_messages(ac, t, even_offset=0.0):
    """t aninda bu ucagin even ve odd position mesajlarini uret."""
    out = []
    me_e = encode_position(ac['lat'], ac['lon'], int(ac['alt']), f=0)
    out.append((t + even_offset, build_df17(ac['icao'], me_e)))
    me_o = encode_position(ac['lat'], ac['lon'], int(ac['alt']), f=1)
    out.append((t + even_offset + 0.25, build_df17(ac['icao'], me_o)))
    return out


def gen_velocity_message(ac, t):
    me = encode_velocity(ac['speed'], ac['heading'], int(ac['vrate']))
    return (t, build_df17(ac['icao'], me))


def gen_identification_message(ac, t):
    me = encode_identification(ac['callsign'])
    return (t, build_df17(ac['icao'], me))


# ----- ana akis -----
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--duration', type=float, default=600,
                    help='Toplam simulasyon suresi (sn). Default 600.')
    ap.add_argument('--n-aircraft', type=int, default=40)
    ap.add_argument('--out', default='samples/synthetic_uk.bin',
                    help='Cikis dosyasi (8-bit IQ unsigned, rtl_sdr formati)')
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--noise', type=int, default=2,
                    help='Gauss noise std (0=temiz)')
    args = ap.parse_args()

    rng = random.Random(args.seed)
    fleet = [random_aircraft(rng) for _ in range(args.n_aircraft)]
    print(f'{len(fleet)} ucak olusturuldu')
    print(f'Sure         : {args.duration} sn')
    print(f'Toplam sample: {int(args.duration * FS):,}')
    print(f'Dosya boyutu : {int(args.duration * FS * 2) / 1e9:.2f} GB')
    print(f'Output       : {args.out}')

    # Tum mesajlari zaman planla
    print('Mesaj plani olusturuluyor...')
    schedule = []  # list of (time, msg_bytes)
    for ac_idx, ac in enumerate(fleet):
        # Her ucak icin kendi zaman ofseti (carpisma azalt)
        phase = rng.uniform(0, 0.5)
        t = phase
        # Position cadence ~0.5 sn (even+odd birlikte = 0.25 sn arali)
        while t < args.duration:
            # Once ucak konumunu ilerlet
            advance(ac, 0.5 if t > 0 else 0)
            schedule.extend(gen_position_messages(ac, t, even_offset=0))
            schedule.append(gen_velocity_message(ac, t + 0.1))
            t += 0.5
        # Identification her 5 sn
        for t_id in np.arange(phase + 1.0, args.duration, 5.0):
            ac_t = ac  # callsign degismiyor
            schedule.append(gen_identification_message(ac_t, t_id))

    schedule.sort(key=lambda x: x[0])
    print(f'Toplam mesaj: {len(schedule):,}')

    # Cikis dosyasi - memmap ile parca parca yaz
    out_path = args.out
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    n_samples = int(args.duration * FS)
    n_bytes = n_samples * 2

    print('Output dosyasi olusturuluyor (DC 127 + noise)...')
    t0 = time.time()
    CHUNK = 4 * 1024 * 1024  # 4 MB
    with open(out_path, 'wb') as f:
        remaining = n_bytes
        while remaining > 0:
            n = min(CHUNK, remaining)
            if args.noise > 0:
                buf = (127 + rng.gauss(0, args.noise) * np.ones(n)).astype(np.uint8)
                # Gercek random noise
                buf = np.clip(
                    127 + np.random.normal(0, args.noise, n),
                    0, 255).astype(np.uint8)
            else:
                buf = np.full(n, 127, dtype=np.uint8)
            f.write(buf.tobytes())
            remaining -= n
    print(f'  noise yazma : {time.time()-t0:.1f} sn')

    # Mesajlari uygun ofsetlere yaz
    print('Mesajlar dosyaya yaziliyor...')
    t1 = time.time()
    with open(out_path, 'r+b') as f:
        for i, (t, msg) in enumerate(schedule):
            sample_pos = int(t * FS)
            if sample_pos + TOTAL_SAMPLES_PER_MSG >= n_samples:
                continue
            byte_pos = sample_pos * 2
            buf = modulate_msg(msg)
            f.seek(byte_pos)
            f.write(buf)
            if i % 10000 == 0 and i > 0:
                print(f'  {i:>7}/{len(schedule)}  ({i/len(schedule)*100:.0f}%)')
    print(f'  mesaj yazma : {time.time()-t1:.1f} sn')

    print(f'\nTamamlandi: {out_path}')
    print(f'Decode etmek icin:')
    print(f'  py main.py --iq {out_path} --speed 2 --ref-lat 53 --ref-lon -2')


if __name__ == '__main__':
    main()
