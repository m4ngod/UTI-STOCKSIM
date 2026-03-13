# file: core/matching_engine_extended.py
# python
# 说明：保留之前 matching_engine 的逻辑，这里只演示可以在服务层接管冻结与风险后精简。
from stock_sim.core.matching_engine import MatchingEngine
# 可在此扩展分阶段撮合 / call auction / batch match 等高级功能。