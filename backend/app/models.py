from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Problem(Base):
    __tablename__ = "problems"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str]
    category: Mapped[str]
    difficulty: Mapped[str]
    language: Mapped[str]
    description: Mapped[str] = mapped_column(Text)
    starter_code: Mapped[str] = mapped_column(Text)
    required_file: Mapped[str]
    required_function: Mapped[str]
    problem_key: Mapped[Optional[str]] = mapped_column(nullable=True)
    problem_type: Mapped[Optional[str]] = mapped_column(nullable=True)
    raw_definition_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class CompetitionRun(Base):
    __tablename__ = "competition_runs"

    id: Mapped[str] = mapped_column(primary_key=True, index=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id"), index=True)
    total_models: Mapped[int] = mapped_column(Integer)
    status: Mapped[str]
    model_names_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id"), index=True)
    model_name: Mapped[str]
    mode: Mapped[str]
    status: Mapped[str]
    stdout: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stderr: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    compile_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    time: Mapped[Optional[str]] = mapped_column(nullable=True)
    memory: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    score_earned: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score_possible: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score_percentage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    competition_run_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    quality_status: Mapped[Optional[str]] = mapped_column(nullable=True)
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    competition_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quality_breakdown_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quality_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_analysis_status: Mapped[Optional[str]] = mapped_column(nullable=True)
    ai_analysis_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ai_analysis_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_analysis_reviewer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_analysis_prompt_version: Mapped[Optional[str]] = mapped_column(
        nullable=True
    )
    ai_analysis_created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
    )
    ai_analysis_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    comparison_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    test_results: Mapped[list["EvaluationTestResult"]] = relationship(
        back_populates="evaluation_result",
        cascade="all, delete-orphan",
        order_by="EvaluationTestResult.id",
    )


class EvaluationTestResult(Base):
    __tablename__ = "evaluation_test_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    evaluation_result_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_results.id"),
        index=True,
    )
    test_id: Mapped[str]
    test_name: Mapped[str]
    status: Mapped[str]
    points_earned: Mapped[float] = mapped_column(Float)
    points_possible: Mapped[float] = mapped_column(Float)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    details_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    evaluation_result: Mapped[EvaluationResult] = relationship(
        back_populates="test_results"
    )
