"""
Weather MCP — OpenWeatherMap API
Docs: https://openweathermap.org/api/one-call-3
FREE: 1,000 calls/day. Key: openweathermap.org → API Keys tab.
"""
import os
from datetime      import datetime
from .base_mcp     import BaseMCP
from .http_client  import get

OWM_CURRENT  = "https://api.openweathermap.org/data/2.5/weather"
OWM_FORECAST = "https://api.openweathermap.org/data/2.5/forecast"

# All destination cities with coordinates
CITY_COORDS = {
    "LIS":(38.7223,-9.1393,"Lisbon","Portugal"),
    "OPO":(41.1496,-8.6109,"Porto","Portugal"),
    "FAO":(37.0194,-7.9322,"Faro","Portugal"),
    "BCN":(41.3851,2.1734,"Barcelona","Spain"),
    "MAD":(40.4168,-3.7038,"Madrid","Spain"),
    "AGP":(36.7213,-4.4213,"Málaga","Spain"),
    "TFS":(28.0469,-16.5726,"Tenerife","Spain"),
    "PMI":(39.5696,2.6502,"Palma","Spain"),
    "IBZ":(38.9067,1.4321,"Ibiza","Spain"),
    "LPA":(27.9202,-15.3884,"Gran Canaria","Spain"),
    "ACE":(28.9455,-13.6026,"Lanzarote","Spain"),
    "FUE":(28.4997,-13.8644,"Fuerteventura","Spain"),
    "SVQ":(37.3826,-5.9870,"Seville","Spain"),
    "FCO":(41.9028,12.4964,"Rome","Italy"),
    "MXP":(45.4654,9.1866,"Milan","Italy"),
    "VCE":(45.4408,12.3155,"Venice","Italy"),
    "NAP":(40.8518,14.2681,"Naples","Italy"),
    "CDG":(48.8566,2.3522,"Paris","France"),
    "NCE":(43.7102,7.2620,"Nice","France"),
    "AMS":(52.3676,4.9041,"Amsterdam","Netherlands"),
    "BRU":(50.8503,4.3517,"Brussels","Belgium"),
    "ZRH":(47.3769,8.5417,"Zurich","Switzerland"),
    "GVA":(46.2044,6.1432,"Geneva","Switzerland"),
    "VIE":(48.2082,16.3738,"Vienna","Austria"),
    "MUC":(48.1351,11.5820,"Munich","Germany"),
    "FRA":(50.1109,8.6821,"Frankfurt","Germany"),
    "BER":(52.5200,13.4050,"Berlin","Germany"),
    "ATH":(37.9838,23.7275,"Athens","Greece"),
    "JTR":(36.3932,25.4615,"Santorini","Greece"),
    "HER":(35.3387,25.1442,"Heraklion","Greece"),
    "CFU":(39.6243,19.9217,"Corfu","Greece"),
    "RHO":(36.4349,28.2176,"Rhodes","Greece"),
    "JMK":(37.4443,25.3289,"Mykonos","Greece"),
    "CPH":(55.6761,12.5683,"Copenhagen","Denmark"),
    "ARN":(59.3293,18.0686,"Stockholm","Sweden"),
    "OSL":(59.9139,10.7522,"Oslo","Norway"),
    "HEL":(60.1699,24.9384,"Helsinki","Finland"),
    "KEF":(64.1355,-21.8954,"Reykjavik","Iceland"),
    "PRG":(50.0755,14.4378,"Prague","Czech Republic"),
    "WAW":(52.2297,21.0122,"Warsaw","Poland"),
    "BUD":(47.4979,19.0402,"Budapest","Hungary"),
    "IST":(41.0082,28.9784,"Istanbul","Turkey"),
    "DUB":(53.3498,-6.2603,"Dublin","Ireland"),
    "DXB":(25.2048,55.2708,"Dubai","UAE"),
    "AUH":(24.4539,54.3773,"Abu Dhabi","UAE"),
    "DOH":(25.2854,51.5310,"Doha","Qatar"),
    "CAI":(30.0444,31.2357,"Cairo","Egypt"),
    "CMN":(33.5731,-7.5898,"Casablanca","Morocco"),
    "RAK":(31.6295,-7.9811,"Marrakech","Morocco"),
    "NBO":(-1.2921,36.8219,"Nairobi","Kenya"),
    "JNB":(-26.2041,28.0473,"Johannesburg","South Africa"),
    "CPT":(-33.9249,18.4241,"Cape Town","South Africa"),
    "MRU":(-20.1609,57.4977,"Mauritius","Mauritius"),
    "SEZ":(-4.6796,55.4930,"Mahé","Seychelles"),
    "KGL":(-1.9403,29.8739,"Kigali","Rwanda"),
    "SIN":(1.3521,103.8198,"Singapore","Singapore"),
    "NRT":(35.6762,139.6503,"Tokyo","Japan"),
    "KIX":(34.6937,135.5023,"Osaka","Japan"),
    "HKG":(22.3193,114.1694,"Hong Kong","China"),
    "ICN":(37.5665,126.9780,"Seoul","South Korea"),
    "PEK":(39.9042,116.4074,"Beijing","China"),
    "PVG":(31.2304,121.4737,"Shanghai","China"),
    "BKK":(13.7563,100.5018,"Bangkok","Thailand"),
    "HKT":(7.8804,98.3923,"Phuket","Thailand"),
    "CNX":(18.7883,98.9853,"Chiang Mai","Thailand"),
    "DPS":(-8.3405,115.0920,"Bali","Indonesia"),
    "CGK":(-6.2088,106.8456,"Jakarta","Indonesia"),
    "KUL":(3.1390,101.6869,"Kuala Lumpur","Malaysia"),
    "MNL":(14.5995,120.9842,"Manila","Philippines"),
    "SGN":(10.8231,106.6297,"Ho Chi Minh City","Vietnam"),
    "HAN":(21.0285,105.8542,"Hanoi","Vietnam"),
    "CMB":(6.9271,79.8612,"Colombo","Sri Lanka"),
    "MLE":(4.1755,73.5093,"Malé","Maldives"),
    "KTM":(27.7172,85.3240,"Kathmandu","Nepal"),
    "DEL":(28.6139,77.2090,"New Delhi","India"),
    "BOM":(19.0760,72.8777,"Mumbai","India"),
    "BLR":(12.9716,77.5946,"Bangalore","India"),
    "GOI":(15.2993,74.1240,"Goa","India"),
    "SYD":(-33.8688,151.2093,"Sydney","Australia"),
    "MEL":(-37.8136,144.9631,"Melbourne","Australia"),
    "AKL":(-36.8509,174.7645,"Auckland","New Zealand"),
    "JFK":(40.7128,-74.0060,"New York","USA"),
    "LAX":(34.0522,-118.2437,"Los Angeles","USA"),
    "MIA":(25.7617,-80.1918,"Miami","USA"),
    "ORD":(41.8781,-87.6298,"Chicago","USA"),
    "SFO":(37.7749,-122.4194,"San Francisco","USA"),
    "YYZ":(43.6510,-79.3470,"Toronto","Canada"),
    "YVR":(49.2827,-123.1207,"Vancouver","Canada"),
    "GIG":(-22.9068,-43.1729,"Rio de Janeiro","Brazil"),
    "GRU":(-23.5558,-46.6396,"São Paulo","Brazil"),
    "EZE":(-34.6037,-58.3816,"Buenos Aires","Argentina"),
    "SCL":(-33.4489,-70.6693,"Santiago","Chile"),
    "LIM":(-12.0464,-77.0428,"Lima","Peru"),
    "BOG":(4.7110,-74.0721,"Bogotá","Colombia"),
    "HNL":(21.3069,-157.8583,"Honolulu","USA"),
    "CUN":(21.1743,-86.8466,"Cancún","Mexico"),
    "NAN":(-17.7134,178.0650,"Nadi","Fiji"),
    "PPT":(-17.5518,-149.5583,"Papeete","French Polynesia"),
    "BOB":(-16.5004,-151.7415,"Bora Bora","French Polynesia"),
    "KEF":(64.1355,-21.8954,"Reykjavik","Iceland"),
    "FNC":(32.6669,-16.9241,"Funchal","Portugal"),
    "LCA":(34.9000,33.6250,"Larnaca","Cyprus"),
    "MLA":(35.8997,14.4425,"Valletta","Malta"),
    "DBV":(42.6507,18.0944,"Dubrovnik","Croatia"),
    "SPU":(43.5089,16.2978,"Split","Croatia"),
}

