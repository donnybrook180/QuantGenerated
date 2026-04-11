# Report Map

Dit document beschrijft welke reports en artifacts je hebt, waar ze staan, wanneer je ze gebruikt en welke beslissingen je erop baseert.

## Dagelijkse kernreports

### `artifacts/system/reports/live_health_report.txt`
Doel:
- Hoofd-overzicht van de live omgeving.
- Laat per symbool zien wat de status is, of er fills zijn, incidents, TCA-status en research-triggers.

Gebruik wanneer:
- Je snel wilt weten of live trading operationeel gezond is.
- Je wilt zien welke symbolen tradeable, blocked of reduced-risk zijn.

Beslissingen:
- Of een server gezond draait.
- Of een symbool operationeel aandacht nodig heeft.
- Of je eerst naar TCA, incidents of research queue moet kijken.

### `artifacts/system/reports/trade_cost_analysis.txt`
Doel:
- Globale Trade Cost Analysis over alle opgeslagen MT5 fills.
- Meet spread/slippage/shortfall/cost/adverse fills.

Gebruik wanneer:
- Je wilt begrijpen hoeveel execution drag je live resultaat wegvreet.
- Je wilt weten of de brokeromgeving execution-technisch goed genoeg is.

Beslissingen:
- Of live edge nog overeind blijft na kosten.
- Of execution te slecht is voor bepaalde symbolen of uren.

### `artifacts/system/reports/tca_impact_report.txt`
Doel:
- Verbindt research-edge met live execution drag.
- Laat zien hoeveel edge overblijft na execution.

Gebruik wanneer:
- Je wilt weten of een strategie alleen op papier goed is of ook netto live overeind blijft.

Beslissingen:
- Welke agents netto nog tradable zijn.
- Welke agents fragile of untradeable worden na execution costs.

### `artifacts/system/reports/execution_adaptation_report.txt`
Doel:
- Laat zien welke live adaptation-acties zijn toegepast.
- Per strategie zie je promotie, demotie, severe demotion, guardrails en blokkades.

Gebruik wanneer:
- Je wilt weten wat de TCA adaptation layer feitelijk doet met live exposure.

Beslissingen:
- Of demoties logisch zijn.
- Of guardrails te streng of juist nuttig zijn.

### `artifacts/system/reports/live_improvement_activity_report.txt`
Doel:
- Historisch overzicht van adaptation- en research-activiteit.
- Telt hoe vaak en waar demoties, guardrails, research-triggers en auto-research runs gebeuren.

Gebruik wanneer:
- Je wilt zien of het systeem structureel vaak aan dezelfde symbolen of agents sleutelt.

Beslissingen:
- Of een probleem incidenteel of structureel is.
- Of research-activiteit goed verdeeld is of te veel op enkele symbolen valt.

## TCA en adaptation reports

### `artifacts/system/reports/trade_cost_analysis_<symbol>.txt`
Doel:
- TCA per broker symbol.

Gebruik wanneer:
- Je één prop-firm symbol of één markt apart wilt beoordelen.

Beslissingen:
- Of een specifiek symbool lokaal goed of slecht executeert.

### `artifacts/system/reports/tca_adaptation_impact_report.txt`
Doel:
- Before/after-inschatting van wat adaptation doet voor expected resultaat.

Gebruik wanneer:
- Je wilt zien of adaptation retained edge beschermt of te veel exposure afknijpt.

Beslissingen:
- Of adaptation-policy goed staat.
- Of je sneller wilt researchen in plaats van alleen de-risken.

### `artifacts/system/reports/live_research_queue.txt`
Doel:
- Tekstueel overzicht van welke agents research nodig hebben en waarom.

Gebruik wanneer:
- Je wilt zien welke live failures nu naar research vertaald worden.

Beslissingen:
- Welke research eerst prioriteit heeft.
- Of de autopsy-diagnose logisch is.

