"""
VoyageAI Admin API — Full CRUD for all config and master data.
"""
import json, os, sqlite3, time, re
from functools import wraps
from pathlib import Path
from flask import Blueprint, request, jsonify

bp      = Blueprint("admin", __name__)
DB_PATH = Path(__file__).parent.parent / "data" / "voyageai.db"
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "voyageai-admin-2026")

def require_admin(f):
    @wraps(f)
    def dec(*a, **kw):
        t = request.headers.get("X-Admin-Token") or request.args.get("token", "")
        if t != ADMIN_TOKEN:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*a, **kw)
    return dec

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def rows_to_list(rows):
    return [dict(r) for r in rows]

def _reload():
    try:
        from core.guardrail_config_cache import gcfg
        gcfg.reload()
    except Exception:
        pass

@bp.route("/admin/stats", methods=["GET"])
@require_admin
def admin_stats():
    conn = get_db()
    tables = ["guardrail_config","guardrail_skip_codes","guardrail_injection_patterns",
              "guardrail_travel_signals","guardrail_schema_rules",
              "ref_airports","ref_currencies","ref_gbp_rates","customers"]
    stats = {}
    for t in tables:
        try: stats[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except: stats[t] = 0
    conn.close()
    return jsonify(stats)

# ── Guardrail Config ──────────────────────────────────────────────
@bp.route("/admin/guardrail/config", methods=["GET"])
@require_admin
def gc_list():
    conn = get_db()
    rows = rows_to_list(conn.execute("SELECT key,value,dtype,description FROM guardrail_config ORDER BY key"))
    conn.close()
    return jsonify(rows)

@bp.route("/admin/guardrail/config", methods=["POST"])
@require_admin
def gc_upsert():
    d = request.get_json() or {}
    key = (d.get("key") or "").strip()
    val = str(d.get("value","")).strip()
    if not key or not val:
        return jsonify({"error":"key and value required"}),400
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO guardrail_config (key,value,dtype,description,updated_at) VALUES (?,?,?,?,?)",
                 (key,val,d.get("dtype","float"),d.get("description",""),time.time()))
    conn.commit(); conn.close(); _reload()
    return jsonify({"ok":True,"key":key,"value":val})

@bp.route("/admin/guardrail/config/<key>", methods=["DELETE"])
@require_admin
def gc_delete(key):
    conn = get_db()
    conn.execute("DELETE FROM guardrail_config WHERE key=?",(key,))
    conn.commit(); conn.close(); _reload()
    return jsonify({"ok":True,"deleted":key})

# ── Skip Codes ────────────────────────────────────────────────────
@bp.route("/admin/guardrail/skip-codes", methods=["GET"])
@require_admin
def sc_list():
    category = request.args.get("category","")
    q = "SELECT code,category,description FROM guardrail_skip_codes "
    params = []
    if category:
        q += "WHERE category=? "; params.append(category)
    q += "ORDER BY category,code"
    conn = get_db()
    rows = rows_to_list(conn.execute(q,params))
    cats = [r[0] for r in conn.execute("SELECT DISTINCT category FROM guardrail_skip_codes ORDER BY category")]
    conn.close()
    return jsonify({"rows":rows,"categories":cats,"total":len(rows)})

@bp.route("/admin/guardrail/skip-codes", methods=["POST"])
@require_admin
def sc_add():
    d = request.get_json() or {}
    code = (d.get("code") or "").strip().upper()
    cat  = (d.get("category") or "").strip().upper()
    if not code or not cat:
        return jsonify({"error":"code and category required"}),400
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO guardrail_skip_codes (code,category,description,updated_at) VALUES (?,?,?,?)",
                 (code,cat,d.get("description",""),time.time()))
    conn.commit(); conn.close(); _reload()
    return jsonify({"ok":True,"code":code,"category":cat})

@bp.route("/admin/guardrail/skip-codes/<code>", methods=["DELETE"])
@require_admin
def sc_delete(code):
    cat = request.args.get("category","")
    conn = get_db()
    if cat: conn.execute("DELETE FROM guardrail_skip_codes WHERE code=? AND category=?",(code.upper(),cat))
    else:   conn.execute("DELETE FROM guardrail_skip_codes WHERE code=?",(code.upper(),))
    conn.commit(); conn.close(); _reload()
    return jsonify({"ok":True,"deleted":code})

