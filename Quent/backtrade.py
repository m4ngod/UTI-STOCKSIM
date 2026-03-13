import backtrader as bt
import pandas as pd
import numpy as np
from datetime import datetime
import main

#数据加载
df = pd.read_csv('rb_spread_signals.csv', parse_dates=['date'])
df.set_index('date', inplace=True)
assert not df[['rb_near', 'rb_far', 'beta', 'long_signal', 'short_signal', 'close_signal']].isnull().any().any()


#自定义 DataFeed
class SpreadFeed(bt.feeds.PandasData):
    lines = ('spread_beta', 'long_signal', 'short_signal', 'close_signal')
    params = dict(
        datetime=None,
        open=0, high=0, low=0,
        close=0,
        volume=-1, openinterest=-1,
        spread_beta=1, long_signal=2, short_signal=3, close_signal=4,
    )



#创建两个 feed：近月 / 远月，仅价差不同，其余信号完全一致
df_near = df[['rb_near', 'beta', 'long_signal', 'short_signal', 'close_signal']].copy()
df_near.columns = ['close', 'beta', 'long_signal', 'short_signal', 'close_signal']

df_far  = df[['rb_far',  'beta', 'long_signal', 'short_signal', 'close_signal']].copy()
df_far.columns  = df_near.columns

data_near = SpreadFeed(dataname=df_near)
data_far  = SpreadFeed(dataname=df_far)

#策略
class SpreadStrategy(bt.Strategy):
    params = dict(
        slippage = 2,           # 交易滑点
        margin_rate = 0.12,     # 交易所保证金率
        contract_size = 10,     # t/手
        stop_loss = 500,        # 固定止损 / 手
        max_drawdown = 0.10,    # 账户回撤
    )

    def __init__(self):
        self.near, self.far = self.datas  # data0, data1

        #通过 lines 直接拿自定义列
        self.beta   = self.near.spread_beta
        self.lsig   = self.near.long_signal
        self.ssig   = self.near.short_signal
        self.csig   = self.near.close_signal

        self.equity_peak = self.broker.getvalue()

    #手续费、滑点、保证金动态检查
    def _margin_ok(self, lots_near, lots_far):
        price_near = self.near.close[0]
        price_far  = self.far.close[0]
        if np.isnan(price_near) or np.isnan(price_far):
            return False
        margin_need = (abs(lots_near)*price_near +
                       abs(lots_far)*price_far) * self.p.contract_size * self.p.margin_rate
        return self.broker.getcash() > margin_need

    def notify_trade(self, trade):
        if trade.isclosed:
            pnl = trade.pnlcomm
            print(f'{trade.getdataname()} 平仓, PnL={pnl:.0f}')

    # ---------------- next ------------------
    def next(self):
        #回撤风控
        equity = self.broker.getvalue()
        self.equity_peak = max(self.equity_peak, equity)
        if equity < self.equity_peak * (1 - self.p.max_drawdown):
            self.close(self.near); self.close(self.far)
            print('触发回撤风控, 全部平仓')
            return

        pos_near = self.getposition(self.near).size
        if min(self.near.close[0], self.far.close[0]) <= 0: return
        hedge    = int(round(self.beta[0]))

        #平仓
        if self.csig[0] and pos_near != 0:
            self.close(self.near); self.close(self.far); return

        #确保空仓再开新单
        if pos_near == 0:
            if self.lsig[0]:
                if self._margin_ok(1, -hedge):
                    self.buy (self.near, size=20,  price=self.near.close[0]+self.p.slippage)
                    self.sell(self.far,  size=hedge, price=self.far.close[0]-self.p.slippage)
            elif self.ssig[0]:
                if self._margin_ok(1, -hedge):
                    self.sell(self.near, size=20,  price=self.near.close[0]-self.p.slippage)
                    self.buy (self.far,  size=hedge, price=self.far.close[0]+self.p.slippage)

        #固定止损
        if pos_near != 0:
            entry_price = self.getposition(self.near).price
            if abs(self.near.close[0] - entry_price) * self.p.contract_size >= self.p.stop_loss:
                print('触发止损')
                self.close(self.near); self.close(self.far)

#回测执行
cerebro = bt.Cerebro()
cerebro.adddata(data_near, name='rb_near')
cerebro.adddata(data_far,  name='rb_far')

#佣金（双边各收）
#cerebro.broker.setcommission(commission=1.5/1e4)

class FixedPerLot(bt.CommInfoBase):
    params = dict(perlot=1.2, contract_size=10)
    def _getcommission(self, size, price, pseudoexec):
        return abs(size) * self.p.perlot
cerebro.broker.addcommissioninfo(FixedPerLot())

cerebro.broker.setcash(1_000_000)

cerebro.addstrategy(SpreadStrategy)

print('回测开始资金: %.0f' % cerebro.broker.getvalue())
cerebro.run()
print('回测结束资金: %.0f' % cerebro.broker.getvalue())
