"""
Pydantic data models for API request/response and internal data structures.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────

class DecisionType(str, Enum):
    BET = "BET"
    WATCH = "WATCH"
    SKIP = "SKIP"

class EventType(str, Enum):
    SPORTS = "sports"
    PREDICTION_MARKET = "prediction_market"
    FINANCIAL = "financial"
    POLITICAL = "political"
    OTHER = "other"

class AgentRole(str, Enum):
    SCANNER = "scanner"
    INPUT_PARSER = "input_parser"
    RESEARCH = "research"
    PREDICTOR = "predictor"
    ANALYST = "analyst"
    SKEPTIC = "skeptic"
    SCENARIO = "scenario"
    VALIDATOR = "validator"
    SYNTHESIZER = "synthesizer"
    SCORING = "scoring"

class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


# ─────────────────────────────────────────────────────────────────────────────
# Agent Output Models
# ─────────────────────────────────────────────────────────────────────────────

class AgentOutput(BaseModel):
    role: AgentRole
    agent_name: str
    status: str = "completed"  # pending | running | completed | error
    output: Dict[str, Any] = Field(default_factory=dict)
    reasoning: str = ""
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    processing_time_ms: int = 0
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    error: Optional[str] = None


class ParsedEvent(BaseModel):
    event_type: EventType = EventType.SPORTS
    sport: Optional[str] = None
    teams: List[str] = Field(default_factory=list)
    players: List[str] = Field(default_factory=list)
    outcome_description: str = ""
    timeframe: str = ""
    market_type: str = ""
    implied_probability: Optional[float] = None
    raw_query: str = ""


class ResearchData(BaseModel):
    sources: List[Dict[str, str]] = Field(default_factory=list)
    key_facts: List[str] = Field(default_factory=list)
    recent_news: List[str] = Field(default_factory=list)
    statistics: Dict[str, Any] = Field(default_factory=dict)
    data_quality_score: float = Field(0.5, ge=0.0, le=1.0)
    summary: str = ""


class PredictionOutput(BaseModel):
    predicted_probability: float = Field(0.5, ge=0.0, le=1.0)
    reasoning: str = ""
    key_factors: List[str] = Field(default_factory=list)
    uncertainty_factors: List[str] = Field(default_factory=list)


class AnalystOutput(BaseModel):
    bull_case: str = ""
    bull_factors: List[str] = Field(default_factory=list)
    argument_strength: float = Field(0.5, ge=0.0, le=1.0)
    supporting_evidence: List[str] = Field(default_factory=list)


class SkepticOutput(BaseModel):
    bear_case: str = ""
    bear_factors: List[str] = Field(default_factory=list)
    counter_argument_strength: float = Field(0.5, ge=0.0, le=1.0)
    risks: List[str] = Field(default_factory=list)
    flaws_in_analysis: List[str] = Field(default_factory=list)


class Scenario(BaseModel):
    name: str
    description: str
    probability: float = Field(0.0, ge=0.0, le=1.0)
    outcome: str
    impact: str


class ScenarioOutput(BaseModel):
    scenarios: List[Scenario] = Field(default_factory=list)
    most_likely_scenario: str = ""
    tail_risk: str = ""


class ValidationOutput(BaseModel):
    is_consistent: bool = True
    logical_issues: List[str] = Field(default_factory=list)
    data_quality_flags: List[str] = Field(default_factory=list)
    bias_warnings: List[str] = Field(default_factory=list)
    adjusted_confidence: float = Field(0.5, ge=0.0, le=1.0)
    validation_score: float = Field(0.5, ge=0.0, le=1.0)


class SynthesisOutput(BaseModel):
    summary: str = ""
    key_insights: List[str] = Field(default_factory=list)
    agent_agreement_level: float = Field(0.5, ge=0.0, le=1.0)
    conflicts: List[str] = Field(default_factory=list)
    final_probability: float = Field(0.5, ge=0.0, le=1.0)
    narrative: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Scoring & Decision Models
# ─────────────────────────────────────────────────────────────────────────────

class ScoreBreakdown(BaseModel):
    predicted_probability: float = 0.5
    confidence_score: float = 0.5
    data_quality: float = 0.5
    argument_strength: float = 0.5
    counter_argument_strength: float = 0.5
    risk_level: float = 0.5
    market_signal: float = 0.0
    validation_score: float = 0.5
    agent_agreement: float = 0.5

    # Weighted composite
    composite_score: float = 0.5
    edge: float = 0.0


class RiskWarning(BaseModel):
    level: RiskLevel = RiskLevel.MEDIUM
    warnings: List[str] = Field(default_factory=list)
    max_exposure_recommendation: str = ""


class FinalDecision(BaseModel):
    decision: DecisionType
    confidence_score: float = Field(0.5, ge=0.0, le=1.0)
    predicted_probability: float = Field(0.5, ge=0.0, le=1.0)
    edge: float = 0.0
    risk: RiskWarning
    score_breakdown: ScoreBreakdown
    explanation: str = ""
    reasoning_summary: str = ""
    bull_case: str = ""
    bear_case: str = ""
    scenarios: List[Scenario] = Field(default_factory=list)
    conflicts: List[str] = Field(default_factory=list)
    key_insights: List[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Analysis Session Models
# ─────────────────────────────────────────────────────────────────────────────

class AnalysisRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=1000)
    implied_probability: Optional[float] = Field(None, ge=0.0, le=1.0)
    market_odds: Optional[str] = None
    context: Optional[str] = None
    stream: bool = True


class AnalysisSession(BaseModel):
    session_id: str
    query: str
    status: str = "pending"  # pending | running | completed | error
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    agent_outputs: List[AgentOutput] = Field(default_factory=list)
    parsed_event: Optional[ParsedEvent] = None
    final_decision: Optional[FinalDecision] = None
    error: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# API Response Models
# ─────────────────────────────────────────────────────────────────────────────

class AnalysisResponse(BaseModel):
    session_id: str
    status: str
    message: str = ""


class SessionStatusResponse(BaseModel):
    session_id: str
    status: str
    agent_outputs: List[AgentOutput] = Field(default_factory=list)
    final_decision: Optional[FinalDecision] = None
    error: Optional[str] = None


class HistoryItem(BaseModel):
    session_id: str
    query: str
    decision: Optional[str] = None
    confidence: Optional[float] = None
    created_at: datetime
    status: str


class HistoryResponse(BaseModel):
    items: List[HistoryItem]
    total: int


class SSEEvent(BaseModel):
    event: str  # agent_start | agent_complete | session_complete | error
    data: Dict[str, Any]