# ── Injection Patterns ────────────────────────────────────────────
@bp.route("/admin/guardrail/injection-patterns", methods=["GET"])
@require_admin
def ip_list():
    conn = get_db()
    rows = rows_to_list(conn.execute("SELECT id,pattern,description,enabled FROM guardrail_injection_patterns ORDER BY id"))
    conn.close()
    return jsonify(rows)

@bp.route("/admin/guardrail/injection-patterns", methods=["POST"])
@require_admin
def ip_add():
    d = request.get_json() or {}
    pattern = (d.get("pattern") or "").strip()
    if not pattern: return jsonify({"error":"pattern required"}),400
    try: re.compile(pattern)
    except re.error as e: return jsonify({"error":f"Invalid regex: {e}"}),400
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO guardrail_injection_patterns (pattern,description,enabled,updated_at) VALUES (?,?,?,?)",
                 (pattern,d.get("description",""),int(d.get("enabled",1)),time.time()))
    conn.commit(); conn.close(); _reload()
    return jsonify({"ok":True,"pattern":pattern})

@bp.route("/admin/guardrail/injection-patterns/<int:pid>", methods=["PATCH"])
@require_admin
def ip_toggle(pid):
    d = request.get_json() or {}
    conn = get_db()
    conn.execute("UPDATE guardrail_injection_patterns SET enabled=?,updated_at=? WHERE id=?",
                 (int(d.get("enabled",1)),time.time(),pid))
    conn.commit(); conn.close(); _reload()
    return jsonify({"ok":True,"id":pid})

@bp.route("/admin/guardrail/injection-patterns/<int:pid>", methods=["DELETE"])
@require_admin
def ip_delete(pid):
    conn = get_db()
    conn.execute("DELETE FROM guardrail_injection_patterns WHERE id=?",(pid,))
    conn.commit(); conn.close(); _reload()
    return jsonify({"ok":True,"deleted":pid})

# ── Travel Signals ────────────────────────────────────────────────
@bp.route("/admin/guardrail/travel-signals", methods=["GET"])
@require_admin
def ts_list():
    category = request.args.get("category","")
    q = "SELECT signal,category FROM guardrail_travel_signals "
    params = []
    if category: q += "WHERE category=? "; params.append(category)
    q += "ORDER BY category,signal"
    conn = get_db()
    rows = rows_to_list(conn.execute(q,params))
    cats = [r[0] for r in conn.execute("SELECT DISTINCT category FROM guardrail_travel_signals ORDER BY category")]
    conn.close()
    return jsonify({"rows":rows,"categories":cats,"total":len(rows)})

@bp.route("/admin/guardrail/travel-signals", methods=["POST"])
@require_admin
def ts_add():
    d = request.get_json() or {}
    signal = (d.get("signal") or "").strip().lower()
    cat    = (d.get("category") or "CORE").strip().upper()
    if not signal: return jsonify({"error":"signal required"}),400
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO guardrail_travel_signals (signal,category,updated_at) VALUES (?,?,?)",
                 (signal,cat,time.time()))
    conn.commit(); conn.close(); _reload()
    return jsonify({"ok":True,"signal":signal})

@bp.route("/admin/guardrail/travel-signals/<signal>", methods=["DELETE"])
@require_admin
def ts_delete(signal):
    conn = get_db()
    conn.execute("DELETE FROM guardrail_travel_signals WHERE signal=?",(signal,))
    conn.commit(); conn.close(); _reload()
    return jsonify({"ok":True,"deleted":signal})

# ── Ref Airports ──────────────────────────────────────────────────
@bp.route("/admin/ref/airports", methods=["GET"])
@require_admin
def ap_list():
    q=request.args.get("q",""); cc=request.args.get("country","").upper()
    lim=min(int(request.args.get("limit",100)),500); off=int(request.args.get("offset",0))
    where,params=[],[]
    if q: where.append("(iata LIKE ? OR city LIKE ? OR name LIKE ?)"); params+=[f"%{q}%",f"%{q}%",f"%{q}%"]
    if cc: where.append("country_code=?"); params.append(cc)
    clause=("WHERE "+" AND ".join(where)) if where else ""
    conn=get_db()
    total=conn.execute(f"SELECT COUNT(*) FROM ref_airports {clause}",params).fetchone()[0]
    rows=rows_to_list(conn.execute(f"SELECT iata,name,city,country_code,lat,lon FROM ref_airports {clause} ORDER BY iata LIMIT ? OFFSET ?",params+[lim,off]))
    conn.close()
    return jsonify({"rows":rows,"total":total,"offset":off,"limit":lim})

