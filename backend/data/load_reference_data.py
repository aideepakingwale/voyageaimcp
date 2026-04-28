"""
VoyageAI Reference Data Loader — run: python data/load_reference_data.py
Loads data/reference_data.py into SQLite ref_* tables in voyageai.db
Options:
  (no args)       full load
  --stats         show table counts and sample lookups
  --lookup CODE   look up any code (IATA / ISO currency / country)
"""
import os, sys, sqlite3, time, argparse
from pathlib import Path

HERE    = Path(__file__).parent
DB_PATH = HERE / "voyageai.db"


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def create_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ref_airports (
            iata         TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            city         TEXT NOT NULL,
            country_code TEXT NOT NULL,
            lat          REAL,
            lon          REAL,
            updated_at   REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ref_currencies (
            code       TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            symbol     TEXT NOT NULL,
            decimals   INTEGER NOT NULL DEFAULT 2,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ref_countries (
            code         TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            currency     TEXT NOT NULL,
            main_airport TEXT,
            updated_at   REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ref_city_iata (
            alias      TEXT PRIMARY KEY,
            iata       TEXT NOT NULL,
            source     TEXT NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ref_gbp_rates (
            currency   TEXT PRIMARY KEY,
            rate       REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ap_country  ON ref_airports(country_code);
        CREATE INDEX IF NOT EXISTS idx_ap_city     ON ref_airports(city);
        CREATE INDEX IF NOT EXISTS idx_ctr_cur     ON ref_countries(currency);
    """)
    conn.commit()
    print("  + Tables created/verified")


def load_all(conn, AIRPORTS, CURRENCIES, COUNTRIES, GBP_FALLBACK_RATES):
    now = time.time()

    # Airports
    conn.execute("DELETE FROM ref_airports")
    conn.executemany(
        "INSERT OR REPLACE INTO ref_airports VALUES (?,?,?,?,?,?,?)",
        [(k,v["name"],v["city"],v["country_code"],
          v.get("lat"),v.get("lon"),now) for k,v in AIRPORTS.items()]
    )
    print(f"  + Airports:    {len(AIRPORTS)}")

    # Currencies
    conn.execute("DELETE FROM ref_currencies")
    conn.executemany(
        "INSERT OR REPLACE INTO ref_currencies VALUES (?,?,?,?,?)",
        [(k,v["name"],v["symbol"],v.get("decimals",2),now) for k,v in CURRENCIES.items()]
    )
    print(f"  + Currencies:  {len(CURRENCIES)}")

    # Countries
    conn.execute("DELETE FROM ref_countries")
    conn.executemany(
        "INSERT OR REPLACE INTO ref_countries VALUES (?,?,?,?,?)",
        [(k,v["name"],v["currency"],v.get("main_airport"),now) for k,v in COUNTRIES.items()]
    )
    print(f"  + Countries:   {len(COUNTRIES)}")

    # City aliases (derived)
    aliases = {}
    for iata, info in AIRPORTS.items():
        city = info.get("city","")
        if city:
            aliases[city.lower()] = (iata,"airport_city")
            nospace = city.lower().replace(" ","")
            if nospace != city.lower():
                aliases[nospace] = (iata,"airport_nospace")
            name = info.get("name","").lower()
            if name: aliases[name] = (iata,"airport_name")
    for cc, info in COUNTRIES.items():
        name = info.get("name","").lower()
        airport = info.get("main_airport","")
        if name and airport:
            aliases[name] = (airport,"country_name")
    conn.execute("DELETE FROM ref_city_iata")
    conn.executemany(
        "INSERT OR REPLACE INTO ref_city_iata VALUES (?,?,?,?)",
        [(alias,iata,src,now) for alias,(iata,src) in aliases.items()]
    )
    print(f"  + City aliases:{len(aliases)}")

    # GBP rates
    conn.execute("DELETE FROM ref_gbp_rates")
    conn.executemany(
        "INSERT OR REPLACE INTO ref_gbp_rates VALUES (?,?,?)",
        [(k,v,now) for k,v in GBP_FALLBACK_RATES.items()]
    )
    print(f"  + GBP rates:   {len(GBP_FALLBACK_RATES)}")

    conn.commit()


def show_stats(conn):
    print("\n  DB Stats:")
    for t in ["ref_airports","ref_currencies","ref_countries","ref_city_iata","ref_gbp_rates"]:
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"    {t:<22} {n:>5} rows")
    print()
    tests = [
        ("Airport DXB",   "SELECT name,city,country_code FROM ref_airports WHERE iata='DXB'"),
        ("Currency AED",  "SELECT name,symbol FROM ref_currencies WHERE code='AED'"),
        ("Country AE",    "SELECT name,currency FROM ref_countries WHERE code='AE'"),
        ("City alias 'dubai'", "SELECT iata,source FROM ref_city_iata WHERE alias='dubai'"),
        ("GBP→AED rate",  "SELECT rate FROM ref_gbp_rates WHERE currency='AED'"),
    ]
    print("  Samples:")
    for label, sql in tests:
        row = conn.execute(sql).fetchone()
        print(f"    {label:<25} {dict(row) if row else 'NOT FOUND'}")


def lookup(conn, query):
    q = query.strip().upper()
    print(f"\n  Lookup: {query!r}")
    for table, col, label in [
        ("ref_airports",  "iata", "AIRPORT"),
        ("ref_currencies","code", "CURRENCY"),
        ("ref_countries", "code", "COUNTRY"),
    ]:
        row = conn.execute(f"SELECT * FROM {table} WHERE {col}=?", (q,)).fetchone()
        if row: print(f"    {label}: {dict(row)}")
    alias = conn.execute("SELECT iata,source FROM ref_city_iata WHERE alias=?",
                         (query.lower(),)).fetchone()
    if alias:
        airport = conn.execute("SELECT name FROM ref_airports WHERE iata=?",
                               (alias["iata"],)).fetchone()
        print(f"    CITY ALIAS -> {alias['iata']} ({alias['source']}): {airport['name'] if airport else '?'}")
    rate = conn.execute("SELECT rate FROM ref_gbp_rates WHERE currency=?", (q,)).fetchone()
    if rate: print(f"    GBP RATE: 1 GBP = {rate['rate']} {q}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stats",  action="store_true")
    p.add_argument("--lookup", metavar="CODE")
    args = p.parse_args()

    print(f"VoyageAI Reference Loader  DB={DB_PATH}")
    conn = get_db()
    create_tables(conn)

    if args.stats:
        show_stats(conn); conn.close(); return
    if args.lookup:
        lookup(conn, args.lookup); conn.close(); return

    sys.path.insert(0, str(HERE.parent))
    from data.reference_data import AIRPORTS, CURRENCIES, COUNTRIES, GBP_FALLBACK_RATES
    print(f"Source: {len(AIRPORTS)} airports  {len(CURRENCIES)} currencies  "
          f"{len(COUNTRIES)} countries  {len(GBP_FALLBACK_RATES)} rates")
    t0 = time.perf_counter()
    load_all(conn, AIRPORTS, CURRENCIES, COUNTRIES, GBP_FALLBACK_RATES)
    ms = round((time.perf_counter()-t0)*1000, 1)
    print(f"\n  Loaded in {ms}ms")
    show_stats(conn)
    conn.close()
    print("\nDone. Restart the server to rebuild cache from DB.")

if __name__ == "__main__":
    main()
