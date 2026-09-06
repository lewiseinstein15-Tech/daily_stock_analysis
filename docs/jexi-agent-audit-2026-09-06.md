# Jexi OS / daily_stock_analysis audit

**Audit date:** 2026-09-06 (Africa/Nairobi)
**Repository:** `lewiseinstein15-Tech/daily_stock_analysis`
**Parent:** `ZhuLinsen/daily_stock_analysis`
**Scope:** paper-trading bot, ntfy delivery, fork synchronization, agent/tool/MCP research, deterministic simulator tests, and safety controls.

> This project is an experimental paper-trading system. It is not AGI, investment advice, or a guarantee of profit. No live-money order was placed during this audit. The new safety gate refuses a non-paper Alpaca endpoint unless two explicit live-trading flags are set.

## 1. Fork status at audit time

The fork was fetched against the parent repository before changes were made.

| Item | Value |
| --- | --- |
| Fork HEAD before this audit | `0d62104949ab0ea0d5996e59a1a5274308d0f86a` |
| Parent `main` | `303f4e1c18b7e149bc2b7618eb63a6574507bc6b` |
| Commits ahead of parent | 18 |
| Commits behind parent | 0 |
| Fork type | public GitHub fork |
| Parent remote | `https://github.com/ZhuLinsen/daily_stock_analysis.git` |

There were **no parent-only commits to merge** at the time of the audit. The fork's latest commits already contained the previous-session trading and ntfy work, including the data-host correction, market-clock lookup, position sizing, double-sell guard, JSON ntfy publishing, and oversized-report attachment fallback.

The auto-sync workflow's range-based calculation (`HEAD..upstream/main` and `upstream/main..HEAD`) is the correct way to calculate behind/ahead counts for a fork with its own commits and merge commits.

## 2. Problems found and corrected

### A. `NTFY_URL` was ignored by the standalone trading bot

The rest of the application documents the canonical form:

```text
NTFY_URL=https://ntfy.sh/my-topic
```

But `automated_trading_bot.py` only read `NTFY_SERVER` and `NTFY_TOPIC`. If only the documented `NTFY_URL` Secret was configured, the trading workflow could publish to the default topic instead of the user's ntfy topic. This directly explains a likely “the ntfy app is not receiving the bot report” failure mode.

**Fix:** the bot now parses `NTFY_URL`, including a reverse-proxy path prefix, and uses it as the canonical destination. The legacy server/topic pair still works. The auto-trading workflow now passes the `NTFY_URL` Secret to the bot run itself, not just to its failure-notification step.

### B. Accidental live-endpoint risk

The old code accepted any `APCA_API_BASE_URL`. A typo or an accidentally configured live URL could have sent orders to a real account.

**Fix:** normal order cycles now fail closed unless the endpoint is Alpaca paper (`paper-api.alpaca.markets`) or a local test simulator. Live trading requires both:

```text
BOT_PAPER_ONLY=false
BOT_ALLOW_LIVE_TRADING=true
```

`BOT_DRY_RUN=true` and `BOT_RESEARCH_ONLY=true` never submit orders. The workflow defaults remain paper-only.

### C. Margin buying power could inflate the budget

The old `RiskAgent` subtracted the cash reserve from `buying_power`. A margin paper account can report buying power greater than equity, which contradicted the bot's documented “equity-based, not leveraged” contract.

**Fix:** entry capital is now capped by equity, buying power, and cash when available, then the reserve is removed. The new regression test proves that a `$100,000` equity account with `$400,000` buying power cannot spend more than the configured `$80,000` after a 20% reserve.

### D. No safe overnight research mode

Closed-market cycles previously sent a short closed note and did no research. That meant there was no day/night agent review loop.

**Fix:** added `.github/workflows/overnight-research.yml`. It runs every four hours on weekdays with both `BOT_RESEARCH_ONLY=true` and `BOT_DRY_RUN=true`. It can collect the market regime, paper quotes, technical analysis, data-quality audit, and optional repository agent advisory, then send the structured report to ntfy. It has no order path.

### E. Incomplete market data could look like a neutral signal

The regime fallback previously returned a neutral score when SPY data was unavailable. A neutral number is not the same as valid evidence, and a candidate could otherwise pass a buy threshold.

**Fix:** regime output now carries `data_ok`; new entries are blocked when SPY history is incomplete. A `DataQualityAgent` also marks symbols without a valid quote and sufficient history as not tradeable.

### F. The automated bot did not use the fork's existing multi-agent runtime

The repository already contains a multi-agent stack (technical, intel, risk, portfolio/decision orchestration and registered data/search tools), but the automated trading script only used its own deterministic scorer.

**Fix:** added an opt-in advisory bridge. With `BOT_USE_LLM_AGENTS=true`, the trading bot lazily reuses the repository's existing `build_agent_executor()` / `AgentOrchestrator` path. The advisory result is blended with the deterministic technical score; it cannot submit orders, override position sizing, bypass the data gate, or bypass the paper endpoint gate. LLM failure falls back to deterministic analysis unless `BOT_LLM_AGENTS_REQUIRED=true` is explicitly requested.

