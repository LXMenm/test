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
  step?: string;
  message?: string;
  payload?: Record<string, unknown>;
  inputs?: Record<string, unknown>;
  outputs?: Record<string, unknown>;
  decision?: Record<string, unknown>;
}

export interface LightweightDiagnosisPhaseSummary {
  kind: 'lightweight_diagnosis_phase';
  started_at?: string;
  ended_at?: string;
  disease?: string;
  confidence?: number;
  need_confirm?: boolean;
  image_path?: string;
  confidence_gate_reasons: string[];
  raw_events: RawTraceEvent[];
}

export interface StructuredWorkflowPhaseSummary {
  kind: 'structured_workflow_phase';
  started_at?: string;
  ended_at?: string;
  raw_events: RawTraceEvent[];
}

export type TracePhaseSummary = LightweightDiagnosisPhaseSummary | StructuredWorkflowPhaseSummary;

export interface AgentPhaseDurations {
  phase1Ms: number;
  phase2Ms: number;
}

export interface OverallPhaseDurations {
  phase1Ms: number;
  phase2Ms: number;
  totalMs: number;
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

const isRecord = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);

export const getTracePayload = (event: RawTraceEvent): Record<string, unknown> => {
  return isRecord(event?.payload) ? event.payload : {};
};

const toLower = (v: unknown): string => String(v ?? '').trim().toLowerCase();

const inferAgentFromNode = (nodeName: string): string => {
  const node = toLower(nodeName);
  if (node.includes('parseinput') || node.includes('parse_input')) return 'parse_input';
  if (node.includes('diagnosis')) return 'diagnosis';
  if (node.includes('confidencegate') || node.includes('confidence_gate')) return 'confidence_gate';
  if (node.includes('final')) return 'final';
  if (node.includes('persist')) return 'persist';
  if (node.includes('verification') || node.includes('validator')) return 'verification';
  if (node.includes('treatment') || node.includes('prescription') || node.includes('personalization')) return 'treatment';
  if (node.includes('retrieve') || node.includes('kb')) return 'kb_retrieval';
  if (node.includes('confirm')) return 'confirm_input';
  return '';
};

export const resolveTraceNode = (event: RawTraceEvent): string => {
  return String(event.node || event.step || event.agent || 'trace');
};

export const resolveTraceAgentId = (event: RawTraceEvent): string => {
  const payload = getTracePayload(event);
  const resolved = String(
    event.agent_id
    || event.agent
    || payload.agent_id
    || payload.agent
    || inferAgentFromNode(resolveTraceNode(event)),
  ).trim();
  return resolved.toLowerCase();
};

export const isStructuredAgentTraceEvent = (event: RawTraceEvent): boolean => {
  return Boolean(event.agent || event.agent_id || event.step || isRecord(event.inputs) || isRecord(event.outputs) || isRecord(event.decision));
};

export const isLightweightTraceEvent = (event: RawTraceEvent): boolean => {
  if (!event) return false;
  if (isStructuredAgentTraceEvent(event)) return false;
  const node = toLower(resolveTraceNode(event));
  return Boolean(node) || isRecord(event.payload);
};

const readDisease = (payload: Record<string, unknown>): string => {
  return String(payload.final_disease || payload.disease || '').trim();
};

const readConfidence = (payload: Record<string, unknown>): number | undefined => {
  const raw = Number(payload.final_confidence ?? payload.confidence ?? payload.confidence_pct);
  if (!Number.isFinite(raw)) return undefined;
  return raw;
};

const lightweightSignature = (event: RawTraceEvent): string => {
  const payload = getTracePayload(event);
  return JSON.stringify({
    node: toLower(resolveTraceNode(event)),
    status: toLower(event.status),
    message: String(event.message || ''),
    agent: resolveTraceAgentId(event),
    disease: readDisease(payload),
    confidence: readConfidence(payload),
  });
};

const dedupRawTraceEvents = (events: RawTraceEvent[]): RawTraceEvent[] => {
  const sorted = [...events].sort(compareEvents);
  const seenSeq = new Set<number>();
  const seenSig = new Set<string>();
  const result: RawTraceEvent[] = [];
  sorted.forEach((event) => {
    if (typeof event.seq === 'number' && Number.isFinite(event.seq)) {
      if (seenSeq.has(event.seq)) return;
      seenSeq.add(event.seq);
    }
    const sig = lightweightSignature(event);
    if (seenSig.has(sig)) return;
    seenSig.add(sig);
    result.push(event);
  });
  return result;
};

