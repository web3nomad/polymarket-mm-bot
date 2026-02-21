# polymarket-mm-bot (MVP)

按 `REFACTOR_MVP_SPEC.md` 重构后的极简版本：单文件入口、paper trading、单一结算日志。

## 目录

```text
polymarket-mm-bot/
  bot.py
  config.yaml
  settlement.jsonl   # 运行后自动创建
  README.md
```

## 一键安装与运行（推荐）

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bot.py run --once
python bot.py report
```

## 依赖

- Python 3.11
- requests
- pyyaml

手动安装：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install requests pyyaml
# 或
pip install -r requirements.txt
```

## 运行

```bash
python bot.py run --once
python bot.py run --interval 2
python bot.py report
```

也可显式指定配置：

```bash
python bot.py --config config.yaml run --once
python bot.py --config config.yaml report
```

## 功能边界

- 数据：轮询 Gamma 公共接口，提取 `market_id/question/best_bid/best_ask/liquidity/end_time`
- 策略：Top N（按 liquidity）+ spread 阈值触发双边 paper 报价
- 风控：单笔名义、单市场敞口、日亏损熔断
- 执行：仅 paper；`buy>=ask` / `sell<=bid` 即成交
- 记录：统一写 `settlement.jsonl`，事件包括：
  - `tick`
  - `order_open`
  - `fill`
  - `position_snapshot`
  - `equity_snapshot`
  - `halt`

## 验收点

1. 无网络时 `python bot.py run --once` 不崩溃，仅 warning。
2. 有网络时会写入 `tick` 与 `equity_snapshot`。
3. 触发成交时会写入 `fill`。
4. `python bot.py report` 输出今日 realized/unrealized、当前持仓、是否熔断。
