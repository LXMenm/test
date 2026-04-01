import { useEffect, useMemo, useState } from 'react';
import { Loader2, RefreshCcw, Save, ClipboardCheck, User, Clock, CheckCircle2, ChevronDown, ChevronUp } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { loadAuthUser, withAuthHeaders } from '@/auth';

interface AdminConfig {
  workflow: {
    confirm_round_limit: number;
    validator_rewrite_limit: number;
    enable_validator_agent: boolean;
    enable_personalization_agent: boolean;
  };
  model_fusion: {
    enable_image_model: boolean;
    enable_text_model: boolean;
    text_backend: 'auto' | 'bert' | 'rule';
    image_top1_threshold: number;
    image_margin_threshold: number;
    text_top1_threshold: number;
    text_margin_threshold: number;
    weak_conflict_min_image_top1: number;
    weak_conflict_min_text_top1: number;
    diagnosis_conf_threshold: number;
    low_margin_threshold: number;
  };
  llm: {
    enable_llm: boolean;
    enable_treatment_generation: boolean;
    enable_constraint_validation: boolean;
  };
}

interface LlmRuntimeSnapshot {
  model: {
    provider: string;
    provider_display_name: string;
    model_id: string;
    model_display_name: string;
  };
  template: {
    name: string;
    purpose: string;
    scenes: string;
  };
  constraint_validation: {
    mode: string;
    global_enabled?: boolean;
    items: Array<{
      key: string;
      label: string;
      enabled: boolean;
      description: string;
    }>;
  };
}

interface ReviewItem {
  trace_id: string;
  farmer_id?: string;
  farmer_name?: string;
  top1_disease?: string;
  status?: string;
  assigned_expert_id?: string;
  expert_review_status?: string;
  review_flow_status?: 'normal' | 'abnormal' | 'closed';
  review_flow_note?: string;
  case_status?: string;
  review_task_status?: 'UNNEEDED' | 'UNASSIGNED' | 'ASSIGNED' | 'COMPLETED' | 'CANCELLED';
  admin_flag?: 'normal' | 'abnormal' | 'closed';
  admin_note?: string;
  updated_at?: string;
}

interface ReviewDetail extends ReviewItem {
  symptoms_text?: string;
  model_outputs?: {
    final_confidence?: number;
  };
  expert_review_result?: string;
  expert_review_notes?: string;
}

interface ExpertOption {
  user_id: string;
  display_name?: string;
}

const DEFAULT_CONFIG: AdminConfig = {
  workflow: {
    confirm_round_limit: 1,
    validator_rewrite_limit: 1,
    enable_validator_agent: true,
    enable_personalization_agent: true,
  },
  model_fusion: {
    enable_image_model: true,
    enable_text_model: true,
    text_backend: 'auto',
    image_top1_threshold: 0.65,
    image_margin_threshold: 0.15,
    text_top1_threshold: 0.4,
    text_margin_threshold: 0.1,
    weak_conflict_min_image_top1: 0.5,
    weak_conflict_min_text_top1: 0.4,
    diagnosis_conf_threshold: 0.5,
    low_margin_threshold: 0.03,
  },
  llm: {
    enable_llm: true,
    enable_treatment_generation: true,
    enable_constraint_validation: true,
  },
};

const DEFAULT_LLM_RUNTIME_SNAPSHOT: LlmRuntimeSnapshot = {
  model: {
    provider: 'openai',
    provider_display_name: 'OpenAI',
    model_id: 'unknown',
    model_display_name: 'OpenAI · unknown',
  },
  template: {
    name: 'llm_dynamic_generation',
    purpose: '生成可执行、可审计的番茄病害治疗建议，并结合个性化档案约束。',
    scenes: '家庭/中等规模/企业分档 + 专家复核后可再生成',
  },
  constraint_validation: {
    mode: 'runtime_default_summary',
    global_enabled: true,
    items: [
      { key: 'banned_ingredients', label: '禁用成分', enabled: true, description: '校验并剔除禁用成分建议' },
      { key: 'harvest_window', label: '采收窗口', enabled: true, description: '采收临近时补充窗口与时机提醒' },
      { key: 'safety_interval', label: '安全间隔', enabled: true, description: '提示施药后采收安全间隔' },
      { key: 'equipment_capability', label: '设备能力', enabled: true, description: '结合设备条件约束执行流程' },
      { key: 'organic_preference', label: '有机偏好', enabled: true, description: '偏好低残留/有机友好方案' },
      { key: 'risk_preference', label: '风险偏好', enabled: true, description: '按风险偏好控制建议激进程度' },
    ],
  },
};

const REVIEW_STATUS_OPTIONS = [
  { value: 'pending', label: '待分配' },
  { value: 'assigned', label: '已分配' },
  { value: 'completed', label: '已完成' },
] as const;

function formatTime(value?: string): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

const WORKFLOW_LIMIT_MIN = 0;
const WORKFLOW_LIMIT_MAX = 10;
const THRESHOLD_MIN = 0;
const THRESHOLD_MAX = 1;

