import sys, importlib, pathlib, traceback

root = pathlib.Path(r'F:\PythonProjects\stock_sim')

if str(root) not in sys.path:
    sys.path.insert(0, str(root))
    print('sys.path[0:3]=', sys.path[:3])
    try:
        m = importlib.import_module('app.indicators.executor')
        print('module file:', m.__file__)
        print('has IndicatorExecutor:', hasattr(m, 'IndicatorExecutor'))
        print('dir keys snippet:', [k for k in dir(m) if 'Indicator' in k])
    except Exception as e:
        print('IMPORT FAILED')
        traceback.print_exc()