export const collapseLightweightDiagnosisPhase = (events: RawTraceEvent[]): LightweightDiagnosisPhaseSummary[] => {
  const deduped = dedupRawTraceEvents(events).filter(isLightweightTraceEvent);
  const chunks: RawTraceEvent[][] = [];
  let current: RawTraceEvent[] = [];
  const flush = () => {
    if (current.length) chunks.push(current);
    current = [];
  };
  deduped.forEach((event) => {
    const node = toLower(resolveTraceNode(event));
    const status = toLower(event.status);
    const isStart = (node.includes('parseinput') || node.includes('parse_input') || node.includes('diagnosisagent') || node.includes('diagnosis_agent')) && status === 'start';
    if (isStart && current.length) flush();
    current.push(event);
    const isEnd = (node.includes('confidencegate') && status === 'end')
      || (node.includes('diagnosiscompleted') && status === 'end')
      || (node === 'final' && status === 'end');
    if (isEnd) flush();
  });
  flush();

  const phases = chunks.map((chunk): LightweightDiagnosisPhaseSummary => {
    const first = chunk[0];
    const last = chunk[chunk.length - 1];
    const payloadList = chunk.map(getTracePayload);
    const reversePayloads = [...payloadList].reverse();
    const disease = reversePayloads.map(readDisease).find(Boolean);
    const confidence = reversePayloads.map(readConfidence).find((v) => typeof v === 'number');
    const needConfirmPayload = reversePayloads.find((p) => typeof p.need_confirm === 'boolean');
    const imagePath = reversePayloads.map((p) => String(p.image_path || '')).find(Boolean);
    const confidenceReasons = reversePayloads
      .flatMap((p) => (Array.isArray(p.reasons) ? p.reasons : []))
      .map((r) => String(r).trim())
      .filter(Boolean);
    return {
      kind: 'lightweight_diagnosis_phase',
      started_at: first?.ts,
      ended_at: last?.ts,
      disease,
      confidence,
      need_confirm: needConfirmPayload ? Boolean(needConfirmPayload.need_confirm) : undefined,
      image_path: imagePath,
      confidence_gate_reasons: Array.from(new Set(confidenceReasons)),
      raw_events: chunk,
    };
  });

  const merged: LightweightDiagnosisPhaseSummary[] = [];
  phases.forEach((phase) => {
    const prev = merged[merged.length - 1];
    if (!prev) {
      merged.push(phase);
      return;
    }
    const sameDisease = prev.disease && phase.disease && prev.disease === phase.disease;
    const prevConf = typeof prev.confidence === 'number' ? prev.confidence : undefined;
    const phaseConf = typeof phase.confidence === 'number' ? phase.confidence : undefined;
    const closeConfidence = typeof prevConf === 'number' && typeof phaseConf === 'number' && Math.abs(prevConf - phaseConf) <= 0.03;
    if (sameDisease || closeConfidence) {
      merged[merged.length - 1] = {
        ...prev,
        ended_at: phase.ended_at || prev.ended_at,
        confidence_gate_reasons: Array.from(new Set([...prev.confidence_gate_reasons, ...phase.confidence_gate_reasons])),
        need_confirm: phase.need_confirm ?? prev.need_confirm,
        image_path: phase.image_path || prev.image_path,
        raw_events: [...prev.raw_events, ...phase.raw_events],
        confidence: phase.confidence ?? prev.confidence,
        disease: phase.disease || prev.disease,
      };
      return;
    }
    merged.push(phase);
  });
  return merged;
};

