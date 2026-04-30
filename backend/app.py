"""VoyageAI Flask Application Factory"""
from flask      import Flask
from flask_cors import CORS
from config     import Config


def create_app(config_class=Config) -> Flask:
    # ── Logging must be first ──────────────────────────────────
    from core import init_logging, register_request_logging
    init_logging()

    # Build reference cache from data/reference_data.py (once at startup)
    from core.reference_cache import ref as _ref
    _ref.build()

    # Build guardrail config cache from guardrail_* DB tables (once at startup)
    from core.guardrail_config_cache import gcfg as _gcfg
    _gcfg.build()

    app = Flask(__name__)
    app.config.from_object(config_class)
    CORS(app, origins=config_class.CORS_ORIGINS)

    # HTTP request/response logging middleware
    register_request_logging(app)

    _register_blueprints(app)
    _log_startup()
    return app


def _register_blueprints(app):
    from api.health      import bp as health_bp
    from api.session     import bp as session_bp
    from api.chat        import bp as chat_bp
    from api.customer    import bp as customer_bp
    from api.loyalty     import bp as loyalty_bp
    from api.ancillaries import bp as ancillaries_bp
    from api.mcp         import bp as mcp_bp
    from api.auth        import bp as auth_bp
    from api.locate      import bp as locate_bp

    app.register_blueprint(health_bp,      url_prefix="/api")
    app.register_blueprint(session_bp,     url_prefix="/api")
    app.register_blueprint(chat_bp,        url_prefix="/api")
    app.register_blueprint(customer_bp,    url_prefix="/api")
    app.register_blueprint(loyalty_bp,     url_prefix="/api")
    app.register_blueprint(ancillaries_bp, url_prefix="/api")
    app.register_blueprint(mcp_bp,         url_prefix="/api")
    app.register_blueprint(auth_bp,        url_prefix="/api")
    app.register_blueprint(locate_bp,      url_prefix="/api")


def _log_startup():
    print("\n╔═══════════════════════════════════╗")
    print("║         VoyageAI  v3.0            ║")
    print("║   Autonomous Travel Assistant     ║")
    print("╚═══════════════════════════════════╝")