# Monthly climate: (avg_max_c, avg_rain_mm, sunshine_hrs/day, description)
MONTHLY_CLIMATE = {
    "LIS":[(13,96,4),(14,76,5),(16,73,6),(18,51,7),(21,39,9),(24,13,10),(27,3,11),(28,4,11),(25,33,8),(20,80,6),(15,93,5),(13,100,4)],
    "BCN":[(13,41,5),(14,35,6),(15,48,7),(17,44,7),(20,54,9),(24,34,10),(27,22,10),(28,63,9),(25,83,8),(21,91,6),(16,57,5),(13,40,4)],
    "MAD":[(9,39,5),(11,34,6),(14,28,7),(16,38,8),(21,43,9),(27,23,11),(32,11,12),(31,10,12),(25,25,9),(18,48,7),(12,48,5),(8,49,4)],
    "TFS":[(21,30,6),(21,25,7),(22,20,8),(23,10,9),(24,5,10),(25,2,10),(28,0,11),(29,0,11),(27,10,9),(25,30,8),(22,40,7),(21,35,6)],
    "FCO":[(11,62,4),(12,57,5),(14,57,6),(17,60,7),(22,37,8),(26,17,10),(29,8,11),(29,21,10),(25,68,8),(19,99,6),(14,99,5),(11,82,4)],
    "CDG":[(6,50,2),(7,37,3),(11,36,5),(14,43,6),(18,58,7),(21,53,8),(23,60,8),(23,48,7),(19,52,6),(14,57,4),(8,50,2),(6,51,2)],
    "ATH":[(12,48,4),(13,38,5),(15,36,6),(20,21,8),(25,16,9),(30,6,11),(33,3,12),(33,6,11),(29,13,9),(23,45,7),(17,56,5),(13,56,4)],
    "DXB":[(19,10,8),(21,13,9),(24,12,9),(29,7,10),(34,1,11),(36,0,12),(38,0,12),(38,0,11),(35,0,11),(30,1,10),(25,3,9),(21,13,8)],
    "SIN":[(30,257,6),(31,132,7),(31,182,7),(31,166,7),(31,169,7),(30,130,7),(30,150,6),(30,158,6),(30,178,6),(30,208,6),(30,259,6),(29,316,6)],
    "BKK":[(32,9,8),(33,31,8),(34,33,8),(35,76,8),(33,189,6),(32,142,5),(31,152,5),(31,171,5),(31,302,5),(31,231,6),(30,59,7),(30,7,8)],
    "DPS":[(29,232,7),(29,207,7),(29,133,7),(29,112,8),(28,66,9),(27,51,9),(27,44,9),(27,37,10),(28,52,9),(28,119,8),(29,191,8),(29,246,7)],
    "MLE":[(29,114,9),(29,53,9),(29,75,8),(30,122,9),(29,216,8),(29,164,7),(29,167,8),(30,132,8),(29,179,8),(29,186,8),(29,231,8),(29,225,8)],
    "SEZ":[(28,252,6),(28,151,7),(28,107,8),(29,103,8),(28,176,7),(27,60,7),(26,61,8),(26,67,8),(27,130,8),(27,232,7),(27,269,6),(28,257,6)],
    "MRU":[(27,277,8),(27,221,8),(26,216,8),(24,130,8),(22,82,7),(20,53,6),(19,43,6),(20,47,7),(22,70,7),(23,95,7),(24,150,7),(26,239,8)],
    "NBO":[(24,68,7),(25,64,8),(25,121,7),(23,195,6),(22,150,6),(21,33,5),(20,18,5),(21,28,5),(24,30,7),(24,72,7),(23,133,6),(23,84,6)],
    "CPT":[(26,8,11),(26,7,10),(24,18,9),(21,36,7),(18,68,6),(17,84,5),(16,76,5),(16,65,6),(18,43,7),(21,23,8),(23,15,9),(25,10,11)],
    "MRU":[(27,277,8),(27,221,8),(26,216,8),(24,130,8),(22,82,7),(20,53,6),(19,43,6),(20,47,7),(22,70,7),(23,95,7),(24,150,7),(26,239,8)],
    "NRT":[(9,52,6),(9,57,6),(12,116,6),(17,127,7),(21,138,7),(24,164,6),(28,154,6),(30,152,6),(26,210,5),(21,197,5),(15,93,5),(10,39,6)],
    "SIN":[(30,257,6),(31,132,7),(31,182,7),(31,166,7),(31,169,7),(30,130,7),(30,150,6),(30,158,6),(30,178,6),(30,208,6),(30,259,6),(29,316,6)],
    "JFK":[(3,91,5),(4,79,6),(9,97,7),(15,94,8),(21,96,8),(26,94,8),(29,100,8),(28,100,7),(24,89,7),(18,86,7),(12,97,5),(5,100,4)],
    "LAX":[(18,84,7),(19,69,8),(20,55,9),(21,27,10),(23,5,11),(25,1,12),(28,0,12),(29,1,12),(28,6,11),(25,20,10),(21,27,9),(18,72,7)],
    "SYD":[(26,103,7),(26,113,7),(24,131,6),(22,127,6),(19,122,6),(17,132,5),(16,117,5),(17,78,6),(19,69,7),(22,77,7),(23,82,7),(25,78,7)],
    "AKL":[(23,72,7),(24,53,7),(22,87,7),(19,97,6),(16,91,5),(14,106,5),(13,138,5),(13,116,5),(15,86,6),(17,69,7),(19,71,7),(21,72,7)],
    "MIA":[(24,51,8),(25,55,8),(27,71,9),(28,86,9),(30,163,8),(31,195,8),(32,172,8),(32,195,8),(31,230,8),(29,176,8),(27,93,8),(25,59,8)],
    "CUN":[(27,45,7),(28,39,8),(29,33,8),(30,44,8),(31,96,8),(32,113,7),(32,106,7),(32,121,7),(31,182,6),(29,205,6),(27,75,7),(27,45,7)],
    "HNL":[(26,72,8),(26,64,8),(26,70,8),(27,45,9),(28,25,10),(29,14,10),(29,20,11),(30,16,11),(30,22,10),(29,50,10),(28,55,9),(26,68,8)],
    "BOB":[(30,135,8),(30,100,8),(30,115,8),(30,130,8),(29,120,8),(28,60,7),(27,45,7),(27,40,8),(28,55,8),(29,90,8),(30,110,8),(30,125,8)],
}


