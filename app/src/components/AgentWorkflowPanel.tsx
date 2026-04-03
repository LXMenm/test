import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
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
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { fetchTraceEvents } from '@/lib/traceClient';
import type { LucideIcon } from 'lucide-react';
import {
  calcPhaseDurationsByAgent,
  calcOverallPhaseDuration,
  formatDurationMs,
  isReplayTerminalWaitingEvent,
  isWaitingForUserInputEvent,
  parseTsMs,
  shouldIncludeEvent,
  sliceCurrentPhaseEvents,
} from './agentWorkflowTiming';

type AgentStatus = 'pending' | 'running' | 'completed' | 'error';
type FixedAgentId = 'supervisor' | 'reception' | 'diagnosis' | 'kb_retrieval' | 'treatment' | 'verification' | 'final';

interface AgentWorkflowPanelProps {
  traceId?: string;
  confidencePct?: number;
  phaseStartMs?: number;
  refreshToken?: number;
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
  payload?: Record<string, unknown>;
  inputs?: Record<string, unknown>;
  outputs?: Record<string, unknown>;
  decision?: Record<string, unknown>;
}

interface NormalizedEvent {
  seq?: number;
  ts?: string;
  tsMs?: number;
  agentId: FixedAgentId;
  nodeName: string;
  status: AgentStatus | 'info';
  message: string;
  data: Record<string, unknown>;
}


interface AgentPhaseDurations {
  phase1Ms: number;
  phase2Ms: number;
}

interface AgentRowDef {
  id: FixedAgentId;
  name: string;
  description: string;
  icon: LucideIcon;
}

interface AgentRowState {
  id: FixedAgentId;
  status: AgentStatus;
  startTs?: number;
  endTs?: number;
  progress: number;
  lastMessage: string;
  steps: Array<{ seq?: number; node: string; message: string }>;
  highlights: string[];
}

const FIXED_AGENTS: AgentRowDef[] = [
  { id: 'supervisor', name: 'supervisor', description: '监督与路由决策', icon: Bot },
  { id: 'reception', name: 'reception', description: '输入接待与要素提取', icon: Headset },
  { id: 'diagnosis', name: 'diagnosis', description: '病害诊断与置信度评估', icon: Stethoscope },
  { id: 'kb_retrieval', name: 'kb_retrieval', description: '知识库检索与信息补全', icon: BookOpen },
  { id: 'treatment', name: 'treatment', description: '治疗方案生成与个性化约束处理', icon: Pill },
  { id: 'verification', name: 'verification', description: '农业合规性审查与风险复核', icon: BadgeCheck },
  { id: 'final', name: 'final', description: '流程结束与结果输出', icon: Flag },
];

const DIRECT_SET = new Set<FixedAgentId>(['supervisor', 'reception', 'diagnosis', 'kb_retrieval', 'treatment', 'verification', 'final']);

const MERGE_MAP: Record<string, FixedAgentId> = {
  parse_input: 'reception',
  confirm_input: 'supervisor',
  confidence_gate: 'diagnosis',
  personalization: 'treatment',
  prescription: 'treatment',
  validator: 'verification',
  verification: 'verification',
  compliance: 'verification',
  review: 'verification',
  persist: 'treatment',
  final: 'final',
};

const buildInitialState = (): Record<FixedAgentId, AgentRowState> => {
  return FIXED_AGENTS.reduce((acc, row) => {
    acc[row.id] = {
      id: row.id,
      status: 'pending',
      progress: 0,
      lastMessage: row.description,
      steps: [],
      highlights: [],
    };
    return acc;
  }, {} as Record<FixedAgentId, AgentRowState>);
};

const clamp = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v));

const softProgress = (elapsedMs: number) => clamp(Math.round((elapsedMs / 8000) * 90), 5, 90);

const shortText = (value: unknown, max = 80): string => {
  const raw = String(value ?? '').trim();
  if (!raw) return '';
  return raw.length <= max ? raw : `${raw.slice(0, max)}...`;
};

const toArray = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

const isRecord = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);

const normalizeStatus = (status: unknown): AgentStatus | 'info' => {
  const text = String(status || '').toLowerCase();
  if (text === 'waiting_for_supplement') return 'info';
  if (['start', 'started', 'begin', 'running', '执行中', '开始'].includes(text)) return 'running';
  if (['progress', 'processing', '进行中'].includes(text)) return 'running';
  if (['end', 'done', 'completed', 'finish', '结束', '完成'].includes(text)) return 'completed';
  if (['error', 'failed', '错误', 'fail'].includes(text)) return 'error';
  return 'info';
};

const mapToFixedAgent = (agentId: string | undefined, node: string | undefined): FixedAgentId => {
  const aid = String(agentId || '').toLowerCase();
  if (DIRECT_SET.has(aid as FixedAgentId)) return aid as FixedAgentId;
  if (MERGE_MAP[aid]) return MERGE_MAP[aid];

  const nodeLower = String(node || '').toLowerCase();
  if (nodeLower === 'final') return 'final';
  if (nodeLower.includes('final')) return 'final';
  if (nodeLower.includes('verification') || nodeLower.includes('validator') || nodeLower.includes('review') || nodeLower.includes('compliance')) return 'verification';
  if (nodeLower.includes('retrieve') || nodeLower.includes('kb')) return 'kb_retrieval';
  if (nodeLower.includes('diagnosis') || nodeLower.includes('confidence')) return 'diagnosis';
  if (nodeLower.includes('persist') || nodeLower.includes('prescription') || nodeLower.includes('personalization') || nodeLower.includes('treatment')) return 'treatment';
  if (aid.includes('verification') || aid.includes('validator') || aid.includes('review') || aid.includes('compliance')) return 'verification';
  if (nodeLower.includes('parse') || nodeLower.includes('input') || nodeLower.includes('reception')) return 'reception';
  return 'supervisor';
};

