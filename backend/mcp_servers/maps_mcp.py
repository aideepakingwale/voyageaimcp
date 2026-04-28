"""
Maps/Distance MCP — OpenRouteService API
Docs: https://openrouteservice.org/dev/#/api-docs
FREE: 2,000 requests/day. Key: openrouteservice.org → Dashboard
"""
import os, math
from .base_mcp   import BaseMCP
from .http_client import post, get

ORS_BASE    = "https://api.openrouteservice.org"
MATRIX_URL  = f"{ORS_BASE}/v2/matrix/driving-car"
ROUTE_URL   = f"{ORS_BASE}/v2/directions/driving-car"
GEOCODE_URL = f"{ORS_BASE}/geocode/search"

# Airport → (lat, lon) — all major destinations
AIRPORT_COORDS = {
    "LIS":(38.7756,-9.1354),"OPO":(41.2481,-8.6814),"FAO":(37.0144,-7.9659),
    "BCN":(41.2971,2.0785), "MAD":(40.4983,-3.5676),"AGP":(36.6749,-4.4991),
    "TFS":(28.0445,-16.5724),"PMI":(39.5517,2.7387),"IBZ":(38.8729,1.3731),
    "LPA":(27.9319,-15.3866),"ACE":(28.9454,-13.6052),"FUE":(28.4440,-13.8632),
    "FCO":(41.8003,12.2389),"MXP":(45.6306,8.7281),"VCE":(45.5053,12.3519),
    "PSA":(43.6832,10.3927),"NAP":(40.8860,14.2908),"CDG":(49.0097,2.5479),
    "NCE":(43.6584,7.2159), "MRS":(43.4365,5.2151),"AMS":(52.3086,4.7639),
    "BRU":(50.9014,4.4844), "ZRH":(47.4647,8.5492),"GVA":(46.2381,6.1089),
    "VIE":(48.1103,16.5697),"MUC":(48.3538,11.7861),"FRA":(50.0379,8.5622),
    "BER":(52.3667,13.5033),"HAM":(53.6304,9.9882),"ATH":(37.9364,23.9445),
    "JTR":(36.3993,25.4788),"HER":(35.3397,25.1803),"CFU":(39.6018,19.9118),
    "RHO":(36.4054,28.0862),"JMK":(37.4351,25.3481),"ZTH":(37.7509,20.8843),
    "CPH":(55.6180,12.6561),"ARN":(59.6519,17.9186),"OSL":(60.1939,11.1004),
    "HEL":(60.3172,24.9633),"KEF":(63.9850,-22.6056),"PRG":(50.1008,14.2600),
    "WAW":(52.1657,20.9671),"BUD":(47.4298,19.2611),"DUB":(53.4213,-6.2701),
    "LCA":(34.8752,33.6249),"MLA":(35.8574,14.4775),"DBV":(42.5614,18.2682),
    "SPU":(43.5389,16.2980),"IST":(41.2753,28.7519),"LHR":(51.4775,-0.4614),
    "LGW":(51.1481,-0.1903),"STN":(51.8850,0.2350), "LTN":(51.8747,-0.3683),
    "MAN":(53.3537,-2.2750),"BHX":(52.4539,-1.7480),"EDI":(55.9500,-3.3725),
    "GLA":(55.8719,-4.4331),"BRS":(51.3827,-2.7191),"NCL":(55.0375,-1.6916),
    "DXB":(25.2532,55.3657),"AUH":(24.4330,54.6511),"DOH":(25.2731,51.6081),
    "RUH":(24.9576,46.6988),"JED":(21.6542,39.1568),"CAI":(30.1219,31.4056),
    "CMN":(33.3675,-7.5900),"RAK":(31.6069,-8.0363),"NBO":(-1.3192,36.9275),
    "JNB":(-26.1367,28.2411),"CPT":(-33.9715,18.6021),"MRU":(-20.4302,57.6836),
    "SEZ":(-4.6742,55.5219),"KGL":(-1.9686,30.1395),"DAR":(-6.8780,39.2026),
    "ADD":(8.9779,38.7993), "ACC":(5.6052,-0.1668),"LOS":(6.5773,3.3210),
    "SIN":(1.3644,103.9915),"NRT":(35.7720,140.3929),"KIX":(34.4347,135.2440),
    "HKG":(22.3080,113.9185),"ICN":(37.4602,126.4407),"PEK":(40.0799,116.6031),
    "PVG":(31.1443,121.8083),"BKK":(13.6811,100.7472),"HKT":(8.1132,98.3169),
    "DPS":(-8.7482,115.1671),"CGK":(-6.1275,106.6537),"KUL":(2.7456,101.7099),
    "MNL":(14.5086,121.0194),"SGN":(10.8188,106.6520),"HAN":(21.2212,105.8072),
    "CMB":(7.1808,79.8841), "MLE":(4.1917,73.5290),"DEL":(28.5665,77.1031),
    "BOM":(19.0896,72.8656),"BLR":(13.1986,77.7066),"GOI":(15.3808,73.8314),
    "SYD":(-33.9399,151.1753),"MEL":(-37.6690,144.8410),"AKL":(-37.0082,174.7850),
    "JFK":(40.6413,-73.7781),"LAX":(33.9425,-118.4081),"MIA":(25.7959,-80.2870),
    "ORD":(41.9742,-87.9073),"SFO":(37.6213,-122.3790),"YYZ":(43.6777,-79.6248),
    "YVR":(49.1967,-123.1815),"GIG":(-22.8099,-43.2505),"GRU":(-23.4356,-46.4731),
    "HNL":(21.3245,-157.9251),"CUN":(21.0365,-86.8771),
}

