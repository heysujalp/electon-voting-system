"""
ElectON v2 — Timezone service.
Displays as Country / City, searchable by country name.
Covers all IANA geographic zones without redundancy.
"""
from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo, available_timezones
import threading

# ────────────────────────────────────────────────────────
# Mapping: IANA zone ID → Country Name
# Comprehensive coverage of all major IANA geographic zones.
# LOW-13: TODO: Consider deriving this mapping programmatically using
# the `babel` library (babel.dates.get_timezone_location) to avoid
# maintaining a 250+ line hardcoded dictionary.
# ────────────────────────────────────────────────────────
IANA_TO_COUNTRY = {
    # ── Africa ──
    'Africa/Abidjan': "Côte d'Ivoire", 'Africa/Accra': 'Ghana',
    'Africa/Addis_Ababa': 'Ethiopia', 'Africa/Algiers': 'Algeria',
    'Africa/Asmara': 'Eritrea', 'Africa/Bamako': 'Mali',
    'Africa/Bangui': 'Central African Republic', 'Africa/Banjul': 'Gambia',
    'Africa/Bissau': 'Guinea-Bissau', 'Africa/Blantyre': 'Malawi',
    'Africa/Brazzaville': 'Congo', 'Africa/Bujumbura': 'Burundi',
    'Africa/Cairo': 'Egypt', 'Africa/Casablanca': 'Morocco',
    'Africa/Ceuta': 'Spain', 'Africa/Conakry': 'Guinea',
    'Africa/Dakar': 'Senegal', 'Africa/Dar_es_Salaam': 'Tanzania',
    'Africa/Djibouti': 'Djibouti', 'Africa/Douala': 'Cameroon',
    'Africa/El_Aaiun': 'Western Sahara', 'Africa/Freetown': 'Sierra Leone',
    'Africa/Gaborone': 'Botswana', 'Africa/Harare': 'Zimbabwe',
    'Africa/Johannesburg': 'South Africa', 'Africa/Juba': 'South Sudan',
    'Africa/Kampala': 'Uganda', 'Africa/Khartoum': 'Sudan',
    'Africa/Kigali': 'Rwanda', 'Africa/Kinshasa': 'DR Congo',
    'Africa/Lagos': 'Nigeria', 'Africa/Libreville': 'Gabon',
    'Africa/Lome': 'Togo', 'Africa/Luanda': 'Angola',
    'Africa/Lubumbashi': 'DR Congo', 'Africa/Lusaka': 'Zambia',
    'Africa/Malabo': 'Equatorial Guinea', 'Africa/Maputo': 'Mozambique',
    'Africa/Maseru': 'Lesotho', 'Africa/Mbabane': 'Eswatini',
    'Africa/Mogadishu': 'Somalia', 'Africa/Monrovia': 'Liberia',
    'Africa/Nairobi': 'Kenya', 'Africa/Ndjamena': 'Chad',
    'Africa/Niamey': 'Niger', 'Africa/Nouakchott': 'Mauritania',
    'Africa/Ouagadougou': 'Burkina Faso', 'Africa/Porto-Novo': 'Benin',
    'Africa/Sao_Tome': 'São Tomé and Príncipe', 'Africa/Tripoli': 'Libya',
    'Africa/Tunis': 'Tunisia', 'Africa/Windhoek': 'Namibia',

    # ── Americas ──
    'America/Adak': 'United States', 'America/Anchorage': 'United States',
    'America/Anguilla': 'Anguilla', 'America/Antigua': 'Antigua and Barbuda',
    'America/Araguaina': 'Brazil', 'America/Argentina/Buenos_Aires': 'Argentina',
    'America/Argentina/Catamarca': 'Argentina', 'America/Argentina/Cordoba': 'Argentina',
    'America/Argentina/Jujuy': 'Argentina', 'America/Argentina/La_Rioja': 'Argentina',
    'America/Argentina/Mendoza': 'Argentina', 'America/Argentina/Rio_Gallegos': 'Argentina',
    'America/Argentina/Salta': 'Argentina', 'America/Argentina/San_Juan': 'Argentina',
    'America/Argentina/San_Luis': 'Argentina', 'America/Argentina/Tucuman': 'Argentina',
    'America/Argentina/Ushuaia': 'Argentina', 'America/Aruba': 'Aruba',
    'America/Asuncion': 'Paraguay', 'America/Atikokan': 'Canada',
    'America/Bahia': 'Brazil', 'America/Bahia_Banderas': 'Mexico',
    'America/Barbados': 'Barbados', 'America/Belem': 'Brazil',
    'America/Belize': 'Belize', 'America/Blanc-Sablon': 'Canada',
    'America/Boa_Vista': 'Brazil', 'America/Bogota': 'Colombia',
    'America/Boise': 'United States', 'America/Cambridge_Bay': 'Canada',
    'America/Campo_Grande': 'Brazil', 'America/Cancun': 'Mexico',
    'America/Caracas': 'Venezuela', 'America/Cayenne': 'French Guiana',
    'America/Cayman': 'Cayman Islands', 'America/Chicago': 'United States',
    'America/Chihuahua': 'Mexico', 'America/Ciudad_Juarez': 'Mexico',
    'America/Costa_Rica': 'Costa Rica', 'America/Creston': 'Canada',
    'America/Cuiaba': 'Brazil', 'America/Curacao': 'Curaçao',
    'America/Danmarkshavn': 'Greenland', 'America/Dawson': 'Canada',
    'America/Dawson_Creek': 'Canada', 'America/Denver': 'United States',
    'America/Detroit': 'United States', 'America/Dominica': 'Dominica',
    'America/Edmonton': 'Canada', 'America/Eirunepe': 'Brazil',
    'America/El_Salvador': 'El Salvador', 'America/Fort_Nelson': 'Canada',
    'America/Fortaleza': 'Brazil', 'America/Glace_Bay': 'Canada',
    'America/Goose_Bay': 'Canada', 'America/Grand_Turk': 'Turks and Caicos',
    'America/Grenada': 'Grenada', 'America/Guadeloupe': 'Guadeloupe',
    'America/Guatemala': 'Guatemala', 'America/Guayaquil': 'Ecuador',
    'America/Guyana': 'Guyana', 'America/Halifax': 'Canada',
    'America/Havana': 'Cuba', 'America/Hermosillo': 'Mexico',
    'America/Indiana/Indianapolis': 'United States',
    'America/Indiana/Knox': 'United States', 'America/Indiana/Marengo': 'United States',
    'America/Indiana/Petersburg': 'United States', 'America/Indiana/Tell_City': 'United States',
    'America/Indiana/Vevay': 'United States', 'America/Indiana/Vincennes': 'United States',
    'America/Indiana/Winamac': 'United States', 'America/Inuvik': 'Canada',
    'America/Iqaluit': 'Canada', 'America/Jamaica': 'Jamaica',
    'America/Juneau': 'United States', 'America/Kentucky/Louisville': 'United States',
    'America/Kentucky/Monticello': 'United States', 'America/Kralendijk': 'Bonaire',
    'America/La_Paz': 'Bolivia', 'America/Lima': 'Peru',
    'America/Los_Angeles': 'United States', 'America/Lower_Princes': 'Sint Maarten',
    'America/Maceio': 'Brazil', 'America/Managua': 'Nicaragua',
    'America/Manaus': 'Brazil', 'America/Marigot': 'Saint Martin',
    'America/Martinique': 'Martinique', 'America/Matamoros': 'Mexico',
    'America/Mazatlan': 'Mexico', 'America/Menominee': 'United States',
    'America/Merida': 'Mexico', 'America/Metlakatla': 'United States',
    'America/Mexico_City': 'Mexico', 'America/Miquelon': 'Saint Pierre and Miquelon',
    'America/Moncton': 'Canada', 'America/Monterrey': 'Mexico',
    'America/Montevideo': 'Uruguay', 'America/Montserrat': 'Montserrat',
    'America/Nassau': 'Bahamas', 'America/New_York': 'United States',
    'America/Nome': 'United States', 'America/Noronha': 'Brazil',
    'America/North_Dakota/Beulah': 'United States',
    'America/North_Dakota/Center': 'United States',
    'America/North_Dakota/New_Salem': 'United States',
    'America/Nuuk': 'Greenland', 'America/Ojinaga': 'Mexico',
    'America/Panama': 'Panama', 'America/Paramaribo': 'Suriname',
    'America/Phoenix': 'United States', 'America/Port-au-Prince': 'Haiti',
    'America/Port_of_Spain': 'Trinidad and Tobago', 'America/Porto_Velho': 'Brazil',
    'America/Puerto_Rico': 'Puerto Rico', 'America/Punta_Arenas': 'Chile',
    'America/Rankin_Inlet': 'Canada', 'America/Recife': 'Brazil',
    'America/Regina': 'Canada', 'America/Resolute': 'Canada',
    'America/Rio_Branco': 'Brazil', 'America/Santarem': 'Brazil',
    'America/Santiago': 'Chile', 'America/Santo_Domingo': 'Dominican Republic',
    'America/Sao_Paulo': 'Brazil', 'America/Scoresbysund': 'Greenland',
    'America/Sitka': 'United States', 'America/St_Barthelemy': 'Saint Barthélemy',
    'America/St_Johns': 'Canada', 'America/St_Kitts': 'Saint Kitts and Nevis',
    'America/St_Lucia': 'Saint Lucia', 'America/St_Thomas': 'US Virgin Islands',
    'America/St_Vincent': 'Saint Vincent', 'America/Swift_Current': 'Canada',
    'America/Tegucigalpa': 'Honduras', 'America/Thule': 'Greenland',
    'America/Tijuana': 'Mexico', 'America/Toronto': 'Canada',
    'America/Tortola': 'British Virgin Islands', 'America/Vancouver': 'Canada',
    'America/Whitehorse': 'Canada', 'America/Winnipeg': 'Canada',
    'America/Yakutat': 'United States', 'America/Yellowknife': 'Canada',

    # ── Antarctica ──
    'Antarctica/Casey': 'Antarctica', 'Antarctica/Davis': 'Antarctica',
    'Antarctica/DumontDUrville': 'Antarctica', 'Antarctica/Macquarie': 'Australia',
    'Antarctica/Mawson': 'Antarctica', 'Antarctica/McMurdo': 'Antarctica',
    'Antarctica/Palmer': 'Antarctica', 'Antarctica/Rothera': 'Antarctica',
    'Antarctica/Syowa': 'Antarctica', 'Antarctica/Troll': 'Antarctica',
    'Antarctica/Vostok': 'Antarctica',

    # ── Arctic ──
    'Arctic/Longyearbyen': 'Norway',

    # ── Asia ──
    'Asia/Aden': 'Yemen', 'Asia/Almaty': 'Kazakhstan',
    'Asia/Amman': 'Jordan', 'Asia/Anadyr': 'Russia',
    'Asia/Aqtau': 'Kazakhstan', 'Asia/Aqtobe': 'Kazakhstan',
    'Asia/Ashgabat': 'Turkmenistan', 'Asia/Atyrau': 'Kazakhstan',
    'Asia/Baghdad': 'Iraq', 'Asia/Bahrain': 'Bahrain',
    'Asia/Baku': 'Azerbaijan', 'Asia/Bangkok': 'Thailand',
    'Asia/Barnaul': 'Russia', 'Asia/Beirut': 'Lebanon',
    'Asia/Bishkek': 'Kyrgyzstan', 'Asia/Brunei': 'Brunei',
    'Asia/Chita': 'Russia', 'Asia/Choibalsan': 'Mongolia',
    'Asia/Colombo': 'Sri Lanka', 'Asia/Damascus': 'Syria',
    'Asia/Dhaka': 'Bangladesh', 'Asia/Dili': 'Timor-Leste',
    'Asia/Dubai': 'United Arab Emirates', 'Asia/Dushanbe': 'Tajikistan',
    'Asia/Famagusta': 'Cyprus', 'Asia/Gaza': 'Palestine',
    'Asia/Hebron': 'Palestine', 'Asia/Ho_Chi_Minh': 'Vietnam',
    'Asia/Hong_Kong': 'Hong Kong', 'Asia/Hovd': 'Mongolia',
    'Asia/Irkutsk': 'Russia', 'Asia/Istanbul': 'Turkey',
    'Asia/Jakarta': 'Indonesia', 'Asia/Jayapura': 'Indonesia',
    'Asia/Jerusalem': 'Israel', 'Asia/Kabul': 'Afghanistan',
    'Asia/Kamchatka': 'Russia', 'Asia/Karachi': 'Pakistan',
    'Asia/Kathmandu': 'Nepal', 'Asia/Khandyga': 'Russia',
    'Asia/Kolkata': 'India', 'Asia/Krasnoyarsk': 'Russia',
    'Asia/Kuala_Lumpur': 'Malaysia', 'Asia/Kuching': 'Malaysia',
    'Asia/Kuwait': 'Kuwait', 'Asia/Macau': 'Macau',
    'Asia/Magadan': 'Russia', 'Asia/Makassar': 'Indonesia',
    'Asia/Manila': 'Philippines', 'Asia/Muscat': 'Oman',
    'Asia/Nicosia': 'Cyprus', 'Asia/Novokuznetsk': 'Russia',
    'Asia/Novosibirsk': 'Russia', 'Asia/Omsk': 'Russia',
    'Asia/Oral': 'Kazakhstan', 'Asia/Phnom_Penh': 'Cambodia',
    'Asia/Pontianak': 'Indonesia', 'Asia/Pyongyang': 'North Korea',
    'Asia/Qatar': 'Qatar', 'Asia/Qostanay': 'Kazakhstan',
    'Asia/Qyzylorda': 'Kazakhstan', 'Asia/Riyadh': 'Saudi Arabia',
    'Asia/Sakhalin': 'Russia', 'Asia/Samarkand': 'Uzbekistan',
    'Asia/Seoul': 'South Korea', 'Asia/Shanghai': 'China',
    'Asia/Singapore': 'Singapore', 'Asia/Srednekolymsk': 'Russia',
    'Asia/Taipei': 'Taiwan', 'Asia/Tashkent': 'Uzbekistan',
    'Asia/Tbilisi': 'Georgia', 'Asia/Tehran': 'Iran',
    'Asia/Thimphu': 'Bhutan', 'Asia/Tokyo': 'Japan',
    'Asia/Tomsk': 'Russia', 'Asia/Ulaanbaatar': 'Mongolia',
    'Asia/Urumqi': 'China', 'Asia/Ust-Nera': 'Russia',
    'Asia/Vientiane': 'Laos', 'Asia/Vladivostok': 'Russia',
    'Asia/Yakutsk': 'Russia', 'Asia/Yangon': 'Myanmar',
    'Asia/Yekaterinburg': 'Russia', 'Asia/Yerevan': 'Armenia',

    # ── Atlantic ──
    'Atlantic/Azores': 'Portugal', 'Atlantic/Bermuda': 'Bermuda',
    'Atlantic/Canary': 'Spain', 'Atlantic/Cape_Verde': 'Cape Verde',
    'Atlantic/Faroe': 'Faroe Islands', 'Atlantic/Madeira': 'Portugal',
    'Atlantic/Reykjavik': 'Iceland', 'Atlantic/South_Georgia': 'South Georgia',
    'Atlantic/St_Helena': 'Saint Helena', 'Atlantic/Stanley': 'Falkland Islands',

    # ── Australia ──
    'Australia/Adelaide': 'Australia', 'Australia/Brisbane': 'Australia',
    'Australia/Broken_Hill': 'Australia', 'Australia/Darwin': 'Australia',
    'Australia/Eucla': 'Australia', 'Australia/Hobart': 'Australia',
    'Australia/Lindeman': 'Australia', 'Australia/Lord_Howe': 'Australia',
    'Australia/Melbourne': 'Australia', 'Australia/Perth': 'Australia',
    'Australia/Sydney': 'Australia',

    # ── Europe ──
    'Europe/Amsterdam': 'Netherlands', 'Europe/Andorra': 'Andorra',
    'Europe/Astrakhan': 'Russia', 'Europe/Athens': 'Greece',
    'Europe/Belgrade': 'Serbia', 'Europe/Berlin': 'Germany',
    'Europe/Bratislava': 'Slovakia', 'Europe/Brussels': 'Belgium',
    'Europe/Bucharest': 'Romania', 'Europe/Budapest': 'Hungary',
    'Europe/Busingen': 'Germany', 'Europe/Chisinau': 'Moldova',
    'Europe/Copenhagen': 'Denmark', 'Europe/Dublin': 'Ireland',
    'Europe/Gibraltar': 'Gibraltar', 'Europe/Guernsey': 'Guernsey',
    'Europe/Helsinki': 'Finland', 'Europe/Isle_of_Man': 'Isle of Man',
    'Europe/Istanbul': 'Turkey', 'Europe/Jersey': 'Jersey',
    'Europe/Kaliningrad': 'Russia', 'Europe/Kirov': 'Russia',
    'Europe/Kyiv': 'Ukraine', 'Europe/Lisbon': 'Portugal',
    'Europe/Ljubljana': 'Slovenia', 'Europe/London': 'United Kingdom',
    'Europe/Luxembourg': 'Luxembourg', 'Europe/Madrid': 'Spain',
    'Europe/Malta': 'Malta', 'Europe/Mariehamn': 'Åland Islands',
    'Europe/Minsk': 'Belarus', 'Europe/Monaco': 'Monaco',
    'Europe/Moscow': 'Russia', 'Europe/Nicosia': 'Cyprus',
    'Europe/Oslo': 'Norway', 'Europe/Paris': 'France',
    'Europe/Podgorica': 'Montenegro', 'Europe/Prague': 'Czech Republic',
    'Europe/Riga': 'Latvia', 'Europe/Rome': 'Italy',
    'Europe/Samara': 'Russia', 'Europe/San_Marino': 'San Marino',
    'Europe/Sarajevo': 'Bosnia and Herzegovina', 'Europe/Saratov': 'Russia',
    'Europe/Simferopol': 'Ukraine', 'Europe/Skopje': 'North Macedonia',
    'Europe/Sofia': 'Bulgaria', 'Europe/Stockholm': 'Sweden',
    'Europe/Tallinn': 'Estonia', 'Europe/Tirane': 'Albania',
    'Europe/Ulyanovsk': 'Russia', 'Europe/Vaduz': 'Liechtenstein',
    'Europe/Vatican': 'Vatican City', 'Europe/Vienna': 'Austria',
    'Europe/Vilnius': 'Lithuania', 'Europe/Volgograd': 'Russia',
    'Europe/Warsaw': 'Poland', 'Europe/Zagreb': 'Croatia',
    'Europe/Zurich': 'Switzerland',

    # ── Indian ──
    'Indian/Antananarivo': 'Madagascar', 'Indian/Chagos': 'British Indian Ocean Territory',
    'Indian/Christmas': 'Christmas Island', 'Indian/Cocos': 'Cocos Islands',
    'Indian/Comoro': 'Comoros', 'Indian/Kerguelen': 'French Southern Territories',
    'Indian/Mahe': 'Seychelles', 'Indian/Maldives': 'Maldives',
    'Indian/Mauritius': 'Mauritius', 'Indian/Mayotte': 'Mayotte',
    'Indian/Reunion': 'Réunion',

    # ── Pacific ──
    'Pacific/Apia': 'Samoa', 'Pacific/Auckland': 'New Zealand',
    'Pacific/Bougainville': 'Papua New Guinea', 'Pacific/Chatham': 'New Zealand',
    'Pacific/Chuuk': 'Micronesia', 'Pacific/Easter': 'Chile',
    'Pacific/Efate': 'Vanuatu', 'Pacific/Fakaofo': 'Tokelau',
    'Pacific/Fiji': 'Fiji', 'Pacific/Funafuti': 'Tuvalu',
    'Pacific/Galapagos': 'Ecuador', 'Pacific/Gambier': 'French Polynesia',
    'Pacific/Guadalcanal': 'Solomon Islands', 'Pacific/Guam': 'Guam',
    'Pacific/Honolulu': 'United States', 'Pacific/Kanton': 'Kiribati',
    'Pacific/Kiritimati': 'Kiribati', 'Pacific/Kosrae': 'Micronesia',
    'Pacific/Kwajalein': 'Marshall Islands', 'Pacific/Majuro': 'Marshall Islands',
    'Pacific/Marquesas': 'French Polynesia', 'Pacific/Midway': 'US Minor Outlying Islands',
    'Pacific/Nauru': 'Nauru', 'Pacific/Niue': 'Niue',
    'Pacific/Norfolk': 'Norfolk Island', 'Pacific/Noumea': 'New Caledonia',
    'Pacific/Pago_Pago': 'American Samoa', 'Pacific/Palau': 'Palau',
    'Pacific/Pitcairn': 'Pitcairn Islands', 'Pacific/Pohnpei': 'Micronesia',
    'Pacific/Port_Moresby': 'Papua New Guinea', 'Pacific/Rarotonga': 'Cook Islands',
    'Pacific/Saipan': 'Northern Mariana Islands', 'Pacific/Tahiti': 'French Polynesia',
    'Pacific/Tarawa': 'Kiribati', 'Pacific/Tongatapu': 'Tonga',
    'Pacific/Wake': 'US Minor Outlying Islands', 'Pacific/Wallis': 'Wallis and Futuna',
}


