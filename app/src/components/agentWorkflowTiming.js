/**
 * Shared trace timing helpers for AgentWorkflowPanel and regression tests.
 */

/** @typedef {{seq?: number, ts?: string, tsMs?: number, agentId: string, nodeName: string, status: string, data: Record<string, unknown>}} NormalizedEvent */
/** @typedef {{seq?: number, ts?: string, node?: string, status?: string, agent?: string, agent_id?: string}} RawTraceEvent */

export const FIXED_AGENT_IDS = [
  'supervisor',
  'reception',
  'diagnosis',
  'kb_retrieval',
  'treatment',
  'verification',
  'final',
];

export const parseTsMs = (ts) => {
  if (!ts) return undefined;
  const ms = Date.parse(ts);
  return Number.isFinite(ms) ? ms : undefined;
};

export const compareEvents = (a, b) => {
  const aHasSeq = typeof a.seq === 'number' && Number.isFinite(a.seq);
  const bHasSeq = typeof b.seq === 'number' && Number.isFinite(b.seq);
  if (aHasSeq && bHasSeq) return a.seq - b.seq;

  const aTs = parseTsMs(a.ts) ?? Number.MAX_SAFE_INTEGER;
  const bTs = parseTsMs(b.ts) ?? Number.MAX_SAFE_INTEGER;
  if (aTs !== bTs) return aTs - bTs;

  if (aHasSeq && !bHasSeq) return -1;
  if (!aHasSeq && bHasSeq) return 1;
  return 0;
};

export const shouldIncludeEvent = (event, phaseStartMs) => {
  if (!phaseStartMs || !Number.isFinite(phaseStartMs)) return true;
  const tsMs = parseTsMs(event.ts);
  if (typeof tsMs !== 'number') return true;
  return tsMs >= (phaseStartMs - 120_000);
};

export const sliceCurrentPhaseEvents = (events, phaseStartMs) => {
  const sorted = [...events].sort(compareEvents);
  if (!phaseStartMs || !Number.isFinite(phaseStartMs)) return sorted;

  let startIndex = -1;
  for (let i = sorted.length - 1; i >= 0; i -= 1) {
    const e = sorted[i] || {};
    const node = String(e.node || '').toLowerCase();
    const status = String(e.status || '').toLowerCase();
    const agent = String(e.agent || e.agent_id || '').toLowerCase();
    if ((node === 'confirmflow' && ['start', 'started', 'begin', 'running', '开始'].includes(status)) || agent === 'confirm_input') {
      startIndex = i;
      break;
    }
  }
  if (startIndex >= 0) return sorted.slice(startIndex);

  const filtered = sorted.filter((raw) => shouldIncludeEvent(raw, phaseStartMs));
  return filtered.length ? filtered : sorted;
};

export const isSecondPhaseBoundaryEvent = (event) => {
  const node = String(event.nodeName || '').toLowerCase();
  if (node === 'confirmflow' && event.status === 'running') return true;
  const agent = String((event.data && (event.data.agent ?? event.data.agent_id)) || '').toLowerCase();
  return agent === 'confirm_input' || node === 'confirm_input';
};

export const calcPhaseDurationsByAgent = (events, nowMs, workflowDone) => {
  const sorted = [...events].sort((a, b) => {
    const sa = typeof a.seq === 'number' ? a.seq : Number.MAX_SAFE_INTEGER;
    const sb = typeof b.seq === 'number' ? b.seq : Number.MAX_SAFE_INTEGER;
    if (sa !== sb) return sa - sb;
    return (a.tsMs ?? Number.MAX_SAFE_INTEGER) - (b.tsMs ?? Number.MAX_SAFE_INTEGER);
  });

  let phaseBoundaryIndex = -1;
  for (let i = 0; i < sorted.length; i += 1) {
    if (isSecondPhaseBoundaryEvent(sorted[i])) {
      phaseBoundaryIndex = i;
      break;
    }
  }

  const phase1 = phaseBoundaryIndex >= 0 ? sorted.slice(0, phaseBoundaryIndex) : sorted;
  const phase2 = phaseBoundaryIndex >= 0 ? sorted.slice(phaseBoundaryIndex) : [];

  const calcForPhase = (phaseEvents) => {
    const totals = Object.fromEntries(FIXED_AGENT_IDS.map((agentId) => [agentId, 0]));
    if (!phaseEvents.length) return totals;

    for (let i = 0; i < phaseEvents.length - 1; i += 1) {
      const current = phaseEvents[i];
      const next = phaseEvents[i + 1];
      if (typeof current.tsMs !== 'number' || typeof next.tsMs !== 'number') continue;
      totals[current.agentId] += Math.max(0, next.tsMs - current.tsMs);
    }

    const last = phaseEvents[phaseEvents.length - 1];
    if (!workflowDone && typeof last.tsMs === 'number') {
      totals[last.agentId] += Math.max(0, nowMs - last.tsMs);
    }

    return totals;
  };

  const phase1Totals = calcForPhase(phase1);
  const phase2Totals = calcForPhase(phase2);

  return Object.fromEntries(
    FIXED_AGENT_IDS.map((agentId) => [
      agentId,
      { phase1Ms: phase1Totals[agentId], phase2Ms: phase2Totals[agentId] },
    ]),
  );
};
