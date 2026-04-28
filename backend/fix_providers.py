"""
VoyageAI Provider Fix Script
Run from backend folder: python fix_providers.py

Fixes:
  1. Upgrades groq SDK (proxies error = old version)
  2. Sets GEMINI_MODEL to best available (gemini-2.5-flash)
  3. Updates GEMINI_PRO fallback
"""
import subprocess, sys, re, os

def run(cmd):
    print(f"  > {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        print(f"    {result.stdout.strip()[:200]}")
    if result.returncode != 0 and result.stderr.strip():
        print(f"    ERR: {result.stderr.strip()[:200]}")
    return result.returncode == 0

# ── 1. Upgrade groq SDK ───────────────────────────────────────
print("=== FIX 1: Upgrade groq SDK ===")
print("  The 'proxies' error means your groq package is too old.")
ok = run("pip install --upgrade groq")
print(f"  {'✓ Done' if ok else '✗ Failed — try: pip install groq==0.11.0'}")

print()

# ── 2. Upgrade google-genai SDK ──────────────────────────────
print("=== FIX 2: Upgrade google-genai SDK ===")
ok = run("pip install --upgrade google-genai")
print(f"  {'✓ Done' if ok else '✗ Failed'}")

print()

# ── 3. Set best available Gemini model ────────────────────────
print("=== FIX 3: Update config.py with best models ===")
# From the check_keys.py output we know these are available:
# gemini-2.5-flash, gemini-2.0-flash, gemini-2.0-flash-001, gemini-2.0-flash-lite
# gemini-2.5-flash is best, gemini-2.0-flash is reliable fallback

best_model    = "gemini-2.5-flash"
fallback_model= "gemini-2.0-flash"

try:
    cfg = open("config.py", encoding="utf-8").read()
    original = cfg

    cfg = re.sub(r'GEMINI_MODEL\s*=\s*"[^"]+"',
                 f'GEMINI_MODEL   = "{best_model}"', cfg)
    cfg = re.sub(r'GEMINI_PRO\s*=\s*"[^"]+"',
                 f'GEMINI_PRO     = "{fallback_model}"', cfg)

    open("config.py", "w", encoding="utf-8").write(cfg)
    print(f"  ✓ GEMINI_MODEL   = \"{best_model}\"")
    print(f"  ✓ GEMINI_PRO     = \"{fallback_model}\"")
except Exception as e:
    print(f"  ✗ {e}")

print()

# ── 4. Verify groq after upgrade ─────────────────────────────
print("=== VERIFY: Testing Groq after upgrade ===")
try:
    from dotenv import load_dotenv
    load_dotenv()

    # Force fresh import
    if 'groq' in sys.modules:
        del sys.modules['groq']

    import importlib
    groq_mod = importlib.import_module('groq')
    key = os.getenv("GROQ_API_KEY", "")
    client = groq_mod.Groq(api_key=key)
    r = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user",
                   "content": 'Reply ONLY with this JSON object: {"msg":"hello from groq"}'}],
        max_tokens=40,
    )
    print(f"  ✓ Groq working! → {r.choices[0].message.content[:80]}")
except Exception as e:
    print(f"  ✗ {str(e)[:120]}")
    print()
    print("  If error persists, try:")
    print("    pip install groq==0.11.0")

print()

# ── 5. Verify Gemini after upgrade ───────────────────────────
print("=== VERIFY: Testing Gemini after upgrade ===")
try:
    from dotenv import load_dotenv
    load_dotenv()

    for mod_name in list(sys.modules.keys()):
        if 'google' in mod_name or 'genai' in mod_name:
            del sys.modules[mod_name]

    import importlib
    genai = importlib.import_module('google.genai')
    key = os.getenv("GEMINI_API_KEY", "")
    client = genai.Client(api_key=key)
    r = client.models.generate_content(
        model=best_model,
        contents='Reply ONLY with this JSON object: {"msg":"hello from gemini"}',
    )
    print(f"  ✓ Gemini working! → {r.text[:80]}")
except Exception as e:
    print(f"  ✗ {str(e)[:120]}")

print()
print("=" * 55)
print("All fixes applied.")
print()
print("Restart the server:")
print("  python run.py")
print()
print("Expected waterfall order:")
print("  ✓ Groq    (llama-3.3-70b-versatile) — fastest")
print("  ✓ Gemini  (gemini-2.5-flash)        — most capable")
print("  ✗ Anthropic (not configured)")
print("  ✓ Template (always works)")
print("=" * 55)
