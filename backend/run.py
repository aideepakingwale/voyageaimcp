"""
VoyageAI server entry point.
Run: python run.py
Open: http://127.0.0.1:5000
"""
import os

from core.logging_config import get_logger, init_logging
from fix_models import run_model_fix

init_logging()

log = get_logger("app")
model_fix_summary = run_model_fix(
    upgrade_sdks=os.getenv("VOYAGEAI_FIX_MODELS_UPGRADE_SDKS", "").strip().lower() in {"1", "true", "yes"},
    logger=log,
)
log.info("Model fix completed", extra=model_fix_summary)

from app import create_app

app = create_app()
FRONTEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))


if __name__ == "__main__":
    log.info(
        "VoyageAI server starting",
        extra={"frontend": FRONTEND, "port": 5000, "debug": False},
    )
    print("")
    print(f"  Frontend: {FRONTEND}")
    print("  Open:     http://127.0.0.1:5000")
    print(f"  Logs:     {os.path.abspath('logs/')}")
    print("")
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