class WeatherMCP(BaseMCP):
    def __init__(self): super().__init__(ttl=1800)

    def _fetch(self, params: dict) -> dict:
        city_code = params.get("city","LIS").upper()[:3]
        month_idx = int(params.get("month", datetime.now().month)) - 1
        dep_date  = params.get("departure_date","")

        info   = CITY_COORDS.get(city_code, CITY_COORDS.get("LIS"))
        lat, lon, city_name, country = info[0], info[1], info[2], info[3]

        api_key = os.getenv("OPENWEATHER_API_KEY","").strip()

        if api_key:
            live = self._live(api_key, lat, lon, city_name, country, city_code, month_idx)
            if live:
                return live

        return self._climate(city_code, city_name, country, month_idx)

    def _live(self, api_key, lat, lon, city_name, country, code, month_idx):
        try:
            # Current weather
            r = get(OWM_CURRENT,
                    params={"lat":lat,"lon":lon,"appid":api_key,
                            "units":"metric","lang":"en"},
                    timeout=5)
            if not r or not r.ok:
                return None

            w      = r.json()
            temp   = round(w["main"]["temp"], 1)
            feels  = round(w["main"]["feels_like"], 1)
            humid  = w["main"]["humidity"]
            desc   = w["weather"][0]["description"].title()
            wind   = round(w["wind"]["speed"]*3.6, 1)
            icon   = w["weather"][0]["icon"]
            vis    = round(w.get("visibility",10000)/1000,1)
            press  = w["main"]["pressure"]

            # 5-day forecast (free endpoint)
            forecast_summary = ""
            rf = get(OWM_FORECAST,
                     params={"lat":lat,"lon":lon,"appid":api_key,
                             "units":"metric","cnt":16},
                     timeout=5)
            if rf and rf.ok:
                items   = rf.json().get("list",[])
                temps   = [i["main"]["temp"] for i in items]
                descs   = [i["weather"][0]["description"] for i in items[:8]]
                rain_mm = sum(i.get("rain",{}).get("3h",0) for i in items)
                forecast_summary = (
                    f"Next 48h: {min(temps):.0f}–{max(temps):.0f}°C. "
                    f"{'Some rain expected.' if rain_mm>5 else 'Dry conditions.'}"
                )

            # Monthly climate stats as context
            climate = MONTHLY_CLIMATE.get(code, [(20,50,7,"Pleasant")])
            mc = climate[month_idx % 12]
            avg_max, rain_mm_mo, sun_hrs, *_ = mc if len(mc)>=3 else (20,50,7)

            return {"data":{
                "city":            city_name,
                "country":         country,
                "temp_c":          temp,
                "feels_like_c":    feels,
                "humidity_pct":    humid,
                "description":     desc,
                "wind_kph":        wind,
                "visibility_km":   vis,
                "pressure_hpa":    press,
                "weather_icon":    f"https://openweathermap.org/img/wn/{icon}@2x.png",
                "forecast_48h":    forecast_summary,
                "month_avg_max_c": avg_max,
                "month_rain_mm":   rain_mm_mo,
                "month_sunshine_h":sun_hrs,
                "advisory":        _advisory(temp, desc, month_idx+1),
                "packing":         _packing(temp, desc),
                "best_time":       _best_time(code),
                "source":          "openweathermap_live",
            }}
        except Exception as e:
            self._log.debug("OWM error: %s", e)
            return None

    def _climate(self, code, city_name, country, month_idx):
        table = MONTHLY_CLIMATE.get(code, [(22,40,8,"Pleasant")]*12)
        mc    = table[month_idx%12]
        avg_max, rain_mm, sun_hrs, *_ = mc if len(mc)>=3 else (22,40,8)
        months = ["January","February","March","April","May","June",
                  "July","August","September","October","November","December"]
        return {"data":{
            "city":            city_name,
            "country":         country,
            "month":           months[month_idx%12],
            "avg_max_c":       avg_max,
            "rain_mm_month":   rain_mm,
            "sunshine_hrs_day":sun_hrs,
            "advisory":        _advisory(avg_max, "", month_idx+1),
            "packing":         _packing(avg_max, ""),
            "best_time":       _best_time(code),
            "source":          "climate_averages",
        }}

    def _score_confidence(self, r):
        src = r.get("data",{}).get("source","")
        return 0.98 if "live" in src else 0.88


