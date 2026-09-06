# JEXI 架构与配置说明

J.E.X.I.（Joint Executive & eXecution Intelligence）是本仓库的多智能体市场分析增强层。
它**不替换**现有主流程：复用 `data_provider.DataFetcherManager` 取数、复用 ntfy 通知、复用
`src/agent` 已有能力认知，在其上叠加 boss 编排器、领导层判断、50 位 specialist persona、
历史纸面模拟与自改进循环。默认关闭，不配置任何 `JEXI_*` 变量不影响现有分析流程。

> 边界声明：本模块全部交易分析均为**纸面 / 研究用途**（paper trading），不产生任何实盘指令。

## 1. 模块一览

| 模块 | 职责 |
| --- | --- |
| `src/jexi/personas.yaml` | persona 数据真源：领导层（`jexi`/`thorne`/`sterling`）+ 50 位 specialist |
| `src/jexi/persona.py` | `Persona` / `PersonaRegistry` / `LeadershipBundle`，YAML 加载与工具、tilt 校验 |
| `src/jexi/specialist.py` | 确定性因子引擎：动量/趋势/反转/量能/资金/波动/风险，按 persona tilt 加权 |
| `src/jexi/orchestrator.py` | `JexiBossAgent`：规划→分发→共识→执行计划→报告→推送；`RegimeClassifier`（Prof Thorne）、`SterlingExecutionOptimiser` |
| `src/jexi/papersim.py` | 历史纸面模拟器：长/短双向、止损/止盈成对、风险仓位、权益曲线 |
| `src/jexi/metrics.py` | win rate / Sharpe / max drawdown / 总收益四指标 |
| `src/jexi/loop.py` | 自改进循环：随窗口重算共识 → 指标 → 调整 adaptive weights → 重新评估 |
| `src/jexi/notify.py` | ntfy.sh JSON publish 封装（title/priority/tags；未配置时只写日志/stdout） |
| `src/jexi/mcp_client.py` | 可选 MCP 数据集适配（stdin/out,  零依赖）；`JEXI_MCP_ENABLED=1` 启用 |
| `scripts/jexi_cli.py` | CLI：`--status` / `--mode once` / `--mode sim` / `--mode loop` |

## 2. 关键语义

- 50 位 specialist 是 **YAML 数据 persona**，运行在**同一个**确定性运行时上，避免 50 个平行类；
  每个 persona 通过 `tilt`（动量/宏观/价值/情绪/资金/风险/量化/波动）对同一组因子给出差异化结论。
- 共识 = 置信度加权平均分（`JexiBossAgent.build_consensus`），方向阈值 `±0.08`。
- 自适应权重（self-loop）：`op.score *= 1 + 0.25 * adaptive_weight`，权重范围 `[0.2, 3.0]`，
  循环中按窗口胜负偏差每轮调整；这是与仓库既有 `AGENT_SKILL_AUTOWEIGHT` 平行的 Jexi 实现。
- 执行护栏（Vic Sterling + papersim）：单笔止损距离风险 ≤ `JEXI_RISK_PER_TRADE`（默认 2%）、
  单标的仓位 ≤ `JEXI_MAX_POSITION_FRACTION`（默认 25%）、年化波动 ≥45% 对半降仓、
  回撤超 `JEXI_MAX_DRAWDOWN_HALT`（默认 10%）暂停新开仓。

## 3. 配置

所有 `JEXI_*` 键同时注册于 `src/config.py`（`Config` 字段 + getenv 映射）与
`src/core/config_registry.py`（Web 设置页 `agent` 分类）。`.env.example` 含示例与注释。

### 核心开关

```bash
JEXI_ENABLED=true
JEXI_SPECIALISTS=            # 逗号分隔的 specialist id 子集，默认全部 50 位
```

### LLM 研究模式（Research Backend）

`JEXI_RESEARCH_BACKEND`（默认 `off`）控制 specialist 是否接入真实模型：

| 值 | 含义 |
| --- | --- |
| `off` | 确定性因子引擎（无任何 key 也能跑） |
| `opencode_cli` | 内置 opencode CLI（无需 API key），persona brief 为 system prompt、行情快照为 user prompt |
| `litellm` | 复用仓库 `src/llm` 生成后端（需配置 `LITELLM_MODEL`/key） |
| `auto` | `opencode_cli` 可用时用它，否则 `litellm` 若已配置，否则回退 `off` |

```bash
JEXI_RESEARCH_BACKEND=auto
JEXI_RESEARCH_TIMEOUT_SECONDS=120
```

模型必须返回 `{"direction":"long|short|neutral","conviction":0..1,"rationale","risk"}` 的 JSON；
有效时该研究观点按 **35/65** 与因子分数融合（`conviction ≥ 0.5` 才改写方向），无效/超时/无后端
一律回退因子结果。研究调用按 `(bucket, 代码, persona)` 缓存；滚动回测里每场景每标的每 persona
只调用一次，不会逐根 K 线打爆账单。CLI 可用 `--research auto|opencode_cli|litellm|off` 覆盖。

### 市场状态方向门槛（Regime Gate，可选增强）

默认关闭（`JEXI_REGIME_GATE=false`，等量保持旧行为），回测/循环用 `--regime-gate` 开启：
Prof Thorne 按基准 index（默认 SPY）前一 `lookback_days` 根 K 线判定市场状态，然后用结论过滤
consensus 计划——`bear` tape 下禁止持仓共识弱于 0.6 的多头、`bull` tape 下禁止弱空头、
`sideways` 下只保留强信心（confidence ≥ 0.5）持仓。该门槛只影响方向过滤，不影响仓位与止损风控。

### 通知（与既有 ntfy 打通）

优先级：`JEXI_NTFY_URL` > `NTFY_URL` > `JEXI_NTFY_SERVER + JEXI_NTFY_TOPIC`。

