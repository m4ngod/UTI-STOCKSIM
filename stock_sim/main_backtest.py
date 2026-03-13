# file: main_backtest.py
# python
from stock_sim.persistence.models_init import init_models
from stock_sim.backtest.runner import BacktestRunner

def main():
    init_models()
    runner = BacktestRunner("TEST")
    runner.run()

if __name__ == "__main__":
    main()