"""
VoyageAI Guardrail Config Loader
==================================
Loads ALL guardrail configuration from Python dicts into SQLite tables.
No more hardcoded lists in guardrail code — everything lives here and is
read at startup from the DB.

Tables created:
  guardrail_config        — key/value settings (thresholds, limits)
  guardrail_skip_codes    — 3-letter codes to skip in IATA validation
  guardrail_injection_patterns — prompt injection regex patterns
  guardrail_travel_signals     — words that indicate a travel query
  guardrail_schema_rules       — required/optional JSON fields

Run:
  python data/load_guardrail_config.py              # full load
  python data/load_guardrail_config.py --stats      # show counts
  python data/load_guardrail_config.py --lookup ENGLISH_WORD
"""
import os, sys, sqlite3, json, argparse, time
from pathlib import Path

HERE    = Path(__file__).parent
DB_PATH = HERE / "voyageai.db"


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ── Schema ────────────────────────────────────────────────────────────────────

def create_tables(conn):
    conn.executescript("""
        -- Numeric/string guardrail settings (replaces Config class constants)
        CREATE TABLE IF NOT EXISTS guardrail_config (
            key         TEXT PRIMARY KEY,
            value       TEXT NOT NULL,
            dtype       TEXT NOT NULL DEFAULT 'float',  -- float | int | str | bool
            description TEXT,
            updated_at  REAL NOT NULL
        );

        -- 3-letter codes to skip in IATA validation
        -- category: ENGLISH | TECH | AIRPORT | AIRLINE | HOTEL | ROOM_TYPE | COUNTRY_ABBREV
        CREATE TABLE IF NOT EXISTS guardrail_skip_codes (
            code        TEXT NOT NULL,
            category    TEXT NOT NULL,
            description TEXT,
            updated_at  REAL NOT NULL,
            PRIMARY KEY (code, category)
        );

        -- Prompt injection detection patterns (regex)
        CREATE TABLE IF NOT EXISTS guardrail_injection_patterns (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern     TEXT NOT NULL UNIQUE,
            description TEXT,
            enabled     INTEGER NOT NULL DEFAULT 1,
            updated_at  REAL NOT NULL
        );

        -- Keywords that indicate a travel-domain query
        CREATE TABLE IF NOT EXISTS guardrail_travel_signals (
            signal      TEXT PRIMARY KEY,
            category    TEXT NOT NULL,  -- CORE | MODIFICATION | DESTINATION
            updated_at  REAL NOT NULL
        );

        -- JSON schema rules for LLM output validation
        CREATE TABLE IF NOT EXISTS guardrail_schema_rules (
            field_path  TEXT PRIMARY KEY,  -- e.g. "intent.destination"
            required    INTEGER NOT NULL DEFAULT 1,
            dtype       TEXT NOT NULL,     -- str | int | float | list | object
            min_val     TEXT,
            max_val     TEXT,
            min_length  INTEGER,
            description TEXT,
            updated_at  REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_skip_category ON guardrail_skip_codes(category);
        CREATE INDEX IF NOT EXISTS idx_travel_cat    ON guardrail_travel_signals(category);
    """)
    conn.commit()
    print("  + Tables created/verified")


# ── Data definitions ──────────────────────────────────────────────────────────

GUARDRAIL_CONFIG = {
    # Thresholds
    "CONFIDENCE_THRESHOLD":  ("0.72",  "float", "Min LLM confidence to return itinerary"),
    "FACTUAL_ACCURACY_MIN":  ("0.80",  "float", "Min fraction of IATA codes that must be valid"),
    "PRICE_DRIFT_LIMIT":     ("1.50",  "float", "Max ± fraction flight price can differ from MCP range"),
    "MAX_BUDGET_OVERSHOOT":  ("0.50",  "float", "Max fraction total can exceed requested budget before blocking"),
    "RAG_SIMILARITY_THRESHOLD":("0.75","float", "Min cosine similarity for RAG memory retrieval"),

    # Limits
    "MAX_INPUT_TOKENS":      ("512",   "int",   "Max words in a user message"),
    "MAX_RETRY_ITERATIONS":  ("3",     "int",   "Max reasoning engine retries before human handoff"),
    "HIGH_VALUE_THRESHOLD":  ("1000",  "float", "Booking total (GBP) requiring user confirmation"),
    "MIN_CONNECTION_MINUTES":("45",    "int",   "Min connecting flight layover in minutes"),
    "SESSION_TTL_SECONDS":   ("1800",  "int",   "Inactivity timeout for in-memory session"),
    "GDS_SESSION_TIMEOUT":   ("600",   "int",   "GDS fare quote expiry in seconds"),

    # LLM
    "LLM_MAX_TOKENS":        ("2048",  "int",   "Max output tokens per LLM call"),
    "LLM_TEMPERATURE":       ("0.1",   "float", "LLM sampling temperature"),
    "LLM_TIMEOUT_S":         ("20",    "int",   "HTTP timeout for LLM API calls in seconds"),
    "LLM_WATERFALL":         ('["groq","gemini","anthropic","template"]', "str",
                              "Ordered list of LLM providers to try"),
}

