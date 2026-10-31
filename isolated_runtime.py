"""Explicit disposable local runtime. Never reads .env or a business database."""
import secrets
import socket
import tempfile
from pathlib import Path

import requests

_directory = None


def deny_network(*args, **kwargs):
    raise RuntimeError("External network disabled in isolated mode")


def configure(app):
    global _directory
    _directory = tempfile.TemporaryDirectory(prefix="logistics-v1-")
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///" + str(Path(_directory.name) / "test.db"),
        SECRET_KEY=secrets.token_hex(32),
        ISOLATED_MODE=True,
    )
    # Block both HTTP and direct Python TCP connections before importing routes.
    requests.sessions.Session.request = deny_network
    requests.sessions.Session.send = deny_network
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    socket.create_connection = deny_network

    @app.after_request
    def browser_network_policy(response):
        # A browser must not bypass the Python guard via legacy remote fetch URLs.
        response.headers["Content-Security-Policy"] = "connect-src 'self'; form-action 'self'"
        return response
