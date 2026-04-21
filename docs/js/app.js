/* ═══════════════════════════════════════════════════════════════════════════
   PolyBot — 10-Agent AI Analysis Pipeline
   Runs entirely in-browser · OpenRouter API
═══════════════════════════════════════════════════════════════════════════ */

/* ── CONFIG ─────────────────────────────────────────────────────────────── */
const CFG = {
  URL:     'https://openrouter.ai/api/v1/chat/completions',
  REFERER: location.origin + location.pathname.replace(/\/$/, ''),
  FEE:     0.02,
  KELLY:   0.25,
  TIMEOUT: 90_000,
};

/* ── STORAGE ─────────────────────────────────────────────────────────────── */
const store = {
  get: (k, fb = null) => {
    try { const v = localStorage.getItem(k); return v === null ? fb : JSON.parse(v); }
    catch { return fb; }
  },
  set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};

/* ── AGENTS ──────────────────────────────────────────────────────────────── */
const AGENTS = [
  { id: 'scanner',     name: 'ScannerAgent',     icon: '🔍', stage: 'Stage 1 · Scan & Parse'  },
  { id: 'parser',      name: 'InputParserAgent',  icon: '📝', stage: 'Stage 1 · Scan & Parse'  },
  { id: 'research',    name: 'ResearchAgent',     icon: '🔬', stage: 'Stage 2 · Research'       },
  { id: 'predictor',   name: 'PredictorAgent',    icon: '🎯', stage: 'Stage 3 · Prediction'     },
  { id: 'analyst',     name: 'AnalystAgent',      icon: '📈', stage: 'Stage 4 · Debate'         },
  { id: 'skeptic',     name: 'SkepticAgent',      icon: '📉', stage: 'Stage 4 · Debate'         },
  { id: 'debate',      name: 'DebateAgent',       icon: '⚖️',  stage: 'Stage 4 · Debate'        },
  { id: 'scenario',    name: 'ScenarioAgent',     icon: '🎲', stage: 'Stage 5 · Scenarios'      },
  { id: 'validator',   name: 'ValidatorAgent',    icon: '✅', stage: 'Stage 6 · Validation'     },
  { id: 'synthesizer', name: 'SynthesizerAgent',  icon: '🧬', stage: 'Stage 7 · Synthesis'      },
  { id: 'scoring',     name: 'Decision Engine',   icon: '⭐', stage: 'Final Decision'           },
];

