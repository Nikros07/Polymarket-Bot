/**
 * AI Decision System — Frontend Application
 * ==========================================
 * Handles:
 *  - Analysis form submission
 *  - Server-Sent Events (SSE) for live agent streaming
 *  - Real-time agent activity feed
 *  - Results rendering (decision, scores, scenarios, etc.)
 *  - History sidebar
 */

const API_BASE = '';  // Same-origin; prefix empty (served by FastAPI)

// ── Agent Metadata ────────────────────────────────────────────────────────
const AGENT_META = {
  scanner:      { icon: '🔍', name: 'Scanner',     desc: 'Identifying event entities' },
  input_parser: { icon: '📋', name: 'Parser',      desc: 'Structuring the query' },
  research:     { icon: '📊', name: 'Research',    desc: 'Gathering intelligence' },
  predictor:    { icon: '🎯', name: 'Predictor',   desc: 'Estimating probability' },
  analyst:      { icon: '📈', name: 'Analyst',     desc: 'Building bull case' },
  skeptic:      { icon: '⚔️', name: 'Skeptic',     desc: 'Challenging the thesis' },
  debate:       { icon: '⚡', name: 'Debate',      desc: 'Moderating bull vs bear' },
  scenario:     { icon: '🌐', name: 'Scenarios',   desc: 'Modeling outcomes' },
  validator:    { icon: '✓',  name: 'Validator',   desc: 'Checking consistency' },
  synthesizer:  { icon: '⚖️', name: 'Synthesizer', desc: 'Merging perspectives' },
  scoring:      { icon: '🏆', name: 'Scoring',     desc: 'Computing final score' },
};

const TOTAL_AGENTS = 11;

// ── State ─────────────────────────────────────────────────────────────────
let currentSessionId = null;
let eventSource      = null;
let agentCards       = {};
let completedAgents  = 0;

// ── Init ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initSystem();
  loadHistory();
});

async function initSystem() {
  try {
    const res  = await fetch(`${API_BASE}/api/health`);
    const data = await res.json();
    setStatus('online', `${data.llm_provider} · ${data.llm_model}${data.demo_mode ? ' · DEMO' : ''}`);
    document.getElementById('llmModel').textContent = data.llm_model;

    const stats = await fetch(`${API_BASE}/api/stats`).then(r => r.json());
    document.getElementById('totalAnalyses').textContent = `${stats.total_analyses} analyses`;
  } catch (err) {
    setStatus('error', 'Backend unreachable');
  }
}

// ── Analysis Flow ─────────────────────────────────────────────────────────

async function startAnalysis() {
  const query = document.getElementById('queryInput').value.trim();
  if (!query) return;

  const odds  = document.getElementById('oddsInput').value.trim();
  const btn   = document.getElementById('analyzeBtn');

  btn.disabled = true;
  btn.querySelector('.btn-text').textContent = 'Analyzing...';

  resetState();
  showRunning(query);

  try {
    const res = await fetch(`${API_BASE}/api/analyze`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        market_odds: odds || null,
        stream: true,
      }),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    currentSessionId = data.session_id;

    connectSSE(currentSessionId);

  } catch (err) {
    showError(`Failed to start analysis: ${err.message}`);
    resetBtn();
  }
}

function connectSSE(sessionId) {
  if (eventSource) eventSource.close();

  eventSource = new EventSource(`${API_BASE}/api/analyze/${sessionId}/stream`);

  eventSource.addEventListener('agent_running', (e) => {
    const agent = JSON.parse(e.data);
    updateAgentCard(agent, 'running');
  });

  eventSource.addEventListener('agent_complete', (e) => {
    const agent = JSON.parse(e.data);
    updateAgentCard(agent, 'complete');
    completedAgents++;
    updateProgress();
  });

  eventSource.addEventListener('session_complete', (e) => {
    const session = JSON.parse(e.data);
    eventSource.close();
    eventSource = null;

    if (session.final_decision) {
      showResults(session.query, session.final_decision);
    } else {
      showError(session.error || 'Analysis completed without result');
    }
    resetBtn();
    loadHistory();
  });

  eventSource.addEventListener('error', (e) => {
    let errMsg = 'Unknown error';
    try { errMsg = JSON.parse(e.data).error; } catch {}
    showError(errMsg);
    eventSource.close();
    resetBtn();
  });

  eventSource.onerror = (e) => {
    if (eventSource && eventSource.readyState === EventSource.CLOSED) {
      // Normal close after session_complete — do nothing
      return;
    }
    if (eventSource && eventSource.readyState === EventSource.CONNECTING) {
      // Transient network issue — SSE will auto-reconnect, just log it
      return;
    }
    // Persistent error
    showError('Connection to analysis stream lost. Please try again.');
    if (eventSource) { eventSource.close(); eventSource = null; }
    resetBtn();
  };
}

