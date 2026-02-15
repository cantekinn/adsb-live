"""
OpenSky Network live API feeder.

REST: https://opensky-network.org/api/states/all
Anonim (auth'suz): ~400 credit/gun, 10 sn'de bir kabul.
Auth'lu: ~4000 credit/gun.

Response 'states' alani liste. Her ucak = 17 alanli array:
  [icao24, callsign, origin_country, time_position, last_contact,
   longitude, latitude, baro_altitude, on_ground, velocity, true_track,
   vertical_rate, sensors, geo_altitude, squawk, spi, position_source]

Bunlari Aircraft modelimize map ediyoruz.
"""

import logging
import threading
import time
import urllib.request
import urllib.parse
import urllib.error
import json
import math

log = logging.getLogger(__name__)

API_URL = 'https://opensky-network.org/api/states/all'

# Saniye olarak poll araligi - anonim icin 10+ tavsiye
DEFAULT_INTERVAL_S = 12.0

# Dunya cevreleyen bbox: lamin, lomin, lamax, lomax
BBOX_WORLD = None
BBOX_TR_EU = (35.0, -15.0, 60.0, 45.0)
BBOX_TURKEY = (35.5, 25.5, 42.5, 45.0)
BBOX_UK = (49.5, -8.0, 60.0, 3.0)


class OpenSkyFeed:
    def __init__(self, tracker, bbox=None, interval=DEFAULT_INTERVAL_S,
                 stats: dict | None = None,
                 username: str | None = None, password: str | None = None):
        self.tracker = tracker
        self.bbox = bbox
        self.interval = interval
        self.stats = stats
        self.auth = (username, password) if username and password else None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name='OpenSkyFeed')
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # --------------------------------------------------------
    def _build_url(self) -> str:
        params = {}
        if self.bbox:
            lamin, lomin, lamax, lomax = self.bbox
            params['lamin'] = lamin; params['lomin'] = lomin
            params['lamax'] = lamax; params['lomax'] = lomax
        if params:
            return API_URL + '?' + urllib.parse.urlencode(params)
        return API_URL

    def _fetch(self) -> dict | None:
        url = self._build_url()
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'adsb-live/1.0 (educational)',
                'Accept': 'application/json',
            })
            if self.auth:
                import base64
                token = base64.b64encode(
                    f'{self.auth[0]}:{self.auth[1]}'.encode()
                ).decode()
                req.add_header('Authorization', f'Basic {token}')
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                log.warning('OpenSky rate limit, interval artiriliyor')
                self.interval = min(60.0, self.interval * 1.5)
            else:
                log.warning('OpenSky HTTP %d: %s', e.code, e.reason)
            return None
        except Exception as e:
            log.warning('OpenSky fetch hata: %s', e)
            return None

    # --------------------------------------------------------
    def _ingest(self, data: dict) -> int:
        states = data.get('states') or []
        n = 0
        for s in states:
            try:
                if not s[0]:
                    continue
                icao = s[0].upper()
                callsign = (s[1] or '').strip() or None
                country = s[2]
                t_pos = s[3]
                lon = s[5]; lat = s[6]
                baro_alt = s[7]      # m
                on_ground = s[8]
                vel_ms = s[9]        # m/s
                hdg = s[10]
                vrate_ms = s[11]     # m/s
                geo_alt = s[13]      # m
                squawk = s[14]

                fields = {}
                if callsign:
                    fields['callsign'] = callsign
                if country:
                    fields['country'] = country
                if squawk:
                    fields['squawk'] = squawk
                if on_ground is not None:
                    fields['on_ground'] = on_ground

                # Altitude m -> ft
                if baro_alt is not None:
                    fields['altitude'] = int(baro_alt * 3.28084)
                elif geo_alt is not None:
                    fields['altitude'] = int(geo_alt * 3.28084)

                # Velocity m/s -> kt
                if vel_ms is not None:
                    fields['speed'] = vel_ms * 1.94384
                if hdg is not None:
                    fields['heading'] = hdg
                if vrate_ms is not None:
                    fields['vertical_rate'] = int(vrate_ms * 196.85)

                self.tracker.update(icao, **fields)
                # Konum varsa direkt tracker'a yaz (CPR atla)
                if lat is not None and lon is not None:
                    with self.tracker._lock:
                        ac = self.tracker._get_or_create(icao)
                        ac.lat = lat
                        ac.lon = lon
                        ac.last_pos_t = time.time()
                        ac.push_track(lat, lon)
                n += 1
            except (IndexError, TypeError, ValueError) as e:
                log.debug('OpenSky state parse hatasi: %s', e)
        return n

    def _loop(self) -> None:
        log.info('OpenSky feed basladi (bbox=%s, interval=%.1fs)',
                 self.bbox, self.interval)
        while not self._stop.is_set():
            t0 = time.time()
            data = self._fetch()
            if data:
                n = self._ingest(data)
                if self.stats is not None:
                    self.stats['opensky_last_count'] = n
                    self.stats['opensky_last_t'] = t0
                    self.stats['opensky_total_polls'] = \
                        self.stats.get('opensky_total_polls', 0) + 1
                log.debug('OpenSky: %d state alindi', n)
            # interval kadar bekle
            self._stop.wait(self.interval)
