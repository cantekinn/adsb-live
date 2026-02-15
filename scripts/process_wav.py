"""
WAV IQ kaydini (16-bit, 2.4 MS/s) streaming sekilde decoder'a ver.

SDRangel adsb.zip -> 16-bit signed stereo (ch0=I, ch1=Q) @ 2.4 MS/s, 102 sn, 980 MB.

Chunk chunk oku, 2 MS/s'ye resample et, decoder'a ver. Bellek bagimsiz.
"""

import argparse
import wave
import sys
import os
import time
import numpy as np
from scipy.signal import resample_poly

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decoder.pipeline import Decoder
from aircraft.tracker import AircraftTracker


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('wav')
    ap.add_argument('--seconds', type=float, default=None,
                    help='Sadece ilk N saniye (test icin)')
    ap.add_argument('--chunk-sec', type=float, default=2.0,
                    help='Kac saniyelik chunk islensin')
    args = ap.parse_args()

    w = wave.open(args.wav, 'rb')
    fs_in = w.getframerate()
    n_ch = w.getnchannels()
    sw = w.getsampwidth()
    total = w.getnframes()
    if sw != 2 or n_ch != 2:
        print(f'Beklenmedik WAV: {sw*8} bit, {n_ch} ch')
        return 1

    duration = total / fs_in
    target_dur = min(args.seconds, duration) if args.seconds else duration
    target_frames = int(target_dur * fs_in)

    print(f'WAV: {fs_in} Hz, {n_ch} ch, {sw*8} bit, {duration:.1f} s toplam')
    print(f'Islenecek: {target_dur:.1f} s')
    print()

    tracker = AircraftTracker()
    dec = Decoder(tracker)

    # GCD ile resample oran
    from math import gcd
    fs_out = 2_000_000
    g = gcd(fs_in, fs_out)
    up, down = fs_out // g, fs_in // g
    print(f'Resample: {fs_in} -> {fs_out} (up={up}, down={down})')

    chunk_frames = int(args.chunk_sec * fs_in)
    processed = 0
    t0 = time.time()
    last_print = t0
    while processed < target_frames:
        n = min(chunk_frames, target_frames - processed)
        raw = w.readframes(n)
        if not raw:
            break
        actual = len(raw) // (sw * n_ch)
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        iq = (data[0::2] + 1j * data[1::2]).astype(np.complex64)
        # Resample
        iq = resample_poly(iq, up, down).astype(np.complex64)
        # Decoder'a 256k'lik mini-chunklar halinde
        SUB = 256 * 1024
        for s in range(0, len(iq), SUB):
            dec.process(iq[s:s + SUB])
        processed += actual

        now = time.time()
        if now - last_print > 2.0:
            wall = now - t0
            sim_sec = processed / fs_in
            print(f'  [{sim_sec:5.1f}/{target_dur:.0f} s sim, {wall:5.1f} s wall] '
                  f'preamble={dec.stats["preamble_hits"]:>6}  '
                  f'CRC ok={dec.stats["crc_ok"]:>5}  '
                  f'DF17={dec.stats["df17_decoded"]:>5}  '
                  f'ucak={tracker.count()}')
            last_print = now

    w.close()
    wall = time.time() - t0
    print()
    print('=== SONUC ===')
    s = dec.stats
    print(f'Wall time       : {wall:.1f} s')
    print(f'Simulasyon      : {target_dur:.1f} s')
    print(f'Hizlanma        : {target_dur/wall:.2f}x realtime')
    print(f'Preamble hits   : {s["preamble_hits"]:,}')
    print(f'CRC ok          : {s["crc_ok"]:,}')
    print(f'DF17 decoded    : {s["df17_decoded"]:,}')
    print(f'1-bit duzeltme  : {s.get("fixed_1bit", 0):,}')
    print(f'DF11 onaylanan  : {s.get("df11_confirmed", 0):,}  (DF17 ile bilinen ICAO)')
    print(f'Bulunan ucak    : {tracker.count()}')
    print()
    print('=== UCAKLAR (mesaj sayisina gore, en aktif 30) ===')
    snap = sorted(tracker.snapshot(), key=lambda a: -a['msg_count'])
    for ac in snap[:30]:
        cs = (ac.get('callsign') or '-').strip()
        alt = ac.get('altitude')
        spd = ac.get('speed')
        hdg = ac.get('heading')
        lat = ac.get('lat'); lon = ac.get('lon')
        loc = f'({lat:7.4f},{lon:8.4f})' if lat is not None else '       (no pos)'
        alts = f'{alt:>5}' if alt is not None else '   -'
        spds = f'{spd:>5.0f}' if spd is not None else '   -'
        hdgs = f'{hdg:>3.0f}' if hdg is not None else '  -'
        print(f'  ICAO {ac["icao"]}  cs={cs:>9}  alt={alts} ft  spd={spds} kt  hdg={hdgs}°  pos={loc}  msg={ac["msg_count"]:>4}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
