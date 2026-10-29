"""
Dauerbetrieb für einen Server oder Container (nur Papiergeld).

- Alle `interval_min` Minuten ein Zyklus (abrechnen, scannen, Papier-Käufe),
  danach Statusbericht. Ein fehlgeschlagener Zyklus beendet den Dienst nicht.
- Statusseite auf $PORT (Standard 8080): `/` zeigt den Bericht, `/health`
  liefert JSON für Health-Checks des Hosters. Nur lesend, keine Eingaben.
- SIGTERM/SIGINT beenden sauber nach dem laufenden Zyklus.
"""
from __future__ import annotations

import html
import json
import os
import signal
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from paperbot.config import BotConfig

STALE_FACTOR = 3        # /health meldet Fehler, wenn der letzte Zyklus > 3 Intervalle her ist


class _State:
    def __init__(self, source: str, interval_s: float, report_path):
        self.source = source
        self.interval_s = interval_s
        self.report_path = report_path
        self.started = int(time.time())
        self.last_ok: Optional[int] = None
        self.last_error: Optional[str] = None
        self.cycles = 0
        self.lock = threading.Lock()

    def health(self) -> dict:
        with self.lock:
            now = int(time.time())
            ref = self.last_ok or self.started
            ok = now - ref <= STALE_FACTOR * self.interval_s + 300
            return {"ok": ok, "source": self.source, "cycles": self.cycles, "last_ok": self.last_ok,
                    "last_error": self.last_error, "uptime_s": now - self.started, "paper_only": True}


def _handler(state: _State):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (http.server-Schnittstelle)
            if self.path.startswith("/health"):
                h = state.health()
                self._send(200 if h["ok"] else 503, "application/json", json.dumps(h))
                return
            if self.path not in ("/", "/index.html"):
                self._send(404, "text/plain; charset=utf-8", "nicht gefunden")
                return
            try:
                text = state.report_path.read_text(encoding="utf-8")
            except OSError:
                text = "Noch kein Bericht – der erste Zyklus läuft."
            body = ("<!doctype html><meta charset=utf-8><title>paperbot</title>"
                    "<meta name=viewport content='width=device-width,initial-scale=1'>"
                    "<body style='font-family:system-ui;max-width:960px;margin:2em auto;padding:0 16px'>"
                    f"<p><b>Nur Papiergeld.</b> Quelle: {html.escape(state.source)} · "
                    f"<a href='/health'>/health</a></p><pre style='white-space:pre-wrap'>"
                    f"{html.escape(text)}</pre></body>")
            self._send(200, "text/html; charset=utf-8", body)

        def _send(self, code: int, ctype: str, body: str) -> None:
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):   # keine Zugriffsprotokolle im Container-Log
            pass

    return Handler


def run_one(source: str) -> dict:
    """Ein Zyklus wie `python -m paperbot cycle`, gibt den Bericht als dict zurück."""
    from paperbot.cli import _cfg, _client
    from paperbot.engine import run_cycle
    from paperbot.report import write_status
    cfg = _cfg(source)
    report = run_cycle(_client(source), cfg)
    write_status(cfg, source, last_cycle=report.as_dict())
    return report.as_dict()


def serve(source: str, interval_min: float = 30.0, port: Optional[int] = None,
          max_cycles: Optional[int] = None) -> int:
    cfg = BotConfig.from_env()
    port = int(port or os.environ.get("PORT") or 8080)
    state = _State(source, interval_min * 60, cfg.report_dir / f"STATUS_{source}.md")
    httpd = ThreadingHTTPServer(("0.0.0.0", port), _handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"[serve] {source}: Zyklus alle {interval_min:g} min, Status auf Port {port}", flush=True)

    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, lambda *_: stop.set())
        except ValueError:          # nicht im Hauptthread (Tests)
            pass
    while not stop.is_set():
        t0 = time.time()
        try:
            rep = run_one(source)
            with state.lock:
                state.cycles += 1
                state.last_ok = int(time.time())
                state.last_error = "; ".join(rep.get("errors") or [])[:500] or None
            print(f"[serve] Zyklus {state.cycles}: {len(rep.get('opened', []))} gekauft, "
                  f"{len(rep.get('settled', []))} abgerechnet, {len(rep.get('errors', []))} Fehler",
                  flush=True)
        except Exception as exc:    # Dienst läuft weiter, Fehler sichtbar in /health
            with state.lock:
                state.last_error = f"{exc!r}"[:500]
            traceback.print_exc(file=sys.stderr)
        if max_cycles is not None and state.cycles >= max_cycles:
            break
        stop.wait(max(5.0, interval_min * 60 - (time.time() - t0)))
    httpd.shutdown()
    return 0