const normalizeEvent = (raw: RawTraceEvent): NormalizedEvent => {
  const ts = raw.ts;
  const tsMs = parseTsMs(ts);

  if (raw.agent) {
    const agentId = mapToFixedAgent(String(raw.agent_id || raw.agent), undefined);
    const outputs = isRecord(raw.outputs) ? raw.outputs : undefined;
    const decision = isRecord(raw.decision) ? raw.decision : undefined;
    const isComplete = String(raw.step || '').toLowerCase().endsWith('_complete') || outputs?.['is_complete'] === true;
    const status = isComplete ? 'completed' : 'running';

    const reasons = toArray(decision?.['reasons_cn'] ?? decision?.['reasons']).map((item) => String(item));
    const reasonText = shortText(decision?.['reason_str'] ?? reasons.join('、'), 120);
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
        inputs: isRecord(raw.inputs) ? raw.inputs : undefined,
        outputs,
        decision,
      },
    };
  }

  const payload = isRecord(raw.payload) ? raw.payload : {};
  const status = normalizeStatus(raw.status);
  return {
    seq: raw.seq,
    ts,
    tsMs,
    agentId: mapToFixedAgent(String(payload['agent_id'] || raw.agent_id || ''), raw.node),
    nodeName: String(raw.node || raw.agent || 'trace'),
    status,
    message: shortText(raw.message || payload['message'] || raw.node || 'trace', 140),
    data: payload,
  };
};


const toStringArray = (value: unknown): string[] => toArray(value).map((item) => String(item)).filter(Boolean);

const toPercent = (value: unknown): string => {
  const n = Number(value);
  if (!Number.isFinite(n)) return '-';
  const pct = n <= 1 ? n * 100 : n;
  return `${pct.toFixed(2)}%`;
};

const sortNormalizedEvents = (events: NormalizedEvent[]): NormalizedEvent[] => {
  return [...events].sort((a, b) => {
    const sa = typeof a.seq === 'number' ? a.seq : Number.MAX_SAFE_INTEGER;
    const sb = typeof b.seq === 'number' ? b.seq : Number.MAX_SAFE_INTEGER;
    if (sa !== sb) return sa - sb;
    return (a.tsMs ?? Number.MAX_SAFE_INTEGER) - (b.tsMs ?? Number.MAX_SAFE_INTEGER);
  });
};

const dedupBySeq = (events: NormalizedEvent[]): NormalizedEvent[] => {
  const sorted = sortNormalizedEvents(events);
  const seen = new Set<number>();
  const result: NormalizedEvent[] = [];
  sorted.forEach((event) => {
    if (typeof event.seq === 'number' && Number.isFinite(event.seq)) {
      if (seen.has(event.seq)) return;
      seen.add(event.seq);
    }
    result.push(event);
  });
  return result;
};

const getEventsByAgent = (events: NormalizedEvent[], agentId: FixedAgentId): NormalizedEvent[] => {
  const target = agentId.toLowerCase();
  return dedupBySeq(events).filter((event) => {
    const data = isRecord(event.data) ? event.data : {};
    const rawAgent = String(data['agent_id'] ?? data['agent'] ?? '').toLowerCase();
    return event.agentId === agentId || rawAgent === target;
  });
};

const getSystemNodeEvents = (events: NormalizedEvent[], nodeName: string): NormalizedEvent[] => {
  const target = nodeName.toLowerCase();
  return dedupBySeq(events).filter((event) => String(event.nodeName || '').toLowerCase() === target);
};

const getOutputs = (event: NormalizedEvent): Record<string, unknown> => {
  const data = isRecord(event.data) ? event.data : {};
  if (isRecord(data['outputs'])) return data['outputs'];
  if (isRecord(data['payload']) && isRecord((data['payload'] as Record<string, unknown>)['outputs'])) {
    return (data['payload'] as Record<string, unknown>)['outputs'] as Record<string, unknown>;
  }
  return data;
};

const TREATMENT_OUTPUT_KEYS = [
  'selected_branch',
  'llm_failed',
  'personalization_applied',
  'filtered',
  'filtered_reasons',
  'filtered_components',
  'personalization_reasons',
] as const;

const hasTreatmentOutputFields = (outputs: Record<string, unknown>): boolean => {
  return TREATMENT_OUTPUT_KEYS.some((key) => outputs[key] !== undefined && outputs[key] !== null);
};

const getPreferredTreatmentOutputs = (allEvents: NormalizedEvent[], fallbackOutputs: Record<string, unknown>): Record<string, unknown> => {
  const deduped = dedupBySeq(allEvents);

  const treatmentAgentEvents = deduped.filter((event) => {
    const data = isRecord(event.data) ? event.data : {};
    return String(data['agent'] ?? data['agent_id'] ?? '').toLowerCase() === 'treatment';
  });
  const treatmentFromAgent = [...treatmentAgentEvents].reverse().find((event) => hasTreatmentOutputFields(getOutputs(event)));
  if (treatmentFromAgent) return getOutputs(treatmentFromAgent);

  const personalizationEvent = [...deduped].reverse().find((event) => {
    const node = String(event.nodeName || '').toLowerCase();
    return node === 'personalizationagent' || node === 'personalization';
  });
  if (personalizationEvent) {
    const outputs = getOutputs(personalizationEvent);
    if (hasTreatmentOutputFields(outputs)) return outputs;
  }

  return fallbackOutputs;
};

