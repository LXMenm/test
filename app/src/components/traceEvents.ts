export type TraceEventStatus = 'start' | 'end' | 'info' | 'error' | 'decision';
type TraceSourceHint = 'start' | 'continue' | 'replay' | 'unknown';

export type NormalizedTraceEvent = {
  traceId: string;
  seq: number;
  ts: string | null;
  stage: string;
  stageCn: string;
  agentId: string;
  agentLabel: string;
  status: TraceEventStatus;
  title: string;
  detail: string;
  payload: Record<string, unknown>;
  raw: Record<string, unknown>;
};

const FALLBACK_SEQ = Number.POSITIVE_INFINITY;

const isRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);

const asText = (value: unknown): string => {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return '';
};

const toSeq = (value: unknown): number => {
  const n = Number(value);
  return Number.isFinite(n) ? n : FALLBACK_SEQ;
};

const pickStatus = (raw: Record<string, unknown>): TraceEventStatus => {
  const rawStatus = asText(raw.status).toLowerCase();
  if (rawStatus === 'decision') return 'decision';
  if (['start', 'started', 'begin', 'running'].includes(rawStatus)) return 'start';
  if (['end', 'done', 'completed', 'finish'].includes(rawStatus)) return 'end';
  if (['error', 'failed', 'fail'].includes(rawStatus)) return 'error';
  if (rawStatus) return 'info';

  if (isRecord(raw.decision)) return 'decision';
  if (raw.outputs !== undefined) return 'end';
  if (raw.inputs !== undefined) return 'info';
  return 'info';
};

const sourcePriority = (raw: Record<string, unknown>): number => {
  const source = String(raw.__source ?? '').toLowerCase();
  if (source === 'continue') return 30;
  if (source === 'start') return 10;
  if (source === 'replay') return 0;
  return 1;
};

const keyFieldBonus = (bag: Record<string, unknown>): number => {
  const keys = ['final_disease', 'disease_type', 'final_confidence', 'need_confirm', 'verification_result', 'treatment', 'selected_branch', 'actions'] as const;
  return keys.reduce((acc, key) => (bag[key] !== undefined ? acc + 5 : acc), 0);
};

export const normalizeTraceEvent = (rawEvent: unknown): NormalizedTraceEvent => {
  const raw = isRecord(rawEvent) ? rawEvent : {};
  const payload = isRecord(raw.payload) ? raw.payload : {};
  const stage = asText(raw.node) || asText(raw.step) || asText(raw.agent) || asText(raw.agent_id) || 'unknown';
  const decision = isRecord(raw.decision) ? raw.decision : undefined;
  const detail = asText(decision?.reason) || asText(payload.detail) || '';

  return {
    traceId: asText(raw.trace_id),
    seq: toSeq(raw.seq),
    ts: asText(raw.ts) || asText(payload.ts) || null,
    stage,
    stageCn: asText(raw.step_cn) || asText(raw.agent_cn) || asText(raw.message) || stage,
    agentId: asText(raw.agent_id) || asText(raw.agent) || asText(payload.agent_id) || 'unknown',
    agentLabel: asText(raw.agent_cn) || asText(raw.agent) || asText(raw.agent_id) || stage,
    status: pickStatus(raw),
    title: asText(raw.message) || asText(raw.step_cn) || asText(raw.agent_cn) || asText(raw.step) || asText(raw.node) || asText(raw.agent) || '未命名步骤',
    detail,
    payload,
    raw,
  };
};

export const normalizeTraceEvents = (eventsLike: unknown): NormalizedTraceEvent[] => {
  if (!Array.isArray(eventsLike)) return [];
  return eventsLike.map((eventLike) => normalizeTraceEvent(eventLike));
};

