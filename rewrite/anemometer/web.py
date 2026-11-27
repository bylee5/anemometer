"""Flask application: the HTTP entry point (formerly index.php).

All pages are served from one URL and selected with ``?action=``; both ``/``
and ``/index.php`` work, so existing bookmarks and favourites keep working.

Environment variables:

``ANEMOMETER_CONFIG``      configuration module (default: ``conf/config.py``
                           next to the ``anemometer`` package)
``ANEMOMETER_STATIC_DIR``  directory containing ``js/``, ``css/`` and ``img/``
                           (default: the repository root, one level up)
``ANEMOMETER_SECRET_KEY``  key used to sign the session cookie
``ANEMOMETER_TIMEZONE``    IANA time zone for graphs (default: server local time)
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, Response, abort, redirect, request, send_from_directory, session

from anemometer.config import AppConfig, load_config
from anemometer.controller import Anemometer
from anemometer.request_vars import RequestVars, parse_php_params
from anemometer.views import make_environment

__all__ = ["create_app"]

log = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_DIR / "conf" / "config.py"
DEFAULT_STATIC_DIR = PROJECT_DIR.parent
STATIC_SUBDIRS = ("js", "css", "img")


def create_app(
    config: AppConfig | None | str | Path = DEFAULT_CONFIG,
    *,
    static_dir: str | Path | None = None,
    secret_key: str | None = None,
    timezone: str | None = None,
) -> Flask:
    """Build the application.

    :param config: an :class:`AppConfig`, or the path of a configuration module.
        A missing file (or ``None``) shows the "not configured" page.
    """
    if isinstance(config, (str, Path)):
        config = load_config(os.environ.get("ANEMOMETER_CONFIG", config))
    static_dir = Path(static_dir or os.environ.get("ANEMOMETER_STATIC_DIR", DEFAULT_STATIC_DIR))
    timezone = timezone or os.environ.get("ANEMOMETER_TIMEZONE")
    tz = ZoneInfo(timezone) if timezone else None

    app = Flask(__name__, static_folder=None)
    app.secret_key = secret_key or os.environ.get("ANEMOMETER_SECRET_KEY")
    if not app.secret_key:
        log.warning("ANEMOMETER_SECRET_KEY is not set; sessions won't survive a restart")
        app.secret_key = secrets.token_hex(32)
    env = make_environment()

    @app.route("/", methods=["GET", "POST"])
    @app.route("/index.php", methods=["GET", "POST"])
    def dispatch() -> Response:
        params = RequestVars(
            parse_php_params(request.args.items(multi=True)),
            parse_php_params(request.form.items(multi=True)),
        )
        action = request.args.get("action", "index")
        if config is None:
            action = "noconfig"
        authorization = request.authorization
        controller: Anemometer | None = None
        status = 200
        try:
            controller = Anemometer(
                config,
                params,
                env=env,
                site_url=request.script_root + request.path,
                session=session,
                auth_user=authorization.username if authorization else None,
                tz=tz,
            )
            controller.run(action)
        except Exception as exc:
            log.exception("error handling action %s", action)
            status = 500
            body = controller.body if controller is not None else ""
            body += f'<div class="alert alert-error"><strong>Error</strong> {exc}</div>'
            return Response(body, status=status, mimetype="text/html")
        finally:
            if controller is not None:
                controller.close()

        if controller.redirect_to is not None:
            return redirect(controller.redirect_to)
        return Response(controller.body, status=status, mimetype="text/html")

    @app.route("/<any(js, css, img):folder>/<path:filename>")
    def static_files(folder: str, filename: str) -> Response:
        directory = static_dir / folder
        if not directory.is_dir():
            abort(404)
        return send_from_directory(directory, filename)

    return app
