"""Optional bounded Claude signal-review layer; no leverage/size/stop authority.

Every LLM response is UNTRUSTED and may only veto or approve a technical
candidate. Technical confluence and risk checks always run independently.
No account credentials, personal data, wallet or order identifiers are sent.
"""

from __future__ import annotations

import json
import math
import os

import requests

from .models import Signal


class ReviewUnavailable(RuntimeError):
    pass


def confirm(
    signal: Signal, *, session=None, api_key: str | None = None, model: str | None = None
) -> tuple[bool, float, str]:
    token = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY")
    if not token:
        raise ReviewUnavailable("Claude review enabled but ANTHROPIC_API_KEY is missing")
    chosen = model or os.environ.get("VORTEX_CLAUDE_MODEL", "claude-sonnet-4-5")
    if not chosen.startswith("claude-") or len(chosen) > 80:
        raise ReviewUnavailable("Unexpected Claude model identifier")
    if signal.side not in {"LONG", "SHORT"} or not math.isfinite(signal.entry):
        raise ValueError("Invalid technical candidate")
    # Only public market observations leave the host. The model has no order controls.
    payload = {
        "model": chosen,
        "max_tokens": 180,
        "temperature": 0,
        "system": (
            "Review a proposed futures strategy setup skeptically. "
            "Return ONLY a valid JSON object with keys "
            "approved (boolean), confidence (number 0-1), rationale (string <=120 chars). "
            "Do not give trading commands, change stop/target or suggest leverage. "
            "Reject incomplete data, anomalous direction or contradictory signals."
        ),
        "messages": [
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "symbol": signal.symbol,
                        "side": signal.side,
                        "technical_score": signal.score,
                        "entry": round(signal.entry, 8),
                        "stop": round(signal.stop, 8),
                        "target": round(signal.target, 8),
                        "technical_rationale": signal.reason[:240],
                        "entry_features": signal.features,
                    },
                    allow_nan=False,
                ),
            }
        ],
    }
    sender = session or requests.Session()
    try:
        resp = sender.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": token,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        blocks = resp.json()["content"]
        message = next(x["text"] for x in blocks if x["type"] == "text")
        review = json.loads(message)
        if set(review) != {"approved", "confidence", "rationale"}:
            raise ValueError("Unexpected LLM schema")
        if not isinstance(review["approved"], bool):
            raise ValueError("LLM approval not a boolean")
        if isinstance(review["confidence"], bool) or not isinstance(review["confidence"], (float, int)):
            raise ValueError("LLM confidence invalid")
        confidence = float(review["confidence"])
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("LLM confidence out of bounds")
        rationale = str(review["rationale"])[:120]
        return bool(review["approved"]) and confidence >= 0.6, confidence, rationale
    except (requests.RequestException, ValueError, TypeError, KeyError, StopIteration, IndexError) as exc:
        raise ReviewUnavailable("Claude review unavailable or malformed; abort candidate") from exc