// ── UI State Transitions ──────────────────────────────────────────────────

function resetState() {
  agentCards = {};
  completedAgents = 0;
  document.getElementById('agentFeed').innerHTML = '';
  document.getElementById('agentCount').textContent = `0/${TOTAL_AGENTS}`;
  hideAll();
}

function showRunning(query) {
  document.getElementById('welcomeState').classList.add('hidden');
  document.getElementById('runningState').classList.remove('hidden');
  document.getElementById('resultsState').classList.add('hidden');
  document.getElementById('runningQuery').textContent = query;
  document.getElementById('progressFill').style.width = '0%';
  document.getElementById('progressText').textContent = 'Initializing agents...';
  renderPipelineStages();
}

function showResults(query, decision) {
  document.getElementById('welcomeState').classList.add('hidden');
  document.getElementById('runningState').classList.add('hidden');
  document.getElementById('resultsState').classList.remove('hidden');
  renderDecision(query, decision);
}

function showError(msg) {
  document.getElementById('progressText').textContent = `Error: ${msg}`;
}

function hideAll() {
  document.getElementById('runningState').classList.add('hidden');
  document.getElementById('resultsState').classList.add('hidden');
}

function resetBtn() {
  const btn = document.getElementById('analyzeBtn');
  btn.disabled = false;
  btn.querySelector('.btn-text').textContent = 'Run Analysis';
}

function newAnalysis() {
  hideAll();
  document.getElementById('welcomeState').classList.remove('hidden');
  document.getElementById('queryInput').value = '';
  document.getElementById('oddsInput').value = '';
}

// ── Pipeline Stages Rendering ─────────────────────────────────────────────

function renderPipelineStages() {
  const stages = [
    { key: 'scan-parse',    label: 'Stage 1: Scan & Parse',   agents: ['scanner', 'input_parser'], icon: '📋' },
    { key: 'research',      label: 'Stage 2: Research',        agents: ['research'],                icon: '📊' },
    { key: 'predict',       label: 'Stage 3: Predict',         agents: ['predictor'],               icon: '🎯' },
    { key: 'analyze',       label: 'Stage 4: Analyze',         agents: ['analyst', 'skeptic'],      icon: '⚡' },
    { key: 'debate',        label: 'Stage 5: Debate',          agents: ['debate'],                  icon: '🥊' },
    { key: 'scenario',      label: 'Stage 6: Scenarios',       agents: ['scenario'],                icon: '🌐' },
    { key: 'validate',      label: 'Stage 7: Validate',        agents: ['validator'],               icon: '✓' },
    { key: 'synthesize',    label: 'Stage 8: Synthesize',      agents: ['synthesizer'],             icon: '⚖️' },
    { key: 'score',         label: 'Stage 9: Score',           agents: ['scoring'],                 icon: '🏆' },
  ];

  const container = document.getElementById('pipelineStages');
  container.innerHTML = stages.map(s => `
    <div class="stage-item pending" id="stage-${s.key}">
      <div class="stage-icon">${s.icon}</div>
      <div class="stage-info">
        <div class="stage-name">${s.label}</div>
        <div class="stage-desc">${s.agents.map(a => AGENT_META[a]?.name || a).join(', ')}</div>
      </div>
      <div class="stage-time" id="stage-time-${s.key}"></div>
      <div class="stage-status pending" id="stage-status-${s.key}">·</div>
    </div>
  `).join('');
}

function updateProgress() {
  const pct = Math.round((completedAgents / TOTAL_AGENTS) * 100);
  document.getElementById('progressFill').style.width = `${pct}%`;
  document.getElementById('agentCount').textContent = `${completedAgents}/${TOTAL_AGENTS}`;

  const labels = [
    'Scanning event...', 'Parsing query...', 'Gathering research...',
    'Computing prediction...', 'Building bull case...', 'Challenging thesis...',
    'Modeling scenarios...', 'Validating logic...', 'Synthesizing analysis...', 'Scoring decision...'
  ];
  const label = labels[Math.min(completedAgents, labels.length - 1)];
  document.getElementById('progressText').textContent = `${label} (${pct}%)`;
}

