# Code Index

## Frontend structure

- Real main window: `app/ui/main_window.py`
- Legacy entry wrapper: `app/main.py`
- UI bridge / dynamic page opening: `app/ui/ui_refresh.py`
- Dock host: `app/ui/docking.py`
- Panel registry: `app/panels/__init__.py`, `app/panels/registry.py`
- Startup entry: `setup_frontend_entry.py`

## Market frontend

- Controller: `app/controllers/market_controller.py`
- Logic panel: `app/panels/market/panel.py`
- UI adapter: `app/ui/adapters/market_adapter.py`
- Bars/K-line cache service: `app/services/market_data_service.py`
- Snapshot/event bridge: `app/event_bridge.py`

## Account frontend

- Controller: `app/controllers/account_controller.py`
- Logic panel: `app/panels/account/panel.py`
- App-layer account service: `app/services/account_service.py`

## Backend/runtime trading

- Order orchestration: `services/order_service.py`
- Runtime account service: `services/account_service.py`
- Engine registry: `services/engine_registry.py`
- Instrument creation / engine registration: `services/instrument_service.py`
- Backend snapshot service: `services/market_data_service.py`
- Snapshot dump service: `services/snapshot_service.py`

## Existing architecture note

- Frontend/backend dependency map: `docs/frontend-backend-dependency-map.md`
