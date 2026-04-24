"""Runtime-backed account cache/store for the desktop app."""
from __future__ import annotations

from threading import RLock
from typing import Dict, List, Optional
import time

from app.core_dto.account import AccountDTO, PositionDTO
from app.runtime_gateway import RuntimeGateway

try:
    from app.event_bridge import on_account_created, on_account_updated  # type: ignore
except Exception:  # pragma: no cover
    on_account_created = None  # type: ignore
    on_account_updated = None  # type: ignore


def account_dto_from_runtime_payload(payload: dict | None) -> AccountDTO | None:
    if not isinstance(payload, dict):
        return None
    positions = [
        PositionDTO(
            symbol=str(pos.get("symbol") or ""),
            quantity=int(pos.get("quantity") or 0),
            frozen_qty=int(pos.get("frozen_qty") or 0),
            avg_price=float(pos.get("avg_price") or 0.0),
            borrowed_qty=int(pos.get("borrowed_qty") or 0),
            pnl_unreal=float(pos.get("pnl_unreal") or 0.0),
        )
        for pos in list(payload.get("positions") or [])
        if isinstance(pos, dict)
    ]
    account_id = str(payload.get("account_id") or "").strip()
    if not account_id:
        return None
    sim_day = payload.get("sim_day")
    return AccountDTO(
        account_id=account_id,
        cash=float(payload.get("cash") or 0.0),
        frozen_cash=float(payload.get("frozen_cash") or 0.0),
        positions=positions,
        realized_pnl=float(payload.get("realized_pnl") or 0.0),
        unrealized_pnl=float(payload.get("unrealized_pnl") or 0.0),
        equity=float(payload.get("equity") or 0.0),
        utilization=float(payload.get("utilization") or 0.0),
        snapshot_id=str(payload.get("snapshot_id") or f"runtime-{account_id}-{int(time.time() * 1000)}"),
        sim_day=str(sim_day) if sim_day is not None else time.strftime("%Y-%m-%d"),
    )


def account_dto_from_account_event(payload: dict | None) -> AccountDTO | None:
    if not isinstance(payload, dict):
        return None
    account = payload.get("account")
    if isinstance(account, dict):
        raw = dict(account)
    else:
        raw = dict(payload)
    account_id = str(raw.get("id") or raw.get("account_id") or "").strip()
    if not account_id:
        return None
    positions = [
        PositionDTO(
            symbol=str(pos.get("symbol") or ""),
            quantity=max(0, int(pos.get("quantity") or 0)),
            frozen_qty=max(0, int(pos.get("frozen_qty") or 0)),
            avg_price=max(0.0, float(pos.get("avg_price") or 0.0)),
            borrowed_qty=max(0, int(pos.get("borrowed_qty") or 0)),
            pnl_unreal=float(pos.get("pnl_unreal") or 0.0),
        )
        for pos in list(raw.get("positions") or [])
        if isinstance(pos, dict)
    ]
    cash = float(raw.get("cash") or 0.0)
    frozen_cash = float(raw.get("frozen_cash") or 0.0)
    frozen_fee = float(raw.get("frozen_fee") or 0.0)
    equity = float(raw.get("equity") or (cash + frozen_cash + sum(p.quantity * p.avg_price for p in positions)))
    utilization = float(raw.get("utilization") or 0.0)
    if utilization <= 0.0 and equity > 0:
        utilization = min(max((frozen_cash + frozen_fee) / equity, 0.0), 1.0)
    sim_day = raw.get("sim_day")
    snapshot_id = str(raw.get("snapshot_id") or f"event-{account_id}-{int(time.time() * 1000)}")
    return AccountDTO(
        account_id=account_id,
        cash=cash,
        frozen_cash=frozen_cash,
        positions=positions,
        realized_pnl=float(raw.get("realized_pnl") or 0.0),
        unrealized_pnl=float(raw.get("unrealized_pnl") or 0.0),
        equity=max(0.0, equity),
        utilization=min(max(utilization, 0.0), 1.0),
        snapshot_id=snapshot_id,
        sim_day=str(sim_day) if sim_day is not None else time.strftime("%Y-%m-%d"),
    )


class AccountRuntimeStore:
    def __init__(self, runtime_gateway: RuntimeGateway | None = None):
        self._runtime_gateway = runtime_gateway or RuntimeGateway()
        self._lock = RLock()
        self._accounts: Dict[str, AccountDTO] = {}
        self._cancel_subs: List[object] = []
        self._setup_subscriptions()

    def _setup_subscriptions(self) -> None:
        try:
            if callable(on_account_updated):
                self._cancel_subs.append(on_account_updated(self._on_account_updated, async_mode=False))
        except Exception:
            pass
        try:
            if callable(on_account_created):
                self._cancel_subs.append(on_account_created(self._on_account_created, async_mode=False))
        except Exception:
            pass

    def _on_account_updated(self, _topic: str, payload: dict) -> None:
        dto = account_dto_from_account_event(payload)
        if dto is not None:
            self._put(dto)
            return
        account_id = ""
        if isinstance(payload, dict):
            account_id = str(payload.get("id") or "").strip()
            if not account_id and isinstance(payload.get("account"), dict):
                account_id = str((payload.get("account") or {}).get("id") or "").strip()
        if account_id:
            self.refresh(account_id)

    def _on_account_created(self, _topic: str, payload: dict) -> None:
        if not isinstance(payload, dict):
            return
        account_id = str(payload.get("account_id") or "").strip()
        if account_id:
            self.refresh(account_id)

    def _put(self, dto: AccountDTO) -> AccountDTO:
        with self._lock:
            self._accounts[dto.account_id] = dto
        return dto

    def get(self, account_id: str) -> Optional[AccountDTO]:
        normalized = str(account_id or "").strip()
        if not normalized:
            return None
        with self._lock:
            return self._accounts.get(normalized)

    def refresh(self, account_id: str) -> Optional[AccountDTO]:
        normalized = str(account_id or "").strip()
        if not normalized:
            return None
        dto = account_dto_from_runtime_payload(self._runtime_gateway.get_account_snapshot(normalized))
        if dto is None:
            return None
        return self._put(dto)

    def get_or_fetch(self, account_id: str) -> Optional[AccountDTO]:
        return self.get(account_id) or self.refresh(account_id)

    def list_account_ids(self) -> List[str]:
        runtime_ids = list(self._runtime_gateway.list_account_ids() or [])
        with self._lock:
            cached_ids = list(self._accounts.keys())
        ordered: List[str] = []
        for account_id in runtime_ids + cached_ids:
            normalized = str(account_id or "").strip()
            if normalized and normalized not in ordered:
                ordered.append(normalized)
        return ordered

    def close(self) -> None:
        for cancel in list(self._cancel_subs):
            try:
                cancel()
            except Exception:
                pass
        self._cancel_subs.clear()

    def __del__(self):  # pragma: no cover
        try:
            self.close()
        except Exception:
            pass


__all__ = [
    "AccountRuntimeStore",
    "account_dto_from_runtime_payload",
    "account_dto_from_account_event",
]
