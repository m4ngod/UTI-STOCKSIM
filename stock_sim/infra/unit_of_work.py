# file: infra/unit_of_work.py
# python
from contextlib import AbstractContextManager
from typing import Callable
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
import time

DEADLOCK_CODES = {1213, 1205}

class UnitOfWork(AbstractContextManager):
    def __init__(self, session_factory: Callable[[], Session], *, max_retries: int = 3, base_sleep: float = 0.02):
        self._session_factory = session_factory
        self.session: Session | None = None
        self.committed = False
        self.max_retries = max_retries
        self.base_sleep = base_sleep

    def __enter__(self):
        self.session = self._session_factory()
        self.committed = False
        return self

    def commit(self):
        if not self.session or self.committed:
            return
        attempt = 0
        while True:
            try:
                self.session.commit()
                self.committed = True
                return
            except OperationalError as e:
                code = getattr(getattr(e, 'orig', None), 'args', [None])[0]
                if code in DEADLOCK_CODES and attempt < self.max_retries:
                    self.session.rollback()
                    sleep_s = self.base_sleep * (2 ** attempt)
                    time.sleep(sleep_s)
                    attempt += 1
                    continue
                # 非死锁或超出重试
                self.session.rollback()
                raise
            except Exception:
                self.session.rollback()
                raise

    def rollback(self):
        if self.session and not self.committed:
            self.session.rollback()

    def __exit__(self, exc_type, exc, tb):
        if exc:
            self.rollback()
        elif not self.committed:
            try:
                self.commit()
            except Exception:
                # 让上层看到异常
                raise
        if self.session:
            self.session.close()
        return False