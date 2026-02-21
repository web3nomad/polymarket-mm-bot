# Polymarket Bot 重构需求（MVP 极简版）

> 目标：把当前项目重构成“最小可行版本”，便于快速实盘小额测试。  
> 原则：少模块、少抽象、少依赖、可读可改。

## 1) 产品目标

- 只做 **paper trading / 小额手动确认实盘前置**。
- 单文件记录交易与状态（结算文件）。
- 逻辑足够简单：能跑、能看、能停、能复盘。

## 2) 技术约束

- 语言：**Python 3.11**（先不引入 Rust）
- 依赖尽量少：
  - `requests`
  - `pyyaml`（可选）
- 不用数据库（SQLite 删除）
- 不引入消息队列、服务拆分、复杂框架

## 3) 目录结构（极简）

```text
polymarket-mm-bot/
  bot.py                 # 主程序（唯一入口）
  config.yaml            # 参数
  settlement.jsonl       # 唯一结算/交易记录文件（自动创建）
  README.md
```

## 4) MVP 功能范围

### 4.1 数据
- 从 Polymarket Gamma 公共接口拉市场（轮询）
- 只取必要字段：
  - market_id
  - question
  - best_bid / best_ask
  - liquidity
  - end_time

### 4.2 策略（非常简单）
- 仅对 Top N（按 liquidity）市场运行
- 若 spread >= 阈值，则给出双边报价意图（paper）
- 不做复杂 inventory skew，不做花哨因子

### 4.3 风控（硬规则）
- 单笔最大名义金额
- 单市场最大敞口
- 日亏损熔断（达到就停止开新单）

### 4.4 执行（paper）
- 简化成交模型：
  - buy price >= ask 即成交
  - sell price <= bid 即成交
- 记录成交、持仓、PnL（都写入 settlement.jsonl）

### 4.5 记录（单一结算文件）
- 所有事件写入 `settlement.jsonl`，一行一个 JSON
- 事件类型：
  - `tick`
  - `order_open`
  - `fill`
  - `position_snapshot`
  - `equity_snapshot`
  - `halt`

示例：
```json
{"ts":"2026-02-22T02:00:00Z","type":"fill","market_id":"123","side":"buy","price":0.51,"size":10}
```

## 5) CLI（仅 3 个）

```bash
python bot.py run --once
python bot.py run --interval 2
python bot.py report
```

- `run`: 跑策略循环
- `report`: 从 settlement.jsonl 汇总今日 pnl / 当前持仓

## 6) 非目标（本次不做）

- 不做 Rust 服务
- 不做真实下单
- 不做 WebSocket 本地订单簿
- 不做数据库
- 不做回测引擎
- 不做多策略框架

## 7) 验收标准

1. 无网络时 `run --once` 不崩溃，只打印 warning。
2. 有网络时能拉到市场并至少写入 `tick/equity_snapshot`。
3. 触发模拟成交时写入 `fill`。
4. `report` 能输出：
   - 今日 realized/unrealized pnl
   - 当前持仓
   - 是否触发熔断

## 8) 给 Codex 的执行指令（可直接贴）

请将当前项目重构为上述 MVP：

- 删除多余模块，合并为 `bot.py` 单入口。
- 删除 SQLite 持久化，统一改为 `settlement.jsonl` 事件日志。
- 保留最小配置项（风险阈值、轮询间隔、市场数量、下单大小）。
- 保证 `python bot.py run --once` 与 `python bot.py report` 可运行。
- 不实现真实下单，全部 paper。
- 代码优先可读性，避免过度工程化。
