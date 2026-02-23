import { useEffect, useMemo, useRef, useState } from 'react';
import {
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
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

type AgentStatus = 'pending' | 'running' | 'completed' | 'error';

type FixedAgentId = 'supervisor' | 'reception' | 'diagnosis' | 'kb_retrieval' | 'treatment' | 'final';

interface WorkflowEvent {
  seq?: number;
  ts?: string;
  node?: string;
  agent_id?: string;
  status?: string;
  message?: string;
  payload?: Record<string, any>;
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
}

interface AgentWorkflowPanelProps {
  traceId?: string;
  confidencePct?: number;
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
};

const buildInitialState = (): Record<FixedAgentId, AgentRowState> => {
  return FIXED_AGENTS.reduce((acc, row) => {
    acc[row.id] = {
      id: row.id,
      status: 'pending',
      progress: 0,
      lastMessage: row.description,
      steps: [],
    };
    return acc;
  }, {} as Record<FixedAgentId, AgentRowState>);
};

const normalizeStatus = (status: unknown): 'start' | 'progress' | 'completed' | 'error' | 'info' => {
  const text = String(status || '').toLowerCase();
  if (['start', 'started', 'begin', 'running', '执行中', '开始'].includes(text)) return 'start';
  if (['progress', 'processing', '进行中'].includes(text)) return 'progress';
  if (['end', 'done', 'completed', 'finish', '结束', '完成'].includes(text)) return 'completed';
  if (['error', 'failed', '错误', 'fail'].includes(text)) return 'error';
  return 'info';
};

const parseTsMs = (ts?: string): number | undefined => {
  if (!ts) return undefined;
  const ms = Date.parse(ts);
  return Number.isFinite(ms) ? ms : undefined;
};

const clamp = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v));

const softProgress = (elapsedMs: number) => clamp(Math.round((elapsedMs / 8000) * 90), 5, 90);