/* ── SYSTEM PROMPTS ──────────────────────────────────────────────────────── */
function getSystemPrompt(id) {
  const p = {
    scanner: `You are ScannerAgent in a multi-agent prediction analysis system.
Extract key entities from the user query and classify the event.
Respond with ONLY a valid JSON object — no markdown, no explanation:
{"event_type":"SPORTS|PREDICTION_MARKET|FINANCIAL|POLITICAL|OTHER","sport":"football|basketball|tennis|cricket|esports|other|null","participants":["name1","name2"],"competition":"string or null","bet_type_detected":"match_winner|over_under|btts|handicap|tournament|yes_no|player_prop|other","timeframe":"string","key_entities":["e1","e2"]}`,

    parser: `You are InputParserAgent in a multi-agent prediction analysis system.
Normalize the user query into a clear, unambiguous analysis target.
Respond with ONLY a valid JSON object:
{"canonical_query":"clear normalized question","outcome_to_analyze":"exactly what must happen for this bet to WIN","parsing_notes":"any ambiguities or clarifications"}`,

    research: `You are ResearchAgent in a multi-agent prediction analysis system.
Using your training knowledge, synthesize everything relevant about this event. Be factual and specific with statistics and recent context. If your knowledge may be outdated, say so.
Respond with ONLY a valid JSON object:
{"key_facts":["fact1","fact2","fact3","fact4","fact5"],"recent_form":"recent performance information","relevant_statistics":"key stats and numbers","historical_context":"relevant patterns and history","data_quality_score":0.0,"knowledge_note":"any caveats"}`,

    predictor: `You are PredictorAgent in a multi-agent prediction analysis system.
Based on all context provided, estimate the probability of the described outcome occurring. Be well-calibrated — avoid extremes unless truly warranted. Consider base rates.
Respond with ONLY a valid JSON object:
{"predicted_probability":0.0,"uncertainty_lower":0.0,"uncertainty_upper":0.0,"base_rate":"how often similar events occur","primary_driver":"biggest factor driving estimate","reasoning":"2-3 clear sentences"}`,

    analyst: `You are AnalystAgent in a multi-agent prediction analysis system.
Build the STRONGEST possible case FOR this outcome occurring. Be thorough and persuasive. Find every supporting factor.
Respond with ONLY a valid JSON object:
{"bull_case":"2-3 paragraphs making the strongest case for YES","bull_factors":["f1","f2","f3","f4"],"argument_strength":0.0,"key_evidence":"single most compelling piece of evidence"}`,

    skeptic: `You are SkepticAgent in a multi-agent prediction analysis system.
Build the STRONGEST possible case AGAINST this outcome. You MUST find significant concerns — never simply agree with the analyst. Challenge assumptions aggressively.
Respond with ONLY a valid JSON object:
{"bear_case":"2-3 paragraphs making the strongest case for NO","bear_factors":["f1","f2","f3","f4"],"counter_argument_strength":0.0,"key_weakness":"the single biggest flaw in the bull case"}`,

    debate: `You are DebateAgent in a multi-agent prediction analysis system.
You have seen both the bull case and bear case. Adjudicate the debate — who made the stronger argument and why?
Respond with ONLY a valid JSON object:
{"debate_winner":"BULL|BEAR|DRAW","winner_margin":0.0,"key_disagreements":["d1","d2"],"post_debate_probability_low":0.0,"post_debate_probability_high":0.0,"debate_summary":"2-3 sentences summarising what was most decisive"}`,

    scenario: `You are ScenarioAgent in a multi-agent prediction analysis system.
Model 4-5 distinct alternative scenarios. Probabilities must sum to approximately 1.0.
Respond with ONLY a valid JSON object:
{"scenarios":[{"name":"string","probability":0.0,"outcome":"WIN|LOSE|PUSH","description":"what happens","bet_impact":"effect on the bet"}],"dominant_scenario":"most likely name","tail_risk":"worst-case description"}`,

    validator: `You are ValidatorAgent in a multi-agent prediction analysis system.
Check the entire analysis for logical consistency, factual issues, and cognitive biases.
Common biases: recency bias, home-team bias, star-player bias, narrative fallacy, availability heuristic, confirmation bias.
Respond with ONLY a valid JSON object:
{"is_consistent":true,"validation_score":0.0,"cognitive_biases_detected":[],"logical_issues":[],"overconfidence_risk":false,"recommended_adjustment":0.0}`,

    synthesizer: `You are SynthesizerAgent in a multi-agent prediction analysis system.
Integrate ALL agent perspectives into a final coherent analysis. Surface disagreements — do NOT hide conflicts. Apply any validator adjustments to the probability.
Respond with ONLY a valid JSON object:
{"final_probability":0.0,"confidence_score":0.0,"narrative":"3-4 sentence plain-English synthesis","key_insights":["i1","i2","i3"],"conflicts_preserved":["c1"],"persona_probabilities":{"analyst":0.0,"skeptic":0.0,"predictor":0.0,"debate_adjusted":0.0,"consensus":0.0}}`,
  };
  return p[id] || '';
}

/* ── USER MESSAGES ───────────────────────────────────────────────────────── */
function getUserMessage(id, ctx) {
  const base = [
    `Query: "${ctx.query}"`,
    `Bet Type: ${ctx.betType}`,
    ctx.oddsStr  ? `Market Odds: ${ctx.oddsStr}`  : '',
    ctx.context  ? `Context: ${ctx.context}`       : '',
  ].filter(Boolean).join('\n');

  const add = (key) => ctx[key] ? `\n\n${key}: ${JSON.stringify(ctx[key])}` : '';

  const msgs = {
    scanner:     base,
    parser:      base + add('scanner'),
    research:    base + add('scanner') + add('parser'),
    predictor:   base + add('scanner') + add('parser') + add('research'),
    analyst:     base + add('scanner') + add('parser') + add('research') + add('predictor'),
    skeptic:     base + add('scanner') + add('parser') + add('research') + add('predictor'),
    debate:      base + add('predictor') + add('analyst') + add('skeptic'),
    scenario:    base + add('predictor') + add('analyst') + add('skeptic') + add('debate'),
    validator:   base + add('research') + add('predictor') + add('analyst') + add('skeptic') + add('debate') + add('scenario'),
    synthesizer: base + add('research') + add('predictor') + add('analyst') + add('skeptic') + add('debate') + add('scenario') + add('validator'),
  };
  return msgs[id] || base;
}

