"""
planespotters.net foto API.

Public REST: https://api.planespotters.net/pub/photos/hex/<ICAO24>
Anonim, sinirsiz olmayan. Cache zorunlu (24 saat TTL).
"""

import time
import json
import logging
import urllib.request

log = logging.getLogger(__name__)

_cache: dict[str, tuple[float, dict | None]] = {}
TTL = 24 * 3600.0  # 24 saat


def get_photo(icao: str) -> dict | None:
    """ICAO24 hex -> {thumbnail, large, photographer, link}."""
    icao = icao.upper().strip()
    if not icao or len(icao) != 6:
        return None
    now = time.time()
    if icao in _cache:
        t, d = _cache[icao]
        if now - t < TTL:
            return d
    try:
        url = f'https://api.planespotters.net/pub/photos/hex/{icao}'
        req = urllib.request.Request(url, headers={
            'User-Agent': 'adsb-live/1.0 (educational)',
            'Accept': 'application/json',
        })
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        if not data.get('photos'):
            _cache[icao] = (now, None)
            return None
        p = data['photos'][0]
        result = {
            'thumbnail': p.get('thumbnail', {}).get('src'),
            'large': p.get('thumbnail_large', {}).get('src'),
            'photographer': p.get('photographer'),
            'link': p.get('link'),
            'aircraft': p.get('aircraft_type'),
            'registration': p.get('registration'),
        }
        _cache[icao] = (now, result)
        return result
    except Exception as e:
        log.debug('planespotters %s: %s', icao, e)
        _cache[icao] = (now, None)
        return None
