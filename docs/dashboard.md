# Dashboard

De eerste dashboardversie staat in:
- `dashboard/app.py`

Start via:

```powershell
python tools/main_dashboard.py
```

Benodigde dependency:

```powershell
pip install ".[dashboard]"
```

## Pagina's

### Overview
Toont:
- deployments
- fills
- live/blocked status
- weighted shortfall
- weighted cost
- median edge retention
- research trigger count
- recente activity

### Execution
Toont:
- TCA overview
- by symbol
- by strategy
- by hour
- worst fills

### Agents
Toont:
- edge retention per agent
- drag share
- execution drag
- cost drag
- fragility label
- adaptation action
- estimated result-index change

### Research
Toont:
- research queue
- escalation mode
- failure labels
- recente research activity

## Databronnen

Het dashboard leest:
- `artifacts/system/reports/live_health_report.json`
- `artifacts/system/reports/trade_cost_analysis.json`
- `artifacts/system/reports/tca_impact_report.json`
- `artifacts/system/reports/tca_adaptation_impact_report.json`
- `artifacts/system/reports/live_research_queue.json`
- `artifacts/live/<symbol>/improvement_activity.jsonl`

## Snapshot generatie

De JSON snapshots worden automatisch bijgewerkt wanneer je deze report generators draait:
- `generate_tca_report(...)`
- `generate_tca_impact_report(...)`
- `generate_tca_adaptation_impact_report(...)`
- `generate_live_health_report(...)`

In de live loop worden deze reports al mee ververst.

## Doel van v1

Deze dashboardversie is read-only en bedoeld voor:
- live monitoring
- TCA review
- agent health review
- research queue review

Nog niet in v1:
- write-actions
- authentication
- multi-server centrale aggregatie
- realtime websockets
