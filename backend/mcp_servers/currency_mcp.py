"""
Currency MCP — ExchangeRate-API v6
Docs: https://www.exchangerate-api.com/docs/overview
FREE: 1,500 requests/month. Key: exchangerate-api.com
"""
import os, time
from .base_mcp   import BaseMCP
from .http_client import get

BASE_URL = "https://v6.exchangerate-api.com/v6"

# Destination currency map — IATA → (currency_code, currency_name, symbol)
DEST_CURRENCIES = {
    "LIS":"EUR","OPO":"EUR","FAO":"EUR","BCN":"EUR","MAD":"EUR","AGP":"EUR",
    "TFS":"EUR","PMI":"EUR","IBZ":"EUR","LPA":"EUR","ACE":"EUR","FUE":"EUR",
    "SVQ":"EUR","VLC":"EUR","FCO":"EUR","MXP":"EUR","VCE":"EUR","NAP":"EUR",
    "CDG":"EUR","NCE":"EUR","MRS":"EUR","AMS":"EUR","BRU":"EUR","ZRH":"CHF",
    "GVA":"CHF","VIE":"EUR","MUC":"EUR","FRA":"EUR","BER":"EUR","ATH":"EUR",
    "JTR":"EUR","HER":"EUR","CFU":"EUR","RHO":"EUR","JMK":"EUR","CPH":"DKK",
    "ARN":"SEK","OSL":"NOK","HEL":"EUR","KEF":"ISK","PRG":"CZK","WAW":"PLN",
    "BUD":"HUF","DUB":"EUR","IST":"TRY","LCA":"EUR","MLA":"EUR","DBV":"EUR",
    "DXB":"AED","AUH":"AED","SHJ":"AED","DOH":"QAR","RUH":"SAR","JED":"SAR",
    "CAI":"EGP","CMN":"MAD","RAK":"MAD","TUN":"TND","NBO":"KES","JNB":"ZAR",
    "CPT":"ZAR","MRU":"MUR","SEZ":"SCR","KGL":"RWF","DAR":"TZS","ADD":"ETB",
    "SIN":"SGD","NRT":"JPY","KIX":"JPY","HKG":"HKD","ICN":"KRW",
    "PEK":"CNY","PVG":"CNY","BKK":"THB","HKT":"THB","DPS":"IDR","CGK":"IDR",
    "KUL":"MYR","MNL":"PHP","SGN":"VND","HAN":"VND","CMB":"LKR","MLE":"USD",
    "DEL":"INR","BOM":"INR","BLR":"INR","GOI":"INR","KHI":"PKR","DAC":"BDT",
    "SYD":"AUD","MEL":"AUD","BNE":"AUD","PER":"AUD","AKL":"NZD",
    "JFK":"USD","LAX":"USD","MIA":"USD","ORD":"USD","SFO":"USD","YYZ":"CAD",
    "YVR":"CAD","MEX":"MXN","CUN":"MXN","GIG":"BRL","GRU":"BRL",
    "EZE":"ARS","SCL":"CLP","LIM":"PEN","BOG":"COP","HNL":"USD",
    "NAN":"FJD","PPT":"XPF","BOB":"XPF",
}

CURRENCY_INFO = {
    "EUR":("Euro","€"),"GBP":("British Pound","£"),"USD":("US Dollar","$"),
    "CHF":("Swiss Franc","Fr"),"JPY":("Japanese Yen","¥"),"AED":("UAE Dirham","د.إ"),
    "SGD":("Singapore Dollar","S$"),"AUD":("Australian Dollar","A$"),
    "CAD":("Canadian Dollar","C$"),"NZD":("New Zealand Dollar","NZ$"),
    "HKD":("Hong Kong Dollar","HK$"),"THB":("Thai Baht","฿"),
    "IDR":("Indonesian Rupiah","Rp"),"MYR":("Malaysian Ringgit","RM"),
    "INR":("Indian Rupee","₹"),"PKR":("Pakistani Rupee","₨"),
    "ZAR":("South African Rand","R"),"KES":("Kenyan Shilling","KSh"),
    "MUR":("Mauritian Rupee","₨"),"SCR":("Seychellois Rupee","₨"),
    "MAD":("Moroccan Dirham","MAD"),"EGP":("Egyptian Pound","E£"),
    "TRY":("Turkish Lira","₺"),"QAR":("Qatari Riyal","QR"),
    "SAR":("Saudi Riyal","SR"),"KRW":("South Korean Won","₩"),
    "CNY":("Chinese Yuan","¥"),"TWD":("Taiwan Dollar","NT$"),
    "PHP":("Philippine Peso","₱"),"VND":("Vietnamese Dong","₫"),
    "LKR":("Sri Lankan Rupee","₨"),"BDT":("Bangladeshi Taka","৳"),
    "DKK":("Danish Krone","kr"),"SEK":("Swedish Krona","kr"),
    "NOK":("Norwegian Krone","kr"),"CZK":("Czech Koruna","Kč"),
    "PLN":("Polish Złoty","zł"),"HUF":("Hungarian Forint","Ft"),
    "ISK":("Icelandic Króna","kr"),"MXN":("Mexican Peso","$"),
    "BRL":("Brazilian Real","R$"),"ARS":("Argentine Peso","$"),
    "CLP":("Chilean Peso","$"),"PEN":("Peruvian Sol","S/"),
    "COP":("Colombian Peso","$"),"FJD":("Fijian Dollar","FJ$"),
    "XPF":("CFP Franc","F"),"MXN":("Mexican Peso","$"),
    "KWD":("Kuwaiti Dinar","KD"),"OMR":("Omani Rial","OMR"),
    "BHD":("Bahraini Dinar","BD"),"JOD":("Jordanian Dinar","JD"),
    "RWF":("Rwandan Franc","FRw"),"TZS":("Tanzanian Shilling","TSh"),
    "ETB":("Ethiopian Birr","Br"),"UGX":("Ugandan Shilling","USh"),
}

