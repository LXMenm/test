/**
 * Shared trace timing helpers for AgentWorkflowPanel and regression tests.
 */

export const FIXED_AGENT_IDS = [
  'supervisor',
  'reception',
  'diagnosis',
  'kb_retrieval',
  'treatment',
  'verification',
  'final',
] as const;

export type FixedAgentId = (typeof FIXED_AGENT_IDS)[number];

export interface NormalizedEvent {
  seq?: number;
  ts?: string;
  tsMs?: number;
  agentId: FixedAgentId;
  nodeName: string;
  status: string;
  data: Record<string, unknown>;
}

export interface RawTraceEvent {
  seq?: number;
  ts?: string;
  node?: string;
  status?: string;
  agent?: string;
  agent_id?: string;
}

export interface AgentPhaseDurations {
  phase1Ms: number;
  phase2Ms: number;
}

export interface OverallPhaseDurations {
  phase1Ms: number;
  phase2Ms: number;
  totalMs: number;
}
export interface AgentRuntimeDurations extends AgentPhaseDurations {
  totalMs: number;
  phase1Open?: boolean;
  phase2Open?: boolean;
  missingStart?: boolean;
}

export const parseTsMs = (ts?: string): number | undefined => {
  if (!ts) return undefined;
  const ms = Date.parse(ts);
  return Number.isFinite(ms) ? ms : undefined;
};

export const formatDurationMs = (ms: number): string => {
  if (!Number.isFinite(ms) || ms <= 0) return '0.000s';
  if (ms < 1000) return `${(ms / 1000).toFixed(3)}s`;

  const seconds = ms / 1000;
  if (seconds >= 60) {
    const minutes = Math.floor(seconds / 60);
    const remainSeconds = seconds - minutes * 60;
    return `${minutes}m${remainSeconds.toFixed(1)}s`;
  }

  return `${seconds.toFixed(2)}s`;
};

export const compareEvents = (a: RawTraceEvent, b: RawTraceEvent): number => {
  const aSeq = typeof a.seq === 'number' && Number.isFinite(a.seq) ? a.seq : undefined;
  const bSeq = typeof b.seq === 'number' && Number.isFinite(b.seq) ? b.seq : undefined;
  const aHasSeq = typeof aSeq === 'number';
  const bHasSeq = typeof bSeq === 'number';
  if (aHasSeq && bHasSeq) return aSeq - bSeq;

  const aTs = parseTsMs(a.ts) ?? Number.MAX_SAFE_INTEGER;
  const bTs = parseTsMs(b.ts) ?? Number.MAX_SAFE_INTEGER;
  if (aTs !== bTs) return aTs - bTs;

  if (aHasSeq && !bHasSeq) return -1;
  if (!aHasSeq && bHasSeq) return 1;
  return 0;
};

export const shouldIncludeEvent = (event: RawTraceEvent, phaseStartMs?: number): boolean => {
  if (!phaseStartMs || !Number.isFinite(phaseStartMs)) return true;
  const tsMs = parseTsMs(event.ts);
  if (typeof tsMs !== 'number') return true;
  return tsMs >= (phaseStartMs - 120_000);
};

export const isWaitingForUserInputRawEvent = (event: RawTraceEvent): boolean => {
  const node = String(event.node || '').toLowerCase();
  const status = String(event.status || '').toLowerCase();
  const agent = String(event.agent || event.agent_id || '').toLowerCase();
  return (
    node === 'awaituserconfirmation'
    || status === 'waiting_for_supplement'
    || agent === 'await_user_confirmation'
  );
};

const TIMING_AGENT_ALIAS_MAP: Record<string, FixedAgentId> = {
  parse_input: 'reception',
  confirm_input: 'supervisor',
  confidence_gate: 'diagnosis',
  personalization: 'treatment',
  prescription: 'treatment',
  persist: 'treatment',
  validator: 'verification',
  verification: 'verification',
  compliance: 'verification',
  review: 'verification',
  final: 'final',
};

