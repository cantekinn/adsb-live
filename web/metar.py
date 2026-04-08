"""
METAR / TAF fetcher (NOAA Aviation Weather Center).

Public REST API: https://aviationweather.gov/api/data/metar?ids=ICAO&format=json
Rate limit makul; biz sadece icin gerektikce sorgulariz, cache'leriz.
"""

import time
import json
import logging
import urllib.request
import urllib.parse

log = logging.getLogger(__name__)

_cache: dict[str, tuple[float, dict]] = {}   # ICAO -> (timestamp, data)
TTL = 600.0  # 10 dakika cache


def get_metar(icao: str) -> dict | None:
    icao = icao.upper().strip()
    if not icao or len(icao) != 4:
        return None
    now = time.time()
    if icao in _cache:
        t, d = _cache[icao]
        if now - t < TTL:
            return d
    try:
        url = (f'https://aviationweather.gov/api/data/metar'
               f'?ids={icao}&format=json&hours=2')
        req = urllib.request.Request(url, headers={
            'User-Agent': 'adsb-live/1.0', 'Accept': 'application/json',
        })
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        if not data:
            _cache[icao] = (now, {})
            return {}
        latest = data[0]
        result = {
            'raw': latest.get('rawOb'),
            'temp_c': latest.get('temp'),
            'dewp_c': latest.get('dewp'),
            'wind_dir': latest.get('wdir'),
            'wind_kt': latest.get('wspd'),
            'visib': latest.get('visib'),
            'altim_mb': latest.get('altim'),
            'wx': latest.get('wxString'),
            'time': latest.get('reportTime'),
        }
        _cache[icao] = (now, result)
        return result
    except Exception as e:
        log.warning('METAR fetch %s: %s', icao, e)
        return None


def get_taf(icao: str) -> dict | None:
    icao = icao.upper().strip()
    if not icao or len(icao) != 4:
        return None
    cache_key = 'TAF_' + icao
    now = time.time()
    if cache_key in _cache:
        t, d = _cache[cache_key]
        if now - t < TTL:
            return d
    try:
        url = f'https://aviationweather.gov/api/data/taf?ids={icao}&format=json'
        req = urllib.request.Request(url, headers={
            'User-Agent': 'adsb-live/1.0', 'Accept': 'application/json',
        })
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        if not data:
            _cache[cache_key] = (now, {})
            return {}
        result = {'raw': data[0].get('rawTAF')}
        _cache[cache_key] = (now, result)
        return result
    except Exception as e:
        log.warning('TAF fetch %s: %s', icao, e)
        return None
