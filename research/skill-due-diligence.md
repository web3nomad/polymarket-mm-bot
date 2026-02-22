# Polymarket Agent Skill 调研（扩展版）

生成时间：2026-02-22 (Asia/Shanghai)

## 1) 核心候选（skills.sh）

### A. agentmc15/polymarket-trader（3个skill）
- skills安装量：
  - trading-strategies: 274
  - polymarket-api: 169
  - trader-analysis: 98
- 仓库信号：
  - repo: agentmc15/polymarket-trader
  - stars: 2, forks: 1
  - 最近push: 2025-12-25
  - 最近update: 2026-02-19
  - 开源许可：未声明
- 内容信号：
  - 有真实项目结构（backend/services/strategies/backtesting）
  - skill文本可读，覆盖策略/API/交易员分析
- 风险点：
  - 社区规模小
  - 代码维护连续性一般（最近commit不密集）

结论：**垂直度最高，可作为“第一试用对象”**。

---

### B. 2025Emma/vibe-coding-cn@polymarket
- skills安装量：210
- 仓库信号：
  - stars: 12k+, forks: 1.3k+
  - 最近push: 2025-12-17（偏早）
  - 许可：MIT
- 内容信号：
  - polymarket是大仓中的一个子技能
  - 更偏“文档/知识聚合”而非单一交易执行系统

结论：**适合作为参考文档库，不是首选执行框架**。

---

### C. robonet-tech/skills@trade-prediction-markets
- skills安装量：55
- 仓库信号：
  - stars: 0, forks: 0
  - 最近push: 2026-02-02
  - 许可：未声明
- 结论：**可看，但优先级较低**。

## 2) 社交口碑（X API + 网页）

### X(Twitter) API 检索结果
- 已使用 .env 中 `X_BEARER_TOKEN` 进行检索。
- 宽松关键词能抓到内容，但大多是泛“trading strategy”讨论，噪音高。
- 精确检索（skills.sh具体链接 / 仓库全名）近窗口内几乎0命中。

结论：**目前无法从X得到对这几个skill的高置信“用户口碑”证据**。

## 3) 外围信号（你要求“各种东西都看”）
- Reddit 可找到“AI agents trade on Polymarket”讨论，但多是策略实验贴，和具体skills关联弱。
- Trustpilot 对 Polymarket 主站负面评价很多（资金、提现、客服等），可作为平台风险背景，不直接等于某个skill质量。
- 官方方向参考：`Polymarket/agents`（官方开源框架）存在，适合作为架构与实践对照基线。

## 4) 最终建议（实操向）
1. 先试用：`agentmc15/polymarket-trader@polymarket-api + trading-strategies`
2. 文档辅助：`2025Emma/vibe-coding-cn@polymarket`
3. 低优先：robonet-tech 相关技能

## 5) 安装命令
```bash
npx skills add agentmc15/polymarket-trader@polymarket-api -g -y
npx skills add agentmc15/polymarket-trader@trading-strategies -g -y
npx skills add agentmc15/polymarket-trader@trader-analysis -g -y
```

## 6) 下一步（可选）
- 做一轮“可运行性验收”：
  - 是否可直接接你当前bot
  - 依赖冲突/凭证兼容
  - 最小下单链路是否成功
- 输出一份 A/B 对照结果（可直接落地到你的仓库配置）。
