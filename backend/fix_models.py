"""
VoyageAI Model Fix — run from backend folder: python fix_models.py
Updates Groq + Gemini model names in config.py and verifies both work.
"""
import subprocess, sys, os, re

HERE = os.path.dirname(os.path.abspath(__file__))

# ── Step 1: upgrade SDKs ──────────────────────────────────────
print("Upgrading SDKs...")
for pkg in ["groq", "google-genai"]:
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", pkg],
                       capture_output=True, text=True)
    ok = r.returncode == 0
    print(f"  {'✓' if ok else '✗'} {pkg}")

# ── Step 2: load keys ─────────────────────────────────────────
print()
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HERE, ".env"))
except Exception:
    pass

groq_key   = os.getenv("GROQ_API_KEY", "").strip()
gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
print(f"GROQ_API_KEY:   {'SET' if groq_key   else 'MISSING'}")
print(f"GEMINI_API_KEY: {'SET' if gemini_key else 'MISSING'}")

# ── Step 3: find working Groq model ───────────────────────────
print()
print("=== GROQ ===")
groq_model = None
if groq_key:
    GROQ_CANDIDATES = [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "llama3-70b-8192",
        "llama3-8b-8192",
        "gemma2-9b-it",
    ]
    try:
        # reload after upgrade
        if "groq" in sys.modules:
            del sys.modules["groq"]
        import importlib
        groq_mod = importlib.import_module("groq")
        client   = groq_mod.Groq(api_key=groq_key)
        for model in GROQ_CANDIDATES:
            try:
                r = client.chat.completions.create(
                    model=model,
                    messages=[{"role":"user","content":'{"ok":true}'}],
                    max_tokens=20,
                )
                print(f"  ✓ Working model: {model}")
                groq_model = model
                break
            except Exception as e:
                print(f"  ✗ {model}: {str(e)[:60]}")
    except ImportError:
        print("  ✗ groq not installed — run: pip install groq")
    except Exception as e:
        print(f"  ✗ Client error: {e}")
else:
    print("  SKIP — no key")

# ── Step 4: find working Gemini model ─────────────────────────
print()
print("=== GEMINI ===")
gemini_model    = None
gemini_fallback = None
if gemini_key:
    try:
        for mod_name in list(sys.modules):
            if "google" in mod_name or "genai" in mod_name:
                del sys.modules[mod_name]
        import importlib
        genai  = importlib.import_module("google.genai")
        client = genai.Client(api_key=gemini_key)

        # Get available models from API
        all_models = list(client.models.list())
        flash = [m.name.replace("models/","") for m in all_models if "flash" in m.name.lower()]
        print(f"  Available flash models: {flash[:6]}")

        GEMINI_CANDIDATES = flash + [
            "gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-001",
            "gemini-2.0-flash-lite", "gemini-1.5-flash", "gemini-1.5-flash-8b",
        ]
        for model in GEMINI_CANDIDATES:
            try:
                r = client.models.generate_content(
                    model=model,
                    contents='Reply with only: {"ok":true}',
                )
                print(f"  ✓ Primary model:  {model}")
                gemini_model = model
                # Find a fallback
                for fb in GEMINI_CANDIDATES:
                    if fb != model:
                        try:
                            client.models.generate_content(model=fb, contents="hi")
                            gemini_fallback = fb
                            print(f"  ✓ Fallback model: {fb}")
                            break
                        except Exception:
                            pass
                break
            except Exception as e:
                print(f"  ✗ {model}: {str(e)[:70]}")
    except ImportError:
        print("  ✗ google-genai not installed — run: pip install google-genai")
    except Exception as e:
        print(f"  ✗ {e}")
else:
    print("  SKIP — no key")

# ── Step 5: update config.py ──────────────────────────────────
print()
print("=== UPDATING config.py ===")
cfg_path = os.path.join(HERE, "config.py")
try:
    cfg = open(cfg_path, encoding="utf-8").read()
    orig = cfg

    if groq_model:
        cfg = re.sub(r'GROQ_MODEL\s*=\s*"[^"]+"',
                     f'GROQ_MODEL     = "{groq_model}"', cfg)
        cfg = re.sub(r'GROQ_FALLBACK\s*=\s*"[^"]+"',
                     f'GROQ_FALLBACK  = "llama-3.1-8b-instant"', cfg)
        print(f"  GROQ_MODEL    = {groq_model}")
    else:
        # Safe defaults even without testing
        cfg = re.sub(r'GROQ_MODEL\s*=\s*"[^"]+"',
                     'GROQ_MODEL     = "llama-3.3-70b-versatile"', cfg)
        cfg = re.sub(r'GROQ_FALLBACK\s*=\s*"[^"]+"',
                     'GROQ_FALLBACK  = "llama-3.1-8b-instant"', cfg)
        print("  GROQ_MODEL    = llama-3.3-70b-versatile (default)")

    if gemini_model:
        cfg = re.sub(r'GEMINI_MODEL\s*=\s*"[^"]+"',
                     f'GEMINI_MODEL   = "{gemini_model}"', cfg)
        print(f"  GEMINI_MODEL  = {gemini_model}")
    else:
        cfg = re.sub(r'GEMINI_MODEL\s*=\s*"[^"]+"',
                     'GEMINI_MODEL   = "gemini-2.0-flash"', cfg)
        print("  GEMINI_MODEL  = gemini-2.0-flash (default)")

    if gemini_fallback:
        cfg = re.sub(r'GEMINI_PRO\s*=\s*"[^"]+"',
                     f'GEMINI_PRO     = "{gemini_fallback}"', cfg)
        print(f"  GEMINI_PRO    = {gemini_fallback}")
    else:
        cfg = re.sub(r'GEMINI_PRO\s*=\s*"[^"]+"',
                     'GEMINI_PRO     = "gemini-1.5-flash"', cfg)

    if cfg != orig:
        open(cfg_path, "w", encoding="utf-8").write(cfg)
        print("  ✓ config.py saved")
    else:
        print("  (no changes needed)")

except Exception as e:
    print(f"  ✗ {e}")

print()
print("="*50)
print("Done. Restart the server:  python run.py")
print("="*50)
