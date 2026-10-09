"""Opt-in delivery of manual cards; persistent at-most-once send attempts."""
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import sqlite3
import time

from .alerts import notify


def format_card(card):
    s = card['signal']
    expiry = datetime.fromtimestamp(card['expires_ms'] / 1000, timezone.utc)
    lines = [
        'إشارة للمراجعة اليدوية — لا تنفيذ تلقائي',
        f"{s['symbol']} | {s['side']}",
        f"الدخول التقريبي: {s['entry']:.10g}",
        f"وقف الخسارة: {s['stop']:.10g}",
        f"الهدف: {s['target']:.10g}",
        f"الدرجة: {s['score']} | الأصوات: {', '.join(s['votes'])}",
        f"الرافعة في الحساب التوضيحي: {card['leverage']}x",
        f"تنتهي صلاحية الإشارة: {expiry:%Y-%m-%d %H:%M:%S} UTC",
    ]
    if card['quantity'] is None:
        lines.append('المبلغ والكمية: غير محددين')
    else:
        lines.append(f"كمية توضيحية: {card['quantity']:.10g} | هامش توضيحي: {card['margin_usdt']:.4f} USDT")
    lines.append('راجع السعر الحالي وصلاحية الإشارة ورصيدك ومراكزك قبل قرارك. الأسعار استرشادية والحساب غير متصل.')
    return '\n'.join(lines)


class ManualTelegram:
    def __init__(self, path: Path):
        token = os.environ.get('VORTEX_TELEGRAM_TOKEN', '').strip()
        chat = os.environ.get('VORTEX_TELEGRAM_CHAT_ID', '').strip()
        if not token or not token.replace(':', '').replace('-', '').replace('_', '').isalnum():
            raise ValueError('Set a valid VORTEX_TELEGRAM_TOKEN locally in .env')
        if not chat.isdecimal():
            raise ValueError('Set your private VORTEX_TELEGRAM_CHAT_ID locally in .env')
        self.destination = hashlib.sha256((token.split(':')[0] + ':' + chat).encode()).hexdigest()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, status TEXT NOT NULL)')
        self.db.commit()
        self.blocked_until = 0.0

    def send(self, card, now_ms):
        # Caller supplies a fresh exchange clock; network work does not renew expiry.
        if not card['created_ms'] <= now_ms < card['expires_ms']:
            return 'expired'
        if time.monotonic() < self.blocked_until:
            return 'delivery_backoff'
        s = card['signal']
        key = f"{self.destination}:{s['symbol']}:{s['side']}:{s['ts']}"
        with self.db:
            inserted = self.db.execute('INSERT OR IGNORE INTO attempts VALUES (?, ?)',
                                       (key, 'attempted')).rowcount
        if not inserted:
            return 'duplicate'
        # Commit before HTTP: a crash/timeout must not replay an uncertain send.
        status = 'sent' if notify(format_card(card)) else 'failed_or_uncertain'
        with self.db:
            self.db.execute('UPDATE attempts SET status=? WHERE id=?', (status, key))
        if status != 'sent':
            self.blocked_until = time.monotonic() + 60
        return status

    def close(self):
        self.db.close()
