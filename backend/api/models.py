"""
Pydantic data models — API contracts and internal data structures.
"""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────

class DecisionType(str, Enum):
    BET   = "BET"
    WATCH = "WATCH"
    SKIP  = "SKIP"


class EventType(str, Enum):
    SPORTS            = "sports"
    PREDICTION_MARKET = "prediction_market"
    FINANCIAL         = "financial"
    POLITICAL         = "political"
    OTHER             = "other"


class BetType(str, Enum):
    MATCH_WINNER     = "match_winner"
    OVER_UNDER       = "over_under"
    BTTS             = "btts"               # Both Teams To Score
    ASIAN_HANDICAP   = "asian_handicap"
    DOUBLE_CHANCE    = "double_chance"
    CLEAN_SHEET      = "clean_sheet"
    CORRECT_SCORE    = "correct_score"
    TOURNAMENT_WINNER= "tournament_winner"
    PLAYER_PROP      = "player_prop"
    OUTRIGHT         = "outright"
    YES_NO           = "yes_no"             # generic Polymarket Yes/No

    @property
    def label(self) -> str:
        return {
            "match_winner":     "Match Winner",
            "over_under":       "Over / Under",
            "btts":             "Both Teams to Score",
            "asian_handicap":   "Asian Handicap",
            "double_chance":    "Double Chance",
            "clean_sheet":      "Clean Sheet",
            "correct_score":    "Correct Score",
            "tournament_winner":"Tournament Winner",
            "player_prop":      "Player Prop",
            "outright":         "Outright",
            "yes_no":           "Yes / No",
        }.get(self.value, self.value)


class AgentRole(str, Enum):
    SCANNER      = "scanner"
    INPUT_PARSER = "input_parser"
    RESEARCH     = "research"
    PREDICTOR    = "predictor"
    ANALYST      = "analyst"
    SKEPTIC      = "skeptic"
    SCENARIO     = "scenario"
    VALIDATOR    = "validator"
    SYNTHESIZER  = "synthesizer"
    SCORING      = "scoring"


class RiskLevel(str, Enum):
    LOW     = "low"
    MEDIUM  = "medium"
    HIGH    = "high"
    EXTREME = "extreme"


# ─────────────────────────────────────────────────────────────────────────────
# Polymarket
# ─────────────────────────────────────────────────────────────────────────────

class PolymarketMarket(BaseModel):
    id:          str   = ""
    question:    str   = ""
    slug:        str   = ""
    description: str   = ""
    outcomes:    List[str] = Field(default_factory=lambda: ["Yes", "No"])
    prices:      List[float] = Field(default_factory=list)
    yes_prob:    Optional[float] = None
    no_prob:     Optional[float] = None
    volume_usd:  float = 0.0
    end_date:    Optional[str] = None
    url:         str   = ""
    active:      bool  = True


# ─────────────────────────────────────────────────────────────────────────────
# Agent outputs
# ─────────────────────────────────────────────────────────────────────────────

class AgentOutput(BaseModel):
    role:               AgentRole
    agent_name:         str
    status:             str = "completed"        # pending|running|completed|error
    output:             Dict[str, Any] = Field(default_factory=dict)
    reasoning:          str = ""
    confidence:         float = Field(0.5, ge=0.0, le=1.0)
    processing_time_ms: int   = 0
    timestamp:          datetime = Field(default_factory=datetime.utcnow)
    error:              Optional[str] = None


class ParsedEvent(BaseModel):
    event_type:          EventType = EventType.SPORTS
    sport:               Optional[str] = None
    teams:               List[str] = Field(default_factory=list)
    players:             List[str] = Field(default_factory=list)
    outcome_description: str = ""
    timeframe:           str = ""
    market_type:         str = ""
    bet_type:            BetType = BetType.MATCH_WINNER
    implied_probability: Optional[float] = None
    raw_query:           str = ""


class Scenario(BaseModel):
    name:        str
    description: str
    probability: float = Field(0.0, ge=0.0, le=1.0)
    outcome:     str
    impact:      str


class ScoreBreakdown(BaseModel):
    predicted_probability:    float = 0.5
    confidence_score:         float = 0.5
    data_quality:             float = 0.5
    argument_strength:        float = 0.5
    counter_argument_strength:float = 0.5
    risk_level:               float = 0.5
    market_signal:            float = 0.0
    validation_score:         float = 0.5
    agent_agreement:          float = 0.5
    composite_score:          float = 0.5
    edge:                     float = 0.0


class RiskWarning(BaseModel):
    level:                        RiskLevel = RiskLevel.MEDIUM
    warnings:                     List[str] = Field(default_factory=list)
    max_exposure_recommendation:  str = ""


class FinalDecision(BaseModel):
    decision:              DecisionType
    confidence_score:      float = Field(0.5, ge=0.0, le=1.0)
    predicted_probability: float = Field(0.5, ge=0.0, le=1.0)
    edge:                  float = 0.0
    risk:                  RiskWarning
    score_breakdown:       ScoreBreakdown
    explanation:           str = ""
    reasoning_summary:     str = ""
    bull_case:             str = ""
    bear_case:             str = ""
    scenarios:             List[Scenario] = Field(default_factory=list)
    conflicts:             List[str]      = Field(default_factory=list)
    key_insights:          List[str]      = Field(default_factory=list)
    polymarket_markets:    List[PolymarketMarket] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Session / API models
# ─────────────────────────────────────────────────────────────────────────────

class AnalysisRequest(BaseModel):
    query:               str     = Field(..., min_length=3, max_length=1000)
    bet_type:            BetType = BetType.MATCH_WINNER
    implied_probability: Optional[float] = Field(None, ge=0.0, le=1.0)
    market_odds:         Optional[str]   = None
    context:             Optional[str]   = None
    stream:              bool    = True


class AnalysisSession(BaseModel):
    session_id:     str
    query:          str
    bet_type:       BetType  = BetType.MATCH_WINNER
    status:         str      = "pending"
    created_at:     datetime = Field(default_factory=datetime.utcnow)
    completed_at:   Optional[datetime] = None
    agent_outputs:  List[AgentOutput]  = Field(default_factory=list)
    parsed_event:   Optional[ParsedEvent] = None
    final_decision: Optional[FinalDecision] = None
    error:          Optional[str] = None


class AnalysisResponse(BaseModel):
    session_id: str
    status:     str
    message:    str = ""


class SessionStatusResponse(BaseModel):
    session_id:     str
    status:         str
    agent_outputs:  List[AgentOutput] = Field(default_factory=list)
    final_decision: Optional[FinalDecision] = None
    error:          Optional[str] = None


class HistoryItem(BaseModel):
    session_id: str
    query:      str
    bet_type:   Optional[str]   = None
    decision:   Optional[str]   = None
    confidence: Optional[float] = None
    created_at: datetime
    status:     str


class HistoryResponse(BaseModel):
    items: List[HistoryItem]
    total: int