The default is **off** to avoid surprise provider cost and to keep paper cycles deterministic until LLM credentials and model routing are deliberately configured.

### G. MCP was descriptor-only, not an order-capable transport

The existing `ToolSurface` already exports MCP-compatible descriptors, but it intentionally did not expose a REST/MCP transport. Exposing broker-order tools directly to an LLM would add a high-risk side-effect boundary.

**Fix:** added `src/agent/mcp_manifest.py` and `scripts/export_jexi_mcp_manifest.py`. The manifest exports read-only data, analysis, search, market, and backtest descriptors by default. Action tools are excluded. If explicitly exported for a controlled host, action descriptors are marked destructive and require confirmation in the Jexi policy metadata. This is an MCP-ready manifest, not a claim that an unauthenticated public MCP server has been deployed.

## 3. Resulting agent architecture

The trading cycle is now organized as:

1. **Market Agent** — Alpaca clock and SPY regime; holiday-aware when Alpaca is reachable.
2. **Technical / Research Agent** — Alpaca quote and daily bars; repository `src.stock_analyzer` first, pure-Python fallback if optional dependencies are unavailable.
3. **Optional LLM Council** — repository Technical, Intel, Risk, and Decision agents through the existing orchestrator; advisory only.
4. **Data-Quality Agent** — blocks incomplete evidence from new entries.
5. **Risk Agent** — reserve, equity/cash caps, position slots, take-profit, stop-loss, regime exits, pending-order double-sell protection.
6. **Execution Agent** — market-order submission or explicit dry-run plans.
7. **Report Agent** — structured cycle report, agent/data audit, ntfy JSON publish, and long-report attachment fallback.
8. **MCP manifest layer** — safe discovery of read-only tools for a future authenticated Jexi host.

The report now shows the research source, data gate, optional LLM-council status, audit warnings, action results, and final portfolio state.

## 4. Configuration that must be set in GitHub

### Required Secrets

```text
ALPACA_API_KEY       # Alpaca PAPER account key
ALPACA_SECRET_KEY    # Alpaca PAPER account secret
NTFY_URL             # complete endpoint, e.g. https://ntfy.sh/my-stock-report-kenya
```

Optional:

```text
NTFY_TOKEN
OPENAI_API_KEY
ANTHROPIC_API_KEY
GEMINI_API_KEY
DEEPSEEK_API_KEY
```

### Recommended Variables

```text
APCA_API_BASE_URL=https://paper-api.alpaca.markets
ALPACA_DATA_BASE_URL=https://data.alpaca.markets
STOCKS_TO_TRADE=AAPL,MSFT,NVDA
BOT_PAPER_ONLY=true
BOT_ALLOW_LIVE_TRADING=false
BOT_USE_LLM_AGENTS=false
BOT_RESEARCH_ONLY=false
```

To enable the repository multi-agent advisory path after provider configuration:

```text
BOT_USE_LLM_AGENTS=true
BOT_LLM_AGENTS_REQUIRED=false
BOT_LLM_AGENT_WEIGHT=0.35
AGENT_ARCH=multi
AGENT_ORCHESTRATOR_MODE=standard
LITELLM_MODEL=<configured model route>
```

Start with `BOT_LLM_AGENTS_REQUIRED=false`; this preserves deterministic paper analysis if a provider, tool, or model is temporarily unavailable.

### First acceptance run

Use GitHub Actions → **Automated Trading Bot** → **Run workflow** with:

```text
force: false
 dry_run: true
```

For an overnight agent acceptance run, use **Overnight Agent Research**. The workflow is already hard-wired to research-only and dry-run.

## 5. Test and verification matrix

All HTTP calls in the checked-in automated-bot tests are mocked or point to the local simulator. No Alpaca or ntfy credential is required for these tests.

Scenarios covered:

- Alpaca trading/data hosts and v2 payload parsing
- quote fallback and bar fallback
- Alpaca market clock and ET-hours fallback
- SPY regime buckets and incomplete-data block
- repository analyzer path and built-in scorer fallback
- LLM advisory blending with a fake executor
- take-profit, stop-loss, regime liquidation
- pending sell double-sell protection
- margin buying-power budget cap
- max positions, max buys, reserve, dust orders, existing/pending positions
- paper endpoint safety gate
- dry-run plans without `/v2/orders`
- research-only closed-market run without `/v2/orders`
- structured ntfy JSON, Bearer authentication, timeout
- ntfy HTTP 413 summary + full attachment fallback
- Unicode-safe attachment headers
- simulator end-to-end bull, stop-loss, crash, closed, forced, dry-run, research-only, and 413 scenarios
- read-only MCP manifest export and action confirmation metadata

Commands run during the audit:

```bash
python -m pytest -q tests/test_automated_trading_bot.py tests/test_trading_bot_e2e.py
python -m pytest -q tests/test_trading_bot_safety_and_agents.py tests/test_jexi_mcp_manifest.py
```

