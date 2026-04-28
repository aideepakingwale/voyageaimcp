"""
VoyageAI Reference Cache
=========================
Singleton built once at application startup.
Load order:  DB (ref_* tables) → Python dicts (reference_data.py) → empty

Usage:
    from core.reference_cache import ref

    ref.is_airport("DXB")             True
    ref.is_currency("AED")            True
    ref.is_country_code("AE")         True
    ref.should_validate_as_iata("UAE") False  (country abbrev, not airport)
    ref.airport("DXB")                {"name":"Dubai International","city":"Dubai",...}
    ref.currency("AED")               {"name":"UAE Dirham","symbol":"\u062f.\u0625",...}
    ref.country("AE")                 {"name":"United Arab Emirates","currency":"AED",...}
    ref.city_to_iata("dubai")         "DXB"
    ref.iata_to_currency("DXB")       "AED"
    ref.iata_to_country("DXB")        "AE"
    ref.gbp_rate("AED")               4.672
"""
import logging
import time
from typing import Optional

log = logging.getLogger("voyageai.app")

# Common 3-letter abbreviations that are NEVER airport codes
_NEVER_AIRPORT = frozenset([
    # ISO 4217 currency codes (3 letters)
    "GBP","EUR","USD","AED","SAR","QAR","KWD","OMR","BHD","JOD","ILS","EGP",
    "TRY","MAD","TND","DZD","ZAR","KES","TZS","UGX","ETB","NGN","GHS","MUR",
    "SCR","RWF","SGD","JPY","HKD","KRW","CNY","TWD","THB","IDR","MYR","PHP",
    "VND","KHR","LKR","MVR","NPR","PKR","BDT","INR","AUD","NZD","FJD","XPF",
    "CHF","NOK","SEK","DKK","ISK","CZK","PLN","HUF","RON","BGN","HRK","CAD",
    "MXN","BRL","ARS","CLP","PEN","COP","UAH","BYN","RUB","GEL","AMD","AZN",
    "KZT","UZS","ALL","BAM","MKD","RSD","MDL","MMK","LAK","MNT","XOF","XAF",
    "XCD","HTG","JMD","BBD","TTD","BSD","KYD","AWG","ANG","SRD","PYG","UYU",
    "BOB","NIO","GTQ","BZD","DOP","PAB","CRC","HNL","PGK","SBD","VUV","WST",
    "TOP","GNF","SLL","LRD","CVE","KMF","MGA","BMD","GMD","MRO","STN","DJF",
    "SOS","ERN","ZMW","ZWL","MWK","MZN","BWP","NAD","SZL","LSL","IRR","IQD",
    "SYP","AFN","YER","SSP","AOA","CDF","SDG","LYD","IRR",
    # 3-letter country/territory abbreviations (not IATA)
    "UAE","KSA","USA","GBR","CHN","JPN","KOR","AUS","NZL","IND","PAK","BGD",
    "LKA","THA","IDN","MYS","PHL","VNM","ZAF","KEN","TZA","ETH","NGA","GHA",
    "MAR","TUN","TUR","ISR","JOR","LBN","IRN","IRQ","SYR","YEM","FRA","DEU",
    "ITA","ESP","PRT","GRC","NLD","BEL","CHE","AUT","POL","CZE","HUN","ROU",
    "BGR","HRV","SRB","MNE","ALB","MKD","SVN","SVK","UKR","BLR","MDA","GEO",
    "ARM","AZR","KAZ","UZB","TKM","KGZ","TJK","MNG","LAO","KHM","BRN","TWN",
    "MAC","PNG","SLB","VUT","WSM","TON","KIR","TUV","NRU","FSM","PLW","COK",
    # Tech/business abbreviations
    "API","URL","PDF","CSS","LLM","MCP","RAG","GDS","ETA","VIP","TBC","TBD",
    "PRO","GDP","VAT","TAX","SLA","ROI","KPI","CRM","SRC","DST","DEP","ARR",
    "DUR","LEG","PAX","ADT","CHD","INF","AGT","OPT","MOD","NUM","REF","EST",
    "AVG","STD","MIN","MAX","GPS","ETD","ETB","MON","TUE","WED","THU","FRI",
    "SAT","SUN","JAN","FEB","MAR","APR","JUN","JUL","AUG","SEP","OCT","NOV",
    "DEC","ETE","GPS","PNR","GDS",
])