def _advisory(temp, desc, month):
    desc_l = desc.lower()
    if temp>33:   return f"Very hot ({temp}°C). Stay hydrated, avoid midday sun. Factor 50+ sunscreen essential."
    if temp>27:   return f"Hot and sunny ({temp}°C). Perfect beach weather. Light clothing, high SPF sunscreen."
    if temp>22:   return f"Warm and pleasant ({temp}°C). Ideal for sightseeing and outdoor activities."
    if temp>16:   return f"Mild ({temp}°C). Light jacket for evenings. Comfortable for walking tours."
    if temp>10:   return f"Cool ({temp}°C). Layers recommended. {'Rainy—pack waterproof.' if 'rain' in desc_l else 'Some cloud likely.'}"
    return        f"Cold ({temp}°C). Warm coat, layers and waterproof jacket essential."

def _packing(temp, desc):
    desc_l = desc.lower()
    rain   = "rain" in desc_l or "shower" in desc_l
    if temp>27: return ["light clothing","swimwear","sunscreen SPF50+","sunglasses","hat","flip flops"]
    if temp>20: return ["summer clothes","light cardigan","sunscreen","comfortable walking shoes"] + (["travel umbrella"] if rain else [])
    if temp>14: return ["layers","light jacket","waterproof","comfortable shoes","day bag"]
    return      ["warm coat","thermal layers","waterproof jacket","boots","gloves"]

