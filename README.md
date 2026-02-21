# polymarket-mm-bot (MVP)

当前版本支持 `paper/live` 双模式：

- `paper`: 本地模拟成交，不会真实下单。
- `live`: 使用官方 Python SDK (`py-clob-client`) 发真实订单。

## 一键安装与运行（推荐）

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 默认 paper
python bot.py run --once
python bot.py report
```

## Live 最小运行

先改配置：`config.yaml` 里 `mode: live`

再设置凭证：

```bash
export POLYMARKET_PRIVATE_KEY='0x...'
export POLYMARKET_FUNDER='0x...'
python bot.py run --once --confirm-live
```

注意：`live` 会真实下单。现在必须显式加 `--confirm-live` 才会放行。建议先小 `order_size`、`--once`、`FOK`。

## CLI

```bash
python bot.py run --once
python bot.py run --interval 2
python bot.py report
```

## 紧急停止

创建 `kill_switch_file`（默认 `.halt`）即可让运行中的 loop 在下一轮自动停机：

```bash
touch .halt
```

## 记录文件

统一写 `settlement.jsonl`，常见事件：

- `tick`
- `order_open`
- `fill`（paper）
- `position_snapshot`
- `equity_snapshot`
- `halt`
- `live_order_result` / `live_order_error`

## 配置说明（`config.yaml`）

- `mode`: `paper` 或 `live`
- `top_n / min_liquidity / min_spread / order_size / order_edge`
- `min_minutes_to_expiry / max_orders_per_loop / kill_switch_file`
- `risk.max_order_notional / risk.max_market_exposure / risk.daily_loss_limit`
- `live.host / live.chain_id / live.signature_type / live.private_key_env / live.funder_env / live.order_type`

## 文档

- `docs/ARCHITECTURE_AND_DECISIONS.md`
- `docs/HANDOFF.md`
- `REFACTOR_MVP_SPEC.md`
