"""
Currency MCP Server
PRIMARY:  ExchangeRate-API v6 (real-time mid-market rates)
FALLBACK: Static indicative rates with daily variation simulation
"""
import os, time
from .base_mcp    import BaseMCP
from .http_client import get

EXCHANGERATE_BASE = "https://v6.exchangerate-api.com/v6"

# Fallback rates (approx mid-market, update monthly if not using API)
FALLBACK_RATES = {
    ("GBP","EUR"):1.170, ("GBP","USD"):1.270, ("GBP","CHF"):1.110,
    ("GBP","JPY"):191.0, ("GBP","AED"):4.670, ("GBP","THB"):45.8,
    ("GBP","SGD"):1.710, ("GBP","AUD"):1.960, ("GBP","MYR"):5.970,
    ("GBP","INR"):105.0, ("GBP","MXN"):21.8,  ("GBP","BRL"):6.350,
    ("EUR","GBP"):0.855, ("EUR","USD"):1.085,  ("EUR","CHF"):0.950,
    ("USD","GBP"):0.787, ("USD","EUR"):0.922,  ("USD","JPY"):150.5,
}


class CurrencyMCP(BaseMCP):
    def __init__(self): super().__init__(ttl=3600)

    def _fetch(self, params: dict) -> dict:
        base   = params.get("base","GBP").upper()
        target = params.get("target","EUR").upper()
        amount = float(params.get("amount",1000))

        api_key = os.getenv("EXCHANGERATE_API_KEY","").strip()

        if api_key and api_key not in ("","demo","your_exchangerate_key_here"):
            live = self._live(api_key, base, target, amount)
            if live:
                return live

        return self._fallback(base, target, amount)

    def _live(self, api_key, base, target, amount):
        try:
            r = get(f"{EXCHANGERATE_BASE}/{api_key}/pair/{base}/{target}/{amount}",
                    timeout=5)
            if r.ok:
                d = r.json()
                if d.get("result") == "success":
                    rate      = d["conversion_rate"]
                    converted = d["conversion_result"]
                    return {"data":{
                        "base":      base,
                        "target":    target,
                        "rate":      rate,
                        "amount":    amount,
                        "converted": round(converted, 2),
                        "inverse":   round(1/rate, 4) if rate else 0,
                        "tip":       f"£1 = {target} {rate:.3f}. Your £{amount:.0f} budget ≈ {target} {converted:.0f}",
                        "source":    "exchangerate_live",
                        "updated":   d.get("time_last_update_utc",""),
                    }}
        except Exception:
            pass
        return None

    def _fallback(self, base, target, amount):
        import math
        rate = FALLBACK_RATES.get((base,target))
        if not rate:
            # Try to chain via GBP
            to_gbp   = FALLBACK_RATES.get((base,"GBP"), 1.0)
            from_gbp = FALLBACK_RATES.get(("GBP",target), 1.0)
            rate     = to_gbp * from_gbp

        # Add ±1% daily variation based on date hash
        day_seed = hash(str(time.gmtime().tm_yday)) % 200
        rate     = round(rate * (1 + (day_seed - 100) / 10000), 4)
        converted= round(amount * rate, 2)

        return {"data":{
            "base":      base,
            "target":    target,
            "rate":      rate,
            "amount":    amount,
            "converted": converted,
            "inverse":   round(1/rate, 4),
            "tip":       f"£1 ≈ {target} {rate:.3f}. £{amount:.0f} ≈ {target} {converted:.0f}. Indicative rate — check your bank.",
            "source":    "indicative",
        }}

    def _score_confidence(self, r):
        src = r.get("data",{}).get("source","")
        return 0.99 if "live" in src else 0.80
