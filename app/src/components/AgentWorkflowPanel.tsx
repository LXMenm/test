import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Bot,
  SearchCheck,
  ShieldCheck,
  BookOpen,
  SlidersHorizontal,
  FilePenLine,
  Database,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  Signal,
  Timer,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

type NodeStatus = 'pending' | 'running' | 'completed' | 'error';

interface AgentCatalogItem {
  id: string;
  name: string;
  description: string;
}

interface NodeState {
  id: string;
  nodeName: string;
  status: NodeStatus;
  progress: number;
  detail: string;
  startTime?: number;
  endTime?: number;
  seqFirstSeen?: number;
  agentId?: string;
  agentName?: string;
}

interface AgentWorkflowPanelProps {
  traceId?: string;
  lastConfidencePct?: number;
  onPhaseChange?: (phaseId: string) => void;
}

const ICONS: Record<string, any> = {
  parse_input: SearchCheck,
  reception: Bot,
  diagnosis: SearchCheck,
  confidence_gate: ShieldCheck,
  kb_retrieval: BookOpen,
  personalization: SlidersHorizontal,
  treatment: FilePenLine,
  prescription: FilePenLine,
  validator: ShieldCheck,
  persist: Database,
  supervisor: Bot,
  confirm_input: SearchCheck,
  final: CheckCircle2,
};

const normalizeStatus = (status: unknown): 'start' | 'progress' | 'completed' | 'error' | 'info' => {
  const text = String(status || '').toLowerCase();
  if (['start', 'started', 'begin', 'running', '执行中', '开始'].includes(text)) return 'start';
  if (['progress', 'processing', '进行中'].includes(text)) return 'progress';
  if (['end', 'done', 'completed', 'finish', '结束', '完成'].includes(text)) return 'completed';
  if (['error', 'failed', '错误', 'fail'].includes(text)) return 'error';
  return 'info';
};

const defaultDetail = (status: 'start' | 'progress' | 'completed' | 'error' | 'info', nodeName: string) => {
  if (status === 'start') return `开始执行 ${nodeName}`;
  if (status === 'progress') return `${nodeName} 处理中`;
  if (status === 'completed') return `${nodeName} 已完成`;
  if (status === 'error') return `${nodeName} 执行失败`;
  return nodeName;
};

const formatDuration = (start?: number, end?: number, now?: number) => {
  if (!start) return null;
  const finalTs = end ?? now;
  if (!finalTs) return null;
  return (((finalTs - start) / 1000)).toFixed(2);
};

const isDoneEvent = (nodeName: string, status: string, message?: string) => {
  const n = (nodeName || '').toLowerCase();
  const s = (status || '').toLowerCase();
  const m = (message || '').toLowerCase();
  const finalNode = ['final', 'end', 'finish', '结束'];
  return finalNode.some((k) => n.includes(k)) || (s === 'end' && finalNode.some((k) => n.includes(k))) || m.includes('结束');
};

