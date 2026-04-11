"""
AI Decision System — Streamlit Frontend
========================================
Start with:  streamlit run streamlit_app.py

This app calls the backend agents directly (no FastAPI server needed).
Set your API keys in .env before running.
"""
import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st
from dotenv import load_dotenv

# ── Bootstrap: ensure backend package is importable ───────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

# ── Page config (must be first Streamlit call) ─────────────────────────────
st.set_page_config(
    page_title="AI Decision System",
    page_icon="⬡",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"About": "OASIS Multi-Agent Decision Engine v2.0"},
)

# ── Custom CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Base ─────────────────────────────────────────────────────── */
html, body, [data-testid="stApp"] {
    background-color: #0a0c10;
    color: #e8edf5;
}
[data-testid="stSidebar"] {
    background-color: #0f1318;
    border-right: 1px solid #1e2535;
}
[data-testid="stSidebar"] * { color: #e8edf5 !important; }

/* ── Cards ─────────────────────────────────────────────────────── */
.decision-card {
    border-radius: 12px;
    padding: 24px 28px;
    margin-bottom: 20px;
    border: 1px solid #1e2535;
}
.bet-card   { border-top: 4px solid #22c55e; background: linear-gradient(135deg,#0f1a0f,#0a0c10); }
.watch-card { border-top: 4px solid #f59e0b; background: linear-gradient(135deg,#1a1500,#0a0c10); }
.skip-card  { border-top: 4px solid #ef4444; background: linear-gradient(135deg,#1a0a0a,#0a0c10); }

.decision-label-BET   { color:#22c55e; font-size:3rem; font-weight:900; letter-spacing:4px; }
.decision-label-WATCH { color:#f59e0b; font-size:3rem; font-weight:900; letter-spacing:4px; }
.decision-label-SKIP  { color:#ef4444; font-size:3rem; font-weight:900; letter-spacing:4px; }

/* ── Metric boxes ─────────────────────────────────────────────── */
.metric-box {
    background:#141820;
    border:1px solid #1e2535;
    border-radius:8px;
    padding:14px 18px;
    text-align:center;
}
.metric-value { font-size:1.6rem; font-weight:700; font-family:monospace; }
.metric-label { font-size:0.7rem; color:#7a8ba5; letter-spacing:1px; margin-top:2px; }

/* ── Bull / Bear ──────────────────────────────────────────────── */
.bull-box {
    background:#0a120a; border:1px solid #1e2535;
    border-left:4px solid #22c55e;
    border-radius:8px; padding:16px; margin-bottom:8px;
}
.bear-box {
    background:#120a0a; border:1px solid #1e2535;
    border-left:4px solid #ef4444;
    border-radius:8px; padding:16px; margin-bottom:8px;
}

/* ── Agent cards ──────────────────────────────────────────────── */
.agent-card {
    background:#141820; border:1px solid #1e2535;
    border-radius:8px; padding:10px 14px; margin-bottom:6px;
    font-size:0.82rem;
}
.agent-card.running  { border-color:#3b82f6; }
.agent-card.complete { border-color:#22c55e44; }
.agent-card.error    { border-color:#ef444466; }

/* ── Scenario bars ────────────────────────────────────────────── */
.scenario-row { margin-bottom:10px; }
.scenario-name { font-size:0.85rem; font-weight:600; margin-bottom:3px; }
.scenario-bar-bg { background:#1e2535; border-radius:4px; height:8px; }
.scenario-bar    { border-radius:4px; height:8px; }

/* ── Polymarket ───────────────────────────────────────────────── */
.pm-card {
    background:#0d1220; border:1px solid #1e3060;
    border-left:4px solid #3b82f6;
    border-radius:8px; padding:12px 16px; margin-bottom:8px;
}
.pm-question { font-size:0.88rem; font-weight:600; color:#93c5fd; }
.pm-meta     { font-size:0.75rem; color:#7a8ba5; margin-top:4px; }

/* ── Score bars ──────────────────────────────────────────────── */
.score-label { font-size:0.78rem; color:#7a8ba5; margin-bottom:2px; }
.score-bar-bg { background:#1e2535; border-radius:4px; height:6px; margin-bottom:8px; }
.score-bar    { border-radius:4px; height:6px; }

/* ── Risk badge ──────────────────────────────────────────────── */
.risk-low     { color:#22c55e; font-weight:700; }
.risk-medium  { color:#f59e0b; font-weight:700; }
.risk-high    { color:#ef4444; font-weight:700; }
.risk-extreme { color:#dc2626; font-weight:700; }

/* ── Info box ────────────────────────────────────────────────── */
.info-box {
    background:#111827; border:1px solid #1e2535; border-radius:8px;
    padding:14px 18px; margin-bottom:10px; font-size:0.84rem; color:#9ca3af;
    line-height:1.7;
}

/* ── Hide Streamlit chrome ───────────────────────────────────── */
#MainMenu {visibility:hidden;}
footer    {visibility:hidden;}
header    {visibility:hidden;}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Lazy imports (after sys.path is set)
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_resource
def _load_backend():
    """Import heavy backend modules once and cache."""
    from backend.core.orchestrator      import get_orchestrator
    from backend.services.polymarket_service import get_polymarket_service
    from backend.core.memory            import get_memory
    from backend.api.models             import BetType
    return get_orchestrator, get_polymarket_service, get_memory, BetType

try:
    get_orchestrator, get_polymarket_svc, get_memory, BetType = _load_backend()
    BACKEND_OK = True
except Exception as _be:
    BACKEND_OK = False
    _BACKEND_ERR = str(_be)


# ─────────────────────────────────────────────────────────────────────────────
# Async helper
# ─────────────────────────────────────────────────────────────────────────────

def run_async(coro):
    """Run an async coroutine from synchronous Streamlit context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=180)
        return loop.run_until_complete(coro)
    except Exception:
        return asyncio.run(coro)


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────

def render_sidebar():
    with st.sidebar:
        st.markdown("### ⬡ AI Decision System")
        st.markdown("<p style='color:#7a8ba5;font-size:0.75rem;'>OASIS Multi-Agent Engine v2.0</p>",
                    unsafe_allow_html=True)
        st.divider()

        # ── Input form ─────────────────────────────────────────────────────
        st.markdown("**EVENT QUERY**")
        query = st.text_area(
            "Question",
            placeholder="Will Bayern Munich win their next Bundesliga match?",
            height=90,
            label_visibility="collapsed",
        )

        # Bet type
        if BACKEND_OK:
            bet_options = {
                "Match Winner":      BetType.MATCH_WINNER,
                "Over / Under":      BetType.OVER_UNDER,
                "Both Teams Score":  BetType.BTTS,
                "Asian Handicap":    BetType.ASIAN_HANDICAP,
                "Double Chance":     BetType.DOUBLE_CHANCE,
                "Clean Sheet":       BetType.CLEAN_SHEET,
                "Correct Score":     BetType.CORRECT_SCORE,
                "Tournament Winner": BetType.TOURNAMENT_WINNER,
                "Player Prop":       BetType.PLAYER_PROP,
                "Yes / No (PM)":     BetType.YES_NO,
            }
        else:
            bet_options = {"Match Winner": "match_winner"}

        st.markdown("**BET TYPE**")
        bet_label = st.selectbox("Bet Type", list(bet_options.keys()),
                                  label_visibility="collapsed")
        bet_type = bet_options[bet_label]

        # Market odds
        st.markdown("**MARKET ODDS** *(optional)*")
        odds_input = st.text_input(
            "Odds", placeholder="e.g. 1.75  or  -140  or  57%",
            label_visibility="collapsed"
        )

        st.divider()

        # ── Run button ─────────────────────────────────────────────────────
        run_clicked = st.button(
            "▶  Run Analysis",
            type="primary",
            use_container_width=True,
            disabled=not BACKEND_OK,
        )

        if not BACKEND_OK:
            st.error(f"Backend error: {_BACKEND_ERR}")

        st.divider()

        # ── Quick examples ─────────────────────────────────────────────────
        st.markdown("**EXAMPLES**")
        examples = [
            "Will Bayern München win vs Dortmund?",
            "Will the Lakers beat the Celtics tonight?",
            "Will Bitcoin reach $120k before July 2025?",
            "Will Donald Trump be US president end of 2025?",
        ]
        for ex in examples:
            if st.button(ex[:42] + ("…" if len(ex) > 42 else ""),
                         use_container_width=True, key=f"ex_{ex[:10]}"):
                st.session_state["prefill_query"] = ex
                st.rerun()

        st.divider()

        # ── History ────────────────────────────────────────────────────────
        st.markdown("**RECENT ANALYSES**")
        _render_history_sidebar()

    # Handle prefilled queries
    if "prefill_query" in st.session_state:
        query = st.session_state.pop("prefill_query")

    return query.strip(), bet_type, odds_input.strip(), run_clicked


def _render_history_sidebar():
    if not BACKEND_OK:
        return
    try:
        memory = get_memory()
        rows   = run_async(memory.get_history(limit=8))
        if not rows:
            st.caption("No analyses yet")
            return
        for r in rows:
            dec  = r.get("decision", "—")
            col  = {"BET": "🟢", "WATCH": "🟡", "SKIP": "🔴"}.get(dec, "⚪")
            label = f"{col} {r['query'][:34]}{'…' if len(r['query'])>34 else ''}"
            if st.button(label, use_container_width=True, key=f"hist_{r['session_id']}"):
                st.session_state["load_session"] = r["session_id"]
                st.rerun()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Main analysis runner
# ─────────────────────────────────────────────────────────────────────────────

AGENT_META = {
    "scanner":      ("🔍", "Scanner"),
    "input_parser": ("📋", "Parser"),
    "research":     ("📊", "Research"),
    "predictor":    ("🎯", "Predictor"),
    "analyst":      ("📈", "Analyst"),
    "skeptic":      ("⚔️",  "Skeptic"),
    "scenario":     ("🌐", "Scenarios"),
    "validator":    ("✅", "Validator"),
    "synthesizer":  ("⚖️",  "Synthesis"),
    "scoring":      ("🏆", "Scoring"),
}


def run_analysis(query: str, bet_type, odds_input: str):
    """Run full pipeline with real-time progress display."""
    st.markdown(f"### 🔎 Analysing: *{query}*")

    # Progress containers
    prog_bar  = st.progress(0)
    prog_text = st.empty()
    agent_col, _ = st.columns([2, 1])

    agent_containers: Dict[str, Any] = {}
    completed = [0]

    def on_progress(agent_out):
        role   = agent_out.role if isinstance(agent_out.role, str) else agent_out.role.value
        icon, name = AGENT_META.get(role, ("🤖", role))

        if role not in agent_containers:
            with agent_col:
                agent_containers[role] = st.empty()

        status = agent_out.status
        conf   = f"{agent_out.confidence*100:.0f}%" if agent_out.confidence else "—"
        ms     = f"{agent_out.processing_time_ms}ms" if agent_out.processing_time_ms else ""
        reason = (agent_out.reasoning or "")[:140]

        border = {"running": "#3b82f6", "completed": "#22c55e55", "error": "#ef444466"}.get(status, "#1e2535")
        bg     = {"running": "#0d1525", "completed": "#0a120a",   "error": "#120a0a"  }.get(status, "#141820")
        badge  = {"running": "🔄 THINKING", "completed": "✓ DONE", "error": "✗ ERROR"}.get(status, status.upper())

        html = f"""<div style="background:{bg};border:1px solid {border};border-radius:8px;
                   padding:10px 14px;margin-bottom:6px;font-size:0.82rem;">
          <span style="font-size:1.1rem">{icon}</span>
          <strong style="margin-left:6px;color:#e8edf5">{name}</strong>
          <span style="float:right;font-size:0.7rem;color:#7a8ba5">{badge}</span>
          {f'<div style="color:#9ca3af;margin-top:5px;line-height:1.5">{reason}</div>' if reason else ''}
          <div style="color:#4a5570;font-size:0.7rem;margin-top:4px">conf: {conf}  {ms}</div>
        </div>"""

        agent_containers[role].markdown(html, unsafe_allow_html=True)

        if status == "completed":
            completed[0] += 1
            pct = min(completed[0] / 10, 1.0)
            prog_bar.progress(pct)
            prog_text.markdown(
                f"<span style='color:#7a8ba5;font-size:0.8rem'>"
                f"Agent {completed[0]}/10 done ({pct*100:.0f}%)</span>",
                unsafe_allow_html=True,
            )

    # Parse odds
    implied_prob = None
    if odds_input:
        try:
            from backend.services.market_service import get_market_service
            implied_prob = get_market_service().parse_odds(odds_input)
        except Exception:
            pass

    # Create & run session
    orchestrator = get_orchestrator()
    session_id   = orchestrator.create_session(query=query, bet_type=bet_type)

    prog_text.markdown("<span style='color:#7a8ba5;font-size:0.8rem'>Starting agents…</span>",
                       unsafe_allow_html=True)

    session = run_async(orchestrator.run_analysis(
        session_id=session_id,
        query=query,
        bet_type=bet_type,
        implied_probability=implied_prob,
        market_odds=odds_input or None,
        on_progress=on_progress,
    ))

    prog_bar.progress(1.0)
    prog_text.empty()

    if session.status == "error":
        st.error(f"Analysis failed: {session.error}")
        return

    st.session_state["last_session"] = session
    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Results renderer
# ─────────────────────────────────────────────────────────────────────────────

def render_results(session):
    fd = session.final_decision
    if not fd:
        st.error("No decision produced.")
        return

    dec   = str(fd.decision).replace("DecisionType.", "")
    prob  = fd.predicted_probability
    conf  = fd.confidence_score
    edge  = fd.edge
    risk  = fd.risk

    # ── Decision Banner ─────────────────────────────────────────────────────
    card_cls = {"BET": "bet-card", "WATCH": "watch-card", "SKIP": "skip-card"}.get(dec, "watch-card")
    edge_sign = "+" if edge >= 0 else ""
    edge_col  = "#22c55e" if edge >= 0.05 else ("#f59e0b" if edge >= 0 else "#ef4444")
    risk_level = str(risk.level).replace("RiskLevel.", "").lower() if risk else "medium"

    st.markdown(f"""
    <div class="decision-card {card_cls}">
      <div class="decision-label-{dec}">{dec}</div>
      <p style="color:#9ca3af;margin:6px 0 16px;font-size:0.9rem">{session.query}</p>
      <div style="display:flex;gap:28px;flex-wrap:wrap;">
        <div class="metric-box">
          <div class="metric-value" style="color:#93c5fd">{prob*100:.1f}%</div>
          <div class="metric-label">PROBABILITY</div>
        </div>
        <div class="metric-box">
          <div class="metric-value" style="color:{edge_col}">{edge_sign}{edge*100:.1f}%</div>
          <div class="metric-label">EDGE</div>
        </div>
        <div class="metric-box">
          <div class="metric-value" style="color:#a78bfa">{conf*100:.1f}%</div>
          <div class="metric-label">CONFIDENCE</div>
        </div>
        <div class="metric-box">
          <div class="metric-value risk-{risk_level}">{risk_level.upper()}</div>
          <div class="metric-label">RISK</div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Explanation ─────────────────────────────────────────────────────────
    if fd.explanation:
        st.markdown(f'<div class="info-box">💡 {fd.explanation}</div>', unsafe_allow_html=True)

    # ── Tabs ────────────────────────────────────────────────────────────────
    tabs = st.tabs(["📊 Analysis", "🌐 Polymarket", "📈 Scores", "⚠️ Risk", "📝 Full Report"])

    # TAB 1 — Analysis
    with tabs[0]:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### 📈 Bull Case")
            st.markdown(
                f'<div class="bull-box">{fd.bull_case or "Not available."}</div>',
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown("#### 📉 Bear Case")
            st.markdown(
                f'<div class="bear-box">{fd.bear_case or "Not available."}</div>',
                unsafe_allow_html=True,
            )

        # Scenarios
        if fd.scenarios:
            st.markdown("#### 🌐 Scenario Distribution")
            total_p = sum(s.probability for s in fd.scenarios)
            for sc in fd.scenarios:
                p   = sc.probability
                pct = min(int(p / max(total_p, 0.01) * 100), 100)
                clr = "#22c55e" if pct > 30 else ("#3b82f6" if pct > 20 else "#f59e0b")
                outcome_badge = {"WIN": "🟢", "LOSS": "🔴", "DRAW": "🟡"}.get(
                    sc.outcome.upper()[:4], "⚪")
                st.markdown(f"""
                <div class="scenario-row">
                  <div class="scenario-name">{outcome_badge} {sc.name}
                    <span style="color:#7a8ba5;font-weight:400;font-size:0.78rem"> — {sc.description}</span>
                    <span style="float:right;font-family:monospace;color:{clr}">{p*100:.0f}%</span>
                  </div>
                  <div class="scenario-bar-bg">
                    <div class="scenario-bar" style="width:{pct}%;background:{clr}"></div>
                  </div>
                </div>""", unsafe_allow_html=True)

        # Conflicts & Insights
        if fd.conflicts:
            st.markdown("#### ⚡ Agent Conflicts")
            for c in fd.conflicts:
                st.markdown(
                    f'<div style="background:#120d1a;border-left:4px solid #a855f7;'
                    f'border-radius:4px;padding:10px 14px;margin-bottom:6px;'
                    f'font-size:0.83rem;color:#c4b5fd">{c}</div>',
                    unsafe_allow_html=True,
                )

        if fd.key_insights:
            st.markdown("#### 💡 Key Insights")
            for ins in fd.key_insights:
                st.markdown(f"• {ins}")

    # TAB 2 — Polymarket
    with tabs[1]:
        markets = fd.polymarket_markets or []
        if markets:
            st.markdown(f"#### 🔵 {len(markets)} Polymarket Markets Found")
            for m in markets:
                yes_p = m.yes_prob or (m.prices[0] if m.prices else None)
                no_p  = m.no_prob  or (m.prices[1] if len(m.prices) > 1 else None)
                vol   = f"${m.volume_usd:,.0f}" if m.volume_usd else "—"
                end   = m.end_date or "—"

                yes_str = f"{yes_p*100:.1f}% Yes" if yes_p is not None else "—"
                no_str  = f"{no_p *100:.1f}% No"  if no_p  is not None else "—"
                url_btn = f'<a href="{m.url}" target="_blank" style="color:#93c5fd;font-size:0.75rem">→ View on Polymarket</a>' if m.url else ""

                st.markdown(f"""
                <div class="pm-card">
                  <div class="pm-question">{m.question}</div>
                  <div class="pm-meta">
                    🟢 {yes_str} &nbsp;|&nbsp; 🔴 {no_str}
                    &nbsp;|&nbsp; Vol: {vol}
                    &nbsp;|&nbsp; Ends: {end}
                    &nbsp;&nbsp;{url_btn}
                  </div>
                </div>""", unsafe_allow_html=True)
        else:
            st.info("No Polymarket markets found for this query. Try adjusting your question or bet type.")

            # Manual search
            st.markdown("**Manual Polymarket Search**")
            pm_q = st.text_input("Search Polymarket", placeholder="e.g. Bayern Munich win")
            if st.button("Search Polymarket", key="pm_manual"):
                with st.spinner("Searching…"):
                    svc   = get_polymarket_svc()
                    found = run_async(svc.search_markets(pm_q, "yes_no", limit=5))
                if found:
                    for m in found:
                        yes_p  = m.get("yes_prob")
                        vol    = f"${m.get('volume_usd',0):,.0f}"
                        st.markdown(f"""
                        <div class="pm-card">
                          <div class="pm-question">{m['question']}</div>
                          <div class="pm-meta">
                            🟢 {f"{yes_p*100:.1f}% Yes" if yes_p else "—"}
                            &nbsp;|&nbsp; Vol: {vol}
                            &nbsp;|&nbsp; <a href="{m.get('url','')}" target="_blank"
                            style="color:#93c5fd">→ Polymarket</a>
                          </div>
                        </div>""", unsafe_allow_html=True)
                else:
                    st.warning("No markets found.")

    # TAB 3 — Scores
    with tabs[2]:
        sb = fd.score_breakdown
        if sb:
            metrics = [
                ("Predicted Probability",    sb.predicted_probability,    "#3b82f6"),
                ("Confidence Score",         sb.confidence_score,         "#a78bfa"),
                ("Data Quality",             sb.data_quality,             "#22c55e"),
                ("Argument Strength",        sb.argument_strength,        "#22c55e"),
                ("Validation Score",         sb.validation_score,         "#14b8a6"),
                ("Agent Agreement",          sb.agent_agreement,          "#06b6d4"),
                ("Composite Score",          sb.composite_score,          "#f59e0b"),
            ]
            for label, val, clr in metrics:
                pct = int(val * 100)
                st.markdown(f"""
                <div class="score-label">{label} <span style="float:right;font-family:monospace;color:{clr}">{pct}%</span></div>
                <div class="score-bar-bg"><div class="score-bar" style="width:{pct}%;background:{clr}"></div></div>
                """, unsafe_allow_html=True)

            # Edge
            edge_clr = "#22c55e" if edge >= 0 else "#ef4444"
            st.markdown(f"""
            <div style="background:#141820;border:1px solid #1e2535;border-radius:8px;
                        padding:14px 18px;margin-top:12px;text-align:center;">
              <span style="color:#7a8ba5;font-size:0.8rem">EDGE vs MARKET</span><br>
              <span style="color:{edge_clr};font-size:2rem;font-weight:700;font-family:monospace">
                {'+' if edge >= 0 else ''}{edge*100:.2f}%
              </span>
            </div>""", unsafe_allow_html=True)

    # TAB 4 — Risk
    with tabs[3]:
        if risk:
            risk_label = str(risk.level).replace("RiskLevel.", "").lower()
            risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴", "extreme": "💀"}.get(risk_label, "⚪")
            st.markdown(f"**Risk Level:** {risk_emoji} <span class='risk-{risk_label}'>{risk_label.upper()}</span>",
                        unsafe_allow_html=True)
            if risk.max_exposure_recommendation:
                st.markdown(f"**Exposure Guidance:** {risk.max_exposure_recommendation}")
            st.markdown("---")
            for w in (risk.warnings or []):
                st.markdown(f"""<div style="background:#120a0a;border-left:4px solid #f59e0b;
                border-radius:4px;padding:10px 14px;margin-bottom:6px;font-size:0.83rem;
                color:#fcd34d">⚠ {w}</div>""", unsafe_allow_html=True)

        st.markdown("---")
        st.caption("⚠️ This system provides probabilistic analysis only. "
                   "All decisions and actions are solely your responsibility. "
                   "Past performance does not guarantee future results.")

    # TAB 5 — Full Report
    with tabs[4]:
        if fd.reasoning_summary:
            st.markdown("#### 📝 Analysis Narrative")
            st.markdown(f'<div class="info-box">{fd.reasoning_summary}</div>',
                        unsafe_allow_html=True)

        # Raw agent outputs
        if session.agent_outputs:
            st.markdown("#### 🤖 Agent Outputs")
            for ao in session.agent_outputs:
                role = ao.role if isinstance(ao.role, str) else ao.role.value
                icon, name = AGENT_META.get(role, ("🤖", role))
                with st.expander(f"{icon} {name}  —  conf: {ao.confidence*100:.0f}%  |  {ao.processing_time_ms}ms"):
                    if ao.reasoning:
                        st.markdown(f"**Reasoning:** {ao.reasoning}")
                    if ao.output:
                        st.json(ao.output)
                    if ao.error:
                        st.error(f"Error: {ao.error}")

    # ── Action row ──────────────────────────────────────────────────────────
    st.markdown("---")
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        if st.button("🔄 New Analysis", use_container_width=True):
            if "last_session" in st.session_state:
                del st.session_state["last_session"]
            st.rerun()
    with c2:
        if st.button("✅ Mark as Correct", use_container_width=True):
            st.session_state["record_outcome"] = (session.session_id, True)
    with c3:
        st.caption(f"Session ID: `{session.session_id[:16]}…`")

    # Record outcome
    if "record_outcome" in st.session_state:
        sid, correct = st.session_state.pop("record_outcome")
        try:
            run_async(get_memory().record_outcome(sid, "user_confirmed", correct))
            st.toast("✅ Outcome recorded — helps calibrate future predictions.")
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Welcome screen
# ─────────────────────────────────────────────────────────────────────────────

def render_welcome():
    st.markdown("""
    <div style="text-align:center;padding:60px 20px;">
      <div style="font-size:3.5rem;margin-bottom:16px">⬡</div>
      <h1 style="font-size:2rem;font-weight:800;margin-bottom:8px">AI Decision System</h1>
      <p style="color:#7a8ba5;font-size:1rem;max-width:520px;margin:0 auto 32px">
        Enter an event or prediction question in the sidebar to start
        a full 10-agent OASIS analysis.
      </p>
    </div>
    """, unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("""<div class="info-box">
        <strong style="color:#e8edf5">🤖 10 Specialized Agents</strong><br>
        Scanner → Parser → Research → Predictor → Analyst → Skeptic → Scenarios → Validator → Synthesis → Scoring
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown("""<div class="info-box">
        <strong style="color:#e8edf5">🔵 Polymarket Integration</strong><br>
        Automatically searches for related prediction markets and shows current probabilities & volumes.
        </div>""", unsafe_allow_html=True)
    with c3:
        st.markdown("""<div class="info-box">
        <strong style="color:#e8edf5">📊 Weighted Scoring</strong><br>
        BET / WATCH / SKIP based on edge, confidence, data quality, argument strength, and risk.
        </div>""", unsafe_allow_html=True)

    # Config check
    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")
    demo    = os.getenv("DEMO_MODE", "false").lower() == "true"
    if not api_key and not demo:
        st.warning("⚠️ No API key found. Add **ANTHROPIC_API_KEY** to your `.env` file, "
                   "or set **DEMO_MODE=true** to run with simulated responses.")
    elif demo:
        st.info("ℹ️ Running in **Demo Mode** — responses are simulated. "
                "Set DEMO_MODE=false and add an API key for real analysis.")
    else:
        st.success("✅ API key configured. System ready.")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    query, bet_type, odds_input, run_clicked = render_sidebar()

    # Load a past session from history
    if "load_session" in st.session_state:
        sid = st.session_state.pop("load_session")
        try:
            orchestrator = get_orchestrator()
            sess = orchestrator.get_session(sid)
            if not sess:
                mem  = get_memory()
                data = run_async(mem.get_session(sid))
                if data and data.get("final_decision"):
                    from backend.api.models import AnalysisSession, FinalDecision
                    sess = AnalysisSession(session_id=sid, query=data["query"],
                                           status=data["status"])
                    try:
                        sess.final_decision = FinalDecision(**data["final_decision"])
                    except Exception:
                        pass
            if sess:
                st.session_state["last_session"] = sess
        except Exception:
            pass

    # Run new analysis
    if run_clicked and query and BACKEND_OK:
        if "last_session" in st.session_state:
            del st.session_state["last_session"]
        run_analysis(query, bet_type, odds_input)
        return

    # Show results or welcome
    if "last_session" in st.session_state:
        render_results(st.session_state["last_session"])
    else:
        render_welcome()


if __name__ == "__main__":
    main()
