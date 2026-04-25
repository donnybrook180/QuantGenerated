from __future__ import annotations

import copy


def run_symbol_research_orchestration(
    data_symbol: str,
    broker_symbol: str | None = None,
    *,
    candidate_name_prefixes: tuple[str, ...] | None = None,
    system_config_cls,
    resolve_symbol_request_fn,
    symbol_research_history_days_fn,
    configure_symbol_execution_fn,
    build_symbol_feature_variants_fn,
    is_stock_symbol_fn,
    default_variant_features_fn,
    candidate_specs_fn,
    with_variant_name_fn,
    symbol_slug_fn,
    exit_family_specs_fn,
    run_candidate_with_splits_fn,
    parameter_sweep_specs_fn,
    auto_improvement_specs_fn,
    second_pass_specs_fn,
    regime_improvement_specs_fn,
    autopsy_improvement_specs_fn,
    near_miss_optimizer_specs_fn,
    near_miss_local_optimizer_fn,
    combined_specs_fn,
    load_execution_features_for_variant_fn,
    annotate_combo_results_fn,
    export_results_fn,
    build_broker_data_sanity_summary_fn,
    meets_viability_fn,
    execution_candidate_row_from_result_fn,
    build_execution_policy_from_candidate_row_fn,
    build_execution_candidate_sets_fn,
    evaluate_execution_candidate_set_fn,
    execution_path_metrics_fn,
    regime_overlap_diagnostics_fn,
    execution_result_score_fn,
    tiered_fallback_candidates_fn,
    filter_live_approved_execution_candidates_fn,
    derive_symbol_status_fn,
    promotion_tier_for_row_fn,
    experiment_store_cls,
    export_viability_autopsy_fn,
    agent_descriptor_cls,
    build_symbol_deployment_fn,
    export_symbol_deployment_fn,
    plot_symbol_research_fn,
    specialist_regime_overlap_rejections_fn,
    is_crypto_symbol_fn,
    is_forex_symbol_fn,
):
    config = system_config_cls()
    resolved = resolve_symbol_request_fn(data_symbol, broker_symbol)
    config.symbol_research.broker_symbol = resolved.broker_symbol
    config.market_data.history_days = symbol_research_history_days_fn(config, resolved.profile_symbol)
    configure_symbol_execution_fn(config, resolved.profile_symbol, resolved.broker_symbol)
    feature_variants, data_source, effective_mode = build_symbol_feature_variants_fn(
        config,
        resolved.profile_symbol,
        resolved.data_symbol,
    )
    if is_stock_symbol_fn(resolved.profile_symbol) and config.symbol_research.mode == "auto" and effective_mode == "seed":
        full_config = copy.deepcopy(config)
        full_config.symbol_research.mode = "full"
        full_mode_variants, full_mode_source, full_mode = build_symbol_feature_variants_fn(
            full_config,
            resolved.profile_symbol,
            resolved.data_symbol,
        )
        if full_mode == "full" and any(features for features in full_mode_variants.values()):
            feature_variants = full_mode_variants
            data_source = full_mode_source
            effective_mode = full_mode
    default_features = default_variant_features_fn(feature_variants)
    if not default_features:
        raise RuntimeError(f"No usable feature variants were generated for {resolved.profile_symbol}.")
    singles = candidate_specs_fn(config, resolved.profile_symbol)
    if candidate_name_prefixes:
        singles = [
            spec
            for spec in singles
            if any(spec.name.startswith(prefix) for prefix in candidate_name_prefixes)
        ]
    symbol_slug = symbol_slug_fn(resolved.profile_symbol)
    results = []
    explored_entry_exit_specs = []
    for variant_label, features in feature_variants.items():
        if not features:
            continue
        variant_specs = [spec for base_spec in singles if (spec := with_variant_name_fn(base_spec, variant_label)) is not None]
        exit_family_specs = exit_family_specs_fn(config, resolved.profile_symbol, variant_specs)
        explored_entry_exit_specs.extend(variant_specs + exit_family_specs)
        results.extend(
            run_candidate_with_splits_fn(
                config,
                features,
                spec,
                "single" if "__exit_" not in spec.name else "entry_exit_family",
                f"{symbol_slug}_{spec.name}_{variant_label}_symbol_candidate",
            )
            for spec in (variant_specs + exit_family_specs)
        )
    sweep_specs = parameter_sweep_specs_fn(config, resolved.profile_symbol)
    if sweep_specs:
        for variant_label, features in feature_variants.items():
            if not features:
                continue
            results.extend(
                run_candidate_with_splits_fn(
                    config,
                    features,
                    materialized_spec,
                    "parameter_sweep",
                    f"{symbol_slug}_{materialized_spec.name}_{variant_label}_symbol_candidate",
                )
                for base_spec in sweep_specs
                if (materialized_spec := with_variant_name_fn(base_spec, variant_label)) is not None
            )
    improvement_specs = auto_improvement_specs_fn(config, resolved.profile_symbol, results)
    if improvement_specs:
        results.extend(
            run_candidate_with_splits_fn(
                config,
                default_features,
                spec,
                "auto_improved",
                f"{symbol_slug}_{spec.name}_symbol_candidate",
            )
            for spec in improvement_specs
        )
    second_pass_specs = second_pass_specs_fn(config, resolved.profile_symbol, results)
    if second_pass_specs:
        results.extend(
            run_candidate_with_splits_fn(
                config,
                default_features,
                spec,
                "auto_second_pass",
                f"{symbol_slug}_{spec.name}_symbol_candidate",
            )
            for spec in second_pass_specs
        )
    regime_specs = regime_improvement_specs_fn(
        explored_entry_exit_specs + sweep_specs + improvement_specs + second_pass_specs,
        results,
    )
    if regime_specs:
        results.extend(
            run_candidate_with_splits_fn(
                config,
                load_execution_features_for_variant_fn(
                    config,
                    resolved.profile_symbol,
                    resolved.data_symbol,
                    spec.variant_label,
                    spec.regime_filter_label,
                    spec.cross_filter_label,
                )[0],
                spec,
                "regime_improved",
                f"{symbol_slug}_{spec.name}_symbol_candidate",
            )
            for spec in regime_specs
        )
    autopsy_specs = autopsy_improvement_specs_fn(
        config,
        resolved.profile_symbol,
        explored_entry_exit_specs + sweep_specs + improvement_specs + second_pass_specs + regime_specs,
        results,
    )
    if autopsy_specs:
        results.extend(
            run_candidate_with_splits_fn(
                config,
                load_execution_features_for_variant_fn(
                    config,
                    resolved.profile_symbol,
                    resolved.data_symbol,
                    spec.variant_label,
                    spec.regime_filter_label,
                    spec.cross_filter_label,
                )[0],
                spec,
                "autopsy_improved",
                f"{symbol_slug}_{spec.name}_symbol_candidate",
            )
            for spec in autopsy_specs
        )
    near_miss_specs = near_miss_optimizer_specs_fn(
        resolved.profile_symbol,
        explored_entry_exit_specs + sweep_specs + improvement_specs + second_pass_specs + regime_specs + autopsy_specs,
        results,
    )
    if near_miss_specs:
        results.extend(
            run_candidate_with_splits_fn(
                config,
                load_execution_features_for_variant_fn(
                    config,
                    resolved.profile_symbol,
                    resolved.data_symbol,
                    spec.variant_label,
                    spec.regime_filter_label,
                    spec.cross_filter_label,
                )[0],
                spec,
                "near_miss_optimized",
                f"{symbol_slug}_{spec.name}_symbol_candidate",
            )
            for spec in near_miss_specs
        )
    local_optimized_specs, local_optimized_results = near_miss_local_optimizer_fn(
        config,
        resolved.profile_symbol,
        resolved.data_symbol,
        explored_entry_exit_specs + sweep_specs + improvement_specs + second_pass_specs + regime_specs + autopsy_specs + near_miss_specs,
        results,
        symbol_slug,
    )
    results.extend(local_optimized_results)
    combos = combined_specs_fn(
        config,
        explored_entry_exit_specs
        + sweep_specs
        + improvement_specs
        + second_pass_specs
        + regime_specs
        + autopsy_specs
        + near_miss_specs
        + local_optimized_specs,
        results,
    )
    results.extend(
        run_candidate_with_splits_fn(
            config,
            default_features,
            spec,
            "combined",
            f"{symbol_slug}_{spec.name}_symbol_candidate",
        )
        for spec in combos
    )
    spec_lookup = {
        spec.name: spec
        for spec in (
            explored_entry_exit_specs
            + sweep_specs
            + improvement_specs
            + second_pass_specs
            + regime_specs
            + autopsy_specs
            + near_miss_specs
            + local_optimized_specs
            + combos
        )
    }
    annotate_combo_results_fn(results)
    broker_data_summary = build_broker_data_sanity_summary_fn(
        config,
        resolved.profile_symbol,
        resolved.data_symbol,
        resolved.broker_symbol,
        data_source,
        default_features,
    )
    csv_path, txt_path = export_results_fn(
        resolved.profile_symbol,
        resolved.broker_symbol,
        data_source,
        results,
        broker_data_summary=broker_data_summary,
    )
    ranked = sorted(
        results,
        key=lambda item: (
            meets_viability_fn(item, resolved.profile_symbol),
            item.regime_stability_score,
            -item.regime_loss_ratio,
            item.combo_outperformance_score,
            item.walk_forward_pass_rate_pct,
            item.walk_forward_avg_test_pnl,
            item.walk_forward_avg_validation_pnl,
            item.test_pnl,
            item.validation_pnl,
            item.test_profit_factor,
            item.test_closed_trades,
        ),
        reverse=True,
    )
    viable_ranked = [row for row in ranked if meets_viability_fn(row, resolved.profile_symbol)]
    best = viable_ranked[0] if viable_ranked else None
    recommended = [row.name for row in viable_ranked[:3]]
    profile_name = f"symbol::{symbol_slug_fn(resolved.profile_symbol)}"

    execution_candidate_rows = []
    for row in results:
        candidate_row = execution_candidate_row_from_result_fn(resolved.profile_symbol, row)
        candidate_row["recommended"] = row.name in recommended
        candidate_row["agents"] = copy.deepcopy(spec_lookup[row.name].agents) if row.name in spec_lookup else None
        candidate_row.update(build_execution_policy_from_candidate_row_fn(candidate_row))
        execution_candidate_rows.append(candidate_row)
    default_limit = 3 if is_forex_symbol_fn(resolved.profile_symbol) or is_crypto_symbol_fn(resolved.profile_symbol) else 2
    fallback_limit = max(1, config.symbol_research.max_live_candidates_per_symbol or default_limit)
    candidate_sets = build_execution_candidate_sets_fn(
        execution_candidate_rows,
        resolved.profile_symbol,
        max_candidates=fallback_limit,
    )
    standard_candidates = next((candidate_set for label, candidate_set in candidate_sets if label == "standard"), [])
    sparse_candidates = next((candidate_set for label, candidate_set in candidate_sets if label == "sparse"), [])
    selected_execution_candidates = []
    execution_set_id = None
    execution_validation_summary = "not_run"
    execution_rejection_reason = ""
    selection_diagnostics = f"standard={len(standard_candidates)} sparse={len(sparse_candidates)}"
    generated_combo_count = sum(1 for label, _ in candidate_sets if label.startswith("combo_"))
    if generated_combo_count:
        selection_diagnostics += f" combos={generated_combo_count}"
    best_execution_choice = None
    best_reduced_risk_choice = None
    for selection_kind, candidate_set in candidate_sets:
        execution_validation_result, execution_validation_source, execution_variant = evaluate_execution_candidate_set_fn(
            config,
            resolved.profile_symbol,
            resolved.data_symbol,
            candidate_set,
        )
        path_metrics = execution_path_metrics_fn(execution_validation_result)
        max_regime_overlap, overlap_diagnostics = regime_overlap_diagnostics_fn(candidate_set)
        sparse_execution = any(bool(row.get("sparse_strategy")) for row in candidate_set)
        min_execution_closed_trades = 3 if sparse_execution else 2
        accepted = (
            execution_validation_result.realized_pnl > 0.0
            and execution_validation_result.profit_factor >= 1.0
            and len(execution_validation_result.closed_trades) >= min_execution_closed_trades
        )
        normal_quality = (
            path_metrics["equity_quality_score"] >= 0.35
            and path_metrics["time_under_water_pct"] <= 75.0
            and path_metrics["best_trade_share_pct"] <= 75.0
        )
        reduced_risk_acceptable = (
            execution_validation_result.realized_pnl > 0.0
            and execution_validation_result.profit_factor >= 1.0
            and len(execution_validation_result.closed_trades) >= min_execution_closed_trades
            and path_metrics["equity_quality_score"] >= 0.18
            and path_metrics["time_under_water_pct"] <= 90.0
            and path_metrics["best_trade_share_pct"] <= 90.0
        )
        summary = (
            f"selection={selection_kind} variant={execution_variant} data_source={execution_validation_source} "
            f"pnl={execution_validation_result.realized_pnl:.2f} "
            f"pf={execution_validation_result.profit_factor:.2f} "
            f"closed={len(execution_validation_result.closed_trades)} "
            f"quality={path_metrics['equity_quality_score']:.2f} "
            f"underwater={path_metrics['time_under_water_pct']:.1f}% "
            f"max_regime_overlap={max_regime_overlap:.2f}"
        )
        if overlap_diagnostics:
            summary += " overlaps=" + "; ".join(overlap_diagnostics)
        if accepted and normal_quality:
            summary += " -> accepted"
            score = execution_result_score_fn(execution_validation_result, candidate_set)
            if best_execution_choice is None or score > best_execution_choice[0]:
                best_execution_choice = (score, candidate_set, summary)
        elif reduced_risk_acceptable:
            summary += " -> accepted_with_reduced_risk"
            score = execution_result_score_fn(execution_validation_result, candidate_set)
            if best_reduced_risk_choice is None or score > best_reduced_risk_choice[0]:
                best_reduced_risk_choice = (score, candidate_set, summary)
        elif best_execution_choice is None:
            execution_validation_summary = summary + " -> rejected"
            rejection_reasons = []
            if execution_validation_result.realized_pnl <= 0.0:
                rejection_reasons.append(f"execution pnl <= 0 ({execution_validation_result.realized_pnl:.2f})")
            if execution_validation_result.profit_factor < 1.0:
                rejection_reasons.append(f"execution PF < 1.0 ({execution_validation_result.profit_factor:.2f})")
            if len(execution_validation_result.closed_trades) < min_execution_closed_trades:
                rejection_reasons.append(
                    f"execution closed trades too low ({len(execution_validation_result.closed_trades)} < {min_execution_closed_trades})"
                )
            if path_metrics["equity_quality_score"] < 0.2:
                rejection_reasons.append(f"execution quality too low ({path_metrics['equity_quality_score']:.2f})")
            execution_rejection_reason = ", ".join(rejection_reasons) if rejection_reasons else "execution set rejected by validation"
    if best_execution_choice is not None:
        _, selected_execution_candidates, execution_validation_summary = best_execution_choice
    elif best_reduced_risk_choice is not None:
        _, selected_execution_candidates, execution_validation_summary = best_reduced_risk_choice
    else:
        tiered_fallback = tiered_fallback_candidates_fn(
            execution_candidate_rows,
            resolved.profile_symbol,
            max_candidates=fallback_limit,
        )
        selection_diagnostics += f" tiered_fallback={len(tiered_fallback)}"
        if tiered_fallback:
            selected_execution_candidates = tiered_fallback
            core_count = sum(1 for row in selected_execution_candidates if str(row.get("promotion_tier", "")) == "core")
            specialist_count = sum(1 for row in selected_execution_candidates if str(row.get("promotion_tier", "")) == "specialist")
            execution_validation_summary = (
                f"selection=tiered_fallback core={core_count} specialist={specialist_count} "
                f"-> accepted_with_reduced_risk"
            )
    specialist_live_rejections = []
    if selected_execution_candidates:
        selected_execution_candidates, specialist_live_rejections = filter_live_approved_execution_candidates_fn(selected_execution_candidates)
        if specialist_live_rejections:
            execution_validation_summary += " specialist_live_gate=" + "; ".join(specialist_live_rejections)
    recommended = [str(row["candidate_name"]) for row in selected_execution_candidates]
    symbol_status = derive_symbol_status_fn(selected_execution_candidates, execution_validation_summary)
    tier_counts = {"core": 0, "specialist": 0, "reject": 0}
    for row in results:
        tier = promotion_tier_for_row_fn(row, resolved.profile_symbol)
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    store = experiment_store_cls(config.ai.experiment_database_path)
    run_id = store.record_symbol_research_run(
        profile_name=profile_name,
        data_symbol=resolved.data_symbol,
        broker_symbol=resolved.broker_symbol,
        data_source=data_source,
        candidates=results,
        recommended_names=recommended,
    )
    if selected_execution_candidates:
        execution_set_id = store.record_symbol_execution_set(
            profile_name=profile_name,
            symbol_research_run_id=run_id,
            selected_candidates=selected_execution_candidates,
        )
    autopsy_path = export_viability_autopsy_fn(resolved.profile_symbol, results, execution_validation_summary)
    descriptors = [
        agent_descriptor_cls(
            profile_name=profile_name,
            agent_name=row.name,
            lifecycle_scope="active",
            class_name=row.name,
            code_path=row.code_path,
            description=row.description,
            is_active=row.name in recommended,
            variant_label=row.variant_label,
            timeframe_label=row.timeframe_label,
            session_label=row.session_label,
        )
        for row in results
    ]
    store.promote_symbol_research_candidates(
        profile_name=profile_name,
        data_symbol=resolved.data_symbol,
        broker_symbol=resolved.broker_symbol,
        descriptors=descriptors,
        candidates=results,
        recommended_names=recommended,
        symbol_research_run_id=run_id,
    )
    deployment = build_symbol_deployment_fn(
        profile_name=profile_name,
        symbol=resolved.profile_symbol,
        data_symbol=resolved.data_symbol,
        broker_symbol=resolved.broker_symbol,
        research_run_id=run_id,
        execution_set_id=execution_set_id,
        execution_validation_summary=execution_validation_summary,
        symbol_status=symbol_status,
        selected_candidates=selected_execution_candidates,
        venue_key=str(config.mt5.prop_broker),
    )
    deployment_path = export_symbol_deployment_fn(deployment)
    selected_execution_results = [row for row in results if row.name in {str(item["candidate_name"]) for item in selected_execution_candidates}]
    plot_paths = plot_symbol_research_fn(
        resolved.profile_symbol,
        results,
        best_row=best,
        execution_rows=selected_execution_results,
    )
    lines = [
        f"Requested symbol: {resolved.requested_symbol}",
        f"Symbol: {resolved.profile_symbol}",
        f"Data symbol: {resolved.data_symbol}",
        f"Broker symbol: {resolved.broker_symbol}",
        f"Catalog profile: {profile_name}",
        f"Data source: {data_source}",
        f"Broker data source: {broker_data_summary.get('broker_data_source', data_source)}",
        f"Candidates tested: {len(results)}",
        f"Research CSV: {csv_path}",
        f"Research report: {txt_path}",
        f"Viability autopsy: {autopsy_path}",
    ]
    if plot_paths:
        lines.append("Plots: " + ", ".join(str(path) for path in plot_paths))
    if best is not None:
        lines.extend(
            [
                f"Best candidate: {best.name}",
                f"Best PnL: {best.realized_pnl:.2f}",
                f"Best profit factor: {best.profit_factor:.2f}",
                f"Best closed trades: {best.closed_trades}",
                f"Validation: pnl={best.validation_pnl:.2f} pf={best.validation_profit_factor:.2f} closed={best.validation_closed_trades}",
                f"Test: pnl={best.test_pnl:.2f} pf={best.test_profit_factor:.2f} closed={best.test_closed_trades}",
            ]
        )
    else:
        lines.append("Best candidate: none")
        lines.append(
            "No viable candidate met the symbol-specific viability rules "
            "(validation/test robustness, walk-forward robustness, and execution consistency)."
        )
    lines.append("Recommended active agents: " + (", ".join(recommended) if recommended else "none"))
    lines.append(f"Symbol status: {symbol_status}")
    lines.append(f"Tier counts: core={tier_counts['core']} specialist={tier_counts['specialist']} reject={tier_counts['reject']}")
    lines.append(
        "Execution set: "
        + (", ".join(str(row["candidate_name"]) for row in selected_execution_candidates) if selected_execution_candidates else "none")
    )
    if not selected_execution_candidates and tier_counts["core"] > 0:
        lines.append(
            "Execution set note: core candidates existed, but no candidate set survived symbol-level execution selection "
            "or execution validation."
        )
        lines.append(f"Execution selection diagnostics: {selection_diagnostics}")
        if execution_rejection_reason:
            lines.append(f"Execution rejection reason: {execution_rejection_reason}")
    if selected_execution_candidates:
        selected_max_overlap, selected_overlap_diagnostics = regime_overlap_diagnostics_fn(selected_execution_candidates)
        specialist_overlap_rejections = specialist_regime_overlap_rejections_fn(execution_candidate_rows, selected_execution_candidates)
        lines.append(
            "Execution tiers: "
            + ", ".join(f"{row['candidate_name']}[{row.get('promotion_tier', 'core')}]" for row in selected_execution_candidates)
        )
        lines.append(f"Execution regime overlap max: {selected_max_overlap:.2f}")
        lines.append(
            "Execution regime overlap detail: "
            + ("; ".join(selected_overlap_diagnostics) if selected_overlap_diagnostics else "none")
        )
        lines.append(
            "Execution regime overlap rejections: "
            + ("; ".join(specialist_overlap_rejections) if specialist_overlap_rejections else "none")
        )
        lines.append(
            "Execution specialist live rejections: "
            + ("; ".join(specialist_live_rejections) if specialist_live_rejections else "none")
        )
    elif specialist_live_rejections:
        lines.append("Execution specialist live rejections: " + "; ".join(specialist_live_rejections))
    lines.append(f"Execution set id: {execution_set_id if execution_set_id is not None else 'none'}")
    lines.append(f"Execution validation: {execution_validation_summary}")
    lines.append(f"Live deployment: {deployment_path}")
    lines.append(f"Research history days: {config.market_data.history_days}")
    lines.append(f"Research mode: {effective_mode}")
    if config.symbol_research.mode == "auto":
        lines.append(
            "Research mode selection: "
            + (
                "full because all required timeframe caches were found."
                if effective_mode == "full"
                else "seed because one or more full-research timeframe caches were missing."
            )
        )
    if resolved.profile_symbol.upper() == "US500":
        lines.append("Split ratio: train 60% / validation 20% / test 20% ; walk-forward windows use 45% / 15% / 15%")
    elif is_crypto_symbol_fn(resolved.profile_symbol):
        lines.append("Split ratio: train 60% / validation 20% / test 20% ; walk-forward windows use 45% / 25% / 20%")
    elif is_stock_symbol_fn(resolved.profile_symbol):
        lines.append("Split ratio: train 50% / validation 25% / test 25% ; walk-forward windows use 42% / 22% / 22%")
    else:
        lines.append("Split ratio: train 60% / validation 20% / test 20% ; walk-forward windows use 50% / 20% / 20%")
    return lines