SKIP_CODES = {
    # category → list of (code, description)
    "ENGLISH": [
        ("THE","definite article"), ("AND","conjunction"), ("FOR","preposition"),
        ("NOT","negation"), ("BUT","conjunction"), ("YOU","pronoun"), ("HIS","pronoun"),
        ("HER","pronoun"), ("CAN","modal verb"), ("ALL","quantifier"), ("ARE","verb"),
        ("WAS","verb"), ("HAS","verb"), ("HAD","verb"), ("ITS","possessive"),
        ("ONE","numeral"), ("OUT","adverb"), ("WHO","pronoun"), ("GET","verb"),
        ("GOT","verb"), ("SET","verb"), ("YES","affirmation"), ("NOW","adverb"),
        ("OLD","adjective"), ("NEW","adjective"), ("OWN","adjective"), ("USE","verb"),
        ("DAY","noun"), ("WAY","noun"), ("MAY","modal verb"), ("SAY","verb"),
        ("SEE","verb"), ("HOW","adverb"), ("OUR","pronoun"), ("ANY","quantifier"),
        ("FAR","adverb"), ("FEW","quantifier"), ("BIG","adjective"), ("DID","verb"),
        ("CAR","noun"), ("END","noun"), ("JOB","noun"), ("LET","verb"), ("PUT","verb"),
        ("RUN","verb"), ("INN","noun"), ("AIR","noun"), ("SKY","noun"), ("SEA","noun"),
        ("BAY","noun"), ("SUN","noun"), ("TOP","noun"), ("GEM","noun"), ("MAP","noun"),
        ("KEY","noun"), ("ACE","noun"), ("AGE","noun"), ("AIM","noun"), ("ARM","noun"),
        ("ART","noun"), ("BAD","adjective"), ("BED","noun"), ("BOX","noun"),
        ("BOY","noun"), ("BUS","noun"), ("CUP","noun"), ("CUT","verb"), ("DOG","noun"),
        ("DRY","adjective"), ("EAR","noun"), ("EYE","noun"), ("FIT","adjective"),
        ("FLY","verb"), ("FUN","noun"), ("GAP","noun"), ("GAS","noun"), ("GUN","noun"),
        ("HAT","noun"), ("HIT","verb"), ("HOT","adjective"), ("HUG","verb"),
        ("HIT","verb"), ("HOP","verb"), ("ICE","noun"), ("INK","noun"), ("JAM","noun"),
        ("JAW","noun"), ("LAW","noun"), ("LAY","verb"), ("LEG","noun"), ("LID","noun"),
        ("LIP","noun"), ("LOG","noun"), ("LOT","noun"), ("LOW","adjective"),
        ("MAN","noun"), ("MIX","verb"), ("MOB","noun"), ("MOP","noun"), ("MUD","noun"),
        ("NAP","noun"), ("NET","noun"), ("NIT","noun"), ("NUT","noun"), ("OAK","noun"),
        ("ODD","adjective"), ("OIL","noun"), ("ORB","noun"), ("ORE","noun"),
        ("OWL","noun"), ("PAD","noun"), ("PAN","noun"), ("PAW","noun"), ("PEA","noun"),
        ("PEN","noun"), ("PET","noun"), ("PIE","noun"), ("PIG","noun"), ("PIN","noun"),
        ("PIT","noun"), ("POD","noun"), ("POT","noun"), ("POW","exclamation"),
        ("PUB","noun"), ("RAG","noun"), ("RAM","noun"), ("RAP","noun"), ("RAW","adjective"),
        ("RAY","noun"), ("RIB","noun"), ("RIG","noun"), ("RIP","verb"), ("ROB","verb"),
        ("ROD","noun"), ("ROT","verb"), ("ROW","noun"), ("RUB","verb"), ("SAC","noun"),
        ("SAP","noun"), ("SAT","verb"), ("SAW","verb"), ("SAX","noun"), ("SIP","verb"),
        ("SIT","verb"), ("SIX","numeral"), ("SKI","verb"), ("SKY","noun"),
        ("SLY","adjective"), ("SOB","verb"), ("SOD","noun"), ("SOL","noun"),
        ("SOP","noun"), ("SOT","noun"), ("SOW","verb"), ("SOY","noun"), ("SPA","noun"),
        ("SPY","verb"), ("STY","noun"), ("SUB","noun"), ("SUM","noun"), ("TAN","noun"),
        ("TAP","verb"), ("TAR","noun"), ("TEN","numeral"), ("TIP","noun"), ("TOE","noun"),
        ("TON","noun"), ("TOO","adverb"), ("TOR","noun"), ("TOW","verb"), ("TOY","noun"),
        ("TUB","noun"), ("TUG","verb"), ("TUP","noun"), ("URN","noun"), ("VAT","noun"),
        ("VET","noun"), ("VIA","preposition"), ("VIE","verb"), ("WAR","noun"),
        ("WAS","verb"), ("WAX","noun"), ("WEB","noun"), ("WED","verb"), ("WIG","noun"),
        ("WIN","verb"), ("WIT","noun"), ("WOE","noun"), ("WOK","noun"), ("WON","verb"),
        ("WOO","verb"), ("YAK","noun"), ("YAM","noun"), ("YAP","verb"), ("YAW","verb"),
        ("YEW","noun"), ("ZAP","verb"), ("ZEN","noun"), ("ZIT","noun"), ("ZOO","noun"),
    ],
    "TECH": [
        ("LLM","Large Language Model"), ("MCP","Model Context Protocol"),
        ("RAG","Retrieval Augmented Generation"), ("GDS","Global Distribution System"),
        ("API","Application Programming Interface"), ("URL","Uniform Resource Locator"),
        ("PDF","Portable Document Format"), ("CSS","Cascading Style Sheets"),
        ("ETA","Estimated Time of Arrival"), ("VIP","Very Important Person"),
        ("TBC","To Be Confirmed"), ("TBD","To Be Determined"), ("PRO","Professional"),
        ("GDP","Gross Domestic Product"), ("VAT","Value Added Tax"), ("TAX","Taxation"),
        ("SLA","Service Level Agreement"), ("ROI","Return on Investment"),
        ("KPI","Key Performance Indicator"), ("CRM","Customer Relationship Management"),
        ("SRC","Source"), ("DST","Destination code context"), ("DEP","Departure context"),
        ("ARR","Arrival context"), ("DUR","Duration"), ("LEG","Flight leg"),
        ("PAX","Passengers"), ("ADT","Adult"), ("CHD","Child"), ("INF","Infant"),
        ("GPS","Global Positioning System"), ("ETD","Estimated Time of Departure"),
        ("MON","Monday abbrev"), ("TUE","Tuesday abbrev"), ("WED","Wednesday abbrev"),
        ("THU","Thursday abbrev"), ("FRI","Friday abbrev"), ("SAT","Saturday abbrev"),
        ("SUN","Sunday abbrev"), ("JAN","January"), ("FEB","February"), ("MAR","March"),
        ("APR","April"), ("JUN","June"), ("JUL","July"), ("AUG","August"),
        ("SEP","September"), ("OCT","October"), ("NOV","November"), ("DEC","December"),
    ],
    "AIRLINE": [
        ("TAP","TAP Air Portugal"), ("BAW","British Airways ICAO"),
        ("EZY","EasyJet"), ("RYR","Ryanair"), ("IBE","Iberia"),
        ("KLM","KLM Royal Dutch"), ("AFR","Air France"), ("DLH","Lufthansa"),
        ("AZA","Alitalia ITA"), ("TOM","TUI/Thomson"), ("SAS","Scandinavian Airlines"),
        ("NAX","Norwegian Air"), ("UAE","Emirates ICAO"), ("ETD","Etihad Airways"),
        ("QTR","Qatar Airways"), ("FIN","Finnair"), ("AAL","American Airlines"),
        ("DAL","Delta Airlines"), ("UAL","United Airlines"), ("BAA","British Airport Authority"),
        ("VIR","Virgin Atlantic"), ("MON","Monarch Airlines"), ("TUI","TUI Group"),
        ("TCX","Thomas Cook"), ("WZZ","Wizz Air"), ("LOT","LOT Polish Airlines"),
        ("AIC","Air India ICAO"), ("AIX","Air India Express"),
        ("THA","Thai Airways ICAO"), ("SIA","Singapore Airlines ICAO"),
        ("MAS","Malaysia Airlines ICAO"), ("EVA","EVA Air"), ("CAL","China Airlines"),
        ("ANA","All Nippon Airways"), ("JAL","Japan Airlines"), ("CES","China Eastern"),
        ("CSN","China Southern"), ("HVN","Vietnam Airlines"), ("SWR","Swiss ICAO"),
        ("AUA","Austrian Airlines"), ("BEL","Brussels Airlines"),
    ],
    "HOTEL_BRAND": [
        ("ITC","ITC Hotels India"), ("TAJ","Taj Hotels"), ("OBR","Oberoi Hotels"),
        ("LEM","Lemon Tree Hotels"), ("ADR","Adaaran Hotels"),
        ("HYT","Hyatt Hotels ICAO-like"), ("MAR","Marriott"), ("IHG","InterContinental"),
        ("ACC","Accor Hotels"), ("WIN","Wyndham"), ("SHO","Shangri-La"),
        ("AND","Anantara Hotels"), ("LHW","Leading Hotels of the World"),
        ("SMH","Small Luxury Hotels"), ("FHR","Four Seasons"), ("GHA","Global Hotel Alliance"),
        ("YTL","YTL Hotels"), ("AMA","Aman Resorts"), ("OAS","Oasis Hotels"),
        ("REL","Relais & Chateaux"), ("RHC","Rosewood Hotels"), ("BGN","Banyan Tree"),
        ("SON","Soneva Resorts"), ("COA","Constance Hotels"), ("LMB","Lembeh Resorts"),
    ],
    "ROOM_TYPE": [
        ("STD","Standard"), ("DBL","Double"), ("TWN","Twin"), ("SGL","Single"),
        ("FAM","Family"), ("SUI","Suite"), ("EXE","Executive"), ("PRE","Premier"),
        ("DLX","Deluxe"), ("SPA","Spa suite"), ("PNT","Penthouse"), ("VIL","Villa"),
        ("STU","Studio"), ("OVR","Overwater"), ("BCH","Beach"), ("CLB","Club"),
    ],
    "COUNTRY_ABBREV": [
        ("UAE","United Arab Emirates"), ("KSA","Kingdom of Saudi Arabia"),
        ("USA","United States of America"), ("GBR","Great Britain"),
        ("CHN","China"), ("JPN","Japan"), ("KOR","Korea"),
        ("AUS","Australia"), ("NZL","New Zealand"), ("IND","India"),
        ("PAK","Pakistan"), ("BGD","Bangladesh"), ("LKA","Sri Lanka"),
        ("THA","Thailand"), ("IDN","Indonesia"), ("MYS","Malaysia"),
        ("PHL","Philippines"), ("VNM","Vietnam"), ("ZAF","South Africa"),
        ("KEN","Kenya"), ("TZA","Tanzania"), ("ETH","Ethiopia"), ("NGA","Nigeria"),
        ("GHA","Ghana"), ("MAR","Morocco"), ("TUN","Tunisia"), ("TUR","Turkey"),
        ("ISR","Israel"), ("JOR","Jordan"), ("LBN","Lebanon"), ("IRN","Iran"),
        ("IRQ","Iraq"), ("SYR","Syria"), ("YEM","Yemen"), ("FRA","France"),
        ("DEU","Germany"), ("ITA","Italy"), ("ESP","Spain"), ("PRT","Portugal"),
        ("GRC","Greece"), ("NLD","Netherlands"), ("BEL","Belgium"), ("CHE","Switzerland"),
        ("AUT","Austria"), ("POL","Poland"), ("CZE","Czech Republic"),
        ("HUN","Hungary"), ("ROU","Romania"), ("BGR","Bulgaria"), ("HRV","Croatia"),
        ("SRB","Serbia"), ("UKR","Ukraine"), ("BLR","Belarus"), ("RUS","Russia"),
    ],
}

