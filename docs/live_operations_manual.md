# Live Operations Manual

Dit is het centrale handboek voor live operatie van het project.

Gebruik dit document als startpunt. De detaildocumenten blijven daarnaast bestaan:
- `docs/report_map.md`
- `docs/architecture_map.md`
- `docs/operator_cheat_sheet.md`
- `docs/server_runbook.md`
- `docs/prop_firm_launch_checklist.md`
- `docs/repo_usage_guide.md`
- `docs/multi_prop_env_and_live_plan.md`

## Doel

Dit handboek helpt je bij:
- live monitoring
- TCA review
- adaptation en research observability
- server launches per prop firm
- dagelijkse en wekelijkse operator-routine

## Architectuurprincipe

De juiste setup is:
- 1 codebase
- meerdere servers
- 1 server per prop firm
- per server een eigen runtime, database, MT5 account en artifactstroom

Dus:
- code gedeeld
- data en feedback niet gedeeld

Dat betekent dat:
- FTMO alleen leert van FTMO fills
- FundedNext alleen leert van FundedNext fills
- Top One Trader alleen leert van Top One Trader fills

## Documenten

### `docs/report_map.md`
Gebruik voor:
- volledig overzicht van alle reports, plots en artifacts
- betekenis per report
- beslissingen per report

### `docs/architecture_map.md`
Gebruik voor:
- actuele modulegrenzen na Step 1
- vinden van research/live/venue/app code
- zien welke root-entrypoint naar welke subsystemmodule doorstuurt

### `docs/operator_cheat_sheet.md`
Gebruik voor:
- dagelijkse korte operator-routine
- alarmsignalen
- directe acties

### `docs/server_runbook.md`
Gebruik voor:
- wat je controleert na deploy
- wat je controleert na eerste fills
- wat je controleert na 1 dag en 1 week live

### `docs/prop_firm_launch_checklist.md`
Gebruik voor:
- pre-live checklist voordat een nieuwe prop-firm server aan gaat

### `docs/repo_usage_guide.md`
Gebruik voor:
- dagelijkse repo-usage
- research draaien
- venue-aware deployments begrijpen
- multi-prop operator flow

### `docs/multi_prop_env_and_live_plan.md`
Gebruik voor:
- implementatieplan voor broker-specifieke env vars
- keuze voor aparte live loops per prop firm
- migratievolgorde voor multi-prop live

## Kernreports

De belangrijkste reports zijn:

1. `artifacts/system/reports/live_health_report.txt`
2. `artifacts/system/reports/trade_cost_analysis.txt`
3. `artifacts/system/reports/tca_impact_report.txt`
4. `artifacts/system/reports/execution_adaptation_report.txt`
5. `artifacts/system/reports/live_improvement_activity_report.txt`
6. `artifacts/system/reports/live_research_queue.txt`

## Dagelijkse routine

Leesvolgorde:

1. `live_health_report.txt`
2. `trade_cost_analysis.txt`
3. `tca_impact_report.txt`
4. `execution_adaptation_report.txt`
5. `live_improvement_activity_report.txt`
6. `live_research_queue.txt` indien nodig

Beantwoord elke dag:
- draait live gezond?
- krijgen we fills?
- hoeveel edge verliezen we aan execution?
- welke agents worden lokaal gedemoveerd?
- hoe vaak gebeurt dat en waar?
- welke problemen worden naar research gestuurd?

## Wekelijkse routine

Per server:

1. bekijk globale TCA
2. bekijk symbol-specifieke TCA reports
3. bekijk TCA impact
4. bekijk adaptation impact
5. bekijk activity report op frequentie per symbool
6. bekijk research queue en research output

Beantwoord per server:
- welke symbols zijn execution-vriendelijk?
- welke symbols zijn structureel duur?
- welke agents behouden netto edge?
- welke agents moeten kleiner?
- welke agents moeten vervangen worden?

## Launch flow voor een nieuwe prop-firm server

Gebruik eerst:
- `docs/prop_firm_launch_checklist.md`

Daarna:
- start live loop
- check `live_health_report.txt`
- check of journals en incidents goed werken
- wacht op eerste fills
- controleer of TCA metrics binnenkomen

Na de eerste echte live periode:
- gebruik `docs/server_runbook.md`

## Hoe je de reports leest

### Health
`live_health_report.txt`

Gebruik om te zien:
- algemene live status
- incidenten
- tradeable of blocked status
- link naar alle andere belangrijke reports

### TCA
`trade_cost_analysis.txt`

Gebruik om te zien:
- spread
- slippage
- implementation shortfall
- broker costs
- adverse fills

### TCA impact
`tca_impact_report.txt`

Gebruik om te zien:
- hoeveel research-edge netto overblijft na execution

### Adaptation
`execution_adaptation_report.txt`

Gebruik om te zien:
- welke strategies gepromoveerd of gedemoveerd worden
- waar guardrails ingrijpen

### Improvement activity
`live_improvement_activity_report.txt`

Gebruik om te zien:
- hoe vaak demoties en research-events gebeuren
- op welke symbolen
- wat de laatste trigger of run was

### Research queue
`live_research_queue.txt`

Gebruik om te zien:
- welke live problemen naar research vertaald worden
- of het targeted repair of replacement research is

## Belangrijkste operationele signalen

Goed:
- fills nemen toe
- TCA heeft data
- edge retention blijft redelijk
- adaptation grijpt selectief in
- research queue bevat alleen echte structurele problemen

Slecht:
- geen fills
- veel incidents
- massale severe demotions
- lage edge retention op meerdere symbols
- herhaalde research triggers zonder verbetering

## Wat je doet bij problemen

Bij operationeel probleem:
- open `live_health_report.txt`
- check incidents en journals

Bij execution-probleem:
- open `trade_cost_analysis.txt`
- open `tca_impact_report.txt`

Bij adaptation-probleem:
- open `execution_adaptation_report.txt`
- open `live_improvement_activity_report.txt`

Bij research-probleem:
- open `live_research_queue.txt`
- open symbol research reports in `artifacts/research/<symbol>/reports/`

## Per prop firm vergelijken

Vergelijk alleen rapportuitkomsten tussen servers, niet de ruwe databases.

Vergelijk bijvoorbeeld:
- `weighted_shortfall_bps`
- `weighted_cost_bps`
- `adverse_fill_rate_pct`
- edge retention
- frequentie van demoties
- frequentie van research triggers

Zo leer je:
- welke prop firm execution-vriendelijk is
- welke symbols per prop firm wel of niet geschikt zijn

## Kernregel

Het systeem moet niet alleen beschermen, maar ook leren.

Dus:
- adaptation beschermt live kapitaal
- autopsy verklaart het probleem
- research zoekt reparatie of vervanging
- TCA bepaalt hoeveel edge werkelijk overblijft

## Aanbevolen gebruik

Gebruik dit als hoofdindex:
- begin hier
- ga daarna naar het relevante detaildocument

Aanbevolen volgorde:
1. `docs/live_operations_manual.md`
2. `docs/architecture_map.md`
3. `docs/operator_cheat_sheet.md`
4. `docs/server_runbook.md`
5. `docs/report_map.md`
6. `docs/prop_firm_launch_checklist.md`