export const segmentTracePhases = (events: RawTraceEvent[]): TracePhaseSummary[] => {
  const deduped = dedupRawTraceEvents(events);
  const phases: TracePhaseSummary[] = [];
  let lightweightBuffer: RawTraceEvent[] = [];
  let structuredBuffer: RawTraceEvent[] = [];
  const flushLightweight = () => {
    if (!lightweightBuffer.length) return;
    phases.push(...collapseLightweightDiagnosisPhase(lightweightBuffer));
    lightweightBuffer = [];
  };
  const flushStructured = () => {
    if (!structuredBuffer.length) return;
    phases.push({
      kind: 'structured_workflow_phase',
      started_at: structuredBuffer[0]?.ts,
      ended_at: structuredBuffer[structuredBuffer.length - 1]?.ts,
      raw_events: structuredBuffer,
    });
    structuredBuffer = [];
  };
  deduped.forEach((event) => {
    if (isStructuredAgentTraceEvent(event)) {
      flushLightweight();
      structuredBuffer.push(event);
      return;
    }
    flushStructured();
    lightweightBuffer.push(event);
  });
  flushLightweight();
  flushStructured();
  return phases;
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
  const payload = getTracePayload(event);
  const inputs = event.inputs;
  const outputs = event.outputs;
  const ts = event.ts;
  const tsMs = parseTsMs(ts);
  const agentHint = resolveTraceAgentId(event);
  const nodeName = resolveTraceNode(event);

  let status = String(event.status || payload?.status || '').toLowerCase();
  if (!status && agentHint) {
    const step = String(event.step || '').toLowerCase();
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
  const node = toLower(resolveTraceNode(event));
  const status = toLower(event.status);
  const payload = getTracePayload(event);
  const agent = resolveTraceAgentId(event);
  if (isLightweightTraceEvent(event)) {
    const hasDiagnosisCompleted = node.includes('diagnosiscompleted') && status === 'end' && Boolean(readDisease(payload));
    const hasConfidenceGateEnd = node.includes('confidencegate') && status === 'end';
    const hasDiagnosisEnd = node.includes('diagnosisagent') && status === 'end' && Boolean(readDisease(payload));
    return hasDiagnosisCompleted || hasConfidenceGateEnd || hasDiagnosisEnd;
  }
  const payloadStatus = String(payload?.status || '').toLowerCase();
  const outputs = isRecord(event.outputs) ? event.outputs : {};
  const isSupervisorTerminal = agent === 'supervisor' && outputs.is_complete === true && String(outputs.next_action || '').toLowerCase() === 'end';
  const verificationCompleteToEnd = String(event.step || '').toLowerCase() === 'verification_complete' && String(outputs.next_action || '').toLowerCase() === 'end';
  return (
    (node === 'final' && ['end', 'error', 'completed', 'done'].includes(status))
    || isSupervisorTerminal
    || verificationCompleteToEnd
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

  const calcForPhase = (phaseEvents: NormalizedEvent[]): Record<FixedAgentId, number> => {
    const totals = Object.fromEntries(FIXED_AGENT_IDS.map((agentId) => [agentId, 0])) as Record<FixedAgentId, number>;
    if (!phaseEvents.length) return totals;

    for (let i = 0; i < phaseEvents.length - 1; i += 1) {
      const current = phaseEvents[i];
      const next = phaseEvents[i + 1];
      if (typeof current.tsMs !== 'number' || typeof next.tsMs !== 'number') continue;
      totals[current.agentId] += Math.max(0, next.tsMs - current.tsMs);
    }

    const last = phaseEvents[phaseEvents.length - 1];
    if (!workflowDone && typeof last.tsMs === 'number' && !isWaitingForUserInputEvent(last)) {
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
  ) as Record<FixedAgentId, AgentPhaseDurations>;
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

export const calcTracePhaseTiming = (events: RawTraceEvent[], nowMs: number): OverallPhaseDurations & { workflowDone: boolean; hasTraceTiming: boolean } => {
  const segmented = segmentTracePhases(events);
  const normalized = segmented
    .flatMap((phase) => phase.raw_events)
    .map(normalizeRawEventForTiming)
    .filter((event) => typeof event.tsMs === 'number')
    .sort((a, b) => compareEvents(a, b));
  const workflowDone = segmented.every((phase) => phase.raw_events.some(isWorkflowTerminalRawEvent));
  const byAgent = calcPhaseDurationsByAgent(normalized, nowMs, workflowDone);
  return {
    ...calcOverallPhaseDuration(byAgent),
    workflowDone,
    hasTraceTiming: normalized.length > 0,
  };
};
