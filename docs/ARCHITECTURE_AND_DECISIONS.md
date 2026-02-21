# Polymarket MVP 重构记录（讨论版）

## 1) 我们打算怎么做

- 保留极简结构：单入口 `bot.py`，单配置 `config.yaml`，单结算文件 `settlement.jsonl`。
- 执行器改为双模式：
  - `paper`：本地模拟成交与 PnL。
  - `live`：使用官方 Python SDK `py-clob-client` 发真实订单。
- 策略保持简单：Top N + spread 阈值触发双边意图。
- 风控保持硬规则：单笔名义、单市场敞口、日亏损熔断。

## 2) 经过了怎样的讨论

- 你提出“先别模拟，能不能直接上 live，小资金即可”。
- 我们确认了关键点：
  - 数据读取可简单；
  - 真下单认证和签名流程不建议手搓；
  - 优先官方 SDK，降低协议和签名细节的维护成本。
- 我们同时确认：文档要完整，包含思路、反馈、实现结果，并给 hand-off。

## 3) 你给了什么反馈

- 你明确表示：
  - 可以自己安装依赖，不需要降级成“无依赖回退”；
  - 安装步骤要写清楚；
  - 当前方向可直接以 live 为目标推进；
  - 文档要沉淀到 `docs/`。

## 4) 当前版本实现了什么

- 实现了 `paper/live` 双模式开关（`config.yaml -> mode`）。
- `paper` 模式：
  - 按 MVP 规则运行，写入 `tick/order_open/fill/position_snapshot/equity_snapshot/halt`。
- `live` 模式：
  - 使用 `py-clob-client` 初始化 `ClobClient`；
  - `create_or_derive_api_creds` + `set_api_creds`；
  - 对每个意图创建并提交订单（默认 `FOK`）；
  - 将结果写入 `live_order_result` 或 `live_order_error` 事件。
- 保持 `report` 命令可用（主要汇总 paper 快照）。

## 5) 版本边界（刻意不做）

- 不做多策略框架。
- 不做数据库。
- 不做复杂订单状态机和成交回补。
- 不做高频并发架构。

## 6) 下一步建议

- 先用 `mode: paper` 连续跑，确认策略参数与日志结构。
- 再切 `mode: live`，用小仓位 + FOK 验证凭证和真实下单链路。
- live 稳定后补：
  - `cancel` 管理、
  - 实时持仓/成交同步、
  - 更严格的熔断与告警。
