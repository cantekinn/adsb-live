"""
OurAirports CSV (85k satir) -> web/static/airports.json (sadece buyuk/orta).

Heliport/seaplane filter. Sadece type=large_airport ve medium_airport.
Output ~10k satir, ~1.5 MB JSON.

Kullanim:
  py scripts/build_airports_json.py [csv_path]
"""

import csv
import json
import sys
import os


KEEP_TYPES = {'large_airport', 'medium_airport'}


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else '/tmp/airports.csv'
    if not os.path.exists(src):
        print(f'CSV bulunamadi: {src}')
        print('Indir: curl -sL https://davidmegginson.github.io/ourairports-data/airports.csv -o airports.csv')
        return 1

    rows = []
    with open(src, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r['type'] not in KEEP_TYPES:
                continue
            if not r.get('iata_code') and r['type'] == 'medium_airport':
                continue  # IATA'sizleri at (cogu kucuk)
            try:
                lat = float(r['latitude_deg']); lon = float(r['longitude_deg'])
            except (ValueError, TypeError):
                continue
            rows.append({
                'iata': r.get('iata_code') or '',
                'icao': r.get('icao_code') or r.get('ident'),
                'name': r['name'],
                'lat': round(lat, 4), 'lon': round(lon, 4),
                'country': r['iso_country'],
                'type': r['type'][0],  # 'l' or 'm'
            })

    out = 'web/static/airports.json'
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, separators=(',', ':'))
    print(f'{len(rows)} havaalani yazildi: {out}')
    size = os.path.getsize(out) / 1024
    print(f'Boyut: {size:.0f} KB')
    by_country = {}
    for r in rows:
        by_country[r['country']] = by_country.get(r['country'], 0) + 1
    top = sorted(by_country.items(), key=lambda x: -x[1])[:10]
    print('Top 10 ulke:', top)


if __name__ == '__main__':
    sys.exit(main() or 0)
