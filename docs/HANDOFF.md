# Hand-off

## 当前状态

已完成从单纯 paper MVP 到 `paper/live` 双模式的最小可运行版本。

## 关键文件

- `bot.py`: 主程序（唯一入口）
- `config.yaml`: 运行配置（包含 `mode` 与 `live` 配置）
- `requirements.txt`: 依赖（含 `py-clob-client`）
- `docs/ARCHITECTURE_AND_DECISIONS.md`: 讨论与决策记录

## 运行方式

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# paper
python bot.py run --once
python bot.py report

# live（先配置环境变量）
export POLYMARKET_PRIVATE_KEY='0x...'
export POLYMARKET_FUNDER='0x...'
python bot.py run --once
```

## 已实现能力

- Gamma 市场轮询 + TopN 筛选
- spread 触发的双边意图
- 风控硬规则（单笔/单市场/日亏损）
- paper 模拟成交与 PnL
- live 真实下单最小链路（SDK）
- settlement 事件日志

## 风险与注意事项

- `mode: live` 会真实下单，请先确认钱包权限、余额和 allowance。
- 当前 `report` 以 paper 快照为主；live 场景下不代表完整账户状态。
- `token_id` 解析依赖 Gamma 返回字段，不同市场结构可能需要补充映射逻辑。

## 建议接手顺序

1. 先用 `paper` 连跑并查看 `settlement.jsonl`。
2. live 下只保留极小 `order_size`，先跑 `--once`。
3. 核验订单结果后，再考虑连续运行和扩市场。