def _best_time(code):
    times = {
        "DXB":"Nov–Mar (avoid summer heat Jun–Sep, up to 45°C)",
        "BKK":"Nov–Mar (dry season; Apr–Oct is monsoon season)",
        "DPS":"Apr–Sep (dry season; avoid Oct–Mar monsoon)",
        "MLE":"Nov–Apr (dry northeast monsoon; best diving & weather)",
        "SEZ":"Apr–May, Oct–Nov (calmer seas, good visibility)",
        "MRU":"May–Dec (dry and cooler; Jan–Apr cyclone season)",
        "NBO":"Jun–Sep, Jan–Feb (dry seasons for safari)",
        "CPT":"Nov–Mar (summer; wine regions and beaches)",
        "JNB":"May–Sep (dry winter; best for safari)",
        "NRT":"Mar–May, Sep–Nov (spring/autumn; avoid Aug humidity)",
        "BKK":"Nov–Feb (cool and dry; avoid Apr–Oct)",
        "SIN":"Feb–Apr (drier; year-round warm at 30°C)",
        "SYD":"Sep–Nov, Mar–May (spring/autumn; beach Dec–Feb)",
        "AKL":"Dec–Feb (summer; warmest and driest)",
        "JFK":"May–Jun, Sep–Oct (avoid Jul–Aug heat and Feb cold)",
        "MIA":"Nov–Apr (dry season; avoid Jun–Oct hurricane season)",
        "CUN":"Dec–Apr (dry season; Jul–Oct hurricane risk)",
        "HNL":"Apr–Jun, Sep–Nov (shoulder season, fewer crowds)",
        "BOB":"May–Oct (dry season, best snorkelling and diving)",
    }
    return times.get(code, "Check seasonal weather for your travel dates")
