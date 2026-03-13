import pandas as pd
import numpy as np
import requests
from statsmodels.tsa.stattools import adfuller
from pykalman import KalmanFilter

# Step 1  获取数据
SINA_URL = (
    "https://stock2.finance.sina.com.cn/futures/api/json.php/"
    "IndexService.getInnerFuturesDailyKLine?symbol={}"
)

def fetch_sina_future(symbol: str) -> pd.DataFrame:
    url = SINA_URL.format(symbol)
    try:
        js = requests.get(url, timeout=10).json()
    except Exception as e:
        raise ConnectionError(f"网络/接口错误 {symbol}: {e}")

    if not js:
        raise ValueError(f"{symbol} 返回空数据，检查合约代码")

    df = pd.DataFrame(js, columns=['date', 'open', 'high', 'low', 'close', 'volume'])
    df['date'] = pd.to_datetime(df['date'])
    df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
    return df.set_index('date').sort_index()

print(">>> 下载 RB2001（近月）")
near_df = fetch_sina_future("RB2201").rename(columns={'close': 'rb_near'})
print(">>> 下载 RB2005（远月）")
far_df  = fetch_sina_future("RB2205").rename(columns={'close': 'rb_far'})

data = near_df[['rb_near']].join(far_df[['rb_far']], how='inner').dropna()
if data.empty:
    raise RuntimeError("两组数据没有交集，停止运行")

# Step 2  ADF 协整检验
spread_raw = data['rb_near'] - data['rb_far']
p_value = adfuller(spread_raw)[1]
print(f"ADF 检验 p-value = {p_value:.4f}  （仅供参考, 不作为硬门槛）")

# Step 3 卡尔曼滤波动态 β
y = data['rb_near'].values
x = data['rb_far'].values.reshape(-1, 1)

# pykalman
obs_mats = x.reshape(-1, 1, 1)

# Q / R 可以微调；先给经验值
R = np.var(y - x.flatten())       #观测噪声协方差
Q = 1e-5                          #状态噪声协方差

kf = KalmanFilter(
    transition_matrices      = [1.0],      # β_t = β_{t-1} + w_t
    observation_matrices     = obs_mats,
    transition_covariance    = Q,
    observation_covariance   = R,
    initial_state_mean       = 1.0,
    initial_state_covariance = 1.0
)

state_means, _ = kf.filter(y)

data['beta']   = state_means.flatten()
data['spread'] = data['rb_near'] - data['beta'] * data['rb_far']

# Step 4  z-score 信号示例
win = 60
data['z'] = (data['spread'] - data['spread'].rolling(win).mean()) / \
             data['spread'].rolling(win).std()

data['long_signal']  = (data['z'] < -2).astype(int)    #做多近月、做空远月
data['short_signal'] = (data['z'] >  2).astype(int)    #反向
data['close_signal'] = (data['z'].abs() < 0.5).astype(int)

print("\n=== 最新结果预览 ===")
print(data.tail(10))

#在保存到CSV前，加NaN清理，避免将NaN行喂给回测
data = data.dropna(subset=['rb_near', 'rb_far', 'beta', 'spread', 'z'])
#NaN统一补0
for c in ['long_signal', 'short_signal', 'close_signal']:
    data[c] = data[c].fillna(0).astype(int)

data.to_csv('rb_spread_signals.csv')
