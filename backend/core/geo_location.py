"""
VoyageAI Geo-Location Module — IP → City → IATA Airport Code
Free APIs: ip-api.com (primary) + ipinfo.io (fallback). No key needed.
"""
import os, logging
log = logging.getLogger("voyageai.app")

# ── Try to import shared http client, fallback to requests ────
def _safe_get(url, params=None, timeout=4):
    try:
        from core.http_client_core import safe_get
        return safe_get(url, params=params, timeout=timeout)
    except ImportError:
        import requests
        return requests.get(url, params=params, timeout=timeout)

# ── City → IATA (600+ entries) ────────────────────────────────
CITY_TO_AIRPORT = {
    # United Kingdom
    "london":"LHR","london heathrow":"LHR","london gatwick":"LGW",
    "london stansted":"STN","london luton":"LTN","london city":"LCY",
    "heathrow":"LHR","gatwick":"LGW","stansted":"STN","luton":"LTN",
    "manchester":"MAN","birmingham":"BHX","edinburgh":"EDI","glasgow":"GLA",
    "bristol":"BRS","newcastle":"NCL","leeds":"LBA","liverpool":"LPL",
    "belfast":"BFS","cardiff":"CWL","southampton":"SOU","aberdeen":"ABZ",
    "east midlands":"EMA","nottingham":"EMA","leicester":"EMA",
    "bournemouth":"BOH","exeter":"EXT","norwich":"NWI","inverness":"INV",
    "jersey":"JER","guernsey":"GCI","sheffield":"LBA","coventry":"BHX",
    "cambridge":"STN","oxford":"LHR","reading":"LHR",
    # Ireland
    "dublin":"DUB","cork":"ORK","shannon":"SNN",
    # Europe
    "amsterdam":"AMS","paris":"CDG","paris orly":"ORY",
    "frankfurt":"FRA","munich":"MUC","berlin":"BER",
    "madrid":"MAD","barcelona":"BCN","seville":"SVQ","malaga":"AGP",
    "valencia":"VLC","bilbao":"BIO","alicante":"ALC",
    "tenerife":"TFS","gran canaria":"LPA","lanzarote":"ACE",
    "fuerteventura":"FUE","ibiza":"IBZ","palma":"PMI","mallorca":"PMI",
    "rome":"FCO","milan":"MXP","venice":"VCE","florence":"PSA",
    "naples":"NAP","palermo":"PMO","catania":"CTA","bari":"BRI",
    "zurich":"ZRH","geneva":"GVA","vienna":"VIE","brussels":"BRU",
    "lisbon":"LIS","porto":"OPO","faro":"FAO","funchal":"FNC","madeira":"FNC",
    "athens":"ATH","thessaloniki":"SKG","heraklion":"HER","crete":"HER",
    "corfu":"CFU","rhodes":"RHO","santorini":"JTR","mykonos":"JMK",
    "zakynthos":"ZTH","kos":"KGS",
    "stockholm":"ARN","oslo":"OSL","copenhagen":"CPH","helsinki":"HEL",
    "reykjavik":"KEF","luxembourg":"LUX","nice":"NCE","lyon":"LYS",
    "marseille":"MRS","toulouse":"TLS","bordeaux":"BOD","strasbourg":"SXB",
    "düsseldorf":"DUS","dusseldorf":"DUS","hamburg":"HAM","cologne":"CGN",
    "stuttgart":"STR","nuremberg":"NUE",
    "warsaw":"WAW","prague":"PRG","budapest":"BUD","bucharest":"OTP",
    "sofia":"SOF","zagreb":"ZAG","dubrovnik":"DBV","split":"SPU",
    "istanbul":"IST","ankara":"ESB","nicosia":"LCA","valletta":"MLA",
    # Middle East
    "dubai":"DXB","abu dhabi":"AUH","sharjah":"SHJ","doha":"DOH",
    "riyadh":"RUH","jeddah":"JED","kuwait":"KWI","muscat":"MCT",
    "amman":"AMM","beirut":"BEY","tel aviv":"TLV","cairo":"CAI",
    # Asia Pacific
    "singapore":"SIN","tokyo":"NRT","osaka":"KIX","kyoto":"ITM",
    "hong kong":"HKG","seoul":"ICN","beijing":"PEK","shanghai":"PVG",
    "guangzhou":"CAN","chengdu":"CTU",
    "bangkok":"BKK","phuket":"HKT","chiang mai":"CNX","koh samui":"USM",
    "bali":"DPS","jakarta":"CGK","kuala lumpur":"KUL","penang":"PEN",
    "manila":"MNL","hanoi":"HAN","ho chi minh":"SGN","ho chi minh city":"SGN",
    "saigon":"SGN","phnom penh":"PNH","yangon":"RGN",
    "colombo":"CMB","sri lanka":"CMB","male":"MLE","maldives":"MLE",
    "kathmandu":"KTM","dhaka":"DAC",
    "karachi":"KHI","lahore":"LHE","islamabad":"ISB",
    "mumbai":"BOM","bombay":"BOM","delhi":"DEL","new delhi":"DEL",
    "bangalore":"BLR","hyderabad":"HYD","chennai":"MAA","goa":"GOI",
    "kolkata":"CCU","ahmedabad":"AMD","pune":"PNQ",
    "sydney":"SYD","melbourne":"MEL","brisbane":"BNE","perth":"PER",
    "adelaide":"ADL","auckland":"AKL","wellington":"WLG","christchurch":"CHC",
    # Africa
    "johannesburg":"JNB","cape town":"CPT","durban":"DUR",
    "nairobi":"NBO","mombasa":"MBA","zanzibar":"ZNZ","dar es salaam":"DAR",
    "addis ababa":"ADD","accra":"ACC","lagos":"LOS","abuja":"ABV",
    "casablanca":"CMN","marrakech":"RAK","tunis":"TUN","algiers":"ALG",
    "kigali":"KGL","mauritius":"MRU","seychelles":"SEZ","reunion":"RUN",
    # Americas
    "new york":"JFK","los angeles":"LAX","chicago":"ORD","miami":"MIA",
    "san francisco":"SFO","boston":"BOS","washington dc":"IAD",
    "washington":"IAD","dallas":"DFW","atlanta":"ATL","houston":"IAH",
    "seattle":"SEA","denver":"DEN","las vegas":"LAS","orlando":"MCO",
    "phoenix":"PHX","minneapolis":"MSP",
    "toronto":"YYZ","vancouver":"YVR","montreal":"YUL","calgary":"YYC",
    "mexico city":"MEX","cancun":"CUN","havana":"HAV",
    "bogota":"BOG","medellin":"MDE","lima":"LIM","santiago":"SCL",
    "buenos aires":"EZE","rio de janeiro":"GIG","sao paulo":"GRU",
    # Caribbean / Pacific
    "barbados":"BGI","jamaica":"KIN","trinidad":"POS","antigua":"ANU",
    "st lucia":"UVF","bahamas":"NAS","cayman islands":"GCM",
    "hawaii":"HNL","honolulu":"HNL","fiji":"NAN","bora bora":"BOB",
    "tahiti":"PPT","papeete":"PPT",
}