@bp.route("/admin/ref/airports", methods=["POST"])
@require_admin
def ap_add():
    d=request.get_json() or {}
    iata=(d.get("iata") or "").strip().upper()
    if not re.match(r"^[A-Z]{3}$",iata): return jsonify({"error":"iata must be 3 uppercase letters"}),400
    conn=get_db()
    conn.execute("INSERT OR REPLACE INTO ref_airports (iata,name,city,country_code,lat,lon,updated_at) VALUES (?,?,?,?,?,?,?)",
                 (iata,d.get("name",""),d.get("city",""),d.get("country_code",""),d.get("lat",0),d.get("lon",0),time.time()))
    conn.commit(); conn.close(); _reload()
    return jsonify({"ok":True,"iata":iata})

@bp.route("/admin/ref/airports/<iata>", methods=["DELETE"])
@require_admin
def ap_delete(iata):
    conn=get_db()
    conn.execute("DELETE FROM ref_airports WHERE iata=?",(iata.upper(),))
    conn.commit(); conn.close(); _reload()
    return jsonify({"ok":True,"deleted":iata})

# ── Ref Currencies ────────────────────────────────────────────────
@bp.route("/admin/ref/currencies", methods=["GET"])
@require_admin
def cu_list():
    q=request.args.get("q",""); lim=min(int(request.args.get("limit",200)),500)
    conn=get_db()
    if q: rows=rows_to_list(conn.execute("SELECT code,name,symbol FROM ref_currencies WHERE code LIKE ? OR name LIKE ? LIMIT ?",(f"%{q}%",f"%{q}%",lim)))
    else: rows=rows_to_list(conn.execute("SELECT code,name,symbol FROM ref_currencies ORDER BY code LIMIT ?",(lim,)))
    conn.close()
    return jsonify({"rows":rows,"total":len(rows)})

@bp.route("/admin/ref/currencies", methods=["POST"])
@require_admin
def cu_add():
    d=request.get_json() or {}
    code=(d.get("code") or "").strip().upper()
    if not re.match(r"^[A-Z]{3}$",code): return jsonify({"error":"code must be 3 uppercase letters"}),400
    conn=get_db()
    conn.execute("INSERT OR REPLACE INTO ref_currencies (code,name,symbol,updated_at) VALUES (?,?,?,?)",(code,d.get("name",""),d.get("symbol",""),time.time()))
    conn.commit(); conn.close(); _reload()
    return jsonify({"ok":True,"code":code})

@bp.route("/admin/ref/currencies/<code>", methods=["DELETE"])
@require_admin
def cu_delete(code):
    conn=get_db()
    conn.execute("DELETE FROM ref_currencies WHERE code=?",(code.upper(),))
    conn.commit(); conn.close(); _reload()
    return jsonify({"ok":True,"deleted":code})

# ── GBP Rates ─────────────────────────────────────────────────────
@bp.route("/admin/ref/gbp-rates", methods=["GET"])
@require_admin
def gr_list():
    q=request.args.get("q","")
    conn=get_db()
    if q: rows=rows_to_list(conn.execute("SELECT currency,rate FROM ref_gbp_rates WHERE currency LIKE ? ORDER BY currency",(f"%{q}%",)))
    else: rows=rows_to_list(conn.execute("SELECT currency,rate FROM ref_gbp_rates ORDER BY currency"))
    conn.close()
    return jsonify({"rows":rows,"total":len(rows)})

@bp.route("/admin/ref/gbp-rates", methods=["POST"])
@require_admin
def gr_upsert():
    d=request.get_json() or {}
    currency=(d.get("currency") or "").strip().upper()
    rate=float(d.get("rate",0))
    if not currency or rate<=0: return jsonify({"error":"currency and positive rate required"}),400
    conn=get_db()
    conn.execute("INSERT OR REPLACE INTO ref_gbp_rates (currency,rate,updated_at) VALUES (?,?,?)",(currency,rate,time.time()))
    conn.commit(); conn.close(); _reload()
    return jsonify({"ok":True,"currency":currency,"rate":rate})

