# MainWindow Module Status

## Module

Frontend main window structure / panel host unification

## Current goal

- Make `app/ui/main_window.py` the single real frontend window structure.
- Reduce duplicate workspace/dock mounting that can create one content-bearing panel set plus one blank duplicate set.

## Current state

in-progress

## Task 2026-03-25-mainwindow-12
- **time**: 2026-03-25
- **status**: in-progress
- **goal**: 修复真实 GUI 中“每种面板出现两次，且其中一组空白”的问题，优先只切空白残留路径，不误删真实有内容的一组。
- **files involved**:
  - `setup_frontend_entry.py`
  - `app/ui/main_window.py`
- **change summary**:
  - 去掉了 `setup_frontend_entry.py::main()` 在 GUI 启动后对默认面板的第二次 `open_panel()`。
  - 保留 `_start_frontend()` 内的默认预加载，避免同一面板在 GUI 入口阶段被重复打开一次。
  - 去掉了 `MainWindow.open_panel()` 中 dock-only 面板再额外塞进 legacy layout bookkeeping 的路径，减少“真实 workspace 页面 + 空白残留挂载”同时出现的风险。
  - 进一步修正了 `MainWindow.open_panel()` 的重入判断：现在会先检查 `self._workspace_pages`，避免主页面已经存在于 workspace 时，因为 `_dock` 中查不到而再次挂出第二份同名页面。
- **purpose**:
  - 针对用户在真实 GUI 中观察到的重复面板现象做最小、低风险收敛。
  - 优先删除最像“空白残留”的挂载路径，而不是粗暴删掉真实有内容的页面。
- **impact / risk**:
  - 正向：应减少 entry 重复 open 与 dock/layout 双挂载造成的重复面板。
  - 风险：若仍有重复，问题可能还存在于 panel registry / adapter replacement / layout restore 交互，需要继续检查，但当前改动已先去掉最明显的重复源。
- **next actions**:
  - 重新验证 GUI 是否仍出现“一组空白、一组有内容”的重复面板。
  - 若仍存在，继续检查 `register_builtin_panels()` / `register_ui_adapters()` 与 layout restore 的交互。
