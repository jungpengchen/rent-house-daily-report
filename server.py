"""
HTTP API server — 接收 request 觸發爬蟲 pipeline。

端點：
    GET  /health          健康檢查
    GET  /status          最近一次執行結果
    POST /run             立即執行（背景非同步）
    POST /run?dry_run=1   dry-run，不發通知、不寫 DB

啟動：
    python server.py
    # 或
    gunicorn server:app -b 0.0.0.0:8080 --timeout 120
"""

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("server")

app = Flask(__name__)

# ── 執行狀態 ──────────────────────────────────────────────────────────────────

_lock = threading.Lock()
_status: dict = {
    "state": "idle",        # idle | running | done | error
    "started_at": None,
    "finished_at": None,
    "new_listings": None,
    "error": None,
    "dry_run": False,
}


def _run_in_background(cfg: dict, dry_run: bool) -> None:
    with _lock:
        _status.update(state="running", started_at=datetime.now().isoformat(),
                       finished_at=None, new_listings=None, error=None,
                       dry_run=dry_run)
    try:
        from main import run_pipeline
        count = run_pipeline(cfg, dry_run=dry_run)
        with _lock:
            _status.update(state="done", finished_at=datetime.now().isoformat(),
                           new_listings=count)
        logger.info("Pipeline done. New listings: %d", count)
    except Exception as exc:
        logger.error("Pipeline error: %s", exc, exc_info=True)
        with _lock:
            _status.update(state="error", finished_at=datetime.now().isoformat(),
                           error=str(exc))


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return jsonify(status="ok"), 200


@app.get("/status")
def status():
    with _lock:
        return jsonify(dict(_status)), 200


@app.post("/run")
def run():
    # 驗證 API key（若有設定）
    api_key = os.getenv("API_KEY", "")
    if api_key:
        provided = request.headers.get("X-Api-Key", "")
        if provided != api_key:
            return jsonify(error="Unauthorized"), 401

    with _lock:
        if _status["state"] == "running":
            return jsonify(error="Pipeline already running"), 409

    dry_run = request.args.get("dry_run", "0") in ("1", "true", "yes")

    try:
        import yaml
        config_path = os.getenv("CONFIG_PATH", "config.yaml")
        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
    except Exception as exc:
        return jsonify(error=f"Config load failed: {exc}"), 500

    Path("data").mkdir(exist_ok=True)
    thread = threading.Thread(target=_run_in_background, args=(cfg, dry_run),
                              daemon=True)
    thread.start()

    return jsonify(message="Pipeline started", dry_run=dry_run), 202


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
