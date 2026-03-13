# python
from __future__ import annotations
from sqlalchemy.orm import Session, sessionmaker
import inspect# 新增
from sqlalchemy.exc import IntegrityError
from contextlib import contextmanager  # 新增
from sqlalchemy import select  # 新增
from stock_sim.persistence.models_agent_binding import AgentBinding
import json  # 新增

class AgentBindingService:
    """智能体 / 散户 与账户绑定服务。
    规则:
      - 一个 agent_name 只能绑定一个 account_id (主键限制)
      - 一个 account_id 只能被一个 agent 占用 (unique)
      - rebind: 为已存在的 agent 更换账户 (旧账户释放)
      - overwrite: 允许覆盖已经存在的 agent 绑定 (保持 account 唯一)
    支持传入 Session 或 SessionLocal 工厂, 防止 UI 误传工厂导致 AttributeError。
    """
    def __init__(self, session_or_factory):
        # sessionmaker / factory: callable 且无 add 属性
        if callable(session_or_factory) and not hasattr(session_or_factory, 'add'):
            self._factory = session_or_factory
            self._session = None
        elif hasattr(session_or_factory, 'add'):
            # 直接复用该 session (单线程 UI 可用)
            self._factory = None
            self._session = session_or_factory
        else:
            raise ValueError("无效的 session_or_factory 传入")

    @contextmanager
    def _get_session(self):
        if self._factory:
            sess = self._factory()
            try:
                yield sess
                sess.close()
            except Exception:
                try: sess.close()
                except Exception: pass
                raise
        else:
            # 持久会话
            yield self._session

    # -------- Internal helpers --------
    def _sa_get(self, sess, entity, ident):
        try:
            return sess.get(entity, ident)
        except Exception:
            try:
                pk = list(entity.__table__.primary_key.columns)[0]
                stmt = select(entity).where(pk == ident)
                return sess.execute(stmt).scalars().first()
            except Exception:
                return None

    # -------- CRUD --------
    def bind(self, agent_name: str, agent_type: str, account_id: str, *, overwrite: bool = False, meta: dict | None = None) -> AgentBinding:
        agent_name = agent_name.strip()
        if not agent_name:
            raise ValueError("agent_name 不能为空")
        meta_json = json.dumps(meta, ensure_ascii=False) if meta else None
        with self._get_session() as s:
            row = self._sa_get(s, AgentBinding, agent_name)
            if row and not overwrite:
                if row.account_id != account_id:
                    raise ValueError(f"已存在绑定: {agent_name} -> {row.account_id}")
                # 可选择更新 meta
                if meta_json and row.meta != meta_json:
                    row.meta = meta_json; row.touch(); s.commit()
                return row
            if row is None:
                row = AgentBinding(agent_name=agent_name, agent_type=agent_type.upper(), account_id=account_id, meta=meta_json)
                s.add(row)
            else:
                row.account_id = account_id
                row.agent_type = agent_type.upper() or row.agent_type
                if meta_json:
                    row.meta = meta_json
                row.touch()
            try:
                s.commit()
            except Exception as e:
                s.rollback()
                raise ValueError(f"账户 {account_id} 已被其它智能体占用") from e
            return row

    def rebind(self, agent_name: str, new_account_id: str) -> AgentBinding:
        with self._get_session() as s:
            row = self._sa_get(s, AgentBinding, agent_name)
            if not row:
                raise ValueError(f"agent 不存在: {agent_name}")
            if row.account_id == new_account_id:
                return row
            row.account_id = new_account_id
            row.touch()
            try:
                s.commit()
            except Exception as e:
                s.rollback()
                raise ValueError(f"账户 {new_account_id} 已被其它智能体��用") from e
            return row

    def unbind(self, agent_name: str) -> bool:
        with self._get_session() as s:
            row = self._sa_get(s, AgentBinding, agent_name)
            if not row:
                return False
            s.delete(row)
            try:
                s.commit()
            except Exception:
                s.rollback(); return False
            return True

    def set_meta(self, agent_name: str, meta: dict):
        meta_json = json.dumps(meta, ensure_ascii=False)
        with self._get_session() as s:
            row = self._sa_get(s, AgentBinding, agent_name)
            if not row:
                raise ValueError("agent 不存在")
            row.meta = meta_json
            row.touch()
            try:
                s.commit()
            except Exception as e:
                s.rollback(); raise e
            return True

    # -------- Query --------
    def get(self, agent_name: str) -> AgentBinding | None:
        with self._get_session() as s:
            return self._sa_get(s, AgentBinding, agent_name)

    def get_account(self, agent_name: str) -> str | None:
        r = self.get(agent_name)
        return r.account_id if r else None

    def ensure_retail_name(self, base_prefix: str = "RC") -> str:
        idx = 1
        with self._get_session() as s:
            from sqlalchemy import select
            while True:
                cand = f"{base_prefix}{idx:03d}"
                stmt = select(AgentBinding.agent_name).where(AgentBinding.agent_name == cand)
                exists = s.execute(stmt).scalar_one_or_none()
                if not exists:
                    return cand
                idx += 1

    def all_dict(self):
        with self._get_session() as s:
            try:
                from sqlalchemy import select
                rows = s.execute(select(AgentBinding)).scalars().all()
            except Exception:
                rows = []
            out = []
            for r in rows:
                try:
                    meta_obj = json.loads(r.meta) if r.meta else None
                except Exception:
                    meta_obj = None
                item = {
                    "agent_name": r.agent_name,
                    "agent": r.agent_name,
                    "agent_type": getattr(r, 'agent_type', None),
                    "account_id": r.account_id,
                    "created_at": getattr(r, 'created_at', None),
                    "meta": meta_obj
                }
                out.append(item)
            return out