// ── Agent Feed ─────────────────────────────────────────────────────────────

function updateAgentCard(agent, status) {
  const role = agent.role;
  const meta = AGENT_META[role] || { icon: '🤖', name: agent.agent_name, desc: '' };
  const feedEl = document.getElementById('agentFeed');

  // Remove empty placeholder
  const empty = feedEl.querySelector('.af-empty');
  if (empty) empty.remove();

  if (!agentCards[role]) {
    // Create new card
    const card = document.createElement('div');
    card.className = `agent-card ${status}`;
    card.id = `agent-card-${role}`;
    card.innerHTML = buildAgentCardHTML(meta, agent, status);
    feedEl.insertBefore(card, feedEl.firstChild);
    agentCards[role] = card;
  } else {
    // Update existing
    const card = agentCards[role];
    card.className = `agent-card ${status}`;
    card.innerHTML = buildAgentCardHTML(meta, agent, status);
  }

  // Update pipeline stage
  updatePipelineStage(role, status);
}

function buildAgentCardHTML(meta, agent, status) {
  const conf = agent.confidence ? `${(agent.confidence * 100).toFixed(0)}%` : '—';
  const time = agent.processing_time_ms ? `${agent.processing_time_ms}ms` : '';
  const reasoning = (agent.reasoning || '').slice(0, 160);

  const statusLabel = { running: 'THINKING', complete: 'DONE', error: 'ERROR' }[status] || status.toUpperCase();

  return `
    <div class="ac-header">
      <span class="ac-icon">${meta.icon}</span>
      <span class="ac-name">${meta.name}</span>
      <span class="ac-status ${status}">${statusLabel}</span>
    </div>
    ${reasoning ? `<div class="ac-reasoning">${escapeHtml(reasoning)}</div>` : `<div class="ac-reasoning">${meta.desc}...</div>`}
    <div class="ac-meta">
      <span class="ac-conf ${status === 'complete' ? 'color-green' : 'color-blue'}">conf: ${conf}</span>
      ${time ? `<span class="ac-time">${time}</span>` : ''}
    </div>
  `;
}

function updatePipelineStage(role, status) {
  const stageMap = {
    scanner: 'scan-parse', input_parser: 'scan-parse',
    research: 'research',
    predictor: 'predict',
    analyst: 'analyze', skeptic: 'analyze',
    debate: 'debate',
    scenario: 'scenario',
    validator: 'validate',
    synthesizer: 'synthesize',
    scoring: 'score',
  };
  const stageKey = stageMap[role];
  if (!stageKey) return;

  const stageEl = document.getElementById(`stage-${stageKey}`);
  const statusEl = document.getElementById(`stage-status-${stageKey}`);
  if (!stageEl || !statusEl) return;

  if (status === 'running' && !stageEl.classList.contains('complete')) {
    stageEl.classList.remove('pending');
    stageEl.classList.add('running');
    statusEl.className = 'stage-status running';
    statusEl.textContent = '↻';
  } else if (status === 'complete') {
    stageEl.classList.remove('running', 'pending');
    stageEl.classList.add('complete');
    statusEl.className = 'stage-status complete';
    statusEl.textContent = '✓';
  }
}

// ── Results Rendering ─────────────────────────────────────────────────────

