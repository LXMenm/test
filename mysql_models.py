"""
MySQL ORM 模型定义
用于后续将 JSON / JSONL 存储逐步迁移到 SQLAlchemy + MySQL。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import JSON

from db import Base


class TimestampMixin:
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class FarmerProfileORM(TimestampMixin, Base):
    __tablename__ = "farmer_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    farmer_id = Column(String(64), nullable=False, unique=True, index=True)

    name = Column(String(128), nullable=True)
    schema_version = Column(String(16), nullable=False, default="1.2")
    profile_updated_at = Column(DateTime, nullable=True)
    active_base_id = Column(String(64), nullable=True, index=True)
    confirm_when_low_confidence = Column(Boolean, nullable=False, default=True)

    farm_scale = Column(String(32), nullable=True)
    pesticide_access_level = Column(String(32), nullable=True)
    equipment_json = Column(JSON, nullable=True)

    cultivation_mode = Column(String(32), nullable=True)
    experience_level = Column(String(32), nullable=True)
    risk_preference = Column(String(32), nullable=True)

    constraints_json = Column(JSON, nullable=True)
    meta_json = Column(JSON, nullable=True)

    __table_args__ = (
        Index("idx_farmer_profiles_name", "name"),
    )


class FarmBaseORM(TimestampMixin, Base):
    __tablename__ = "farm_bases"

    id = Column(Integer, primary_key=True, autoincrement=True)

    farmer_id = Column(String(64), nullable=False, index=True)
    base_id = Column(String(64), nullable=False, unique=True, index=True)
    internal_base_uid = Column(String(64), nullable=True, index=True)

    name = Column(String(128), nullable=True)
    location = Column(String(255), nullable=True)

    province = Column(String(64), nullable=True)
    city = Column(String(64), nullable=True)
    district = Column(String(64), nullable=True)

    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    facility = Column(String(64), nullable=True)
    environment = Column(Text, nullable=True)
    growth_stage = Column(String(64), nullable=True, index=True)
    sowing_date = Column(String(32), nullable=True)

    weather_snapshot = Column(Text, nullable=True)
    relative_humidity_2m = Column(Float, nullable=True)
    precipitation = Column(Float, nullable=True)
    rain_risk = Column(Float, nullable=True)

    risk_tags_json = Column(JSON, nullable=True)
    risk_reasons_json = Column(JSON, nullable=True)
    risk_items_json = Column(JSON, nullable=True)
    risk_updated_at = Column(DateTime, nullable=True)

    notes = Column(Text, nullable=True)
    extra_json = Column(JSON, nullable=True)

    __table_args__ = (
        Index("idx_farm_bases_farmer_base", "farmer_id", "base_id"),
        Index("idx_farm_bases_geo", "latitude", "longitude"),
    )


class WeatherSnapshotORM(TimestampMixin, Base):
    __tablename__ = "weather_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)

    base_id = Column(String(64), nullable=True, index=True)
    farmer_id = Column(String(64), nullable=True, index=True)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)

    temperature = Column(Float, nullable=True)
    humidity = Column(Float, nullable=True)
    precipitation = Column(Float, nullable=True)
    rain_probability = Column(Float, nullable=True)

    weather_code = Column(String(32), nullable=True)
    weather_desc = Column(String(128), nullable=True)
    source = Column(String(64), nullable=False, default="open-meteo")

    snapshot_time = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    raw_json = Column(JSON, nullable=True)

    __table_args__ = (
        Index("idx_weather_snapshots_base_time", "base_id", "snapshot_time"),
    )


class DiagnosisEventORM(Base):
    __tablename__ = "diagnosis_events"

    id = Column(Integer, primary_key=True, autoincrement=True)

    event_id = Column(String(64), nullable=False, unique=True, index=True)
    trace_id = Column(String(64), nullable=False, index=True)
    ts = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    farmer_id = Column(String(64), nullable=True, index=True)
    base_id = Column(String(64), nullable=True, index=True)
    crop_type = Column(String(64), nullable=True, index=True)
    growth_stage = Column(String(64), nullable=True)

    final_disease = Column(String(128), nullable=True, index=True)
    final_confidence = Column(Float, nullable=True)
    final_source = Column(String(64), nullable=True)

    model_id = Column(String(64), nullable=True)
    model_display_name = Column(String(128), nullable=True, index=True)

    status = Column(String(32), nullable=True, index=True)
    need_confirm = Column(Boolean, nullable=True)
    personalization_applied = Column(Boolean, nullable=True, default=False)
    filtered = Column(Boolean, nullable=True, default=False)
    workflow_degraded = Column(Boolean, nullable=True, default=False)

    elapsed_ms = Column(Float, nullable=True)

    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)

    symptoms_json = Column(JSON, nullable=True)
    image_result_json = Column(JSON, nullable=True)
    fallback_reason_json = Column(JSON, nullable=True)
    rule_result_json = Column(JSON, nullable=True)
    treatment_json = Column(JSON, nullable=True)
    verification_result_json = Column(JSON, nullable=True)
    verification_issues_json = Column(JSON, nullable=True)
    risk_tags_json = Column(JSON, nullable=True)
    risk_items_json = Column(JSON, nullable=True)
    text_top3_json = Column(JSON, nullable=True)
    fusion_top3_json = Column(JSON, nullable=True)
    diagnosis_evidence_json = Column(JSON, nullable=True)
    meta_json = Column(JSON, nullable=True)

    payload_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_diagnosis_events_trace_ts", "trace_id", "ts"),
        Index("idx_diagnosis_events_disease_ts", "final_disease", "ts"),
        Index("idx_diagnosis_events_farmer_ts", "farmer_id", "ts"),
        Index("idx_diagnosis_events_base_ts", "base_id", "ts"),
    )


class TraceEventORM(Base):
    __tablename__ = "trace_events"

    id = Column(Integer, primary_key=True, autoincrement=True)

    trace_id = Column(String(64), nullable=False, index=True)
    seq = Column(Integer, nullable=False)

    node = Column(String(64), nullable=True, index=True)
    agent = Column(String(64), nullable=True)
    agent_id = Column(String(64), nullable=True)

    status = Column(String(32), nullable=True, index=True)
    message = Column(String(255), nullable=True)
    payload_json = Column(JSON, nullable=False)

    ts = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("trace_id", "seq", name="uq_trace_events_trace_seq"),
        Index("idx_trace_events_trace_ts", "trace_id", "ts"),
    )


class KBDiseaseORM(TimestampMixin, Base):
    __tablename__ = "kb_diseases"

    id = Column(Integer, primary_key=True, autoincrement=True)

    disease_name = Column(String(128), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    image_labels_json = Column(JSON, nullable=True)
    meta_json = Column(JSON, nullable=True)


class KBTreatmentORM(TimestampMixin, Base):
    __tablename__ = "kb_treatments"

    id = Column(Integer, primary_key=True, autoincrement=True)

    disease_name = Column(String(128), nullable=False, unique=True, index=True)
    treatment = Column(Text, nullable=True)
    prevention = Column(Text, nullable=True)

    actions_json = Column(JSON, nullable=True)
    ingredients_json = Column(JSON, nullable=True)
    meta_json = Column(JSON, nullable=True)


class KBRuleORM(TimestampMixin, Base):
    __tablename__ = "kb_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)

    rule_id = Column(String(64), nullable=True, unique=True, index=True)
    crop_type = Column(String(64), nullable=True, index=True)
    disease_name = Column(String(128), nullable=False, index=True)

    symptoms_json = Column(JSON, nullable=True)
    confidence = Column(Float, nullable=True)
    evidence = Column(Text, nullable=True)

    growth_stage_weights_json = Column(JSON, nullable=True)
    environment_weights_json = Column(JSON, nullable=True)
    meta_json = Column(JSON, nullable=True)


class KBSymptomMapORM(TimestampMixin, Base):
    __tablename__ = "kb_symptom_maps"

    id = Column(Integer, primary_key=True, autoincrement=True)

    symptom_key = Column(String(128), nullable=False, unique=True, index=True)
    canonical_symptom = Column(String(128), nullable=True)

    aliases_json = Column(JSON, nullable=True)
    disease_candidates_json = Column(JSON, nullable=True)
    meta_json = Column(JSON, nullable=True)
