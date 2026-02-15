"""Tek bir ucagin durumu."""

import time
from dataclasses import dataclass, field, asdict


@dataclass
class Aircraft:
    icao: str
    callsign: str | None = None
    category: int | None = None
    lat: float | None = None
    lon: float | None = None
    altitude: int | None = None        # ft
    speed: float | None = None         # knots
    heading: float | None = None       # deg
    vertical_rate: int | None = None   # ft/min
    speed_type: str | None = None
    country: str | None = None
    squawk: str | None = None
    on_ground: bool | None = None
    # Aircraft DB lookup
    registration: str | None = None
    aircraft_type: str | None = None
    operator: str | None = None
    country_code: str | None = None
    # TC 31 OpStatus
    adsb_version: int | None = None
    nic: int | None = None
    nacp: int | None = None
    # BDS 4,0
    mcp_alt: int | None = None
    fms_alt: int | None = None
    baro_set: float | None = None
    # BDS 6,0
    mag_heading: float | None = None
    ias: int | None = None
    mach: float | None = None
    baro_rate: int | None = None
    inertial_rate: int | None = None
    # BDS 5,0 / track quality
    roll: float | None = None
    track_rate: float | None = None
    tas: float | None = None
    last_seen: float = field(default_factory=time.time)
    msg_count: int = 0

    last_pos_t: float | None = None    # son basarili pozisyon zamani

    # CPR cache
    even_lat_cpr: int | None = None
    even_lon_cpr: int | None = None
    even_t: float | None = None
    odd_lat_cpr: int | None = None
    odd_lon_cpr: int | None = None
    odd_t: float | None = None

    # Track gecmisi (en son N nokta) - [(lat, lon), ...]
    track: list = field(default_factory=list)
    TRACK_MAX_POINTS: int = 100

    def push_track(self, lat: float, lon: float) -> None:
        """Yeni konum ekle. Son nokta ile ayniysa skip."""
        if self.track:
            last_lat, last_lon = self.track[-1]
            if abs(last_lat - lat) < 1e-4 and abs(last_lon - lon) < 1e-4:
                return
        self.track.append((lat, lon))
        if len(self.track) > self.TRACK_MAX_POINTS:
            self.track = self.track[-self.TRACK_MAX_POINTS:]

    def to_dict(self) -> dict:
        d = asdict(self)
        # CPR cache UI'a gerek yok, temizle
        for k in ('even_lat_cpr', 'even_lon_cpr', 'even_t',
                  'odd_lat_cpr', 'odd_lon_cpr', 'odd_t',
                  'last_pos_t', 'TRACK_MAX_POINTS'):
            d.pop(k, None)
        # Country + operator zenginlestir (cheap lookup)
        from . import db
        db.enrich(d)
        return d
