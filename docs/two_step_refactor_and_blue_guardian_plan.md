# Two-Step Refactor And Blue Guardian Plan

Date: 2026-04-25

## Intent

The next phase of this project will be executed in two clearly separated steps:

1. Refactor the project into a cleaner, easier-to-read, easier-to-maintain structure with explicit room for independent prop-firm treatment.
2. Implement the Blue Guardian research improvement plan on top of that new structure.

This separation is intentional.

The current codebase is too structurally messy to safely layer more venue-specific research logic on top of it. If the architecture remains unclear, Blue Guardian-specific improvements will increase complexity faster than they improve reliability.

## Why This New Plan Exists

Current pain points:

- It is not clear where to find things.
- A few files and classes are too large.
- Research, live runtime, evaluation, deployment, and venue-specific concerns are too intertwined.
- Prop-firm handling exists, but not yet as a clean first-class boundary.
- Adding Blue Guardian-specific realism now would make the project harder to reason about unless the structure is cleaned first.

So the correct order is:

- first architecture,
- then venue-specific research sophistication.

## Step 1: Refactor For Readability, Maintainability, And Prop-Firm Separation

### Step 1 Goal

Turn the current project into a codebase where:

- module boundaries are obvious,
- large files are decomposed,
- research and live logic are easier to follow,
- prop firms can be handled independently without hidden coupling,
- and future venue-specific improvements can be implemented without creating another monolith.

### Step 1 Success Criteria

Step 1 is complete only when:

- `symbol_research.py` is no longer a monolith,
- oversized live/runtime files are reduced in responsibility,
- prop-firm-specific data and configuration boundaries are explicit,
- project navigation becomes predictable,
- and adding a new prop-firm-specific rule no longer requires touching unrelated modules.

### Step 1 Architecture Direction

The codebase should move toward clear subsystem ownership:

```text
quant_system/
  core/
  research/
  interpreter/
  evaluation/
  optimization/
  live/
  venues/
  agents/
  tools/
```

### New First-Class Boundary: `venues/`

Add a dedicated venue layer so prop firms are no longer treated as scattered flags.

Target direction:

```text
quant_system/
  venues/
    __init__.py
    models.py
    registry.py
    generic/
      __init__.py
      profile.py
      rules.py
      costs.py
      symbols.py
    blue_guardian/
      __init__.py
      profile.py
      rules.py
      costs.py
      symbols.py
      research.py
    ftmo/
      __init__.py
      profile.py
      rules.py
      costs.py
      symbols.py
    fundednext/
      __init__.py
      profile.py
      rules.py
      costs.py
      symbols.py
```

This does not mean implementing all venue details immediately.
It means creating a stable home for:

- venue identity,
- venue cost assumptions,
- venue restrictions,
- venue symbol mapping,
- venue data quality policies,
- and venue-specific research extensions.

### Step 1 Main Workstreams

#### 1. Split monoliths

Primary targets:

- [quant_system/symbol_research.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/symbol_research.py)
- [quant_system/live/runtime.py](C:/Users/liset/PycharmProjects/QuantGenerated/quant_system/live/runtime.py)
- large agent modules
- any entrypoint that mixes orchestration with business logic

Target outcome:

- smaller files with one main responsibility,
- less hidden coupling,
- easier testing and targeted edits.

#### 2. Clarify project navigation

Make it obvious where to find:

- symbol research logic,
- candidate scoring,
- viability rules,
- execution-set selection,
- deployment export,
- live runtime behavior,
- and prop-firm rules.

This should be reflected in:

- module names,
- file placement,
- and docs.

#### 3. Separate orchestration from domain logic

Entry scripts and app runners should orchestrate only.
They should not contain deep logic for:

- scoring,
- rule enforcement,
- research thresholds,
- or venue-specific conditionals.

#### 4. Create explicit prop-firm independence

Prop firms need isolated treatment in:

- configuration,
- storage,
- cost profiles,
- research assumptions,
- live reports,
- and execution adaptation.

That means:

- venue-specific DB paths are standard, not ad hoc
- venue profile resolution is explicit
- venue-specific rule logic is not buried in generic runtime code

#### 5. Reduce class width

Some classes currently do too much.

Refactor target:

- classes should own one layer of responsibility
- wide “god objects” should become smaller coordinators over narrower services

### Step 1 Deliverables