### `artifacts/system/reports/live_research_queue.json`
Doel:
- Machine-leesbare versie van de research queue.

Gebruik wanneer:
- Je later automation of dashboards wilt bouwen op research-triggers.

Beslissingen:
- Vooral voor automatisering, minder voor handmatige review.

## Portfolio en allocatie reports

### `artifacts/system/reports/portfolio_allocator.txt`
Doel:
- Huidige allocatie-uitkomst op systeemniveau.

Gebruik wanneer:
- Je wilt zien hoe kapitaal over symbolen/strategieën wordt verdeeld.

Beslissingen:
- Of allocatie logisch is ten opzichte van edge en risico.

### `artifacts/system/reports/portfolio_allocator_backtest.txt`
Doel:
- Backtest van de allocator-logica.

Gebruik wanneer:
- Je wilt beoordelen of je allocatieregels historisch zinvol zijn.

Beslissingen:
- Of allocator-regels aangepast moeten worden.

### `artifacts/system/reports/portfolio_allocator_fill_backtest.txt`
Doel:
- Fill-aware allocator backtest.
- Houdt rekening met execution in allocator-evaluatie.

Gebruik wanneer:
- Je allocator execution-aware wilt beoordelen.

Beslissingen:
- Of allocatie rekening moet houden met brokerkosten en fill quality.

### `artifacts/system/reports/portfolio_allocator_forward_backtest.txt`
Doel:
- Forward-style allocator evaluatie.

Gebruik wanneer:
- Je allocator minder in-sample en meer deployment-achtig wilt beoordelen.

Beslissingen:
- Of allocator robuust genoeg is voor live gebruik.

### `artifacts/system/reports/one_year_expectation.txt`
Doel:
- Verwachtingsbeeld op systeemniveau over een jaar.

Gebruik wanneer:
- Je een samenvattend rendement/risico-perspectief wilt.

Beslissingen:
- Of portfolio-ambitie realistisch is.

## Stock selector reports

### `artifacts/system/reports/stock_selector_today.txt`
### `artifacts/system/reports/stock_selector_today.csv`
Doel:
- Huidige selectie van aandelenkandidaten.

Gebruik wanneer:
- Je wilt weten welke aandelen vandaag/recent geselecteerd zijn.

Beslissingen:
- Welke aandelen verder onderzocht of uitgerold worden.

### `artifacts/system/reports/stock_selector_research_batch.txt`
Doel:
- Batch-overzicht van selector plus vervolg-research.

Gebruik wanneer:
- Je stock selection en research-output samen wilt beoordelen.

Beslissingen:
- Welke geselecteerde namen echt deploymentwaardig zijn.

## Symbol research reports

Per symbool in `artifacts/research/<symbol>/reports/`.

### `symbol_research.txt`
Doel:
- Hoofdrapport van de symbol research.

Gebruik wanneer:
- Je wilt begrijpen welke kandidaten en archetypes goed scoorden.

Beslissingen:
- Welke kandidaat in deployment of shortlist komt.

### `symbol_research.csv`
Doel:
- Tabel met kandidaten, metrics en ranking.

Gebruik wanneer:
- Je data-gedreven wilt filteren of sorteren.

Beslissingen:
- Vergelijking van kandidaten op metricniveau.

### `viability_autopsy.txt`
Doel:
- Analyse waarom een symbool of kandidaat niet goed genoeg is.

Gebruik wanneer:
- Research niks goeds oplevert of twijfelachtig is.

Beslissingen:
- Of een symbool opnieuw onderzocht moet worden.
- Of je een ander archetype nodig hebt.

### `regime_allocator_comparison.txt`
Doel:
- Vergelijking van regime- en allocator-gedrag binnen symbol research.

Gebruik wanneer:
- Je wilt begrijpen of regimefiltering of allocatie een doorslaggevende rol speelt.

Beslissingen:
- Of regime-aware deployment zinvol is voor dat symbool.