const extractHighlights = (agentId: FixedAgentId, allEvents: NormalizedEvent[]): string[] => {
  const events = getEventsByAgent(allEvents, agentId);
  if (!events.length) return [];
  const latest = events[events.length - 1];
  const outputs = getOutputs(latest);

  if (agentId === 'supervisor') {
    const decision = isRecord((isRecord(latest.data) ? latest.data['decision'] : undefined)) ? (latest.data as Record<string, unknown>)['decision'] as Record<string, unknown> : undefined;
    const nextAction = String(decision?.['next_action'] ?? outputs['next_action'] ?? '').trim();
    const reasons = toStringArray(decision?.['reasons_cn'] ?? decision?.['reasons']);
    const reasonText = String(decision?.['reason_str'] ?? '').trim();
    const reason = reasons.length ? reasons.join(',') : reasonText;
    if (nextAction) return [`决策：下一步 = ${nextAction}${reason ? `（原因：${reason}）` : ''}`];
    return [reasonText ? `流程结束（${reasonText}）` : '流程结束'];
  }

  if (agentId === 'reception') {
    const cropType = String(outputs['crop_type'] ?? '-');
    const imagePath = String(outputs['image_path'] ?? '').trim();
    const symptoms = toArray(outputs['symptoms']).length;
    const missing = toStringArray(outputs['missing_profile_fields']);
    return [`结构化抽取：作物=${cropType} / 图像=${imagePath ? '已识别' : '未识别'} / 症状=${symptoms}项 / 缺失字段=${missing.length ? `${missing.join(',')}（${missing.length}项）` : '0项'}`];
  }

  if (agentId === 'diagnosis') {
    const disease = String(outputs['disease_type'] ?? outputs['final_disease'] ?? '-');
    const confidence = toPercent(outputs['final_confidence'] ?? outputs['disease_confidence'] ?? outputs['confidence_pct'] ?? outputs['confidence']);
    const source = String(outputs['final_source'] ?? '-');
    const needConfirm = outputs['need_confirm'] === true ? '是' : '否';
    return [`诊断：${disease} / 置信度=${confidence} / 来源=${source} / need_confirm=${needConfirm}`];
  }

  if (agentId === 'kb_retrieval') {
    const disease = String(outputs['disease'] ?? outputs['final_disease'] ?? '-');
    const hasActions = isRecord(outputs['actions']);
    const ingredients = toStringArray(outputs['ingredients']).length;
    return [`检索：命中 KB=${disease}（actions=${hasActions ? '是' : '否'} / ingredients=${ingredients}）`];
  }

  if (agentId === 'treatment') {
    const treatmentOutputs = getPreferredTreatmentOutputs(allEvents, outputs);
    const selectedBranch = String(treatmentOutputs['selected_branch'] ?? '-').trim() || '-';
    const llmFailed = treatmentOutputs['llm_failed'] === true;
    const personalizationApplied = treatmentOutputs['personalization_applied'] === true;
    const filtered = treatmentOutputs['filtered'] === true;
    const filteredReasons = toStringArray(treatmentOutputs['filtered_reasons']);
    const filteredComponents = toStringArray(treatmentOutputs['filtered_components']);
    const reasons = toStringArray(treatmentOutputs['personalization_reasons']);

    const filterLine = (() => {
      if (!filtered) return '未触发过滤';
      if (!filteredReasons.length) return '触发过滤';
      return `触发过滤：${filteredReasons.join('；')}${filteredComponents.length ? `（过滤成分：${filteredComponents.join('、')}）` : ''}`;
    })();

    return [
      `档位=${selectedBranch}；LLM=${llmFailed ? '失败' : '成功'}；输出来源=${llmFailed ? 'KB后备' : 'LLM'}`,
      personalizationApplied ? '已应用个性化' : '未应用个性化',
      filterLine,
      `原因概览：${reasons.length ? reasons.slice(0, 3).join('；') : '无'}`,
    ];
  }

  if (agentId === 'verification') {
    const verificationRaw = isRecord(outputs['verification_result']) ? outputs['verification_result'] : outputs;
    const passed = verificationRaw['passed'] ?? outputs['verification_passed'];
    const riskLevel = String(verificationRaw['risk_level'] ?? outputs['verification_risk_level'] ?? '-');
    const issues = toStringArray(verificationRaw['issues'] ?? outputs['verification_issues']);
    const mustFix = toStringArray(verificationRaw['must_fix'] ?? outputs['verification_must_fix']);
    const summary = String(verificationRaw['compliance_summary'] ?? outputs['verification_summary'] ?? '').trim();

    const lines = [
      `审查结果：${passed === true ? '通过' : passed === false ? '未通过' : '待确认'}`,
      `风险等级：${riskLevel || '-'}`,
    ];
    if (issues.length) lines.push(`主要问题：${issues.slice(0, 2).join('；')}`);
    if (mustFix.length) lines.push(`必须修改：${mustFix.slice(0, 2).join('；')}`);
    if (!issues.length && !mustFix.length && summary) lines.push(`摘要：${shortText(summary, 120)}`);
    if (lines.length <= 2) lines.push(shortText(latest.message, 120) || '正在检查禁用成分与安全间隔...');
    return lines.slice(0, 4);
  }

  if (agentId === 'final') return ['流程完成'];
  return [shortText(latest.message, 100) || '等待事件'];
};

