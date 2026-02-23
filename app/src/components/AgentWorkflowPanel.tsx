import { useEffect, useMemo, useRef, useState } from 'react';
import {
  SearchCheck,
  BookOpen,
  SlidersHorizontal,
  ShieldCheck,
  FilePenLine,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  Signal,
  Timer,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

export type AgentPhaseStatus = 'pending' | 'running' | 'completed' | 'error';

export interface AgentPhase {
  id: 'diagnose' | 'retrieve' | 'plan' | 'validate' | 'generate';
  name: string;
  icon: any;
  description: string;
  status: AgentPhaseStatus;
  progress: number;
  detail?: string;
  confidence?: number;
  startTime?: number;
  endTime?: number;
}

interface AgentWorkflowPanelProps {
  traceId?: string;
  lastConfidencePct?: number;
  traceEvents?: any[];
  onPhaseChange?: (phaseId: string) => void;
  onTraceEvent?: (payload: any) => void;
}

const AGENT_PHASES: AgentPhase[] = [
  {
    id: 'diagnose',
    name: '🕵️ 诊断智能体',
    icon: SearchCheck,
    description: '分析图像特征 / 计算置信度',
    status: 'pending',
    progress: 0,
  },
  {
    id: 'retrieve',
    name: '📚 检索智能体',
    icon: BookOpen,
    description: '查询知识库 / 匹配条目',
    status: 'pending',
    progress: 0,
  },
  {
    id: 'plan',
    name: '⚙️ 规划智能体',
    icon: SlidersHorizontal,
    description: '结合个性化约束过滤并规划',
    status: 'pending',
    progress: 0,
  },
  {
    id: 'validate',
    name: '🛡️ 验证智能体',
    icon: ShieldCheck,
    description: '校对处方与合规性检查',
    status: 'pending',
    progress: 0,
  },
  {
    id: 'generate',
    name: '✍️ 生成智能体',
    icon: FilePenLine,
    description: '生成最终报告 / 结构化输出',
    status: 'pending',
    progress: 0,
  },
];

// 步骤0（开发期保留）: 基于已观测节点建立 phaseMap。
const NODE_PHASE_MAP: Record<string, AgentPhase['id']> = {
  ParseInput: 'diagnose',
  DiagnosisAgent: 'diagnose',
  ConfidenceGate: 'diagnose',
  diagnosis: 'diagnose',
  confirm_input: 'diagnose',

  KBRetrievalAgent: 'retrieve',
  kb_retrieval: 'retrieve',

  PersonalizationAgent: 'plan',
  reception: 'plan',
  supervisor: 'plan',
  treatment: 'plan',

  ValidatorAgent: 'validate',
  validate: 'validate',
  check: 'validate',

  PrescriptionAgent: 'generate',
  Persist: 'generate',
  Final: 'generate',
  report: 'generate',
};

const PHASE_ORDER: AgentPhase['id'][] = ['diagnose', 'retrieve', 'plan', 'validate', 'generate'];

function normalizeStatus(status: unknown): 'start' | 'progress' | 'completed' | 'error' | 'info' {
  const text = String(status || '').toLowerCase();
  if (['start', 'started', 'begin', 'running', '执行中', '开始'].includes(text)) return 'start';
  if (['progress', 'processing', '进行中'].includes(text)) return 'progress';
  if (['end', 'done', 'completed', 'finish', '完成'].includes(text)) return 'completed';
  if (['error', 'failed', '错误', 'fail'].includes(text)) return 'error';
  return 'info';
}

function inferPhaseId(node: string, message?: string): AgentPhase['id'] {
  const text = `${node || ''} ${message || ''}`.toLowerCase();
  if (text.includes('kb') || text.includes('retrieve') || text.includes('query')) return 'retrieve';
  if (text.includes('validate') || text.includes('check') || text.includes('校验')) return 'validate';
  if (text.includes('plan') || text.includes('filter') || text.includes('constraint') || text.includes('个性化')) return 'plan';
  if (text.includes('report') || text.includes('generate') || text.includes('write') || text.includes('final') || text.includes('输出')) return 'generate';
  return 'diagnose';
}

function formatDuration(start?: number, end?: number, now?: number) {
  if (!start) return '0.00';
  const finalTs = end ?? now ?? Date.now();
  return ((finalTs - start) / 1000).toFixed(2);
}

export function AgentWorkflowPanel({ traceId, lastConfidencePct, traceEvents, onPhaseChange, onTraceEvent }: AgentWorkflowPanelProps) {
  const [phases, setPhases] = useState<AgentPhase[]>(AGENT_PHASES);
  const [connectionState, setConnectionState] = useState<'idle' | 'connecting' | 'connected' | 'disconnected'>('idle');
  const [connectionHint, setConnectionHint] = useState('');
  const [now, setNow] = useState(Date.now());
  const [activePhaseId, setActivePhaseId] = useState<string>('');

  const intervalRefs = useRef<Record<string, ReturnType<typeof setInterval> | undefined>>({});
  const esRef = useRef<EventSource | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const seenRef = useRef<Set<string>>(new Set());
  const sampledNodesRef = useRef<string[]>([]);
  const hasRealEventRef = useRef(false);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (typeof lastConfidencePct === 'number' && Number.isFinite(lastConfidencePct)) {
      setPhases((prev: AgentPhase[]) => prev.map((phase: AgentPhase) => phase.id === 'diagnose' ? { ...phase, confidence: lastConfidencePct } : phase));
    }
  }, [lastConfidencePct]);

  useEffect(() => {
    if (!traceEvents?.length) return;
    const nodes = traceEvents.map((evt) => evt?.node || evt?.agent).filter(Boolean);
    const unique = Array.from(new Set(nodes)).slice(0, 20);
    if (unique.length > 0) {
      console.log('[AgentWorkflowPanel] sampled trace nodes (max20):', unique);
    }
  }, [traceEvents]);

  const clearSimProgress = (phaseId: string) => {
    const existing = intervalRefs.current[phaseId];
    if (existing) {
      clearInterval(existing);
      intervalRefs.current[phaseId] = undefined;
    }
  };

  const startSimProgress = (phaseId: string) => {
    clearSimProgress(phaseId);
    intervalRefs.current[phaseId] = setInterval(() => {
      setPhases((prev: AgentPhase[]) => prev.map((phase: AgentPhase) => {
        if (phase.id !== phaseId || phase.status !== 'running') return phase;
        const next = Math.min(90, phase.progress + 2);
        return { ...phase, progress: next };
      }));
    }, 200);
  };

  const recordNodeSample = (node: string) => {
    if (!node) return;
    if (!sampledNodesRef.current.includes(node)) {
      sampledNodesRef.current.push(node);
      if (sampledNodesRef.current.length <= 20) {
        console.log('[AgentWorkflowPanel] node sample:', sampledNodesRef.current);
      }
    }
  };

  const handleTraceEvent = (rawPayload: any) => {
    const payload = rawPayload || {};
    const node = String(payload.node || payload.agent || '');
    const status = normalizeStatus(payload.status);
    const message = payload.message || payload.step || '';
    const outputs = payload.outputs || payload.payload || {};
    const phaseId = NODE_PHASE_MAP[node] || inferPhaseId(node, message);

    recordNodeSample(node);
    onTraceEvent?.(payload);
    hasRealEventRef.current = true;

    if (status === 'info') return;

    const idx = PHASE_ORDER.indexOf(phaseId);

    setPhases((prev: AgentPhase[]) => {
      const cloned = prev.map((phase) => ({ ...phase }));
      const current = cloned.find((phase) => phase.id === phaseId);
      if (!current) return prev;

      if (status === 'start') {
        for (let i = 0; i < idx; i += 1) {
          const before = cloned.find((phase) => phase.id === PHASE_ORDER[i]);
          if (before && before.status === 'running') {
            before.status = 'completed';
            before.progress = 100;
            before.endTime = Date.now();
          }
        }

        current.status = 'running';
        current.startTime = current.startTime ?? Date.now();
        current.progress = Math.max(current.progress, 5);
        current.detail = message || '阶段启动';
        setActivePhaseId(phaseId);
        onPhaseChange?.(phaseId);
        startSimProgress(phaseId);
      }

      if (status === 'progress') {
        const candidateProgress = Number(outputs?.progress ?? payload?.progress);
        const nextProgress = Number.isFinite(candidateProgress)
          ? Math.min(95, Math.max(0, candidateProgress))
          : Math.min(95, current.progress + 5);
        current.status = current.status === 'pending' ? 'running' : current.status;
        current.startTime = current.startTime ?? Date.now();
        current.progress = Math.max(current.progress, nextProgress);
        if (message) current.detail = message;
        if (current.status === 'running' && !intervalRefs.current[phaseId]) {
          startSimProgress(phaseId);
        }
      }

      if (status === 'completed') {
        current.status = 'completed';
        current.progress = 100;
        current.endTime = Date.now();
        current.detail = message || '处理完成';
        clearSimProgress(phaseId);
      }

      if (status === 'error') {
        current.status = 'error';
        current.endTime = Date.now();
        current.detail = message || '发生错误';
        clearSimProgress(phaseId);
      }

      const confidence = Number(outputs?.confidence_pct ?? outputs?.confidence ?? payload?.confidence_pct ?? payload?.confidence);
      if (Number.isFinite(confidence)) {
        const diagnose = cloned.find((phase) => phase.id === 'diagnose');
        if (diagnose) {
          diagnose.confidence = confidence <= 1 ? confidence * 100 : confidence;
        }
      }

      return cloned;
    });
  };

  useEffect(() => {
    return () => {
      Object.keys(intervalRefs.current).forEach((key) => clearSimProgress(key));
    };
  }, []);

  useEffect(() => {
    if (!traceId) {
      setPhases(AGENT_PHASES);
      setConnectionState('idle');
      setConnectionHint('');
      return;
    }

    setPhases(AGENT_PHASES.map((phase) => ({ ...phase, detail: phase.description })));
    seenRef.current.clear();
    sampledNodesRef.current = [];
    hasRealEventRef.current = false;
    setConnectionState('connecting');
    setConnectionHint('正在连接追踪流...');

    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }

    const fallbackBoot = setTimeout(() => {
      if (!hasRealEventRef.current) {
        handleTraceEvent({ node: 'DiagnosisAgent', status: 'start', message: '等待后端事件，已启用模拟进度' });
      }
    }, 1200);

    const es = new EventSource(`/api/traces/${encodeURIComponent(traceId)}/stream`);
    esRef.current = es;

    es.addEventListener('trace', (evt) => {
      const payload = JSON.parse(evt.data || '{}');
      const eventKey = `${payload.trace_id || traceId}-${payload.seq || ''}-${payload.ts || ''}-${payload.node || ''}-${payload.status || ''}`;
      if (!seenRef.current.has(eventKey)) {
        seenRef.current.add(eventKey);
        handleTraceEvent(payload);
      }
      setConnectionState('connected');
      setConnectionHint('SSE 实时连接中');
    });

    es.onerror = () => {
      setConnectionState('disconnected');
      setConnectionHint('连接已断开，尝试使用轮询补齐...');
      es.close();

      pollRef.current = setInterval(async () => {
        try {
          const resp = await fetch(`/api/trace-events?trace_id=${encodeURIComponent(traceId)}`);
          if (!resp.ok) return;
          const data = await resp.json();
          const list = Array.isArray(data?.events) ? data.events : [];
          list.slice(-20).forEach((evt: any, idx: number) => {
            const payload = {
              node: evt?.node || evt?.agent,
              status: evt?.status || evt?.step,
              message: evt?.message || evt?.step,
              payload: evt?.payload || {},
              ts: evt?.timestamp,
              seq: evt?.seq ?? idx,
            };
            const eventKey = `${traceId}-${payload.seq || ''}-${payload.ts || ''}-${payload.node || ''}-${payload.status || ''}`;
            if (!seenRef.current.has(eventKey)) {
              seenRef.current.add(eventKey);
              handleTraceEvent(payload);
            }
          });
        } catch {
          // ignore polling errors
        }
      }, 2000);
    };

    return () => {
      clearTimeout(fallbackBoot);
      es.close();
      esRef.current = null;
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [traceId]);

  const totalProgress = useMemo(() => {
    const sum = phases.reduce((acc: number, phase: AgentPhase) => acc + phase.progress, 0);
    return Math.round(sum / phases.length);
  }, [phases]);

  const totalStart = useMemo(() => {
    const starts = phases.map((phase: AgentPhase) => phase.startTime).filter(Boolean) as number[];
    return starts.length > 0 ? Math.min(...starts) : undefined;
  }, [phases]);

  const totalEnd = useMemo(() => {
    const ends = phases.map((phase: AgentPhase) => phase.endTime).filter(Boolean) as number[];
    if (ends.length === 0) return undefined;
    if (phases.some((phase: AgentPhase) => phase.status === 'running')) return undefined;
    return Math.max(...ends);
  }, [phases]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="border-[#c8f7c5]/50 text-[#c8f7c5]">
          <Signal className="w-3 h-3 mr-1" />
          {connectionState === 'connected' ? 'SSE 已连接' : connectionState === 'connecting' ? 'SSE 连接中' : connectionState === 'disconnected' ? 'SSE 已断开' : '等待 trace'}
        </Badge>
        {connectionHint && <span className="text-xs text-white/50">{connectionHint}</span>}
        {typeof lastConfidencePct === 'number' && (
          <Badge className="bg-[#c8f7c5]/20 text-[#c8f7c5] border border-[#c8f7c5]/30">置信度 {lastConfidencePct.toFixed(2)}%</Badge>
        )}
      </div>

      <div className="space-y-0">
        {phases.map((phase: AgentPhase, idx: number) => {
          const Icon = phase.icon;
          const duration = formatDuration(phase.startTime, phase.endTime, now);
          return (
            <div key={phase.id} className="animate-phase-enter">
              <div className="flex gap-3">
                <div className="flex flex-col items-center">
                  <div
                    className={cn(
                      'w-9 h-9 rounded-full border flex items-center justify-center',
                      phase.status === 'completed' && 'bg-green-500/20 border-green-400 text-green-300',
                      phase.status === 'running' && 'bg-[#c8f7c5]/20 border-[#c8f7c5] text-[#c8f7c5] animate-phase-pulse',
                      phase.status === 'error' && 'bg-red-500/20 border-red-400 text-red-300',
                      phase.status === 'pending' && 'bg-white/5 border-white/20 text-white/50',
                    )}
                  >
                    {phase.status === 'completed' ? (
                      <CheckCircle2 className="w-5 h-5" />
                    ) : phase.status === 'error' ? (
                      <AlertTriangle className="w-5 h-5" />
                    ) : phase.status === 'running' ? (
                      <Loader2 className="w-5 h-5 animate-spin" />
                    ) : (
                      <Icon className="w-5 h-5" />
                    )}
                  </div>
                  {idx < phases.length - 1 && (
                    <div className="w-[2px] h-10 mt-1 rounded-full bg-white/10 overflow-hidden">
                      <div
                        className={cn(
                          'w-full transition-all duration-500',
                          phase.status === 'completed' ? 'h-full bg-green-400 progress-shine' : 'h-0',
                        )}
                      />
                    </div>
                  )}
                </div>

                <div className="flex-1 pb-4">
                  <div className="bg-white/5 border border-white/10 rounded-xl p-3">
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <div className="flex items-center gap-2">
                        <h4 className="text-white font-medium">{phase.name}</h4>
                        <Badge
                          variant="outline"
                          className={cn(
                            'text-xs',
                            phase.status === 'completed' && 'border-green-400/50 text-green-300',
                            phase.status === 'running' && 'border-[#c8f7c5]/50 text-[#c8f7c5]',
                            phase.status === 'error' && 'border-red-400/50 text-red-300',
                            phase.status === 'pending' && 'border-white/20 text-white/60',
                          )}
                        >
                          {phase.status}
                        </Badge>
                        {phase.id === 'diagnose' && typeof phase.confidence === 'number' && (
                          <Badge className="bg-[#c8f7c5]/15 text-[#c8f7c5] border border-[#c8f7c5]/30">
                            置信度 {phase.confidence.toFixed(2)}%
                          </Badge>
                        )}
                      </div>
                      <div className="text-xs text-white/50 flex items-center gap-1">
                        <Timer className="w-3 h-3" />
                        {phase.status === 'completed' ? `✓ 完成 (${duration}s)` : phase.status === 'running' ? `进行中 (${duration}s)` : '等待执行'}
                      </div>
                    </div>
                    <p className={cn('text-sm mt-2 text-white/70', phase.status === 'running' && 'animate-pulse')}>
                      {phase.detail || phase.description}
                    </p>
                    <div className="mt-3 h-2 rounded-full bg-white/10 overflow-hidden">
                      <div
                        className={cn('h-full rounded-full bg-[#c8f7c5] transition-all duration-500 progress-shine')}
                        style={{ width: `${Math.min(100, Math.max(0, phase.progress))}%` }}
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
        <p className="text-xs text-white/50 mt-2">总耗时：{formatDuration(totalStart, totalEnd, now)}s {activePhaseId ? `· 当前阶段 ${activePhaseId}` : ''}</p>
      </div>
    </div>
  );
}
