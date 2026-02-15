"""
Aircraft database - ICAO adresinden basit lookup.

Iki kaynak:
1. ICAO blok atamalari (ulkeye gore) - hard-coded ITU/ICAO Annex 10.
2. Callsign prefix -> operator/airline.

Daha sonra opsiyonel: FAA registry CSV (5M satir, ~600 MB), local downloadable.
"""

# ICAO 24-bit address -> ulke. (start, end, country, country_code)
# Kaynak: dump1090-fa, ICAO 9 Annex 10 Volume III.
ICAO_RANGES = [
    (0x004000, 0x0043FF, 'Zimbabwe', 'ZW'),
    (0x004400, 0x004FFF, 'Mozambique', 'MZ'),
    (0x008000, 0x00FFFF, 'South Africa', 'ZA'),
    (0x010000, 0x017FFF, 'Egypt', 'EG'),
    (0x018000, 0x01FFFF, 'Libya', 'LY'),
    (0x020000, 0x027FFF, 'Morocco', 'MA'),
    (0x028000, 0x02FFFF, 'Tunisia', 'TN'),
    (0x030000, 0x0303FF, 'Botswana', 'BW'),
    (0x032000, 0x032FFF, 'Burundi', 'BI'),
    (0x034000, 0x034FFF, 'Cameroon', 'CM'),
    (0x035000, 0x0353FF, 'Comoros', 'KM'),
    (0x036000, 0x036FFF, 'Congo', 'CG'),
    (0x038000, 0x038FFF, 'Cote d\'Ivoire', 'CI'),
    (0x03E000, 0x03EFFF, 'Gabon', 'GA'),
    (0x040000, 0x040FFF, 'Ethiopia', 'ET'),
    (0x042000, 0x042FFF, 'Equatorial Guinea', 'GQ'),
    (0x044000, 0x044FFF, 'Ghana', 'GH'),
    (0x046000, 0x046FFF, 'Guinea', 'GN'),
    (0x048000, 0x0483FF, 'Guinea-Bissau', 'GW'),
    (0x04A000, 0x04A3FF, 'Lesotho', 'LS'),
    (0x04C000, 0x04CFFF, 'Kenya', 'KE'),
    (0x050000, 0x050FFF, 'Liberia', 'LR'),
    (0x054000, 0x054FFF, 'Madagascar', 'MG'),
    (0x058000, 0x058FFF, 'Malawi', 'MW'),
    (0x05A000, 0x05A3FF, 'Maldives', 'MV'),
    (0x05C000, 0x05CFFF, 'Mali', 'ML'),
    (0x05E000, 0x05E3FF, 'Mauritania', 'MR'),
    (0x060000, 0x0603FF, 'Mauritius', 'MU'),
    (0x062000, 0x062FFF, 'Niger', 'NE'),
    (0x064000, 0x064FFF, 'Nigeria', 'NG'),
    (0x068000, 0x068FFF, 'Uganda', 'UG'),
    (0x06A000, 0x06A3FF, 'Qatar', 'QA'),
    (0x06C000, 0x06CFFF, 'Central African Republic', 'CF'),
    (0x06E000, 0x06EFFF, 'Rwanda', 'RW'),
    (0x070000, 0x070FFF, 'Senegal', 'SN'),
    (0x074000, 0x0743FF, 'Seychelles', 'SC'),
    (0x076000, 0x0763FF, 'Sierra Leone', 'SL'),
    (0x078000, 0x078FFF, 'Somalia', 'SO'),
    (0x07A000, 0x07A3FF, 'Eswatini', 'SZ'),
    (0x07C000, 0x07CFFF, 'Sudan', 'SD'),
    (0x080000, 0x080FFF, 'Tanzania', 'TZ'),
    (0x084000, 0x084FFF, 'Chad', 'TD'),
    (0x088000, 0x088FFF, 'Togo', 'TG'),
    (0x08A000, 0x08AFFF, 'Zambia', 'ZM'),
    (0x08C000, 0x08CFFF, 'DR Congo', 'CD'),
    (0x090000, 0x090FFF, 'Angola', 'AO'),
    (0x094000, 0x0943FF, 'Benin', 'BJ'),
    (0x096000, 0x0963FF, 'Cape Verde', 'CV'),
    (0x098000, 0x0983FF, 'Djibouti', 'DJ'),
    (0x09A000, 0x09AFFF, 'Gambia', 'GM'),
    (0x09C000, 0x09C3FF, 'Burkina Faso', 'BF'),
    (0x09E000, 0x09E3FF, 'Sao Tome and Principe', 'ST'),
    (0x0A0000, 0x0A7FFF, 'Algeria', 'DZ'),
    (0x0A8000, 0x0A8FFF, 'Bahamas', 'BS'),
    (0x0AA000, 0x0AA3FF, 'Barbados', 'BB'),
    (0x0AB000, 0x0AB3FF, 'Belize', 'BZ'),
    (0x0AC000, 0x0ACFFF, 'Colombia', 'CO'),
    (0x0AE000, 0x0AEFFF, 'Costa Rica', 'CR'),
    (0x0B0000, 0x0B0FFF, 'Cuba', 'CU'),
    (0x0B2000, 0x0B2FFF, 'El Salvador', 'SV'),
    (0x0B4000, 0x0B4FFF, 'Guatemala', 'GT'),
    (0x0B6000, 0x0B6FFF, 'Guyana', 'GY'),
    (0x0B8000, 0x0B8FFF, 'Haiti', 'HT'),
    (0x0BA000, 0x0BAFFF, 'Honduras', 'HN'),
    (0x0BC000, 0x0BC3FF, 'Saint Vincent', 'VC'),
    (0x0BE000, 0x0BEFFF, 'Jamaica', 'JM'),
    (0x0C0000, 0x0C0FFF, 'Nicaragua', 'NI'),
    (0x0C2000, 0x0C2FFF, 'Panama', 'PA'),
    (0x0C4000, 0x0C4FFF, 'Dominican Republic', 'DO'),
    (0x0C6000, 0x0C6FFF, 'Trinidad and Tobago', 'TT'),
    (0x0C8000, 0x0C8FFF, 'Suriname', 'SR'),
    (0x0CA000, 0x0CA3FF, 'Antigua and Barbuda', 'AG'),
    (0x0CC000, 0x0CC3FF, 'Grenada', 'GD'),
    (0x0D0000, 0x0D7FFF, 'Mexico', 'MX'),
    (0x0D8000, 0x0DFFFF, 'Venezuela', 'VE'),
    (0x100000, 0x1FFFFF, 'Russia', 'RU'),
    (0x201000, 0x2013FF, 'Namibia', 'NA'),
    (0x202000, 0x2023FF, 'Eritrea', 'ER'),
    (0x300000, 0x33FFFF, 'Italy', 'IT'),
    (0x340000, 0x37FFFF, 'Spain', 'ES'),
    (0x380000, 0x3BFFFF, 'France', 'FR'),
    (0x3C0000, 0x3FFFFF, 'Germany', 'DE'),
    (0x400000, 0x43FFFF, 'United Kingdom', 'GB'),
    (0x440000, 0x447FFF, 'Austria', 'AT'),
    (0x448000, 0x44FFFF, 'Belgium', 'BE'),
    (0x450000, 0x457FFF, 'Bulgaria', 'BG'),
    (0x458000, 0x45FFFF, 'Denmark', 'DK'),
    (0x460000, 0x467FFF, 'Finland', 'FI'),
    (0x468000, 0x46FFFF, 'Greece', 'GR'),
    (0x470000, 0x477FFF, 'Hungary', 'HU'),
    (0x478000, 0x47FFFF, 'Norway', 'NO'),
    (0x480000, 0x487FFF, 'Netherlands', 'NL'),
    (0x488000, 0x48FFFF, 'Poland', 'PL'),
    (0x490000, 0x497FFF, 'Portugal', 'PT'),
    (0x498000, 0x49FFFF, 'Czech Republic', 'CZ'),
    (0x4A0000, 0x4A7FFF, 'Romania', 'RO'),
    (0x4A8000, 0x4AFFFF, 'Sweden', 'SE'),
    (0x4B0000, 0x4B7FFF, 'Switzerland', 'CH'),
    (0x4B8000, 0x4BFFFF, 'Turkey', 'TR'),
    (0x4C0000, 0x4C7FFF, 'Yugoslavia (former)', 'YU'),
    (0x4C8000, 0x4C83FF, 'Cyprus', 'CY'),
    (0x4CA000, 0x4CAFFF, 'Ireland', 'IE'),
    (0x4CC000, 0x4CCFFF, 'Iceland', 'IS'),
    (0x4D0000, 0x4D03FF, 'Luxembourg', 'LU'),
    (0x4D2000, 0x4D23FF, 'Malta', 'MT'),
    (0x4D4000, 0x4D43FF, 'Monaco', 'MC'),
    (0x500000, 0x5003FF, 'San Marino', 'SM'),
    (0x501000, 0x5013FF, 'Albania', 'AL'),
    (0x502000, 0x5023FF, 'Croatia', 'HR'),
    (0x503000, 0x5033FF, 'Latvia', 'LV'),
    (0x504000, 0x5043FF, 'Lithuania', 'LT'),
    (0x505000, 0x5053FF, 'Moldova', 'MD'),
    (0x506000, 0x5063FF, 'Slovakia', 'SK'),
    (0x507000, 0x5073FF, 'Slovenia', 'SI'),
    (0x508000, 0x5083FF, 'Uzbekistan', 'UZ'),
    (0x509000, 0x5093FF, 'Ukraine', 'UA'),
    (0x50A000, 0x50A3FF, 'Belarus', 'BY'),
    (0x50B000, 0x50B3FF, 'Estonia', 'EE'),
    (0x50C000, 0x50C3FF, 'Macedonia', 'MK'),
    (0x50D000, 0x50D3FF, 'Bosnia and Herzegovina', 'BA'),
    (0x50E000, 0x50E3FF, 'Georgia', 'GE'),
    (0x50F000, 0x50F3FF, 'Tajikistan', 'TJ'),
    (0x600000, 0x6003FF, 'Armenia', 'AM'),
    (0x600800, 0x600BFF, 'Azerbaijan', 'AZ'),
    (0x601000, 0x6013FF, 'Kyrgyzstan', 'KG'),
    (0x602000, 0x6023FF, 'Turkmenistan', 'TM'),
    (0x680000, 0x6803FF, 'Bhutan', 'BT'),
    (0x681000, 0x6813FF, 'Federated States of Micronesia', 'FM'),
    (0x682000, 0x6823FF, 'Mongolia', 'MN'),
    (0x683000, 0x6833FF, 'Kazakhstan', 'KZ'),
    (0x684000, 0x6843FF, 'Palau', 'PW'),
    (0x700000, 0x700FFF, 'Afghanistan', 'AF'),
    (0x702000, 0x702FFF, 'Bangladesh', 'BD'),
    (0x704000, 0x704FFF, 'Myanmar', 'MM'),
    (0x706000, 0x706FFF, 'Kuwait', 'KW'),
    (0x708000, 0x708FFF, 'Laos', 'LA'),
    (0x70A000, 0x70AFFF, 'Nepal', 'NP'),
    (0x70C000, 0x70C3FF, 'Oman', 'OM'),
    (0x70E000, 0x70EFFF, 'Cambodia', 'KH'),
    (0x710000, 0x717FFF, 'Saudi Arabia', 'SA'),
    (0x718000, 0x71FFFF, 'South Korea', 'KR'),
    (0x720000, 0x727FFF, 'North Korea', 'KP'),
    (0x728000, 0x72FFFF, 'Iraq', 'IQ'),
    (0x730000, 0x737FFF, 'Iran', 'IR'),
    (0x738000, 0x73FFFF, 'Israel', 'IL'),
    (0x740000, 0x747FFF, 'Jordan', 'JO'),
    (0x748000, 0x74FFFF, 'Lebanon', 'LB'),
    (0x750000, 0x757FFF, 'Malaysia', 'MY'),
    (0x758000, 0x75FFFF, 'Philippines', 'PH'),
    (0x760000, 0x767FFF, 'Pakistan', 'PK'),
    (0x768000, 0x76FFFF, 'Singapore', 'SG'),
    (0x770000, 0x777FFF, 'Sri Lanka', 'LK'),
    (0x778000, 0x77FFFF, 'Syria', 'SY'),
    (0x780000, 0x7BFFFF, 'China', 'CN'),
    (0x7C0000, 0x7FFFFF, 'Australia', 'AU'),
    (0x800000, 0x83FFFF, 'India', 'IN'),
    (0x840000, 0x87FFFF, 'Japan', 'JP'),
    (0x880000, 0x887FFF, 'Thailand', 'TH'),
    (0x888000, 0x88FFFF, 'Viet Nam', 'VN'),
    (0x890000, 0x890FFF, 'Yemen', 'YE'),
    (0x894000, 0x894FFF, 'Bahrain', 'BH'),
    (0x895000, 0x8953FF, 'Brunei', 'BN'),
    (0x896000, 0x896FFF, 'United Arab Emirates', 'AE'),
    (0x898000, 0x898FFF, 'Solomon Islands', 'SB'),
    (0x899000, 0x8993FF, 'Papua New Guinea', 'PG'),
    (0x89A000, 0x89A3FF, 'Taiwan', 'TW'),
    (0x900000, 0x9003FF, 'Marshall Islands', 'MH'),
    (0x901000, 0x9013FF, 'Cook Islands', 'CK'),
    (0x902000, 0x9023FF, 'Samoa', 'WS'),
    (0xA00000, 0xAFFFFF, 'United States', 'US'),
    (0xC00000, 0xC3FFFF, 'Canada', 'CA'),
    (0xC80000, 0xC87FFF, 'New Zealand', 'NZ'),
    (0xC88000, 0xC88FFF, 'Fiji', 'FJ'),
    (0xC8A000, 0xC8A3FF, 'Nauru', 'NR'),
    (0xC8C000, 0xC8C3FF, 'Saint Lucia', 'LC'),
    (0xC8D000, 0xC8D3FF, 'Tonga', 'TO'),
    (0xC8E000, 0xC8E3FF, 'Kiribati', 'KI'),
    (0xC90000, 0xC903FF, 'Vanuatu', 'VU'),
    (0xE00000, 0xE3FFFF, 'Argentina', 'AR'),
    (0xE40000, 0xE7FFFF, 'Brazil', 'BR'),
    (0xE80000, 0xE80FFF, 'Chile', 'CL'),
    (0xE84000, 0xE84FFF, 'Ecuador', 'EC'),
    (0xE88000, 0xE88FFF, 'Paraguay', 'PY'),
    (0xE8C000, 0xE8CFFF, 'Peru', 'PE'),
    (0xE90000, 0xE90FFF, 'Uruguay', 'UY'),
    (0xE94000, 0xE94FFF, 'Bolivia', 'BO'),
]