const infoScore = (event: NormalizedTraceEvent): number => {
  const raw = event.raw;
  let score = 0;
  score += Object.keys(raw).length;
  if (asText(raw.message)) score += 3;
  if (asText(raw.step_cn)) score += 3;
  if (asText(raw.agent_cn)) score += 3;
  if (Object.keys(event.payload).length > 0) score += 2;
  if (Object.keys(event.raw).length > 0) score += 2;
  if (event.detail) score += 1;
  if (isRecord(raw.outputs)) score += 6;
  if (isRecord(raw.inputs)) score += 4;
  if (isRecord(raw.decision)) score += 6;
  if (asText(raw.step)) score += 4;
  if (asText(raw.agent)) score += 4;
  if (asText(raw.node) && !asText(raw.step) && !asText(raw.agent) && !isRecord(raw.outputs) && !isRecord(raw.inputs) && !isRecord(raw.decision)) score += 1;
  score += keyFieldBonus(event.payload);
  if (isRecord(raw.outputs)) score += keyFieldBonus(raw.outputs);
  score += sourcePriority(raw);
  return score;
};

const eventKey = (event: NormalizedTraceEvent): string => {
  const traceId = event.traceId || asText(event.raw.trace_id) || 'unknown_trace';
  if (Number.isFinite(event.seq)) {
    return `seq:${traceId}:${event.seq}`;
  }
  return `fallback:${traceId}:${event.ts ?? ''}:${event.title}:${event.stage}`;
};

export const mergeAndDedupeTraceEvents = (
  existingEvents: NormalizedTraceEvent[],
  incomingEvents: NormalizedTraceEvent[],
): NormalizedTraceEvent[] => {
  const merged = [...existingEvents, ...incomingEvents];
  const bestByKey = new Map<string, { event: NormalizedTraceEvent; index: number }>();

  merged.forEach((event, index) => {
    const key = eventKey(event);
    const prev = bestByKey.get(key);
    if (!prev) {
      bestByKey.set(key, { event, index });
      return;
    }
    const prevScore = infoScore(prev.event);
    const nextScore = infoScore(event);
    const prevSource = String(prev.event.raw.__source ?? 'unknown') as TraceSourceHint;
    const nextSource = String(event.raw.__source ?? 'unknown') as TraceSourceHint;
    if (nextScore > prevScore) {
      bestByKey.set(key, { event, index: prev.index });
      if (typeof window !== 'undefined' && window?.location?.hostname === 'localhost') {
        console.debug('[trace dedupe]', { key, seq: event.seq, oldSource: prevSource, newSource: nextSource, oldScore: prevScore, newScore: nextScore, kept: nextSource });
      }
      return;
    }
    if (nextScore === prevScore && sourcePriority(event.raw) > sourcePriority(prev.event.raw)) {
      bestByKey.set(key, { event, index: prev.index });
      if (typeof window !== 'undefined' && window?.location?.hostname === 'localhost') {
        console.debug('[trace dedupe]', { key, seq: event.seq, oldSource: prevSource, newSource: nextSource, oldScore: prevScore, newScore: nextScore, kept: nextSource });
      }
    }
  });

  return Array.from(bestByKey.values())
    .sort((a, b) => {
      const aSeq = Number.isFinite(a.event.seq) ? a.event.seq : FALLBACK_SEQ;
      const bSeq = Number.isFinite(b.event.seq) ? b.event.seq : FALLBACK_SEQ;
      if (aSeq !== bSeq) return aSeq - bSeq;

      const aTs = a.event.ts ? Date.parse(a.event.ts) : Number.POSITIVE_INFINITY;
      const bTs = b.event.ts ? Date.parse(b.event.ts) : Number.POSITIVE_INFINITY;
      const safeATs = Number.isFinite(aTs) ? aTs : Number.POSITIVE_INFINITY;
      const safeBTs = Number.isFinite(bTs) ? bTs : Number.POSITIVE_INFINITY;
      if (safeATs !== safeBTs) return safeATs - safeBTs;

      return a.index - b.index;
    })
    .map((entry) => entry.event);
};
