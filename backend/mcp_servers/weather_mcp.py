"""
Weather MCP Server
PRIMARY:  OpenWeatherMap Current + Forecast API (real-time)
FALLBACK: Seasonal averages by city/month
"""
import os
from datetime import datetime
from .base_mcp     import BaseMCP
from .http_client  import get

OWM_CURRENT  = "https://api.openweathermap.org/data/2.5/weather"
OWM_FORECAST = "https://api.openweathermap.org/data/2.5/forecast"
OWM_ONECALL  = "https://api.openweathermap.org/data/3.0/onecall"

CITY_COORDS = {
    "LIS":(38.7223,-9.1393,"Lisbon"),    "BCN":(41.3851,2.1734,"Barcelona"),
    "MAD":(40.4168,-3.7038,"Madrid"),    "FCO":(41.9028,12.4964,"Rome"),
    "CDG":(48.8566,2.3522,"Paris"),      "AMS":(52.3676,4.9041,"Amsterdam"),
    "ATH":(37.9838,23.7275,"Athens"),    "DXB":(25.2048,55.2708,"Dubai"),
    "JFK":(40.7128,-74.0060,"New York"), "NRT":(35.6762,139.6503,"Tokyo"),
    "SIN":(1.3521,103.8198,"Singapore"), "ZRH":(47.3769,8.5417,"Zurich"),
    "VIE":(48.2082,16.3738,"Vienna"),    "MLE":(4.1755,73.5093,"Malé"),
    "DPS":(-8.3405,115.0920,"Bali"),     "BKK":(13.7563,100.5018,"Bangkok"),
    "MRU":(-20.1609,57.4977,"Mauritius"),"OPO":(41.1496,-8.6109,"Porto"),
    "TFS":(28.0469,-16.5726,"Tenerife"), "LHR":(51.5074,-0.1278,"London"),
}

# Monthly averages [Jan..Dec]: (temp_c, rain_days, sunshine_hrs)
MONTHLY_CLIMATE = {
    "LIS":[(11,8,5),(12,7,6),(14,6,7),(16,5,8),(18,3,9),(21,1,10),
           (24,0,11),(25,0,11),(22,3,9),(18,6,7),(14,8,5),(11,9,4)],
    "BCN":[(11,5,5),(12,4,6),(14,4,7),(16,6,7),(19,5,8),(23,3,9),
           (26,2,10),(26,3,9),(23,5,8),(19,6,6),(14,6,5),(11,5,4)],
    "MAD":[(7,5,5),(9,4,6),(12,4,7),(15,5,8),(19,5,9),(25,2,11),
           (30,1,12),(29,1,12),(24,3,9),(17,5,7),(11,5,5),(7,5,4)],
    "FCO":[(9,6,4),(10,5,5),(12,5,6),(15,5,7),(20,3,9),(24,1,10),
           (27,0,11),(27,1,10),(23,5,8),(18,6,6),(13,7,5),(10,7,4)],
    "CDG":[(5,10,2),(6,9,3),(9,8,5),(12,8,6),(16,8,7),(19,7,8),
           (21,6,8),(21,6,8),(18,6,6),(13,7,4),(8,9,2),(5,10,2)],
    "DXB":[(19,1,9),(21,1,9),(24,1,9),(29,0,10),(33,0,11),(35,0,11),
           (37,0,11),(37,0,11),(35,0,10),(31,0,10),(26,0,9),(21,1,9)],
    "ATH":[(10,8,4),(11,7,5),(13,5,6),(17,4,8),(22,2,10),(27,1,11),
           (30,0,12),(30,0,11),(26,2,9),(20,5,7),(15,7,5),(12,8,4)],
    "SIN":[(27,16,6),(28,12,7),(28,14,7),(29,15,7),(29,16,7),(29,14,6),
           (28,15,6),(28,15,6),(27,16,6),(27,17,6),(27,18,6),(27,17,6)],
    "MLE":[(28,5,8),(29,4,9),(29,6,8),(30,9,8),(29,14,7),(28,16,6),
           (28,15,6),(28,15,7),(28,14,7),(28,13,7),(28,11,8),(28,8,8)],
    "DPS":[(27,18,6),(27,17,6),(28,16,7),(28,12,8),(27,8,9),(27,5,9),
           (26,3,10),(26,2,11),(27,3,10),(28,7,9),(28,12,7),(28,16,6)],
    "NRT":[(6,5,6),(7,6,6),(10,10,6),(15,10,6),(19,11,6),(22,12,5),
           (26,12,5),(27,9,6),(23,12,5),(17,9,5),(12,7,5),(8,4,5)],
    "LHR":[(5,11,2),(6,9,3),(8,9,4),(11,8,5),(14,8,6),(18,8,7),
           (20,7,7),(20,7,6),(17,8,5),(13,9,3),(8,10,2),(5,11,2)],
}


