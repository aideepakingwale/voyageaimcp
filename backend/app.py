"""VoyageAI Flask application factory."""
from pathlib import Path

from flask import Flask, send_from_directory
from flask_cors import CORS

from config import Config


def create_app(config_class=Config) -> Flask:
    from core import init_logging, register_request_logging

    init_logging()
    _build_reference_cache()
    _build_guardrail_cache()

    frontend_dir = Path(__file__).resolve().parents[1] / "frontend"
    app = Flask(
        __name__,
        static_folder=str(frontend_dir),
        static_url_path="",
    )
    app.config.from_object(config_class)
    CORS(app, origins=config_class.CORS_ORIGINS)

    register_request_logging(app)
    _register_frontend_routes(app, frontend_dir)
    _register_blueprints(app)
    _log_startup()
    return app


def _build_reference_cache() -> None:
    from core.reference_cache import ref

    ref.build()
    try:
        import logging
        from data.reference_data import AIRPORTS, CURRENCIES, COUNTRIES, GBP_FALLBACK_RATES

        db_count = ref.stats().get("airports", 0)
        if len(AIRPORTS) <= db_count:
            return

        logging.getLogger("voyageai.app").warning(
            "DB has %d airports, source has %d; auto-reloading reference data",
            db_count,
            len(AIRPORTS),
        )
        from data.load_reference_data import create_tables, get_db, load_all

        conn = get_db()
        create_tables(conn)
        load_all(conn, AIRPORTS, CURRENCIES, COUNTRIES, GBP_FALLBACK_RATES)
        conn.close()
        ref.build()
    except Exception:
        pass


def _build_guardrail_cache() -> None:
    from core.guardrail_config_cache import gcfg

    gcfg.build()
    if gcfg.stats().get("source") == "database":
        return

    try:
        import logging
        from data.load_guardrail_config import (
            create_tables,
            get_db,
            load_config,
            load_injection_patterns,
            load_schema_rules,
            load_skip_codes,
            load_travel_signals,
        )

        logging.getLogger("voyageai.app").warning(
            "Guardrail tables missing or empty; auto-bootstrapping guardrail config"
        )
        conn = get_db()
        create_tables(conn)
        load_config(conn)
        load_skip_codes(conn)
        load_injection_patterns(conn)
        load_travel_signals(conn)
        load_schema_rules(conn)
        conn.close()
        gcfg.reload()
    except Exception:
        pass


def _register_blueprints(app: Flask) -> None:
    from api.admin import bp as admin_bp
    from api.ancillaries import bp as ancillaries_bp
    from api.auth import bp as auth_bp
    from api.chat import bp as chat_bp
    from api.customer import bp as customer_bp
    from api.health import bp as health_bp
    from api.locate import bp as locate_bp
    from api.logs import bp as logs_bp
    from api.loyalty import bp as loyalty_bp
    from api.mcp import bp as mcp_bp
    from api.session import bp as session_bp

    for bp in (
        health_bp,
        session_bp,
        chat_bp,
        customer_bp,
        loyalty_bp,
        ancillaries_bp,
        mcp_bp,
        auth_bp,
        locate_bp,
        admin_bp,
        logs_bp,
    ):
        app.register_blueprint(bp, url_prefix="/api")


def _register_frontend_routes(app: Flask, frontend_dir: Path) -> None:
    @app.get("/")
    def frontend_index():
        return send_from_directory(frontend_dir, "login.html")

    @app.get("/login")
    def frontend_login():
        return send_from_directory(frontend_dir, "login.html")

    @app.get("/app")
    def frontend_app():
        return send_from_directory(frontend_dir, "index.html")

    @app.get("/logs")
    def frontend_logs():
        return send_from_directory(frontend_dir, "logs.html")

    @app.get("/<path:asset_path>")
    def frontend_assets(asset_path: str):
        asset_file = frontend_dir / asset_path
        if asset_file.is_file():
            return send_from_directory(frontend_dir, asset_path)
        return send_from_directory(frontend_dir, "login.html")


def _log_startup() -> None:
    print("")
    print("===================================")
    print("         VoyageAI v3.0")
    print("   Autonomous Travel Assistant")
    print("===================================")


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