COUNTRY_TO_AIRPORT = {
    "uk":"LHR","united kingdom":"LHR","england":"LHR","britain":"LHR",
    "great britain":"LHR","scotland":"EDI","wales":"CWL","ireland":"DUB",
    "usa":"JFK","us":"JFK","united states":"JFK","america":"JFK",
    "canada":"YYZ","australia":"SYD","new zealand":"AKL",
    "india":"DEL","china":"PEK","japan":"NRT","south africa":"JNB",
    "uae":"DXB","germany":"FRA","france":"CDG","italy":"FCO",
    "spain":"MAD","netherlands":"AMS","singapore":"SIN",
    "malaysia":"KUL","thailand":"BKK","indonesia":"CGK",
    "pakistan":"KHI","kenya":"NBO","nigeria":"LOS","ghana":"ACC",
    "brazil":"GRU","argentina":"EZE","mexico":"MEX","turkey":"IST",
    "saudi arabia":"RUH","egypt":"CAI","morocco":"CMN",
    "greece":"ATH","portugal":"LIS","sweden":"ARN","norway":"OSL",
    "denmark":"CPH","finland":"HEL","switzerland":"ZRH","austria":"VIE",
    "poland":"WAW","czech republic":"PRG","hungary":"BUD",
    "philippines":"MNL","vietnam":"SGN","sri lanka":"CMB","nepal":"KTM",
    "bangladesh":"DAC","ethiopia":"ADD","tanzania":"DAR",
    "peru":"LIM","chile":"SCL","colombia":"BOG",
    "maldives":"MLE","mauritius":"MRU","seychelles":"SEZ",
}