## Research plots

Per symbool in `artifacts/research/<symbol>/plots/`.

### `best_candidate_equity.png`
Doel:
- Equity curve van de beste kandidaat.

### `candidate_ranking.png`
Doel:
- Visueel overzicht van kandidaat-scores/ranking.

### `execution_set_equity.png`
Doel:
- Equity van de gekozen execution-set of live-geschikte kandidaten.

### `regimes.png`
Doel:
- Visuele samenvatting van regimes.

### `validation_test_scatter.png`
Doel:
- Vergelijking van validation en test gedrag.

Gebruik wanneer:
- Je visueel wilt beoordelen of research coherent en robuust oogt.

Beslissingen:
- Vooral review en sanity-check, minder directe runtime-beslissingen.

## Profielreports

Per profiel in `artifacts/profiles/<profile>/reports/`.

### `ai_summary.txt`
Doel:
- Samenvatting van AI/experiment-output voor het profiel.

### `next_experiment.txt`
Doel:
- Voorstel voor volgende experimentstap.

### `experiment_history.txt`
Doel:
- Historie van eerdere experimenten.

### `run_comparison.txt`
Doel:
- Vergelijking tussen meerdere runs.

### `agent_registry.txt`
Doel:
- Overzicht van geregistreerde agents.

### `agent_catalog.txt`
Doel:
- Catalogus van agenttypes en varianten.

### `shadow_setups.txt`
Doel:
- Analyse van shadow setups of niet-geactiveerde kansen.

### `signals_analysis.txt`
Doel:
- Analyse van signaalgedrag binnen het profiel.

Gebruik wanneer:
- Je profiel- of agentontwikkeling wilt beoordelen buiten de live loop om.

Beslissingen:
- Welke agents behouden, uitbreiden of vervangen.

## Live symbol artifacts

Per symbool in `artifacts/live/<symbol>/`.

### `execution_adaptation.json`
Doel:
- Laat de laatste adaptation-state en strategie-acties zien voor dat symbool.

### `research_trigger.json`
Doel:
- Laat de laatste research-trigger voor het symbool zien.

### `improvement_activity.jsonl`
Doel:
- Eventlog van demoties, guardrails, research-triggers en research-runs.

### `journals/`
Doel:
- Resultaten van live cycle-runs en acties.

### `incidents/`
Doel:
- Error- en incidentregistratie per symbool.

Gebruik wanneer:
- Je één symbool diep wilt debuggen.

Beslissingen:
- Root-cause analyse op symboolniveau.

## Aanbevolen leesvolgorde

Voor dagelijkse live review:
1. `live_health_report.txt`
2. `trade_cost_analysis.txt`
3. `tca_impact_report.txt`
4. `execution_adaptation_report.txt`
5. `live_improvement_activity_report.txt`
6. `live_research_queue.txt`

Voor research review van één symbool:
1. `artifacts/research/<symbol>/reports/symbol_research.txt`
2. `viability_autopsy.txt`
3. `symbol_research.csv`
4. plots in `artifacts/research/<symbol>/plots/`

Voor portfolio review:
1. `portfolio_allocator.txt`
2. `portfolio_allocator_fill_backtest.txt`
3. `portfolio_allocator_forward_backtest.txt`

## Praktische hoofdvraag per report

- `live_health_report`: draait live gezond?
- `trade_cost_analysis`: hoe duur is execution echt?
- `tca_impact_report`: hoeveel edge blijft netto over?
- `execution_adaptation_report`: wat doet de adaptation layer met exposure?
- `live_improvement_activity_report`: hoe vaak en waar grijpt het systeem in?
- `live_research_queue`: welke problemen worden nu naar research vertaald?
- `symbol_research`: welke kandidaten zijn inhoudelijk sterk?
- `viability_autopsy`: waarom werkt iets niet goed genoeg?
- `portfolio_allocator`: hoe wordt kapitaal verdeeld?
