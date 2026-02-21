# polymarket-mm-bot

Polymarket 做市机器人 v1（`paper trading` 版本）。

默认只做本地仿真，不会发真实订单；无需私钥即可直接跑起来。

## 功能概览

- Gamma 公共 API 轮询（`/events` + `/markets`）
- Top-N 市场筛选（流动性 / 价差 / 到期时间）
- 简单做市策略（围绕 mid 双边报价 + inventory skew）
- 纸面执行引擎（内存订单/持仓/盈亏，含滑点参数）
- 风控：单笔风险、市场暴露、主题暴露占位、日内回撤停机、最大挂单数
- SQLite 持久化：`runs / orders / fills / positions / equity_curve`
- CLI：`run` / `backtest-lite` / `report`

## 安装

```bash
cd polymarket-mm-bot
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 配置

- 默认配置：`config/default.yaml`
- 纸面预设：`config/paper.yaml`

关键分区：

- `market_selection`
- `execution`
- `telemetry`
- 以及 `risk` / `strategy` / `runtime`

## 运行

单次循环（推荐先跑这个）：

```bash
python -m polymarket_mm_bot run --once --config config/paper.yaml
```

连续运行（2 秒轮询）：

```bash
python -m polymarket_mm_bot run --config config/paper.yaml --interval 2
```

网络不可用时会打印 warning 并安全跳过，不会崩溃。

## 回放回测（lite）

支持 JSON 或 JSONL 快照文件。

```bash
python -m polymarket_mm_bot backtest-lite \
  --config config/paper.yaml \
  --snapshots ./sample_snapshots.jsonl
```

每行 JSON 示例（JSONL）：

```json
{"ts":"2026-02-22T00:00:00Z","markets":[{"market_id":"123","question":"Will X happen?","theme":"politics","liquidity":5000,"best_bid":0.48,"best_ask":0.52,"minutes_to_expiry":180}]}
```

## 报告

```bash
python -m polymarket_mm_bot report --config config/paper.yaml
```

输出示例：今日 PnL、最新 equity/cash、以及最新持仓暴露。

## 风险声明（务必阅读）

- 本项目仅用于研究与教学，不构成任何投资建议。
- `paper trading` 的成交与滑点模型非常简化，和真实市场存在显著偏差。
- 即使后续接入真实下单，也必须补充更完整的风控、异常处理、监控与审计。
- 任何实盘行为均由使用者自行承担风险与责任。

## 凭证说明

当前版本不需要任何私钥/API 凭证即可运行。未来若接入实盘执行，请使用 `.env` 并确保密钥不入库。
