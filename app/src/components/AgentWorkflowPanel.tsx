import { useEffect, useMemo, useRef, useState } from 'react';
import {
<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
  AlertTriangle,
  BadgeCheck,
  BookOpen,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Flag,
  Headset,
  Loader2,
  Pill,
  Signal,
  Stethoscope,
  Timer,
=======
  Bot,
  Headset,
  Stethoscope,
  BookOpen,
  Pill,
  Flag,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  Signal,
  Timer,
  BadgeCheck,
>>>>>>> main
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

type AgentStatus = 'pending' | 'running' | 'completed' | 'error';
<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
type FixedAgentId = 'supervisor' | 'reception' | 'diagnosis' | 'kb_retrieval' | 'treatment' | 'final';

interface AgentWorkflowPanelProps {
  traceId?: string;
  confidencePct?: number;
}

interface RawTraceEvent {
  seq?: number;
  ts?: string;
  agent?: string;
  agent_id?: string;
  agent_cn?: string;
  step?: string;
  step_cn?: string;
  node?: string;
  status?: string;
  message?: string;
  payload?: Record<string, any>;
  inputs?: Record<string, any>;
  outputs?: Record<string, any>;
  decision?: Record<string, any>;
}

interface NormalizedEvent {
  seq?: number;
  ts?: string;
  tsMs?: number;
  agentId: FixedAgentId;
  nodeName: string;
  status: AgentStatus | 'info';
  message: string;
  data: Record<string, any>;
=======

type FixedAgentId = 'supervisor' | 'reception' | 'diagnosis' | 'kb_retrieval' | 'treatment' | 'final';

interface WorkflowEvent {
  seq?: number;
  ts?: string;
  node?: string;
  agent_id?: string;
  status?: string;
  message?: string;
  payload?: Record<string, any>;
>>>>>>> main
}

interface AgentRowDef {
  id: FixedAgentId;
  name: string;
  description: string;
  icon: any;
}

interface AgentRowState {
  id: FixedAgentId;
  status: AgentStatus;
  startTs?: number;
  endTs?: number;
  progress: number;
  lastMessage: string;
  steps: Array<{ seq?: number; node: string; message: string }>;
<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
  highlights: string[];
=======
}

interface AgentWorkflowPanelProps {
  traceId?: string;
  confidencePct?: number;
>>>>>>> main
}

const FIXED_AGENTS: AgentRowDef[] = [
  { id: 'supervisor', name: 'supervisor', description: '监督与路由决策', icon: Bot },
  { id: 'reception', name: 'reception', description: '输入接待与要素提取', icon: Headset },
  { id: 'diagnosis', name: 'diagnosis', description: '病害诊断与置信度评估', icon: Stethoscope },
  { id: 'kb_retrieval', name: 'kb_retrieval', description: '知识库检索与信息补全', icon: BookOpen },
  { id: 'treatment', name: 'treatment', description: '治疗方案生成与校验落盘', icon: Pill },
  { id: 'final', name: 'final', description: '流程结束与结果输出', icon: Flag },
];

const DIRECT_SET = new Set<FixedAgentId>(['supervisor', 'reception', 'diagnosis', 'kb_retrieval', 'treatment', 'final']);

const MERGE_MAP: Record<string, FixedAgentId> = {
  parse_input: 'reception',
  confirm_input: 'supervisor',
  confidence_gate: 'diagnosis',
  personalization: 'treatment',
  prescription: 'treatment',
  validator: 'treatment',
  persist: 'treatment',
<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
  final: 'final',
=======
>>>>>>> main
};

const buildInitialState = (): Record<FixedAgentId, AgentRowState> => {
  return FIXED_AGENTS.reduce((acc, row) => {
    acc[row.id] = {
      id: row.id,
      status: 'pending',
      progress: 0,
      lastMessage: row.description,
      steps: [],
<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
      highlights: [],
=======
>>>>>>> main
    };
    return acc;
  }, {} as Record<FixedAgentId, AgentRowState>);
};

<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
=======
const normalizeStatus = (status: unknown): 'start' | 'progress' | 'completed' | 'error' | 'info' => {
  const text = String(status || '').toLowerCase();
  if (['start', 'started', 'begin', 'running', '执行中', '开始'].includes(text)) return 'start';
  if (['progress', 'processing', '进行中'].includes(text)) return 'progress';
  if (['end', 'done', 'completed', 'finish', '结束', '完成'].includes(text)) return 'completed';
  if (['error', 'failed', '错误', 'fail'].includes(text)) return 'error';
  return 'info';
};

>>>>>>> main
const parseTsMs = (ts?: string): number | undefined => {
  if (!ts) return undefined;
  const ms = Date.parse(ts);
  return Number.isFinite(ms) ? ms : undefined;
};

const clamp = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v));

const softProgress = (elapsedMs: number) => clamp(Math.round((elapsedMs / 8000) * 90), 5, 90);

const formatDuration = (ms: number): string => {
  if (!Number.isFinite(ms) || ms <= 0) return '0.00s';
  if (ms < 1000) return `${(ms / 1000).toFixed(2)}s`;

  const seconds = ms / 1000;
  if (seconds >= 60) {
    const minutes = Math.floor(seconds / 60);
    const remainSeconds = seconds - minutes * 60;
    return `${minutes}m${remainSeconds.toFixed(1)}s`;
  }

  return `${seconds.toFixed(2)}s`;
};

