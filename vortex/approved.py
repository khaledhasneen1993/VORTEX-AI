"""User-adopted PAPER configuration from d54ee34; not profitability approval."""

from dataclasses import fields

APPROVED_SOURCE = "d54ee349d470c97862059058ecefa8285c1a0083"
APPROVED_ENV = {
    "BASKET_ENABLED": "false",
    "BASKET_MIN_ENTRY_FILL_RATIO": "0",
    "RUN_MODE": "paper",
    "TIMEFRAME": "5m",
    "TRAILING_ATR_MULT": "1.0",
    "STARTING_EQUITY": "20",
    "PAPER_EXP_ENABLED": "true",
    "PAPER_EXP_CAPTURE_ENABLED": "true",
    "PAPER_EXP_AVERAGE_ENABLED": "true",
    "PAPER_EXP_PROFIT_MARGIN": "0.04",
    "PAPER_EXP_STOP_PRICE": "0.10",
    "PAPER_EXP_ACCOUNT_LOSS": "0.25",
    "PAPER_EXP_AVERAGE_TRIGGER": "0.05",
    "PAPER_EXP_AVERAGE_FRACTION": "0.50",
    "OPS_PROFILE": "aggressive",
    "RISK_PER_TRADE": "0.12",
    "MAX_DAILY_LOSS": "0.25",
    "MAX_POSITIONS": "5",
    "MAX_LEVERAGE": "5",
    "MAX_MARGIN_FRACTION": "0.25",
    "COOLDOWN_MINUTES": "5",
    "STRICT_VOTES": "false",
    "ALLOW_SINGLE_STRONG_VOTE": "true",
    "MIN_STRONG_SCORE": "6",
    "MIN_SCORE": "5",
    "PHASE2_AGGRESSIVE_STRONG_RISK": "true",
    "PHASE2_STRONG_MAX": "0.18",
    "OPS_SHORT_LOSS_COOLDOWN": "true",
    "RADAR_LIMIT": "30",
    "RADAR_FAST_RANKING": "true",
    "LOOP_SECONDS": "10",
    "PHASE1_REGIME_ENABLED": "false",
    "PHASE1_FLOW_ENABLED": "true",
    "PHASE1_FLOW_MODE": "voter",
    "PHASE1_VOLUME_SPIKE_ENABLED": "true",
    "PHASE1_LIQUIDITY_SWEEP_ENABLED": "false",
    "PHASE1_FUNDING_FLOW_CONFIRM": "false",
    "PHASE1_SESSION_FILTER": "false",
    "PAPER_FAST_SCAN": "true",
    "PAPER_SCAN_WORKERS": "4",
    "LIVE_RESILIENCE": "true",
    "HEALTH_ENABLED": "true",
    "RECORDER_ENABLED": "true",
    "RECORDER_DECISIONS": "true",
    "RECORDER_INTERVAL_SECONDS": "60",
    "RECORDER_FLOW": "true",
    "RECORDER_SHUTDOWN_SECONDS": "15",
    "USE_RADAR": "true",
    "USE_WEBSOCKET": "false",
    "USE_AI_MODEL": "false",
    "USE_CLAUDE": "false",
    "USE_MICROSTRUCTURE": "false",
    "OPS_FOCUS_SYMBOL": "",
    "OPS_TELEGRAM_ALERTS": "false",
    "DATA_DIR": "data/vortex-approved",
    "PHASE1_ENABLED": "true",
    "PHASE2_ENABLED": "true",
    "OPS_ENABLED": "true",
}


def policy_defaults(cls, prefix="", aliases=None):
    """One source of deployment defaults; persisted policy schemas stay unchanged."""
    defaults = cls()
    values = {}
    aliases = aliases or {}
    for field in fields(cls):
        raw = APPROVED_ENV.get(aliases.get(field.name, prefix + field.name.upper()))
        if raw is None:
            continue
        value = getattr(defaults, field.name)
        values[field.name] = raw == "true" if isinstance(value, bool) else type(value)(raw)
    return cls(**values)


def canonical_environment(values, setting_fields):
    """Reset old deployment overrides without discarding local credentials."""
    values = dict(values)
    setting_keys = {field.name.upper() for field in setting_fields}
    for key in list(values):
        if key in setting_keys or key.startswith(
            ("PHASE1_", "PHASE2_", "OPS_", "PAPER_EXP_", "RECORDER_", "BASKET_")
        ):
            values.pop(key)
    values.pop("VORTEX_CLAUDE_MODEL", None)
    values.update(APPROVED_ENV)
    return values
