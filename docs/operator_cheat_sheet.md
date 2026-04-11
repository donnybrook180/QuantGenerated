# Operator Cheat Sheet

Gebruik dit als dagelijkse reviewkaart voor live trading, TCA en self-improvement.

## Dagelijkse volgorde

Check deze 5 reports in deze volgorde:

1. `artifacts/system/reports/live_health_report.txt`
2. `artifacts/system/reports/trade_cost_analysis.txt`
3. `artifacts/system/reports/tca_impact_report.txt`
4. `artifacts/system/reports/execution_adaptation_report.txt`
5. `artifacts/system/reports/live_improvement_activity_report.txt`

Daarna alleen indien nodig:

6. `artifacts/system/reports/live_research_queue.txt`

## 1. Live health

Open:
- `live_health_report.txt`

Check:
- `Deployments scanned`
- `live_ready`, `reduced_risk_only`, `research_only`
- `symbols_with_incidents`
- `total_fills`
- `Tradeable now`
- `Blocked now`
- per symbool:
  - `status`
  - `execution_adaptation`
  - `execution_guardrail`
  - `latest_incident`
  - `fills`

Alarm als:
- `symbols_with_incidents > 0`
- bijna alles in `Blocked now` staat
- `total_fills = 0` terwijl live trading had moeten draaien
- veel symbolen op `reduced_risk_only` staan zonder duidelijke reden

Actie:
- check incident logs in `artifacts/live/<symbol>/incidents/`
- check of MT5/datafeed/live loop draait
- check of adaptation te streng is geworden

## 2. Trade Cost Analysis

Open:
- `trade_cost_analysis.txt`
- eventueel `trade_cost_analysis_<symbol>.txt`

Check:
- `fills`
- `weighted_touch_slippage_bps`
- `weighted_shortfall_bps`
- `weighted_cost_bps`
- `adverse_fill_rate_pct`
- slechtste symbols / strategieen / uren

Alarm als:
- `weighted_shortfall_bps` duidelijk oploopt
- `weighted_cost_bps` groot wordt t.o.v. je edge
- `adverse_fill_rate_pct` structureel hoog is
- 1 symbool veel slechter executeert dan de rest

Actie:
- kijk per symbool of sessie waar drag zit
- verwacht adaptation of research-triggers op die symbolen
- overweeg tijdelijke risk reduction als drag extreem is

## 3. TCA impact

Open:
- `tca_impact_report.txt`

Check:
- `edge_retention_pct`
- `drag_share_pct`
- verdicts zoals `safe`, `watch`, `fragile`, `untradeable`

Alarm als:
- `edge_retention_pct < 60%` bij meerdere live agents
- `edge_retention_pct < 40%` bij belangrijke agents
- `drag_share_pct` groot deel van de bruto edge opeet

Actie:
- check of adaptation deze agents al afschaalt
- check of research queue deze agents oppakt
- als niet: onderzoek autopsy/adaptation thresholds

## 4. Execution adaptation

Open:
- `execution_adaptation_report.txt`

Check:
- hoeveel `demote_moderate`
- hoeveel `demote_severe`
- of er `guardrail_*` acties zijn
- of er `tca_block_new_entries`-achtig gedrag optreedt

Alarm als:
- dezelfde agent vaak severe gedemoveerd wordt
- veel symbolen tegelijk severe worden gedemoveerd
- guardrails constant ingrijpen

Actie:
- check `live_improvement_activity_report.txt` voor frequentie
- check of het een structureel execution-probleem is
- check of research al getriggerd is

## 5. Improvement activity

Open:
- `live_improvement_activity_report.txt`

Check:
- `Total events`
- `By category`
- `Top actions`
- per symbool:
  - `events`
  - `actions`
  - `last_demotion`
  - `last_research_trigger`
  - `last_research_run`

Alarm als:
- 1 symbool veel meer events heeft dan de rest
- dezelfde agent steeds opnieuw demoties krijgt
- research-triggers vaak voorkomen maar research-runs uitblijven
- research-runs vaak mislukken

Actie:
- diepere debug in `artifacts/live/<symbol>/improvement_activity.jsonl`
- check `live_research_queue.txt`
- bepaal of dit tijdelijk is of structureel

## 6. Research queue

Open:
- `live_research_queue.txt`

Check:
- `priority`
- `failure_labels`
- `escalation_mode`
- `structured_experiments`
- `command`

Alarm als:
- high-priority directives blijven terugkomen
- blokkades ontstaan zonder replacement research
- repeated demotion optreedt op hetzelfde symbool

Actie:
- voer research gericht uit of laat auto-research lopen
- kijk na de rerun in `artifacts/research/<symbol>/reports/`

## Simpele drempels

Gebruik deze als operator-alarm, niet als harde research-wet:

- `edge_retention_pct < 60%`: opletten
- `edge_retention_pct < 40%`: ernstig
- `weighted_shortfall_bps` duidelijk hoger dan normaal: execution stress
- `weighted_cost_bps` in orde van grootte van je edge: strategie fragiel
- herhaalde `demote_severe`: structureel probleem
- herhaalde `targeted_plus_replacement` of `full_rerun_only`: huidige live variant faalt

## Wat je dan doet

Bij operationeel probleem:
- kijk eerst naar `live_health_report`
- daarna incidents en journals

Bij execution-probleem:
- kijk naar `trade_cost_analysis`
- daarna `tca_impact_report`

Bij adaptation-probleem:
- kijk naar `execution_adaptation_report`
- daarna `live_improvement_activity_report`

Bij self-improvement/research-probleem:
- kijk naar `live_research_queue`
- daarna symbol research reports

## Kernvragen

Elke dag wil je deze vragen kunnen beantwoorden:

- Draait live gezond?
- Krijgen we genoeg fills?
- Hoeveel edge verliezen we aan execution?
- Welke agents worden lokaal gedemoveerd?
- Hoe vaak gebeurt dat en op welke symbolen?
- Welke problemen gaan automatisch de research queue in?
- Levert research vervanging of reparatie op?
