import nasdaqdatalink as ndl
import pandas as pd
import numpy as np
from statsmodels.tsa.stattools import adfuller
from pykalman import KalmanFilter

ndl.ApiConfig.api_key = "-9n8d4z5_t_ihhyy3tga"     #API Key
TABLE = "DY/FUA"

# df = ndl.get_table('DY/FUA', commodity='AL', last_trade_month='201501')
# print(df.head())

df = ndl.get_table(
    'DY/FUA',
    commodity='AU',
    paginate=True
)
print(df[['date', 'last_trade_month']].drop_duplicates().sort_values('last_trade_month').tail(20))