const mapTimingAgentId = (agentId?: string, nodeName?: string): FixedAgentId => {
  const agent = String(agentId || '').toLowerCase();
  if ((FIXED_AGENT_IDS as readonly string[]).includes(agent)) return agent as FixedAgentId;
  if (TIMING_AGENT_ALIAS_MAP[agent]) return TIMING_AGENT_ALIAS_MAP[agent];

  const node = String(nodeName || '').toLowerCase();
  if (node === 'final' || node.includes('final')) return 'final';
  if (node.includes('verification') || node.includes('validator') || node.includes('review') || node.includes('compliance')) return 'verification';
  if (node.includes('retrieve') || node.includes('kb')) return 'kb_retrieval';
  if (node.includes('diagnosis') || node.includes('confidence')) return 'diagnosis';
  if (node.includes('persist') || node.includes('prescription') || node.includes('personalization') || node.includes('treatment')) return 'treatment';
  if (agent.includes('verification') || agent.includes('validator') || agent.includes('review') || agent.includes('compliance')) return 'verification';
  if (node.includes('parse') || node.includes('input') || node.includes('reception')) return 'reception';
  return 'supervisor';
};

export const normalizeRawEventForTiming = (event: RawTraceEvent): NormalizedEvent => {
  const payload = (event as RawTraceEvent & { payload?: Record<string, unknown> }).payload;
  const inputs = (event as RawTraceEvent & { inputs?: Record<string, unknown> }).inputs;
  const outputs = (event as RawTraceEvent & { outputs?: Record<string, unknown> }).outputs;
  const ts = event.ts;
  const tsMs = parseTsMs(ts);
  const agentHint = String(event.agent_id || event.agent || payload?.agent_id || payload?.agent || '');
  const nodeName = String(event.node || agentHint || 'trace');

  let status = String(event.status || payload?.status || '').toLowerCase();
  if (!status && agentHint) {
    const step = String((event as RawTraceEvent & { step?: string }).step || '').toLowerCase();
    const isComplete = step.endsWith('_complete') || outputs?.is_complete === true;
    status = isComplete ? 'completed' : 'running';
  }

  return {
    seq: event.seq,
    ts,
    tsMs,
    agentId: mapTimingAgentId(agentHint, nodeName),
    nodeName,
    status,
    data: {
      ...(payload || {}),
      agent: agentHint || payload?.agent,
      agent_id: event.agent_id || payload?.agent_id,
      inputs: inputs || undefined,
      outputs: outputs || undefined,
    },
  };
};

export const isWorkflowTerminalRawEvent = (event: RawTraceEvent): boolean => {
  const node = String(event.node || '').toLowerCase();
  const status = String(event.status || '').toLowerCase();
  const payload = (event as RawTraceEvent & { payload?: Record<string, unknown> }).payload;
  const payloadStatus = String(payload?.status || '').toLowerCase();
  return (
    (node === 'final' && ['end', 'error', 'completed', 'done'].includes(status))
    || ['completed', 'pending_expert_review', 'manual_review_recommended', 'failed', 'cancelled'].includes(payloadStatus)
  );
};

export const isReplayTerminalWaitingEvent = (events: RawTraceEvent[], index: number): boolean => {
  const current = normalizeRawEventForTiming(events[index] || {});
  if (!isWaitingForUserInputEvent(current)) return false;

  for (let i = index + 1; i < events.length; i += 1) {
    const later = normalizeRawEventForTiming(events[i] || {});
    const sameSeq = typeof current.seq === 'number' && typeof later.seq === 'number' && current.seq === later.seq;
    if (sameSeq) continue;
    return false;
  }
  return true;
};