# Callsign 3-letter prefix -> (operator name, country)
AIRLINE_PREFIX = {
    # Turkiye
    'THY': ('Turkish Airlines', 'TR'),
    'TUR': ('Turkish Cargo', 'TR'),
    'PGT': ('Pegasus', 'TR'),
    'SXS': ('SunExpress', 'TR'),
    'AJA': ('AnadoluJet', 'TR'),
    'CAI': ('Corendon', 'TR'),
    # UK
    'BAW': ('British Airways', 'GB'),
    'VIR': ('Virgin Atlantic', 'GB'),
    'EZY': ('easyJet', 'GB'),
    'TOM': ('TUI Airways', 'GB'),
    'JET2': ('Jet2', 'GB'),
    'CFE': ('BA Cityflyer', 'GB'),
    # Ireland
    'RYR': ('Ryanair', 'IE'),
    'EIN': ('Aer Lingus', 'IE'),
    # EU
    'EJU': ('easyJet Europe', 'AT'),
    'KLM': ('KLM', 'NL'),
    'AFR': ('Air France', 'FR'),
    'DLH': ('Lufthansa', 'DE'),
    'EWG': ('Eurowings', 'DE'),
    'SWR': ('Swiss', 'CH'),
    'AUA': ('Austrian', 'AT'),
    'IBE': ('Iberia', 'ES'),
    'VLG': ('Vueling', 'ES'),
    'AZA': ('ITA Airways', 'IT'),
    'AEE': ('Aegean', 'GR'),
    'TAP': ('TAP Portugal', 'PT'),
    'SAS': ('SAS', 'SE'),
    'FIN': ('Finnair', 'FI'),
    'LOT': ('LOT Polish', 'PL'),
    'CSA': ('CSA Czech', 'CZ'),
    'WZZ': ('Wizz Air', 'HU'),
    # US
    'AAL': ('American', 'US'),
    'UAL': ('United', 'US'),
    'DAL': ('Delta', 'US'),
    'SWA': ('Southwest', 'US'),
    'JBU': ('JetBlue', 'US'),
    'FFT': ('Frontier', 'US'),
    'NKS': ('Spirit', 'US'),
    'ASA': ('Alaska Airlines', 'US'),
    # Gulf
    'UAE': ('Emirates', 'AE'),
    'ETD': ('Etihad', 'AE'),
    'QTR': ('Qatar Airways', 'QA'),
    # Asia
    'CCA': ('Air China', 'CN'),
    'CES': ('China Eastern', 'CN'),
    'CSN': ('China Southern', 'CN'),
    'CPA': ('Cathay Pacific', 'HK'),
    'SIA': ('Singapore Airlines', 'SG'),
    'JAL': ('Japan Airlines', 'JP'),
    'ANA': ('All Nippon', 'JP'),
    'KAL': ('Korean Air', 'KR'),
    # business jet & charter
    'NJE': ('NetJets', 'PT'),
    'EJM': ('Executive Jet', 'US'),
    'GMI': ('Germania', 'DE'),
}