function renderDecision(query, d) {
  // Banner
  const banner = document.getElementById('decisionBanner');
  banner.className = `decision-banner ${d.decision}`;

  const decEl = document.getElementById('dbDecision');
  decEl.className = `db-decision ${d.decision}`;
  decEl.textContent = d.decision;

  document.getElementById('dbQuery').textContent = query;
  document.getElementById('dbProbability').textContent = pct(d.predicted_probability);
  document.getElementById('dbEdge').textContent = (d.edge >= 0 ? '+' : '') + pct(d.edge);
  document.getElementById('dbEdge').className = `dbm-value ${d.edge >= 0 ? 'color-green' : 'color-red'}`;
  document.getElementById('dbConfidence').textContent = pct(d.confidence_score);

  const riskEl = document.getElementById('dbRisk');
  riskEl.textContent = (d.risk?.level || 'MEDIUM').toUpperCase();
  riskEl.className = `dbm-value risk-value ${(d.risk?.level || 'medium').toLowerCase()}`;

  // Explanation
  document.getElementById('decisionExplanation').textContent = d.explanation || '—';

  // Bull / Bear
  document.getElementById('bullCase').textContent = d.bull_case || 'No bull case available.';
  document.getElementById('bearCase').textContent = d.bear_case || 'No bear case available.';

  const sb = d.score_breakdown;
  if (sb) {
    document.getElementById('bullStrength').textContent = pct(sb.argument_strength);
    document.getElementById('bearStrength').textContent = pct(1 - sb.counter_argument_strength);
  }

  // Scenarios
  renderScenarios(d.scenarios || []);

  // Score breakdown
  renderScoreBars(d.score_breakdown);

  // Risk warnings
  renderRiskWarnings(d.risk);

  // Conflicts
  renderConflicts(d.conflicts || []);

  // Insights
  renderInsights(d.key_insights || []);

  // Debate summary
  const debateEl = document.getElementById('debateSummaryText');
  const debateSection = document.getElementById('debateSection');
  if (d.debate_summary && debateEl) {
    debateEl.textContent = d.debate_summary;
    if (debateSection) debateSection.classList.remove('hidden');
  } else if (debateSection) {
    debateSection.classList.add('hidden');
  }

  // Sports Predictions
  renderSportsPredictions(d.sports_predictions);

  // Persona Breakdown
  renderPersonaBreakdown(d.persona_breakdown);

  // Narrative
  document.getElementById('narrativeText').textContent = d.reasoning_summary || '—';
}

function renderSportsPredictions(sp) {
  const section = document.getElementById('sportsPredictionsSection');
  if (!section) return;
  if (!sp || sp.home_win_probability == null) {
    section.classList.add('hidden');
    return;
  }
  section.classList.remove('hidden');

  const homeTeam = sp.home_team || 'Home';
  const awayTeam = sp.away_team || 'Away';

  // Helper: render a market row with probabilities and bet badge
  function marketRow(label, entries, betValue) {
    const betBadge = betValue && betValue !== 'NO BET'
      ? `<span class="bet-badge bet">${betValue} ✅ BET</span>`
      : betValue === 'NO BET' ? `<span class="bet-badge no-bet">NO BET</span>` : '';

    const bars = entries.map(e => {
      const p = e.prob != null ? e.prob : 0;
      const pct_val = (p * 100).toFixed(1);
      const isTop = entries.reduce((mx, x) => x.prob > mx ? x.prob : mx, 0) === p && p >= 0.5;
      const barColor = isTop ? 'var(--accent-green)' : p > 0.35 ? 'var(--accent-blue)' : 'var(--text-dim)';
      return `
        <div class="sp-entry">
          <div class="sp-label">${escapeHtml(e.label)}</div>
          <div class="sp-bar-wrap">
            <div class="sp-bar" style="width:${Math.max(4, p*100).toFixed(0)}%;background:${barColor}"></div>
          </div>
          <div class="sp-value" style="color:${barColor}">${pct_val}%</div>
        </div>`;
    }).join('');

    return `
      <div class="sp-market">
        <div class="sp-market-header">
          <span class="sp-market-label">${escapeHtml(label)}</span>
          ${betBadge}
        </div>
        ${bars}
      </div>`;
  }

  const html = `
    <div class="sp-teams">${escapeHtml(homeTeam)} <span class="sp-vs">vs</span> ${escapeHtml(awayTeam)}</div>
    <div class="sp-markets">
      ${marketRow('Match Winner', [
          { label: homeTeam, prob: sp.home_win_probability },
          { label: 'Draw',   prob: sp.draw_probability },
          { label: awayTeam, prob: sp.away_win_probability },
        ], sp.match_winner_bet)}
      ${sp.over_2_5_probability != null ? marketRow('Over / Under 2.5 Goals', [
          { label: 'Over 2.5',  prob: sp.over_2_5_probability },
          { label: 'Under 2.5', prob: sp.under_2_5_probability },
        ], sp.over_under_bet) : ''}
      ${sp.btts_yes_probability != null ? marketRow('Both Teams to Score', [
          { label: 'BTTS Yes', prob: sp.btts_yes_probability },
          { label: 'BTTS No',  prob: sp.btts_no_probability },
        ], sp.btts_bet) : ''}
    </div>`;

  document.getElementById('sportsPredictionsContent').innerHTML = html;
}

