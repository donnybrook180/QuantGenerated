# Prop Firm Launch Checklist

Gebruik deze checklist voordat je een nieuwe prop-firm server live zet.

Voorbeeld:
- FTMO server
- FundedNext server
- Top One Trader server

## 1. Runtime-isolatie

Check:
- aparte server of aparte volledig geïsoleerde runtime
- eigen `.env`
- eigen MT5 terminal/account
- eigen `AI_EXPERIMENT_DB_PATH`
- geen gedeelde live database met andere prop firms

Klaar als:
- deze server alleen lokale data van deze prop firm zal opbouwen

## 2. Broker en account

Check:
- juiste MT5 login
- juiste broker server
- account opent correct
- symbolen zijn zichtbaar in MT5
- market watch bevat de benodigde live symbolen

Klaar als:
- je handmatig kunt bevestigen dat de terminal met het juiste account verbonden is

## 3. Symbol mapping

Check:
- deployment symbol klopt met broker symbol
- voorbeelden:
  - `XAUUSD` -> juiste broker variant
  - `US100` -> `US100.cash` als broker dat gebruikt
  - `JP225` -> juiste cash/index notatie

Klaar als:
- de symbols in `artifacts/deploy/<symbol>/live.json` overeenkomen met de MT5 broker symbols

## 4. Database en artifacts

Check:
- databasebestand bestaat of wordt op de juiste plek aangemaakt
- `artifacts/` wordt op deze server lokaal opgebouwd
- er zijn geen oude artifacts van een andere prop firm vermengd

Klaar als:
- reports en live logs op deze server alleen lokale runtime-data tonen

## 5. Deployments

Check:
- `artifacts/deploy/<symbol>/live.json` bestaat voor alle gewenste symbolen
- er staat minstens 1 live strategie per symbool in
- deployment status is logisch

Klaar als:
- je symbols hebt die technisch live kunnen draaien

## 6. Research basis

Check:
- per live symbool bestaat research output in `artifacts/research/<symbol>/reports/`
- minimaal:
  - `symbol_research.txt`
  - `symbol_research.csv`
  - `viability_autopsy.txt`

Klaar als:
- live deployment is gebaseerd op echte research artifacts

## 7. Live loop

Check:
- `main_live_loop.py` start zonder error
- geen directe MT5 exceptions
- journals worden aangemaakt

Klaar als:
- de live loop minstens 1 volledige cycle succesvol draait

## 8. Reporting

Check dat deze reports gegenereerd worden:
- `artifacts/system/reports/live_health_report.txt`
- `artifacts/system/reports/trade_cost_analysis.txt`
- `artifacts/system/reports/tca_impact_report.txt`
- `artifacts/system/reports/execution_adaptation_report.txt`
- `artifacts/system/reports/live_improvement_activity_report.txt`
- `artifacts/system/reports/live_research_queue.txt`

Klaar als:
- alle kernreports bestaan, ook als sommige nog `none` of `insufficient_data` tonen

## 9. Guardrails

Check:
- `LIVE_GUARDRAIL_MIN_ACTIVE_STRATEGIES_PER_SYMBOL`
- `LIVE_GUARDRAIL_MAX_SEVERE_DEMOTIONS_PER_SYMBOL`
- `LIVE_GUARDRAIL_MIN_FILLS_TO_BLOCK`

Klaar als:
- autopsy/adaptation niet direct alle live exposure kan wegdrukken

## 10. Auto-research policy

Check:
- of `LIVE_AUTO_RESEARCH_ENABLED` aan of uit moet staan
- indien aan:
  - `LIVE_AUTO_RESEARCH_MAX_RUNS`
  - `LIVE_AUTO_RESEARCH_TIMEOUT_SECONDS`

Klaar als:
- je bewust hebt gekozen of deze server alleen research queue bouwt of ook automatisch research draait

## 11. TCA readiness

Check:
- MT5 fills komen in `mt5_fill_events`
- broker costs kunnen worden gelezen uit deal history
- TCA report kan draaien

Klaar als:
- eerste fills straks direct bruikbaar zijn voor TCA

## 12. Eerste live doel

Bepaal vooraf:
- wil je vooral fills verzamelen?
- wil je echte edge testen?
- wil je broker execution karakteriseren?

Aanbevolen eerste doel:
- eerst execution-data opbouwen
- daarna pas adaptation en research triggers serieus interpreteren

## Go / No-Go

### Go als:
- runtime gescheiden is
- MT5 account correct verbonden is
- deployments bestaan
- live loop draait
- kernreports worden geschreven

### No-Go als:
- verkeerde broker/account is gekoppeld
- database of artifacts gedeeld worden met andere prop firms
- live loop incidenten blijft produceren
- deployments ontbreken of symbol mapping niet klopt

## Eerste 24 uur na launch

Na launch meteen volgen:
1. `live_health_report.txt`
2. `trade_cost_analysis.txt`
3. `execution_adaptation_report.txt`
4. `live_improvement_activity_report.txt`

Doel:
- bevestigen dat de server echt lokaal leert van deze prop firm