class TimezoneService:
    """Timezone utilities — Country / City display format, searchable by country."""

    # BE-31: Use time-limited cache instead of permanent lru_cache
    # to avoid stale UTC offsets after DST transitions
    _tz_cache = None
    _tz_cache_time = 0
    _TZ_CACHE_TTL = 3600  # 1 hour
    _tz_lock = threading.Lock()  # Thread-safe cache access

    @staticmethod
    def get_timezone_choices() -> list[tuple[str, str]]:
        """
        Return a sorted list of (iana_id, display_label) tuples.

        Display format: (UTC±HH:MM) Country / City
        Value remains the IANA zone ID for backend compatibility.
        Filters out non-geographic and alias zones to avoid redundancy.
        Results are cached for 1 hour to stay fresh across DST transitions.
        """
        import time
        now_mono = time.monotonic()
        # Fast-path: cache hit (no lock needed for reads of immutable list)
        if (TimezoneService._tz_cache is not None
                and now_mono - TimezoneService._tz_cache_time < TimezoneService._TZ_CACHE_TTL):
            return TimezoneService._tz_cache

        with TimezoneService._tz_lock:
            # Double-checked locking: re-check after acquiring lock
            now_mono = time.monotonic()
            if (TimezoneService._tz_cache is not None
                    and now_mono - TimezoneService._tz_cache_time < TimezoneService._TZ_CACHE_TTL):
                return TimezoneService._tz_cache

            now = datetime.now(dt_timezone.utc)
            choices = []

            for tz_name in sorted(available_timezones()):
                # Skip non-geographic timezones
                if '/' not in tz_name or tz_name.startswith(('Etc/', 'SystemV/', 'US/')):
                    continue

                # Only include zones in our country map (canonical zones)
                country = IANA_TO_COUNTRY.get(tz_name)
                if not country:
                    continue

                try:
                    tz = ZoneInfo(tz_name)
                    offset = now.astimezone(tz).utcoffset()
                    total_seconds = int(offset.total_seconds())
                    hours, remainder = divmod(abs(total_seconds), 3600)
                    minutes = remainder // 60
                    sign = '+' if total_seconds >= 0 else '-'

                    # Extract city name from IANA path
                    parts = tz_name.split('/')
                    city = parts[-1].replace('_', ' ')

                    label = f"{country} / {city} (UTC{sign}{hours:02d}:{minutes:02d})"
                    choices.append((tz_name, label, country, city))
                except Exception:
                    continue

            # Sort alphabetically by country name, then by city name
            choices.sort(key=lambda x: (x[2].lower(), x[3].lower()))

            # Build final list (drop the sort keys)
            result = [(tz_name, label) for tz_name, label, _, _ in choices]

            # Add UTC at the top
            result.insert(0, ('UTC', 'UTC — Coordinated Universal Time (UTC+00:00)'))

            # Store in cache
            TimezoneService._tz_cache = result
            TimezoneService._tz_cache_time = now_mono

            return result

    @staticmethod
    def get_friendly_name(tz_name: str) -> str:
        """Get a friendly display name like 'Nepal / Kathmandu'."""
        country = IANA_TO_COUNTRY.get(tz_name)
        if country and '/' in tz_name:
            city = tz_name.split('/')[-1].replace('_', ' ')
            return f"{country} / {city}"
        if '/' in tz_name:
            return tz_name.split('/')[-1].replace('_', ' ')
        return tz_name