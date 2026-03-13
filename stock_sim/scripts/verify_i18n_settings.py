import json, os, time, sys
# 确保可从 scripts/ 目录导入项目包
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.state.settings_store import SettingsStore
from app.i18n import current_language

def run_case(label: str, lang: str, auto_save: bool=True):
    path = f"tmp_settings_{label}.json"
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({
            "language": lang,
            "theme": "light",
            "refresh_interval_ms": 1000,
            "playback_speed": 1.0,
            "alert_thresholds": {},
            "high_contrast": False
        }, f)
    store = SettingsStore(path=path, auto_save=auto_save)
    print(f"[{label}] before apply -> current_language={current_language()} state={store.get_state().language}", flush=True)
    time.sleep(0.6)  # give async thread time
    print(f"[{label}] after  apply -> current_language={current_language()} state={store.get_state().language}", flush=True)
    try:
        os.remove(path)
    except Exception:
        pass

if __name__ == '__main__':
    print('--- verify i18n settings start ---', flush=True)
    # 无效语言，期望回退到默认（loader 默认 en_US）且回写状态
    run_case('invalid', 'xx_YY', auto_save=True)
    # 有效语言 zh_CN，期望生效
    run_case('valid', 'zh_CN', auto_save=False)
    print('--- verify i18n settings done ---', flush=True)
