# Server Runbook

Gebruik dit runbook per prop-firm server, bijvoorbeeld:
- FTMO server
- FundedNext server
- Top One Trader server

Uitgangspunt:
- 1 server = 1 prop firm = 1 eigen runtime
- zelfde codebase
- eigen MT5 login
- eigen database
- eigen live data
- eigen TCA en adaptation feedback

## Fase 1: Direct na deploy

Doel:
- Controleren dat de server technisch goed staat en live artifacts kan opbouwen.

Check:
- juiste `.env`
- juiste MT5 terminal/account
- juiste `AI_EXPERIMENT_DB_PATH`
- live loop start zonder crash
- deployments bestaan in `artifacts/deploy/<symbol>/live.json`

Open:
- `artifacts/system/reports/live_health_report.txt`

Je wilt zien:
- `Deployments scanned` groter dan `0`
- geen directe import/runtime errors
- symbols zichtbaar in het report
- `latest_incident` liefst `none`

Als fout:
- check MT5 login
- check of DB-pad uniek is per server
- check of deployments zijn gegenereerd

## Fase 2: Eerste live cycle

Doel:
- Controleren dat de live loop echt draait en journals schrijft.

Check per symbool:
- `artifacts/live/<symbol>/journals/`
- `artifacts/live/<symbol>/incidents/`

Open:
- `live_health_report.txt`

Je wilt zien:
- `latest_journal` aanwezig
- `latest_actions` ingevuld
- geen nieuwe incident-spam

Als fout:
- check regime/policy blokkades
- check marktopen status
- check of executor orders probeert te bouwen

## Fase 3: Eerste fills

Doel:
- Verifiëren dat execution-data binnenkomt en TCA begint te leven.

Open:
- `trade_cost_analysis.txt`
- eventueel `trade_cost_analysis_<symbol>.txt`
- `live_health_report.txt`

Je wilt zien:
- `total_fills > 0`
- TCA niet meer `none`
- per symbool echte spread/slippage/cost metrics

Als fout:
- check of fills in `mt5_fill_events` terechtkomen
- check MT5 deal history access
- check of symbol mapping klopt tussen deployment en broker symbol

## Fase 4: Eerste adaptation signalen

Doel:
- Begrijpen of de prop firm execution meteen lokaal afwijkend gedrag veroorzaakt.

Open:
- `execution_adaptation_report.txt`
- `tca_impact_report.txt`

Je wilt zien:
- nog niet te veel `insufficient_data` zodra fills binnenkomen
- logische eerste `demote_moderate` of `promote_healthy`
- geen massale severe demotions zonder duidelijke TCA-drag

Als fout:
- thresholds mogelijk te streng
- te weinig fills voor betrouwbare conclusies
- broker execution mogelijk structureel slecht op specifieke symbols

## Fase 5: Eerste research triggers

Doel:
- Zien of live failures netjes naar research vertaald worden.

Open:
- `live_research_queue.txt`
- `live_improvement_activity_report.txt`

Je wilt zien:
- research triggers pas na voldoende fills
- failure labels die logisch aansluiten op de TCA-data
- escalation mode passend bij ernst:
  - `targeted_only`
  - `targeted_plus_replacement`
  - `full_rerun_only`

Als fout:
- check autopsy thresholds
- check of adaptation-acties en research-triggers goed aansluiten
- check of repeated demotions niet te snel escaleren

## Fase 6: Na 1 dag live

Doel:
- Eerste operationele en executionmatige beoordeling van de server.

Open in deze volgorde:
1. `live_health_report.txt`
2. `trade_cost_analysis.txt`
3. `tca_impact_report.txt`
4. `execution_adaptation_report.txt`
5. `live_improvement_activity_report.txt`
6. `live_research_queue.txt`

Je wilt beantwoorden:
- draait live gezond?
- krijgen we genoeg fills?
- welke symbols executen slecht?
- welke agents worden gedemoveerd?
- wordt research logisch getriggerd?

Beslissing:
- server laten doorlopen
- thresholds tunen
- bepaalde symbols tijdelijk kleiner zetten

## Fase 7: Na 1 week live

Doel:
- De prop-firm runtime echt evalueren als lokale execution venue.

Open:
- `trade_cost_analysis.txt`
- alle relevante `trade_cost_analysis_<symbol>.txt`
- `tca_impact_report.txt`
- `tca_adaptation_impact_report.txt`
- `live_improvement_activity_report.txt`
- `live_research_queue.txt`

Je wilt beantwoorden:
- welke symbols zijn execution-vriendelijk op deze prop firm?
- welke symbols zijn structureel duur of adversarial?
- welke agents behouden netto edge?
- welke agents blijven terugkomen in demotions/research?
- is adaptation voldoende of is replacement research nodig?

Beslissingen:
- symbolen promoten/de-risken/blokkeren
- thresholds aanpassen per prop firm
- replacement research starten voor structurele verliezers

## Fase 8: Vergelijken tussen servers

Doel:
- Niet data mengen, maar wel de uitkomsten vergelijken.

Vergelijk tussen FTMO / FundedNext / Top One servers:
- gemiddelde `weighted_shortfall_bps`
- gemiddelde `weighted_cost_bps`
- `adverse_fill_rate_pct`
- welke symbols vaak severe worden gedemoveerd
- welke symbols veel research triggers genereren
- welke agents netto edge behouden

Belangrijk:
- vergelijk alleen reports tussen servers
- meng geen databases of live fill events

## Alarmen

Direct aandacht nodig als:
- `total_fills = 0` terwijl live trades verwacht worden
- incidenten blijven terugkomen
- bijna alle symbols blocked of reduced-risk worden
- `edge_retention_pct` structureel laag blijft
- dezelfde agent herhaald severe demotions krijgt
- research queue groeit maar levert geen vervangers op

## Minimale dagelijkse routine per server

1. Open `live_health_report.txt`
2. Open `trade_cost_analysis.txt`
3. Open `tca_impact_report.txt`
4. Open `execution_adaptation_report.txt`
5. Open `live_improvement_activity_report.txt`

## Minimale wekelijkse routine per server

1. Bekijk symbol-specifieke TCA reports
2. Bekijk adaptation impact
3. Bekijk activity report op frequentie per symbool
4. Bekijk research queue en uitgevoerde research
5. Beslis welke agents lokaal mogen blijven, kleiner moeten of vervangen moeten worden

## Kernprincipe

Per server wil je uiteindelijk dit weten:

- Welke edge heeft research beloofd?
- Hoeveel daarvan wordt door deze prop firm opgegeten?
- Welke agents overleven netto?
- Welke agents moeten alleen kleiner?
- Welke agents moeten herontworpen of vervangen worden?
