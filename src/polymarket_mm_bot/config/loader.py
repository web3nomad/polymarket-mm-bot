from __future__ import annotations

from pathlib import Path

from polymarket_mm_bot.config.models import (
    AppConfig,
    ExecutionConfig,
    MarketSelectionConfig,
    RiskConfig,
    RuntimeConfig,
    StrategyConfig,
    TelemetryConfig,
)

try:
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - environment dependent
    yaml = None


def _require(mapping: dict, key: str) -> object:
    if key not in mapping:
        raise ValueError(f"Missing config key: {key}")
    return mapping[key]


def _as_dict(raw: object, section: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"Config section '{section}' must be a mapping")
    return raw


def _load_mapping(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        payload = yaml.safe_load(text) or {}
        if not isinstance(payload, dict):
            raise ValueError("Config root must be a mapping")
        return payload
    return _parse_simple_yaml(text)


def load_app_config(path: Path) -> AppConfig:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    raw = _load_mapping(path)

    risk_raw = _as_dict(_require(raw, "risk"), "risk")
    strategy_raw = _as_dict(_require(raw, "strategy"), "strategy")
    market_raw = _as_dict(_require(raw, "market_selection"), "market_selection")
    execution_raw = _as_dict(_require(raw, "execution"), "execution")
    telemetry_raw = _as_dict(raw.get("telemetry", {}), "telemetry")
    runtime_raw = _as_dict(raw.get("runtime", {}), "runtime")

    risk = RiskConfig(
        total_capital=float(_require(risk_raw, "total_capital")),
        strategy_capital=float(_require(risk_raw, "strategy_capital")),
        per_trade_risk_pct=float(_require(risk_raw, "per_trade_risk_pct")),
        market_exposure_pct=float(_require(risk_raw, "market_exposure_pct")),
        theme_exposure_pct=float(_require(risk_raw, "theme_exposure_pct")),
        daily_drawdown_stop_pct=float(_require(risk_raw, "daily_drawdown_stop_pct")),
        max_open_orders=int(risk_raw.get("max_open_orders", 200)),
    )

    strategy = StrategyConfig(
        quote_refresh_sec=float(_require(strategy_raw, "quote_refresh_sec")),
        quote_half_spread_bps=float(_require(strategy_raw, "quote_half_spread_bps")),
        inventory_skew_bps_per_contract=float(_require(strategy_raw, "inventory_skew_bps_per_contract")),
        max_inventory_contracts=float(_require(strategy_raw, "max_inventory_contracts")),
    )

    market_selection = MarketSelectionConfig(
        top_n=int(_require(market_raw, "top_n")),
        min_liquidity=float(_require(market_raw, "min_liquidity")),
        max_spread_bps=float(_require(market_raw, "max_spread_bps")),
        min_minutes_to_expiry=int(_require(market_raw, "min_minutes_to_expiry")),
    )

    execution = ExecutionConfig(
        mode=str(execution_raw.get("mode", "paper")),
        default_order_size=float(_require(execution_raw, "default_order_size")),
        slippage_bps=float(execution_raw.get("slippage_bps", 5.0)),
    )

    telemetry = TelemetryConfig(
        db_path=str(telemetry_raw.get("db_path", "data/paper_runs.sqlite3")),
        persist_positions_every_loop=bool(telemetry_raw.get("persist_positions_every_loop", True)),
    )

    runtime = RuntimeConfig(
        dry_run=bool(runtime_raw.get("dry_run", True)),
        log_level=str(runtime_raw.get("log_level", "INFO")),
    )

    return AppConfig(
        risk=risk,
        strategy=strategy,
        market_selection=market_selection,
        execution=execution,
        telemetry=telemetry,
        runtime=runtime,
    )


def _parse_simple_yaml(text: str) -> dict:
    """Parse a small YAML subset (nested mappings with scalar values)."""
    root: dict[str, object] = {}
    stack: list[tuple[int, dict[str, object]]] = [(0, root)]

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip(" "))
        key, sep, value = line.strip().partition(":")
        if not sep:
            raise ValueError(f"Invalid YAML line: {raw_line}")

        while stack and indent < stack[-1][0]:
            stack.pop()
        if not stack:
            raise ValueError("Invalid indentation in YAML")

        current = stack[-1][1]
        value = value.strip()
        if value == "":
            child: dict[str, object] = {}
            current[key] = child
            stack.append((indent + 2, child))
        else:
            current[key] = _parse_scalar(value)

    return root


def _parse_scalar(value: str) -> object:
    low = value.lower()
    if low == "true":
        return True
    if low == "false":
        return False

    try:
        if any(ch in value for ch in [".", "e", "E"]):
            return float(value)
        return int(value)
    except ValueError:
        return value