<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
const shortText = (value: unknown, max = 80): string => {
  const raw = String(value ?? '').trim();
  if (!raw) return '';
  return raw.length <= max ? raw : `${raw.slice(0, max)}...`;
};

const toArray = (value: unknown): any[] => (Array.isArray(value) ? value : []);

const normalizeStatus = (status: unknown): AgentStatus | 'info' => {
  const text = String(status || '').toLowerCase();
  if (['start', 'started', 'begin', 'running', '执行中', '开始'].includes(text)) return 'running';
  if (['progress', 'processing', '进行中'].includes(text)) return 'running';
  if (['end', 'done', 'completed', 'finish', '结束', '完成'].includes(text)) return 'completed';
  if (['error', 'failed', '错误', 'fail'].includes(text)) return 'error';
  return 'info';
=======
const normalizeMessage = (rawMessage: unknown, fallback: string) => {
  const m = String(rawMessage || '').trim();
  if (!m || m.toLowerCase() === 'start') return fallback;
  return m;
>>>>>>> main
};

const mapToFixedAgent = (agentId: string | undefined, node: string | undefined): FixedAgentId => {
  const aid = String(agentId || '').toLowerCase();
  if (DIRECT_SET.has(aid as FixedAgentId)) return aid as FixedAgentId;
  if (MERGE_MAP[aid]) return MERGE_MAP[aid];

  const nodeLower = String(node || '').toLowerCase();
  if (nodeLower.includes('final')) return 'final';
  if (nodeLower.includes('retrieve') || nodeLower.includes('kb')) return 'kb_retrieval';
  if (nodeLower.includes('diagnosis') || nodeLower.includes('confidence')) return 'diagnosis';
  if (nodeLower.includes('persist') || nodeLower.includes('validator') || nodeLower.includes('prescription') || nodeLower.includes('personalization') || nodeLower.includes('treatment')) return 'treatment';
  if (nodeLower.includes('parse') || nodeLower.includes('input') || nodeLower.includes('reception')) return 'reception';
  return 'supervisor';
};

<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
const compareEvents = (a: RawTraceEvent, b: RawTraceEvent): number => {
=======
const compareEvents = (a: WorkflowEvent, b: WorkflowEvent): number => {
>>>>>>> main
  const aHasSeq = typeof a.seq === 'number' && Number.isFinite(a.seq);
  const bHasSeq = typeof b.seq === 'number' && Number.isFinite(b.seq);
  if (aHasSeq && bHasSeq) return (a.seq as number) - (b.seq as number);

  const aTs = parseTsMs(a.ts) ?? Number.MAX_SAFE_INTEGER;
  const bTs = parseTsMs(b.ts) ?? Number.MAX_SAFE_INTEGER;
  if (aTs !== bTs) return aTs - bTs;

  if (aHasSeq && !bHasSeq) return -1;
  if (!aHasSeq && bHasSeq) return 1;
  return 0;
};

<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
const normalizeEvent = (raw: RawTraceEvent): NormalizedEvent => {
  const ts = raw.ts;
  const tsMs = parseTsMs(ts);

  if (raw.agent) {
    const agentId = mapToFixedAgent(String(raw.agent_id || raw.agent), undefined);
    const outputs = raw.outputs && typeof raw.outputs === 'object' ? raw.outputs : {};
    const decision = raw.decision && typeof raw.decision === 'object' ? raw.decision : {};
    const isComplete = String(raw.step || '').toLowerCase().endsWith('_complete') || outputs?.is_complete === true;
    const status = isComplete ? 'completed' : 'running';

    const reasons = toArray(decision?.reasons_cn || decision?.reasons).map((item) => String(item));
    const reasonText = shortText(decision?.reason_str || reasons.join('、'), 120);
    const message = shortText(raw.step_cn || raw.step || reasonText || `${raw.agent} ${status === 'completed' ? '完成' : '执行中'}`, 140);

    return {
      seq: raw.seq,
      ts,
      tsMs,
      agentId,
      nodeName: String(raw.step || raw.agent),
      status,
      message,
      data: {
        agent: raw.agent,
        agent_cn: raw.agent_cn,
        step: raw.step,
        step_cn: raw.step_cn,
        inputs: raw.inputs || {},
        outputs,
        decision,
      },
    };
  }

  const payload = raw.payload && typeof raw.payload === 'object' ? raw.payload : {};
  const status = normalizeStatus(raw.status);
  return {
    seq: raw.seq,
    ts,
    tsMs,
    agentId: mapToFixedAgent(String(payload.agent_id || raw.agent_id || ''), raw.node),
    nodeName: String(raw.node || raw.agent || 'trace'),
    status,
    message: shortText(raw.message || payload.message || raw.node || 'trace', 140),
    data: payload,
  };
};

const extractHighlights = (agentId: FixedAgentId, events: NormalizedEvent[]): string[] => {
  if (!events.length) return [];

  const latest = events[events.length - 1];
  const lines: string[] = [];

  if (agentId === 'supervisor') {
    const decision = latest.data?.decision || {};
    const nextAction = decision?.next_action || latest.data?.outputs?.next_action;
    const reasons = toArray(decision?.reasons_cn || decision?.reasons).map((item) => String(item)).filter(Boolean);
    const isComplete = latest.data?.outputs?.is_complete ?? decision?.is_complete;
    if (nextAction) lines.push(`下一步：${nextAction}`);
    reasons.slice(0, 2).forEach((reason) => lines.push(`原因：${shortText(reason, 70)}`));
    if (typeof isComplete === 'boolean') lines.push(`is_complete：${isComplete ? '是' : '否'}`);
  }

  if (agentId === 'reception') {
    const inputs = latest.data?.inputs || {};
    const cropType = inputs?.crop_type || latest.data?.outputs?.crop_type;
    const imageName = inputs?.filename || inputs?.image_name || inputs?.image_path || latest.data?.outputs?.image_path;
    const missing = toArray(latest.data?.outputs?.missing_profile_fields);
    const symptoms = inputs?.symptoms;
    const symptomCount = Array.isArray(symptoms)
      ? symptoms.length
      : typeof symptoms === 'string'
        ? symptoms.split(/[，,\s]+/).filter(Boolean).length
        : 0;
    if (cropType) lines.push(`作物：${cropType}`);
    if (imageName) lines.push(`图片：${shortText(imageName, 48)}`);
    if (missing.length) lines.push(`缺失档案字段：${missing.join('、')}`);
    lines.push(`症状数量：${symptomCount}`);
  }

  if (agentId === 'diagnosis') {
    const outputs = latest.data?.outputs || latest.data;
    const modelId = outputs?.model_id;
    const backend = outputs?.backend || outputs?.model_backend;
    const path = outputs?.path || outputs?.model_path;
    const finalDisease = outputs?.final_disease || outputs?.disease;
    const confidenceRaw = Number(outputs?.confidence_pct ?? outputs?.confidence);
    const confidencePct = Number.isFinite(confidenceRaw)
      ? (confidenceRaw <= 1 ? confidenceRaw * 100 : confidenceRaw)
      : undefined;
    const top3 = toArray(outputs?.top3 || outputs?.image_result?.top3)
      .slice(0, 3)
      .map((item: any) => `${item?.disease || item?.name || '-'}:${Number(item?.confidence_pct ?? (Number(item?.confidence) * 100)).toFixed(1)}%`);

    if (modelId || backend) lines.push(`模型：${modelId || '-'} / ${backend || '-'}`);
    if (path) lines.push(`路径：${shortText(path, 54)}`);
    if (finalDisease) lines.push(`结论：${finalDisease}`);
    if (typeof confidencePct === 'number' && Number.isFinite(confidencePct)) lines.push(`置信度：${confidencePct.toFixed(2)}%`);
    if (top3.length) lines.push(`Top3：${top3.join(' | ')}`);
    if (outputs?.fallback_reason) lines.push(`回退原因：${outputs.fallback_reason}`);
  }

  if (agentId === 'kb_retrieval') {
    const outputs = latest.data?.outputs || latest.data;
    if (outputs?.disease) lines.push(`命中病害：${outputs.disease}`);
    if (outputs?.description) lines.push(`描述：${shortText(outputs.description, 80)}`);
    if (outputs?.treatment) lines.push(`治疗：${shortText(outputs.treatment, 70)}`);
    if (outputs?.prevention) lines.push(`预防：${shortText(outputs.prevention, 70)}`);
  }

  if (agentId === 'treatment') {
    const outputs = latest.data?.outputs || latest.data;
    if (outputs?.treatment_plan || outputs?.plan) lines.push(`处方：${shortText(outputs.treatment_plan || outputs.plan, 80)}`);
    if (outputs?.prevention_advice || outputs?.prevention) lines.push(`预防：${shortText(outputs.prevention_advice || outputs.prevention, 80)}`);
    const filtered = toArray(outputs?.filtered_components).map((item) => String(item));
    if (filtered.length) lines.push(`过滤组件：${filtered.slice(0, 3).join('、')}`);
    const validatorMessages = events
      .filter((event) => /validator|persist/i.test(event.nodeName))
      .slice(-2)
      .map((event) => shortText(event.message, 80));
    validatorMessages.forEach((message) => lines.push(`校验/落盘：${message}`));
  }

  if (agentId === 'final') {
    const outputs = latest.data?.outputs || latest.data;
    if (outputs?.final_disease || outputs?.disease) lines.push(`最终病害：${outputs?.final_disease || outputs?.disease}`);
    lines.push('流程完成');
  }

  if (!lines.length) {
    lines.push(shortText(latest.message, 100) || '等待事件');
  }

  return lines.filter(Boolean).slice(0, 6);
};

=======
>>>>>>> main
export function AgentWorkflowPanel({ traceId, confidencePct }: AgentWorkflowPanelProps) {
  const [rows, setRows] = useState<Record<FixedAgentId, AgentRowState>>(buildInitialState());
  const [connectionState, setConnectionState] = useState<'idle' | 'connecting' | 'connected' | 'disconnected'>('idle');
  const [connectionHint, setConnectionHint] = useState('');
  const [replayedCount, setReplayedCount] = useState(0);
  const [nowMs, setNowMs] = useState(Date.now());
  const [workflowDone, setWorkflowDone] = useState(false);
  const [diagnosisConfidencePct, setDiagnosisConfidencePct] = useState<number | undefined>(undefined);
<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
  const [debugOpen, setDebugOpen] = useState<Record<FixedAgentId, boolean>>({
    supervisor: false,
    reception: false,
    diagnosis: false,
    kb_retrieval: false,
    treatment: false,
    final: false,
  });

  const esRef = useRef<EventSource | null>(null);
  const tickerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastSeqRef = useRef(-1);
  const workflowDoneRef = useRef(false);
  const replayedCountRef = useRef(0);
  const finalTsRef = useRef<number | undefined>(undefined);
  const eventHistoryRef = useRef<Record<FixedAgentId, NormalizedEvent[]>>({
    supervisor: [],
    reception: [],
    diagnosis: [],
    kb_retrieval: [],
    treatment: [],
    final: [],
  });
=======

  const esRef = useRef<EventSource | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const tickerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const seenSeqRef = useRef<Set<number>>(new Set());
  const lastSeqRef = useRef(-1);
  const workflowDoneRef = useRef(false);
  const replayedCountRef = useRef(0);
>>>>>>> main

  useEffect(() => {
    if (typeof confidencePct === 'number' && Number.isFinite(confidencePct)) {
      setDiagnosisConfidencePct(confidencePct);
    }
  }, [confidencePct]);

  const clearTicker = () => {
    if (tickerRef.current) {
      clearInterval(tickerRef.current);
      tickerRef.current = null;
    }
  };

<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
  const closeStream = () => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  };

  const clearExternal = () => {
    closeStream();
    clearTicker();
  };

  const maybeStartTicker = (snapshot: Record<FixedAgentId, AgentRowState>, done: boolean) => {
    const hasRunning = FIXED_AGENTS.some((agent) => snapshot[agent.id].status === 'running');
=======
  const updateTicker = (snapshot: Record<FixedAgentId, AgentRowState>, done: boolean) => {
    const hasRunning = FIXED_AGENTS.some((a) => snapshot[a.id].status === 'running');
>>>>>>> main
    if (!done && hasRunning) {
      if (!tickerRef.current) {
        tickerRef.current = setInterval(() => setNowMs(Date.now()), 100);
      }
    } else {
      clearTicker();
    }
  };

<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
  const completeSupervisorOnDone = (doneTs?: number) => {
    setRows((prev) => {
      if (prev.supervisor.status !== 'running') return prev;
      const next = { ...prev };
      next.supervisor = {
        ...next.supervisor,
        status: 'completed',
        progress: 100,
        endTs: doneTs ?? next.supervisor.endTs,
      };
      return next;
    });
  };

  const applyNormalizedEvent = (event: NormalizedEvent): boolean => {
    if (workflowDoneRef.current) return false;

    const seq = event.seq;
    if (typeof seq === 'number' && Number.isFinite(seq) && seq <= lastSeqRef.current) {
      return false;
    }
    if (typeof seq === 'number' && Number.isFinite(seq)) {
      lastSeqRef.current = seq;
    }

    if (event.status === 'info') return false;

    const agentId = event.agentId;
    eventHistoryRef.current[agentId] = [...eventHistoryRef.current[agentId], event].slice(-20);

    if (agentId === 'diagnosis') {
      const rawConfidence = Number(event.data?.confidence_pct ?? event.data?.confidence ?? event.data?.outputs?.confidence_pct ?? event.data?.outputs?.confidence);
=======
  const clearExternal = () => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    clearTicker();
  };

  const normalizeEvent = (evt: any): WorkflowEvent => {
    const payload = evt?.payload && typeof evt.payload === 'object' ? evt.payload : {};
    return {
      seq: evt?.seq,
      ts: evt?.ts || evt?.timestamp,
      node: evt?.node || evt?.agent,
      agent_id: evt?.agent_id || payload?.agent_id,
      status: evt?.status || evt?.step,
      message: evt?.message,
      payload,
    };
  };

  const handleEvent = (evt: WorkflowEvent) => {
    if (workflowDoneRef.current) return;

    const seqRaw = evt.seq;
    if (typeof seqRaw === 'number' && Number.isFinite(seqRaw)) {
      if (seenSeqRef.current.has(seqRaw)) return;
      if (seqRaw < lastSeqRef.current) return;
      seenSeqRef.current.add(seqRaw);
      lastSeqRef.current = seqRaw;
    }

    const nodeName = String(evt.node || '').trim();
    const statusNorm = normalizeStatus(evt.status);
    if (!nodeName || statusNorm === 'info') return;

    const payload = evt.payload && typeof evt.payload === 'object' ? evt.payload : {};
    const mappedAgent = mapToFixedAgent(String(evt.agent_id || payload.agent_id || ''), nodeName);

    const tsMs = parseTsMs(evt.ts);
    const fallbackMessage = statusNorm === 'start'
      ? `开始执行 ${mappedAgent}`
      : statusNorm === 'progress'
        ? `${mappedAgent} 进行中`
        : statusNorm === 'completed'
          ? `${mappedAgent} 执行完成`
          : `${mappedAgent} 执行错误`;
    const message = normalizeMessage(evt.message ?? payload.message, fallbackMessage);

    if (mappedAgent === 'diagnosis') {
      const rawConfidence = Number(payload.confidence_pct ?? payload.confidence);
>>>>>>> main
      if (Number.isFinite(rawConfidence)) {
        setDiagnosisConfidencePct(rawConfidence <= 1 ? rawConfidence * 100 : rawConfidence);
      }
    }

<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
    let markDone = false;
    setRows((prev) => {
      const next = { ...prev };
      const current = { ...next[agentId] };

      const fallbackMessage = event.status === 'completed'
        ? `${agentId} 执行完成`
        : event.status === 'error'
          ? `${agentId} 执行错误`
          : `${agentId} 执行中`;
      const message = shortText(event.message || fallbackMessage, 140) || fallbackMessage;

      current.steps = [...current.steps, { seq: event.seq, node: event.nodeName, message }]
=======
    setRows((prev) => {
      const next = { ...prev };
      const current = { ...next[mappedAgent] };

      current.steps = [...current.steps, { seq: seqRaw, node: nodeName, message }]
>>>>>>> main
        .sort((a, b) => {
          const sa = typeof a.seq === 'number' ? a.seq : Number.MAX_SAFE_INTEGER;
          const sb = typeof b.seq === 'number' ? b.seq : Number.MAX_SAFE_INTEGER;
          return sa - sb;
        })
        .slice(-3);
      current.lastMessage = message;
<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
      current.highlights = extractHighlights(agentId, eventHistoryRef.current[agentId]);

      if (event.status === 'running') {
        current.status = 'running';
        if (typeof event.tsMs === 'number') {
          current.startTs = current.startTs ?? event.tsMs;
        }
        const explicit = Number(event.data?.progress ?? event.data?.outputs?.progress);
        if (Number.isFinite(explicit)) {
          current.progress = clamp(explicit, 0, 90);
        } else if (typeof event.tsMs === 'number' && typeof current.startTs === 'number') {
          current.progress = Math.max(current.progress, softProgress(Math.max(0, event.tsMs - current.startTs)));
        } else {
          current.progress = Math.max(current.progress, 5);
        }
      } else if (event.status === 'completed') {
        current.status = 'completed';
        if (typeof event.tsMs === 'number') {
          current.startTs = current.startTs ?? event.tsMs;
          current.endTs = event.tsMs;
        }
        current.progress = 100;
      } else if (event.status === 'error') {
        current.status = 'error';
        if (typeof event.tsMs === 'number') {
          current.startTs = current.startTs ?? event.tsMs;
          current.endTs = event.tsMs;
=======

      if (statusNorm === 'start') {
        current.status = 'running';
        if (typeof tsMs === 'number') current.startTs = current.startTs ?? tsMs;
        current.progress = Math.max(current.progress, 5);
      } else if (statusNorm === 'progress') {
        current.status = current.status === 'pending' ? 'running' : current.status;
        if (typeof tsMs === 'number') current.startTs = current.startTs ?? tsMs;
        const explicit = Number(payload.progress ?? evt.payload?.progress);
        if (Number.isFinite(explicit)) {
          current.progress = clamp(explicit, 0, 90);
        } else {
          if (typeof tsMs === 'number' && typeof current.startTs === 'number') {
            const elapsed = Math.max(0, tsMs - current.startTs);
            current.progress = Math.max(current.progress, softProgress(elapsed));
          }
        }
      } else if (statusNorm === 'completed') {
        current.status = 'completed';
        if (typeof tsMs === 'number') {
          current.startTs = current.startTs ?? tsMs;
          current.endTs = tsMs;
        }
        current.progress = 100;
      } else if (statusNorm === 'error') {
        current.status = 'error';
        if (typeof tsMs === 'number') {
          current.startTs = current.startTs ?? tsMs;
          current.endTs = tsMs;
>>>>>>> main
        }
        current.progress = 100;
      }

<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
      next[agentId] = current;

      const finalDone = agentId === 'final' && event.status === 'completed';
      if (finalDone) {
        markDone = true;
        if (typeof event.tsMs === 'number') {
          finalTsRef.current = event.tsMs;
        }
      }

      maybeStartTicker(next, markDone || workflowDoneRef.current);
      return next;
    });

    if (markDone) {
      workflowDoneRef.current = true;
      setWorkflowDone(true);
      closeStream();
      clearTicker();
      completeSupervisorOnDone(finalTsRef.current);
    }

    return true;
=======
      next[mappedAgent] = current;

      const done = (mappedAgent === 'final' && statusNorm === 'completed') ||
        (nodeName.toLowerCase() === 'final' && statusNorm === 'completed');
      if (done) {
        workflowDoneRef.current = true;
        setWorkflowDone(true);
      }
      updateTicker(next, workflowDoneRef.current);
      return next;
    });
>>>>>>> main
  };

  useEffect(() => {
    if (!traceId) {
      clearExternal();
      setRows(buildInitialState());
      setConnectionState('idle');
      setConnectionHint('');
      setReplayedCount(0);
      replayedCountRef.current = 0;
      setWorkflowDone(false);
      workflowDoneRef.current = false;
<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
      lastSeqRef.current = -1;
      finalTsRef.current = undefined;
      eventHistoryRef.current = {
        supervisor: [],
        reception: [],
        diagnosis: [],
        kb_retrieval: [],
        treatment: [],
        final: [],
      };
=======
      seenSeqRef.current.clear();
      lastSeqRef.current = -1;
>>>>>>> main
      return;
    }

    clearExternal();
    setRows(buildInitialState());
    setConnectionState('connecting');
    setConnectionHint('正在回放历史事件...');
    setReplayedCount(0);
    replayedCountRef.current = 0;
    setWorkflowDone(false);
    workflowDoneRef.current = false;
<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
    lastSeqRef.current = -1;
    finalTsRef.current = undefined;
    eventHistoryRef.current = {
      supervisor: [],
      reception: [],
      diagnosis: [],
      kb_retrieval: [],
      treatment: [],
      final: [],
    };
=======
    seenSeqRef.current.clear();
    lastSeqRef.current = -1;
>>>>>>> main

    let cancelled = false;

    const openStream = () => {
      if (cancelled || workflowDoneRef.current) return;

      const es = new EventSource(`/api/traces/${encodeURIComponent(traceId)}/stream`);
      esRef.current = es;

<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
      es.addEventListener('trace', (messageEvent) => {
        if (cancelled || workflowDoneRef.current) return;
        const raw = JSON.parse(messageEvent.data || '{}') as RawTraceEvent;
        const normalized = normalizeEvent(raw);
        const seq = normalized.seq;
        if (typeof seq === 'number' && Number.isFinite(seq) && seq <= lastSeqRef.current) {
          return;
        }
        applyNormalizedEvent(normalized);
=======
      es.addEventListener('trace', (e) => {
        const payload = normalizeEvent(JSON.parse(e.data || '{}'));
        const seq = payload.seq;
        if (typeof seq === 'number' && Number.isFinite(seq) && seq <= lastSeqRef.current) {
          return;
        }
        handleEvent(payload);
>>>>>>> main
        setConnectionState('connected');
        setConnectionHint(`已回放 ${replayedCountRef.current} 条事件 + 实时连接中`);
      });

      es.onerror = () => {
<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
        if (cancelled || workflowDoneRef.current) return;
        setConnectionState('disconnected');
        setConnectionHint(`实时连接断开（已回放 ${replayedCountRef.current} 条）`);
        closeStream();
=======
        setConnectionState('disconnected');
        setConnectionHint('连接已断开，尝试轮询补齐...');
        clearTicker();
        es.close();

        pollRef.current = setInterval(async () => {
          if (workflowDoneRef.current) return;
          try {
            const resp = await fetch(`/api/trace-events?trace_id=${encodeURIComponent(traceId)}`);
            if (!resp.ok) return;
            const data = await resp.json();
            const list = Array.isArray(data?.events) ? data.events : [];
            list
              .map((eventLike) => normalizeEvent(eventLike))
              .sort(compareEvents)
              .forEach((evt) => {
                const seq = evt.seq;
                if (typeof seq === 'number' && Number.isFinite(seq) && seq <= lastSeqRef.current) {
                  return;
                }
                handleEvent(evt);
              });
          } catch {
            // ignore polling failures
          }
        }, 2000);
>>>>>>> main
      };
    };

    const replayThenConnect = async () => {
      try {
<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
        const response = await fetch(`/api/trace-events?trace_id=${encodeURIComponent(traceId)}`);
        if (!response.ok) {
          setConnectionHint('历史回放失败，尝试直接连接实时流...');
          openStream();
          return;
        }
        const payload = await response.json();
        const events = Array.isArray(payload?.events) ? payload.events : [];
        const sorted = [...events].sort(compareEvents);

        if (cancelled) return;

        let replayed = 0;
        sorted.forEach((raw) => {
          const normalized = normalizeEvent(raw as RawTraceEvent);
          if (applyNormalizedEvent(normalized)) replayed += 1;
        });

        const maxSeq = sorted.reduce((max: number, eventLike: RawTraceEvent) => {
          const seq = eventLike?.seq;
          return typeof seq === 'number' && Number.isFinite(seq) ? Math.max(max, seq) : max;
        }, -1);
        lastSeqRef.current = Math.max(lastSeqRef.current, maxSeq);

        setReplayedCount(replayed);
        replayedCountRef.current = replayed;

        if (workflowDoneRef.current) {
          setConnectionState('disconnected');
          setConnectionHint(`已回放 ${replayed} 条事件，流程已结束`);
          return;
        }

        setConnectionHint(`已回放 ${replayed} 条事件，正在连接实时流...`);
        openStream();
      } catch {
        if (cancelled) return;
        setConnectionState('disconnected');
        setConnectionHint('历史回放异常，实时连接未建立');
=======
        const resp = await fetch(`/api/trace-events?trace_id=${encodeURIComponent(traceId)}`);
        if (!resp.ok) {
          setConnectionHint('历史回放失败，直接连接实时流...');
          openStream();
          return;
        }
        const data = await resp.json();
        const list = Array.isArray(data?.events) ? data.events : [];
        const sorted = list
          .map((eventLike) => normalizeEvent(eventLike))
          .sort(compareEvents);

        if (cancelled) return;

        sorted.forEach((evt) => handleEvent(evt));

        const maxSeq = sorted.reduce((max, evt) => {
          if (typeof evt.seq === 'number' && Number.isFinite(evt.seq)) {
            return Math.max(max, evt.seq);
          }
          return max;
        }, -1);
        lastSeqRef.current = Math.max(lastSeqRef.current, maxSeq);
        setReplayedCount(sorted.length);
        replayedCountRef.current = sorted.length;

        if (workflowDoneRef.current) {
          setConnectionState('disconnected');
          setConnectionHint(`已回放 ${sorted.length} 条事件，流程已结束`);
          return;
        }

        setConnectionHint(`已回放 ${sorted.length} 条事件，正在连接实时流...`);
        openStream();
      } catch {
        if (cancelled) return;
        setConnectionHint('历史回放异常，直接连接实时流...');
        openStream();
>>>>>>> main
      }
    };

    replayThenConnect();

    return () => {
      cancelled = true;
      clearExternal();
    };
  }, [traceId]);

  useEffect(() => {
    if (workflowDone) {
      clearTicker();
<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
      closeStream();
      completeSupervisorOnDone(finalTsRef.current);
=======
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
      setRows((prev) => {
        if (prev.supervisor.status !== 'running') return prev;
        const next = { ...prev };
        next.supervisor = {
          ...next.supervisor,
          status: 'completed',
          progress: 100,
          endTs: next.supervisor.endTs ?? Date.now(),
          lastMessage: next.supervisor.lastMessage || 'supervisor 执行完成',
        };
        return next;
      });
>>>>>>> main
    }
  }, [workflowDone]);

  const renderedRows = useMemo(() => {
    return FIXED_AGENTS.map((def) => {
      const row = rows[def.id];
<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
      const elapsedMs = row.startTs ? Math.max(0, (row.endTs ?? nowMs) - row.startTs) : 0;
      const progress = row.status === 'running' && !workflowDone
        ? Math.max(row.progress, softProgress(elapsedMs))
        : row.progress;
      return {
        ...def,
        ...row,
        progress,
        duration: formatDuration(elapsedMs ?? 0),
      };
    });
  }, [rows, nowMs, workflowDone]);

  const completedCount = useMemo(() => renderedRows.filter((row) => row.status === 'completed').length, [renderedRows]);

  const totalProgress = Math.round((completedCount / FIXED_AGENTS.length) * 100);

  const overallStart = useMemo(() => {
    const starts = renderedRows.map((row) => row.startTs).filter(Boolean) as number[];
=======
      const elapsed = row.startTs ? (row.endTs ?? nowMs) - row.startTs : 0;
      const soft = row.status === 'running' && !workflowDone && row.progress < 90
        ? softProgress(Math.max(0, elapsed))
        : row.progress;
      const progress = row.status === 'running' ? Math.max(row.progress, soft) : row.progress;
      const durationMs = row.startTs ? Math.max(0, (row.endTs ?? nowMs) - row.startTs) : 0;
      const duration = formatDuration(durationMs ?? 0);
      return { ...def, ...row, progress, duration };
    });
  }, [rows, nowMs, workflowDone]);

  const totalProgress = useMemo(() => {
    const sum = renderedRows.reduce((acc, row) => acc + row.progress, 0);
    return Math.round(sum / renderedRows.length);
  }, [renderedRows]);

  const overallStart = useMemo(() => {
    const starts = renderedRows.map((r) => r.startTs).filter(Boolean) as number[];
>>>>>>> main
    return starts.length ? Math.min(...starts) : undefined;
  }, [renderedRows]);

  const overallEnd = useMemo(() => {
    if (!workflowDone) return undefined;
<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
    const ends = renderedRows.map((row) => row.endTs).filter(Boolean) as number[];
=======
    const ends = renderedRows.map((r) => r.endTs).filter(Boolean) as number[];
>>>>>>> main
    return ends.length ? Math.max(...ends) : undefined;
  }, [renderedRows, workflowDone]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="border-[#c8f7c5]/50 text-[#c8f7c5]">
          <Signal className="w-3 h-3 mr-1" />
<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
          {connectionState === 'connected'
            ? 'SSE 已连接'
            : connectionState === 'connecting'
              ? 'SSE 连接中'
              : connectionState === 'disconnected'
                ? 'SSE 已断开'
                : '等待 trace'}
=======
          {connectionState === 'connected' ? 'SSE 已连接' : connectionState === 'connecting' ? 'SSE 连接中' : connectionState === 'disconnected' ? 'SSE 已断开' : '等待 trace'}
>>>>>>> main
        </Badge>
        {connectionHint && <span className="text-xs text-white/50">{connectionHint}</span>}
        {replayedCount > 0 && <span className="text-xs text-[#c8f7c5]/70">已回放 {replayedCount} 条</span>}
        {typeof diagnosisConfidencePct === 'number' && (
          <Badge className="bg-[#c8f7c5]/20 text-[#c8f7c5] border border-[#c8f7c5]/30">
            诊断置信度 {diagnosisConfidencePct.toFixed(2)}%
          </Badge>
        )}
        {workflowDone && (
          <Badge className="bg-green-500/20 text-green-300 border border-green-400/40">
            <BadgeCheck className="w-3 h-3 mr-1" />流程已结束
          </Badge>
        )}
      </div>

      <div className="space-y-0">
        {renderedRows.map((row, idx) => {
          const Icon = row.icon;
          const running = row.status === 'running' && !workflowDone;
          return (
            <div key={row.id} className="animate-phase-enter">
              <div className="flex gap-3">
                <div className="flex flex-col items-center">
                  <div
                    className={cn(
                      'w-9 h-9 rounded-full border flex items-center justify-center',
                      row.status === 'completed' && 'bg-green-500/20 border-green-400 text-green-300',
                      running && 'bg-[#c8f7c5]/20 border-[#c8f7c5] text-[#c8f7c5] animate-phase-pulse',
                      row.status === 'error' && 'bg-red-500/20 border-red-400 text-red-300',
                      row.status === 'pending' && 'bg-white/5 border-white/20 text-white/50',
                    )}
                  >
                    {row.status === 'completed'
                      ? <CheckCircle2 className="w-5 h-5" />
                      : row.status === 'error'
                        ? <AlertTriangle className="w-5 h-5" />
                        : running
                          ? <Loader2 className="w-5 h-5 animate-spin" />
                          : <Icon className="w-5 h-5" />}
                  </div>

                  {idx < renderedRows.length - 1 && (
                    <div className="w-[2px] h-10 mt-1 rounded-full bg-white/10 overflow-hidden">
                      <div
                        className={cn(
                          'w-full transition-all duration-500',
                          row.status === 'completed' ? 'h-full bg-green-400 progress-shine' : 'h-0',
                        )}
                      />
                    </div>
                  )}
                </div>

                <div className="flex-1 pb-4">
                  <div className="bg-white/5 border border-white/10 rounded-xl p-3">
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <div className="flex items-center gap-2">
                        <h4 className="text-white font-medium">{row.name}</h4>
                        <Badge
                          variant="outline"
                          className={cn(
                            'text-xs',
                            row.status === 'completed' && 'border-green-400/50 text-green-300',
                            running && 'border-[#c8f7c5]/50 text-[#c8f7c5]',
                            row.status === 'error' && 'border-red-400/50 text-red-300',
                            row.status === 'pending' && 'border-white/20 text-white/60',
                          )}
                        >
                          {row.status}
                        </Badge>
                      </div>
                      <div className="text-xs text-white/50 flex items-center gap-1">
                        <Timer className="w-3 h-3" />
                        {row.startTs
                          ? row.status === 'completed'
                            ? `✓ 完成 (${row.duration})`
                            : row.status === 'running'
                              ? `进行中 (${row.duration})`
                              : row.status === 'error'
                                ? `中断 (${row.duration})`
                                : row.duration
                          : '等待执行'}
                      </div>
                    </div>

                    <p className={cn('text-sm mt-2 text-white/70', running && 'animate-pulse')}>
                      {row.lastMessage || row.description}
                    </p>

<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
                    <div className="mt-3 rounded-md bg-black/25 border border-white/10 p-2">
                      <p className="text-xs text-[#c8f7c5] mb-1">关键步骤</p>
                      {row.highlights.length ? (
                        <ul className="space-y-1">
                          {row.highlights.map((highlight, index) => (
                            <li key={`${row.id}-h-${index}`} className="text-xs text-white/70 flex items-start gap-1">
                              <span className="text-[#c8f7c5] mt-[2px]">•</span>
                              <span>{highlight}</span>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-xs text-white/40">暂无关键步骤</p>
                      )}
                    </div>

                    <button
                      type="button"
                      className="mt-2 text-xs text-white/50 hover:text-white/80 inline-flex items-center gap-1"
                      onClick={() => setDebugOpen((prev) => ({ ...prev, [row.id]: !prev[row.id] }))}
                    >
                      {debugOpen[row.id] ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                      最近子步骤（最近3条）
                    </button>

                    {debugOpen[row.id] && (
                      <div className="mt-1 space-y-1">
                        {row.steps.length ? row.steps.map((step, index) => (
                          <div key={`${step.seq ?? 'na'}-${index}`} className="text-xs text-white/50">
                            <span className="text-white/70">{step.node}</span>
                            <span className="mx-1">·</span>
                            <span>{step.message}</span>
                          </div>
                        )) : <div className="text-xs text-white/40">暂无子步骤</div>}
                      </div>
                    )}

=======
                    <div className="mt-2 space-y-1">
                      {row.steps.map((step, i) => (
                        <div key={`${step.seq ?? 'na'}-${i}`} className="text-xs text-white/50">
                          <span className="text-white/70">{step.node}</span>
                          <span className="mx-1">·</span>
                          <span>{step.message}</span>
                        </div>
                      ))}
                    </div>

>>>>>>> main
                    <div className="mt-3 h-2 rounded-full bg-white/10 overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-500 progress-shine"
                        style={{
                          width: `${Math.max(0, Math.min(100, row.progress))}%`,
                          backgroundColor: row.status === 'error' ? '#f87171' : '#c8f7c5',
                        }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="bg-white/5 border border-white/10 rounded-xl p-4">
        <div className="flex items-center justify-between text-sm mb-2">
          <span className="text-white/70">总体进度</span>
<<<<<<< codex/analyze-repository-structure-and-routes-ruuczy
          <span className="text-[#c8f7c5] font-mono">{completedCount}/6</span>
=======
          <span className="text-[#c8f7c5] font-mono">{totalProgress}%</span>
>>>>>>> main
        </div>
        <div className="h-2 rounded-full bg-white/10 overflow-hidden">
          <div className="h-full bg-[#4ade80] transition-all duration-500 progress-shine" style={{ width: `${totalProgress}%` }} />
        </div>
        <p className="text-xs text-white/50 mt-2">
          总耗时：{formatDuration((overallStart ? Math.max(0, (overallEnd ?? nowMs) - overallStart) : 0) ?? 0)} {workflowDone ? '· 已结束' : ''}
        </p>
      </div>
    </div>
  );
}