INJECTION_PATTERNS = [
    (r"ignore\s+(?:previous|all)\s+instructions?", "Instruction override attempt"),
    (r"you\s+are\s+now",                           "Identity override"),
    (r"pretend\s+you\s+are",                       "Persona hijacking"),
    (r"disregard\s+your",                          "Instruction dismissal"),
    (r"new\s+system\s+prompt",                     "System prompt injection"),
    (r"act\s+as\s+if",                             "Conditional persona"),
    (r"forget\s+everything",                       "Memory wipe attempt"),
    (r"jailbreak",                                 "Explicit jailbreak"),
    (r"DAN\s+mode",                                "Do Anything Now mode"),
    (r"override\s+safety",                         "Safety override"),
    (r"developer\s+mode",                          "Developer mode exploit"),
    (r"sudo\s+mode",                               "Sudo mode exploit"),
    (r"enable\s+unrestricted",                     "Restriction bypass"),
    (r"without\s+restrictions?",                   "Restriction bypass variant"),
]

TRAVEL_SIGNALS = {
    # category → list of signals
    "CORE": [
        "flight","hotel","trip","travel","holiday","vacation","book","journey",
        "destination","airport","visa","passport","accommodation","transfer",
        "car","experience","tour","plan","weather","currency","budget","night",
        "check.?in","check.?out","family","adult","child","passenger","ticket",
        "itinerary","resort","cruise","ski","beach","city","abroad","overseas",
        "depart","arrive","return","stay","nights","weeks","days",
    ],
    "MODIFICATION": [
        "change","update","modify","instead","different","cheaper","upgrade",
        "earlier","later","fewer","more","reschedule","amend","adjust","keep",
        "same but","dates","guests","people","person","rooms","stars",
        "what if","how about","what about","actually","rather",
    ],
    "DESTINATION": [
        "go to","fly to","visit","explore","see","discover","where",
        "suggest","recommend","find","show","holy place","sacred site",
        "pilgrimage","retreat","safari","adventure",
    ],
}