/* ── FALLBACKS ───────────────────────────────────────────────────────────── */
function getFallback(id, ctx) {
  return ({
    scanner:     { event_type: 'OTHER', sport: null, participants: [], bet_type_detected: ctx.betType, key_entities: [] },
    parser:      { canonical_query: ctx.query, outcome_to_analyze: ctx.query, parsing_notes: '' },
    research:    { key_facts: ['Research unavailable'], data_quality_score: 0.35, recent_form: 'Unknown', relevant_statistics: 'N/A', historical_context: 'N/A' },
    predictor:   { predicted_probability: 0.5, uncertainty_lower: 0.35, uncertainty_upper: 0.65, reasoning: 'Insufficient data', base_rate: 'Unknown' },
    analyst:     { bull_case: 'Bull case analysis failed.', bull_factors: [], argument_strength: 0.45 },
    skeptic:     { bear_case: 'Bear case analysis failed.', bear_factors: [], counter_argument_strength: 0.45 },
    debate:      { debate_winner: 'DRAW', winner_margin: 0, post_debate_probability_low: 0.4, post_debate_probability_high: 0.6, debate_summary: 'Debate inconclusive.' },
    scenario:    { scenarios: [], dominant_scenario: 'Unknown', tail_risk: 'Unknown' },
    validator:   { is_consistent: true, validation_score: 0.6, cognitive_biases_detected: [], logical_issues: [], recommended_adjustment: 0 },
    synthesizer: { final_probability: ctx.predictor?.predicted_probability ?? 0.5, confidence_score: 0.45, narrative: 'Partial analysis only.', key_insights: [], conflicts_preserved: [], persona_probabilities: {} },
  })[id] || {};
}

/* ── LLM CALL ────────────────────────────────────────────────────────────── */
async function callLLM(systemPrompt, userMessage, apiKey, model) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), CFG.TIMEOUT);
  try {
    const res = await fetch(CFG.URL, {
      method: 'POST',
      headers: {
        'Authorization':  `Bearer ${apiKey}`,
        'Content-Type':   'application/json',
        'HTTP-Referer':   CFG.REFERER,
        'X-Title':        'PolyBot',
      },
      body: JSON.stringify({
        model,
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user',   content: userMessage  },
        ],
        max_tokens:  1500,
        temperature: 0.25,
      }),
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error?.message || `HTTP ${res.status}`);
    }
    const data = await res.json();
    const content = data.choices?.[0]?.message?.content || '';
    return extractJSON(content);
  } finally {
    clearTimeout(timer);
  }
}

function extractJSON(text) {
  // direct
  try { return JSON.parse(text); } catch {}
  // strip ```json ... ```
  const fence = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fence) { try { return JSON.parse(fence[1].trim()); } catch {} }
  // first {...}
  const obj = text.match(/\{[\s\S]*\}/);
  if (obj)   { try { return JSON.parse(obj[0]); }           catch {} }
  throw new Error(`Cannot parse JSON: ${text.slice(0, 120)}`);
}

/* ── SCORING MATH ────────────────────────────────────────────────────────── */
function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, +v || 0)); }

function parseOdds(str) {
  if (!str?.trim()) return null;
  const s = str.trim();
  if (s.endsWith('%')) {
    const p = parseFloat(s) / 100;
    return (p > 0 && p < 1) ? p : null;
  }
  if (s.startsWith('+')) {
    const n = parseFloat(s.slice(1));
    return isNaN(n) ? null : 100 / (n + 100);
  }
  if (s.startsWith('-') && !s.includes('/')) {
    const n = parseFloat(s.slice(1));
    return isNaN(n) ? null : n / (n + 100);
  }
  if (s.includes('/')) {
    const [a, b] = s.split('/').map(Number);
    return (!isNaN(a) && !isNaN(b) && b > 0) ? b / (a + b) : null;
  }
  const d = parseFloat(s);
  return (!isNaN(d) && d > 1) ? 1 / d : null;
}