# City centre coordinates
CITY_COORDS = {k: (v[0]+0.12, v[1]+0.08) for k,v in AIRPORT_COORDS.items()}

# City-specific distance overrides (airport to city centre, km)
KNOWN_DISTANCES = {
    "LHR":24,"LGW":45,"STN":58,"LTN":50,"LCY":15,
    "CDG":35,"ORY":18,"AMS":18,"FCO":35,"MXP":50,
    "BCN":15,"MAD":25,"DXB":20,"SIN":20,"NRT":80,
    "HKG":35,"BKK":35,"DPS":13,"CMB":32,"MLE":3,
    "JFK":25,"LAX":30,"MIA":15,"SYD":17,"AKL":25,
    "SEZ":12,"MRU":45,"NBO":18,"CPT":22,"JNB":30,
}

TAXI_RATES = {
    "LHR":2.80,"LGW":2.60,"STN":2.20,"MAN":2.10,"BHX":2.00,
    "LIS":1.65,"BCN":1.85,"MAD":1.75,"FCO":1.90,"CDG":2.15,
    "AMS":2.25,"ZRH":3.60,"GVA":3.80,"VIE":2.20,"MUC":1.90,
    "ATH":1.55,"DXB":2.60,"DOH":2.40,"SIN":2.20,"NRT":4.60,
    "HKG":2.80,"BKK":1.20,"DPS":1.10,"KUL":1.00,"JFK":3.20,
    "LAX":2.80,"MIA":2.60,"SYD":2.20,"AKL":2.40,"SEZ":2.00,
    "MRU":1.80,"NBO":1.40,"JNB":2.00,"CPT":1.70,"CMB":1.30,
}