function normalizeSystemConfig(raw: Record<string, unknown> | null | undefined): AdminConfig {
  const workflow = raw?.workflow as Record<string, unknown> | undefined;
  const modelFusion = raw?.model_fusion as Record<string, unknown> | undefined;
  const llm = raw?.llm as Record<string, unknown> | undefined;
  const textBackend = String(modelFusion?.text_backend || DEFAULT_CONFIG.model_fusion.text_backend) as AdminConfig['model_fusion']['text_backend'];
  const safeTextBackend = (textBackend === 'auto' || textBackend === 'bert' || textBackend === 'rule') ? textBackend : 'auto';

  return {
    workflow: {
      confirm_round_limit: Number(workflow?.confirm_round_limit ?? DEFAULT_CONFIG.workflow.confirm_round_limit),
      validator_rewrite_limit: Number(workflow?.validator_rewrite_limit ?? DEFAULT_CONFIG.workflow.validator_rewrite_limit),
      enable_validator_agent: workflow?.enable_validator_agent === undefined ? DEFAULT_CONFIG.workflow.enable_validator_agent : Boolean(workflow?.enable_validator_agent),
      enable_personalization_agent: workflow?.enable_personalization_agent === undefined ? DEFAULT_CONFIG.workflow.enable_personalization_agent : Boolean(workflow?.enable_personalization_agent),
    },
    model_fusion: {
      enable_image_model: modelFusion?.enable_image_model === undefined ? DEFAULT_CONFIG.model_fusion.enable_image_model : Boolean(modelFusion?.enable_image_model),
      enable_text_model: modelFusion?.enable_text_model === undefined ? DEFAULT_CONFIG.model_fusion.enable_text_model : Boolean(modelFusion?.enable_text_model),
      text_backend: safeTextBackend,
      image_top1_threshold: Number(modelFusion?.image_top1_threshold ?? DEFAULT_CONFIG.model_fusion.image_top1_threshold),
      image_margin_threshold: Number(modelFusion?.image_margin_threshold ?? DEFAULT_CONFIG.model_fusion.image_margin_threshold),
      text_top1_threshold: Number(modelFusion?.text_top1_threshold ?? DEFAULT_CONFIG.model_fusion.text_top1_threshold),
      text_margin_threshold: Number(modelFusion?.text_margin_threshold ?? DEFAULT_CONFIG.model_fusion.text_margin_threshold),
      weak_conflict_min_image_top1: Number(modelFusion?.weak_conflict_min_image_top1 ?? DEFAULT_CONFIG.model_fusion.weak_conflict_min_image_top1),
      weak_conflict_min_text_top1: Number(modelFusion?.weak_conflict_min_text_top1 ?? DEFAULT_CONFIG.model_fusion.weak_conflict_min_text_top1),
      diagnosis_conf_threshold: Number(modelFusion?.diagnosis_conf_threshold ?? DEFAULT_CONFIG.model_fusion.diagnosis_conf_threshold),
      low_margin_threshold: Number(modelFusion?.low_margin_threshold ?? DEFAULT_CONFIG.model_fusion.low_margin_threshold),
    },
    llm: {
      enable_llm: llm?.enable_llm === undefined ? DEFAULT_CONFIG.llm.enable_llm : Boolean(llm?.enable_llm),
      enable_treatment_generation: llm?.enable_treatment_generation === undefined ? DEFAULT_CONFIG.llm.enable_treatment_generation : Boolean(llm?.enable_treatment_generation),
      enable_constraint_validation: llm?.enable_constraint_validation === undefined ? DEFAULT_CONFIG.llm.enable_constraint_validation : Boolean(llm?.enable_constraint_validation),
    },
  };
}

