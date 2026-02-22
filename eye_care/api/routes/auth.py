"""
Auth token endpoint - read-only, no token required.
"""
from flask import Flask, jsonify

from ..auth import get_token


def register_auth_routes(app: Flask, controller, log):
    @app.route("/api/auth/token", methods=["GET"])
    def auth_token():
        """返回当前会话 token，供前端缓存并附加到写请求 header。"""
        t = get_token()
        if not t:
            return jsonify({"error": "token_not_available", "token": None}), 500
        return jsonify({"token": t})
