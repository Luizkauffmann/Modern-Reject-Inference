"""Tiny stand-in for the parts of Flask the Explorer backend uses (browser demo only)."""


class _Request(object):
    def __init__(self):
        self._json, self.args, self.headers = None, {}, {}

    def get_json(self, silent=False, force=False):
        return self._json


request = _Request()


class JsonReply(object):
    def __init__(self, payload):
        self.payload = payload


def jsonify(*args, **kwargs):
    return JsonReply(args[0] if args else kwargs)
