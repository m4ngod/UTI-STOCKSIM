# python
from datetime import datetime
from .models_imports import Base, Column, Integer, String, DateTime, Float
from sqlalchemy import Text

class FeatureBuffer(Base):
    __tablename__ = "feature_buffer"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime, default=datetime.utcnow, index=True)
    symbol = Column(String(32), index=True)
    # 以 JSON 序列化后的特征向量（逗号分隔或 JSON 字符串）
    features = Column(Text)  # 使用通用 Text 便于 sqlite / mysql 兼容
    label = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