```bash
JEXI_NTFY_URL=
JEXI_NTFY_SERVER=https://ntfy.sh
JEXI_NTFY_TOPIC=jexi_reports
JEXI_NTFY_TOKEN=            # 受保护 topic 的 Bearer Token，可选
```

### 自改进循环收敛目标

| 键 | 默认 | 含义 |
| --- | --- | --- |
| `JEXI_MAX_ITERATIONS` | 10 | 循环最大迭代次数 |
| `JEXI_TARGET_WIN_RATE` | 0.55 | 方向胜率下限（长/空独立统计） |
| `JEXI_TARGET_SHARPE` | 1.2 | 年化 Sharpe 下限 |
| `JEXI_TARGET_MAX_DRAWDOWN` | 0.15 | 最大回撤上限 |
| `JEXI_TARGET_MIN_TOTAL_RETURN` | 0.05 | 场景最小总收益 |

场景通过判定 = 四指标同时达标；`--mode loop` 统计通过/总场景数是否收敛。

### 风控

```bash
JEXI_RISK_PER_TRADE=0.02
JEXI_MAX_POSITION_FRACTION=0.25
JEXI_MAX_DRAWDOWN_HALT=0.10
```

## 4. CLI 用法

```bash
# 状态查看（persona 数量、ntfy endpoint、MCP 开关）
.venv/bin/python scripts/jexi_cli.py --status

# 一次分析（支持 A股/港股/美股混合，代码以逗号分隔）
.venv/bin/python scripts/jexi_cli.py --mode once --stocks 600519,hk00700,AAPL

# 单个历史场景纸面模拟（不再推送：--no-push）
.venv/bin/python scripts/jexi_cli.py --mode sim --scenario bull \
  --scenario-tickers "bull=SPY,QQQ"
# --stocks / --days / --specialists 同 once

# 自改进循环（默认单窗口评估；加 --rebalance-days 切换为滚动回测）
.venv/bin/python scripts/jexi_cli.py --mode loop --max-iterations 5 --rebalance-days 20 \
  --scenario-tickers "bull=SPY,QQQ;bear=SPY,TSLA;sideways=SPY;volatile=SPY"

# 2020-2025 五年滚动回测（bull/bear/sideways/volatile 各场景 + 全 5 年汇总）
.venv/bin/python scripts/jexi_cli.py --mode backtest --rebalance-days 20 \
  --lookback-days 120 --no-push

# LLM 研究模式：一次 real-time 分析走真实模型（需要 opencode 或已配置 litellm）
.venv/bin/python scripts/jexi_cli.py --mode once --research auto \
  --stocks AAPL --no-push

# ntfy 连通性测试（默认 topic jexi_reports）
.venv/bin/python scripts/jexi_cli.py --test-push
```

内置场景窗口（2020-2025）：`bull 2020-11~2021-12`、`bear 2022`、
`sideways 2023`、`volatile 2020-02~2020-05`（COVID 崩盘与回升）；`--mode backtest`
另跑全量 `2020-01-01..2025-12-31`。

收敛判定 = 四指标同时达标；`--mode backtest` 打印各场景与 5 年汇总的
胜率 / Sharpe / 最大回撤 / 总收益 / 平仓笔数表格并返回退出码。

## 5. MCP（可选增强）

`finance-data-mcp`、`mcp-market-data` 等免费服务器可选接入，作为额外数据面而非依赖：

```bash
JEXI_MCP_ENABLED=true
JEXI_MCP_SERVERS=[{"name":"finance-data-mcp","command":"npx","args":["-y","finance-data-mcp"],"env":{"SEC_USER_AGENT":"Jexi Research jexi@example.com"}}]
```

适配器支持官方 `mcp` SDK（若已安装）与零依赖 stdio JSON-RPC 两种 transport；任何 MCP
失败只记日志，不影响分析路径。

## 6. 验证

- `pytest -m "not network" tests/test_jexi_pilot.py`：离线覆盖 persona 加载/校验、指标数学、
  specialist 方向性、长/短 papersim、Regime 分类、仓位约束、端到端自改进循环。
- 在线/场景类验证（真实历史窗口、`--mode loop`、ntfy 推送）需联网，交付时单独说明。
- Web 改动（settingsHelp 帮助文案）走 `npm run lint && npm run build`。

## 7. 已知限制

- `papersim.py` 按日线收盘开仓、下一交易日逐根检查止损/止盈；持仓周期按票开/平，冻结单票单仓。
- LLM 研究模式仅在显式开启 `--research` / `JEXI_RESEARCH_BACKEND` 时生效；`opencode_cli`
  已实测无 key 可用，`litellm` 路径依赖外部模型/key 配置（未配置即回退确定性）。
- 场景窗口数据依赖数据源覆盖区间；数据不足的场景会被跳过并记录。
- 2020-2025 实盘收益已由 `papersim` 验证为真实可复现（日线 delta 逐日标记、每再平衡一只
  一份计划、止损/止盈后不重复入场）；当前（未开 regime gate、无 LLM 研究）四场景实测
  **未达全部收敛目标**——bull 主要卡 Sharpe、bear/sideways/volatile 卡胜率，系统整体偏多头。
- Jexi 报告定时推送由 ops 按 `JEXI_REPORT_INTERVAL_HOURS` 接线，pilot 不自动注册到调度器。

## 8. 回滚

- 关闭 `JEXI_ENABLED` 或移除触发入口即可整体停用；`src/jexi/` 与 `scripts/jexi_cli.py`
  可整体删除，无其他模块强依赖。
- `src/config.py`/`config_registry.py`/`.env.example`/Web locale 的 `JEXI_*` 增量为
  独立可逆块，删除后回到未配置状态。