function computeDecision(ctx, oddsStr) {
  const sy = ctx.synthesizer || {};
  const pr = ctx.predictor   || {};
  const an = ctx.analyst     || {};
  const sk = ctx.skeptic     || {};
  const va = ctx.validator   || {};
  const re = ctx.research    || {};

  const p          = clamp(sy.final_probability     ?? pr.predicted_probability ?? 0.5, 0.01, 0.99);
  const confidence = clamp(sy.confidence_score      ?? 0.6,  0.05, 1);
  const dataQual   = clamp(re.data_quality_score    ?? 0.6,  0,    1);
  const argStr     = clamp(an.argument_strength     ?? 0.5,  0,    1);
  const ctrStr     = clamp(sk.counter_argument_strength ?? 0.5, 0, 1);
  const valScore   = clamp(va.validation_score      ?? 0.6,  0,    1);

  const composite =
    p          * 0.25 +
    confidence * 0.20 +
    dataQual   * 0.15 +
    argStr     * 0.15 +
    (1 - ctrStr) * 0.10 +
    valScore   * 0.10 +
    0.5        * 0.05;

  const impliedP   = parseOdds(oddsStr);
  const grossEdge  = impliedP != null ? p - impliedP              : null;
  const feeEdge    = grossEdge  != null ? grossEdge - CFG.FEE     : null;
  const adjEdge    = feeEdge    != null ? feeEdge * confidence    : null;

  let kelly = 0;
  if (impliedP != null && impliedP > 0 && impliedP < 1) {
    const b = (1 / impliedP) - 1;
    kelly = Math.max(0, ((b * p - (1 - p)) / b) * CFG.KELLY);
  }

  let risk = 0.20;
  if (dataQual < 0.4)           risk += 0.15;
  if (ctrStr > 0.65)            risk += 0.20;
  if (valScore < 0.5)           risk += 0.20;
  if (confidence < 0.5)         risk += 0.15;
  if (feeEdge != null && feeEdge < 0.03) risk += 0.10;
  if (kelly === 0 && impliedP != null)   risk += 0.20;
  const biases = va.cognitive_biases_detected || [];
  risk += Math.min(0.25, biases.length * 0.10);
  risk = clamp(risk, 0, 1);

  const riskLevel = risk < 0.30 ? 'LOW' : risk < 0.55 ? 'MEDIUM' : risk < 0.75 ? 'HIGH' : 'EXTREME';

  let decision;
  if (impliedP != null) {
    if (adjEdge >= 0.10 && confidence >= 0.65 && risk < 0.70 && kelly > 0)
      decision = 'BET';
    else if (feeEdge >= 0.03 || composite > 0.58)
      decision = 'WATCH';
    else
      decision = 'SKIP';
  } else {
    if (p >= 0.70 && confidence >= 0.65 && risk < 0.50)      decision = 'BET';
    else if (p >= 0.55 || composite > 0.58)                   decision = 'WATCH';
    else                                                       decision = 'SKIP';
  }

  return {
    decision, composite_score: composite,
    predicted_probability: p, confidence_score: confidence,
    implied_probability: impliedP,
    gross_edge: grossEdge, fee_adjusted_edge: feeEdge, adjusted_edge: adjEdge,
    kelly_fraction: kelly, risk_score: risk, risk_level: riskLevel, biases,
    bull_case:      an.bull_case      || null,
    bear_case:      sk.bear_case      || null,
    debate_summary: ctx.debate?.debate_summary || null,
    narrative:      sy.narrative      || null,
    key_insights:   sy.key_insights   || [],
    conflicts:      sy.conflicts_preserved || [],
    scenarios:      ctx.scenario?.scenarios || [],
    key_facts:      re.key_facts      || [],
    persona_probabilities: sy.persona_probabilities || {},
  };
}

/* ── PIPELINE ────────────────────────────────────────────────────────────── */
let _abort = false;

