from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, Text

from .models_imports import Base, Column, DateTime, Float, Integer, String


class TrainingEpisode(Base):
    __tablename__ = "training_episodes"

    episode_id = Column(String(96), primary_key=True)
    arena_id = Column(String(96), nullable=True, index=True)
    run_id = Column(String(64), nullable=True, index=True)
    generation = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="created", index=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    sim_day_start = Column(Integer, nullable=True)
    sim_day_end = Column(Integer, nullable=True)
    config_json = Column(Text, nullable=True)
    summary_json = Column(Text, nullable=True)


class ModelEpisodeResult(Base):
    __tablename__ = "model_episode_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    episode_id = Column(String(96), nullable=False, index=True)
    agent_id = Column(String(128), nullable=False, index=True)
    model_id = Column(String(128), nullable=False, index=True)
    generation = Column(Integer, nullable=False, default=0)
    score = Column(Float, nullable=False, default=0.0)
    rank = Column(Integer, nullable=True)
    equity_start = Column(Float, nullable=True)
    equity_end = Column(Float, nullable=True)
    equity_return = Column(Float, nullable=True)
    max_drawdown = Column(Float, nullable=True)
    turnover = Column(Float, nullable=True)
    fee_total = Column(Float, nullable=True)
    trade_count = Column(Integer, nullable=False, default=0)
    reward_total = Column(Float, nullable=False, default=0.0)
    metrics_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class ModelTransition(Base):
    __tablename__ = "model_transitions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), nullable=True, index=True)
    episode_id = Column(String(96), nullable=True, index=True)
    arena_id = Column(String(96), nullable=True, index=True)
    agent_id = Column(String(128), nullable=False, index=True)
    model_id = Column(String(128), nullable=True, index=True)
    step_index = Column(Integer, nullable=False, default=0)
    observation_json = Column(Text, nullable=True)
    action_json = Column(Text, nullable=True)
    execution_json = Column(Text, nullable=True)
    reward_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class ModelCheckpoint(Base):
    __tablename__ = "model_checkpoints"

    checkpoint_id = Column(String(96), primary_key=True)
    model_id = Column(String(128), nullable=False, index=True)
    agent_id = Column(String(128), nullable=True, index=True)
    generation = Column(Integer, nullable=False, default=0, index=True)
    episode_id = Column(String(96), nullable=True, index=True)
    path = Column(String(512), nullable=False)
    score = Column(Float, nullable=True, index=True)
    is_hall_of_fame = Column(Integer, nullable=False, default=0, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    meta_json = Column(Text, nullable=True)


class ModelLineage(Base):
    __tablename__ = "model_lineage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    child_model_id = Column(String(128), nullable=False, index=True)
    child_agent_id = Column(String(128), nullable=True, index=True)
    parent_model_id = Column(String(128), nullable=False, index=True)
    parent_checkpoint_id = Column(String(96), nullable=True, index=True)
    generation = Column(Integer, nullable=False, default=0, index=True)
    inheritance_mode = Column(String(64), nullable=False, default="full_clone_mutation")
    mutation_json = Column(Text, nullable=True)
    episode_id = Column(String(96), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


Index("ix_model_results_episode_agent", ModelEpisodeResult.episode_id, ModelEpisodeResult.agent_id)
Index("ix_model_transitions_episode_agent_step", ModelTransition.episode_id, ModelTransition.agent_id, ModelTransition.step_index)
Index("ix_model_checkpoints_hof_score", ModelCheckpoint.is_hall_of_fame, ModelCheckpoint.score)
Index("ix_model_lineage_child_parent", ModelLineage.child_model_id, ModelLineage.parent_model_id)


__all__ = [
    "ModelCheckpoint",
    "ModelEpisodeResult",
    "ModelLineage",
    "ModelTransition",
    "TrainingEpisode",
]