# Fallback rates (GBP base, updated quarterly)
FALLBACK_GBP = {
    "EUR":1.175,"USD":1.272,"CHF":1.112,"JPY":192.5,"AED":4.672,
    "SGD":1.718,"AUD":1.967,"CAD":1.758,"NZD":2.143,"HKD":9.921,
    "THB":46.2,"IDR":20450,"MYR":6.01,"INR":106.3,"ZAR":23.8,
    "KES":165.4,"MUR":57.2,"MAD":12.8,"EGP":62.4,"TRY":43.5,
    "QAR":4.630,"SAR":4.774,"KRW":1748,"CNY":9.237,"PHP":72.4,
    "VND":31680,"LKR":390.2,"PKR":354.5,"BDT":140.2,"DKK":8.761,
    "SEK":13.63,"NOK":13.78,"CZK":29.47,"PLN":5.062,"HUF":458.2,
    "ISK":176.3,"MXN":22.17,"BRL":7.218,"ARS":1241,"CLP":1186,
    "PEN":4.741,"COP":5128,"FJD":2.921,"XPF":140.2,"SCR":18.4,
    "RWF":1802,"TZS":3312,"ETB":148.5,
}


class CurrencyMCP(BaseMCP):
    def __init__(self): super().__init__(ttl=3600)

    def _fetch(self, params: dict) -> dict:
        base   = params.get("base","GBP").upper()
        target = params.get("target","EUR").upper()
        amount = float(params.get("amount", 1000))
        dest   = params.get("destination_iata","")

        # Auto-detect target currency from destination using ReferenceCache
        if dest:
            try:
                from core.reference_cache import ref
                detected = ref.iata_to_currency(dest.upper())
                if detected:
                    target = detected
            except Exception:
                if dest.upper() in DEST_CURRENCIES:
                    target = DEST_CURRENCIES[dest.upper()]

        api_key = os.getenv("EXCHANGERATE_API_KEY","").strip()

        if api_key:
            live = self._live(api_key, base, target, amount)
            if live:
                return live

        return self._fallback(base, target, amount)

    def _live(self, api_key, base, target, amount):
        try:
            r = get(f"{BASE_URL}/{api_key}/pair/{base}/{target}/{amount}",
                    timeout=5)
            if r and r.ok:
                d = r.json()
                if d.get("result") == "success":
                    rate   = d["conversion_rate"]
                    conv   = d["conversion_result"]
                    t_name, t_sym = CURRENCY_INFO.get(target, (target,""))
                    b_name, b_sym = CURRENCY_INFO.get(base,   (base,""))
                    return {"data":{
                        "base":          base,
                        "base_name":     b_name,
                        "base_symbol":   b_sym,
                        "target":        target,
                        "target_name":   t_name,
                        "target_symbol": t_sym,
                        "rate":          round(rate,4),
                        "amount":        amount,
                        "converted":     round(conv,2),
                        "inverse":       round(1/rate,4) if rate else 0,
                        "tip":           f"{b_sym}{amount:.0f} = {t_sym}{conv:.0f} {t_name}",
                        "atm_tip":       "Withdraw local currency at airport ATM on arrival for best rates. Avoid exchange bureaus in tourist areas.",
                        "card_tip":      "Use a fee-free travel card (Wise, Revolut) to avoid forex charges.",
                        "updated":       d.get("time_last_update_utc","")[:16],
                        "source":        "exchangerate_api_live",
                    }}
        except Exception as e:
            self._log.debug("ExchangeRate-API error: %s", e)
        return None

    def _fallback(self, base, target, amount):
        # Use ReferenceCache rates (from reference_data.py GBP_FALLBACK_RATES)
        try:
            from core.reference_cache import ref
            def _rate(code): return ref.gbp_rate(code) if code != "GBP" else 1.0
        except Exception:
            def _rate(code): return FALLBACK_GBP.get(code, 1.0)

        if base == "GBP":
            rate = _rate(target)
        elif target == "GBP":
            rate = 1.0 / max(_rate(base), 0.00001)
        else:
            gbp_to_base   = _rate(base)
            gbp_to_target = _rate(target)
            rate = gbp_to_target / max(gbp_to_base, 0.00001)

        # Daily variation ±0.5%
        seed = hash(str(time.gmtime().tm_yday)) % 100
        rate = round(rate * (1 + (seed-50)/10000), 4)
        conv = round(amount * rate, 2)

        try:
            from core.reference_cache import ref
            t_info = ref.currency(target) or {}
            b_info = ref.currency(base) or {}
            t_name = t_info.get("name", target)
            t_sym  = t_info.get("symbol", "")
            b_name = b_info.get("name", base)
            b_sym  = b_info.get("symbol", "")
        except Exception:
            t_name, t_sym = CURRENCY_INFO.get(target, (target,""))
            b_name, b_sym = CURRENCY_INFO.get(base,   (base,""))
        return {"data":{
            "base":b_name,"base_symbol":b_sym,"target":target,
            "target_name":t_name,"target_symbol":t_sym,
            "rate":rate,"amount":amount,"converted":conv,
            "inverse":round(1/rate,4),
            "tip":f"{b_sym}{amount:.0f} ≈ {t_sym}{conv:.0f} {t_name} (indicative)",
            "atm_tip":"Use a no-fee card. Avoid airport exchange bureaus.",
            "card_tip":"Wise or Revolut cards give mid-market rates.",
            "source":"indicative",
        }}

    def _score_confidence(self, r):
        src = r.get("data",{}).get("source","")
        return 0.99 if "live" in src else 0.82