async function runPipeline(params, cbs) {
  const { query, betType, oddsStr, context, apiKey, model } = params;
  const { onStart, onDone, onError, onProgress } = cbs;
  const ctx = { query, betType, oddsStr, context };
  _abort = false;

  async function step(id) {
    if (_abort) throw new Error('cancelled');
    onStart(id);
    try {
      const result = await callLLM(getSystemPrompt(id), getUserMessage(id, ctx), apiKey, model);
      ctx[id] = result;
      onDone(id, result);
    } catch (err) {
      const fb = getFallback(id, ctx);
      ctx[id] = fb;
      onError(id, fb, err.message);
    }
    onProgress(AGENTS.findIndex(a => a.id === id) + 1, AGENTS.length);
  }

  await step('scanner');
  await step('parser');
  await step('research');
  await step('predictor');
  await Promise.all([step('analyst'), step('skeptic')]);
  await step('debate');
  await step('scenario');
  await step('validator');
  await step('synthesizer');

  if (_abort) throw new Error('cancelled');

  onStart('scoring');
  const result = computeDecision(ctx, oddsStr);
  onDone('scoring', result);
  onProgress(AGENTS.length, AGENTS.length);
  return result;
}

/* ── RESULT RENDERER ─────────────────────────────────────────────────────── */
function pct(v, decimals = 1) {
  return v != null ? (v * 100).toFixed(decimals) + '%' : '—';
}
function edge(v) {
  if (v == null) return '—';
  const s = (v * 100).toFixed(1);
  return (v > 0 ? '+' : '') + s + '%';
}