const extractSubsteps = (agentId: FixedAgentId, allEvents: NormalizedEvent[]): Array<{ seq?: number; node: string; message: string }> => {
  const events = getEventsByAgent(allEvents, agentId);
  if (!events.length) return [];
  const map = new Map<string, { seq?: number; node: string; message: string }>();
  const push = (key: string, item: { seq?: number; node: string; message: string }) => {
    if (!map.has(key)) map.set(key, item);
  };

  events.forEach((event) => {
    const data = isRecord(event.data) ? event.data : {};
    const inputs = isRecord(data['inputs']) ? data['inputs'] : {};
    const outputs = getOutputs(event);
    const decision = isRecord(data['decision']) ? data['decision'] : {};

    if (agentId === 'supervisor') {
      const currentStep = String(inputs['current_step'] ?? '-');
      const nextAction = String(decision['next_action'] ?? outputs['next_action'] ?? '-');
      const reasons = toStringArray(decision['reasons_cn'] ?? decision['reasons']);
      const key = `${currentStep}|${nextAction}|${reasons.join(',')}`;
      push(key, { seq: event.seq, node: 'route', message: `${currentStep} → ${nextAction}${reasons.length ? `（${reasons.join(',')}）` : ''}` });
      return;
    }

    if (agentId === 'reception') {
      push('parse', { seq: event.seq, node: 'parse_input', message: '解析输入（file/symptoms/crop_type）' });
      if (outputs['crop_type']) push('normalize', { seq: event.seq, node: 'normalize', message: `规范化字段：crop_type=${String(outputs['crop_type'])}` });
      push('extract_image', { seq: event.seq, node: 'extract_image', message: `提取 image_path：${outputs['image_path'] ? '已生成' : '未生成'}` });
      const missing = toStringArray(outputs['missing_profile_fields']);
      push('missing_fields', { seq: event.seq, node: 'missing_fields', message: `检测缺失字段：${missing.length ? missing.join(',') : '无'}` });
      const followUps = toArray(outputs['follow_up_questions']).length;
      if (followUps) push('followup_map', { seq: event.seq, node: 'followup_map', message: `缺失字段映射为追问：follow_up_questions=${followUps}条` });
      return;
    }

    if (agentId === 'diagnosis') {
      const top1 = String(outputs['top1_disease'] ?? outputs['disease_type'] ?? outputs['final_disease'] ?? '-');
      const top3 = toStringArray(outputs['top3_diseases'] ?? outputs['top3']).join(',') || '-';
      push('infer', { seq: event.seq, node: 'infer', message: `模型推理完成：top1=${top1}，top3=${top3}` });
      const conf = toPercent(outputs['final_confidence'] ?? outputs['disease_confidence'] ?? outputs['confidence_pct'] ?? outputs['confidence']);
      const gateReason = String(outputs['gate_reason'] ?? outputs['need_confirm_reason'] ?? '').trim();
      push('gate', { seq: event.seq, node: 'gate', message: outputs['need_confirm'] === true ? `低置信度（${gateReason || conf}）` : `置信度门控：通过（${conf}）` });
      push('confirm', { seq: event.seq, node: 'confirm', message: `need_confirm：${outputs['need_confirm'] === true ? '是（生成二次确认候选）' : '否'}` });
      const hintFailed = outputs['personalized_hint_failed'] === true;
      push('personalized_hint', { seq: event.seq, node: 'personalized_hint', message: `个性化诊断提示：${hintFailed ? '失败（已降级）' : '成功'}` });
      return;
    }

    if (agentId === 'kb_retrieval') {
      push('load_desc', { seq: event.seq, node: 'load_desc', message: '读取 diseases.json：获取描述' });
      push('load_plan', { seq: event.seq, node: 'load_plan', message: '读取 treatments.json：获取 treatment/prevention' });
      push('load_actions', { seq: event.seq, node: 'load_actions', message: '读取 actions：immediate + 三档处置（FAMILY/MID/ENTERPRISE）+ follow_up' });
      push('load_ingredients', { seq: event.seq, node: 'load_ingredients', message: `读取 ingredients：${toStringArray(outputs['ingredients']).length}项` });
      push('pack_snapshot', { seq: event.seq, node: 'pack_snapshot', message: '打包 kb_snapshot：供治疗智能体使用' });
      return;
    }

    if (agentId === 'treatment') {
      const personalizationOutputs = getOutputs(getSystemNodeEvents(allEvents, 'personalization').slice(-1)[0] ?? event);
      const merged = { ...personalizationOutputs, ...outputs };
      const flags = isRecord(merged['personalization_flags_summary']) ? merged['personalization_flags_summary'] : {};
      const selectedBranch = String(merged['selected_branch'] ?? '-');
      push('branch_select', { seq: event.seq, node: 'branch_select', message: `档位判定：${String(flags['farm_scale'] ?? '-')} + ${String(flags['pesticide_access'] ?? '-')} + ${String(flags['equipment'] ?? '-')} → ${selectedBranch}` });
      const actions = isRecord(merged['actions']) ? merged['actions'] : {};
      push('kb_fuse', { seq: event.seq, node: 'kb_fuse', message: `融合 KB actions：立即行动${toArray(actions['immediate_actions']).length}条 / 差异化处置${toArray(actions['treatment_plan']).length || 3}条 / 抗性管理${toArray(actions['resistance_management']).length}条` });
      const llmFailed = merged['llm_failed'] === true;
      const llmReason = String(merged['llm_failed_reason'] ?? '').trim();
      push('llm_call', { seq: event.seq, node: 'llm_call', message: `LLM 调用：${llmFailed ? `失败（${llmReason || 'JSON解析为空'}）` : '成功'}` });
      if (llmFailed) push('fallback', { seq: event.seq, node: 'fallback', message: '回退策略：使用 KB 后备组装' });
      push('apply_constraints', { seq: event.seq, node: 'apply_constraints', message: `强约束后处理：有机/禁用成分/采收窗口 → filtered=${merged['filtered'] === true ? 'true' : 'false'}` });
      return;
    }

    if (agentId === 'verification') {
      const verificationRaw = isRecord(outputs['verification_result']) ? outputs['verification_result'] : outputs;
      const passed = verificationRaw['passed'] ?? outputs['verification_passed'];
      const riskLevel = String(verificationRaw['risk_level'] ?? outputs['verification_risk_level'] ?? '-');
      const issues = toStringArray(verificationRaw['issues'] ?? outputs['verification_issues']);
      const mustFix = toStringArray(verificationRaw['must_fix'] ?? outputs['verification_must_fix']);
      const summary = String(verificationRaw['compliance_summary'] ?? outputs['verification_summary'] ?? '').trim();
      const decisionAction = String(decision['next_action'] ?? '').trim();

      push('load_constraints', { seq: event.seq, node: 'load_constraints', message: '加载农户档案约束与禁用成分清单' });
      push('review_treatment', { seq: event.seq, node: 'review_treatment', message: '审查 treatment_plan / prevention_advice 的安全与可执行性' });
      push('compliance_check', { seq: event.seq, node: 'compliance_check', message: `审查结果：${passed === true ? '通过' : passed === false ? '未通过' : '待确认'} / 风险等级=${riskLevel}` });
      if (issues.length) push('issues', { seq: event.seq, node: 'issues', message: `主要问题：${issues.slice(0, 2).join('；')}` });
      if (mustFix.length) push('must_fix', { seq: event.seq, node: 'must_fix', message: `必须修改：${mustFix.slice(0, 2).join('；')}` });
      if (summary) push('summary', { seq: event.seq, node: 'summary', message: shortText(summary, 120) });
      if (decisionAction) push('rewrite_decision', { seq: event.seq, node: 'rewrite_decision', message: decisionAction === 'treatment' ? '审查未通过，回写 treatment 重写' : '审查通过，进入流程收敛' });
      return;
    }

    if (agentId === 'final') push('final', { seq: event.seq, node: event.nodeName, message: shortText(event.message, 100) || '流程结束' });
  });

  return Array.from(map.values()).slice(-5);
};

