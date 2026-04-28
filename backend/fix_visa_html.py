"""
Fix: visaHTML is not defined in itinerary.js
Run from backend folder: python fix_visa_html.py
Or from frontend folder — script finds itinerary.js automatically.
"""
import os, sys

# Find itinerary.js
candidates = [
    os.path.join("..",  "frontend", "js", "ui", "itinerary.js"),
    os.path.join(".",   "frontend", "js", "ui", "itinerary.js"),
    os.path.join(".",   "js", "ui", "itinerary.js"),
]
path = None
for c in candidates:
    if os.path.exists(c):
        path = os.path.abspath(c)
        break

if not path:
    # Walk upward to find it
    here = os.path.abspath(".")
    for root, dirs, files in os.walk(here):
        if "itinerary.js" in files and "ui" in root:
            path = os.path.join(root, "itinerary.js")
            break

if not path:
    print("✗ Could not find itinerary.js")
    print("  Run this script from the backend or frontend folder.")
    sys.exit(1)

print(f"Found: {path}")

with open(path, encoding="utf-8") as f:
    src = f.read()

original = src
changes  = []

# ── Fix 1: Declare visaHTML at top of renderItineraryCard ─────
# Find where other HTML vars are declared and add visaHTML
for decl in [
    "let loyaltyHTML    = '';\n  let ancillaryHTML  = '';\n  let personalisedHTML = '';",
    "let loyaltyHTML = '';\n  let ancillaryHTML = '';\n  let personalisedHTML = '';",
    "let loyaltyHTML    = '';\n  let ancillaryHTML  = '';\n  let personalisedHTML = '';\n  let visaHTML = '';",
]:
    if decl in src and "visaHTML" not in decl:
        new_decl = decl + "\n  let visaHTML = '';"
        src = src.replace(decl, new_decl, 1)
        changes.append("Added: let visaHTML = '' declaration")
        break

# ── Fix 2: Build visaHTML BEFORE _buildCard call ──────────────
BUILD_VISA_BLOCK = """
  // ── Visa panel (always built, no customer login required) ────
  try {
    const { buildVisaPanel } = await import('./visa_panel.js').catch(() => ({ buildVisaPanel: () => '' }));
    const visaSource   = (typeof mcp_data !== 'undefined' && mcp_data?.visa?.data)
                         || out.recommendations?.visa_full
                         || null;
    const visaPassport = customer?.profile?.name
      ? customer.profile.name.split(' ')[0] + "'s passport"
      : 'Your passport';
    visaHTML = buildVisaPanel(visaSource, visaPassport, intent.destination || 'your destination');
  } catch (_e) {
    visaHTML = '<div style="padding:16px;color:var(--muted)">Visa information unavailable.</div>';
  }

"""

# Insert before the _buildCard call
build_card_markers = [
    "  const html = _buildCard({",
    "  const html= _buildCard({",
    "  var html = _buildCard(",
]
inserted = False
for marker in build_card_markers:
    if marker in src and BUILD_VISA_BLOCK.strip() not in src:
        src = src.replace(marker, BUILD_VISA_BLOCK + marker, 1)
        changes.append("Inserted: visaHTML build block before _buildCard")
        inserted = True
        break

# ── Fix 3: Pass visaHTML into _buildCard ──────────────────────
for old_args in [
    "loyaltyHTML, ancillaryHTML, personalisedHTML,\n    hasCustomer:",
    "loyaltyHTML, ancillaryHTML, personalisedHTML,\n    hasCustomer :",
    "loyaltyHTML, ancillaryHTML, personalisedHTML, visaHTML,\n    hasCustomer:",
]:
    if old_args in src and "visaHTML" not in old_args:
        new_args = old_args.replace(
            "loyaltyHTML, ancillaryHTML, personalisedHTML,",
            "loyaltyHTML, ancillaryHTML, personalisedHTML, visaHTML,",
        )
        src = src.replace(old_args, new_args, 1)
        changes.append("Added visaHTML to _buildCard() call args")
        break

# ── Fix 4: Accept visaHTML in _buildCard function params ──────
for old_params in [
    "  loyaltyHTML, ancillaryHTML, personalisedHTML,\n  hasCustomer,",
    "  loyaltyHTML, ancillaryHTML, personalisedHTML,\n  hasCustomer :",
]:
    if old_params in src and "visaHTML" not in old_params:
        new_params = old_params.replace(
            "  loyaltyHTML, ancillaryHTML, personalisedHTML,",
            "  loyaltyHTML, ancillaryHTML, personalisedHTML, visaHTML = '',",
        )
        src = src.replace(old_params, new_params, 1)
        changes.append("Added visaHTML to _buildCard() function params with default ''")
        break

# ── Fix 5: Ensure visa pane uses the variable (not undefined) ─
if "${visaHTML}" in src:
    changes.append("✓ ${visaHTML} already in template")
elif "tp-visa" in src:
    # Find the visa pane div and make sure it uses visaHTML
    src = src.replace(
        'id="tp-visa">',
        'id="tp-visa">${visaHTML || \'\'}',
        1,
    )
    changes.append("Fixed: visa pane template uses visaHTML")

# ── Fix 6: Import visa_panel at top if missing ────────────────
if "visa_panel" not in src and "buildVisaPanel" not in src:
    # Add import after first import statement
    first_import = src.find("import ")
    if first_import != -1:
        end_of_line = src.find("\n", first_import)
        src = src[:end_of_line+1] + "import { buildVisaPanel } from './visa_panel.js';\n" + src[end_of_line+1:]
        changes.append("Added: import { buildVisaPanel } from './visa_panel.js'")

# ── Write back ────────────────────────────────────────────────
if src != original:
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print()
    print("Changes applied:")
    for c in changes:
        print(f"  ✓ {c}")
else:
    print()
    if changes:
        print("Some patterns already in place:")
        for c in changes:
            print(f"  ✓ {c}")
    else:
        print("No changes needed — or patterns not matched.")
        print("Applying nuclear fix: safe default for visaHTML...")

        # Nuclear fix: wrap the _buildCard template literal to guarantee visaHTML exists
        # Find the template string that references visaHTML and guard it
        src = src.replace(
            "${visaHTML}",
            "${typeof visaHTML !== 'undefined' ? visaHTML : ''}",
        )
        if src != original:
            with open(path, "w", encoding="utf-8") as f:
                f.write(src)
            print("  ✓ Applied null-guard on ${visaHTML} in template")

# ── Quick verify ──────────────────────────────────────────────
print()
with open(path, encoding="utf-8") as f:
    final = f.read()

checks = [
    ("visaHTML declared",        "let visaHTML" in final),
    ("visaHTML in template",     "visaHTML" in final),
    ("visa pane present",        "tp-visa" in final),
    ("buildVisaPanel imported or dynamic", "buildVisaPanel" in final or "visa_panel" in final),
]
print("Verification:")
all_ok = True
for label, ok in checks:
    print(f"  {'✓' if ok else '✗'} {label}")
    if not ok:
        all_ok = False

print()
if all_ok:
    print("All checks passed. Refresh your browser — error should be gone.")
else:
    print("Some checks failed. Please share the current content of itinerary.js")
    print(f"File: {path}")