@bp.route("/admin/ref/gbp-rates/<currency>", methods=["DELETE"])
@require_admin
def gr_delete(currency):
    conn=get_db()
    conn.execute("DELETE FROM ref_gbp_rates WHERE currency=?",(currency.upper(),))
    conn.commit(); conn.close(); _reload()
    return jsonify({"ok":True,"deleted":currency})

# ── Customers ─────────────────────────────────────────────────────
@bp.route("/admin/customers", methods=["GET"])
@require_admin
def cust_list():
    q=request.args.get("q",""); tier=request.args.get("tier","")
    where,params=[],[]
    if q: where.append("(name LIKE ? OR email LIKE ? OR member_id LIKE ?)"); params+=[f"%{q}%",f"%{q}%",f"%{q}%"]
    if tier: where.append("loyalty_tier=?"); params.append(tier)
    clause=("WHERE "+" AND ".join(where)) if where else ""
    conn=get_db()
    rows=rows_to_list(conn.execute(
        f"SELECT id,member_id,name,email,loyalty_tier,loyalty_points,travel_style,"
        f"typical_budget_gbp,typical_nights,adults_in_family,children_in_family,interests,created_at "
        f"FROM customers {clause} ORDER BY loyalty_tier,name",params))
    conn.close()
    for r in rows:
        if isinstance(r.get("interests"),str):
            try: r["interests"]=json.loads(r["interests"])
            except: r["interests"]=[]
    return jsonify({"rows":rows,"total":len(rows)})

@bp.route("/admin/customers", methods=["POST"])
@require_admin
def cust_add():
    d=request.get_json() or {}
    name=(d.get("name") or "").strip(); email=(d.get("email") or "").strip().lower()
    if not name or not email: return jsonify({"error":"name and email required"}),400
    tier=d.get("loyalty_tier","Blue"); points=int(d.get("loyalty_points",0))
    tier_code={"Platinum":"PLAT","Gold":"GOLD","Silver":"SILV","Blue":"BLUE"}.get(tier,"BLUE")
    import random; member_id=f"VGI-{tier_code}-{random.randint(1000,9999)}"
    conn=get_db()
    try:
        conn.execute("INSERT INTO customers (member_id,name,email,loyalty_tier,loyalty_points,travel_style,typical_budget_gbp,typical_nights,adults_in_family,children_in_family,interests,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (member_id,name,email,tier,points,d.get("travel_style","leisure"),
                      float(d.get("typical_budget_gbp",3000)),int(d.get("typical_nights",7)),
                      int(d.get("adults_in_family",2)),int(d.get("children_in_family",0)),
                      json.dumps(d.get("interests",[])),time.time()))
        conn.commit()
        cid=conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return jsonify({"ok":True,"id":cid,"member_id":member_id}),201
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error":f"Email {email} already exists"}),409

@bp.route("/admin/customers/<int:cid>", methods=["PATCH"])
@require_admin
def cust_update(cid):
    d=request.get_json() or {}
    allowed={"name","email","loyalty_tier","loyalty_points","travel_style","typical_budget_gbp","typical_nights","adults_in_family","children_in_family","interests"}
    sets,params=[],[]
    for field in allowed:
        if field in d:
            val=json.dumps(d[field]) if field=="interests" else d[field]
            sets.append(f"{field}=?"); params.append(val)
    if not sets: return jsonify({"error":"No fields to update"}),400
    sets.append("updated_at=?"); params.append(time.time()); params.append(cid)
    conn=get_db()
    conn.execute(f"UPDATE customers SET {', '.join(sets)} WHERE id=?",params)
    conn.commit(); conn.close()
    return jsonify({"ok":True,"id":cid})

@bp.route("/admin/customers/<int:cid>", methods=["DELETE"])
@require_admin
def cust_delete(cid):
    conn=get_db()
    row=conn.execute("SELECT name FROM customers WHERE id=?",(cid,)).fetchone()
    if not row: conn.close(); return jsonify({"error":"Not found"}),404
    conn.execute("DELETE FROM customers WHERE id=?",(cid,))
    conn.commit(); conn.close()
    return jsonify({"ok":True,"deleted":cid,"name":row["name"]})
