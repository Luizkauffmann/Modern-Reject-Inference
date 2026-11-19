"""Reject Inference Explorer, standalone web app.

    python app.py            # then open http://127.0.0.1:5000
"""

import os

from flask import Flask, Response, send_from_directory

from reject_inference import explorer

UI_DIR = os.path.join(os.path.dirname(os.path.abspath(explorer.__file__)), "ui")

app = Flask(__name__)
explorer.register(app)


@app.route("/")
def index():
    with open(os.path.join(UI_DIR, "index.html"), encoding="utf-8") as f:
        body = f.read()
    page = ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>Reject Inference Explorer</title>"
            "<style>html,body{margin:0;height:100%}#app-root{height:100vh}</style>"
            "<link rel='stylesheet' href='/ui/app.css'></head>"
            "<body><div id='app-root'>" + body + "</div><script src='/ui/app.js'></script></body></html>")
    return Response(page, mimetype="text/html")


@app.route("/ui/<path:name>")
def ui(name):
    return send_from_directory(UI_DIR, name)


if __name__ == "__main__":
    app.run(host=os.environ.get("RI_HOST", "127.0.0.1"), port=int(os.environ.get("RI_PORT", "5000")), debug=False)