function renderResults(result, container) {
  const dec      = result.decision;
  const decClass = { BET: 'bet', WATCH: 'watch', SKIP: 'skip' }[dec] || 'skip';
  const decEmoji = { BET: '✅', WATCH: '👀', SKIP: '❌' }[dec];

  const edgeVal   = result.fee_adjusted_edge;
  const edgeClass = edgeVal == null ? 'neu' : edgeVal > 0 ? 'pos' : 'neg';

  let html = '';

  /* ── decision banner ── */
  html += `
    <div class="res-decision ${decClass}">
      <div class="res-dec-emoji">${decEmoji}</div>
      <div>
        <div class="res-dec-label">Decision</div>
        <div class="res-dec-word">${dec}</div>
      </div>
    </div>`;

  /* ── metrics ── */
  html += `<div class="metrics-grid">
    <div class="metric-card">
      <div class="metric-val">${pct(result.predicted_probability)}</div>
      <div class="metric-lbl">AI Probability</div>
    </div>
    <div class="metric-card">
      <div class="metric-val">${pct(result.confidence_score)}</div>
      <div class="metric-lbl">Confidence</div>
    </div>
    <div class="metric-card">
      <div class="metric-val ${edgeClass}">${edge(edgeVal)}</div>
      <div class="metric-lbl">Fee-Adj. Edge</div>
    </div>
    <div class="metric-card">
      <div class="metric-val">${result.kelly_fraction > 0 ? pct(result.kelly_fraction) : '0%'}</div>
      <div class="metric-lbl">Kelly Stake</div>
    </div>
  </div>`;

  /* ── risk chip ── */
  html += `<div class="risk-chip risk-${result.risk_level}">
    Risk: <strong>${result.risk_level}</strong> &nbsp;·&nbsp; Composite: ${pct(result.composite_score)}
    ${result.implied_probability != null ? `&nbsp;·&nbsp; Implied: ${pct(result.implied_probability)}` : ''}
  </div>`;

  /* ── narrative ── */
  if (result.narrative) {
    html += `<div class="res-card">
      <div class="res-card-title">🧠 Analysis Summary</div>
      <div class="res-card-text">${esc(result.narrative)}</div>
    </div>`;
  }

  /* ── bull / bear ── */
  if (result.bull_case) {
    html += `<div class="res-card bull">
      <div class="res-card-title">📈 Bull Case</div>
      <div class="res-card-text">${esc(result.bull_case)}</div>
    </div>`;
  }
  if (result.bear_case) {
    html += `<div class="res-card bear">
      <div class="res-card-title">📉 Bear Case</div>
      <div class="res-card-text">${esc(result.bear_case)}</div>
    </div>`;
  }

  /* ── debate ── */
  if (result.debate_summary) {
    html += `<div class="res-card debate">
      <div class="res-card-title">⚖️ Debate Verdict</div>
      <div class="res-card-text">${esc(result.debate_summary)}</div>
    </div>`;
  }

  /* ── key insights ── */
  if (result.key_insights?.length) {
    html += `<div class="res-card">
      <div class="res-card-title">💡 Key Insights</div>
      <ul class="ins-list">${result.key_insights.map(i => `<li>${esc(i)}</li>`).join('')}</ul>
    </div>`;
  }

  /* ── scenarios ── */
  if (result.scenarios?.length) {
    const rows = result.scenarios.map(s => {
      const oc = (s.outcome || '').toLowerCase();
      const cls = oc === 'win' ? 'sc-win' : oc === 'lose' ? 'sc-lose' : 'sc-push';
      return `<div class="scenario-row">
        <div class="sc-head">
          <span class="sc-name">${esc(s.name)}</span>
          <span class="sc-prob">${pct(s.probability)}</span>
          <span class="sc-badge ${cls}">${(s.outcome || 'N/A').toUpperCase()}</span>
        </div>
        <div class="sc-desc">${esc(s.description || '')}${s.bet_impact ? ' — ' + esc(s.bet_impact) : ''}</div>
      </div>`;
    }).join('');
    html += `<div class="res-card">
      <div class="res-card-title">🎲 Scenarios</div>
      ${rows}
    </div>`;
  }

  /* ── persona breakdown ── */
  const pp = result.persona_probabilities;
  const ppKeys = Object.keys(pp || {}).filter(k => pp[k] != null);
  if (ppKeys.length) {
    const bars = ppKeys.map(k => `
      <div class="persona-row">
        <span class="persona-name">${k}</span>
        <div class="persona-track"><div class="persona-bar" style="width:${clamp(pp[k],0,1)*100}%"></div></div>
        <span class="persona-pct">${pct(pp[k])}</span>
      </div>`).join('');
    html += `<div class="res-card">
      <div class="res-card-title">👥 Persona Breakdown</div>
      ${bars}
    </div>`;
  }

  /* ── biases ── */
  if (result.biases?.length) {
    html += `<div class="res-card warn">
      <div class="res-card-title">⚠️ Biases Detected</div>
      <ul class="ins-list">${result.biases.map(b => `<li>${esc(b)}</li>`).join('')}</ul>
    </div>`;
  }

  /* ── conflicts ── */
  if (result.conflicts?.length) {
    html += `<div class="res-card warn">
      <div class="res-card-title">⚡ Agent Conflicts</div>
      <ul class="ins-list">${result.conflicts.map(c => `<li>${esc(c)}</li>`).join('')}</ul>
    </div>`;
  }

  /* ── research facts ── */
  if (result.key_facts?.length) {
    html += `<div class="res-card">
      <div class="res-card-title">🔬 Research Facts</div>
      <ul class="ins-list">${result.key_facts.map(f => `<li>${esc(f)}</li>`).join('')}</ul>
    </div>`;
  }

  /* ── disclaimer ── */
  html += `<p class="disclaimer">⚠️ AI-generated analysis for informational purposes only. Not financial advice. Always bet responsibly and within your means.</p>`;

  container.innerHTML = html;
}

function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* ── AGENT CARD UI ───────────────────────────────────────────────────────── */
function createAgentCard(agent) {
  const div = document.createElement('div');
  div.className = 'agent-item pending';
  div.id = `ac-${agent.id}`;
  div.innerHTML = `
    <div class="ai-icon">${agent.icon}</div>
    <div class="ai-body">
      <div class="ai-name">${agent.name}</div>
      <div class="ai-snip" id="ac-snip-${agent.id}">Waiting…</div>
    </div>
    <div class="ai-ind" id="ac-ind-${agent.id}">
      <span class="ai-wait">·</span>
    </div>`;
  return div;
}

function setAgentStatus(id, status, snippet) {
  const card = document.getElementById(`ac-${id}`);
  const snip = document.getElementById(`ac-snip-${id}`);
  const ind  = document.getElementById(`ac-ind-${id}`);
  if (!card) return;

  card.className = `agent-item ${status}`;

  if (status === 'running') {
    if (snip) snip.textContent = 'Processing…';
    if (ind)  ind.innerHTML = '<div class="spinner"></div>';
  } else if (status === 'done') {
    if (snip) snip.textContent = snippet || 'Complete';
    if (ind)  ind.innerHTML = '<span class="ai-check">✓</span>';
  } else if (status === 'error') {
    if (snip) snip.textContent = 'Error — used fallback';
    if (ind)  ind.innerHTML = '<span class="ai-err">!</span>';
  }
}

