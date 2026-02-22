"""
Health check route.
"""
from flask import Flask, jsonify
from ..common import API_VERSION


def register_health_routes(app: Flask, controller, log):
    @app.route("/api/health", methods=["GET"])
    def health():
        return jsonify({"ok": True, "api_version": API_VERSION})