function renderPersonaBreakdown(pb) {
  const section = document.getElementById('personaSection');
  if (!section) return;
  if (!pb) {
    section.classList.add('hidden');
    return;
  }
  section.classList.remove('hidden');

  const personas = [
    { key: 'analyst',      label: 'Analyst (Data)',    weight: '30%', color: 'var(--accent-blue)' },
    { key: 'skeptic',      label: 'Skeptic (Bear)',    weight: '15%', color: 'var(--accent-red, #ef4444)' },
    { key: 'market_reader',label: 'Market Reader',     weight: '20%', color: 'var(--accent-amber)' },
    { key: 'heuristic',    label: 'Heuristic (Pattern)',weight: '20%',color: 'var(--accent-teal)' },
    { key: 'synthesizer',  label: 'Synthesizer (Meta)',weight: '15%', color: 'var(--accent-purple)' },
  ];

  const bars = personas.map(p => {
    const val = pb[p.key] ?? 0;
    return `
      <div class="persona-row">
        <div class="pr-label">
          <span>${escapeHtml(p.label)}</span>
          <span class="pr-weight">${p.weight}</span>
        </div>
        <div class="pr-bar-wrap">
          <div class="pr-bar" style="width:${(val*100).toFixed(0)}%;background:${p.color}"></div>
        </div>
        <div class="pr-value" style="color:${p.color}">${(val*100).toFixed(1)}%</div>
      </div>`;
  }).join('');

  const weightedPct = ((pb.weighted_probability || 0) * 100).toFixed(1);
  const herdPct = ((pb.herd_adjusted_probability || 0) * 100).toFixed(1);
  const disagPct = ((pb.disagreement || 0) * 100).toFixed(1);

  document.getElementById('personaContent').innerHTML = `
    <div class="persona-bars">${bars}</div>
    <div class="persona-aggregates">
      <div class="pa-item">
        <span class="pa-label">Weighted Prob</span>
        <span class="pa-value color-blue">${weightedPct}%</span>
      </div>
      <div class="pa-item">
        <span class="pa-label">Herd-Adjusted</span>
        <span class="pa-value color-green">${herdPct}%</span>
      </div>
      <div class="pa-item">
        <span class="pa-label">Disagreement σ</span>
        <span class="pa-value ${pb.disagreement > 0.1 ? 'color-amber' : 'color-teal'}">${disagPct}%</span>
      </div>
    </div>`;
}

function renderScenarios(scenarios) {
  const grid = document.getElementById('scenariosGrid');
  if (!scenarios.length) {
    document.getElementById('scenariosSection').classList.add('hidden');
    return;
  }
  document.getElementById('scenariosSection').classList.remove('hidden');
  const total = scenarios.reduce((s, x) => s + (x.probability || 0), 0);
  grid.innerHTML = scenarios.map(s => {
    const prob = s.probability || 0;
    const barPct = Math.min(100, (prob / Math.max(total, 1)) * 100);
    const color = prob > 0.35 ? 'var(--accent-green)' :
                  prob > 0.2  ? 'var(--accent-blue)'  :
                                'var(--accent-amber)';
    return `
      <div class="scenario-item">
        <div class="sc-name">${escapeHtml(s.name)}</div>
        <div class="sc-desc">${escapeHtml(s.description || s.impact || '')}</div>
        <div class="sc-prob" style="color:${color}">${pct(prob)}</div>
        <div class="sc-bar-wrap">
          <div class="sc-bar" style="width:${barPct}%;background:${color}"></div>
        </div>
      </div>
    `;
  }).join('');
}

function renderScoreBars(sb) {
  if (!sb) return;
  const metrics = [
    { label: 'Predicted Probability', key: 'predicted_probability', color: 'var(--accent-blue)' },
    { label: 'Confidence Score',      key: 'confidence_score',      color: 'var(--accent-teal)' },
    { label: 'Data Quality',          key: 'data_quality',          color: 'var(--accent-green)' },
    { label: 'Argument Strength',     key: 'argument_strength',     color: 'var(--accent-green)' },
    { label: 'Validation Score',      key: 'validation_score',      color: 'var(--accent-purple)' },
    { label: 'Composite Score',       key: 'composite_score',       color: 'var(--accent-amber)' },
  ];

  document.getElementById('scoreBars').innerHTML = metrics.map(m => {
    const val = sb[m.key] ?? 0;
    return `
      <div class="score-row">
        <div class="sr-label">${m.label}</div>
        <div class="sr-bar-wrap">
          <div class="sr-bar" style="width:${(val*100).toFixed(0)}%;background:${m.color}"></div>
        </div>
        <div class="sr-value">${pct(val)}</div>
      </div>
    `;
  }).join('');
}

