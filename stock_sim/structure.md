# 项目目录结构(精简版)

生成时间：2025-09-14 15:38:14
说明：以下目录树对部分大型或临时目录仅显示到顶层，不展开其子目录：
 - .spec-workflow, .venv（外部库环境）
 - __pycache__, .pytest_cache（临时/编译缓存）
 - logs, stock_sim.egg-info（日志/打包元数据）

---

根目录：

|-- .idea
|   |-- inspectionProfiles
|   |   |-- profiles_settings.xml
|   |   \-- Project_Default.xml
|   |-- .gitignore
|   |-- .name
|   |-- copilotDiffState.xml
|   |-- misc.xml
|   |-- modules.xml
|   |-- stock_sim.iml
|   \-- workspace.xml
|-- .pytest_cache
|-- .spec-workflow
|-- .venv
|-- __pycache__
|-- agents
|   |-- __pycache__
|   |-- __init__.py
|   |-- multi_internal_strategies.py
|   |-- multi_strategy_retail.py
|   |-- ppo_portfolio_agent.py
|   |-- retail_client.py
|   |-- retail_strategy.py
|   \-- retail_trader.py
|-- app
|   |-- __pycache__
|   |-- bridge
|   |   \-- settings_clock.py
|   |-- controllers
|   |   |-- __pycache__
|   |   |-- __init__.py
|   |   |-- account_controller.py
|   |   |-- agent_config_controller.py
|   |   |-- agent_controller.py
|   |   |-- agent_creation_controller.py
|   |   |-- clock_controller.py
|   |   |-- leaderboard_controller.py
|   |   |-- market_controller.py
|   |   \-- settings_controller.py
|   |-- core_dto
|   |   |-- __pycache__
|   |   |-- __init__.py
|   |   |-- account.py
|   |   |-- agent.py
|   |   |-- clock.py
|   |   |-- leaderboard.py
|   |   |-- snapshot.py
|   |   |-- trade.py
|   |   \-- versioning.py
|   |-- i18n
|   |   |-- __pycache__
|   |   |-- __init__.py
|   |   |-- en_US.json
|   |   |-- loader.py
|   |   \-- zh_CN.json
|   |-- indicators
|   |   |-- __pycache__
|   |   |-- __init__.py
|   |   |-- executor.py
|   |   |-- ma.py
|   |   |-- macd.py
|   |   |-- registry.py
|   |   \-- rsi.py
|   |-- panels
|   |   |-- __pycache__
|   |   |-- account
|   |   |   |-- __pycache__
|   |   |   |-- __init__.py
|   |   |   \-- panel.py
|   |   |-- agent_config
|   |   |   |-- __pycache__
|   |   |   \-- panel.py
|   |   |-- agent_creation
|   |   |   |-- __pycache__
|   |   |   \-- dialog.py
|   |   |-- agents
|   |   |   |-- __pycache__
|   |   |   |-- __init__.py
|   |   |   \-- panel.py
|   |   |-- clock
|   |   |   |-- __pycache__
|   |   |   |-- __init__.py
|   |   |   \-- panel.py
|   |   |-- leaderboard
|   |   |   |-- __pycache__
|   |   |   |-- __init__.py
|   |   |   \-- panel.py
|   |   |-- market
|   |   |   |-- __pycache__
|   |   |   |-- __init__.py
|   |   |   \-- panel.py
|   |   |-- settings
|   |   |   |-- __pycache__
|   |   |   |-- __init__.py
|   |   |   \-- panel.py
|   |   |-- shared
|   |   |   |-- __pycache__
|   |   |   |-- __init__.py
|   |   |   |-- export_button.py
|   |   |   |-- notification_widget.py
|   |   |   \-- notifications.py
|   |   |-- __init__.py
|   |   |-- base_logic.py
|   |   |-- notifications_panel.py
|   |   \-- registry.py
|   |-- security
|   |   |-- __pycache__
|   |   |-- __init__.py
|   |   |-- ast_rules.py
|   |   |-- rate_limiter.py
|   |   \-- script_validator.py
|   |-- services
|   |   |-- __pycache__
|   |   |-- account_service.py
|   |   |-- agent_service.py
|   |   |-- bars_cache.py
|   |   |-- clock_service.py
|   |   |-- export_service.py
|   |   |-- leaderboard_service.py
|   |   |-- log_stream_service.py
|   |   |-- market_data_service.py
|   |   |-- redis_subscriber.py
|   |   |-- rollback_service.py
|   |   |-- snapshot_verifier.py
|   |   |-- verification_report.py
|   |   \-- watchlist_store.py
|   |-- state
|   |   |-- __pycache__
|   |   |-- __init__.py
|   |   |-- app_state.py
|   |   |-- layout_persistence.py
|   |   |-- settings_state.py
|   |   |-- settings_store.py
|   |   |-- template_store.py
|   |   \-- version_store.py
|   |-- ui
|   |   |-- __pycache__
|   |   |-- adapters
|   |   |   |-- __pycache__
|   |   |   |-- account_adapter.py
|   |   |   |-- agent_config_adapter.py
|   |   |   |-- agents_adapter.py
|   |   |   |-- agents_log.py
|   |   |   |-- base_adapter.py
|   |   |   |-- clock_adapter.py
|   |   |   |-- leaderboard_adapter.py
|   |   |   |-- market_adapter.py
|   |   |   |-- notifications_adapter.py
|   |   |   \-- settings_adapter.py
|   |   |-- agent_creation_modal.py
|   |   |-- docking.py
|   |   |-- i18n_bind.py
|   |   |-- main_window.py
|   |   |-- settings_sync.py
|   |   \-- theme.py
|   |-- utils
|   |   |-- __pycache__
|   |   |-- __init__.py
|   |   |-- alerts.py
|   |   |-- formatters.py
|   |   |-- metrics_adapter.py
|   |   |-- notification_center.py
|   |   |-- ring_buffer.py
|   |   |-- shortcuts.py
|   |   |-- snapshot_throttler.py
|   |   \-- throttle.py
|   |-- __init__.py
|   |-- event_bridge.py
|   \-- main.py
|-- backtest
|   |-- __pycache__
|   \-- runner.py
|-- configs
|   |-- env_m1.yaml
|   \-- train_m1.yaml
|-- core
|   |-- __pycache__
|   |-- __init__.py
|   |-- auction_engine.py
|   |-- call_auction.py
|   |-- const.py
|   |-- imbalance_engine.py
|   |-- instruments.py
|   |-- market_data.py
|   |-- matching_engine.py
|   |-- matching_engine_extended.py
|   |-- order.py
|   |-- order_book.py
|   |-- ring_buffer.py
|   |-- snapshot.py
|   |-- trade.py
|   \-- validators.py
|-- data_pipeline
|   |-- build_event_nodes.py
|   \-- fetch_bars.py
|-- docs
|   |-- diagnostics.md
|   |-- frontend_dev_guide.md
|   |-- rollout_plan.md
|   \-- traceability_matrix.md
|-- infra
|   |-- __pycache__
|   |-- __init__.py
|   |-- event_bus.py
|   |-- interfaces.py
|   |-- repository.py
|   \-- unit_of_work.py
|-- logs
|-- observability
|   |-- __pycache__
|   |-- metrics.py
|   |-- performance_monitor.py
|   \-- struct_logger.py
|-- persistence
|   |-- __pycache__
|   |-- migrations
|   |   \-- 001_event_log.sql
|   |-- __init__.py
|   |-- logger.py
|   |-- models_account.py
|   |-- models_agent_binding.py
|   |-- models_bars.py
|   |-- models_event_log.py
|   |-- models_feature_buffer.py
|   |-- models_imports.py
|   |-- models_init.py
|   |-- models_instrument.py
|   |-- models_ledger.py
|   |-- models_order.py
|   |-- models_order_event.py
|   |-- models_position.py
|   |-- models_snapshot.py
|   \-- models_trade.py
|-- QSS
|   \-- button_style_1.qss
|-- rl
|   |-- __pycache__
|   |-- models
|   |   \-- lstm_ppo.py
|   |-- utils
|   |   \-- normalizer.py
|   |-- account_adapter.py
|   |-- ppo_agent.py
|   |-- trading_env.py
|   \-- vectorized_env.py
|-- scripts
|   |-- __pycache__
|   |-- benchmark_adaptive_snapshot.py
|   |-- benchmark_frontend_event_flow.py
|   |-- benchmark_replay.py
|   |-- benchmark_vectorized_env.py
|   |-- daily_update.py
|   |-- evaluate.py
|   |-- metrics_sanity_check.py
|   |-- replay.py
|   \-- stocksimctl.py
|-- services
|   |-- __pycache__
|   |-- __init__.py
|   |-- account_service.py
|   |-- adaptive_snapshot_service.py
|   |-- agent_binding_service.py
|   |-- agent_meta_listener.py
|   |-- bar_aggregator.py
|   |-- borrow_fee_scheduler.py
|   |-- config_hot_reload.py
|   |-- event_persistence_service.py
|   |-- fee_engine.py
|   |-- forced_liquidation_service.py
|   |-- instrument_service.py
|   |-- ipo_grant_queue.py
|   |-- ipo_listener.py
|   |-- ipo_poller.py
|   |-- ipo_service.py
|   |-- lending_pool.py
|   |-- market_data_query_service.py
|   |-- market_data_service.py
|   |-- metrics_exporter.py
|   |-- order_dispatcher.py
|   |-- order_service.py
|   |-- portfolio_executor.py
|   |-- recovery_service.py
|   |-- redis_client.py
|   |-- replay_service.py
|   |-- risk_engine.py
|   |-- risk_rule_registry.py
|   |-- risk_storage.py
|   |-- sim_clock.py
|   |-- snapshot_listener.py
|   |-- snapshot_service.py
|   |-- strategy_supervisor.py
|   \-- universe_provider.py
|-- simulation
|   |-- __pycache__
|   |-- ipo_allocator.py
|   |-- market_clock.py
|   |-- market_replay.py
|   \-- random_liquidity_provider.py
|-- stock_sim
|   |-- __pycache__
|   |-- rl
|   |   \-- __init__.py
|   |-- services
|   |   |-- __init__.py
|   |   \-- account_service.py
|   \-- __init__.py
|-- stock_sim.egg-info
|-- tests
|   |-- __pycache__
|   |-- frontend
|   |   |-- e2e
|   |   |   |-- __pycache__
|   |   |   |-- test_full_journey.py
|   |   |   |-- test_full_journey_v2.py
|   |   |   \-- test_i18n_accessibility.py
|   |   |-- integration
|   |   |   |-- __pycache__
|   |   |   |-- test_agents_flow.py
|   |   |   |-- test_event_flow.py
|   |   |   |-- test_frontend_entry.py
|   |   |   \-- test_i18n_accessibility_bridge.py
|   |   \-- unit
|   |       |-- __pycache__
|   |       |-- test_account_panel.py
|   |       |-- test_agent_config_adapter.py
|   |       |-- test_agent_config_panel.py
|   |       |-- test_agent_controller_batch.py
|   |       |-- test_agent_creation_dialog.py
|   |       |-- test_agent_creation_modal.py
|   |       |-- test_agents_panel.py
|   |       |-- test_alert_heartbeat_manual_time.py
|   |       |-- test_alerts.py
|   |       |-- test_clock_panel.py
|   |       |-- test_controllers_account_market.py
|   |       |-- test_controllers_agents.py
|   |       |-- test_controllers_task22.py
|   |       |-- test_dto.py
|   |       |-- test_event_bridge.py
|   |       |-- test_event_bridge_redis.py
|   |       |-- test_event_bridge_redis_fallback.py
|   |       |-- test_export_button.py
|   |       |-- test_export_service.py
|   |       |-- test_export_service_equity_consistency.py
|   |       |-- test_export_service_xlsx_fallback.py
|   |       |-- test_formatters.py
|   |       |-- test_i18n_loader.py
|   |       |-- test_indicator_computations_and_timeout.py
|   |       |-- test_indicator_timeout.py
|   |       |-- test_indicators.py
|   |       |-- test_leaderboard_export_concurrency.py
|   |       |-- test_leaderboard_panel.py
|   |       |-- test_mainwindow_layout.py
|   |       |-- test_market_panel.py
|   |       |-- test_metrics_adapter.py
|   |       |-- test_metrics_dump.py
|   |       |-- test_notification_center_ring_behavior.py
|   |       |-- test_notifications.py
|   |       |-- test_notifications_panel_adapter.py
|   |       |-- test_panel_i18n_titles.py
|   |       |-- test_panel_registry_main.py
|   |       |-- test_performance_monitor.py
|   |       |-- test_rate_limiter.py
|   |       |-- test_ring_buffer_concurrency.py
|   |       |-- test_rollback_consistency.py
|   |       |-- test_script_validator.py
|   |       |-- test_script_validator_notification.py
|   |       |-- test_settings_clock_playback_bridge.py
|   |       |-- test_settings_panel.py
|   |       |-- test_settings_panel_adapter.py
|   |       |-- test_settings_panel_metrics.py
|   |       |-- test_settings_panel_playback_speed_mock.py
|   |       |-- test_settings_panel_redo.py
|   |       |-- test_settings_panel_transaction.py
|   |       |-- test_settings_panel_transaction_task32.py
|   |       |-- test_settings_panel_undo.py
|   |       |-- test_settings_store.py
|   |       |-- test_shortcuts_accessibility.py
|   |       |-- test_snapshot_throttler.py
|   |       |-- test_snapshot_verifier.py
|   |       |-- test_state.py
|   |       |-- test_template_store_and_apply.py
|   |       |-- test_utils_tools.py
|   |       |-- test_verification_report.py
|   |       |-- test_version_store.py
|   |       \-- test_watchlist_corrupted.py
|   |-- integration
|   |   |-- __pycache__
|   |   |-- test_rollback_alert_notification.py
|   |   \-- test_snapshot_throttle_integration.py
|   |-- conftest.py
|   |-- test_account_panel_highlight_notification.py
|   |-- test_account_panel_single_highlight_notification.py
|   |-- test_adaptive_snapshot.py
|   |-- test_agents_panel_heartbeat_notification.py
|   |-- test_borrow_fee.py
|   |-- test_clock_and_rollback_service.py
|   |-- test_e2e_headless_no_gui_attrs.py
|   |-- test_e2e_headless_widget_no_gui_attrs.py
|   |-- test_e2e_preload_panels_mounted.py
|   |-- test_e2e_rollback_alert_notification_widget.py
|   |-- test_event_persistence.py
|   |-- test_export_e2e_files_created.py
|   |-- test_headless_no_gui_attrs.py
|   |-- test_indicator_executor.py
|   |-- test_leaderboard_service.py
|   |-- test_market_panel_indicators.py
|   |-- test_multi_symbol_match.py
|   |-- test_notification_center.py
|   |-- test_panels_e2e_view_models.py
|   |-- test_perf_preload_panels_mount_time.py
|   |-- test_recovery.py
|   |-- test_replay_recovery_integration.py
|   |-- test_risk_config_hot_reload.py
|   |-- test_risk_rules.py
|   |-- test_rl_vectorized.py
|   |-- test_rollback_alert_notification.py
|   |-- test_settings_sync_adapter.py
|   |-- test_short_borrow_liquidation.py
|   |-- test_slow_op.py
|   |-- test_symbol_detail_indicators.py
|   |-- test_symbol_detail_trades.py
|   |-- test_tick_ring_buffer.py
|   |-- test_watchlist_persistence.py
|   |-- test_widget_mount_fallback.py
|   \-- 测试结果.txt
|-- .gen_structure.py
|-- 123.py
|-- __init__.py
|-- diag_orders.py
|-- export_snap-1757431590092.csv
|-- export_snap-1757443310337.csv
|-- export_snap-1757443930920.csv
|-- export_snap-1757445047112.csv
|-- export_snap-1757486861919.csv
|-- export_snap-1757487818365.csv
|-- export_snap-1757489804415.csv
|-- export_snap-1757496527691.csv
|-- export_snap-1757587890620.csv
|-- frontend_settings.json
|-- main_backtest.py
|-- PPO+LSTM落地方案.txt
|-- pyproject.toml
|-- pytest.ini
|-- README.md
|-- settings.py
|-- setup_frontend_entry.py
|-- sitecustomize.py
|-- stock_sim_test.db
|-- StockSim项目架构分析报告.md
|-- structure.md
|-- test_layout.json
|-- 关键规则与建议.txt
\-- 前端需求.md


关键目录说明：
- app/: 应用层入口、控制器、UI 等模块
- core/: 撮合、订单、行情等核心引擎
- infra/: 事件总线、仓储、UoW 等基础设施
- data_pipeline/: 数据抓取与事件构建脚本
- backtest/: 回测运行器
- services/, simulation/, agents/: 业务服务与策略/仿真
- tests/: 测试用例
- docs/: 文档
- configs/: 配置文件