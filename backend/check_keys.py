"""
VoyageAI Diagnostic & Fix Script
Run from backend folder: python check_keys.py
"""
import sys, os
sys.path.insert(0, '.')

# ── 1. Load .env ──────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✓ .env loaded")
except Exception as e:
    print(f"✗ dotenv error: {e}")

print()

# ── 2. Check keys ─────────────────────────────────────────────
groq_key   = os.getenv("GROQ_API_KEY",   "").strip()
gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
anth_key   = os.getenv("ANTHROPIC_API_KEY", "").strip()

print("=== API KEYS ===")
print(f"  GROQ_API_KEY:      {'SET (' + groq_key[:12] + '...)' if groq_key else 'MISSING — add to backend/.env'}")
print(f"  GEMINI_API_KEY:    {'SET (' + gemini_key[:12] + '...)' if gemini_key else 'MISSING — add to backend/.env'}")
print(f"  ANTHROPIC_API_KEY: {'SET (' + anth_key[:12] + '...)' if anth_key else 'not set (optional)'}")
print()

# ── 3. Check .env file location ───────────────────────────────
print("=== FILES ===")
env_path = os.path.abspath(".env")
print(f"  Looking for .env at: {env_path}")
print(f"  .env exists: {os.path.exists('.env')}")
print()

# ── 4. Test Groq ──────────────────────────────────────────────
print("=== GROQ TEST ===")
if not groq_key:
    print("  SKIP — no GROQ_API_KEY in .env")
else:
    try:
        from groq import Groq
        client = Groq(api_key=groq_key)
        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": 'Reply with only this JSON: {"msg":"hello"}'}],
            max_tokens=30,
        )
        print(f"  ✓ Groq working! Response: {r.choices[0].message.content[:60]}")
    except ImportError:
        print("  ✗ groq SDK not installed. Run: pip install groq")
    except Exception as e:
        print(f"  ✗ Groq error: {str(e)[:120]}")

print()

# ── 5. Test Gemini + find working model ───────────────────────
print("=== GEMINI TEST ===")
if not gemini_key:
    print("  SKIP — no GEMINI_API_KEY in .env")
else:
    try:
        from google import genai
        client = genai.Client(api_key=gemini_key)

        # List available models
        print("  Fetching available models...")
        all_models = list(client.models.list())
        flash_models = [
            m.name.replace("models/", "")
            for m in all_models
            if "flash" in m.name.lower()
        ]
        pro_models = [
            m.name.replace("models/", "")
            for m in all_models
            if "pro" in m.name.lower() and "vision" not in m.name.lower()
        ]
        print(f"  Available flash models: {flash_models[:6]}")
        print(f"  Available pro models:   {pro_models[:4]}")

        # Try models in order of preference
        candidates = [
            "gemini-2.0-flash",
            "gemini-2.0-flash-exp",
            "gemini-2.0-flash-001",
            "gemini-2.0-flash-lite",
            "gemini-1.5-flash",
            "gemini-1.5-flash-8b",
        ]
        # Also try any flash model from the API
        for m in flash_models:
            if m not in candidates:
                candidates.insert(0, m)

        working_model = None
        for model in candidates:
            try:
                r = client.models.generate_content(
                    model=model,
                    contents='Reply with only this JSON: {"msg":"hello"}',
                )
                print(f"  ✓ Gemini working! Model: {model}")
                print(f"    Response: {r.text[:60]}")
                working_model = model
                break
            except Exception as e:
                err = str(e)[:80]
                print(f"  ✗ {model}: {err}")

        # Auto-fix config.py with working model
        if working_model:
            print()
            print(f"  Auto-updating config.py with model: {working_model}")
            try:
                import re
                cfg = open("config.py", encoding="utf-8").read()
                cfg = re.sub(
                    r'GEMINI_MODEL\s*=\s*"[^"]+"',
                    f'GEMINI_MODEL   = "{working_model}"',
                    cfg,
                )
                open("config.py", "w", encoding="utf-8").write(cfg)
                print(f"  ✓ config.py updated — GEMINI_MODEL = \"{working_model}\"")
            except Exception as e:
                print(f"  ✗ Could not update config.py: {e}")
                print(f"    Manually set: GEMINI_MODEL = \"{working_model}\"")
        else:
            print()
            print("  ✗ No working Gemini model found.")
            print("    Check your API key is valid at: aistudio.google.com")

    except ImportError:
        print("  ✗ google-genai not installed. Run: pip install google-genai")
    except Exception as e:
        print(f"  ✗ Gemini error: {str(e)[:120]}")

print()

# ── 6. Update Groq model in config.py ─────────────────────────
print("=== UPDATING CONFIG.PY ===")
try:
    import re
    cfg = open("config.py", encoding="utf-8").read()
    original = cfg

    # Groq — update decommissioned models
    cfg = cfg.replace('"llama-3.1-70b-versatile"', '"llama-3.3-70b-versatile"')
    cfg = cfg.replace('"mixtral-8x7b-32768"',       '"llama-3.1-8b-instant"')

    if cfg != original:
        open("config.py", "w", encoding="utf-8").write(cfg)
        print("  ✓ Groq models updated in config.py")
    else:
        print("  ✓ Groq models already up to date")

    # Show final config values
    print()
    print("  Final config.py LLM settings:")
    for line in cfg.splitlines():
        if any(k in line for k in ["GROQ_MODEL", "GEMINI_MODEL", "ANTHROPIC_MODEL",
                                    "GROQ_FALLBACK", "GEMINI_PRO"]):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                print(f"    {stripped}")
except Exception as e:
    print(f"  ✗ Error updating config.py: {e}")

print()
print("=" * 55)
print("Done. Now restart the server:  python run.py")
print("=" * 55)