function renderRiskWarnings(risk) {
  if (!risk) return;
  const container = document.getElementById('riskWarnings');
  const warnings = risk.warnings || [];
  container.innerHTML = warnings.map(w =>
    `<div class="risk-warn-item"><span class="rw-icon">⚠</span>${escapeHtml(String(w))}</div>`
  ).join('') + (risk.max_exposure_recommendation ?
    `<div class="risk-warn-item"><span class="rw-icon">💰</span>${escapeHtml(risk.max_exposure_recommendation)}</div>` : '');
}

function renderConflicts(conflicts) {
  const section = document.getElementById('conflictsSection');
  const list = document.getElementById('conflictsList');
  if (!conflicts.length) {
    section.classList.add('hidden');
    return;
  }
  section.classList.remove('hidden');
  list.innerHTML = conflicts.map(c => {
    if (typeof c === 'object' && c.conflict) {
      return `<div class="conflict-item"><div class="ci-agents">${(c.agents || []).join(' vs ')}</div>${escapeHtml(c.conflict)}</div>`;
    }
    return `<div class="conflict-item">${escapeHtml(String(c))}</div>`;
  }).join('');
}

function renderInsights(insights) {
  document.getElementById('insightsList').innerHTML = insights.map(i =>
    `<div class="insight-item"><div class="insight-dot"></div><span>${escapeHtml(String(i))}</span></div>`
  ).join('') || '<div class="insight-item"><div class="insight-dot"></div><span>No key insights extracted</span></div>';
}

// ── History ───────────────────────────────────────────────────────────────

async function loadHistory() {
  try {
    const data = await fetch(`${API_BASE}/api/history?limit=15`).then(r => r.json());
    const list  = document.getElementById('historyList');
    if (!data.items || !data.items.length) {
      list.innerHTML = '<div class="history-empty">No analyses yet</div>';
      return;
    }
    list.innerHTML = data.items.map(item => {
      const dec = item.decision || '—';
      const time = formatTime(item.created_at);
      return `
        <div class="history-item" onclick="loadSession('${item.session_id}')">
          <div class="hi-query">${escapeHtml(item.query)}</div>
          <div class="hi-meta">
            <span class="hi-decision ${dec}">${dec}</span>
            <span class="hi-time">${time}</span>
          </div>
        </div>
      `;
    }).join('');
  } catch {
    // silently fail
  }
}

async function loadSession(sessionId) {
  try {
    const data = await fetch(`${API_BASE}/api/analyze/${sessionId}`).then(r => r.json());
    if (data.final_decision) {
      resetState();
      // Try to get query from history list item
      const histItem = document.querySelector(`.history-item[onclick="loadSession('${sessionId}')"]`);
      const query = histItem ? histItem.querySelector('.hi-query')?.textContent || '' : '';
      showResults(query, data.final_decision);
    }
  } catch {}
}

// ── Helpers ───────────────────────────────────────────────────────────────

function setQuery(q) {
  document.getElementById('queryInput').value = q;
  document.getElementById('queryInput').focus();
}

function confirmDecision() {
  const decEl = document.getElementById('dbDecision');
  document.getElementById('modalDecisionText').textContent =
    `You are about to act on a ${decEl.textContent} recommendation. ` +
    `This system provides probabilistic analysis only — results are not guaranteed.`;
  document.getElementById('confirmModal').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('confirmModal').classList.add('hidden');
}

function setStatus(type, text) {
  const dot  = document.querySelector('.status-dot');
  const txt  = document.querySelector('.status-text');
  dot.className = `status-dot ${type}`;
  txt.textContent = text;
}

function pct(val) {
  if (val == null || isNaN(val)) return '—';
  return `${(val * 100).toFixed(1)}%`;
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatTime(isoStr) {
  try {
    const d = new Date(isoStr);
    const now = new Date();
    const diff = Math.floor((now - d) / 1000);
    if (diff < 60)     return 'just now';
    if (diff < 3600)   return `${Math.floor(diff/60)}m ago`;
    if (diff < 86400)  return `${Math.floor(diff/3600)}h ago`;
    return d.toLocaleDateString();
  } catch {
    return '—';
  }
}
