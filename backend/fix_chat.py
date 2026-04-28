"""
Fix: AttributeError: 'NoneType' object has no attribute 'strip'
in api/chat.py line 90

Run from backend folder: python fix_chat.py
"""
import os, sys, re

# Find chat.py
candidates = [
    os.path.join(".", "api", "chat.py"),
    os.path.join("..", "backend", "api", "chat.py"),
]
path = None
for c in candidates:
    if os.path.exists(c):
        path = os.path.abspath(c)
        break

if not path:
    for root, dirs, files in os.walk(os.path.abspath(".")):
        if "chat.py" in files and "api" in root:
            path = os.path.join(root, "chat.py")
            break

if not path:
    print("✗ Could not find api/chat.py")
    sys.exit(1)

print(f"Found: {path}")

with open(path, encoding="utf-8") as f:
    src = f.read()

original = src
changes  = []

# ── Fix 1: origin_iata NoneType crash ────────────────────────
# When JS sends null, body.get("origin_iata", "") returns None
# because the key EXISTS (value is null) so default "" is ignored.

# Pattern A — exact match from v10
old_a = 'origin = body.get("origin_iata", "").strip().upper()'
new_a = 'origin = (body.get("origin_iata") or "").strip().upper() or None'
if old_a in src:
    src = src.replace(old_a, new_a, 1)
    changes.append("Fixed: origin_iata NoneType crash (pattern A)")

# Pattern B — from v11 patch attempt
old_b = 'origin_iata  = (body.get("origin_iata") or "").strip().upper() or None'
if old_b in src:
    changes.append("✓ origin_iata already fixed (pattern B)")

# Pattern C — any remaining .strip() on a potentially None value
matches = re.findall(r'body\.get\("origin_iata",\s*""\)', src)
for m in matches:
    src = src.replace(m, 'body.get("origin_iata") or ""', 1)
    changes.append(f"Fixed: replaced {m!r} with null-safe version")

# ── Fix 2: Also guard origin_iata storage block ───────────────
# The storage block should also be safe
old_store = '''    # Persist detected/selected origin in RAG session
    if origin_iata and len(origin_iata) == 3:'''
new_store = '''    # Persist detected/selected origin in RAG session
    if origin_iata and isinstance(origin_iata, str) and len(origin_iata) == 3:'''
if old_store in src and new_store not in src:
    src = src.replace(old_store, new_store, 1)
    changes.append("Fixed: origin_iata storage guard")

# ── Fix 3: Ensure session_id is always safe ───────────────────
old_sid = 'session_id   = data.get("session_id") or memory_store.create_session()'
new_sid = 'session_id   = (data.get("session_id") or "").strip() or memory_store.create_session()'
if old_sid in src and new_sid not in src:
    src = src.replace(old_sid, new_sid, 1)
    changes.append("Fixed: session_id null guard")

# ── Write back ────────────────────────────────────────────────
if src != original:
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print()
    print("Changes applied:")
    for c in changes:
        print(f"  ✓ {c}")
elif changes:
    print()
    print("Already fixed:")
    for c in changes:
        print(f"  ✓ {c}")
else:
    print()
    print("Pattern not matched — applying brute-force fix...")
    # Find line 90 area and replace anything that looks like the bug
    lines = src.splitlines(keepends=True)
    fixed = False
    for i, line in enumerate(lines):
        if 'origin_iata' in line and '.strip()' in line and 'body.get' in line:
            old_line = line
            lines[i] = re.sub(
                r'body\.get\(["\']origin_iata["\'],\s*["\']["\]\)\s*\.strip\(\)',
                '(body.get("origin_iata") or "").strip()',
                line
            )
            if lines[i] != old_line:
                print(f"  ✓ Fixed line {i+1}: {lines[i].strip()}")
                fixed = True
    if fixed:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    else:
        print("  Could not auto-fix. Manual fix:")
        print()
        print("  Open api/chat.py and find line 90 (approx).")
        print("  Change:")
        print('    origin = body.get("origin_iata", "").strip().upper()')
        print("  To:")
        print('    origin = (body.get("origin_iata") or "").strip().upper() or None')

# ── Show relevant lines for verification ─────────────────────
print()
print("Current state of origin_iata lines in chat.py:")
with open(path, encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        if "origin_iata" in line or "origin" in line.lower() and "body.get" in line:
            print(f"  Line {i:3d}: {line.rstrip()}")

print()
print("Restart the server:  python run.py")