PUBLIC_TRANSPORT = {
    "LIS":"Metro Linha Vermelha — 35 min","BCN":"L9 Sud Metro — 30 min",
    "MAD":"Metro Línea 8 — 25 min","FCO":"Leonardo Express train — 32 min",
    "CDG":"RER B train — 35 min","AMS":"Sprinter train — 20 min",
    "ZRH":"ZVV Airport Express — 10 min","ATH":"Metro Line 3 — 45 min",
    "DXB":"Dubai Metro Red Line — 35 min","SIN":"MRT to city — 30 min",
    "HKG":"Airport Express MTR — 24 min","BKK":"Airport Rail Link — 25 min",
    "NRT":"Narita Express N'EX — 60 min","SYD":"Airport Link train — 15 min",
    "JFK":"AirTrain + Subway — 60 min","LHR":"Elizabeth line — 20 min",
    "LGW":"Gatwick Express — 30 min","MAN":"Metrolink tram — 20 min",
    "KUL":"KLIA Ekspres — 28 min","CMB":"No direct rail; taxi recommended",
    "SEZ":"Taxi only; 30 min","MRU":"Taxi or shuttle; 45 min",
}


class MapsMCP(BaseMCP):
    def __init__(self): super().__init__(ttl=86400)

    def _fetch(self, params: dict) -> dict:
        origin_code = params.get("origin","LIS_AIRPORT").upper().replace(" ","_")
        city = origin_code.split("_")[0]

        api_key = os.getenv("OPENROUTESERVICE_API_KEY","").strip()

        a_coords = AIRPORT_COORDS.get(city)
        c_coords = CITY_COORDS.get(city)

        if not a_coords:
            return {"data":{"distance_km":15,"drive_min":25,
                           "taxi_gbp":20,"source":"default"}}

        if api_key and c_coords:
            live = self._live_ors(api_key, a_coords, c_coords, city)
            if live:
                return live

        return self._calculated(a_coords, c_coords, city)

    def _live_ors(self, api_key, a_coords, c_coords, city):
        try:
            r = post(
                f"{ORS_BASE}/v2/directions/driving-car/geojson",
                json={"coordinates":[[a_coords[1],a_coords[0]],
                                      [c_coords[1],c_coords[0]]]},
                headers={"Authorization": api_key,
                         "Content-Type": "application/json"},
                timeout=8,
            )
            if r and r.ok:
                feat     = r.json()["features"][0]["properties"]["summary"]
                dist_km  = round(feat["distance"]/1000, 1)
                dur_min  = round(feat["duration"]/60)
                rate     = TAXI_RATES.get(city, 2.0)
                taxi_est = round(5 + dist_km*rate, 0)
                return {"data":{
                    "city":          city,
                    "distance_km":   dist_km,
                    "drive_min":     dur_min,
                    "taxi_gbp":      taxi_est,
                    "taxi_tip":      f"Allow {dur_min+10} min incl. traffic",
                    "public_transport": PUBLIC_TRANSPORT.get(city,"Check local transport options"),
                    "source":        "openrouteservice_live",
                }}
        except Exception as e:
            self._log.debug("ORS error: %s", e)
        return None

    def _calculated(self, a_coords, c_coords, city):
        # Use known distance if available
        dist_km = KNOWN_DISTANCES.get(city)
        if not dist_km:
            R = 6371
            dlat = math.radians(c_coords[0]-a_coords[0])
            dlon = math.radians(c_coords[1]-a_coords[1])
            a    = (math.sin(dlat/2)**2 +
                    math.cos(math.radians(a_coords[0]))*
                    math.cos(math.radians(c_coords[0]))*
                    math.sin(dlon/2)**2)
            dist_km = round(R*2*math.atan2(math.sqrt(a),math.sqrt(1-a)),1)

        rate    = TAXI_RATES.get(city, 2.0)
        dur_min = round(dist_km/35*60)
        taxi    = round(5 + dist_km*rate, 0)
        return {"data":{
            "city":          city,
            "distance_km":   dist_km,
            "drive_min":     dur_min,
            "taxi_gbp":      taxi,
            "taxi_tip":      f"Airport is ~{dist_km}km from city. Allow {dur_min+10} min incl. traffic.",
            "public_transport": PUBLIC_TRANSPORT.get(city,"Check local transport options"),
            "source":        "calculated",
        }}

    def _score_confidence(self, r):
        src = r.get("data",{}).get("source","")
        return 0.97 if "live" in src else 0.90
