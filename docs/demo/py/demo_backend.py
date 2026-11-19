"""Routes the browser demo's 'requests' to the unchanged Explorer backend (running in Pyodide)."""
import json

import flask


class App(object):
    def __init__(self):
        self.routes = {}

    def route(self, path, methods=None):
        def deco(f):
            self.routes[path] = f
            return f
        return deco


APP = App()


def register(module):
    __import__(module).register(APP)


def dispatch(path, body):
    """-> (text, status, content type)."""
    f = APP.routes.get(path)
    if f is None:
        return json.dumps({"ok": False, "error": "Unknown route %s" % path}), 404, "application/json"
    flask.request._json = json.loads(body) if body else None
    try:
        rv = f()
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}), 500, "application/json"
    status = 200
    if isinstance(rv, tuple):
        rv, status = rv[0], rv[1]
    if isinstance(rv, flask.JsonReply):
        rv = rv.payload
    return json.dumps(rv, default=str), status, "application/json"