The final combined targeted run completed with **187 passed** (including the notification sender regression suite, the trading-bot unit/e2e suite, the new safety/agent tests, and the MCP manifest tests).

A repository-wide `python -m pytest -q` collected **6,852** tests and completed with **6,778 passed, 5 skipped, and 69 failed**. The 69 failures were outside the changed trading-bot/MCP paths and were primarily caused by the deliberately minimal audit environment not installing every optional data-provider dependency (for example `akshare`, `yfinance`, and `pypinyin`) plus pre-existing environment/calendar/image/provider assumptions. The changed trading-bot, notification, e2e, safety, and MCP tests all passed in the targeted run. This distinction is recorded rather than presenting the full-suite run as green.

## 6. Research sweep and design decisions

The research sweep compared the repository against current open-source agent and MCP patterns:

- **TradingAgents** — multi-agent market/fundamental/news/social research, debate, and decision synthesis. Useful architectural idea: specialist opinions should be separate from the final decision; it should not be copied as an unguarded order executor. [GitHub search result](https://github.com/TauricResearch/TradingAgents)
- **ai-hedge-fund** — investor-persona analysis and portfolio-manager synthesis. Useful idea: diversity of independent opinions; not evidence that personas create alpha. [GitHub search result](https://github.com/virattt/ai-hedge-fund)
- **FinRobot** — open-source financial-analysis agent platform. Useful for research/report generation, not a substitute for execution controls. [GitHub search result](https://github.com/AI4Finance-Foundation/FinRobot)
- **AgenticTrading** — traceable experiments, backtests, paper trading, decision logs, evaluation and future MCP/A2A connectivity. Useful idea: evaluate reasoning traces and costs/risks, not just final returns. [GitHub](https://github.com/Open-Finance-Lab/AgenticTrading)
- **AlpacaTradingAgent** — an Alpaca-focused multi-agent implementation with parallel analysts, memory/checkpoints, risk/portfolio roles, and paper/live adapters. Useful idea: separate analyst work from the trade/risk boundary. [GitHub](https://github.com/huygiatrng/AlpacaTradingAgent)
- **Open Paper Trading MCP** — a paper simulator with REST and MCP interfaces and one underlying trading service. Useful for later isolated simulation; it is not imported into this fork because the checked-in local simulator is deterministic and dependency-light. [GitHub](https://github.com/Open-Agent-Tools/open-paper-trading-mcp)
- **Alpaca MCP Server** — official data/account/trading tool surface. It exposes powerful account and order operations, so an eventual Jexi connector must use least privilege and confirmation rather than handing all tools to an LLM. [Official docs](https://docs.alpaca.markets/us/docs/alpaca-mcp-server)
- **MCP specification** — tools, resources, and prompts are distinct primitives; resources are application-driven and resource permissions/URI validation matter. [MCP resources specification](https://modelcontextprotocol.io/specification/2025-06-18/server/resources)
- **MCP security** — current security guidance highlights prompt injection, tool poisoning, overly broad scopes, data exfiltration, and billing/denial-of-wallet risks. Jexi therefore exports read-only descriptors by default and keeps order execution behind code-enforced gates. [Security analysis](https://arxiv.org/html/2601.17549v1), [security best practices](https://labs.cloudsecurityalliance.org/agentic/agentic-mcp-security-best-practices-v1/)
- **Curated directory** — `LLMQuant/awesome-trading-agents` was used as the index for additional agents, MCP servers, skills, benchmarks, and broker adapters. [Directory](https://github.com/LLMQuant/awesome-trading-agents)

### What was not claimed

No public repository was treated as proof of a profitable autonomous AGI. Backtests can overfit; paper fills can differ from live fills; LLM reasoning is probabilistic and can be wrong; third-party data can be delayed, missing, manipulated, or rate-limited. The safe progression is deterministic tests → historical walk-forward evaluation → live-market paper trading → human review → only then a separately approved deployment decision.

## 7. Remaining follow-ups

1. Configure the paper Alpaca and ntfy Secrets, then run the manual dry-run workflow.
2. Verify the ntfy topic receives both an open-market report and a closed/research-only report.
3. Leave LLM advisory disabled until provider/model routing is tested; then enable it for paper-only advisory runs and compare it with the deterministic score.
4. Run at least 30 calendar days of paper results and record fills, slippage, drawdown, turnover, costs, and comparison with SPY buy-and-hold.
5. Add a persistent performance ledger and daily-loss circuit breaker before considering any broader automation.
6. If an external MCP server is added later, pin versions, authenticate it, allowlist only needed tools, validate tool metadata, redact secrets, log every invocation, and require explicit confirmation for any destructive action.

## 8. Credential hygiene

The GitHub credential included in the original request was **not written to the repository, logs, report, or commit**. Because credentials pasted into chat should be considered exposed, revoke/rotate that token in GitHub and create a new least-privilege token if repository push access is still needed. The final commit contains no GitHub token or broker secret.
