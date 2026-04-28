"""
Surgical fix for: visaHTML is not defined
Run from backend folder: python fix_itinerary_visa.py

The problem: _buildCard() destructures the parameter object but
'visaHTML' was missing from the destructure list. JavaScript then
throws 'visaHTML is not defined' when the template string runs.
"""
import os, sys

# Find itinerary.js
path = None
for root, dirs, files in os.walk(os.path.abspath(".")):
    if "itinerary.js" in files and "ui" in root:
        path = os.path.join(root, "itinerary.js")
        break
    # Also check parent (if running from backend/)
    parent = os.path.dirname(os.path.abspath("."))
    for r2, d2, f2 in os.walk(parent):
        if "itinerary.js" in f2 and "ui" in r2:
            path = os.path.join(r2, "itinerary.js")
            break
    if path:
        break

if not path:
    # Try explicit relative path
    candidates = [
        os.path.join("..", "frontend", "js", "ui", "itinerary.js"),
        os.path.join(".",  "frontend", "js", "ui", "itinerary.js"),
    ]
    for c in candidates:
        if os.path.exists(c):
            path = os.path.abspath(c)
            break

if not path:
    print("✗ Cannot find itinerary.js")
    print("  Try running from the backend or frontend folder.")
    sys.exit(1)

print(f"Found: {path}")

with open(path, encoding="utf-8") as f:
    src = f.read()

original = src
fixes    = []

# ── Fix 1: Add visaHTML to _buildCard destructure ────────────
# This is the PRIMARY cause of "visaHTML is not defined"
# _buildCard receives visaHTML in the object but never extracts it

patterns = [
    # Pattern A — current version
    (
        "    loyaltyHTML, ancillaryHTML, personalisedHTML,\n    hasCustomer,\n  } = p;",
        "    loyaltyHTML, ancillaryHTML, personalisedHTML,\n    visaHTML = '',\n    hasCustomer,\n  } = p;"
    ),
    # Pattern B — no trailing comma
    (
        "    loyaltyHTML, ancillaryHTML, personalisedHTML,\n    hasCustomer\n  } = p;",
        "    loyaltyHTML, ancillaryHTML, personalisedHTML,\n    visaHTML = '',\n    hasCustomer\n  } = p;"
    ),
    # Pattern C — single line style
    (
        "loyaltyHTML, ancillaryHTML, personalisedHTML, hasCustomer,",
        "loyaltyHTML, ancillaryHTML, personalisedHTML, visaHTML = '', hasCustomer,"
    ),
    # Pattern D — already has visaHTML but without default
    (
        "loyaltyHTML, ancillaryHTML, personalisedHTML, visaHTML,\n    hasCustomer,",
        "loyaltyHTML, ancillaryHTML, personalisedHTML, visaHTML = '',\n    hasCustomer,"
    ),
]

for old, new in patterns:
    if old in src and new not in src:
        src = src.replace(old, new, 1)
        fixes.append(f"Added visaHTML = '' to _buildCard destructure")
        break

# ── Fix 2: Ensure let visaHTML declared at top ────────────────
decls_needed = [
    "let loyaltyHTML    = '';",
    "let loyaltyHTML = '';",
]
for decl in decls_needed:
    if decl in src and "let visaHTML" not in src:
        src = src.replace(decl, decl + "\n  let visaHTML = '';", 1)
        fixes.append("Declared: let visaHTML = '' at function top")
        break

# ── Fix 3: Guard ${visaHTML} in template ─────────────────────
if "${visaHTML}" in src and "typeof visaHTML" not in src:
    src = src.replace(
        "${visaHTML}",
        "${typeof visaHTML !== 'undefined' ? visaHTML : ''}",
    )
    fixes.append("Guarded ${visaHTML} with typeof check in template")

# ── Write back ────────────────────────────────────────────────
if src != original:
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print()
    print("Fixes applied:")
    for fx in fixes:
        print(f"  ✓ {fx}")
else:
    print()
    print("No pattern matched. Applying nuclear guard...")
    # Last resort: replace ALL ${visaHTML} occurrences with a safe version
    if "${visaHTML}" in src:
        src = src.replace(
            "${visaHTML}",
            "${(typeof visaHTML !== 'undefined' && visaHTML) ? visaHTML : ''}",
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
        print("  ✓ Applied null-guard on all ${visaHTML} in template")
    else:
        print("  ${visaHTML} not found in file at all.")
        print("  The visa tab may not be in this version of itinerary.js.")

# ── Verify ────────────────────────────────────────────────────
print()
with open(path, encoding="utf-8") as f:
    final = f.read()

print("Verification:")
print(f"  {'✓' if 'let visaHTML' in final else '✗'} let visaHTML declared")
print(f"  {'✓' if \"visaHTML = ''\" in final else '✗'} visaHTML has default value in _buildCard")
print(f"  {'✓' if 'tp-visa' in final else '—'} visa tab pane present")
print(f"  {'✓' if 'visaHTML' in final else '✗'} visaHTML referenced in template")

print()
print("Now do a hard refresh in your browser: Ctrl + Shift + R")
print("The error should be gone.")