export function AdminPage({ pageType }: { pageType: 'system' | 'review' }) {
  const authUser = loadAuthUser();
  const [config, setConfig] = useState<AdminConfig>(DEFAULT_CONFIG);
  const [llmRuntimeSnapshot, setLlmRuntimeSnapshot] = useState<LlmRuntimeSnapshot>(DEFAULT_LLM_RUNTIME_SNAPSHOT);
  const [configLoading, setConfigLoading] = useState(false);
  const [configSaving, setConfigSaving] = useState(false);
  const [configTip, setConfigTip] = useState<string>('');
  const [configErrors, setConfigErrors] = useState<string[]>([]);
  const [fusionExpanded, setFusionExpanded] = useState(true);
  const [workflowExpanded, setWorkflowExpanded] = useState(true);
  const [llmConfigExpanded, setLlmConfigExpanded] = useState(true);
  const [runtimeSnapshotExpanded, setRuntimeSnapshotExpanded] = useState(false);
  const [runtimeTemplateExpanded, setRuntimeTemplateExpanded] = useState(false);
  const [runtimeConstraintExpanded, setRuntimeConstraintExpanded] = useState(false);
  const [pathImpactExpanded, setPathImpactExpanded] = useState(true);

  const [statusFilter, setStatusFilter] = useState<(typeof REVIEW_STATUS_OPTIONS)[number]['value']>('pending');
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([]);
  const [selected, setSelected] = useState<ReviewDetail | null>(null);
  const [assignExpertId, setAssignExpertId] = useState('');
  const [flowStatus, setFlowStatus] = useState<'normal' | 'abnormal' | 'closed'>('normal');
  const [flowNote, setFlowNote] = useState('');
  const [reviewTip, setReviewTip] = useState<string>('');
  const [updatingReview, setUpdatingReview] = useState(false);
  const [expertOptions, setExpertOptions] = useState<ExpertOption[]>([]);

  const adminFetch = (input: RequestInfo | URL, init?: RequestInit) => {
    return fetch(input, withAuthHeaders(init, authUser));
  };

  const loadConfig = async () => {
    setConfigLoading(true);
    setConfigTip('');
    try {
      const resp = await adminFetch('/api/admin/system-config');
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '加载配置失败'));
      const raw = (data?.config || DEFAULT_CONFIG) as Record<string, unknown>;
      const snapshot = (data?.llm_runtime_snapshot || DEFAULT_LLM_RUNTIME_SNAPSHOT) as LlmRuntimeSnapshot;
      setConfig(normalizeSystemConfig(raw));
      setConfigErrors([]);
      setLlmRuntimeSnapshot(snapshot);
    } catch (error) {
      console.error(error);
      setConfigTip('加载配置失败，请稍后重试。');
      setLlmRuntimeSnapshot(DEFAULT_LLM_RUNTIME_SNAPSHOT);
    } finally {
      setConfigLoading(false);
    }
  };

  const validateConfig = (candidate: AdminConfig): string[] => {
    const errors: string[] = [];
    const intFields = [
      { key: '补充诊断轮次上限', value: candidate.workflow.confirm_round_limit },
      { key: '校验智能体最大重写次数', value: candidate.workflow.validator_rewrite_limit },
    ];
    intFields.forEach((item) => {
      if (!Number.isInteger(item.value) || item.value < WORKFLOW_LIMIT_MIN || item.value > WORKFLOW_LIMIT_MAX) {
        errors.push(`${item.key} 仅支持 ${WORKFLOW_LIMIT_MIN}~${WORKFLOW_LIMIT_MAX} 的整数`);
      }
    });
    const thresholdFields: Array<[string, number]> = [
      ['图像 top1 可靠阈值', candidate.model_fusion.image_top1_threshold],
      ['图像 margin 阈值', candidate.model_fusion.image_margin_threshold],
      ['文本 top1 可靠阈值', candidate.model_fusion.text_top1_threshold],
      ['文本 margin 阈值', candidate.model_fusion.text_margin_threshold],
      ['弱冲突图像阈值', candidate.model_fusion.weak_conflict_min_image_top1],
      ['弱冲突文本阈值', candidate.model_fusion.weak_conflict_min_text_top1],
      ['诊断低置信度阈值', candidate.model_fusion.diagnosis_conf_threshold],
      ['低 margin 阈值', candidate.model_fusion.low_margin_threshold],
    ];
    thresholdFields.forEach(([label, value]) => {
      if (!Number.isFinite(value) || value < THRESHOLD_MIN || value > THRESHOLD_MAX) {
        errors.push(`${label} 取值范围必须在 ${THRESHOLD_MIN}~${THRESHOLD_MAX}`);
      }
    });
    if (!['auto', 'bert', 'rule'].includes(candidate.model_fusion.text_backend)) {
      errors.push('文本诊断后端仅支持 auto / bert / rule');
    }
    return errors;
  };

  const saveConfig = async () => {
    const errors = validateConfig(config);
    setConfigErrors(errors);
    if (errors.length > 0) {
      setConfigTip('保存失败：请先修正配置项。');
      return;
    }
    setConfigSaving(true);
    setConfigTip('');
    try {
      const resp = await adminFetch('/api/admin/system-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '保存配置失败'));
      const nextConfig = normalizeSystemConfig((data?.config || {}) as Record<string, unknown>);
      setConfig(nextConfig);
      if (data?.llm_runtime_snapshot && typeof data.llm_runtime_snapshot === 'object') {
        setLlmRuntimeSnapshot(data.llm_runtime_snapshot as LlmRuntimeSnapshot);
      } else {
        await loadConfig();
      }
      setConfigTip('配置保存成功。');
    } catch (error) {
      console.error(error);
      setConfigTip('保存失败，请检查输入后重试。');
    } finally {
      setConfigSaving(false);
    }
  };

  const loadReviews = async () => {
    setReviewLoading(true);
    setReviewTip('');
    try {
      const resp = await adminFetch(`/api/admin/reviews?status=${encodeURIComponent(statusFilter)}&limit=50`);
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '加载复核列表失败'));
      const items = Array.isArray(data?.items) ? (data.items as ReviewItem[]) : [];
      setReviewItems(items);
      if (!items.find((item) => item.trace_id === selected?.trace_id)) {
        setSelected(null);
      }
    } catch (error) {
      console.error(error);
      setReviewItems([]);
      setReviewTip('加载复核列表失败。');
    } finally {
      setReviewLoading(false);
    }
  };

  const loadExperts = async () => {
    try {
      const resp = await adminFetch('/api/admin/accounts/experts');
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '加载专家列表失败'));
      const next = Array.isArray(data?.items) ? (data.items as ExpertOption[]) : [];
      setExpertOptions(next);
    } catch (error) {
      console.error(error);
      setExpertOptions([]);
    }
  };

  const loadReviewDetail = async (traceId: string) => {
    setReviewTip('');
    try {
      const resp = await adminFetch(`/api/admin/reviews/${encodeURIComponent(traceId)}`);
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '加载病例详情失败'));
      const item = (data?.item || null) as ReviewDetail | null;
      setSelected(item);
      setAssignExpertId(item?.assigned_expert_id || '');
      setFlowStatus(item?.admin_flag || item?.review_flow_status || 'normal');
      setFlowNote(item?.admin_note || item?.review_flow_note || '');
    } catch (error) {
      console.error(error);
      setSelected(null);
      setReviewTip('加载病例详情失败。');
    }
  };

  const assignExpert = async () => {
    if (!selected?.trace_id || !assignExpertId.trim()) return;
    if (statusFilter !== 'pending' || selected.review_task_status !== 'UNASSIGNED') return;
    setUpdatingReview(true);
    setReviewTip('');
    try {
      const resp = await adminFetch(`/api/admin/reviews/${encodeURIComponent(selected.trace_id)}/assign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ assigned_expert_id: assignExpertId.trim(), admin_note: flowNote, review_flow_note: flowNote }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '分配失败'));
      setReviewTip('复核任务分配成功。');
      await loadReviewDetail(selected.trace_id);
      await loadReviews();
    } catch (error) {
      console.error(error);
      setReviewTip('分配失败，请稍后重试。');
    } finally {
      setUpdatingReview(false);
    }
  };

  const updateFlowStatus = async () => {
    if (!selected?.trace_id) return;
    setUpdatingReview(true);
    setReviewTip('');
    try {
      const resp = await adminFetch(`/api/admin/reviews/${encodeURIComponent(selected.trace_id)}/flow-status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ admin_flag: flowStatus, admin_note: flowNote, review_flow_status: flowStatus, review_flow_note: flowNote }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '更新流程状态失败'));
      setReviewTip('复核流程状态更新成功。');
      await loadReviewDetail(selected.trace_id);
      await loadReviews();
    } catch (error) {
      console.error(error);
      setReviewTip('更新失败，请稍后重试。');
    } finally {
      setUpdatingReview(false);
    }
  };

  useEffect(() => {
    if (pageType === 'system') {
      void loadConfig();
    }
  }, [pageType]);

  useEffect(() => {
    if (pageType === 'review') {
      void loadReviews();
      void loadExperts();
    }
  }, [pageType, statusFilter]);

  const configSummary = '将可编辑配置、运行时观测、链路说明和页面操作分区，降低配置页混乱感。';

  const restoreFusionDefaults = () => {
    setConfig((prev) => ({
      ...prev,
      model_fusion: {
        ...prev.model_fusion,
        enable_image_model: DEFAULT_CONFIG.model_fusion.enable_image_model,
        enable_text_model: DEFAULT_CONFIG.model_fusion.enable_text_model,
        text_backend: DEFAULT_CONFIG.model_fusion.text_backend,
        image_top1_threshold: DEFAULT_CONFIG.model_fusion.image_top1_threshold,
        image_margin_threshold: DEFAULT_CONFIG.model_fusion.image_margin_threshold,
        text_top1_threshold: DEFAULT_CONFIG.model_fusion.text_top1_threshold,
        text_margin_threshold: DEFAULT_CONFIG.model_fusion.text_margin_threshold,
        weak_conflict_min_image_top1: DEFAULT_CONFIG.model_fusion.weak_conflict_min_image_top1,
        weak_conflict_min_text_top1: DEFAULT_CONFIG.model_fusion.weak_conflict_min_text_top1,
        diagnosis_conf_threshold: DEFAULT_CONFIG.model_fusion.diagnosis_conf_threshold,
        low_margin_threshold: DEFAULT_CONFIG.model_fusion.low_margin_threshold,
      },
    }));
    setConfigErrors([]);
    setConfigTip('已恢复“诊断证据与融合”默认值（尚未保存到服务器）。');
  };

  const restoreWorkflowDefaults = () => {
    setConfig((prev) => ({
      ...prev,
      workflow: {
        ...prev.workflow,
        confirm_round_limit: DEFAULT_CONFIG.workflow.confirm_round_limit,
        validator_rewrite_limit: DEFAULT_CONFIG.workflow.validator_rewrite_limit,
        enable_validator_agent: DEFAULT_CONFIG.workflow.enable_validator_agent,
        enable_personalization_agent: DEFAULT_CONFIG.workflow.enable_personalization_agent,
      },
    }));
    setConfigErrors([]);
    setConfigTip('已恢复“工作流与重试”默认值（尚未保存到服务器）。');
  };

  const restoreLlmDefaults = () => {
    setConfig((prev) => ({
      ...prev,
      llm: {
        ...prev.llm,
        enable_llm: DEFAULT_CONFIG.llm.enable_llm,
        enable_treatment_generation: DEFAULT_CONFIG.llm.enable_treatment_generation,
        enable_constraint_validation: DEFAULT_CONFIG.llm.enable_constraint_validation,
      },
    }));
    setConfigErrors([]);
    setConfigTip('已恢复“LLM 与生成”默认值（尚未保存到服务器）。');
  };

  const canAssignTask = statusFilter === 'pending' && selected?.review_task_status === 'UNASSIGNED';
  const showAssignControls = Boolean(selected) && canAssignTask;
  const assignedExpertReadonly = useMemo(() => {
    if (!selected?.assigned_expert_id) return '-';
    const option = expertOptions.find((item) => item.user_id === selected.assigned_expert_id);
    return option?.display_name ? `${option.user_id} · ${option.display_name}` : selected.assigned_expert_id;
  }, [expertOptions, selected?.assigned_expert_id]);

  if (pageType === 'system') {
    return (
      <Card className="glass-card">
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle className="text-white">系统配置</CardTitle>
            <p className="text-xs text-white/60 mt-1">{configSummary}</p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => { void loadConfig(); }}>
              <RefreshCcw className="w-4 h-4 mr-1" />刷新配置
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="border-white/15 text-white/75"
              onClick={() => {
                setConfig(JSON.parse(JSON.stringify(DEFAULT_CONFIG)) as AdminConfig);
                setConfigErrors([]);
                setConfigTip('已恢复整页默认值（尚未保存到服务器）。');
              }}
            >
              恢复整页默认值
            </Button>
            <Button size="sm" className="bg-[#c8f7c5] text-black" onClick={() => { void saveConfig(); }} disabled={configSaving}>
              <Save className="w-4 h-4 mr-1" />{configSaving ? '保存中...' : '保存配置'}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-5 text-white">
          {configLoading ? <p className="text-sm text-white/70 flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" />正在加载配置...</p> : null}
          {configTip ? <p className="text-sm text-[#c8f7c5]">{configTip}</p> : null}
          {configErrors.length > 0 ? (
            <div className="rounded-lg border border-red-400/30 bg-red-500/10 p-3 text-xs text-red-200 space-y-1">
              {configErrors.map((item) => <p key={item}>• {item}</p>)}
            </div>
          ) : null}

          <section className="rounded-xl border border-[#3ddc97]/30 p-4 space-y-4 bg-[#3ddc97]/[0.06]">
            <div className="rounded-lg border border-[#3ddc97]/30 bg-[#3ddc97]/10 p-3 text-xs text-[#d4ffe8]">
              <h3 className="font-semibold text-[#c8f7c5] text-base">A. 可编辑运行配置</h3>
              <p className="mt-1">以下字段会写入 /api/admin/system-config，保存后即时影响系统行为。</p>
            </div>

            <section className="rounded-xl border border-white/10 p-4 bg-white/[0.02] space-y-3">
              <div className="flex items-center justify-between gap-3">
                <button type="button" className="flex items-center gap-2 text-left" onClick={() => setFusionExpanded((v) => !v)}>
                  <h4 className="font-semibold text-[#c8f7c5]">A1. 诊断证据与融合</h4>
                  {fusionExpanded ? <ChevronUp className="w-4 h-4 text-white/70" /> : <ChevronDown className="w-4 h-4 text-white/70" />}
                </button>
                <Button variant="outline" size="sm" className="border-white/20 text-white/80" onClick={restoreFusionDefaults}>恢复本组默认值</Button>
              </div>
              <p className="text-xs text-white/60">控制诊断证据来源、文本/图像分支参与方式与融合判定门槛。</p>
              {fusionExpanded ? (
                <div className="grid md:grid-cols-2 gap-4">
                  <div className="flex items-center justify-between rounded-lg border border-white/10 p-3 bg-white/5"><Label>启用图像模型</Label><Switch checked={config.model_fusion.enable_image_model} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, enable_image_model: v } }))} /></div>
                  <div className="flex items-center justify-between rounded-lg border border-white/10 p-3 bg-white/5"><Label>启用文本模型</Label><Switch checked={config.model_fusion.enable_text_model} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, enable_text_model: v } }))} /></div>
                  <div><Label>文本诊断后端</Label><Select value={config.model_fusion.text_backend} onValueChange={(v) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, text_backend: v as 'auto' | 'bert' | 'rule' } }))}><SelectTrigger className="bg-white/5 border-white/20 text-white"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="auto">自动选择</SelectItem><SelectItem value="bert">BERT 模型</SelectItem><SelectItem value="rule">规则匹配</SelectItem></SelectContent></Select></div>
                  <div><Label>图像 top1 可靠阈值</Label><Input type="number" min={THRESHOLD_MIN} max={THRESHOLD_MAX} step="0.01" value={config.model_fusion.image_top1_threshold} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, image_top1_threshold: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" /></div>
                  <div><Label>图像 margin 阈值</Label><Input type="number" min={THRESHOLD_MIN} max={THRESHOLD_MAX} step="0.01" value={config.model_fusion.image_margin_threshold} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, image_margin_threshold: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" /></div>
                  <div><Label>文本 top1 可靠阈值</Label><Input type="number" min={THRESHOLD_MIN} max={THRESHOLD_MAX} step="0.01" value={config.model_fusion.text_top1_threshold} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, text_top1_threshold: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" /></div>
                  <div><Label>文本 margin 阈值</Label><Input type="number" min={THRESHOLD_MIN} max={THRESHOLD_MAX} step="0.01" value={config.model_fusion.text_margin_threshold} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, text_margin_threshold: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" /></div>
                  <div><Label>弱冲突图像阈值</Label><Input type="number" min={THRESHOLD_MIN} max={THRESHOLD_MAX} step="0.01" value={config.model_fusion.weak_conflict_min_image_top1} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, weak_conflict_min_image_top1: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" /></div>
                  <div><Label>弱冲突文本阈值</Label><Input type="number" min={THRESHOLD_MIN} max={THRESHOLD_MAX} step="0.01" value={config.model_fusion.weak_conflict_min_text_top1} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, weak_conflict_min_text_top1: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" /></div>
                  <div><Label>诊断低置信度阈值</Label><Input type="number" min={THRESHOLD_MIN} max={THRESHOLD_MAX} step="0.01" value={config.model_fusion.diagnosis_conf_threshold} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, diagnosis_conf_threshold: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" /></div>
                  <div><Label>低 margin 阈值</Label><Input type="number" min={THRESHOLD_MIN} max={THRESHOLD_MAX} step="0.01" value={config.model_fusion.low_margin_threshold} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, low_margin_threshold: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" /></div>
                </div>
              ) : null}
            </section>

            <section className="rounded-xl border border-white/10 p-4 bg-white/[0.02] space-y-3">
              <div className="flex items-center justify-between gap-3">
                <button type="button" className="flex items-center gap-2 text-left" onClick={() => setWorkflowExpanded((v) => !v)}>
                  <h4 className="font-semibold text-[#c8f7c5]">A2. 工作流与重试</h4>
                  {workflowExpanded ? <ChevronUp className="w-4 h-4 text-white/70" /> : <ChevronDown className="w-4 h-4 text-white/70" />}
                </button>
                <Button variant="outline" size="sm" className="border-white/20 text-white/80" onClick={restoreWorkflowDefaults}>恢复本组默认值</Button>
              </div>
              <p className="text-xs text-white/60">控制是否允许补充诊断、方案重写、个性化增强与校验阶段。</p>
              {workflowExpanded ? (
                <div className="grid md:grid-cols-2 gap-4">
                  <div><Label>补充诊断轮次上限</Label><Input type="number" min={WORKFLOW_LIMIT_MIN} max={WORKFLOW_LIMIT_MAX} value={config.workflow.confirm_round_limit} onChange={(e) => setConfig((prev) => ({ ...prev, workflow: { ...prev.workflow, confirm_round_limit: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" /></div>
                  <div><Label>校验智能体最大重写次数</Label><Input type="number" min={WORKFLOW_LIMIT_MIN} max={WORKFLOW_LIMIT_MAX} value={config.workflow.validator_rewrite_limit} onChange={(e) => setConfig((prev) => ({ ...prev, workflow: { ...prev.workflow, validator_rewrite_limit: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" /></div>
                  <div className="flex items-center justify-between rounded-lg border border-white/10 p-3 bg-white/5"><Label>启用个性化智能体</Label><Switch checked={config.workflow.enable_personalization_agent} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, workflow: { ...prev.workflow, enable_personalization_agent: v } }))} /></div>
                  <div className="flex items-center justify-between rounded-lg border border-white/10 p-3 bg-white/5"><Label>启用校验智能体</Label><Switch checked={config.workflow.enable_validator_agent} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, workflow: { ...prev.workflow, enable_validator_agent: v } }))} /></div>
                </div>
              ) : null}
            </section>

            <section className="rounded-xl border border-white/10 p-4 bg-white/[0.02] space-y-3">
              <div className="flex items-center justify-between gap-3">
                <button type="button" className="flex items-center gap-2 text-left" onClick={() => setLlmConfigExpanded((v) => !v)}>
                  <h4 className="font-semibold text-[#c8f7c5]">A3. LLM 与生成</h4>
                  {llmConfigExpanded ? <ChevronUp className="w-4 h-4 text-white/70" /> : <ChevronDown className="w-4 h-4 text-white/70" />}
                </button>
                <Button variant="outline" size="sm" className="border-white/20 text-white/80" onClick={restoreLlmDefaults}>恢复本组默认值</Button>
              </div>
              <p className="text-xs text-white/60">控制 LLM 总开关、治疗建议生成阶段与约束规则启用状态。</p>
              {llmConfigExpanded ? (
                <div className="grid md:grid-cols-3 gap-4">
                  <div className="flex items-center justify-between rounded-lg border border-white/10 p-4 bg-white/5"><Label className="text-white">启用大语言模型</Label><Switch checked={config.llm.enable_llm} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, llm: { ...prev.llm, enable_llm: v } }))} /></div>
                  <div className="flex items-center justify-between rounded-lg border border-white/10 p-4 bg-white/5"><Label className="text-white">启用治疗建议生成</Label><Switch checked={config.llm.enable_treatment_generation} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, llm: { ...prev.llm, enable_treatment_generation: v } }))} /></div>
                  <div className="flex items-center justify-between rounded-lg border border-white/10 p-4 bg-white/5"><Label className="text-white">启用约束校验</Label><Switch checked={config.llm.enable_constraint_validation} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, llm: { ...prev.llm, enable_constraint_validation: v } }))} /></div>
                </div>
              ) : null}
            </section>
          </section>

          <section className="rounded-xl border border-[#7da5ff]/30 p-4 bg-[#7da5ff]/[0.06] space-y-4">
            <div className="rounded-lg border border-[#7da5ff]/30 bg-[#7da5ff]/10 p-3 text-xs text-[#d5e3ff]">
              <h3 className="font-semibold text-[#bad1ff] text-base">B. 运行时观测（只读）</h3>
              <p className="mt-1">仅用于查看，不可直接编辑；不作为配置写入源。</p>
            </div>
            <div className="rounded-xl border border-white/10 p-4 bg-gradient-to-br from-[#13221c] to-[#0f1a15]">
              <button type="button" className="w-full flex items-center justify-between text-left" onClick={() => setRuntimeSnapshotExpanded((v) => !v)}>
                <h4 className="text-sm font-semibold text-[#c8f7c5]">当前模型</h4>
                {runtimeSnapshotExpanded ? <ChevronUp className="w-4 h-4 text-white/70" /> : <ChevronDown className="w-4 h-4 text-white/70" />}
              </button>
              {runtimeSnapshotExpanded ? <div className="mt-4 grid md:grid-cols-3 gap-4"><div className="bg-white/5 border border-white/10 rounded-lg p-3">{llmRuntimeSnapshot.model.provider_display_name}</div><div className="bg-white/5 border border-white/10 rounded-lg p-3">{llmRuntimeSnapshot.model.model_id}</div><div className="bg-white/5 border border-white/10 rounded-lg p-3">{llmRuntimeSnapshot.model.model_display_name}</div></div> : null}
            </div>
            <div className="rounded-xl border border-white/10 p-4 bg-gradient-to-br from-[#13221c] to-[#0f1a15]">
              <button type="button" className="w-full flex items-center justify-between text-left" onClick={() => setRuntimeTemplateExpanded((v) => !v)}>
                <h4 className="text-sm font-semibold text-[#c8f7c5]">当前生成模板</h4>
                {runtimeTemplateExpanded ? <ChevronUp className="w-4 h-4 text-white/70" /> : <ChevronDown className="w-4 h-4 text-white/70" />}
              </button>
              {runtimeTemplateExpanded ? <div className="mt-4 space-y-2"><div className="bg-white/5 border border-white/10 rounded-lg p-3">模板：{llmRuntimeSnapshot.template.name}</div><div className="bg-white/5 border border-white/10 rounded-lg p-3">场景：{llmRuntimeSnapshot.template.scenes}</div><div className="bg-white/5 border border-white/10 rounded-lg p-3">用途：{llmRuntimeSnapshot.template.purpose}</div></div> : null}
            </div>
            <div className="rounded-xl border border-white/10 p-4 bg-gradient-to-br from-[#13221c] to-[#0f1a15]">
              <button type="button" className="w-full flex items-center justify-between text-left" onClick={() => setRuntimeConstraintExpanded((v) => !v)}>
                <h4 className="text-sm font-semibold text-[#c8f7c5]">当前约束状态</h4>
                {runtimeConstraintExpanded ? <ChevronUp className="w-4 h-4 text-white/70" /> : <ChevronDown className="w-4 h-4 text-white/70" />}
              </button>
              {runtimeConstraintExpanded ? (
                <div className="mt-4 space-y-2">
                  <p className="text-xs text-white/70">模式：{llmRuntimeSnapshot.constraint_validation.mode}，全局：{llmRuntimeSnapshot.constraint_validation.global_enabled === false ? '禁用' : '启用'}</p>
                  {llmRuntimeSnapshot.constraint_validation.items.map((item) => (
                    <div key={item.key} className="rounded-lg border border-white/10 bg-white/5 p-3">
                      <div className="flex items-center justify-between">
                        <p className="text-sm text-white">{item.label}</p>
                        <span className={`text-xs px-2 py-1 rounded border ${item.enabled ? 'border-[#c8f7c5]/40 text-[#c8f7c5]' : 'border-white/20 text-white/60'}`}>{item.enabled ? '已启用' : '已关闭'}</span>
                      </div>
                      <p className="text-xs text-white/50 mt-1">{item.description}</p>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </section>

          <section className="rounded-xl border border-[#f8d25c]/30 p-4 bg-[#f8d25c]/[0.05] space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-[#f8d25c] text-base">C. 链路影响说明（设计说明）</h3>
              <button type="button" className="flex items-center gap-1 text-white/70" onClick={() => setPathImpactExpanded((v) => !v)}>
                {pathImpactExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </button>
            </div>
            <p className="text-xs text-white/60">该区不是接口返回，也不是配置写入源，仅用于理解当前实现。</p>
            {pathImpactExpanded ? (
              <ul className="text-xs text-white/70 space-y-2 list-disc pl-5">
                {/* TODO(graph-shortcut): 后续可评估将 enable_personalization_agent 下沉为 route/graph shortcut，减少无效路径开销。 */}
                <li><code>enable_personalization_agent</code>：当前实现是节点内逻辑降级，不是 LangGraph 图结构裁剪。</li>
                <li><code>enable_treatment_generation</code>：影响是否进入治疗建议生成阶段。</li>
                <li><code>enable_constraint_validation</code> + <code>enable_validator_agent</code>：共同决定是否进入约束校验阶段。</li>
              </ul>
            ) : null}
          </section>

          <section className="rounded-xl border border-white/15 p-4 bg-white/[0.03]">
            <h3 className="font-semibold text-white text-base">D. 页面操作区</h3>
            <p className="text-xs text-white/60 mt-1">顶部工具条保留刷新配置、恢复整页默认值、保存配置；各分组内保留恢复本组默认值。</p>
          </section>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6 animate-fadeIn">
      <div>
        <h1 className="text-3xl font-bold text-white"><span className="text-[#c8f7c5]">复核管理</span></h1>
        <p className="text-white/60 mt-1">管理专家复核任务的分配、状态跟踪和流程控制</p>
      </div>

      <Card className="glass-card">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-white flex items-center gap-2">
            <ClipboardCheck className="w-5 h-5 text-[#c8f7c5]" />
            复核任务列表
          </CardTitle>
          <div className="flex gap-2">
            {REVIEW_STATUS_OPTIONS.map((item) => (
              <Button key={item.value} size="sm" variant={statusFilter === item.value ? 'default' : 'outline'} onClick={() => setStatusFilter(item.value)} className={statusFilter === item.value ? 'bg-[#c8f7c5] text-black' : 'border-white/20 text-white hover:bg-white/10'}>{item.label}</Button>
            ))}
            <Button variant="outline" size="sm" onClick={() => { void loadReviews(); }} className="border-white/20 text-white hover:bg-white/10"><RefreshCcw className="w-4 h-4 mr-1" />刷新</Button>
          </div>
        </CardHeader>
        <CardContent className="grid lg:grid-cols-2 gap-4 h-[70vh] min-h-[560px]">
          <div className="space-y-3 overflow-y-auto pr-1 dashboard-scrollbar">
            {reviewLoading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="w-8 h-8 animate-spin text-[#c8f7c5]" />
                <span className="ml-3 text-white/70">加载中...</span>
              </div>
            ) : null}
            {!reviewLoading && reviewItems.length === 0 ? (
              <div className="text-center py-16">
                <CheckCircle2 className="w-16 h-16 text-[#c8f7c5]/30 mx-auto mb-4" />
                <h3 className="text-xl text-white/80 mb-2">当前筛选下暂无病例</h3>
                <p className="text-white/50 text-sm">请切换筛选条件或稍后刷新</p>
              </div>
            ) : null}
            {reviewItems.map((item) => (
              <button key={item.trace_id} type="button" onClick={() => { void loadReviewDetail(item.trace_id); }} className={cn("w-full text-left rounded-xl border p-4 bg-white/5 hover:bg-white/[0.08] transition-all duration-300", selected?.trace_id === item.trace_id ? "border-[#c8f7c5]/50 bg-[#c8f7c5]/5" : "border-white/10 hover:border-[#c8f7c5]/30")}>
                <div className="flex items-start justify-between mb-2">
                  <div className="flex-1">
                    <p className="text-xs text-white/40 mb-1 font-mono">trace_id</p>
                    <p className="text-white font-mono text-sm">{item.trace_id.slice(0, 16)}...</p>
                  </div>
                  <Badge className={cn("text-xs", item.admin_flag === 'abnormal' ? 'bg-orange-400/20 text-orange-300 border-orange-400/30' : item.admin_flag === 'closed' ? 'bg-red-400/20 text-red-300 border-red-400/30' : 'bg-emerald-400/20 text-emerald-300 border-emerald-400/30')}>
                    {item.admin_flag === 'abnormal' ? '异常' : item.admin_flag === 'closed' ? '关闭' : '正常'}
                  </Badge>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="flex items-center gap-1 text-white/70">
                    <User className="w-3 h-3" />
                    <span>{item.farmer_name || item.farmer_id || '-'}</span>
                  </div>
                  <div className="flex items-center gap-1 text-white/70">
                    <Clock className="w-3 h-3" />
                    <span>{formatTime(item.updated_at)}</span>
                  </div>
                </div>
                <div className="mt-2 pt-2 border-t border-white/10">
                  <p className="text-xs text-white/50 mb-1">系统诊断</p>
                  <p className="text-[#c8f7c5] font-medium text-sm">{item.top1_disease || '-'}</p>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <p className="text-white/50">任务状态</p>
                    <p className="text-white/80">{item.review_task_status || '-'}</p>
                  </div>
                  <div>
                    <p className="text-white/50">病例状态</p>
                    <p className="text-white/80">{item.case_status || item.status || '-'}</p>
                  </div>
                </div>
              </button>
            ))}
          </div>

          <div className="rounded-xl border border-white/10 p-4 bg-white/5 text-sm text-white space-y-4 overflow-y-auto dashboard-scrollbar">
            {!selected ? (
              <div className="text-center py-16">
                <ClipboardCheck className="w-16 h-16 text-[#c8f7c5]/30 mx-auto mb-4" />
                <h3 className="text-xl text-white/80 mb-2">请选择左侧病例</h3>
                <p className="text-white/50 text-sm">点击病例卡片查看详细信息</p>
              </div>
            ) : (
              <>
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-[#c8f7c5] font-semibold">病例详情</h3>
                    <Badge className={cn("text-xs", selected.admin_flag === 'abnormal' ? 'bg-orange-400/20 text-orange-300 border-orange-400/30' : selected.admin_flag === 'closed' ? 'bg-red-400/20 text-red-300 border-red-400/30' : 'bg-emerald-400/20 text-emerald-300 border-emerald-400/30')}>
                      {selected.admin_flag === 'abnormal' ? '异常' : selected.admin_flag === 'closed' ? '关闭' : '正常'}
                    </Badge>
                  </div>
                  
                  <div className="rounded-lg bg-white/5 p-3 space-y-2">
                    <div>
                      <p className="text-white/50 text-xs mb-1">病例追踪号</p>
                      <p className="text-white font-mono text-sm">{selected.trace_id}</p>
                    </div>
                    <div>
                      <p className="text-white/50 text-xs mb-1">症状摘要</p>
                      <p className="text-white/90">{selected.symptoms_text || '-'}</p>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div className="rounded-lg bg-white/5 p-3">
                      <p className="text-white/50 text-xs mb-1">当前诊断</p>
                      <p className="text-[#c8f7c5] font-medium">{selected.top1_disease || '-'}</p>
                    </div>
                    <div className="rounded-lg bg-white/5 p-3">
                      <p className="text-white/50 text-xs mb-1">最终置信度</p>
                      <p className="text-white font-medium">{typeof selected.model_outputs?.final_confidence === 'number' ? `${(selected.model_outputs.final_confidence * 100).toFixed(2)}%` : '-'}</p>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div className="rounded-lg bg-white/5 p-3">
                      <p className="text-white/50 text-xs mb-1">病例状态</p>
                      <p className="text-white/80">{selected.case_status || selected.status || '-'}</p>
                    </div>
                    <div className="rounded-lg bg-white/5 p-3">
                      <p className="text-white/50 text-xs mb-1">专家任务</p>
                      <p className="text-white/80">{selected.review_task_status || '-'}</p>
                    </div>
                  </div>

                  <div className="rounded-lg bg-white/5 p-3 space-y-2">
                    <div>
                      <p className="text-white/50 text-xs mb-1">复核结果</p>
                      <p className="text-white/90">{selected.expert_review_result || '-'}</p>
                    </div>
                    <div>
                      <p className="text-white/50 text-xs mb-1">复核备注</p>
                      <p className="text-white/90">{selected.expert_review_notes || '-'}</p>
                    </div>
                  </div>
                </div>

                <div className="pt-4 border-t border-white/10 space-y-4">
                  <h3 className="text-[#c8f7c5] font-semibold">管理操作</h3>
                  
                  {showAssignControls ? (
                    <div className="space-y-2">
                      <Label>分配专家账号</Label>
                      <Select value={assignExpertId} onValueChange={setAssignExpertId}>
                        <SelectTrigger className="bg-white/5 border-white/20 text-white">
                          <SelectValue placeholder="请选择专家账号" />
                        </SelectTrigger>
                        <SelectContent>
                          {expertOptions.map((item) => (
                            <SelectItem key={item.user_id} value={item.user_id}>
                              {item.user_id}{item.display_name ? ` · ${item.display_name}` : ''}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  ) : (
                    <div className="rounded-lg bg-white/5 p-3">
                      <p className="text-white/50 text-xs mb-1">已分配专家</p>
                      <p className="text-white/90">{assignedExpertReadonly}</p>
                    </div>
                  )}

                  <div className="space-y-2">
                    <Label>管理标签</Label>
                    <Select value={flowStatus} onValueChange={(v) => setFlowStatus(v as 'normal' | 'abnormal' | 'closed')}>
                      <SelectTrigger className="bg-white/5 border-white/20 text-white"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="normal">正常</SelectItem>
                        <SelectItem value="abnormal">异常</SelectItem>
                        <SelectItem value="closed">关闭</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-2">
                    <Label>管理备注</Label>
                    <Textarea value={flowNote} onChange={(e) => setFlowNote(e.target.value)} className="bg-white/5 border-white/20 text-white" placeholder="请输入管理备注..." />
                  </div>

                  {reviewTip ? (
                    <div className="rounded-lg bg-[#c8f7c5]/10 border border-[#c8f7c5]/30 p-3">
                      <p className="text-[#c8f7c5] text-xs">{reviewTip}</p>
                    </div>
                  ) : null}

                  <div className="flex gap-2">
                    {showAssignControls ? (
                      <Button onClick={() => { void assignExpert(); }} disabled={updatingReview || !assignExpertId.trim()} className="bg-[#c8f7c5] text-black hover:bg-[#c8f7c5]/80 transition-all">
                        {updatingReview ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" />分配中...</> : <>分配复核任务</>}
                      </Button>
                    ) : null}
                    <Button variant="outline" onClick={() => { void updateFlowStatus(); }} disabled={updatingReview} className="border-white/20 text-white hover:bg-white/10 transition-all">
                      {updatingReview ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" />保存中...</> : <>保存管理标签</>}
                    </Button>
                  </div>
                </div>
              </>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