const normalizeMessage = (rawMessage: unknown, fallback: string) => {
  const m = String(rawMessage || '').trim();
  if (!m || m.toLowerCase() === 'start') return fallback;
  return m;
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

export function AgentWorkflowPanel({ traceId, confidencePct }: AgentWorkflowPanelProps) {
  const [rows, setRows] = useState<Record<FixedAgentId, AgentRowState>>(buildInitialState());
  const [connectionState, setConnectionState] = useState<'idle' | 'connecting' | 'connected' | 'disconnected'>('idle');
  const [connectionHint, setConnectionHint] = useState('');
  const [nowMs, setNowMs] = useState(Date.now());
  const [workflowDone, setWorkflowDone] = useState(false);
  const [diagnosisConfidencePct, setDiagnosisConfidencePct] = useState<number | undefined>(undefined);

  const esRef = useRef<EventSource | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const tickerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const seenSeqRef = useRef<Set<number>>(new Set());
  const lastSeqRef = useRef(-1);
  const workflowDoneRef = useRef(false);

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

  const updateTicker = (snapshot: Record<FixedAgentId, AgentRowState>, done: boolean) => {
    const hasRunning = FIXED_AGENTS.some((a) => snapshot[a.id].status === 'running');
    if (!done && hasRunning) {
      if (!tickerRef.current) {
        tickerRef.current = setInterval(() => setNowMs(Date.now()), 100);
      }
    } else {
      clearTicker();
    }
  };

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
      if (Number.isFinite(rawConfidence)) {
        setDiagnosisConfidencePct(rawConfidence <= 1 ? rawConfidence * 100 : rawConfidence);
      }
    }

    setRows((prev) => {
      const next = { ...prev };
      const current = { ...next[mappedAgent] };

      current.steps = [...current.steps, { seq: seqRaw, node: nodeName, message }]
        .sort((a, b) => {
          const sa = typeof a.seq === 'number' ? a.seq : Number.MAX_SAFE_INTEGER;
          const sb = typeof b.seq === 'number' ? b.seq : Number.MAX_SAFE_INTEGER;
          return sa - sb;
        })
        .slice(-3);
      current.lastMessage = message;

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
        }
        current.progress = 100;
      }

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
  };

  useEffect(() => {
    if (!traceId) {
      clearExternal();
      setRows(buildInitialState());
      setConnectionState('idle');
      setConnectionHint('');
      setWorkflowDone(false);
      workflowDoneRef.current = false;
      seenSeqRef.current.clear();
      lastSeqRef.current = -1;
      return;
    }

    clearExternal();
    setRows(buildInitialState());
    setConnectionState('connecting');
    setConnectionHint('正在连接追踪流...');
    setWorkflowDone(false);
    workflowDoneRef.current = false;
    seenSeqRef.current.clear();
    lastSeqRef.current = -1;

    const es = new EventSource(`/api/traces/${encodeURIComponent(traceId)}/stream`);
    esRef.current = es;

    es.addEventListener('trace', (e) => {
      const payload = JSON.parse(e.data || '{}') as WorkflowEvent;
      handleEvent(payload);
      setConnectionState('connected');
      setConnectionHint('SSE 实时连接中');
    });

    es.onerror = () => {
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
          list.forEach((evt: any) => {
            handleEvent({
              seq: evt?.seq,
              ts: evt?.ts || evt?.timestamp,
              node: evt?.node || evt?.agent,
              agent_id: evt?.agent_id || evt?.payload?.agent_id,
              status: evt?.status || evt?.step,
              message: evt?.message,
              payload: evt?.payload || {},
            });
          });
        } catch {
          // ignore polling failures
        }
      }, 2000);
    };

    return () => clearExternal();
  }, [traceId]);

  useEffect(() => {
    if (workflowDone) clearTicker();
  }, [workflowDone]);

  const renderedRows = useMemo(() => {
    return FIXED_AGENTS.map((def) => {
      const row = rows[def.id];
      const elapsed = row.startTs ? (row.endTs ?? nowMs) - row.startTs : 0;
      const soft = row.status === 'running' && !workflowDone && row.progress < 90
        ? softProgress(Math.max(0, elapsed))
        : row.progress;
      const progress = row.status === 'running' ? Math.max(row.progress, soft) : row.progress;
      const duration = formatDuration(row.startTs, row.endTs, nowMs);
      return { ...def, ...row, progress, duration };
    });
  }, [rows, nowMs, workflowDone]);

  const totalProgress = useMemo(() => {
    const sum = renderedRows.reduce((acc, row) => acc + row.progress, 0);
    return Math.round(sum / renderedRows.length);
  }, [renderedRows]);

  const overallStart = useMemo(() => {
    const starts = renderedRows.map((r) => r.startTs).filter(Boolean) as number[];
    return starts.length ? Math.min(...starts) : undefined;
  }, [renderedRows]);

  const overallEnd = useMemo(() => {
    if (!workflowDone) return undefined;
    const ends = renderedRows.map((r) => r.endTs).filter(Boolean) as number[];
    return ends.length ? Math.max(...ends) : undefined;
  }, [renderedRows, workflowDone]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="border-[#c8f7c5]/50 text-[#c8f7c5]">
          <Signal className="w-3 h-3 mr-1" />
          {connectionState === 'connected' ? 'SSE 已连接' : connectionState === 'connecting' ? 'SSE 连接中' : connectionState === 'disconnected' ? 'SSE 已断开' : '等待 trace'}
        </Badge>
        {connectionHint && <span className="text-xs text-white/50">{connectionHint}</span>}
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
                        {row.duration
                          ? row.status === 'completed'
                            ? `✓ 完成 (${row.duration}s)`
                            : row.status === 'running'
                              ? `进行中 (${row.duration}s)`
                              : row.status === 'error'
                                ? `中断 (${row.duration}s)`
                                : ''
                          : '等待执行'}
                      </div>
                    </div>

                    <p className={cn('text-sm mt-2 text-white/70', running && 'animate-pulse')}>
                      {row.lastMessage || row.description}
                    </p>

                    <div className="mt-2 space-y-1">
                      {row.steps.map((step, i) => (
                        <div key={`${step.seq ?? 'na'}-${i}`} className="text-xs text-white/50">
                          <span className="text-white/70">{step.node}</span>
                          <span className="mx-1">·</span>
                          <span>{step.message}</span>
                        </div>
                      ))}
                    </div>

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
          <span className="text-[#c8f7c5] font-mono">{totalProgress}%</span>
        </div>
        <div className="h-2 rounded-full bg-white/10 overflow-hidden">
          <div className="h-full bg-[#4ade80] transition-all duration-500 progress-shine" style={{ width: `${totalProgress}%` }} />
        </div>
        <p className="text-xs text-white/50 mt-2">
          总耗时：{formatDuration(overallStart, overallEnd, nowMs) ?? '0.00'}s {workflowDone ? '· 已结束' : ''}
        </p>
      </div>
    </div>
  );
}