class ReferenceCache:
    """
    In-memory cache built from DB at startup.
    Primary source: ref_* SQLite tables.
    Fallback: data/reference_data.py Python dicts.
    """

    def __init__(self):
        self._built      = False
        self._build_time = 0.0
        self._source     = "empty"

        self._airports:   dict[str, dict] = {}
        self._currencies: dict[str, dict] = {}
        self._countries:  dict[str, dict] = {}
        self._gbp_rates:  dict[str, float] = {}

        self._airport_codes:  frozenset = frozenset()
        self._currency_codes: frozenset = frozenset()
        self._country_codes:  frozenset = frozenset()
        self._non_airport_3:  frozenset = frozenset()

        self._city_idx:      dict[str, str] = {}
        self._iata_currency: dict[str, str] = {}
        self._iata_country:  dict[str, str] = {}

    def build(self) -> "ReferenceCache":
        if self._built:
            return self
        t0 = time.perf_counter()
        try:
            if self._load_from_db():
                self._source = "database"
            else:
                self._load_from_python()
                self._source = "python_dicts"
            self._derive_indexes()
        except Exception as e:
            log.error("ReferenceCache build error: %s", e, exc_info=e)
        finally:
            elapsed = round((time.perf_counter() - t0) * 1000, 1)
            self._built      = True
            self._build_time = elapsed

        log.info(
            "ReferenceCache ready in %sms from %s — %d airports %d currencies "
            "%d countries %d city_aliases",
            self._build_time, self._source,
            len(self._airports), len(self._currencies),
            len(self._countries), len(self._city_idx),
        )
        print(f"  [RefCache] {len(self._airports)} airports  "
              f"{len(self._currencies)} currencies  "
              f"{len(self._countries)} countries  "
              f"{len(self._city_idx)} city aliases  "
              f"({self._build_time}ms from {self._source})")
        return self

    # ── DB load ───────────────────────────────────────────────

    def _load_from_db(self) -> bool:
        try:
            from pathlib import Path
            db_path = Path(__file__).parent.parent / "data" / "voyageai.db"
            if not db_path.exists():
                return False
            import sqlite3
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row

            # Check ref tables exist and have data
            try:
                n = conn.execute("SELECT COUNT(*) FROM ref_airports").fetchone()[0]
            except sqlite3.OperationalError:
                conn.close()
                return False
            if n == 0:
                conn.close()
                return False

            # Load airports
            for row in conn.execute("SELECT * FROM ref_airports"):
                self._airports[row["iata"]] = {
                    "name":         row["name"],
                    "city":         row["city"],
                    "country_code": row["country_code"],
                    "lat":          row["lat"],
                    "lon":          row["lon"],
                }

            # Load currencies
            for row in conn.execute("SELECT * FROM ref_currencies"):
                self._currencies[row["code"]] = {
                    "name":     row["name"],
                    "symbol":   row["symbol"],
                    "decimals": row["decimals"],
                }

            # Load countries
            for row in conn.execute("SELECT * FROM ref_countries"):
                self._countries[row["code"]] = {
                    "name":         row["name"],
                    "currency":     row["currency"],
                    "main_airport": row["main_airport"],
                }

            # Load city aliases (pre-built in DB)
            for row in conn.execute("SELECT alias, iata FROM ref_city_iata"):
                self._city_idx[row["alias"]] = row["iata"]

            # Load GBP rates
            for row in conn.execute("SELECT currency, rate FROM ref_gbp_rates"):
                self._gbp_rates[row["currency"]] = row["rate"]

            conn.close()
            return True

        except Exception as e:
            log.debug("DB load failed: %s", e)
            return False

    def _load_from_python(self):
        from data.reference_data import (
            AIRPORTS, CURRENCIES, COUNTRIES, GBP_FALLBACK_RATES
        )
        self._airports   = dict(AIRPORTS)
        self._currencies = dict(CURRENCIES)
        self._countries  = dict(COUNTRIES)
        self._gbp_rates  = dict(GBP_FALLBACK_RATES)

    def _derive_indexes(self):
        self._airport_codes  = frozenset(self._airports)
        self._currency_codes = frozenset(self._currencies)
        self._country_codes  = frozenset(self._countries)
        self._non_airport_3  = _NEVER_AIRPORT | (self._currency_codes - self._airport_codes)

        # City index (only if not already loaded from DB)
        if not self._city_idx:
            for iata, info in self._airports.items():
                city = info.get("city","")
                if city:
                    self._city_idx[city.lower()] = iata
                    nospace = city.lower().replace(" ","")
                    if nospace != city.lower():
                        self._city_idx[nospace] = iata
            for cc, info in self._countries.items():
                name    = info.get("name","").lower()
                airport = info.get("main_airport","")
                if name and airport:
                    self._city_idx[name] = airport

        # IATA → currency / country
        for iata, info in self._airports.items():
            cc = info.get("country_code","")
            if cc and cc in self._countries:
                self._iata_country[iata]  = cc
                self._iata_currency[iata] = self._countries[cc].get("currency","")

    # ── Public API ────────────────────────────────────────────

    def airport(self, iata: str) -> Optional[dict]:
        return self._airports.get(iata.upper())

    def currency(self, code: str) -> Optional[dict]:
        return self._currencies.get(code.upper())

    def country(self, cc: str) -> Optional[dict]:
        return self._countries.get(cc.upper())

    def is_airport(self, code: str) -> bool:
        return code.upper() in self._airport_codes

    def is_currency(self, code: str) -> bool:
        return code.upper() in self._currency_codes

    def is_country_code(self, code: str) -> bool:
        return code.upper() in self._country_codes

    def is_non_airport(self, code: str) -> bool:
        return code.upper() in self._non_airport_3

    def should_validate_as_iata(self, code: str) -> bool:
        c = code.upper()
        return (len(c) == 3 and c.isalpha()
                and c not in self._non_airport_3
                and c not in self._currency_codes)

    def city_to_iata(self, city: str) -> Optional[str]:
        return self._city_idx.get(city.lower().strip())

    def iata_to_currency(self, iata: str) -> Optional[str]:
        return self._iata_currency.get(iata.upper())

    def iata_to_country(self, iata: str) -> Optional[str]:
        return self._iata_country.get(iata.upper())

    def gbp_rate(self, currency: str) -> float:
        return self._gbp_rates.get(currency.upper(), 1.0)

    def all_airport_codes(self) -> frozenset:
        return self._airport_codes

    def all_currency_codes(self) -> frozenset:
        return self._currency_codes

    def stats(self) -> dict:
        return {
            "built":         self._built,
            "source":        self._source,
            "build_ms":      self._build_time,
            "airports":      len(self._airports),
            "currencies":    len(self._currencies),
            "countries":     len(self._countries),
            "city_aliases":  len(self._city_idx),
            "non_airport_3": len(self._non_airport_3),
        }


# Module-level singleton
ref = ReferenceCache()
