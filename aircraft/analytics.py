"""
Aircraft analytics: holding pattern, ruzgar, rota tahmini.

Tracker'in periyodik calistirdigi hesaplamalar. Sonuclari Aircraft objesine
yazip frontend'de gosteriyoruz.
"""

import math
import time


EARTH_R_NM = 3440.065


def haversine_nm(lat1, lon1, lat2, lon2):
    r1, r2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(r1)*math.cos(r2)*math.sin(dlon / 2)**2
    return 2 * EARTH_R_NM * math.asin(math.sqrt(a))


def bearing(lat1, lon1, lat2, lon2):
    r1, r2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(r2)
    y = math.cos(r1)*math.sin(r2) - math.sin(r1)*math.cos(r2)*math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


# ============== HOLDING PATTERN ==============
def detect_holding(track: list) -> dict | None:
    """Track noktasi listesinden holding pattern tespit et.

    Heuristik: son 6+ nokta varsa, baslangic ve son nokta birbirine
    yakin (< 5 NM) ama toplam yol > 10 NM ise -> oval/dairesel rota.
    """
    if not track or len(track) < 6:
        return None
    pts = track[-10:]  # son 10 nokta
    start = pts[0]
    end = pts[-1]
    closure = haversine_nm(start[0], start[1], end[0], end[1])

    total_dist = 0.0
    for i in range(1, len(pts)):
        total_dist += haversine_nm(pts[i-1][0], pts[i-1][1], pts[i][0], pts[i][1])

    if closure < 5 and total_dist > 8 and total_dist / max(0.1, closure) > 3:
        # Donus yonu - bearing degisimi toplami
        delta_total = 0
        for i in range(2, len(pts)):
            b1 = bearing(pts[i-2][0], pts[i-2][1], pts[i-1][0], pts[i-1][1])
            b2 = bearing(pts[i-1][0], pts[i-1][1], pts[i][0], pts[i][1])
            dd = ((b2 - b1 + 180) % 360) - 180
            delta_total += dd
        turn_dir = 'right' if delta_total > 0 else 'left'
        return {
            'pattern': 'holding',
            'turn': turn_dir,
            'closure_nm': round(closure, 1),
            'total_nm': round(total_dist, 1),
        }
    return None


# ============== WIND ESTIMATE ==============
def estimate_wind(speed_gs: float | None, heading_gs: float | None,
                  tas: float | None, mag_heading: float | None
                  ) -> dict | None:
    """GS vektoru ile TAS vektorunden ruzgar hesabi.

    wind = GS - TAS (vector). 'heading' verisi yon farki olabilir cunku
    mag heading + magnetic variation = true heading. Hata payi var.
    """
    if any(x is None for x in (speed_gs, heading_gs, tas, mag_heading)):
        return None
    # Ground speed vektor
    g_rad = math.radians(heading_gs)
    gx = speed_gs * math.sin(g_rad)
    gy = speed_gs * math.cos(g_rad)
    # Air vector (TAS magnetic heading'i true gibi kabul - mag.var ihmal)
    t_rad = math.radians(mag_heading)
    tx = tas * math.sin(t_rad)
    ty = tas * math.cos(t_rad)
    # Wind = ground - air
    wx = gx - tx
    wy = gy - ty
    wind_speed = math.hypot(wx, wy)
    wind_from = (math.degrees(math.atan2(-wx, -wy)) + 360) % 360
    # Cok dusuk farkta gurultu
    if wind_speed > 200 or wind_speed < 0:
        return None
    return {
        'wind_speed': round(wind_speed),
        'wind_from': round(wind_from),
    }


# ============== ROUTE PREDICTION ==============
def predict_route(lat: float, lon: float, speed_kt: float,
                  heading_deg: float, minutes_ahead: int = 10,
                  step_min: int = 1) -> list:
    """Konum, hiz, heading'ten N dakika sonraki konumlari uret.

    Sabit hiz/heading varsayimi (Kalman degil). Great circle yaklasik.
    """
    if any(x is None for x in (lat, lon, speed_kt, heading_deg)):
        return []
    pts = [[lat, lon]]
    r = math.radians(heading_deg)
    for m in range(step_min, minutes_ahead + 1, step_min):
        d_nm = speed_kt * (m / 60.0)
        dlat = d_nm * math.cos(r) / 60.0
        dlon = d_nm * math.sin(r) / (60.0 * math.cos(math.radians(lat)))
        pts.append([lat + dlat, lon + dlon])
    return pts


# ============== ML CALLSIGN COMPLETION ==============
# Cok basit pattern: callsign'da rakam 4 hane bekleniyor;
# yakin gecmiste benzer prefix gormussek varsayilan format kullan.
_seen_patterns: dict[str, set[str]] = {}  # ICAO prefix -> {gorulmus callsign'lar}


def remember_callsign(icao: str, callsign: str) -> None:
    if not icao or not callsign or len(callsign) < 3:
        return
    cs_prefix = callsign[:3].upper()
    if cs_prefix not in _seen_patterns:
        _seen_patterns[cs_prefix] = set()
    _seen_patterns[cs_prefix].add(callsign.upper())


def guess_callsign(icao: str, partial: str) -> str | None:
    """Eksik veya parcaln callsign'da pattern match."""
    if not partial or len(partial) < 2:
        return None
    pref = partial[:3].upper()
    if pref not in _seen_patterns:
        return None
    candidates = [c for c in _seen_patterns[pref] if c.startswith(partial.upper())]
    if len(candidates) == 1:
        return candidates[0]
    return None


# ============== TRACKER ENRICHMENT ==============
def enrich_aircraft(ac_dict: dict, track: list) -> dict:
    """Bir aircraft snapshot'una analitik alanlar ekle."""
    hp = detect_holding(track) if track else None
    if hp:
        ac_dict['holding'] = hp
    if all(ac_dict.get(k) is not None for k in ('speed', 'heading', 'tas', 'mag_heading')):
        w = estimate_wind(ac_dict['speed'], ac_dict['heading'],
                          ac_dict['tas'], ac_dict['mag_heading'])
        if w:
            ac_dict['wind'] = w
    if (ac_dict.get('lat') is not None and ac_dict.get('speed')
            and ac_dict.get('heading') is not None):
        ac_dict['predicted_route'] = predict_route(
            ac_dict['lat'], ac_dict['lon'],
            ac_dict['speed'], ac_dict['heading'], 10, 2)
    return ac_dict
