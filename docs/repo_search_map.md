# Repo Search Map

This file exists to make repo search faster and less guessy.

Use it together with:

- [docs/architecture_map.md](C:/Users/liset/PycharmProjects/QuantGenerated/docs/architecture_map.md)

## Fast Search Rules

Prefer `rg` over broad manual browsing.

Common patterns:

```powershell
rg -n "run_symbol_research|execution_candidate_row|meets_viability" quant_system
rg -n "build_symbol_deployment|load_symbol_deployment|symbol_status" quant_system
rg -n "main_live_loop|loop_app|run_live_once_app" . docs tools
rg -n "blue_guardian|prop_viability|signal_quality|venue_basis" quant_system docs
rg -n "^class " quant_system\agents
rg --files quant_system\research
rg --files quant_system\live
```

## Search By Intent

If you want symbol research logic:

- start in `quant_system/research/`
- compatibility layer: `quant_system/symbol_research.py`

Best first searches:

```powershell
rg -n "execution_candidate_row|select_execution_candidates|meets_viability" quant_system\research quant_system\symbol_research.py
rg -n "export_results|viability_autopsy|build_execution_policy" quant_system\research quant_system\symbol_research.py
```

If you want live runtime logic:

- start in `quant_system/live/`

Best first searches:

```powershell
rg -n "MT5LiveExecutor|run_once|reconcile|allocation|interpreter" quant_system\live
rg -n "loop_app|run_live_once_app|resolve_live_deployment_paths" quant_system\live main_live_*.py
```

If you want deployment artifact shaping:

```powershell
rg -n "build_symbol_deployment|load_symbol_deployment|DeploymentStrategy|SymbolDeployment" quant_system
```

If you want venue-specific behavior:

```powershell
rg -n "get_venue_profile|normalize_venue_key|blue_guardian|ftmo|fundednext" quant_system\venues quant_system
```

If you want agent-family definitions:

```powershell
rg -n "^class " quant_system\agents\*_setups quant_system\agents
rg -n "from quant_system\\.agents\\.(crypto|forex|us500|xauusd)" quant_system
```

## Hot Files

Highest-value navigation files:

- `quant_system/research/selection.py`
- `quant_system/research/viability.py`
- `quant_system/research/exports.py`
- `quant_system/research/orchestration.py`
- `quant_system/live/deploy.py`
- `quant_system/live/runtime.py`
- `quant_system/live/loop_app.py`
- `quant_system/venues/registry.py`
- `quant_system/profile_app.py`

Compatibility files that still receive search hits:

- `quant_system/symbol_research.py`
- `quant_system/app.py`
- `quant_system/agents/crypto.py`
- `quant_system/agents/forex.py`
- `quant_system/agents/us500.py`
- `quant_system/agents/xauusd.py`

## Artifact Search

If you want where reports come from:

```powershell
rg -n "symbol_research\\.txt|symbol_research\\.csv|viability_autopsy|live\\.json" quant_system tools
```

If you want who writes live reports:

```powershell
rg -n "live_health_report|trade_cost_analysis|execution_adaptation_report|live_research_queue" quant_system
```

## Step 2 Search Shortcuts

For Blue Guardian venue-aware research work:

```powershell
rg -n "blue_guardian|prop_viability|signal_quality|swap|slippage|stress|interpreter_fit" quant_system docs
rg -n "broker_swap|carry|swap_long|swap_short" quant_system
rg -n "allowed_archetypes|blocked_archetypes|interpreter" quant_system\interpreter quant_system\live
```