function getSnippet(id, r) {
  if (!r) return '';
  const map = {
    scanner:     r.event_type ? `${r.event_type}${r.sport ? ' · ' + r.sport : ''}` : '',
    parser:      r.canonical_query?.slice(0, 55) || '',
    research:    r.data_quality_score != null ? `Data quality: ${(r.data_quality_score * 100).toFixed(0)}%` : '',
    predictor:   r.predicted_probability != null ? `P = ${(r.predicted_probability * 100).toFixed(1)}%` : '',
    analyst:     r.argument_strength != null ? `Strength: ${(r.argument_strength * 100).toFixed(0)}%` : '',
    skeptic:     r.counter_argument_strength != null ? `Counter: ${(r.counter_argument_strength * 100).toFixed(0)}%` : '',
    debate:      r.debate_winner ? `Winner: ${r.debate_winner}` : '',
    scenario:    r.dominant_scenario ? `Most likely: ${r.dominant_scenario}` : '',
    validator:   r.validation_score != null ? `Score: ${(r.validation_score * 100).toFixed(0)}%` : '',
    synthesizer: r.final_probability != null ? `Final P = ${(r.final_probability * 100).toFixed(1)}%` : '',
    scoring:     r.decision ? `→ ${r.decision}` : '',
  };
  return map[id] || '';
}

/* ── SCREEN MANAGEMENT ───────────────────────────────────────────────────── */
function showScreen(id) {
  document.querySelectorAll('.screen').forEach(s => {
    if (s.id === id) s.classList.remove('hidden');
    else             s.classList.add('hidden');
  });
  window.scrollTo(0, 0);
}

function showToast(msg, duration = 4000) {
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();
  const t = document.createElement('div');
  t.className = 'toast';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), duration);
}

/* ── MODEL HELPERS ───────────────────────────────────────────────────────── */
function getModelValue(selectEl, customEl) {
  return selectEl.value === '__custom__' ? (customEl?.value.trim() || '') : selectEl.value;
}

function hydrateSelect(selectEl, customWrapEl, customInputEl, savedModel) {
  if (!selectEl) return;
  const known = [...selectEl.options].filter(o => o.value !== '__custom__').map(o => o.value);
  if (known.includes(savedModel)) {
    selectEl.value = savedModel;
    customWrapEl?.classList.add('hidden');
  } else if (savedModel) {
    selectEl.value = '__custom__';
    customWrapEl?.classList.remove('hidden');
    if (customInputEl) customInputEl.value = savedModel;
  }
}

