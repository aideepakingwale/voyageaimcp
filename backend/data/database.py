"""
VoyageAI SQLite Mock Database
Creates realistic mock data for:
- Customer profiles & travel history
- Loyalty program tiers & points
- Ancillary preferences
Run once: python data/database.py
"""
import sqlite3, os, json
from datetime import datetime, timedelta
import random

DB_PATH = os.path.join(os.path.dirname(__file__), "voyageai.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    # ── CUSTOMERS ────────────────────────────────────────
    c.execute("""CREATE TABLE IF NOT EXISTS customers (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        email       TEXT UNIQUE,
        phone       TEXT,
        passport_country TEXT DEFAULT 'GB',
        date_of_birth    TEXT,
        adults_in_family INTEGER DEFAULT 1,
        children_in_family INTEGER DEFAULT 0,
        travel_style TEXT DEFAULT 'leisure',  -- leisure|business|adventure|family
        preferences  TEXT,  -- JSON
        created_at   TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    # ── TRAVEL HISTORY ────────────────────────────────────
    c.execute("""CREATE TABLE IF NOT EXISTS travel_history (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id     TEXT,
        destination     TEXT,
        city_code       TEXT,
        country_code    TEXT,
        departure_date  TEXT,
        return_date     TEXT,
        nights          INTEGER,
        guests          INTEGER,
        airline         TEXT,
        hotel_name      TEXT,
        hotel_stars     INTEGER,
        total_spent_gbp REAL,
        trip_type       TEXT,  -- leisure|business|family|honeymoon|adventure
        rating          INTEGER,  -- 1-5 customer rating
        ancillaries     TEXT,  -- JSON list of bought extras
        FOREIGN KEY (customer_id) REFERENCES customers(id)
    )""")

    # ── LOYALTY PROGRAM ───────────────────────────────────
    c.execute("""CREATE TABLE IF NOT EXISTS loyalty_accounts (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id     TEXT UNIQUE,
        member_id       TEXT UNIQUE,
        tier            TEXT DEFAULT 'Blue',  -- Blue|Silver|Gold|Platinum
        points_balance  INTEGER DEFAULT 0,
        points_ytd      INTEGER DEFAULT 0,  -- points this year
        total_nights_ytd INTEGER DEFAULT 0,
        total_flights_ytd INTEGER DEFAULT 0,
        member_since    TEXT,
        tier_expiry     TEXT,
        FOREIGN KEY (customer_id) REFERENCES customers(id)
    )""")

    # ── LOYALTY TIERS ────────────────────────────────────
    c.execute("""CREATE TABLE IF NOT EXISTS loyalty_tiers (
        tier            TEXT PRIMARY KEY,
        min_points      INTEGER,
        min_nights_ytd  INTEGER,
        min_flights_ytd INTEGER,
        benefits        TEXT,  -- JSON
        next_tier       TEXT,
        points_multiplier REAL DEFAULT 1.0,
        lounge_access   INTEGER DEFAULT 0,
        priority_boarding INTEGER DEFAULT 0
    )""")

    # ── ANCILLARY CATALOGUE ───────────────────────────────
    c.execute("""CREATE TABLE IF NOT EXISTS ancillaries (
        id          TEXT PRIMARY KEY,
        category    TEXT,  -- room_upgrade|transfer|insurance|experience|equipment
        name        TEXT,
        description TEXT,
        price_gbp   REAL,
        conditions  TEXT,  -- JSON: when to auto-suggest
        loyalty_discount REAL DEFAULT 0.0
    )""")

    # ── RECOMMENDATIONS ───────────────────────────────────
    c.execute("""CREATE TABLE IF NOT EXISTS ai_recommendations (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id     TEXT,
        destination     TEXT,
        reason          TEXT,
        confidence      REAL,
        based_on        TEXT,  -- JSON: what triggered this
        created_at      TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    conn.commit()

    # ── SEED DATA ─────────────────────────────────────────
    _seed_tiers(c)
    _seed_ancillaries(c)
    _seed_customers(c)
    conn.commit()
    conn.close()
    print(f"✓ Database created at {DB_PATH}")


def _seed_tiers(c):
    tiers = [
        ("Blue", 0, 0, 0,
         json.dumps({"perks": ["Earn 1x points", "Online check-in", "Basic customer support"],
                     "room_upgrade_chance": "10%", "extra_baggage": "0kg",
                     "lounge_access": False, "priority_boarding": False,
                     "discount_pct": 0, "points_on_hotels": 1, "points_on_flights": 1}),
         "Silver", 1.0, 0, 0),

        ("Silver", 5000, 10, 4,
         json.dumps({"perks": ["Earn 1.5x points", "Priority check-in", "Dedicated phone line",
                               "10% hotel discount", "1 free seat upgrade/year"],
                     "room_upgrade_chance": "25%", "extra_baggage": "10kg",
                     "lounge_access": False, "priority_boarding": True,
                     "discount_pct": 10, "points_on_hotels": 2, "points_on_flights": 2}),
         "Gold", 1.5, 0, 1),

        ("Gold", 15000, 25, 10,
         json.dumps({"perks": ["Earn 2x points", "Airport lounge access", "Complimentary breakfast",
                               "20% hotel discount", "Free room upgrade", "Late checkout",
                               "Dedicated concierge", "Priority boarding"],
                     "room_upgrade_chance": "60%", "extra_baggage": "20kg",
                     "lounge_access": True, "priority_boarding": True,
                     "discount_pct": 20, "points_on_hotels": 3, "points_on_flights": 3}),
         "Platinum", 2.0, 1, 1),

        ("Platinum", 40000, 50, 20,
         json.dumps({"perks": ["Earn 3x points", "Priority everything", "Guaranteed suite upgrade",
                               "30% hotel discount", "Free companion flight", "Private transfer",
                               "Personal travel manager", "Global lounge access", "Meet & greet service"],
                     "room_upgrade_chance": "100%", "extra_baggage": "30kg",
                     "lounge_access": True, "priority_boarding": True,
                     "discount_pct": 30, "points_on_hotels": 5, "points_on_flights": 5}),
         None, 3.0, 1, 1),
    ]
    c.executemany("""INSERT OR REPLACE INTO loyalty_tiers
        (tier, min_points, min_nights_ytd, min_flights_ytd, benefits, next_tier,
         points_multiplier, lounge_access, priority_boarding)
        VALUES (?,?,?,?,?,?,?,?,?)""", tiers)


def _seed_ancillaries(c):
    items = [
        # Room upgrades
        ("RU001","room_upgrade","Junior Suite Upgrade",
         "Upgrade to a junior suite with separate lounge area",89.0,
         json.dumps({"suggest_when":["gold_member","long_stay","anniversary"]}),15.0),
        ("RU002","room_upgrade","Ocean/Pool View Room",
         "Room with guaranteed pool or sea view",45.0,
         json.dumps({"suggest_when":["summer","beach_destination","honeymoon"]}),10.0),
        ("RU003","room_upgrade","Executive Floor Access",
         "Executive floor with lounge, evening drinks, express checkout",65.0,
         json.dumps({"suggest_when":["business","platinum_member"]}),20.0),
        ("RU004","room_upgrade","Family Suite",
         "Connecting rooms or large suite for families",75.0,
         json.dumps({"suggest_when":["family_with_kids","guests_4_plus"]}),10.0),

        # Transfers
        ("TR001","transfer","Private Airport Transfer",
         "Luxury private car from airport to hotel, tracked flight",55.0,
         json.dumps({"suggest_when":["hotel_far_from_airport","late_night_arrival","first_visit"]}),0.0),
        ("TR002","transfer","Premium MPV Transfer (7 seats)",
         "Large luxury MPV for families or groups",85.0,
         json.dumps({"suggest_when":["family_with_kids","guests_5_plus","lots_of_luggage"]}),0.0),
        ("TR003","transfer","Shared Shuttle",
         "Economy shared shuttle — economical option",18.0,
         json.dumps({"suggest_when":["budget_conscious","solo_traveller"]}),0.0),
        ("TR004","transfer","Late Night Private Transfer",
         "Guaranteed private car for arrivals after 10pm",65.0,
         json.dumps({"suggest_when":["late_night_arrival","airport_far"]}),0.0),

        # Insurance
        ("IN001","insurance","Comprehensive Travel Insurance",
         "Full coverage: medical, cancellation, baggage, delay",48.0,
         json.dumps({"suggest_when":["always","family","adventure"]}),5.0),
        ("IN002","insurance","Premium Family Insurance",
         "Extended family coverage with kids activities included",85.0,
         json.dumps({"suggest_when":["family_with_kids"]}),5.0),
        ("IN003","insurance","Adventure Sports Cover",
         "Covers skiing, water sports, hiking, climbing",35.0,
         json.dumps({"suggest_when":["adventure_destination","ski_resort","water_sports"]}),0.0),

        # Experiences
        ("EX001","experience","Private City Tour (Half Day)",
         "Private guide, luxury vehicle, tailored itinerary",150.0,
         json.dumps({"suggest_when":["first_visit","gold_member","city_destination"]}),15.0),
        ("EX002","experience","Kids Club Day Pass",
         "Full day supervised kids activities, meals included",45.0,
         json.dumps({"suggest_when":["family_with_kids","resort_hotel"]}),0.0),
        ("EX003","experience","Romantic Dinner Package",
         "Private beachfront or rooftop dinner for two, wine",120.0,
         json.dumps({"suggest_when":["couple","honeymoon","anniversary"]}),0.0),
        ("EX004","experience","Surf/Water Sports Lesson",
         "2-hour beginner lesson with certified instructor",65.0,
         json.dumps({"suggest_when":["summer","beach_destination","adventure","young_adults"]}),0.0),
        ("EX005","experience","Theme Park Family Pass (2 days)",
         "Entry to top local theme parks, skip-the-line access",180.0,
         json.dumps({"suggest_when":["family_with_kids","city_destination"]}),0.0),
        ("EX006","experience","Spa Day (Couples)",
         "Full day spa access, massage and treatment included",160.0,
         json.dumps({"suggest_when":["couple","honeymoon","platinum_member"]}),15.0),

        # Equipment
        ("EQ001","equipment","Baby Equipment Pack",
         "Cot, highchair, pushchair, baby monitor at hotel",35.0,
         json.dumps({"suggest_when":["infant","family_with_kids","baby_under_2"]}),0.0),
        ("EQ002","equipment","Golf Club Hire (per round)",
         "Premium clubs, bag, trolley at resort course",55.0,
         json.dumps({"suggest_when":["golf_destination","platinum_member"]}),10.0),
    ]
    c.executemany("""INSERT OR REPLACE INTO ancillaries
        (id, category, name, description, price_gbp, conditions, loyalty_discount)
        VALUES (?,?,?,?,?,?,?)""", items)


def _seed_customers(c):
    customers = [
        # Customer 1 — Frequent family traveller, Gold loyalty
        {
            "id": "CUST001",
            "name": "Sarah Mitchell",
            "email": "sarah.mitchell@email.com",
            "phone": "+44 7700 900001",
            "passport_country": "GB",
            "date_of_birth": "1982-03-15",
            "adults_in_family": 2,
            "children_in_family": 2,
            "travel_style": "family",
            "preferences": json.dumps({
                "preferred_airlines": ["British Airways", "EasyJet"],
                "preferred_hotel_type": "resort",
                "min_hotel_stars": 4,
                "interests": ["beach", "kids_activities", "culture", "food"],
                "dietary": ["vegetarian"],
                "seat_preference": "aisle",
                "pool_required": True,
                "kids_club_important": True
            }),
            "loyalty": {
                "member_id": "VGI-GOLD-1001",
                "tier": "Gold",
                "points_balance": 18500,
                "points_ytd": 8200,
                "total_nights_ytd": 22,
                "total_flights_ytd": 8,
                "member_since": "2019-06-01",
                "tier_expiry": "2025-12-31"
            },
            "history": [
                ("Maldives", "MLE", "MV", "2024-02-10", "2024-02-20", 10, 4, "British Airways", "Niyama Private Islands", 5, 6800, "honeymoon", 5, ["spa", "private_transfer", "room_upgrade"]),
                ("Lisbon", "LIS", "PT", "2023-08-05", "2023-08-15", 10, 4, "TAP Air Portugal", "Bairro Alto Hotel", 5, 3200, "family", 5, ["kids_club", "city_tour", "insurance"]),
                ("Tenerife", "TFS", "ES", "2023-02-18", "2023-02-25", 7, 4, "EasyJet", "Bahía del Duque", 5, 2800, "family", 4, ["pool_view", "transfer", "insurance"]),
                ("Barcelona", "BCN", "ES", "2022-07-10", "2022-07-17", 7, 4, "Vueling", "Hotel Arts Barcelona", 5, 3100, "family", 5, ["kids_activities", "transfer"]),
                ("Dubai", "DXB", "AE", "2022-01-02", "2022-01-09", 7, 4, "Emirates", "Atlantis The Palm", 5, 4200, "family", 5, ["water_park", "transfer", "insurance"]),
                ("Cyprus", "LCA", "CY", "2021-08-07", "2021-08-21", 14, 4, "British Airways", "Elysium Hotel", 5, 2600, "family", 4, ["kids_club", "transfer"]),
            ]
        },

        # Customer 2 — Solo business traveller, Platinum
        {
            "id": "CUST002",
            "name": "James Okafor",
            "email": "james.okafor@corp.com",
            "phone": "+44 7700 900002",
            "passport_country": "GB",
            "date_of_birth": "1978-11-22",
            "adults_in_family": 1,
            "children_in_family": 0,
            "travel_style": "business",
            "preferences": json.dumps({
                "preferred_airlines": ["British Airways", "Lufthansa"],
                "preferred_hotel_type": "city_hotel",
                "min_hotel_stars": 5,
                "interests": ["fine_dining", "culture", "golf", "business"],
                "seat_preference": "window",
                "lounge_access": True,
                "priority_boarding": True,
                "suite_upgrade": True
            }),
            "loyalty": {
                "member_id": "VGI-PLAT-2001",
                "tier": "Platinum",
                "points_balance": 52000,
                "points_ytd": 24000,
                "total_nights_ytd": 68,
                "total_flights_ytd": 34,
                "member_since": "2016-03-15",
                "tier_expiry": "2025-12-31"
            },
            "history": [
                ("New York", "JFK", "US", "2024-09-15", "2024-09-22", 7, 1, "British Airways", "The Mark Hotel", 5, 5200, "business", 5, ["suite", "lounge", "golf", "concierge"]),
                ("Singapore", "SIN", "SG", "2024-06-01", "2024-06-08", 7, 1, "Singapore Airlines", "Marina Bay Sands", 5, 4800, "business", 5, ["suite", "spa", "fine_dining"]),
                ("Tokyo", "NRT", "JP", "2024-03-10", "2024-03-17", 7, 1, "Japan Airlines", "Park Hyatt Tokyo", 5, 5500, "business", 5, ["suite", "cultural_tour"]),
                ("Paris", "CDG", "FR", "2023-11-05", "2023-11-09", 4, 1, "Eurostar", "Le Bristol Paris", 5, 3200, "business", 4, ["suite", "restaurant"]),
                ("Dubai", "DXB", "AE", "2023-09-20", "2023-09-27", 7, 1, "Emirates", "Burj Al Arab", 5, 6800, "business", 5, ["suite", "beach_club", "golf"]),
                ("Zurich", "ZRH", "CH", "2023-07-03", "2023-07-08", 5, 1, "Swiss Air", "The Dolder Grand", 5, 4100, "business", 5, ["spa", "golf", "fine_dining"]),
            ]
        },

        # Customer 3 — Silver, cliff-edge case (almost Gold)
        {
            "id": "CUST003",
            "name": "Priya Sharma",
            "email": "priya.sharma@gmail.com",
            "phone": "+44 7700 900003",
            "passport_country": "GB",
            "date_of_birth": "1990-07-08",
            "adults_in_family": 2,
            "children_in_family": 0,
            "travel_style": "leisure",
            "preferences": json.dumps({
                "preferred_airlines": ["EasyJet", "Ryanair", "Jet2"],
                "preferred_hotel_type": "boutique",
                "min_hotel_stars": 4,
                "interests": ["culture", "food", "photography", "art", "wine"],
                "seat_preference": "window",
                "pool_required": False,
                "adventure_level": "moderate"
            }),
            "loyalty": {
                "member_id": "VGI-SILV-3001",
                "tier": "Silver",
                "points_balance": 13200,  # Gold threshold: 15000
                "points_ytd": 6800,
                "total_nights_ytd": 21,   # Gold threshold: 25 nights
                "total_flights_ytd": 8,   # Gold threshold: 10 flights
                "member_since": "2021-09-20",
                "tier_expiry": "2025-12-31"
            },
            "history": [
                ("Rome", "FCO", "IT", "2024-05-12", "2024-05-19", 7, 2, "EasyJet", "Hotel Eden", 5, 2100, "leisure", 5, ["city_tour", "food_tour"]),
                ("Santorini", "JTR", "GR", "2023-09-03", "2023-09-10", 7, 2, "British Airways", "Grace Santorini", 5, 2800, "leisure", 5, ["wine_tour", "sunset_cruise"]),
                ("Porto", "OPO", "PT", "2023-04-15", "2023-04-20", 5, 2, "Ryanair", "Torel Avantgarde", 4, 1200, "leisure", 4, ["wine_tour", "food_tour"]),
                ("Florence", "PSA", "IT", "2022-10-08", "2022-10-15", 7, 2, "EasyJet", "Portrait Firenze", 5, 2400, "leisure", 5, ["art_tour", "cooking_class"]),
                ("Lisbon", "LIS", "PT", "2022-06-18", "2022-06-25", 7, 2, "TAP Air Portugal", "Bairro Alto Hotel", 5, 1900, "leisure", 4, ["city_tour", "food_tour"]),
            ]
        },

        # Customer 4 — Adventure traveller, Blue (new member)
        {
            "id": "CUST004",
            "name": "Tom Bradley",
            "email": "tom.bradley@email.com",
            "phone": "+44 7700 900004",
            "passport_country": "GB",
            "date_of_birth": "1995-04-12",
            "adults_in_family": 1,
            "children_in_family": 0,
            "travel_style": "adventure",
            "preferences": json.dumps({
                "preferred_airlines": ["Any"],
                "preferred_hotel_type": "hostel_or_boutique",
                "min_hotel_stars": 3,
                "interests": ["hiking", "surfing", "diving", "backpacking", "local_culture"],
                "budget_sensitive": True,
                "adventure_level": "extreme"
            }),
            "loyalty": {
                "member_id": "VGI-BLUE-4001",
                "tier": "Blue",
                "points_balance": 1800,
                "points_ytd": 1800,
                "total_nights_ytd": 6,
                "total_flights_ytd": 3,
                "member_since": "2024-01-15",
                "tier_expiry": "2025-12-31"
            },
            "history": [
                ("Bali", "DPS", "ID", "2024-07-20", "2024-08-03", 14, 1, "KLM", "Potato Head Suites", 4, 1400, "adventure", 5, ["surf_lesson", "diving", "motorbike_hire"]),
                ("Thailand", "BKK", "TH", "2023-12-26", "2024-01-08", 13, 1, "Thai Airways", "Various Hostels", 3, 900, "adventure", 4, ["elephant_sanctuary", "cooking_class"]),
                ("Morocco", "CMN", "MA", "2023-05-01", "2023-05-10", 9, 1, "Ryanair", "Riad El Fenn", 4, 1100, "adventure", 5, ["desert_tour", "cooking_class"]),
            ]
        },

        # Customer 5 — Couple, Gold, honeymoon travellers
        {
            "id": "CUST005",
            "name": "Emma & Daniel Clarke",
            "email": "emma.clarke@email.com",
            "phone": "+44 7700 900005",
            "passport_country": "GB",
            "date_of_birth": "1988-12-03",
            "adults_in_family": 2,
            "children_in_family": 0,
            "travel_style": "leisure",
            "preferences": json.dumps({
                "preferred_airlines": ["British Airways", "Emirates"],
                "preferred_hotel_type": "resort",
                "min_hotel_stars": 5,
                "interests": ["beach", "spa", "fine_dining", "romance", "snorkelling"],
                "romantic_packages": True,
                "pool_required": True,
                "adventure_level": "low"
            }),
            "loyalty": {
                "member_id": "VGI-GOLD-5001",
                "tier": "Gold",
                "points_balance": 22000,
                "points_ytd": 9500,
                "total_nights_ytd": 28,
                "total_flights_ytd": 10,
                "member_since": "2020-08-10",
                "tier_expiry": "2025-12-31"
            },
            "history": [
                ("Seychelles", "SEZ", "SC", "2024-04-20", "2024-05-04", 14, 2, "Emirates", "MAIA Luxury Resort", 5, 9200, "honeymoon", 5, ["villa", "spa", "private_dining", "snorkelling"]),
                ("Amalfi Coast", "NAP", "IT", "2023-09-15", "2023-09-25", 10, 2, "British Airways", "Belmond Hotel Caruso", 5, 5800, "leisure", 5, ["boat_tour", "cooking_class", "spa"]),
                ("Mauritius", "MRU", "MU", "2023-02-01", "2023-02-15", 14, 2, "British Airways", "One&Only Le Saint Géran", 5, 7800, "leisure", 5, ["spa", "water_sports", "sunset_cruise"]),
                ("Maldives", "MLE", "MV", "2022-01-15", "2022-01-29", 14, 2, "Emirates", "Soneva Jani", 5, 12000, "honeymoon", 5, ["overwater_villa", "spa", "dolphin_cruise"]),
                ("Bali", "DPS", "ID", "2021-10-10", "2021-10-24", 14, 2, "Singapore Airlines", "COMO Shambhala", 5, 5500, "leisure", 5, ["spa", "yoga", "cultural_tour"]),
            ]
        },
    ]

    for cust in customers:
        # Insert customer
        prefs = cust["preferences"]
        c.execute("""INSERT OR REPLACE INTO customers
            (id, name, email, phone, passport_country, date_of_birth,
             adults_in_family, children_in_family, travel_style, preferences)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (cust["id"], cust["name"], cust["email"], cust["phone"],
             cust["passport_country"], cust["date_of_birth"],
             cust["adults_in_family"], cust["children_in_family"],
             cust["travel_style"], prefs))

        # Insert loyalty
        loy = cust["loyalty"]
        c.execute("""INSERT OR REPLACE INTO loyalty_accounts
            (customer_id, member_id, tier, points_balance, points_ytd,
             total_nights_ytd, total_flights_ytd, member_since, tier_expiry)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (cust["id"], loy["member_id"], loy["tier"], loy["points_balance"],
             loy["points_ytd"], loy["total_nights_ytd"], loy["total_flights_ytd"],
             loy["member_since"], loy["tier_expiry"]))

        # Insert history
        for h in cust["history"]:
            c.execute("""INSERT INTO travel_history
                (customer_id, destination, city_code, country_code, departure_date,
                 return_date, nights, guests, airline, hotel_name, hotel_stars,
                 total_spent_gbp, trip_type, rating, ancillaries)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cust["id"], *h[:-1], json.dumps(h[-1])))


if __name__ == "__main__":
    init_db()
