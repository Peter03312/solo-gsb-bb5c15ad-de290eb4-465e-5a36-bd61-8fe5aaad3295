"""Flask 后端：原稿查询、修补预览、预览确认。"""

import hashlib
import json
import os
import uuid

from flask import Flask, jsonify, request, send_from_directory

from db import Database
from solver import solve_repair
from validate import ValidationError, canonical, validate_design
from weave import find_violations

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "data", "weave.db"))
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

db = Database(DB_PATH)

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")


def _design_payload(design):
    """原稿及其超限段，供页面展示。"""
    payload = dict(design)
    payload["violations"] = find_violations(
        design["grid"], design["rows"], design["cols"], design["k"])
    return payload


def _fingerprint(obj):
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@app.get("/api/state")
def get_state():
    return jsonify(_design_payload(db.get_design()))


@app.post("/api/preview")
def preview():
    try:
        rows, cols, grid, locks, k = validate_design(request.get_json(silent=True))
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400

    input_obj = canonical(rows, cols, grid, locks, k)
    violations = find_violations(grid, rows, cols, k)
    solved = solve_repair(rows, cols, k, grid, locks)

    if solved is None:
        # 无可行修补：保留原稿，仅报无解（不产生可确认的预览）
        return jsonify({
            "solvable": False,
            "violations": violations,
            "input": input_obj,
        })

    result = {
        "repaired": solved["repaired"],
        "flips": solved["flips"],
        "flipCount": len(solved["flips"]),
    }
    token = uuid.uuid4().hex
    db.save_preview(token, input_obj, result)
    return jsonify({
        "solvable": True,
        "token": token,
        "violations": violations,
        "input": input_obj,
        **result,
    })


@app.post("/api/confirm")
def confirm():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "请求体必须是 JSON 对象"}), 400

    token = body.get("token")
    if not isinstance(token, str) or not token:
        return jsonify({"error": "缺少预览令牌"}), 400

    try:
        rows, cols, grid, locks, k = validate_design(body)
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400

    stored = db.get_preview(token)
    if stored is None:
        return jsonify({"error": "预览不存在或已失效，请重新预览"}), 409

    current = canonical(rows, cols, grid, locks, k)
    if _fingerprint(current) != _fingerprint(stored["input"]):
        return jsonify({"error": "预览后稿件已变动，旧预览已失效，请重新预览"}), 409

    result = stored["result"]
    design = db.save_design(rows, cols, result["repaired"], locks, k)
    db.delete_preview(token)
    return jsonify({"state": _design_payload(design)})


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.errorhandler(404)
def not_found(_):
    return jsonify({"error": "接口不存在"}), 404


@app.errorhandler(405)
def method_not_allowed(_):
    return jsonify({"error": "方法不允许"}), 405


@app.errorhandler(500)
def internal_error(exc):
    return jsonify({"error": "服务器内部错误"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    debug = os.environ.get("FLASK_DEBUG", "") == "1"
    if debug:
        app.run(host="0.0.0.0", port=port, debug=True)
    else:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port)