COUNTRY_CODE_TO_AIRPORT = {
    "GB":"LHR","IE":"DUB","US":"JFK","CA":"YYZ","AU":"SYD","NZ":"AKL",
    "DE":"FRA","FR":"CDG","IT":"FCO","ES":"MAD","NL":"AMS","BE":"BRU",
    "CH":"ZRH","AT":"VIE","PT":"LIS","GR":"ATH","SE":"ARN","NO":"OSL",
    "DK":"CPH","FI":"HEL","PL":"WAW","CZ":"PRG","HU":"BUD","RO":"OTP",
    "TR":"IST","AE":"DXB","SA":"RUH","QA":"DOH","KW":"KWI","EG":"CAI",
    "MA":"CMN","NG":"LOS","KE":"NBO","ZA":"JNB","ET":"ADD","GH":"ACC",
    "IN":"DEL","PK":"KHI","BD":"DAC","LK":"CMB","NP":"KTM","SG":"SIN",
    "MY":"KUL","TH":"BKK","ID":"CGK","PH":"MNL","VN":"SGN","JP":"NRT",
    "KR":"ICN","CN":"PEK","HK":"HKG","TW":"TPE","BR":"GRU","AR":"EZE",
    "CL":"SCL","CO":"BOG","PE":"LIM","MX":"MEX","MU":"MRU","SC":"SEZ",
    "RW":"KGL","TZ":"DAR","MV":"MLE","CY":"LCA","MT":"MLA","IS":"KEF",
    "HR":"ZAG","RS":"BEG","BG":"SOF","IL":"TLV","JO":"AMM","LB":"BEY",
    "MK":"SKP","AL":"TIA","BA":"SJJ","ME":"TGD","RU":"SVO","UA":"KBP",
    "KZ":"ALA","GE":"TBS","AM":"EVN","AZ":"GYD","UZ":"TAS",
    "LU":"LUX","SK":"BTS","SI":"LJU","EE":"TLL","LV":"RIX","LT":"VNO",
}


def city_to_iata(text: str) -> str | None:
    key = text.lower().strip()
    return CITY_TO_AIRPORT.get(key) or COUNTRY_TO_AIRPORT.get(key)


def iata_for_location(text: str) -> str | None:
    result = city_to_iata(text)
    if result:
        return result
    text_l = text.lower().strip()
    for city, code in CITY_TO_AIRPORT.items():
        if text_l in city or city in text_l:
            return code
    return None


def locate_ip(ip: str) -> dict | None:
    if not ip or _is_private(ip):
        return None
    return _ip_api(ip) or _ipinfo(ip)


def _ip_api(ip: str) -> dict | None:
    try:
        r = _safe_get(f"http://ip-api.com/json/{ip}",
                      params={"fields":"status,city,country,countryCode,lat,lon,timezone"},
                      timeout=4)
        if r and r.ok:
            d = r.json()
            if d.get("status") == "success":
                iata = city_to_iata(d.get("city","")) or COUNTRY_CODE_TO_AIRPORT.get(d.get("countryCode",""))
                if iata:
                    return {"city":d.get("city",""),"country":d.get("country",""),
                            "country_code":d.get("countryCode",""),"iata":iata,
                            "lat":d.get("lat"),"lon":d.get("lon"),
                            "timezone":d.get("timezone",""),"source":"ip-api.com"}
    except Exception as e:
        log.debug("ip-api.com: %s", e)
    return None


def _ipinfo(ip: str) -> dict | None:
    try:
        token = os.getenv("IPINFO_TOKEN","")
        r = _safe_get(f"https://ipinfo.io/{ip}/json",
                      params={"token":token} if token else {}, timeout=4)
        if r and r.ok:
            d = r.json()
            city = d.get("city","")
            cc   = (d.get("country") or "")[:2].upper()
            iata = city_to_iata(city) or COUNTRY_CODE_TO_AIRPORT.get(cc)
            if iata:
                loc = d.get("loc",",").split(",")
                return {"city":city,"country":d.get("region",""),"country_code":cc,
                        "iata":iata,"lat":float(loc[0]) if len(loc)==2 else None,
                        "lon":float(loc[1]) if len(loc)==2 else None,
                        "timezone":d.get("timezone",""),"source":"ipinfo.io"}
    except Exception as e:
        log.debug("ipinfo.io: %s", e)
    return None


def _is_private(ip: str) -> bool:
    return (not ip or ip in ("127.0.0.1","::1","localhost")
            or ip.startswith(("10.","192.168."))
            or (ip.startswith("172.") and 16 <= int((ip.split(".")+["0"])[1]) <= 31))
