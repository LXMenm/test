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
  const protocol = detectTraceProtocol(raw);
  const rawStatus = asText(raw.status).toLowerCase();
  if (rawStatus === 'decision') return 'decision';
  if (['start', 'started', 'begin', 'running'].includes(rawStatus)) return 'start';
  if (['end', 'done', 'completed', 'finish'].includes(rawStatus)) return 'end';
  if (['error', 'failed', 'fail'].includes(rawStatus)) return 'error';
  if (rawStatus) return 'info';

  if (protocol === 'workflow_snapshot') {
    if (raw.outputs !== undefined) return 'end';
    if (isRecord(raw.decision)) return 'decision';
    if (raw.inputs !== undefined) return 'info';
    return 'info';
  }

  if (isRecord(raw.decision)) return 'decision';
  if (raw.outputs !== undefined) return 'end';
  if (raw.inputs !== undefined) return 'info';
  return 'info';
};

const parseSourceHint = (source) => {
  const lower = asText(source).toLowerCase();
  if (lower === 'continue') return 'continue';
  if (lower === 'start') return 'start';
  if (lower === 'replay') return 'replay';
  if (lower === 'confirm') return 'confirm';
  return 'unknown';
};

const sourcePriority = (sourceHint) => {
  if (sourceHint === 'continue') return 30;
  if (sourceHint === 'confirm') return 20;
  if (sourceHint === 'start') return 10;
  if (sourceHint === 'replay') return 0;
  return 1;
};

const keyFieldBonus = (bag) => {
  const keys = ['final_disease', 'disease_type', 'final_confidence', 'need_confirm', 'verification_result', 'treatment', 'selected_branch', 'actions'];
  return keys.reduce((acc, key) => (bag[key] !== undefined ? acc + 5 : acc), 0);
};

export const detectTraceProtocol = (rawEvent) => {
  const raw = isRecord(rawEvent) ? rawEvent : {};
  if (raw.step !== undefined || raw.agent !== undefined || raw.inputs !== undefined || raw.outputs !== undefined || raw.decision !== undefined) {
    return 'workflow_snapshot';
  }
  if (raw.node !== undefined || raw.status !== undefined || raw.message !== undefined || raw.payload !== undefined) {
    return 'compact_replay';
  }
  return 'unknown';
};

export const normalizeTraceEvent = (rawEvent) => {
  const raw = isRecord(rawEvent) ? rawEvent : {};
  const payload = isRecord(raw.payload) ? raw.payload : {};
  const stage = asText(raw.node) || asText(raw.step) || asText(raw.agent) || asText(raw.agent_id) || 'unknown';
  const decision = isRecord(raw.decision) ? raw.decision : undefined;
  const detail = asText(decision?.reason) || asText(payload.detail) || '';
  const sourceHint = parseSourceHint(raw.__source);

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
    protocol: detectTraceProtocol(raw),
    sourceHint,
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
  if (isRecord(raw.outputs)) score += 6;
  if (isRecord(raw.inputs)) score += 4;
  if (isRecord(raw.decision)) score += 6;
  if (asText(raw.step)) score += 4;
  if (asText(raw.agent)) score += 4;
  if (asText(raw.node) && !asText(raw.step) && !asText(raw.agent) && !isRecord(raw.outputs) && !isRecord(raw.inputs) && !isRecord(raw.decision)) score += 1;
  score += keyFieldBonus(event.payload);
  if (isRecord(raw.outputs)) score += keyFieldBonus(raw.outputs);
  score += sourcePriority(event.sourceHint);
  return score;
};

const eventKey = (event) => {
  const traceId = event.traceId || asText(event.raw.trace_id) || 'unknown_trace';
  const seqPart = Number.isFinite(event.seq) ? String(event.seq) : '∞';
  const stage = event.stage || 'unknown_stage';
  const workflowIdentity = asText(event.raw.agent_id) || asText(event.raw.agent) || asText(event.raw.step) || stage;
  const compactIdentity = asText(event.raw.node) || stage;

  if (event.protocol === 'workflow_snapshot') {
    return `workflow:${traceId}:${seqPart}:${workflowIdentity}`;
  }
  if (event.protocol === 'compact_replay') {
    return `compact:${traceId}:${seqPart}:${compactIdentity}`;
  }
  return `fallback:${traceId}:${event.protocol}:${event.ts ?? ''}:${event.title}:${stage}`;
};

const dedupeWithinBucket = (events) => {
  const bestByKey = new Map();

  events.forEach((event, index) => {
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
      return;
    }

    if (nextScore === prevScore && sourcePriority(event.sourceHint) > sourcePriority(prev.event.sourceHint)) {
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

export const splitTraceEventsByProtocol = (events) => {
  const workflowSnapshotEvents = [];
  const compactReplayEvents = [];
  const unknownEvents = [];

  events.forEach((event) => {
    if (event.protocol === 'workflow_snapshot') {
      workflowSnapshotEvents.push(event);
      return;
    }
    if (event.protocol === 'compact_replay') {
      compactReplayEvents.push(event);
      return;
    }
    unknownEvents.push(event);
  });

  return { workflowSnapshotEvents, compactReplayEvents, unknownEvents };
};

export const mergeAndDedupeTraceEvents = (existingEvents, incomingEvents) => {
  const merged = [...existingEvents, ...incomingEvents];
  const { workflowSnapshotEvents, compactReplayEvents, unknownEvents } = splitTraceEventsByProtocol(merged);

  const dedupedWorkflow = dedupeWithinBucket(workflowSnapshotEvents);
  const dedupedCompact = dedupeWithinBucket(compactReplayEvents);
  const dedupedUnknown = dedupeWithinBucket(unknownEvents);

  return [...dedupedWorkflow, ...dedupedCompact, ...dedupedUnknown].sort((a, b) => {
    const aSeq = Number.isFinite(a.seq) ? a.seq : FALLBACK_SEQ;
    const bSeq = Number.isFinite(b.seq) ? b.seq : FALLBACK_SEQ;
    if (aSeq !== bSeq) return aSeq - bSeq;

    const aTs = a.ts ? Date.parse(a.ts) : Number.POSITIVE_INFINITY;
    const bTs = b.ts ? Date.parse(b.ts) : Number.POSITIVE_INFINITY;
    const safeATs = Number.isFinite(aTs) ? aTs : Number.POSITIVE_INFINITY;
    const safeBTs = Number.isFinite(bTs) ? bTs : Number.POSITIVE_INFINITY;
    if (safeATs !== safeBTs) return safeATs - safeBTs;

    return 0;
  });
};