export function AgentWorkflowPanel({ traceId, confidencePct, phaseStartMs, refreshToken }: AgentWorkflowPanelProps) {
  const [rows, setRows] = useState<Record<FixedAgentId, AgentRowState>>(buildInitialState());
  const [connectionState, setConnectionState] = useState<'idle' | 'connecting' | 'connected' | 'disconnected'>('idle');
  const [connectionHint, setConnectionHint] = useState('');
  const [replayedCount, setReplayedCount] = useState(0);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [workflowDone, setWorkflowDone] = useState(false);
  const [pausedByUserInput, setPausedByUserInput] = useState(false);
  const [tracePausedStable, setTracePausedStable] = useState(false);
  const [diagnosisConfidencePct, setDiagnosisConfidencePct] = useState<number | undefined>(undefined);
  const [allEvents, setAllEvents] = useState<NormalizedEvent[]>([]);
  const [showSystemNodes, setShowSystemNodes] = useState(false);
  const [debugOpen, setDebugOpen] = useState<Record<FixedAgentId, boolean>>({
    supervisor: false,
    reception: false,
    diagnosis: false,
    kb_retrieval: false,
    treatment: false,
    verification: false,
    final: false,
  });

  const esRef = useRef<EventSource | null>(null);
  const tickerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const activeTraceFetchAbortRef = useRef<AbortController | null>(null);
  const activeReplayTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSeqRef = useRef(-1);
  const workflowDoneRef = useRef(false);
  const updatesStoppedRef = useRef(false);
  const waitingStableRef = useRef(false);
  const replayedCountRef = useRef(0);
  const finalTsRef = useRef<number | undefined>(undefined);
  const eventHistoryRef = useRef<Record<FixedAgentId, NormalizedEvent[]>>({
    supervisor: [],
    reception: [],
    diagnosis: [],
    kb_retrieval: [],
    treatment: [],
    verification: [],
    final: [],
  });
  const allEventsRef = useRef<NormalizedEvent[]>([]);

  const clearTicker = useCallback(() => {
    if (tickerRef.current) {
      clearInterval(tickerRef.current);
      tickerRef.current = null;
    }
  }, []);

  const closeStream = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  const clearReplayTimer = useCallback(() => {
    if (activeReplayTimerRef.current) {
      clearTimeout(activeReplayTimerRef.current);
      activeReplayTimerRef.current = null;
    }
  }, []);

  const abortActiveTraceFetch = useCallback(() => {
    if (activeTraceFetchAbortRef.current) {
      activeTraceFetchAbortRef.current.abort();
      activeTraceFetchAbortRef.current = null;
    }
  }, []);

  const clearExternal = useCallback(() => {
    closeStream();
    clearTicker();
    clearReplayTimer();
    abortActiveTraceFetch();
  }, [abortActiveTraceFetch, closeStream, clearReplayTimer, clearTicker]);

  const stopPolling = useCallback((markWaitingStable = false) => {
    updatesStoppedRef.current = true;
    if (markWaitingStable) {
      waitingStableRef.current = true;
    }
    closeStream();
    clearTicker();
    clearReplayTimer();
    abortActiveTraceFetch();
  }, [abortActiveTraceFetch, closeStream, clearReplayTimer, clearTicker]);

  useEffect(() => {
    console.debug('[AgentWorkflowPanel]', {
      waitingStableRef: waitingStableRef.current,
      updatesStoppedRef: updatesStoppedRef.current,
      connectionState,
      connectionHint,
      traceId: traceId ?? null,
    });
  }, [connectionState, connectionHint, traceId, tracePausedStable, pausedByUserInput, workflowDone]);

  const maybeStartTicker = useCallback((snapshot: Record<FixedAgentId, AgentRowState>, done: boolean, paused: boolean) => {
    const hasRunning = FIXED_AGENTS.some((agent) => snapshot[agent.id].status === 'running');
    const hasPhaseTimer = typeof phaseStartMs === 'number' && Number.isFinite(phaseStartMs);
    if (!done && !paused && (hasRunning || hasPhaseTimer)) {
      if (!tickerRef.current) {
        tickerRef.current = setInterval(() => setNowMs(Date.now()), 100);
      }
    } else {
      clearTicker();
    }
  }, [phaseStartMs, clearTicker]);

  const completeSupervisorOnDone = useCallback((doneTs?: number) => {
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
  }, []);

  const applyNormalizedEvent = useCallback((event: NormalizedEvent, options?: { preserveReplayFlow?: boolean }): boolean => {
    if (workflowDoneRef.current || updatesStoppedRef.current) return false;

    const seq = event.seq;
    if (typeof seq === 'number' && Number.isFinite(seq) && seq <= lastSeqRef.current) {
      return false;
    }
    if (typeof seq === 'number' && Number.isFinite(seq)) {
      lastSeqRef.current = seq;
    }

    const waitingForUserInput = isWaitingForUserInputEvent(event);
    if (waitingForUserInput && !options?.preserveReplayFlow) {
      waitingStableRef.current = true;
      updatesStoppedRef.current = true;
      allEventsRef.current = dedupBySeq([...allEventsRef.current, event]);
      setAllEvents(allEventsRef.current);
      setPausedByUserInput(true);
      setTracePausedStable(true);
      setConnectionState('disconnected');
      setConnectionHint(`已回放 ${replayedCountRef.current} 条事件，等待用户补充`);
      clearTicker();
      closeStream();
      stopPolling(true);
    } else if (waitingForUserInput) {
      allEventsRef.current = dedupBySeq([...allEventsRef.current, event]);
      setAllEvents(allEventsRef.current);
    } else if (event.status === 'running') {
      setPausedByUserInput(false);
      setTracePausedStable(false);
    }

    if (event.status === 'info') return false;

    const agentId = event.agentId;
    eventHistoryRef.current[agentId] = dedupBySeq([...eventHistoryRef.current[agentId], event]).slice(-20);
    allEventsRef.current = dedupBySeq([...allEventsRef.current, event]);
    setAllEvents(allEventsRef.current);

    if (agentId === 'diagnosis') {
      const data = isRecord(event.data) ? event.data : undefined;
      const outputs = isRecord(data?.['outputs']) ? data['outputs'] : undefined;
      const rawConfidence = Number(
        (isRecord(data) ? data['confidence_pct'] : undefined)
        ?? (isRecord(data) ? data['confidence'] : undefined)
        ?? (isRecord(outputs) ? outputs['confidence_pct'] : undefined)
        ?? (isRecord(outputs) ? outputs['confidence'] : undefined),
      );
      if (Number.isFinite(rawConfidence)) {
        setDiagnosisConfidencePct(rawConfidence <= 1 ? rawConfidence * 100 : rawConfidence);
      }
    }

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

      current.steps = extractSubsteps(agentId, allEventsRef.current).slice(-5);
      current.lastMessage = message;
      current.highlights = extractHighlights(agentId, allEventsRef.current);

      if (event.status === 'running') {
        current.status = 'running';
        if (typeof event.tsMs === 'number') {
          current.startTs = current.startTs ?? event.tsMs;
        }
        const data = isRecord(event.data) ? event.data : undefined;
        const outputs = isRecord(data?.['outputs']) ? data['outputs'] : undefined;
        const explicit = Number(
          (isRecord(data) ? data['progress'] : undefined)
          ?? (isRecord(outputs) ? outputs['progress'] : undefined),
        );
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
        }
        current.progress = 100;
      }

      next[agentId] = current;

      const finalDone = agentId === 'final' && event.status === 'completed';
      if (finalDone) {
        markDone = true;
        if (typeof event.tsMs === 'number') {
          finalTsRef.current = event.tsMs;
        }
      }

      maybeStartTicker(next, markDone || workflowDoneRef.current, waitingForUserInput);
      return next;
    });

    if (markDone) {
      workflowDoneRef.current = true;
      setWorkflowDone(true);
      stopPolling(false);
      completeSupervisorOnDone(finalTsRef.current);
    }

    return true;

  }, [maybeStartTicker, stopPolling, closeStream, clearTicker, completeSupervisorOnDone]);


  useEffect(() => {
    if (!traceId) {
      clearExternal();
      replayedCountRef.current = 0;
      workflowDoneRef.current = false;
      setPausedByUserInput(false);
      lastSeqRef.current = -1;
      finalTsRef.current = undefined;
      eventHistoryRef.current = {
        supervisor: [],
        reception: [],
        diagnosis: [],
        kb_retrieval: [],
        treatment: [],
        verification: [],
        final: [],
      };
      allEventsRef.current = [];
      queueMicrotask(() => setAllEvents([]));
      return;
    }

    let cancelled = false;

    clearExternal();
    queueMicrotask(() => {
      if (cancelled) return;
      setConnectionState('connecting');
      setConnectionHint('正在回放历史事件...');
      setReplayedCount(0);
      setWorkflowDone(false);
      setPausedByUserInput(false);
      setTracePausedStable(false);
    });
    replayedCountRef.current = 0;
    workflowDoneRef.current = false;
    updatesStoppedRef.current = false;
    waitingStableRef.current = false;
    lastSeqRef.current = -1;
    finalTsRef.current = undefined;
    eventHistoryRef.current = {
      supervisor: [],
      reception: [],
      diagnosis: [],
      kb_retrieval: [],
      treatment: [],
      verification: [],
      final: [],
    };
    allEventsRef.current = [];
    queueMicrotask(() => setAllEvents([]));

    const openStream = () => {
      if (cancelled || workflowDoneRef.current || updatesStoppedRef.current || waitingStableRef.current) return;

      const es = new EventSource(`/api/traces/${encodeURIComponent(traceId)}/stream`);
      esRef.current = es;

      es.addEventListener('trace', (messageEvent) => {
        if (cancelled || workflowDoneRef.current || updatesStoppedRef.current) return;
        const raw = JSON.parse(messageEvent.data || '{}') as RawTraceEvent;
        if (!shouldIncludeEvent(raw, phaseStartMs)) return;
        const normalized = normalizeEvent(raw);
        const seq = normalized.seq;
        if (typeof seq === 'number' && Number.isFinite(seq) && seq <= lastSeqRef.current) {
          return;
        }
        applyNormalizedEvent(normalized);
        if (waitingStableRef.current || updatesStoppedRef.current) {
          setConnectionState('disconnected');
          setConnectionHint(`已回放 ${replayedCountRef.current} 条事件，等待用户补充`);
          return;
        }
        setConnectionState('connected');
        setConnectionHint(`已回放 ${replayedCountRef.current} 条事件 + 实时连接中`);
      });

      es.onerror = () => {
        if (cancelled || workflowDoneRef.current || waitingStableRef.current || updatesStoppedRef.current) return;
        setConnectionState('disconnected');
        setConnectionHint(`实时连接断开（已回放 ${replayedCountRef.current} 条）`);
        closeStream();
      };
    };

    const replayThenConnect = async () => {
      if (cancelled || workflowDoneRef.current || updatesStoppedRef.current || waitingStableRef.current) return;

      abortActiveTraceFetch();
      const controller = new AbortController();
      activeTraceFetchAbortRef.current = controller;

      try {
        const response = await fetchTraceEvents(traceId, {
          source: 'AgentWorkflowPanel.replay',
          signal: controller.signal,
          debugState: {
            updatesStopped: updatesStoppedRef.current,
            waitingStable: waitingStableRef.current,
            workflowDone: workflowDoneRef.current,
            hasInFlight: activeTraceFetchAbortRef.current !== null,
          },
        });
        if (activeTraceFetchAbortRef.current === controller) {
          activeTraceFetchAbortRef.current = null;
        }
        if (!response.ok) {
          if (cancelled || workflowDoneRef.current || updatesStoppedRef.current || waitingStableRef.current) return;
          setConnectionHint('历史回放失败，尝试直接连接实时流...');
          openStream();
          return;
        }
        const payload = await response.json();
        const events = Array.isArray(payload?.events) ? payload.events : [];
        const sorted = sliceCurrentPhaseEvents(events as RawTraceEvent[], phaseStartMs);

        if (cancelled || workflowDoneRef.current || updatesStoppedRef.current || waitingStableRef.current) return;

        let replayed = 0;
        let replayPausedByUserInput = false;
        sorted.forEach((raw: RawTraceEvent, index: number) => {
          if (cancelled || workflowDoneRef.current || updatesStoppedRef.current || waitingStableRef.current) return;
          const normalized = normalizeEvent(raw as RawTraceEvent);
          const terminalWaitingEvent = isReplayTerminalWaitingEvent(sorted as RawTraceEvent[], index);
          if (terminalWaitingEvent) {
            replayPausedByUserInput = true;
          }
          if (normalized.status === 'running') {
            replayPausedByUserInput = false;
          }
          if (applyNormalizedEvent(normalized, { preserveReplayFlow: !terminalWaitingEvent })) replayed += 1;
        });
        setPausedByUserInput(replayPausedByUserInput);

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

        if (waitingStableRef.current || replayPausedByUserInput || updatesStoppedRef.current) {
          setConnectionState('disconnected');
          setConnectionHint(`已回放 ${replayed} 条事件，等待用户补充`);
          return;
        }

        setConnectionHint(`已回放 ${replayed} 条事件，正在连接实时流...`);
        openStream();
      } catch (error) {
        if (activeTraceFetchAbortRef.current === controller) {
          activeTraceFetchAbortRef.current = null;
        }
        if (cancelled) return;
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setConnectionState('disconnected');
        setConnectionHint('历史回放异常，实时连接未建立');
      }
    };

    replayThenConnect();

    return () => {
      cancelled = true;
      clearExternal();
    };
  }, [traceId, phaseStartMs, refreshToken, abortActiveTraceFetch, applyNormalizedEvent, clearExternal, closeStream, stopPolling]);

  useEffect(() => {
    if (workflowDone) {
      clearTicker();
      closeStream();
      completeSupervisorOnDone(finalTsRef.current);
    }
  }, [workflowDone, clearTicker, closeStream, completeSupervisorOnDone]);

  useEffect(() => {
    if (workflowDone || pausedByUserInput || tracePausedStable) return;
    if (typeof phaseStartMs === 'number' && Number.isFinite(phaseStartMs) && !tickerRef.current) {
      tickerRef.current = setInterval(() => setNowMs(Date.now()), 100);
    }
  }, [phaseStartMs, workflowDone, pausedByUserInput, tracePausedStable]);


  const phaseDurationsByAgent = useMemo(
    () => calcPhaseDurationsByAgent(allEvents, nowMs, workflowDone) as Record<FixedAgentId, AgentPhaseDurations>,
    [allEvents, nowMs, workflowDone],
  );

  const activePhaseLabel = useMemo(() => {
    const hasSecondPhase = allEvents.some((event) => {
      const node = String(event.nodeName || '').toLowerCase();
      const data = isRecord(event.data) ? event.data : {};
      const rawAgent = String(data['agent'] ?? data['agent_id'] ?? '').toLowerCase();
      return rawAgent === 'confirm_input' || node === 'confirm_input' || (node === 'confirmflow' && event.status === 'running');
    });
    return hasSecondPhase ? '当前显示二诊阶段链路' : '当前显示一诊阶段链路';
  }, [allEvents]);

  const receptionDebugSummary = useMemo(() => {
    const receptionEvents = getEventsByAgent(allEvents, 'reception');
    const lastReceptionEvent = receptionEvents[receptionEvents.length - 1];
    return {
      count: receptionEvents.length,
      lastSeq: lastReceptionEvent?.seq,
    };
  }, [allEvents]);

  const renderedRows = useMemo(() => {
    return FIXED_AGENTS.map((def) => {
      const row = rows[def.id];
      const elapsedMs = row.startTs ? Math.max(0, (row.endTs ?? nowMs) - row.startTs) : 0;
      const progress = row.status === 'running' && !workflowDone
        ? Math.max(row.progress, softProgress(elapsedMs))
        : row.progress;
      return {
        ...def,
        ...row,
        progress,
        duration: formatDurationMs((phaseDurationsByAgent[def.id]?.phase1Ms ?? 0) + (phaseDurationsByAgent[def.id]?.phase2Ms ?? 0)),
        phase1Duration: formatDurationMs(phaseDurationsByAgent[def.id]?.phase1Ms ?? 0),
        phase2Duration: formatDurationMs(phaseDurationsByAgent[def.id]?.phase2Ms ?? 0),
      };
    });
  }, [rows, nowMs, workflowDone, phaseDurationsByAgent]);

  const completedCount = useMemo(() => renderedRows.filter((row) => row.status === 'completed').length, [renderedRows]);

  const totalProgress = Math.round((completedCount / FIXED_AGENTS.length) * 100);

  const overallDuration = useMemo(
    () => calcOverallPhaseDuration(phaseDurationsByAgent),
    [phaseDurationsByAgent],
  );

  const displayConfidencePct =
    (typeof confidencePct === 'number' && Number.isFinite(confidencePct)) ? confidencePct : diagnosisConfidencePct;

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
        {replayedCount > 0 && <span className="text-xs text-[#c8f7c5]/70">已回放 {replayedCount} 条</span>}
        {typeof displayConfidencePct === 'number' && (
          <Badge className="bg-[#c8f7c5]/20 text-[#c8f7c5] border border-[#c8f7c5]/30">
            诊断置信度 {displayConfidencePct.toFixed(2)}%
          </Badge>
        )}
        {workflowDone && (
          <Badge className="bg-green-500/20 text-green-300 border border-green-400/40">
            <BadgeCheck className="w-3 h-3 mr-1" />流程已结束
          </Badge>
        )}
        {pausedByUserInput && (
          <Badge className="bg-amber-500/20 text-amber-200 border border-amber-400/40">
            <Timer className="w-3 h-3 mr-1" />等待用户补充，计时已暂停
          </Badge>
        )}
        <Badge variant="outline" className="border-white/15 text-white/60">
          {activePhaseLabel}
        </Badge>
        <button
          type="button"
          onClick={() => setShowSystemNodes((v) => !v)}
          className={cn(
            "text-xs px-2 py-1 rounded border",
            showSystemNodes
              ? "border-[#c8f7c5]/60 text-[#c8f7c5] bg-[#c8f7c5]/10"
              : "border-white/20 text-white/60 hover:text-white/80"
          )}
        >
          显示系统节点（校验/落盘）
        </button>
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
                        <span className="text-white/35">（一诊 {row.phase1Duration} / 二诊 {row.phase2Duration}）</span>
                      </div>
                    </div>

                    <p className={cn('text-sm mt-2 text-white/70', running && 'animate-pulse')}>
                      {row.lastMessage || row.description}
                    </p>

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
                      最近子步骤（最近5条）
                    </button>

                    {debugOpen[row.id] && (
                      <div className="mt-1 space-y-1">
                        {row.id === 'reception' && (
                          <div className="text-xs text-[#c8f7c5]/75">
                            reception 原始事件：{receptionDebugSummary.count} 条 / 最后一条 seq：{receptionDebugSummary.lastSeq ?? '—'}
                          </div>
                        )}
                        {(showSystemNodes ? row.steps : row.steps.filter((step) => {
                          const node = String(step.node || '').toLowerCase();
                          const msg = String(step.message || '').toLowerCase();
                          if (row.id === 'verification') {
                            return !(node.includes('persist') || msg.includes('落盘'));
                          }
                          return !(node.includes('persist') || msg.includes('落盘'));
                        })).length ? (showSystemNodes ? row.steps : row.steps.filter((step) => {
                          const node = String(step.node || '').toLowerCase();
                          const msg = String(step.message || '').toLowerCase();
                          if (row.id === 'verification') {
                            return !(node.includes('persist') || msg.includes('落盘'));
                          }
                          return !(node.includes('persist') || msg.includes('落盘'));
                        })).map((step, index) => (
                          <div key={`${step.seq ?? 'na'}-${index}`} className="text-xs text-white/50">
                            <span className="text-white/70">{step.node}</span>
                            <span className="mx-1">·</span>
                            <span>{step.message}</span>
                          </div>
                        )) : <div className="text-xs text-white/40">暂无子步骤</div>}
                      </div>
                    )}

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
          <span className="text-[#c8f7c5] font-mono">{completedCount}/{FIXED_AGENTS.length}</span>
        </div>
        <div className="h-2 rounded-full bg-white/10 overflow-hidden">
          <div className="h-full bg-[#4ade80] transition-all duration-500 progress-shine" style={{ width: `${totalProgress}%` }} />
        </div>
        <p className="text-xs text-white/50 mt-2">
          总耗时：{formatDurationMs(overallDuration.totalMs)}（一诊 {formatDurationMs(overallDuration.phase1Ms)} + 二诊 {formatDurationMs(overallDuration.phase2Ms)}） {workflowDone ? '· 已结束' : ''}
        </p>
      </div>
    </div>
  );
}
