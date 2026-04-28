"""
VoyageAI Reference Cache
========================
Singleton built once at application startup from data/reference_data.py.
Provides O(1) lookups for airports, currencies, countries, cities.

Usage:
    from core.reference_cache import ref

    ref.is_airport("DXB")        → True
    ref.is_currency("AED")       → True
    ref.is_country_code("AE")    → True
    ref.is_non_airport("UAE")    → True   (3-letter but NOT an airport)
    ref.airport("DXB")           → {"name":"Dubai International","city":"Dubai",...}
    ref.currency("AED")          → {"name":"UAE Dirham","symbol":"د.إ",...}
    ref.country("AE")            → {"name":"United Arab Emirates","currency":"AED",...}
    ref.city_to_iata("dubai")    → "DXB"
    ref.iata_to_currency("DXB") → "AED"
    ref.iata_to_country("DXB")  → "AE"
    ref.gbp_rate("AED")         → 4.672
    ref.all_airport_codes()      → frozenset of all valid IATA codes
    ref.all_currency_codes()     → frozenset of all ISO 4217 codes
    ref.all_country_codes()      → frozenset of all ISO 3166-1 alpha-2 codes
    ref.all_non_airport_3char()  → frozenset of 3-letter codes that are NOT airports
"""
import logging
import time
from typing import Optional

log = logging.getLogger("voyageai.app")


class ReferenceCache:
    """
    Startup cache for all reference data.
    Built once, read many times.
    Thread-safe (immutable after build).
    """

    def __init__(self):
        self._built      = False
        self._build_time = 0.0

        # Primary stores (populated by build())
        self._airports:       dict[str, dict] = {}
        self._currencies:     dict[str, dict] = {}
        self._countries:      dict[str, dict] = {}
        self._gbp_rates:      dict[str, float] = {}

        # Derived fast-lookup sets
        self._airport_codes:  frozenset = frozenset()
        self._currency_codes: frozenset = frozenset()
        self._country_codes:  frozenset = frozenset()
        self._non_airport_3:  frozenset = frozenset()  # 3-letter codes that are NOT airports

        # City → IATA index (lowercase city name → IATA)
        self._city_idx:       dict[str, str] = {}
        # IATA → currency code
        self._iata_currency:  dict[str, str] = {}
        # IATA → country code
        self._iata_country:   dict[str, str] = {}

    def build(self) -> "ReferenceCache":
        """Build all caches from reference_data. Call once at startup."""
        if self._built:
            return self

        t0 = time.perf_counter()
        try:
            from data.reference_data import (
                AIRPORTS, CURRENCIES, COUNTRIES, GBP_FALLBACK_RATES
            )

            self._airports   = AIRPORTS
            self._currencies = CURRENCIES
            self._countries  = COUNTRIES
            self._gbp_rates  = GBP_FALLBACK_RATES

            # ── Derived sets ────────────────────────────────────
            self._airport_codes  = frozenset(AIRPORTS.keys())
            self._currency_codes = frozenset(CURRENCIES.keys())
            self._country_codes  = frozenset(COUNTRIES.keys())

            # 3-letter codes that could look like IATA but are not airports
            # Includes: all currency codes, all country codes (alpha-2 won't clash
            # with IATA since country codes are only 2 letters, but some abbreviations
            # like UAE/USA/AED might appear in JSON)
            self._non_airport_3 = frozenset(
                code for code in self._currency_codes
                if len(code) == 3 and code not in self._airport_codes
            ) | frozenset([
                # Common 3-letter abbreviations used in itinerary JSON
                # that are NOT airport codes
                "UAE","KSA","USA","GBR","CHN","JPN","KOR","AUS","NZL",
                "IND","PAK","BGD","LKA","THA","IDN","MYS","PHL","VNM",
                "ZAF","KEN","TZA","ETH","NGA","GHA","MAR","TUN","TUR",
                "ISR","JOR","LBN","IRN","IRQ","SYR","YEM","FRA","DEU",
                "ITA","ESP","PRT","GRC","NLD","BEL","CHE","AUT","POL",
                "CZE","HUN","ROU","BGR","HRV","SRB","MKD","MNE","ALB",
                # Tech/business abbreviations
                "API","URL","PDF","CSS","LLM","MCP","RAG","GDS","ETA",
                "VIP","TBC","TBD","PRO","GDP","VAT","TAX","SLA","ROI",
                "KPI","CRM","SRC","DST","DEP","ARR","DUR","LEG","PAX",
                "ADT","CHD","INF","AGT","OPT","MOD","NUM","REF","EST",
                "AVG","STD","MIN","MAX","GPS","ETD","ETB","MON","TUE",
                "WED","THU","FRI","SAT","SUN","JAN","FEB","MAR","APR",
                "JUN","JUL","AUG","SEP","OCT","NOV","DEC","ETA","ETE",
            ])

            # ── City → IATA index ────────────────────────────────
            for iata, info in AIRPORTS.items():
                city = info.get("city", "")
                if city:
                    self._city_idx[city.lower()] = iata
                    # Also index common variations
                    # "New York" → also index "newyork"
                    no_space = city.lower().replace(" ", "")
                    if no_space != city.lower():
                        self._city_idx[no_space] = iata
                # Index by airport name keywords
                name = info.get("name", "")
                if name:
                    self._city_idx[name.lower()] = iata

            # ── IATA → currency / country ────────────────────────
            for iata, info in AIRPORTS.items():
                cc = info.get("country_code", "")
                if cc and cc in COUNTRIES:
                    country = COUNTRIES[cc]
                    self._iata_country[iata]  = cc
                    self._iata_currency[iata] = country.get("currency", "")

            # ── Also build city_idx from country main airports ───
            for cc, info in COUNTRIES.items():
                name = info.get("name", "").lower()
                airport = info.get("main_airport", "")
                if name and airport:
                    self._city_idx[name] = airport

        except ImportError as e:
            log.error("ReferenceCache: reference_data.py not found: %s", e)
        except Exception as e:
            log.error("ReferenceCache build failed: %s", e, exc_info=e)
        finally:
            elapsed = round((time.perf_counter() - t0) * 1000, 1)
            self._built      = True
            self._build_time = elapsed

        log.info(
            "ReferenceCache built in %sms — %d airports, %d currencies, %d countries, %d city aliases",
            self._build_time,
            len(self._airports),
            len(self._currencies),
            len(self._countries),
            len(self._city_idx),
        )
        return self

    # ── Lookup methods ────────────────────────────────────────

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
        """True if this 3-letter code is a currency, country-name abbreviation or
        known abbreviation — i.e. should NOT be validated as an IATA airport code."""
        return code.upper() in self._non_airport_3

    def should_validate_as_iata(self, code: str) -> bool:
        """True only if this code could plausibly be an IATA airport code."""
        c = code.upper()
        # Must be 3 alphabetic chars, not a known non-airport code
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

    def all_country_codes(self) -> frozenset:
        return self._country_codes

    def all_non_airport_3char(self) -> frozenset:
        return self._non_airport_3

    def stats(self) -> dict:
        return {
            "built":           self._built,
            "build_ms":        self._build_time,
            "airports":        len(self._airports),
            "currencies":      len(self._currencies),
            "countries":       len(self._countries),
            "city_aliases":    len(self._city_idx),
            "non_airport_3":   len(self._non_airport_3),
        }


# ── Module-level singleton ────────────────────────────────────
ref = ReferenceCache()
