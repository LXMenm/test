import { useEffect, useMemo, useState } from 'react';
import { Loader2, RefreshCcw, Save } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';

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
  const [config, setConfig] = useState<AdminConfig>(DEFAULT_CONFIG);
  const [llmRuntimeSnapshot, setLlmRuntimeSnapshot] = useState<LlmRuntimeSnapshot>(DEFAULT_LLM_RUNTIME_SNAPSHOT);
  const [configLoading, setConfigLoading] = useState(false);
  const [configSaving, setConfigSaving] = useState(false);
  const [configTip, setConfigTip] = useState<string>('');
  const [configErrors, setConfigErrors] = useState<string[]>([]);

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

  const loadConfig = async () => {
    setConfigLoading(true);
    setConfigTip('');
    try {
      const resp = await fetch('/api/admin/system-config');
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
      const resp = await fetch('/api/admin/system-config', {
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
      const resp = await fetch(`/api/admin/reviews?status=${encodeURIComponent(statusFilter)}&limit=50`);
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
      const resp = await fetch('/api/admin/accounts/experts');
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
      const resp = await fetch(`/api/admin/reviews/${encodeURIComponent(traceId)}`);
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
      const resp = await fetch(`/api/admin/reviews/${encodeURIComponent(selected.trace_id)}/assign`, {
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
      const resp = await fetch(`/api/admin/reviews/${encodeURIComponent(selected.trace_id)}/flow-status`, {
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

  const configSummary = useMemo(() => {
    return `补充诊断轮次上限 ${config.workflow.confirm_round_limit} · 最大重写次数 ${config.workflow.validator_rewrite_limit} · 文本后端 ${config.model_fusion.text_backend}`;
  }, [config]);

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
              onClick={() => {
                setConfig(JSON.parse(JSON.stringify(DEFAULT_CONFIG)) as AdminConfig);
                setConfigErrors([]);
                setConfigTip('已恢复默认配置（尚未保存到服务器）。');
              }}
            >
              恢复默认配置
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

          <section className="grid md:grid-cols-2 gap-4 rounded-xl border border-white/10 p-3">
            <h3 className="md:col-span-2 font-semibold text-[#c8f7c5]">流程参数</h3>
            <div>
              <Label>补充诊断轮次上限</Label>
              <Input type="number" min={WORKFLOW_LIMIT_MIN} max={WORKFLOW_LIMIT_MAX} value={config.workflow.confirm_round_limit} onChange={(e) => setConfig((prev) => ({ ...prev, workflow: { ...prev.workflow, confirm_round_limit: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" />
              <p className="text-xs text-white/50 mt-1">取值范围 {WORKFLOW_LIMIT_MIN}~{WORKFLOW_LIMIT_MAX}（整数）</p>
            </div>
            <div>
              <Label>校验智能体最大重写次数</Label>
              <Input type="number" min={WORKFLOW_LIMIT_MIN} max={WORKFLOW_LIMIT_MAX} value={config.workflow.validator_rewrite_limit} onChange={(e) => setConfig((prev) => ({ ...prev, workflow: { ...prev.workflow, validator_rewrite_limit: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" />
              <p className="text-xs text-white/50 mt-1">取值范围 {WORKFLOW_LIMIT_MIN}~{WORKFLOW_LIMIT_MAX}（整数）</p>
            </div>
            <div className="rounded-lg border border-white/10 p-3 bg-white/5 space-y-2">
              <div className="flex items-center justify-between">
                <Label>启用校验智能体</Label>
                <Switch checked={config.workflow.enable_validator_agent} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, workflow: { ...prev.workflow, enable_validator_agent: v } }))} />
              </div>
              <p className="text-xs text-white/50">关闭后跳过验证/重写相关流程。</p>
            </div>
            <div className="rounded-lg border border-white/10 p-3 bg-white/5 space-y-2">
              <div className="flex items-center justify-between">
                <Label>启用个性化智能体</Label>
                <Switch checked={config.workflow.enable_personalization_agent} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, workflow: { ...prev.workflow, enable_personalization_agent: v } }))} />
              </div>
              <p className="text-xs text-white/50">关闭后不注入个性化上下文与个性化约束。</p>
            </div>
          </section>

          <section className="grid md:grid-cols-2 gap-4 rounded-xl border border-white/10 p-3">
            <h3 className="md:col-span-2 font-semibold text-[#c8f7c5]">模型与融合参数</h3>
            <div className="flex items-center justify-between rounded-lg border border-white/10 p-3">
              <Label>启用图像模型</Label><Switch checked={config.model_fusion.enable_image_model} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, enable_image_model: v } }))} />
            </div>
            <div className="flex items-center justify-between rounded-lg border border-white/10 p-3">
              <Label>启用文本模型</Label><Switch checked={config.model_fusion.enable_text_model} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, enable_text_model: v } }))} />
            </div>
            <div>
              <Label>文本诊断后端</Label>
              <Select value={config.model_fusion.text_backend} onValueChange={(v) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, text_backend: v as 'auto' | 'bert' | 'rule' } }))}>
                <SelectTrigger className="bg-white/5 border-white/20 text-white"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">自动选择</SelectItem>
                  <SelectItem value="bert">BERT 模型</SelectItem>
                  <SelectItem value="rule">规则匹配</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>图像 top1 可靠阈值</Label>
              <Input type="number" min={THRESHOLD_MIN} max={THRESHOLD_MAX} step="0.01" value={config.model_fusion.image_top1_threshold} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, image_top1_threshold: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" />
              <p className="text-xs text-white/50 mt-1">取值范围 0~1</p>
            </div>
            <div>
              <Label>图像 margin 阈值</Label>
              <Input type="number" min={THRESHOLD_MIN} max={THRESHOLD_MAX} step="0.01" value={config.model_fusion.image_margin_threshold} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, image_margin_threshold: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" />
              <p className="text-xs text-white/50 mt-1">取值范围 0~1</p>
            </div>
            <div>
              <Label>文本 top1 可靠阈值</Label>
              <Input type="number" min={THRESHOLD_MIN} max={THRESHOLD_MAX} step="0.01" value={config.model_fusion.text_top1_threshold} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, text_top1_threshold: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" />
              <p className="text-xs text-white/50 mt-1">取值范围 0~1</p>
            </div>
            <div>
              <Label>文本 margin 阈值</Label>
              <Input type="number" min={THRESHOLD_MIN} max={THRESHOLD_MAX} step="0.01" value={config.model_fusion.text_margin_threshold} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, text_margin_threshold: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" />
              <p className="text-xs text-white/50 mt-1">取值范围 0~1</p>
            </div>
            <div>
              <Label>弱冲突图像阈值</Label>
              <Input type="number" min={THRESHOLD_MIN} max={THRESHOLD_MAX} step="0.01" value={config.model_fusion.weak_conflict_min_image_top1} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, weak_conflict_min_image_top1: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" />
              <p className="text-xs text-white/50 mt-1">取值范围 0~1</p>
            </div>
            <div>
              <Label>弱冲突文本阈值</Label>
              <Input type="number" min={THRESHOLD_MIN} max={THRESHOLD_MAX} step="0.01" value={config.model_fusion.weak_conflict_min_text_top1} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, weak_conflict_min_text_top1: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" />
              <p className="text-xs text-white/50 mt-1">取值范围 0~1</p>
            </div>
            <div>
              <Label>诊断低置信度阈值</Label>
              <Input type="number" min={THRESHOLD_MIN} max={THRESHOLD_MAX} step="0.01" value={config.model_fusion.diagnosis_conf_threshold} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, diagnosis_conf_threshold: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" />
              <p className="text-xs text-white/50 mt-1">取值范围 0~1</p>
            </div>
            <div>
              <Label>低 margin 阈值</Label>
              <Input type="number" min={THRESHOLD_MIN} max={THRESHOLD_MAX} step="0.01" value={config.model_fusion.low_margin_threshold} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, low_margin_threshold: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" />
              <p className="text-xs text-white/50 mt-1">取值范围 0~1</p>
            </div>
          </section>

          <section className="rounded-xl border border-white/10 p-5 space-y-4">
            <h3 className="font-semibold text-[#c8f7c5] text-lg flex items-center gap-2">
              <div className="w-1.5 h-6 bg-[#c8f7c5] rounded-full" />
              大语言模型参数
            </h3>
            <div className="grid md:grid-cols-3 gap-4">
              <div className="flex items-center justify-between rounded-lg border border-white/10 p-4 bg-white/5">
                <Label className="text-white">启用大语言模型</Label>
                <Switch checked={config.llm.enable_llm} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, llm: { ...prev.llm, enable_llm: v } }))} />
              </div>
              <div className="flex items-center justify-between rounded-lg border border-white/10 p-4 bg-white/5">
                <Label className="text-white">启用治疗建议生成</Label>
                <Switch checked={config.llm.enable_treatment_generation} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, llm: { ...prev.llm, enable_treatment_generation: v } }))} />
              </div>
              <div className="flex items-center justify-between rounded-lg border border-white/10 p-4 bg-white/5">
                <Label className="text-white">启用约束校验</Label>
                <Switch checked={config.llm.enable_constraint_validation} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, llm: { ...prev.llm, enable_constraint_validation: v } }))} />
              </div>
            </div>
            <div className="rounded-xl border border-white/10 p-4 bg-white/5">
              <h4 className="text-sm font-semibold text-[#c8f7c5] mb-2">运行时快照（只读）</h4>
              <p className="text-xs text-white/50">以下信息来自当前环境与运行时配置，仅用于观测，不可在此处直接编辑。</p>
            </div>

            <div className="rounded-xl border border-white/10 p-4 bg-gradient-to-br from-[#13221c] to-[#0f1a15]">
              <h4 className="text-sm font-semibold text-[#c8f7c5] mb-4 flex items-center gap-2">
                <div className="w-1 h-5 bg-[#c8f7c5] rounded-full" />
                当前大模型信息（只读）
              </h4>
              <div className="grid md:grid-cols-3 gap-4">
                <div>
                  <Label className="text-white/50 text-xs mb-1 block">当前大模型提供方</Label>
                  <div className="bg-white/5 border border-white/10 rounded-lg p-3 text-white/90">{llmRuntimeSnapshot.model.provider_display_name}</div>
                </div>
                <div>
                  <Label className="text-white/50 text-xs mb-1 block">当前模型名称 / model_id</Label>
                  <div className="bg-white/5 border border-white/10 rounded-lg p-3 text-white/90">{llmRuntimeSnapshot.model.model_id}</div>
                </div>
                <div>
                  <Label className="text-white/50 text-xs mb-1 block">当前模型显示名称</Label>
                  <div className="bg-white/5 border border-white/10 rounded-lg p-3 text-white/90">{llmRuntimeSnapshot.model.model_display_name}</div>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-white/10 p-4 bg-gradient-to-br from-[#13221c] to-[#0f1a15]">
              <h4 className="text-sm font-semibold text-[#c8f7c5] mb-4 flex items-center gap-2">
                <div className="w-1 h-5 bg-[#c8f7c5] rounded-full" />
                当前治疗建议模板信息（只读）
              </h4>
              <div className="grid md:grid-cols-3 gap-4">
                <div>
                  <Label className="text-white/50 text-xs mb-1 block">当前治疗建议模板</Label>
                  <div className="bg-white/5 border border-white/10 rounded-lg p-3 text-white/90">{llmRuntimeSnapshot.template.name}</div>
                </div>
                <div className="md:col-span-2">
                  <Label className="text-white/50 text-xs mb-1 block">模板适用场景</Label>
                  <div className="bg-white/5 border border-white/10 rounded-lg p-3 text-white/90">{llmRuntimeSnapshot.template.scenes}</div>
                </div>
                <div className="md:col-span-3">
                  <Label className="text-white/50 text-xs mb-1 block">模板用途说明</Label>
                  <div className="bg-white/5 border border-white/10 rounded-lg p-4 text-white/80 text-sm">{llmRuntimeSnapshot.template.purpose}</div>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-white/10 p-4 bg-gradient-to-br from-[#13221c] to-[#0f1a15]">
              <h4 className="text-sm font-semibold text-[#c8f7c5] mb-4 flex items-center gap-2">
                <div className="w-1 h-5 bg-[#c8f7c5] rounded-full" />
                约束校验信息（只读）
              </h4>
              <div className="rounded-lg border border-white/10 bg-white/5 p-3 mb-3">
                <p className="text-xs text-white/50">全局开关状态</p>
                <p className={`text-sm mt-1 ${llmRuntimeSnapshot.constraint_validation.global_enabled === false ? 'text-red-300' : 'text-[#c8f7c5]'}`}>
                  {llmRuntimeSnapshot.constraint_validation.global_enabled === false ? '当前约束校验未启用' : '当前约束校验已启用'}
                </p>
              </div>
              <div className="space-y-2">
                {llmRuntimeSnapshot.constraint_validation.items.map((item) => (
                  <div key={item.key} className="rounded-lg border border-white/10 bg-white/5 p-3">
                    <div className="flex items-center justify-between">
                      <p className="text-sm text-white">{item.label}</p>
                      <span className={`text-xs px-2 py-1 rounded border ${item.enabled ? 'border-[#c8f7c5]/40 text-[#c8f7c5]' : 'border-white/20 text-white/60'}`}>
                        {item.enabled ? '已启用' : '已关闭'}
                      </span>
                    </div>
                    <p className="text-xs text-white/50 mt-1">{item.description}</p>
                  </div>
                ))}
              </div>
            </div>
          </section>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="glass-card">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-white">复核管理</CardTitle>
        <div className="flex gap-2">
          {REVIEW_STATUS_OPTIONS.map((item) => (
            <Button key={item.value} size="sm" variant={statusFilter === item.value ? 'default' : 'outline'} onClick={() => setStatusFilter(item.value)} className={statusFilter === item.value ? 'bg-[#c8f7c5] text-black' : ''}>{item.label}</Button>
          ))}
          <Button variant="outline" size="sm" onClick={() => { void loadReviews(); }}><RefreshCcw className="w-4 h-4 mr-1" />刷新列表</Button>
        </div>
      </CardHeader>
      <CardContent className="grid lg:grid-cols-2 gap-4 h-[70vh] min-h-[560px]">
        <div className="space-y-2 overflow-y-auto pr-1 dashboard-scrollbar">
          {reviewLoading ? <p className="text-sm text-white/70 flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" />正在加载...</p> : null}
          {!reviewLoading && reviewItems.length === 0 ? <p className="text-sm text-white/60">当前筛选下暂无病例</p> : null}
          {reviewItems.map((item) => (
            <button key={item.trace_id} type="button" onClick={() => { void loadReviewDetail(item.trace_id); }} className="w-full text-left rounded-xl border border-white/10 p-3 bg-white/5 hover:border-[#c8f7c5]/40">
              <p className="text-xs text-white/50">病例追踪号</p>
              <p className="text-sm text-white">{item.trace_id.slice(0, 18)}...</p>
              <p className="text-xs text-white/70 mt-1">用户：{item.farmer_name || item.farmer_id || '-'}</p>
              <p className="text-xs text-white/70">系统 top1：{item.top1_disease || '-'}</p>
              <p className="text-xs text-white/70">病例状态：{item.case_status || item.status || '-'}</p>
              <p className="text-xs text-white/70">专家任务：{item.review_task_status || '-'}</p>
              <p className="text-xs text-white/70">管理标签：{item.admin_flag || item.review_flow_status || 'normal'}</p>
              <p className="text-xs text-white/40">更新时间：{formatTime(item.updated_at)}</p>
            </button>
          ))}
        </div>

        <div className="rounded-xl border border-white/10 p-3 bg-white/5 text-sm text-white space-y-3 overflow-y-auto dashboard-scrollbar">
          {!selected ? <p className="text-white/60">请选择左侧病例查看详情</p> : (
            <>
              <p><span className="text-white/50">病例追踪号：</span>{selected.trace_id}</p>
              <p><span className="text-white/50">症状摘要：</span>{selected.symptoms_text || '-'}</p>
              <p><span className="text-white/50">当前 top1：</span>{selected.top1_disease || '-'}</p>
              <p><span className="text-white/50">病例状态：</span>{selected.case_status || selected.status || '-'}</p>
              <p><span className="text-white/50">专家任务：</span>{selected.review_task_status || '-'}</p>
              <p><span className="text-white/50">管理标签：</span>{selected.admin_flag || selected.review_flow_status || 'normal'}</p>
              <p><span className="text-white/50">复核结果：</span>{selected.expert_review_result || '-'}</p>
              <p><span className="text-white/50">复核备注：</span>{selected.expert_review_notes || '-'}</p>
              <p><span className="text-white/50">最终置信度：</span>{typeof selected.model_outputs?.final_confidence === 'number' ? `${(selected.model_outputs.final_confidence * 100).toFixed(2)}%` : '-'}</p>

              {showAssignControls ? (
                <div>
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
                <p><span className="text-white/50">已分配专家：</span>{assignedExpertReadonly}</p>
              )}

              <div>
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

              <div>
                <Label>管理备注</Label>
                <Textarea value={flowNote} onChange={(e) => setFlowNote(e.target.value)} className="bg-white/5 border-white/20 text-white" />
              </div>

              {reviewTip ? <p className="text-[#c8f7c5] text-xs">{reviewTip}</p> : null}

              <div className="flex gap-2">
                {showAssignControls ? (
                  <Button onClick={() => { void assignExpert(); }} disabled={updatingReview || !assignExpertId.trim()} className="bg-[#c8f7c5] text-black">分配复核任务</Button>
                ) : null}
                <Button variant="outline" onClick={() => { void updateFlowStatus(); }} disabled={updatingReview}>保存管理标签</Button>
              </div>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
