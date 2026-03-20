"""
Notable callsign / ICAO watchlist + alert.

Bilinen ozel ucaklar (askeri, VIP, Air Force One, vs.) tespiti.
Eslesirse Aircraft objesine 'notable' alani eklenir + frontend rozet.
"""

import re


# (regex pattern, label, kategori)
WATCHLIST = [
    # US askeri/VIP
    (r'^SAM\d+', 'SAM (US Air Force VIP)', 'vip'),
    (r'^AF1$|^AF2$', 'Air Force One/Two', 'vip'),
    (r'^EXEC1[A-Z]', 'Executive 1', 'vip'),
    (r'^MARINE\d+', 'Marine One', 'vip'),
    (r'^RCH\d+', 'US Air Mobility (RCH)', 'mil'),
    (r'^PAT\d+', 'US Army PAT', 'mil'),
    (r'^GTMO\d+', 'Guantanamo', 'mil'),
    # NATO
    (r'^NATO\d+', 'NATO', 'mil'),
    # Cargo/Charter
    (r'^TUR\d+', 'Turkish Cargo', 'cargo'),
    (r'^FDX\d+', 'FedEx', 'cargo'),
    (r'^UPS\d+', 'UPS', 'cargo'),
    (r'^DHL\d+', 'DHL', 'cargo'),
    # Test/Acil
    (r'^N\d+TF$', 'Test flight', 'test'),
    (r'^MEDIC\d+', 'Medical', 'medical'),
    (r'^LIFEGUARD', 'LifeGuard medical', 'medical'),
    # Royal/State (UK)
    (r'^KRF\d+', 'UK Royal Flight', 'vip'),
    (r'^KITTYHAWK', 'UK Cabinet', 'vip'),
]

# Squawk emergency
SQUAWK_EMERGENCY = {
    '7500': ('HIJACK', 'critical'),
    '7600': ('RADIO FAILURE', 'warning'),
    '7700': ('GENERAL EMERGENCY', 'critical'),
}


def check_callsign(callsign: str | None) -> dict | None:
    if not callsign:
        return None
    cs = callsign.strip().upper()
    for pattern, label, cat in WATCHLIST:
        if re.match(pattern, cs):
            return {'label': label, 'category': cat}
    return None


def check_squawk(squawk: str | None) -> dict | None:
    if not squawk:
        return None
    sq = str(squawk).strip()
    if sq in SQUAWK_EMERGENCY:
        label, severity = SQUAWK_EMERGENCY[sq]
        return {'label': label, 'severity': severity, 'squawk': sq}
    return None


def enrich(ac_dict: dict) -> dict:
    cs_notable = check_callsign(ac_dict.get('callsign'))
    if cs_notable:
        ac_dict['notable'] = cs_notable
    sq_emerg = check_squawk(ac_dict.get('squawk'))
    if sq_emerg:
        ac_dict['emergency'] = sq_emerg
    return ac_dict
