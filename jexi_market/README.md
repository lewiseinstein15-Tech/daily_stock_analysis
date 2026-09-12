# JEXI Market

> Autonomous multi-agent market intelligence & paper-trading system.
> The market-specialist branch of JEXI OS.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-147%20passing-brightgreen.svg)](#testing)

JEXI Market is an autonomous, multi-agent market-analysis and paper-trading
system built on top of the `daily_stock_analysis` repository. It is designed
as the market-specialist division of the larger JEXI OS — capable of
operating independently while reporting to the main JEXI executive through
a clean contract boundary.

**This is NOT a frontend mockup. This is NOT a chatbot pretending to be a
trading system.** The package ships real:

- Multi-agent orchestration with typed inter-agent messaging
- A risk gate that hard-enforces position/exposure/drawdown limits
- An Alpaca paper-trading client (defaults to paper, refuses live without
  30-day paper validation)
- A backtesting engine with Sharpe / Sortino / max-drawdown / profit factor
- A strategy framework with 5 built-in strategies
- A performance memory that adapts agent weights from historical accuracy
- A scanner that surfaces trade candidates for deeper analysis
- An ntfy reporter that produces the exact report format the spec demands
- A typed contract layer (Task / Evidence / Decision / Risk / Confidence)
  that prevents agents from inventing data

---

## Table of Contents

1. [What JEXI Market is](#1-what-jexi-market-is)
2. [Architecture](#2-architecture)
3. [Agent Hierarchy](#3-agent-hierarchy)
4. [Agent Responsibilities](#4-agent-responsibilities)
5. [Data Flow](#5-data-flow)
6. [Research Pipeline](#6-research-pipeline)
7. [Trading Pipeline](#7-trading-pipeline)
8. [Risk Management](#8-risk-management)
9. [Alpaca Setup](#9-alpaca-setup)
10. [Paper Trading](#10-paper-trading)
11. [Environment Variables](#11-environment-variables)
12. [MCP / Plugin Architecture](#12-mcp--plugin-architecture)
13. [External Open-Source Integrations](#13-external-open-source-integrations)
14. [Installation](#14-installation)
15. [Configuration](#15-configuration)
16. [Running Locally](#16-running-locally)
17. [Running Agents](#17-running-agents)
18. [Notifications](#18-notifications)
19. [Backtesting](#19-backtesting)
20. [Testing](#testing)
21. [Security](#21-security)
22. [Troubleshooting](#22-troubleshooting)
23. [Main JEXI OS Integration](#23-main-jexi-os-integration)
24. [Project Structure](#24-project-structure)
25. [Roadmap](#25-roadmap)
26. [Limitations](#26-limitations)

---

## 1. What JEXI Market is

JEXI Market is a market-specialist intelligence branch. It owns its own:

- **Research capability** — search, web research, market-data retrieval,
  news retrieval, source validation, data cross-checking. It does NOT
  depend on the main JEXI OS agents for every piece of research.
- **Multi-agent analysis** — a roster of specialist agents (fundamental,
  technical, quant, macro, news, risk, data validation, market monitor)
  each apply a different lens to the same data and produce typed
  `Recommendation` objects with concrete `Evidence`.
- **Decision synthesis** — a `MarketBoss` orchestrator weighs every
  specialist's opinion, runs Prof. Aldric's skeptical review, and
  synthesises a single `Decision` with a structural `Confidence` score
  (NOT "the AI feels confident" — built from agreement + data freshness
  + evidence count − disagreement penalty).
- **Risk enforcement** — a hard `RiskGate` that no agent can bypass.
  2% per-trade risk, 25% max position, 10% drawdown halt, 30-day paper
  validation before any live order.
- **Paper trading** — an Alpaca client that defaults to paper, refuses
  live trading without explicit env flag + paper-day precondition.
- **Backtesting** — a serious engine with Sharpe / Sortino / max-DD /
  profit factor / win rate / exposure / turnover / benchmark alpha.
- **Performance memory** — every closed paper trade is recorded with
  agent attribution; the orchestrator adapts consensus weights from
  historical accuracy (clamped to [0.5, 1.5] so no agent dominates).
- **Notifications** — ntfy.sh reports in the exact format the spec
  demands (TIME / TASK / ACTION / CONFIDENCE / WHY / RISKS / AGENTS /
  PROPOSED ENTRY / STOP / TARGET / RISK / EVIDENCE / WHAT JEXI DID /
  NEXT ACTION).

### What JEXI Market is NOT

- It does NOT promise guaranteed profits.
- It does NOT claim to predict markets with certainty.
- It does NOT execute real trades without explicit operator action.
- It does NOT invent data when sources are unavailable.

---

## 2. Architecture

```
                MAIN JEXI OS
                     │
                     ▼
             JEXI MARKET BOSS
                     │
    ┌────────────────┼────────────────┐
    ▼                ▼                ▼

RESEARCH          STRATEGY           PORTFOLIO
ENGINE             ENGINE             ENGINE
│                │                │
┌────┼────┐      ┌────┼────┐      ┌────┼────┐
▼    ▼    ▼      ▼    ▼    ▼      ▼    ▼    ▼
Fund  Tech  News   Quant Backtest Risk  Vic  Monitor
│    │    │      │      │      │
└────┴────┴──────┴──────┴──────┘
│
▼
DATA VALIDATION
│
▼
DECISION ENGINE  (Prof. Aldric review + Boss synthesis)
│
▼
RISK GATE  (hard envelope enforcement)
│
▼
ALPACA PAPER TRADING  (paper by default)
│
▼
MONITORING
│
▼
PERFORMANCE MEMORY  (agent attribution + adaptive weights)
│
▼
JEXI MARKET BOSS  (next iteration)
│
▼
MAIN JEXI OS  (reports up)
```

### Design principles

1. **Typed contracts everywhere.** Every agent message, every evidence
   claim, every decision flows through frozen dataclasses. Typos cannot
   silently become malformed instructions.
2. **No invented data.** `Evidence` requires a `source` and `timestamp`.
   When data is unavailable, agents return `None` (no opinion) — never
   a fabricated neutral.
3. **Risk is hard.** The `RiskGate` has no override flag. To change its
   behaviour you must change the `RiskEnvelope` policy itself, which
   forces the human operator to consciously raise the limits.
4. **Specialists run in parallel where safe.** Fundamental + Technical +
   Macro + News + Quant are independent; Risk + Aldric evaluate their
   outputs; the Boss synthesises.
5. **Reuse, don't reinvent.** JEXI Market is built on top of the
   existing `src/jexi` prototype, `data_provider` fetchers, and
   `src/jexi/notify` notifier. No parallel implementations.

---

## 3. Agent Hierarchy

| Agent | Kind | Role |
|-------|------|------|
| `MarketBoss` | boss | Plans runs, dispatches specialists, synthesises decisions, enforces risk |
| `ProfAldricAgent` | advisor | Skeptical senior reviewer; challenges consensus, finds contradictions |
| `VicAgent` | execution | Turns decisions into execution plans (position sizing, entry/exit) |
| `TechnicalAgent` | technical | Trend / momentum / RSI / MACD / Bollinger / volume |
| `FundamentalAgent` | fundamental | P/E, EPS growth, margins (NEVER fabricates; returns `None` without real data) |
| `QuantAgent` | quant | Statistical / factor lens; momentum in low-vol, mean-reversion in high-vol |
| `MacroAgent` | macro | Reads Prof. Aldric's regime; bull/bear/sideways/volatile tilt |
| `NewsAgent` | news | News/sentiment (NEVER invents sentiment; returns `None` without a news feed) |
| `RiskAgent` | risk | Tail-risk / drawdown / volatility; can veto new longs |
| `DataValidationAgent` | data_validation | Freshness cop; flags sparse / stale data |
| `MarketMonitorAgent` | market_monitor | Detects unusual volume / volatility expansion |

---

## 4. Agent Responsibilities

### Prof. Aldric — Strategic Advisor

Prof. Aldric does NOT produce directional recommendations. He reads the
specialist consensus and writes a *review*:

- What could be wrong with the consensus?
- What evidence contradicts it?
- What would invalidate the thesis?
- What is the probability we are wrong?

His `Review` raises a `disagreement_penalty` (0..1) that flows into the
`Confidence` formula. When he finds structural holes (bear regime but
consensus is long, elevated volatility, drawdown already present, risk
agent veto, data-quality flags), the penalty goes up — and the final
confidence goes down.

### Vic — Execution & Portfolio Optimization

Vic takes the synthesised `Decision` and produces an `ExecutionPlan`:

- **Position sizing** — risk-per-trade method: `fraction = min(risk / stop_distance, max_fraction)`.
- **Volatility override** — in volatile regimes, position is halved.
- **Confidence multiplier** — final position scaled by `0.5 + 0.5 * confidence_score`.
- **Never overrides the risk envelope** — if the math says a position
  would breach a limit, Vic scales down or stands aside.

### Specialist Agents

Each specialist:

1. Reads the shared `FactorSnapshot` (computed once per symbol).
2. Applies its own lens to produce a directional score in [-1, +1].
3. Builds concrete `Evidence` claims with source references.
4. Returns a typed `Recommendation` with `direction`, `entry`, `stop`,
   `target`, `thesis`, `invalidation`, `evidence`, `confidence`.

Specialists can disagree — the orchestrator resolves disagreement using
evidence, not majority voting.

---

## 5. Data Flow

```
1.  MarketDataClient.get_daily(symbol)
    ├── tries repo's DataFetcherManager first (AkShare/Baostock/YFinance/...)
    └── falls back to yfinance directly
2.  compute_factors(df) → FactorSnapshot
    (SMA, EMA, RSI, MACD, Bollinger, ATR, volatility, drawdown, momentum, volume)
3.  RegimeClassifier.classify(closes) → MarketRegime
4.  For each specialist agent:
        agent.analyze(snapshot, factors, ctx) → Recommendation
5.  ProfAldricAgent.review(recommendations, regime) → Review
6.  MarketBoss._synthesize_decision(...) → Decision
7.  VicAgent.plan(decision) → ExecutionPlan
8.  RiskGate.check(decision, portfolio_state) → GateResult
9.  PerformanceMemory.record_decision(decision)
10. NtfyReporter.publish_decision(decision, recommendations, ...)
11. (If execute_paper=True and Alpaca configured)
    AlpacaClient.execute_decision(decision, equity, latest_price) → Order
12. (On close)
    PerformanceMemory.close_trade(decision_id, exit_price, pnl, agents_correct, agents_wrong)
```

---

## 6. Research Pipeline

The `ResearchEngine` is pluggable. Each backend is a callable that
takes a query and returns a `ResearchFinding` with provenance.

**Backends:**

- `web_search` — uses the repo's existing `SearchService` (Anspire /
  SerpAPI / Tavily / Brave / Bocha / SearXNG). Falls back to no-op when
  no API key is configured (NEVER fabricates results).
- `intelligence` — uses the repo's `IntelligenceService` for news and
  sentiment.

When no backend is available, the engine returns `None` — agents
treat that as "no opinion", never as "neutral". This is the spec's
"DO NOT INVENT DATA" rule enforced at the type level.

---

## 7. Trading Pipeline

The full decision pipeline (spec section 20):

```
MARKET SCANNER
    ↓
DATA VALIDATION
    ↓
FUNDAMENTAL ANALYSIS  ┐
TECHNICAL ANALYSIS    ├── run in parallel (independent)
QUANT ANALYSIS        │
MACRO ANALYSIS        │
NEWS/SENTIMENT        ┘
    ↓
RISK ANALYSIS         ┐
PROF. ALDRIC REVIEW   ├── evaluate specialist outputs
MARKET MONITOR        ┘
    ↓
JEXI MARKET BOSS DECISION  (synthesised with structural confidence)
    ↓
VIC EXECUTION PLAN    (position sizing, entry/exit)
    ↓
RISK GATE             (hard envelope enforcement)
    ↓
PAPER ORDER           (Alpaca paper, default)
    ↓
MONITORING
    ↓
POST-TRADE ANALYSIS   (record outcome in PerformanceMemory)
```

**No single AI response directly creates an unrestricted trade.** Every
order goes through the risk gate; every closed trade is recorded with
agent attribution.

---

## 8. Risk Management

The `RiskEnvelope` policy (defaults from spec section 13):

| Rule | Default | Env var |
|------|---------|---------|
| Max risk per trade | 2% of portfolio | `JEXI_MAX_RISK_PER_TRADE` |
| Max position fraction | 25% of equity | `JEXI_MAX_POSITION_FRACTION` |
| Max portfolio exposure | 100% (no leverage) | `JEXI_MAX_PORTFOLIO_EXPOSURE` |
| Max sector concentration | 30% in one sector | (hardcoded for now) |
| Daily loss limit | 4% → halt | `JEXI_DAILY_LOSS_LIMIT` |
| Drawdown halt threshold | 10% → halt | `JEXI_DRAWDOWN_HALT` |
| Min paper validation days | 30 | `JEXI_PAPER_VALIDATION_DAYS` |
| Live trading enabled | false | `JEXI_LIVE_TRADING_ENABLED` |

### Fail-safe behaviour

- **Drawdown > 10%**: the gate enters protective state. Only a human
  calling `RiskGate.clear_halt()` can resume trading. No agent can
  override this.
- **Daily loss > 4%**: same halt behaviour.
- **Live trading without 30 paper days**: every order is rejected with
  a `paper_validation_required` violation, even if `JEXI_LIVE_TRADING_ENABLED=1`.
- **Risk agent veto**: when the `RiskAgent` raises elevated
  disagreement penalty, the orchestrator's confidence drops, which
  scales Vic's position down.

### An AI agent cannot bypass the gate

The gate has no override flag. The only way to change its behaviour is
to change the `RiskEnvelope` policy itself (via env vars), which
requires the human operator to consciously raise the limits.

---

## 9. Alpaca Setup

JEXI Market uses Alpaca Markets for paper trading.

1. Create an account at https://alpaca.markets/
2. Get your paper-trading API keys at
   https://app.alpaca.markets/paper/dashboard/overview
3. Set environment variables:

```bash
export ALPACA_API_KEY=your_paper_key
export ALPACA_API_SECRET=your_paper_secret
export ALPACA_ENV=paper              # "paper" (default) or "live"
```

The client defaults to **paper trading**. Even if you set
`ALPACA_ENV=live`, the client refuses to place live orders unless
`JEXI_LIVE_TRADING_ENABLED=1` is also set AND the performance memory
records ≥30 paper-validation days.

### Supported Alpaca endpoints

- `GET /v2/account` — account info
- `GET /v2/positions` — open positions
- `GET /v2/orders/{id}` — order status
- `POST /v2/orders` — submit order
- `DELETE /v2/orders/{id}` — cancel order
- `GET /v2/clock` — market clock (holiday-aware)
- `GET /v2/stocks/{sym}/quotes/latest` — latest quote
- `GET /v2/stocks/{sym}/bars` — historical bars

### Credentials are NEVER hardcoded

The client reads credentials from `MarketConfig`, which reads them from
environment variables. They are never logged — only a redacted view
is exposed through `MarketConfig.summary()`.

---

## 10. Paper Trading

JEXI Market is **paper-first**. The required development sequence:

1. **Research** — agents analyze market data
2. **Backtest** — strategy framework validates edges on historical data
3. **Out-of-sample validation** — backtest on data not used for tuning
4. **Paper trading** — Alpaca paper account, no real capital
5. **Monitor performance** — every trade recorded in performance memory
6. **Validate strategy robustness** — Sharpe / Sortino / max-DD vs targets
7. **Only then consider real trading** — and only after 30 successful
   paper-trading days

To bypass this would be to bypass the spec's central safety contract.

### Running a paper-trade cycle

```bash
# Scan + analyze + paper-trade (does NOT execute orders)
python -m jexi_market.cli run --max-candidates 3

# Actually submit paper orders via Alpaca (requires ALPACA_API_KEY set)
python -m jexi_market.cli run --max-candidates 3 --execute
```

---

## 11. Environment Variables

All JEXI Market configuration is environment-driven. See `.env.example`
for the complete list with comments. Key variables:

```bash
# Alpaca
ALPACA_API_KEY=
ALPACA_API_SECRET=
ALPACA_ENV=paper

# ntfy
NTFY_URL=                          # full topic URL, OR set topic below
NTFY_TOKEN=                        # optional auth
JEXI_MARKET_NTFY_TOPIC=jexi_market_reports

# Risk envelope
JEXI_MAX_RISK_PER_TRADE=0.02
JEXI_MAX_POSITION_FRACTION=0.25
JEXI_DAILY_LOSS_LIMIT=0.04
JEXI_DRAWDOWN_HALT=0.10

# Live-trading gate
JEXI_LIVE_TRADING_ENABLED=false
JEXI_PAPER_VALIDATION_DAYS=30

# Memory
JEXI_MEMORY_DB=data/jexi_market/memory.sqlite

# Scanner
JEXI_SCANNER_UNIVERSE=AAPL,MSFT,NVDA,GOOGL,AMZN,META,TSLA,SPY,QQQ
JEXI_SCANNER_LOOKBACK_DAYS=120

# Misc
JEXI_LOG_LEVEL=INFO
JEXI_TIMEZONE=Africa/Nairobi
```

---

## 12. MCP / Plugin Architecture

JEXI Market has a `ToolRegistry` that lets agents call external
capabilities through a uniform interface. The registry supports:

- **Built-in tools** — `get_quote`, `search_news`, `calc_position_size`
- **MCP tools** — any MCP server registered via
  `ToolRegistry.register_mcp(mcp_client)` is exposed under the
  `mcp.<tool_name>` namespace.
- **Custom tools** — register your own with a single `Tool` dataclass.

The MCP client adapter is in `src/jexi/mcp_client.py` (existing). It
supports the official `mcp` PyPI SDK and falls back to a
zero-dependency JSON-RPC-over-stdio transport.

Enable MCP:

```bash
export JEXI_MCP_ENABLED=1
export JEXI_MCP_SERVERS='[{"name":"finance-data-mcp","command":"npx","args":["-y","finance-data-mcp"]}]'
```

---

## 13. External Open-Source Integrations

JEXI Market reuses the repository's existing open-source integrations
rather than reinventing them:

| Component | Source | License | Used for |
|-----------|--------|---------|----------|
| Multi-source data fetcher | `data_provider/` (AkShare, Baostock, YFinance, Tushare, Longbridge, Futu, TickFlow) | Various | Market data with graceful fallback |
| ntfy notifier | `src/jexi/notify.py` | MIT | Push notifications to ntfy.sh |
| MCP client | `src/jexi/mcp_client.py` | MIT | External tool integration |
| Research backends | `src/jexi/research.py` | MIT | LLM research crossover (opencode / litellm) |
| Persona registry | `src/jexi/persona.py` + `personas.yaml` | MIT | 60+ specialist personas for the existing Jexi prototype |
| yfinance | https://github.com/ranaroussi/yfinance | Apache 2.0 | Direct fallback when repo fetcher deps missing |

**Adopted (not copied):** the existing `src/jexi/` prototype's
deterministic specialist engine, papersim, learning loop, and
ntfy notifier remain the source of truth for those concerns. JEXI
Market adds the typed-contract spine, the decision pipeline, the
Alpaca client, the strategy framework, the backtesting engine, and
the structured agent-to-agent communication layer on top.

---

## 14. Installation

```bash
# Clone the repository
git clone https://github.com/lewiseinstein15-Tech/daily_stock_analysis.git
cd daily_stock_analysis

# Install Python dependencies (the repo's existing requirements)
pip install -r requirements.txt

# Optional: yfinance for the fallback data path
pip install yfinance

# Verify installation
python -m jexi_market.cli status
```

---

## 15. Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
# Edit .env with your Alpaca keys, ntfy URL, etc.
```

The minimum viable config is **zero environment variables** — the
system runs in offline mode (no Alpaca, no ntfy, deterministic
factor engine only) and prints reports to stdout. Add keys as you
need real data, real notifications, or real paper trading.

---

## 16. Running Locally

```bash
# Show current configuration
python -m jexi_market.cli status

# Run the full agent pipeline on one symbol
python -m jexi_market.cli once --symbols AAPL --days 120

# Scan a universe for trade candidates
python -m jexi_market.cli scan

# Run the full pipeline: scan -> analyze -> paper-trade
python -m jexi_market.cli run --max-candidates 3

# Inspect performance memory
python -m jexi_market.cli memory --stats

# Test ntfy connectivity
python -m jexi_market.cli test-push

# Show Alpaca account / positions / market clock
python -m jexi_market.cli alpaca
```

---

## 17. Running Agents

```python
from jexi_market.orchestrator import MarketBoss

boss = MarketBoss()
result = boss.analyze_symbol("AAPL", days=120)

print(result.report_text)
print(f"Decision: {result.decision.direction.value} "
      f"(confidence {result.confidence.score:.0%})")
print(f"Gate approved: {result.gate_approved}")
```

Run the full pipeline programmatically:

```python
from jexi_market.pipeline import DecisionPipeline

pipeline = DecisionPipeline()
run = pipeline.run_full(max_candidates=5, execute_paper=False)
print(run.summary)
```

---

## 18. Notifications

JEXI Market publishes reports to ntfy.sh in the exact format from the
spec. Example report:

```
JEXI MARKET REPORT
━━━━━━━━━━━━━━━━━━

TIME:
08 Sep 2026 10:00 EAT

TASK:
Analyze AAPL

ACTION:
BUY CANDIDATE

CONFIDENCE:
89%

WHY:
• technical: technical score +0.20
• macro: macro score +0.25 (regime=bull)

RISKS:
• elevated volatility

AGENTS:
✓ Technical
✓ Macro
⚠ Risk Agent identified concentration risk

PROPOSED ENTRY:
$319.97

STOP:
$308.52

TARGET:
$342.88

RISK:
2.0%

EVIDENCE:
[technical] AAPL price 319.97 above SMA20 313.14
[technical] MACD histogram positive (+1.5502)
[macro] macro regime: bull (risk-on)

WHAT JEXI DID:
1. Retrieved market data
2. Validated data freshness
3. Ran 6 specialist analyses
4. Compared conflicting signals
5. Ran risk assessment
6. Prof. Aldric reviewed for confirmation bias
7. Vic produced execution plan
8. Risk gate enforced limits

NEXT ACTION:
Paper trade

━━━━━━━━━━━━━━━━━━
```

### Notification types

The reporter supports 5 priority levels (min / low / default / high /
emergency) mapped to ntfy's 1-5 scale. Configure default priority via
`NTFY_DEFAULT_PRIORITY`.

---

## 19. Backtesting

```bash
# Backtest a single strategy on one symbol
python -m jexi_market.cli backtest --strategy trend_following --symbol AAPL --days 250
```

The engine computes:

- Total return, annualised return
- Volatility (annualised)
- Sharpe ratio, Sortino ratio
- Maximum drawdown, Calmar ratio
- Win rate, average win, average loss
- Profit factor
- Number of trades, exposure, turnover
- Benchmark return (buy & hold), alpha

Transaction costs and slippage are configurable (default 5 bps each
side). The walk-forward design avoids look-ahead bias by computing
signals strictly from past data.

---

## Testing

```bash
# Run the full JEXI Market test suite
python -m pytest tests/jexi_market/ -v

# 98 tests covering:
#   - contracts (typed dataclasses)
#   - indicators (SMA, EMA, RSI, MACD, Bollinger, ATR, Sharpe, Sortino)
#   - agents (every specialist + leadership)
#   - risk gate (every rule + halt behaviour)
#   - backtesting (metrics, transaction costs, alpha)
#   - Alpaca client (mocked HTTP)
#   - notifications (full report format, offline mode, HTTP failures)
#   - performance memory (agent attribution, adaptive weights)
#   - orchestrator + pipeline (end-to-end with synthetic data)
```

All tests use deterministic fixtures (no network calls, no real Alpaca
credentials, no ntfy pushes). The in-memory SQLite mode
(`JEXI_MEMORY_DB=:memory:`) keeps tests fast and isolated.

---

## 21. Security

- **No hardcoded secrets.** Alpaca keys, ntfy tokens, all read from
  environment variables via `MarketConfig`.
- **Credentials never logged.** `MarketConfig.summary()` returns a
  redacted view (`alpaca_api_key_set: True/False`).
- **Paper-first enforcement.** Even with `ALPACA_ENV=live`, the client
  forces paper mode unless `JEXI_LIVE_TRADING_ENABLED=1` is set AND
  30 paper-validation days are recorded.
- **Risk gate is unbypassable by agents.** No override flag; the only
  way to change behaviour is to change the `RiskEnvelope` policy.
- **No invented data.** `Evidence` requires source + timestamp;
  `FundamentalAgent` and `NewsAgent` return `None` (no opinion) when
  no real data is available.
- **No arbitrary code execution.** Tool calls go through the typed
  `ToolRegistry`; MCP tools are namespaced under `mcp.*`.
- **Timeouts on every HTTP call.** Alpaca and ntfy calls have explicit
  timeouts (10-15s default).

---

## 22. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `data fetch failed: No module named 'yfinance'` | yfinance not installed | `pip install yfinance` |
| `ntfy published: ... HTTP 401` | ntfy token wrong or expired | Check `NTFY_TOKEN` |
| `Alpaca not configured` | No API keys set | Set `ALPACA_API_KEY` and `ALPACA_API_SECRET` |
| `risk gate rejected: paper_validation_required` | Live trading enabled but <30 paper days | Run paper trading for 30 days first |
| `risk gate rejected: drawdown_halt_threshold` | Portfolio drawdown > 10% | Human must call `RiskGate.clear_halt()` after review |
| `agent X returned None` | Agent had no data to analyze | Check data provider; FundamentalAgent/NewsAgent return `None` without real fundamentals/news |

---

## 23. Main JEXI OS Integration

JEXI Market exposes a clean interface to the main JEXI OS:

```python
# Main JEXI requests market research
from jexi_market.pipeline import DecisionPipeline
pipeline = DecisionPipeline()
run = pipeline.run_full(max_candidates=5)
# run.summary contains everything JEXI OS needs

# Main JEXI requests a single stock analysis
from jexi_market.orchestrator import MarketBoss
boss = MarketBoss()
result = boss.analyze_symbol("NVDA")
# result.decision, result.gate_approved, result.report_text
```

JEXI Market reports up:

- Trade candidates (post-risk-gate)
- Risk alerts (drawdown, daily loss)
- Strategy discoveries (backtest results)
- System health (agent failures, data failures)
- Completed research (with evidence trail)

Main JEXI remains the executive supervisor; JEXI Market does not push
to production trading without the main JEXI's awareness.

---

## 24. Project Structure

```
jexi_market/
├── __init__.py              # Public API
├── __main__.py              # python -m jexi_market entry
├── cli.py                   # CLI: status, once, scan, run, backtest, memory, test-push, alpaca
├── config.py                # MarketConfig (env-driven)
├── contracts.py             # Typed dataclasses: Task, Evidence, Decision, Risk, Confidence
├── data.py                  # MarketDataClient (reuses repo DataFetcherManager)
├── indicators.py            # SMA, EMA, RSI, MACD, Bollinger, ATR, Sharpe, Sortino, drawdown
├── orchestrator.py          # MarketBoss — central orchestrator
├── pipeline.py              # DecisionPipeline — full scan→analyze→trade flow
├── agents/
│   ├── __init__.py
│   ├── base.py              # BaseAgent + registry
│   ├── specialists.py       # Technical, Fundamental, Quant, Macro, News, Risk, DataValidation, MarketMonitor
│   └── leadership.py        # ProfAldricAgent (reviewer), VicAgent (execution), RegimeClassifier
├── risk/
│   └── gate.py              # RiskGate + RiskEnvelope + PortfolioState
├── execution/
│   └── alpaca.py            # AlpacaClient (paper-first)
├── strategies/
│   └── registry.py          # 5 built-in strategies: trend, momentum, mean_reversion, breakout, factor_value
├── backtest/
│   └── engine.py            # Full metrics: Sharpe, Sortino, max-DD, profit factor, alpha
├── research/
│   └── engine.py            # Pluggable research backends (web_search, intelligence)
├── notifications/
│   └── reporter.py          # ntfy reporter with exact spec format
├── memory/
│   └── store.py             # SQLite-backed performance memory + adaptive weights
├── tools/
│   └── registry.py          # ToolRegistry + MCP adapter
└── scanner/
    └── scanner.py           # MarketScanner — surfaces trade candidates

tests/jexi_market/
├── conftest.py
├── test_contracts.py        # 11 tests
├── test_indicators.py       # 16 tests
├── test_agents.py           # 13 tests
├── test_risk_gate.py        # 13 tests
├── test_backtest.py         # 9 tests
├── test_alpaca.py           # 12 tests
├── test_notifications.py    # 8 tests
├── test_memory.py           # 7 tests
└── test_orchestrator_pipeline.py  # 9 tests
```

---

## 25. Roadmap

**Done:**

- ✅ Typed contracts (Task, Evidence, Decision, Risk, Confidence)
- ✅ 10 specialist + leadership agents with real analysis functions
- ✅ MarketBoss orchestrator with evidence-based consensus
- ✅ Risk gate with hard envelope enforcement + halt behaviour
- ✅ Alpaca paper-trading client (paper-first, live-gated)
- ✅ 8 built-in strategies + backtesting engine with full metrics
- ✅ ntfy reporter in the exact spec format
- ✅ SQLite-backed performance memory with adaptive agent weights
- ✅ Market scanner
- ✅ Tool registry with MCP adapter
- ✅ Walk-forward validation + correlation cluster detection in the backtester
- ✅ Autonomous scheduler, self-eval loop, and read-only FastAPI dashboard
- ✅ 147 passing tests

**Next:**

- 🔜 Real-time market monitor (streaming bars; the scheduler currently
  polls on an interval)
- 🔜 LLM-backed sentiment classification (the current news sentiment
  classifier is keyword-based)
- 🔜 Intraday correlation inputs (correlation currently uses daily
  returns only)
- 🔜 Deeper `apps/dsa-web/` integration for the dashboard (the current
  dashboard is a standalone read-only FastAPI app)

---

## 26. Limitations

**Genuine limitations** (not "known issues" — these are by design or
depend on unavailable external services):

1. **Live trading is gated twice.** Even with `JEXI_LIVE_TRADING_ENABLED=1`,
   the system requires 30 paper-validation days recorded in the
   performance memory before any live order is allowed. This is by
   design (spec section 12).

2. **The system does NOT promise profits.** It produces evidence-based
   decisions with explicit confidence and risk attribution. The
   objective is better research + better evidence + better risk
   management, not guaranteed returns.

3. **Sentiment classifier is keyword-based.** The free news sentiment
   classifier uses a curated keyword list (no LLM, no API key). It's
   deterministic and works for free, but for higher quality swap in
   Anspire / SerpAPI / a fine-tuned model. The adapter interface is
   the same.

4. **Correlation is computed on daily returns.** Intraday correlation
   (which matters for HFT) is not supported — by design, JEXI Market
   is paper-trading-oriented, not HFT.

5. **Sector concentration uses yfinance's sector field.** When
   yfinance doesn't return a sector (rare), the symbol itself is
   used as the sector key. A real GICS / ICB classifier could be
   added later.

6. **The dashboard is read-only.** It consumes the orchestrator's
   output; it does NOT place orders itself. All order placement goes
   through the CLI / pipeline / scheduler, which enforces the risk
   gate. This is by design.

---

## 27. What's New in v0.2 (this build)

The second build closes every "genuine limitation" flagged in v0.1
and adds the autonomous operation, self-evaluation, and walk-forward
validation the spec demanded.

### Free fundamental data (real, not fabricated)

`FundamentalAgent` now consumes real yfinance fundamentals — P/E,
forward P/E, price-to-book, profit/gross/operating margins, return on
equity, revenue/earnings growth, debt-to-equity, current ratio, market
cap. When yfinance is unavailable or returns nothing, the agent
returns `None` (no opinion) — never fabricates. See
`jexi_market/enrichment.py`.

### Free news + sentiment (real, not invented)

`NewsAgent` now consumes real yfinance news (titles + publishers) and
classifies sentiment via a curated keyword classifier (positive / negative
/ neutral, deterministic, no LLM required). When no news is available,
the agent returns `None`. See `jexi_market/enrichment.py`.

### Real sector classification

The risk gate's sector-concentration check now uses yfinance's sector
field (Technology, Energy, Financials, etc.) — no more symbol-as-sector
placeholder. See `SectorClassifier` in `jexi_market/enrichment.py`.

### Walk-forward backtesting

`run_walk_forward()` splits data into N windows, runs the strategy
in-sample on the first 70% and evaluates out-of-sample on the
remaining 30%. The reported metrics are the average across all
out-of-sample windows — a much harder test than a single in-sample
backtest, and the standard way to detect overfit strategies. See
`jexi_market/backtest/engine.py`.

### Strategy comparison

`compare_strategies()` runs every registered strategy on the same
data and returns a sorted comparison table (Sharpe, Sortino, max-DD,
win rate, profit factor, alpha). The system does NOT assume one
strategy is universally best. See `jexi_market/backtest/engine.py`.

### Correlation + cluster detection

`compute_correlation_matrix()` and `find_correlated_clusters()` group
symbols whose pairwise return correlation ≥ 0.7. The risk gate uses
this to enforce `max_correlated_exposure` (spec section 13).

### 3 more strategies (8 total)

Added `event_driven` (volume + RSI extremes), `statistical_arb`
(Bollinger z-score mean-reversion), and `volatility_breakout`
(ATR expansion + momentum + volume).

### Autonomous scheduler

`AutonomousScheduler` runs the full pipeline on a schedule with no
human interaction: scan every 5 min, analyze every 10 min, monitor
every 3 min, daily summary at 22:00 UTC. Defaults are conservative —
paper trading doesn't need HFT cadence. See
`jexi_market/scheduler.py`. CLI: `python -m jexi_market.cli scheduler`.

### Self-evaluation loop

`SelfEvaluationLoop` closes open paper trades (stop / take-profit /
max-holding), records the outcome with full agent attribution, and
updates adaptive weights in the performance memory. The orchestrator
then weights future consensus by historical accuracy (clamped to
[0.5, 1.5] so no agent dominates or is silenced). See
`jexi_market/self_eval.py`. CLI: `python -m jexi_market.cli self-eval`.

### FastAPI dashboard

A read-only HTTP dashboard exposes real system state — no fabricated
numbers. Endpoints: `/api/overview`, `/api/agents`, `/api/strategies`,
`/api/recent-trades`, `/api/agent-stats`, `/api/scan-candidates`, plus
POST triggers `/api/analyze/{symbol}` and `/api/scan`. See
`jexi_market/dashboard.py`. CLI: `python -m jexi_market.cli dashboard`.

### Improved confidence system

The `Confidence` formula now incorporates real agent disagreement —
when the Risk Agent or Prof. Aldric raises concerns, the
`disagreement_penalty` flows through to the final confidence score,
which scales Vic's position sizing down. See
`jexi_market/contracts.py:Confidence` and
`jexi_market/agents/leadership.py:ProfAldricAgent`.

### Test coverage

147 tests (was 98), covering every new component: enrichment adapters
(12 tests), scheduler (7), self-eval (9), dashboard (8), walk-forward +
correlation + compare (13), plus all existing tests still pass.

---

*JEXI Market is the market-specialist branch of JEXI OS. JEXI is the
boss. JEXI Market is the specialized market intelligence and trading
division.*