SCHEMA_RULES = [
    # (field_path, required, dtype, min_val, max_val, min_length, description)
    ("intent",                   1, "object",  None,  None, None, "Trip intent block"),
    ("intent.destination",       1, "str",     None,  None, 2,    "Destination city name"),
    ("intent.city_code",         1, "str",     None,  None, 3,    "IATA airport code"),
    ("intent.dates",             1, "object",  None,  None, None, "Date block"),
    ("intent.dates.departure_date",1,"str",    None,  None, 10,   "ISO departure date"),
    ("intent.dates.nights",      1, "int",     "1",   "365",None, "Duration in nights"),
    ("intent.guests",            1, "int",     "1",   "20", None, "Total guest count"),
    ("intent.budget_gbp",        1, "float",   "0",   None, None, "Budget in GBP"),
    ("intent.adults",            0, "int",     "0",   "20", None, "Adult count"),
    ("intent.children",          0, "int",     "0",   "10", None, "Children count"),
    ("recommendations",          1, "object",  None,  None, None, "MCP recommendations"),
    ("recommendations.flights",  1, "list",    None,  None, None, "Flight options"),
    ("recommendations.hotels",   1, "list",    None,  None, None, "Hotel options"),
    ("total_cost_gbp",           1, "float",   "0",   None, None, "Total cost in GBP"),
    ("summary",                  1, "str",     None,  None, 10,   "Human-readable summary"),
    ("confidence_scores",        0, "object",  None,  None, None, "Confidence scores"),
    ("confidence_scores.overall",0, "float",   "0",   "1",  None, "Overall confidence 0-1"),
]