class WeatherMCP(BaseMCP):
    def __init__(self): super().__init__(ttl=3600)

    def _fetch(self, params: dict) -> dict:
        city_code = params.get("city","LIS").upper()[:3]
        dep_date  = params.get("departure_date","")
        month_idx = int(params.get("month", datetime.now().month)) - 1

        coords = CITY_COORDS.get(city_code, CITY_COORDS.get("LIS"))
        lat, lon, city_name = coords[0], coords[1], coords[2]

        api_key = os.getenv("OPENWEATHER_API_KEY","").strip()

        # Try live API
        if api_key and api_key not in ("","demo","your_openweather_key_here"):
            live = self._live(api_key, lat, lon, city_name, city_code, month_idx)
            if live:
                return live

        return self._climate(city_code, city_name, month_idx, dep_date)

    def _live(self, api_key, lat, lon, city_name, code, month_idx):
        try:
            r = get(OWM_CURRENT,
                    params={"lat":lat,"lon":lon,"appid":api_key,"units":"metric"},
                    timeout=5)
            if not r.ok:
                return None
            w = r.json()
            temp   = round(w["main"]["temp"], 1)
            feels  = round(w["main"]["feels_like"], 1)
            humid  = w["main"]["humidity"]
            desc   = w["weather"][0]["description"].title()
            wind   = round(w["wind"]["speed"] * 3.6, 1)  # m/s → km/h
            cloud  = w["clouds"]["all"]

            # Also grab 5-day forecast for travel advisory
            rf = get(OWM_FORECAST,
                     params={"lat":lat,"lon":lon,"appid":api_key,
                             "units":"metric","cnt":8},
                     timeout=5)
            forecast_text = ""
            if rf.ok:
                items = rf.json().get("list",[])[:8]
                temps = [i["main"]["temp"] for i in items]
                forecast_text = f"Next 48h: {min(temps):.0f}–{max(temps):.0f}°C. "

            climate = MONTHLY_CLIMATE.get(code, MONTHLY_CLIMATE.get("LIS",[]))[month_idx]

            return {"data":{
                "city":         city_name,
                "temp_c":       temp,
                "feels_like_c": feels,
                "humidity_pct": humid,
                "description":  desc,
                "wind_kph":     wind,
                "cloud_pct":    cloud,
                "forecast":     forecast_text,
                "avg_month_c":  climate[0],
                "rain_days_month": climate[1],
                "advisory":     _travel_advice(temp, desc, month_idx+1),
                "packing":      _packing(temp),
                "source":       "openweathermap_live",
            }}
        except Exception as e:
            return None

    def _climate(self, code, city_name, month_idx, dep_date):
        table = MONTHLY_CLIMATE.get(code, MONTHLY_CLIMATE.get("LIS",[]))
        if not table:
            table = [(20,5,8)]*12
        t, r, s = table[month_idx % 12]
        month_names = ["January","February","March","April","May","June",
                       "July","August","September","October","November","December"]
        return {"data":{
            "city":             city_name,
            "month":            month_names[month_idx % 12],
            "avg_temp_c":       t,
            "rain_days_month":  r,
            "avg_sunshine_hrs": s,
            "advisory":         _travel_advice(t, "", month_idx+1),
            "packing":          _packing(t),
            "source":           "climate_averages",
        }}

    def _score_confidence(self, r):
        src = r.get("data",{}).get("source","")
        return 0.98 if "live" in src else 0.85


def _travel_advice(temp, desc, month):
    rain_months = {6,7,8,9,10,11}  # monsoonal hint
    if temp > 32: return f"Very hot ({temp}°C). Hydration essential, seek shade midday. Light breathable clothing."
    if temp > 26: return f"Hot and sunny ({temp}°C). Perfect beach weather. Factor 30+ sunscreen recommended."
    if temp > 20: return f"Warm and pleasant ({temp}°C). Ideal conditions for sightseeing and outdoor dining."
    if temp > 14: return f"Mild ({temp}°C). Light jacket for evenings. Comfortable walking conditions."
    if temp > 8:  return f"Cool ({temp}°C). Warm layers needed. Some rain likely — pack a waterproof."
    return f"Cold ({temp}°C). Warm coat, gloves and layers essential."


def _packing(temp):
    if temp > 26: return ["light clothing","swimwear","sunscreen SPF50","sunglasses","hat"]
    if temp > 18: return ["summer clothing","light cardigan","sunscreen","comfortable shoes"]
    if temp > 12: return ["layers","light jacket","waterproof","comfortable shoes"]
    return ["warm coat","thermal layers","waterproof jacket","boots"]