export const sliceCurrentPhaseEvents = (events: RawTraceEvent[], phaseStartMs?: number): RawTraceEvent[] => {
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

export const isSecondPhaseBoundaryEvent = (event: NormalizedEvent): boolean => {
  const node = String(event.nodeName || '').toLowerCase();
  if (node === 'confirmflow' && event.status === 'running') return true;
  const agent = String((event.data && (event.data.agent ?? event.data.agent_id)) || '').toLowerCase();
  return agent === 'confirm_input' || node === 'confirm_input';
};

export const isWaitingForUserInputEvent = (event: NormalizedEvent): boolean => {
  const node = String(event.nodeName || '').toLowerCase();
  const agent = String((event.data && (event.data.agent ?? event.data.agent_id)) || '').toLowerCase();
  const payloadStatus = String(
    (event.data && (
      event.data.status
      ?? (typeof event.data.payload === 'object' && event.data.payload !== null
        ? (event.data.payload as Record<string, unknown>).status
        : undefined)
    )) || '',
  ).toLowerCase();

  return (
    node === 'awaituserconfirmation'
    || payloadStatus === 'waiting_for_supplement'
    || agent === 'await_user_confirmation'
  );
};

export const calcPhaseDurationsByAgent = (
  events: NormalizedEvent[],
  nowMs: number,
  workflowDone: boolean,
): Record<FixedAgentId, AgentPhaseDurations> => {
  const runtime = calcAgentRuntimeByIntervals(events, nowMs, workflowDone);
  return Object.fromEntries(
    FIXED_AGENT_IDS.map((agentId) => [
      agentId,
      { phase1Ms: runtime[agentId].phase1Ms, phase2Ms: runtime[agentId].phase2Ms },
    ]),
  ) as Record<FixedAgentId, AgentPhaseDurations>;
};

export const calcAgentRuntimeByIntervals = (
  events: NormalizedEvent[],
  nowMs: number,
  workflowDone: boolean,
): Record<FixedAgentId, AgentRuntimeDurations> => {
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

  const totals = Object.fromEntries(
    FIXED_AGENT_IDS.map((agentId) => [agentId, { phase1Ms: 0, phase2Ms: 0, totalMs: 0, missingStart: false }]),
  ) as Record<FixedAgentId, AgentRuntimeDurations>;
  const openStarts = Object.fromEntries(FIXED_AGENT_IDS.map((agentId) => [agentId, { phase1: undefined as number | undefined, phase2: undefined as number | undefined }])) as Record<FixedAgentId, { phase1?: number; phase2?: number }>;

  const closeInterval = (agentId: FixedAgentId, phase: 'phase1' | 'phase2', endMs: number) => {
    const startMs = openStarts[agentId][phase];
    if (typeof startMs !== 'number') {
      totals[agentId].missingStart = true;
      return;
    }
    totals[agentId][phase === 'phase1' ? 'phase1Ms' : 'phase2Ms'] += Math.max(0, endMs - startMs);
    openStarts[agentId][phase] = undefined;
  };

  sorted.forEach((event, index) => {
    const phase: 'phase1' | 'phase2' = phaseBoundaryIndex >= 0 && index >= phaseBoundaryIndex ? 'phase2' : 'phase1';
    if (typeof event.tsMs !== 'number') return;

    if (event.status === 'running' || event.status === 'start') {
      if (typeof openStarts[event.agentId][phase] !== 'number') {
        openStarts[event.agentId][phase] = event.tsMs;
      }
      return;
    }

    if (event.status === 'completed' || event.status === 'end' || event.status === 'error') {
      closeInterval(event.agentId, phase, event.tsMs);
    }
  });

  FIXED_AGENT_IDS.forEach((agentId) => {
    (['phase1', 'phase2'] as const).forEach((phase) => {
      const startMs = openStarts[agentId][phase];
      if (typeof startMs !== 'number') return;
      const canGrow = !workflowDone;
      if (canGrow) {
        totals[agentId][phase === 'phase1' ? 'phase1Ms' : 'phase2Ms'] += Math.max(0, nowMs - startMs);
        totals[agentId][phase === 'phase1' ? 'phase1Open' : 'phase2Open'] = true;
      }
    });
    totals[agentId].totalMs = totals[agentId].phase1Ms + totals[agentId].phase2Ms;
  });

  return totals;
};

export const calcOverallPhaseDuration = (
  phaseDurations: Record<FixedAgentId, AgentPhaseDurations>,
): OverallPhaseDurations => {
  let phase1Ms = 0;
  let phase2Ms = 0;
  FIXED_AGENT_IDS.forEach((agentId) => {
    phase1Ms += phaseDurations[agentId]?.phase1Ms ?? 0;
    phase2Ms += phaseDurations[agentId]?.phase2Ms ?? 0;
  });
  return { phase1Ms, phase2Ms, totalMs: phase1Ms + phase2Ms };
};

export const calcWallClockPhaseDuration = (
  events: NormalizedEvent[],
  nowMs: number,
  workflowDone: boolean,
): OverallPhaseDurations => {
  const sorted = [...events]
    .filter((event) => typeof event.tsMs === 'number')
    .sort((a, b) => {
      const sa = typeof a.seq === 'number' ? a.seq : Number.MAX_SAFE_INTEGER;
      const sb = typeof b.seq === 'number' ? b.seq : Number.MAX_SAFE_INTEGER;
      if (sa !== sb) return sa - sb;
      return (a.tsMs ?? Number.MAX_SAFE_INTEGER) - (b.tsMs ?? Number.MAX_SAFE_INTEGER);
    });
  if (!sorted.length) return { phase1Ms: 0, phase2Ms: 0, totalMs: 0 };

  let phaseBoundaryIndex = -1;
  for (let i = 0; i < sorted.length; i += 1) {
    if (isSecondPhaseBoundaryEvent(sorted[i])) {
      phaseBoundaryIndex = i;
      break;
    }
  }

  const phase1 = phaseBoundaryIndex >= 0 ? sorted.slice(0, phaseBoundaryIndex) : sorted;
  const phase2 = phaseBoundaryIndex >= 0 ? sorted.slice(phaseBoundaryIndex) : [];
  const lastEventTs = sorted[sorted.length - 1].tsMs as number;
  const calcWindow = (phaseEvents: NormalizedEvent[]): number => {
    if (!phaseEvents.length) return 0;
    const firstTs = phaseEvents[0].tsMs as number;
    const lastTs = phaseEvents[phaseEvents.length - 1].tsMs as number;
    const isCurrentPhase = lastTs === lastEventTs;
    if (!workflowDone && isCurrentPhase) return Math.max(0, nowMs - firstTs);
    return Math.max(0, lastTs - firstTs);
  };

  const phase1Ms = calcWindow(phase1);
  const phase2Ms = calcWindow(phase2);
  const firstTs = sorted[0].tsMs as number;
  const lastTs = sorted[sorted.length - 1].tsMs as number;
  const totalMs = workflowDone ? Math.max(0, lastTs - firstTs) : Math.max(0, nowMs - firstTs);

  return { phase1Ms, phase2Ms, totalMs };
};

export const calcTracePhaseTiming = (events: RawTraceEvent[], nowMs: number): OverallPhaseDurations & {
  workflowDone: boolean;
  hasTraceTiming: boolean;
  byAgentRuntime: Record<FixedAgentId, AgentRuntimeDurations>;
} => {
  const normalized = events
    .map(normalizeRawEventForTiming)
    .filter((event) => typeof event.tsMs === 'number')
    .sort((a, b) => compareEvents(a, b));
  const workflowDone = events.some(isWorkflowTerminalRawEvent);
  const byAgentRuntime = calcAgentRuntimeByIntervals(normalized, nowMs, workflowDone);
  return {
    ...calcWallClockPhaseDuration(normalized, nowMs, workflowDone),
    workflowDone,
    hasTraceTiming: normalized.length > 0,
    byAgentRuntime,
  };
};