# ── Loader functions ──────────────────────────────────────────────────────────

def load_config(conn):
    now = time.time()
    conn.execute("DELETE FROM guardrail_config")
    conn.executemany(
        "INSERT OR REPLACE INTO guardrail_config (key,value,dtype,description,updated_at) VALUES (?,?,?,?,?)",
        [(k, v, dtype, desc, now) for k, (v, dtype, desc) in GUARDRAIL_CONFIG.items()]
    )
    conn.commit()
    return len(GUARDRAIL_CONFIG)


def load_skip_codes(conn):
    now = time.time()
    conn.execute("DELETE FROM guardrail_skip_codes")
    rows = []
    for category, items in SKIP_CODES.items():
        for code, desc in items:
            rows.append((code.upper(), category, desc, now))
    conn.executemany(
        "INSERT OR REPLACE INTO guardrail_skip_codes (code,category,description,updated_at) VALUES (?,?,?,?)",
        rows
    )
    conn.commit()
    return len(rows)


def load_injection_patterns(conn):
    now = time.time()
    conn.execute("DELETE FROM guardrail_injection_patterns")
    conn.executemany(
        "INSERT OR REPLACE INTO guardrail_injection_patterns (pattern,description,enabled,updated_at) VALUES (?,?,1,?)",
        [(pat, desc, now) for pat, desc in INJECTION_PATTERNS]
    )
    conn.commit()
    return len(INJECTION_PATTERNS)