/* ── INIT ────────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {

  /* — saved state — */
  const savedKey   = store.get('apiKey',  '');
  const savedModel = store.get('model',   'meta-llama/llama-3.3-70b-instruct:free');

  /* — setup screen elements — */
  const sKeyEl    = document.getElementById('s-api-key');
  const sModelEl  = document.getElementById('s-model');
  const sCustWrap = document.getElementById('s-custom-wrap');
  const sCustEl   = document.getElementById('s-custom-model');

  if (sKeyEl)   sKeyEl.value = savedKey;
  hydrateSelect(sModelEl, sCustWrap, sCustEl, savedModel);

  sModelEl?.addEventListener('change', () =>
    sCustWrap?.classList.toggle('hidden', sModelEl.value !== '__custom__'));

  document.getElementById('btn-setup-save')?.addEventListener('click', () => {
    const key   = sKeyEl?.value.trim();
    const model = getModelValue(sModelEl, sCustEl);
    if (!key)   { showToast('Please enter your OpenRouter API key.'); return; }
    if (!model) { showToast('Please select or enter a model.');       return; }
    store.set('apiKey', key);
    store.set('model',  model);
    showScreen('screen-form');
  });

  /* — decide start screen — */
  showScreen(savedKey ? 'screen-form' : 'screen-setup');

  /* — bet type chips — */
  document.getElementById('chip-bet-type')?.addEventListener('click', e => {
    const chip = e.target.closest('.chip');
    if (!chip) return;
    document.querySelectorAll('#chip-bet-type .chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
  });

  /* — settings button / modal — */
  const modalEl    = document.getElementById('modal-settings');
  const mKeyEl     = document.getElementById('m-api-key');
  const mModelEl   = document.getElementById('m-model');
  const mCustWrap  = document.getElementById('m-custom-wrap');
  const mCustEl    = document.getElementById('m-custom-model');

  mModelEl?.addEventListener('change', () =>
    mCustWrap?.classList.toggle('hidden', mModelEl.value !== '__custom__'));

  function openModal() {
    if (mKeyEl)   mKeyEl.value = store.get('apiKey', '');
    hydrateSelect(mModelEl, mCustWrap, mCustEl, store.get('model', ''));
    modalEl?.classList.remove('hidden');
  }

  document.getElementById('btn-settings')?.addEventListener('click', openModal);

  document.getElementById('btn-modal-close')?.addEventListener('click', () =>
    modalEl?.classList.add('hidden'));

  modalEl?.addEventListener('click', e => {
    if (e.target === modalEl) modalEl.classList.add('hidden');
  });

  document.getElementById('btn-modal-save')?.addEventListener('click', () => {
    const key   = mKeyEl?.value.trim();
    const model = getModelValue(mModelEl, mCustEl);
    if (!key)   { showToast('API key required.');   return; }
    if (!model) { showToast('Model ID required.'); return; }
    store.set('apiKey', key);
    store.set('model',  model);
    modalEl?.classList.add('hidden');
  });

  /* — run analysis — */
  document.getElementById('btn-analyze')?.addEventListener('click', async () => {
    const query   = document.getElementById('f-query')?.value.trim();
    const oddsStr = document.getElementById('f-odds')?.value.trim();
    const context = document.getElementById('f-context')?.value.trim();
    const betType = document.querySelector('#chip-bet-type .chip.active')?.dataset.value || 'other';
    const apiKey  = store.get('apiKey', '');
    const model   = store.get('model',  '');

    if (!query)  { showToast('Please enter a question to analyze.'); return; }
    if (!apiKey) { showToast('No API key — opening settings.'); openModal(); return; }
    if (!model)  { showToast('No model selected — opening settings.'); openModal(); return; }

    /* set up pipeline screen */
    const shortQ = query.length > 60 ? query.slice(0, 57) + '…' : query;
    const pipeTitle = document.getElementById('pipe-title');
    if (pipeTitle) pipeTitle.textContent = shortQ;

    const listEl = document.getElementById('agent-list');
    if (listEl) {
      listEl.innerHTML = '';
      AGENTS.forEach(a => listEl.appendChild(createAgentCard(a)));
    }

    const progressEl = document.getElementById('progress-fill');
    if (progressEl) progressEl.style.width = '0%';

    const statusEl = document.getElementById('pipe-status');
    if (statusEl) statusEl.textContent = 'Initialising pipeline…';

    showScreen('screen-pipeline');

    try {
      const result = await runPipeline(
        { query, betType, oddsStr, context, apiKey, model },
        {
          onStart: (id) => {
            const ag = AGENTS.find(a => a.id === id);
            if (statusEl) statusEl.textContent = `Running ${ag?.name || id}…`;
            setAgentStatus(id, 'running', '');
          },
          onDone:  (id, r)      => setAgentStatus(id, 'done',  getSnippet(id, r)),
          onError: (id, _r, e)  => { setAgentStatus(id, 'error', ''); console.warn(id, e); },
          onProgress: (done, total) => {
            if (progressEl) progressEl.style.width = `${(done / total) * 100}%`;
          },
        },
      );

      /* render results */
      const rTitle = document.getElementById('results-title');
      if (rTitle) rTitle.textContent = shortQ;

      const rBody = document.getElementById('results-body');
      if (rBody) renderResults(result, rBody);

      showScreen('screen-results');

    } catch (err) {
      if (err.message !== 'cancelled') {
        showToast(`Analysis failed: ${err.message}`);
        showScreen('screen-form');
      }
    }
  });

  /* — cancel pipeline — */
  document.getElementById('btn-cancel')?.addEventListener('click', () => {
    _abort = true;
    showScreen('screen-form');
  });

  /* — new analysis — */
  document.getElementById('btn-new')?.addEventListener('click', () =>
    showScreen('screen-form'));
});
