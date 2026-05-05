"""
VoyageAI model fixer.

Manual:
    python fix_models.py

Programmatic:
    from fix_models import run_model_fix
    run_model_fix()
"""
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.py"

DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_GROQ_FALLBACK = "llama-3.1-8b-instant"
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"
DEFAULT_GEMINI_PRO = "gemini-1.5-flash"


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(HERE / ".env")
        load_dotenv(HERE.parent / ".env")
    except Exception:
        pass


def _upgrade_sdks(logger=None) -> list[str]:
    upgraded = []
    for pkg in ("groq", "google-genai"):
        try:
            res = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", pkg],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0:
                upgraded.append(pkg)
            elif logger:
                logger.warning("SDK upgrade failed", extra={"package": pkg, "stderr": res.stderr[:300]})
        except Exception as exc:
            if logger:
                logger.warning("SDK upgrade exception", extra={"package": pkg, "error": str(exc)})
    return upgraded


def _detect_groq_model(logger=None) -> tuple[str | None, str]:
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if not groq_key:
        return None, "missing_key"

    candidates = [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "llama3-70b-8192",
        "llama3-8b-8192",
        "gemma2-9b-it",
    ]
    try:
        import importlib

        if "groq" in sys.modules:
            del sys.modules["groq"]
        groq_mod = importlib.import_module("groq")
        client = groq_mod.Groq(api_key=groq_key)
        for model in candidates:
            try:
                client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": '{"ok":true}'}],
                    max_tokens=20,
                )
                return model, "ok"
            except Exception as exc:
                if logger:
                    logger.info("Groq model check failed", extra={"model": model, "error": str(exc)[:120]})
        return None, "no_working_model"
    except Exception as exc:
        if logger:
            logger.warning("Groq client setup failed", extra={"error": str(exc)})
        return None, "client_error"


def _detect_gemini_models(logger=None) -> tuple[str | None, str | None, str]:
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not gemini_key:
        return None, None, "missing_key"

    try:
        import importlib

        for mod_name in list(sys.modules):
            if "google" in mod_name or "genai" in mod_name:
                del sys.modules[mod_name]

        genai = importlib.import_module("google.genai")
        client = genai.Client(api_key=gemini_key)
        all_models = list(client.models.list())
        flash = [m.name.replace("models/", "") for m in all_models if "flash" in m.name.lower()]
        candidates = flash + [
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-2.0-flash-001",
            "gemini-2.0-flash-lite",
            "gemini-1.5-flash",
            "gemini-1.5-flash-8b",
        ]
        primary = None
        fallback = None
        for model in candidates:
            try:
                client.models.generate_content(model=model, contents='Reply with only: {"ok":true}')
                primary = model
                break
            except Exception as exc:
                if logger:
                    logger.info("Gemini model check failed", extra={"model": model, "error": str(exc)[:120]})
        if primary:
            for model in candidates:
                if model == primary:
                    continue
                try:
                    client.models.generate_content(model=model, contents="hi")
                    fallback = model
                    break
                except Exception:
                    continue
            return primary, fallback, "ok"
        return None, None, "no_working_model"
    except Exception as exc:
        if logger:
            logger.warning("Gemini client setup failed", extra={"error": str(exc)})
        return None, None, "client_error"


def _rewrite_config(groq_model: str | None, gemini_model: str | None, gemini_fallback: str | None) -> bool:
    cfg = CONFIG_PATH.read_text(encoding="utf-8")
    original = cfg

    cfg = re.sub(
        r'GROQ_MODEL\s*=\s*"[^"]+"',
        f'GROQ_MODEL     = "{groq_model or DEFAULT_GROQ_MODEL}"',
        cfg,
    )
    cfg = re.sub(
        r'GROQ_FALLBACK\s*=\s*"[^"]+"',
        f'GROQ_FALLBACK  = "{DEFAULT_GROQ_FALLBACK}"',
        cfg,
    )
    cfg = re.sub(
        r'GEMINI_MODEL\s*=\s*"[^"]+"',
        f'GEMINI_MODEL   = "{gemini_model or DEFAULT_GEMINI_MODEL}"',
        cfg,
    )
    cfg = re.sub(
        r'GEMINI_PRO\s*=\s*"[^"]+"',
        f'GEMINI_PRO     = "{gemini_fallback or DEFAULT_GEMINI_PRO}"',
        cfg,
    )

    if cfg != original:
        CONFIG_PATH.write_text(cfg, encoding="utf-8")
        return True
    return False


def run_model_fix(upgrade_sdks: bool = False, logger=None) -> dict:
    """
    Ensure config.py points at working/default model names.

    Returns a summary dict suitable for logging.
    """
    _load_env()

    summary = {
        "upgraded": [],
        "groq_model": None,
        "groq_status": "skipped",
        "gemini_model": None,
        "gemini_fallback": None,
        "gemini_status": "skipped",
        "config_updated": False,
    }

    if upgrade_sdks:
        summary["upgraded"] = _upgrade_sdks(logger=logger)

    summary["groq_model"], summary["groq_status"] = _detect_groq_model(logger=logger)
    (
        summary["gemini_model"],
        summary["gemini_fallback"],
        summary["gemini_status"],
    ) = _detect_gemini_models(logger=logger)
    summary["config_updated"] = _rewrite_config(
        summary["groq_model"],
        summary["gemini_model"],
        summary["gemini_fallback"],
    )

    return summary


def main() -> int:
    summary = run_model_fix(upgrade_sdks=True, logger=None)
    print("")
    print("VoyageAI model fix summary")
    print("--------------------------")
    print(f"GROQ:   {summary['groq_model'] or DEFAULT_GROQ_MODEL} ({summary['groq_status']})")
    print(f"GEMINI: {summary['gemini_model'] or DEFAULT_GEMINI_MODEL} ({summary['gemini_status']})")
    print(f"Fallback Gemini: {summary['gemini_fallback'] or DEFAULT_GEMINI_PRO}")
    print(f"Config updated:  {summary['config_updated']}")
    if summary["upgraded"]:
        print(f"SDKs upgraded:   {', '.join(summary['upgraded'])}")
    print("")
    print("Done. Restart the server: python run.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