def load_travel_signals(conn):
    now = time.time()
    conn.execute("DELETE FROM guardrail_travel_signals")
    rows = []
    for category, signals in TRAVEL_SIGNALS.items():
        for signal in signals:
            rows.append((signal, category, now))
    conn.executemany(
        "INSERT OR REPLACE INTO guardrail_travel_signals (signal,category,updated_at) VALUES (?,?,?)",
        rows
    )
    conn.commit()
    return len(rows)


def load_schema_rules(conn):
    now = time.time()
    conn.execute("DELETE FROM guardrail_schema_rules")
    conn.executemany(
        "INSERT OR REPLACE INTO guardrail_schema_rules "
        "(field_path,required,dtype,min_val,max_val,min_length,description,updated_at) VALUES (?,?,?,?,?,?,?,?)",
        [(path, req, dtype, mn, mx, ml, desc, now) for path,req,dtype,mn,mx,ml,desc in SCHEMA_RULES]
    )
    conn.commit()
    return len(SCHEMA_RULES)


def show_stats(conn):
    print("\n  Guardrail Config Stats:")
    tables = [
        "guardrail_config", "guardrail_skip_codes",
        "guardrail_injection_patterns", "guardrail_travel_signals", "guardrail_schema_rules"
    ]
    for t in tables:
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"    {t:<40} {n:>4} rows")
    print()
    print("  Sample config values:")
    for row in conn.execute("SELECT key,value,dtype FROM guardrail_config LIMIT 8"):
        print(f"    {row['key']:<35} = {row['value']} ({row['dtype']})")
    print()
    cats = conn.execute("SELECT category, COUNT(*) as n FROM guardrail_skip_codes GROUP BY category").fetchall()
    print("  Skip code categories:")
    for row in cats:
        print(f"    {row['category']:<20} {row['n']} codes")


def lookup(conn, query):
    q = query.upper().strip()
    print(f"\n  Lookup: '{q}'")
    row = conn.execute("SELECT * FROM guardrail_skip_codes WHERE code=?", (q,)).fetchone()
    if row:
        print(f"  SKIP CODE: category={row['category']} description={row['description']}")
    row = conn.execute("SELECT * FROM guardrail_config WHERE key=?", (q,)).fetchone()
    if row:
        print(f"  CONFIG: {row['key']} = {row['value']} ({row['dtype']}) — {row['description']}")
    if not row:
        print("  Not found in guardrail tables.")


def main():
    p = argparse.ArgumentParser(description="VoyageAI Guardrail Config Loader")
    p.add_argument("--stats",  action="store_true")
    p.add_argument("--lookup", metavar="KEY")
    args = p.parse_args()

    print(f"VoyageAI Guardrail Config Loader  DB={DB_PATH}")
    conn = get_db()
    create_tables(conn)

    if args.stats:
        show_stats(conn); conn.close(); return
    if args.lookup:
        lookup(conn, args.lookup); conn.close(); return

    print("Loading guardrail configuration...")
    t0 = time.perf_counter()
    n1 = load_config(conn);            print(f"  + guardrail_config:              {n1}")
    n2 = load_skip_codes(conn);        print(f"  + guardrail_skip_codes:          {n2}")
    n3 = load_injection_patterns(conn);print(f"  + guardrail_injection_patterns:  {n3}")
    n4 = load_travel_signals(conn);    print(f"  + guardrail_travel_signals:      {n4}")
    n5 = load_schema_rules(conn);      print(f"  + guardrail_schema_rules:        {n5}")
    ms = round((time.perf_counter()-t0)*1000, 1)
    print(f"\n  Loaded in {ms}ms")
    show_stats(conn)
    conn.close()
    print("Done. Restart server to apply new config.")


if __name__ == "__main__":
    main()
