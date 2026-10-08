"""Local, read-only paper trading dashboard (127.0.0.1 only).

Never expose to the public Internet. No buttons change positions, risk or settings.
"""
from __future__ import annotations
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from .config import Settings


def serve(cfg: Settings, port: int = 8765) -> None:
    if not 1024 <= port <= 65535:
        raise ValueError("Invalid local dashboard port")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlparse(self.path).path
            if path not in ("/", "/api/status", "/api/trades"):
                self.send_error(404)
                return
            try:
                state_path = cfg.data_dir / "paper_state.json"
                state = json.loads(state_path.read_text()) if state_path.exists() else {
                    "wallet": cfg.starting_equity, "positions": {}, "closed_count": 0,
                    "risk": {"blocked": False, "consecutive_losses": 0}}
                journal = cfg.data_dir / "closed_trades.jsonl"
                trades = ([json.loads(line) for line in journal.read_text().splitlines() if line.strip()][-100:]
                          if journal.exists() else [])
            except (OSError, ValueError, KeyError):
                self.send_error(503, "Unable to load paper state")
                return
            self.send_response(200)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
            if path.startswith("/api/"):
                self.send_header("Content-Type", "application/json; charset=utf-8")
                body = json.dumps(state if path == "/api/status" else trades).encode()
            else:
                position_rows = "".join(
                    "<tr><td>" + html.escape(s) + "</td><td>" +
                    html.escape(str(p.get("side", ""))) + "</td><td>" +
                    html.escape(str(p.get("entry", ""))) + "</td></tr>"
                    for s, p in state.get("positions", {}).items()
                ) or "<tr><td colspan=3>No open paper positions</td></tr>"
                trades_rows = "".join(
                    "<tr><td>" + html.escape(str(t.get("symbol", ""))) +
                    "</td><td>" + html.escape(str(t.get("side", ""))) +
                    "</td><td>" + html.escape(str(t.get("net_pnl", ""))) +
                    "</td><td>" + html.escape(str(t.get("reason", ""))) + "</td></tr>"
                    for t in reversed(trades[-25:])
                ) or "<tr><td colspan=4>No closed trades yet</td></tr>"
                page = f"""<!doctype html><html lang=en><meta charset=utf-8>
<title>VORTEX AI — Paper Dashboard</title>
<style>body{{background:#0b1325;color:#e5e7eb;font:16px system-ui;margin:2rem auto;max-width:940px;padding:0 1rem}}
h1{{color:#67e8f9}}.cards{{display:flex;flex-wrap:wrap;gap:1rem}}.card{{background:#19253b;padding:1rem 2rem;border-radius:12px;flex:1}}
table{{width:100%;border-collapse:collapse;margin-bottom:1.5rem}}th,td{{text-align:left;padding:.7rem;border-bottom:1px solid #344155}}
small{{color:#94a3b8}}</style><h1>VORTEX AI</h1><p>PAPER MODE — no live exchange orders</p>
<div class=cards><div class=card><small>Realized wallet (USDT)</small><h2>{float(state.get("wallet", 0)):.2f}</h2></div>
<div class=card><small>Closed trades</small><h2>{int(state.get("closed_count", 0))}</h2></div>
<div class=card><small>Risk halted</small><h2>{html.escape(str(state.get("risk", {}).get("blocked", False)))}</h2></div></div>
<h2>Open paper positions</h2><table><tr><th>Symbol</th><th>Side</th><th>Entry</th></tr>{position_rows}</table>
<h2>Recent closed trades</h2><table><tr><th>Symbol</th><th>Side</th><th>Net PnL</th><th>Reason</th></tr>{trades_rows}</table>
<p><small>Read-only snapshot. Unrealized PnL not included. Refresh to update.</small></p></html>"""
                self.send_header("Content-Type", "text/html; charset=utf-8")
                body = page.encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"LOCAL paper dashboard http://127.0.0.1:{port}")
    server.serve_forever()
