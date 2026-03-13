# python
from .models_imports import Base, Column, String, Float, relationship, SimTimeMixin
from sqlalchemy import Boolean  # 新增

class Account(Base, SimTimeMixin):
    __tablename__ = "accounts"
    id = Column(String(64), primary_key=True)
    cash = Column(Float, default=0.0)
    frozen_cash = Column(Float, default=0.0)
    # 预冻结的手续费（买单按吃单假设预估，可在结算后多退少补）
    frozen_fee = Column(Float, default=0.0)
    # 新增: 可交易结算周期限制 (T+0 / T+1) - 两者皆可为默认
    tradable_t0 = Column(Boolean, default=True, index=True)
    tradable_t1 = Column(Boolean, default=True, index=True)
    positions = relationship("Position", back_populates="account", cascade="all, delete-orphan")