export function AgentWorkflowPanel({ traceId, lastConfidencePct, onPhaseChange }: AgentWorkflowPanelProps) {
  const [catalog, setCatalog] = useState<AgentCatalogItem[]>([]);
  const [nodeToAgent, setNodeToAgent] = useState<Record<string, string>>({});
  const [renderNodes, setRenderNodes] = useState<NodeState[]>([]);
  const [connectionState, setConnectionState] = useState<'idle' | 'connecting' | 'connected' | 'disconnected'>('idle');
  const [connectionHint, setConnectionHint] = useState('');
  const [now, setNow] = useState(Date.now());
  const [workflowDone, setWorkflowDone] = useState(false);

  const nodesRef = useRef<Map<string, NodeState>>(new Map());
  const orderRef = useRef<string[]>([]);
  const progressTimers = useRef<Record<string, ReturnType<typeof setInterval>>>({});
  const esRef = useRef<EventSource | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const maxSeqRef = useRef<number>(-1);
  const arrivalSeqRef = useRef<number>(0);
  const workflowDoneRef = useRef(false);

  const clearNodeTimer = (nodeId: string) => {
    const timer = progressTimers.current[nodeId];
    if (timer) {
      clearInterval(timer);
      delete progressTimers.current[nodeId];
    }
  };

  const clearAllTimers = () => {
    Object.keys(progressTimers.current).forEach((nodeId) => {
      clearInterval(progressTimers.current[nodeId]);
      delete progressTimers.current[nodeId];
    });
  };

  const syncRenderNodes = () => {
    const list = orderRef.current
      .map((id) => nodesRef.current.get(id))
      .filter(Boolean) as NodeState[];
    setRenderNodes(list);
  };

  const startProgressTimer = (nodeId: string) => {
    if (progressTimers.current[nodeId] || workflowDoneRef.current) return;
    progressTimers.current[nodeId] = setInterval(() => {
      if (workflowDoneRef.current) {
        clearNodeTimer(nodeId);
        return;
      }
      const current = nodesRef.current.get(nodeId);
      if (!current || current.status !== 'running') {
        clearNodeTimer(nodeId);
        return;
      }
      current.progress = Math.min(90, current.progress + 2);
      nodesRef.current.set(nodeId, { ...current });
      syncRenderNodes();
    }, 200);
  };

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 120);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const resp = await fetch('/api/agents');
        const data = await resp.json();
        if (!alive) return;
        setCatalog(Array.isArray(data?.agents) ? data.agents : []);
        setNodeToAgent(data?.node_to_agent && typeof data.node_to_agent === 'object' ? data.node_to_agent : {});
      } catch {
        if (!alive) return;
        setCatalog([]);
        setNodeToAgent({});
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const getAgentMeta = (agentId?: string) => {
    if (!agentId) return { agentName: '未知节点', description: '等待事件' };
    const found = catalog.find((item) => item.id === agentId);
    if (found) return { agentName: found.name, description: found.description };
    return { agentName: agentId, description: '执行节点' };
  };

  const upsertNode = (payload: any) => {
    if (workflowDoneRef.current) return;

    const nodeName = String(payload?.node || payload?.agent || '').trim();
    if (!nodeName) return;

    const payloadSeq = Number(payload?.seq);
    const hasSeq = Number.isFinite(payloadSeq);
    if (hasSeq) {
      if (payloadSeq < maxSeqRef.current) return;
      maxSeqRef.current = Math.max(maxSeqRef.current, payloadSeq);
    } else {
      arrivalSeqRef.current += 1;
    }

    const normalized = normalizeStatus(payload?.status);
    if (normalized === 'info') return;

    const seqValue = hasSeq ? payloadSeq : arrivalSeqRef.current;

    const agentId = payload?.agent_id || payload?.payload?.agent_id || nodeToAgent[nodeName];
    const { agentName, description } = getAgentMeta(agentId);
    const messageRaw = String(payload?.message || '').trim();
    const message = !messageRaw || messageRaw.toLowerCase() === 'start' ? defaultDetail(normalized, agentName) : messageRaw;

    const existing = nodesRef.current.get(nodeName);
    const base: NodeState = existing
      ? { ...existing }
      : {
          id: nodeName,
          nodeName,
          status: 'pending',
          progress: 0,
          detail: description,
          seqFirstSeen: seqValue,
          agentId,
          agentName,
        };

    if (!existing) {
      nodesRef.current.set(nodeName, base);
      orderRef.current.push(nodeName);
    }

    const current = { ...base, agentId: agentId || base.agentId, agentName: agentName || base.agentName };

    if (normalized === 'start') {
      current.status = 'running';
      current.startTime = current.startTime ?? Date.now();
      current.progress = Math.max(current.progress, 5);
      current.detail = message;
      nodesRef.current.set(nodeName, current);
      startProgressTimer(nodeName);
      onPhaseChange?.(current.agentId || current.nodeName);
    } else if (normalized === 'progress') {
      current.status = current.status === 'pending' ? 'running' : current.status;
      current.startTime = current.startTime ?? Date.now();
      const explicitProgress = Number(payload?.payload?.progress ?? payload?.progress);
      const nextProgress = Number.isFinite(explicitProgress)
        ? Math.max(current.progress, Math.min(95, Math.max(0, explicitProgress)))
        : Math.max(current.progress, Math.min(95, current.progress + 5));
      current.progress = nextProgress;
      current.detail = message;
      nodesRef.current.set(nodeName, current);
      startProgressTimer(nodeName);
    } else if (normalized === 'completed') {
      current.status = 'completed';
      current.progress = 100;
      current.endTime = Date.now();
      current.detail = message;
      nodesRef.current.set(nodeName, current);
      clearNodeTimer(nodeName);
    } else if (normalized === 'error') {
      current.status = 'error';
      current.endTime = Date.now();
      current.detail = message;
      nodesRef.current.set(nodeName, current);
      clearNodeTimer(nodeName);
    }

    if (isDoneEvent(nodeName, String(payload?.status || ''), message)) {
      workflowDoneRef.current = true;
      setWorkflowDone(true);
      clearAllTimers();
    }

    syncRenderNodes();
  };

  useEffect(() => {
    if (!traceId) {
      setConnectionState('idle');
      setConnectionHint('');
      nodesRef.current.clear();
      orderRef.current = [];
      setRenderNodes([]);
      return;
    }

    // reset for new trace
    clearAllTimers();
    nodesRef.current.clear();
    orderRef.current = [];
    maxSeqRef.current = -1;
    arrivalSeqRef.current = 0;
    workflowDoneRef.current = false;
    setWorkflowDone(false);
    setRenderNodes([]);

    setConnectionState('connecting');
    setConnectionHint('正在连接追踪流...');

    if (esRef.current) esRef.current.close();
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }

    const es = new EventSource(`/api/traces/${encodeURIComponent(traceId)}/stream`);
    esRef.current = es;

    es.addEventListener('trace', (evt) => {
      const payload = JSON.parse(evt.data || '{}');
      upsertNode(payload);
      setConnectionState('connected');
      setConnectionHint('SSE 实时连接中');
    });

    es.onerror = () => {
      setConnectionState('disconnected');
      setConnectionHint('连接已断开，尝试使用轮询补齐...');
      clearAllTimers();
      es.close();

      pollRef.current = setInterval(async () => {
        if (workflowDoneRef.current) return;
        try {
          const resp = await fetch(`/api/trace-events?trace_id=${encodeURIComponent(traceId)}`);
          if (!resp.ok) return;
          const data = await resp.json();
          const list = Array.isArray(data?.events) ? data.events : [];
          list.forEach((evt: any, idx: number) => {
            upsertNode({
              node: evt?.node || evt?.agent,
              agent_id: evt?.agent_id || evt?.payload?.agent_id,
              status: evt?.status || evt?.step,
              message: evt?.message || evt?.step,
              payload: evt?.payload || {},
              ts: evt?.ts || evt?.timestamp,
              seq: evt?.seq ?? idx,
            });
          });
        } catch {
          // ignore
        }
      }, 2000);
    };

    return () => {
      es.close();
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      clearAllTimers();
    };
  }, [traceId, JSON.stringify(nodeToAgent), catalog.length]);

  const totalProgress = useMemo(() => {
    if (!renderNodes.length) return 0;
    if (workflowDone) {
      const frozen = renderNodes.reduce((acc, node) => acc + node.progress, 0);
      return Math.round(frozen / renderNodes.length);
    }
    const sum = renderNodes.reduce((acc, node) => acc + node.progress, 0);
    return Math.round(sum / renderNodes.length);
  }, [renderNodes, workflowDone]);

  const totalStart = useMemo(() => {
    const starts = renderNodes.map((node) => node.startTime).filter(Boolean) as number[];
    return starts.length ? Math.min(...starts) : undefined;
  }, [renderNodes]);

  const totalEnd = useMemo(() => {
    if (!workflowDone) return undefined;
    const ends = renderNodes.map((node) => node.endTime).filter(Boolean) as number[];
    return ends.length ? Math.max(...ends) : undefined;
  }, [renderNodes, workflowDone]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="border-[#c8f7c5]/50 text-[#c8f7c5]">
          <Signal className="w-3 h-3 mr-1" />
          {connectionState === 'connected'
            ? 'SSE 已连接'
            : connectionState === 'connecting'
              ? 'SSE 连接中'
              : connectionState === 'disconnected'
                ? 'SSE 已断开'
                : '等待 trace'}
        </Badge>
        {connectionHint && <span className="text-xs text-white/50">{connectionHint}</span>}
        {typeof lastConfidencePct === 'number' && (
          <Badge className="bg-[#c8f7c5]/20 text-[#c8f7c5] border border-[#c8f7c5]/30">
            置信度 {lastConfidencePct.toFixed(2)}%
          </Badge>
        )}
      </div>

      <div className="space-y-0">
        {renderNodes.map((node, idx) => {
          const Icon = ICONS[node.agentId || ''] || Bot;
          const running = node.status === 'running' && !workflowDone;
          const dur = formatDuration(node.startTime, node.endTime, now);
          return (
            <div key={node.id} className="animate-phase-enter">
              <div className="flex gap-3">
                <div className="flex flex-col items-center">
                  <div
                    className={cn(
                      'w-9 h-9 rounded-full border flex items-center justify-center',
                      node.status === 'completed' && 'bg-green-500/20 border-green-400 text-green-300',
                      running && 'bg-[#c8f7c5]/20 border-[#c8f7c5] text-[#c8f7c5] animate-phase-pulse',
                      node.status === 'error' && 'bg-red-500/20 border-red-400 text-red-300',
                      node.status === 'pending' && 'bg-white/5 border-white/20 text-white/50',
                    )}
                  >
                    {node.status === 'completed'
                      ? <CheckCircle2 className="w-5 h-5" />
                      : node.status === 'error'
                        ? <AlertTriangle className="w-5 h-5" />
                        : running
                          ? <Loader2 className="w-5 h-5 animate-spin" />
                          : <Icon className="w-5 h-5" />}
                  </div>
                  {idx < renderNodes.length - 1 && (
                    <div className="w-[2px] h-10 mt-1 rounded-full bg-white/10 overflow-hidden">
                      <div
                        className={cn(
                          'w-full transition-all duration-500',
                          node.status === 'completed' ? 'h-full bg-green-400 progress-shine' : 'h-0',
                        )}
                      />
                    </div>
                  )}
                </div>

                <div className="flex-1 pb-4">
                  <div className="bg-white/5 border border-white/10 rounded-xl p-3">
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <div className="flex items-center gap-2">
                        <h4 className="text-white font-medium">{node.agentName || node.nodeName}</h4>
                        <Badge
                          variant="outline"
                          className={cn(
                            'text-xs',
                            node.status === 'completed' && 'border-green-400/50 text-green-300',
                            running && 'border-[#c8f7c5]/50 text-[#c8f7c5]',
                            node.status === 'error' && 'border-red-400/50 text-red-300',
                            node.status === 'pending' && 'border-white/20 text-white/60',
                          )}
                        >
                          {node.status}
                        </Badge>
                        <Badge variant="outline" className="border-white/20 text-white/50 text-xs">{node.nodeName}</Badge>
                      </div>
                      <div className="text-xs text-white/50 flex items-center gap-1">
                        <Timer className="w-3 h-3" />
                        {dur ? (node.status === 'completed' ? `✓ 完成 (${dur}s)` : node.status === 'running' ? `进行中 (${dur}s)` : '') : '等待执行'}
                      </div>
                    </div>
                    <p className={cn('text-sm mt-2 text-white/70', running && 'animate-pulse')}>
                      {node.detail}
                    </p>
                    <div className="mt-3 h-2 rounded-full bg-white/10 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-[#c8f7c5] transition-all duration-500 progress-shine"
                        style={{ width: `${Math.max(0, Math.min(100, node.progress))}%` }}
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
          <div
            className="h-full bg-[#4ade80] transition-all duration-500 progress-shine"
            style={{ width: `${totalProgress}%` }}
          />
        </div>
        <p className="text-xs text-white/50 mt-2">
          总耗时：{formatDuration(totalStart, totalEnd, now) ?? '0.00'}s {workflowDone ? '· 已结束' : ''}
        </p>
      </div>
    </div>
  );
}
