from __future__ import annotations

import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)

from app.ui.adapters.account_adapter import AccountPanelAdapter
from infra.event_bus import event_bus

print('before_adapter', flush=True)
adp = AccountPanelAdapter()
print('before_widget', flush=True)
widget = adp.widget()
print('after_widget', type(widget).__name__, flush=True)
print('combo_exists', getattr(adp, '_account_combo', None) is not None, flush=True)

aid = 'MSR9999'
print('before_publish', flush=True)
event_bus.publish('account.created', {'account_id': aid, 'initial_cash': 123456.0})
print('after_publish', flush=True)
time.sleep(0.05)
combo = getattr(adp, '_account_combo', None)
print('combo', combo, flush=True)
if combo is not None:
    try:
        print('idx', combo.findText(aid), flush=True)
    except Exception as e:
        print('findText_error', repr(e), flush=True)
print('done', flush=True)
