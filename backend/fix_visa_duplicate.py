"""
Fix: 'visaHTML has already been declared' in itinerary.js
Run from backend folder: python fix_visa_duplicate.py
"""
import os, sys, re

# Find itinerary.js
path = None
for candidate in [
    os.path.join("..", "frontend", "js", "ui", "itinerary.js"),
    os.path.join(".",  "frontend", "js", "ui", "itinerary.js"),
    os.path.join(".",  "js", "ui", "itinerary.js"),
]:
    if os.path.exists(candidate):
        path = os.path.abspath(candidate)
        break

if not path:
    for root, dirs, files in os.walk(os.path.abspath(".")):
        if "itinerary.js" in files and "ui" in root:
            path = os.path.join(root, "itinerary.js")
            break

if not path:
    print("Cannot find itinerary.js — run from backend or frontend folder")
    sys.exit(1)

print(f"File: {path}")

with open(path, encoding="utf-8") as f:
    src = f.read()

# Count how many times visaHTML is declared
decl_count = src.count("let visaHTML")
print(f"Found {decl_count} declaration(s) of 'let visaHTML'")

if decl_count <= 1:
    print("Only one declaration — checking for other issues...")
    # Check if it's declared as const somewhere
    if "const visaHTML" in src:
        print("Found 'const visaHTML' — converting to let")
        src = src.replace("const visaHTML", "let visaHTML")
    elif "var visaHTML" in src:
        print("Found 'var visaHTML' mixed with let — removing var version")
        src = re.sub(r"\bvar visaHTML\s*=\s*'';?\n?", "", src)
else:
    print(f"Removing {decl_count - 1} duplicate declaration(s)...")

    # Strategy: keep only the FIRST declaration, remove all others
    first_pos = src.find("let visaHTML")
    if first_pos == -1:
        print("No declarations found at all — adding one")
        # Find a good place to add it (after other let declarations)
        for marker in ["let loyaltyHTML", "let ancillaryHTML", "let personalisedHTML"]:
            pos = src.find(marker)
            if pos != -1:
                end = src.find("\n", pos)
                src = src[:end+1] + "  let visaHTML = '';\n" + src[end+1:]
                print("Added: let visaHTML = '';")
                break
    else:
        # Remove all subsequent let visaHTML declarations
        # Keep first, delete the rest
        lines = src.split("\n")
        found_first = False
        new_lines = []
        removed = 0
        for line in lines:
            stripped = line.strip()
            is_visa_decl = re.match(r"^\s*let\s+visaHTML\s*=", line)
            if is_visa_decl:
                if not found_first:
                    found_first = True
                    new_lines.append(line)  # keep first
                else:
                    removed += 1
                    # skip duplicate
            else:
                new_lines.append(line)
        src = "\n".join(new_lines)
        print(f"Removed {removed} duplicate declaration(s)")

# Also make sure visaHTML is initialised to '' (not undefined)
# Replace any bare `let visaHTML;` with `let visaHTML = '';`
src = re.sub(r"\blet\s+visaHTML\s*;", "let visaHTML = '';", src)

# Make sure every reference to visaHTML in template literals is safe
# Change ${visaHTML} to ${visaHTML || ''} as a safety net
src = re.sub(
    r"\$\{visaHTML\}",
    "${typeof visaHTML !== 'undefined' ? visaHTML : ''}",
    src
)

with open(path, "w", encoding="utf-8") as f:
    f.write(src)

# Verify
remaining = src.count("let visaHTML")
print(f"\nAfter fix: {remaining} declaration(s) of 'let visaHTML'")

if remaining == 1:
    print("✓ Fixed. Now do a hard refresh in your browser: Ctrl + Shift + R")
elif remaining == 0:
    print("✓ Fixed (no declaration needed — visaHTML set inline).")
    print("  Hard refresh browser: Ctrl + Shift + R")
else:
    print("✗ Still multiple declarations. Please share itinerary.js content.")