def lookup_country(icao: str) -> tuple[str | None, str | None]:
    """ICAO hex -> (country name, country code)."""
    try:
        n = int(icao, 16)
    except ValueError:
        return (None, None)
    # Binary search yapilabilir ama 150 entry ile linear yeterli
    for lo, hi, name, code in ICAO_RANGES:
        if lo <= n <= hi:
            return (name, code)
    return (None, None)


def lookup_operator(callsign: str) -> tuple[str | None, str | None]:
    """Callsign -> (operator, country code).
    Once 3 letter prefix, sonra 2 letter dener."""
    if not callsign or len(callsign) < 3:
        return (None, None)
    cs = callsign.upper()
    p3 = cs[:3]
    if p3 in AIRLINE_PREFIX:
        return AIRLINE_PREFIX[p3]
    return (None, None)


def enrich(ac_dict: dict) -> dict:
    """Aircraft dict'i ulke/operator bilgisi ile zenginlestir."""
    icao = ac_dict.get('icao')
    cs = ac_dict.get('callsign')
    if icao and not ac_dict.get('country'):
        name, code = lookup_country(icao)
        if name:
            ac_dict['country'] = name
            ac_dict['country_code'] = code
    if cs and not ac_dict.get('operator'):
        op, op_country = lookup_operator(cs)
        if op:
            ac_dict['operator'] = op
            if not ac_dict.get('country_code'):
                ac_dict['country_code'] = op_country
    return ac_dict
