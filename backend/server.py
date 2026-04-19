"""
ASGI entry for FilterIN Flask app.
Mounts the WSGI Flask app at /api/ so it works with Emergent's ingress
(which routes /api/* to backend port 8001).
"""
import os
from asgiref.wsgi import WsgiToAsgi
from app_flask import flask_app


class PathPrefixMiddleware:
    """WSGI middleware that strips a URL prefix and sets SCRIPT_NAME.

    Example: request /api/login -> Flask sees PATH_INFO=/login, SCRIPT_NAME=/api.
    url_for() therefore generates /api/login correctly.
    """

    def __init__(self, app, prefix):
        self.app = app
        self.prefix = prefix.rstrip('/')

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        if path == self.prefix or path.startswith(self.prefix + '/'):
            environ['SCRIPT_NAME'] = (environ.get('SCRIPT_NAME', '') + self.prefix)
            environ['PATH_INFO'] = path[len(self.prefix):] or '/'
        return self.app(environ, start_response)


# Mount Flask app at /api
flask_app.wsgi_app = PathPrefixMiddleware(flask_app.wsgi_app, '/api')

# ASGI wrapper for uvicorn
app = WsgiToAsgi(flask_app)
