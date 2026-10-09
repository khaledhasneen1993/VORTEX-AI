"""Optional Telegram operational notifications; NEVER log secrets or chat tokens."""
from __future__ import annotations
import os
import requests


def notify(event: str, *, session=None) -> bool:
    token = os.environ.get("VORTEX_TELEGRAM_TOKEN")
    chat = os.environ.get("VORTEX_TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    if not token.replace(":", "").replace("-", "").replace("_", "").isalnum():
        raise ValueError("Invalid Telegram token")
    if len(event) > 3000:
        event = event[:3000] + "..."
    sender = session or requests.Session()
    try:
        response = sender.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat, "text": "VORTEX AI\n" + event},
            timeout=8)
        response.raise_for_status()
        return bool(response.json().get("ok"))
    except (requests.RequestException, ValueError):
        return False


def detailed_event(kind, data):
    """PAPER notices; partial net and final cumulative net are explicitly different."""
    keys = ('symbol', 'side', 'score', 'entry', 'stop', 'target', 'qty', 'quantity',
            'margin', 'risk_fraction', 'entry_fee', 'exit_fee', 'allocated_entry_fee', 'exit', 'stage_net_pnl',
            'net_pnl', 'final', 'reason', 'wallet', 'votes', 'pyramid_count')
    return 'PAPER ' + kind + '\n' + '\n'.join(
        f'{key}: {data[key]}' for key in keys if key in data)