At the end of Step 1, the repo should contain:

- a cleaner research module structure,
- a clearer live/runtime module structure,
- a new `venues/` subsystem,
- reduced class/file size in key hotspots,
- updated docs that explain where major responsibilities live.

### Step 1 Recommended Execution Order

1. Create `venues/` foundation and move broker/prop abstractions there.
2. Split `symbol_research.py` into research submodules.
3. Split oversized runtime/live modules into narrower services.
4. Refactor agent modules that are too broad.
5. Update docs and report maps to match the new structure.

## Step 2: Implement The Blue Guardian Research Improvement Plan

### Step 2 Goal

Once the architecture is cleaned and venue handling is explicit, improve research so Blue Guardian-specific conclusions are based on:

- Blue Guardian MT5 broker data,
- Blue Guardian execution reality,
- funding / swap drag,
- slippage / spread stress,
- regime fit,
- and Blue Guardian rule compatibility.

### Step 2 Depends On Step 1

This step should not start as scattered patchwork inside the current monoliths.

It should be implemented on top of:

- the new `venues/blue_guardian/` boundary,
- the refactored research pipeline,
- and the clearer viability / deployment / live interfaces from Step 1.

### Step 2 Success Criteria

Step 2 is complete only when:

- Blue Guardian is treated as a first-class venue in research,
- research clearly separates signal edge from prop-firm viability,
- swap/funding drag is measured and used,
- slippage/spread stress is included before live promotion,
- interpreter-fit and venue-fit are visible,
- and deployment decisions explain why a candidate passes or fails for Blue Guardian specifically.

### Step 2 Main Workstreams

#### 1. Broker-data-specific research

Use Blue Guardian MT5 as the authoritative venue feed for Blue Guardian research.

#### 2. Separate signal quality from prop viability

Introduce distinct scoring/reporting for:

- raw strategy merit
- Blue Guardian deployability

#### 3. Funding / swap drag integration

Evaluate whether edge survives realistic carry assumptions.

#### 4. Slippage / spread stress testing

Promote only candidates that remain viable under realistic execution degradation.

#### 5. Rule compatibility

Avoid promoting candidates that clash with Blue Guardian restrictions or practical live constraints.

#### 6. Interpreter-fit integration

Research winners should align better with what the live interpreter is likely to permit.

### Step 2 Deliverables

At the end of Step 2, the project should contain:

- Blue Guardian-specific research outputs,
- Blue Guardian-specific viability logic,
- venue-aware deployment decisions,
- and improved symbol reruns for the current live universe.

## Combined Timeline Logic

### What happens first

Refactor first.

Reason:

- if we improve Blue Guardian research on top of unclear architecture, the venue logic will become another layer of hidden coupling.

### What happens second

Blue Guardian improvement second.

Reason:

- once venue boundaries and research boundaries are clean, the Blue Guardian logic becomes modular and maintainable instead of bespoke and fragile.

## Concrete Program Of Work

### Phase A: Structural Refactor Program

1. Introduce `quant_system/venues/`
2. Move prop-firm profile logic into venue modules
3. Split `symbol_research.py`
4. Split oversized live/runtime code
5. Reduce oversized agent modules
6. Update docs and navigation

### Phase B: Blue Guardian Improvement Program

1. Implement Blue Guardian venue profile behavior
2. Add broker data sanity outputs
3. Add signal vs viability separation
4. Add swap drag estimation
5. Add slippage / spread stress layers
6. Add Blue Guardian rule-fit scoring
7. Add interpreter-fit scoring
8. Rerun priority symbols

## Recommended First Technical Milestone

The first technical milestone should be:

- create the `venues/` subsystem
- and refactor research into smaller modules before any new Blue Guardian-specific scoring logic is added

That is the highest-leverage move because it improves:

- readability,
- maintainability,
- testing,
- and future venue-specific extensibility.

## Definition Of Done

This two-step plan is done when:

- the project is clearly structured and easier to maintain,
- prop firms are independently represented in architecture,
- Blue Guardian research logic is venue-aware and robust,
- and live promotion decisions are based on venue-specific evidence rather than mixed assumptions.

## Immediate Next Action

Start Step 1 by producing a file-by-file refactor execution plan with:

- target module moves,
- target class splits,
- new `venues/` interfaces,
- and a safe migration order.
