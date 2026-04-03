const FALLBACK_SEQ = Number.POSITIVE_INFINITY;

const isRecord = (value) => !!value && typeof value === 'object' && !Array.isArray(value);

const asText = (value) => {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return '';
};

const toSeq = (value) => {
  const n = Number(value);
  return Number.isFinite(n) ? n : FALLBACK_SEQ;
};

const pickStatus = (raw) => {
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

export const normalizeTraceEvent = (rawEvent) => {
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

export const normalizeTraceEvents = (eventsLike) => {
  if (!Array.isArray(eventsLike)) return [];
  return eventsLike.map((eventLike) => normalizeTraceEvent(eventLike));
};

const infoScore = (event) => {
  const raw = event.raw;
  let score = 0;
  score += Object.keys(raw).length;
  if (asText(raw.message)) score += 3;
  if (asText(raw.step_cn)) score += 3;
  if (asText(raw.agent_cn)) score += 3;
  if (Object.keys(event.payload).length > 0) score += 2;
  if (Object.keys(event.raw).length > 0) score += 2;
  if (event.detail) score += 1;
  return score;
};

const eventKey = (event) => {
  const traceId = event.traceId || asText(event.raw.trace_id) || 'unknown_trace';
  if (Number.isFinite(event.seq)) {
    return `seq:${traceId}:${event.seq}`;
  }
  return `fallback:${traceId}:${event.ts ?? ''}:${event.title}:${event.stage}`;
};

export const mergeAndDedupeTraceEvents = (existingEvents, incomingEvents) => {
  const merged = [...existingEvents, ...incomingEvents];
  const bestByKey = new Map();

  merged.forEach((event, index) => {
    const key = eventKey(event);
    const prev = bestByKey.get(key);
    if (!prev) {
      bestByKey.set(key, { event, index });
      return;
    }
    const prevScore = infoScore(prev.event);
    const nextScore = infoScore(event);
    if (nextScore > prevScore) {
      bestByKey.set(key, { event, index: prev.index });
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
