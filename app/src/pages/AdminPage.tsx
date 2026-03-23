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
  };
  model_fusion: {
    enable_image_model: boolean;
    enable_text_model: boolean;
    text_backend: 'auto' | 'bert' | 'rule';
    image_reliable_threshold: number;
    text_reliable_threshold: number;
    conflict_margin: number;
    need_confirm_threshold: number;
  };
  llm: {
    enable_llm: boolean;
    enable_treatment_generation: boolean;
    enable_constraint_validation: boolean;
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

const DEFAULT_CONFIG: AdminConfig = {
  workflow: {
    confirm_round_limit: 1,
    validator_rewrite_limit: 1,
  },
  model_fusion: {
    enable_image_model: true,
    enable_text_model: true,
    text_backend: 'auto',
    image_reliable_threshold: 0.7,
    text_reliable_threshold: 0.45,
    conflict_margin: 0.1,
    need_confirm_threshold: 0.6,
  },
  llm: {
    enable_llm: true,
    enable_treatment_generation: true,
    enable_constraint_validation: true,
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

export function AdminPage({ pageType }: { pageType: 'system' | 'review' }) {
  const [config, setConfig] = useState<AdminConfig>(DEFAULT_CONFIG);
  const [configLoading, setConfigLoading] = useState(false);
  const [configSaving, setConfigSaving] = useState(false);
  const [configTip, setConfigTip] = useState<string>('');

  const [statusFilter, setStatusFilter] = useState<(typeof REVIEW_STATUS_OPTIONS)[number]['value']>('pending');
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([]);
  const [selected, setSelected] = useState<ReviewDetail | null>(null);
  const [assignExpertId, setAssignExpertId] = useState('');
  const [flowStatus, setFlowStatus] = useState<'normal' | 'abnormal' | 'closed'>('normal');
  const [flowNote, setFlowNote] = useState('');
  const [reviewTip, setReviewTip] = useState<string>('');
  const [updatingReview, setUpdatingReview] = useState(false);

  const loadConfig = async () => {
    setConfigLoading(true);
    setConfigTip('');
    try {
      const resp = await fetch('/api/admin/system-config');
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '加载配置失败'));
      const raw = (data?.config || DEFAULT_CONFIG) as Record<string, unknown>;
      setConfig({
        workflow: {
          confirm_round_limit: Number((raw.workflow as Record<string, unknown>)?.confirm_round_limit ?? DEFAULT_CONFIG.workflow.confirm_round_limit),
          validator_rewrite_limit: Number((raw.workflow as Record<string, unknown>)?.validator_rewrite_limit ?? DEFAULT_CONFIG.workflow.validator_rewrite_limit),
        },
        model_fusion: {
          enable_image_model: Boolean((raw.model_fusion as Record<string, unknown>)?.enable_image_model),
          enable_text_model: Boolean((raw.model_fusion as Record<string, unknown>)?.enable_text_model),
          text_backend: (((raw.model_fusion as Record<string, unknown>)?.text_backend as 'auto' | 'bert' | 'rule') || 'auto'),
          image_reliable_threshold: Number((raw.model_fusion as Record<string, unknown>)?.image_reliable_threshold ?? 0.7),
          text_reliable_threshold: Number((raw.model_fusion as Record<string, unknown>)?.text_reliable_threshold ?? 0.45),
          conflict_margin: Number((raw.model_fusion as Record<string, unknown>)?.conflict_margin ?? 0.1),
          need_confirm_threshold: Number((raw.model_fusion as Record<string, unknown>)?.need_confirm_threshold ?? 0.6),
        },
        llm: {
          enable_llm: Boolean((raw.llm as Record<string, unknown>)?.enable_llm),
          enable_treatment_generation: Boolean((raw.llm as Record<string, unknown>)?.enable_treatment_generation),
          enable_constraint_validation: Boolean((raw.llm as Record<string, unknown>)?.enable_constraint_validation),
        },
      });
    } catch (error) {
      console.error(error);
      setConfigTip('加载配置失败，请稍后重试。');
    } finally {
      setConfigLoading(false);
    }
  };

  const saveConfig = async () => {
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

  const loadReviewDetail = async (traceId: string) => {
    setReviewTip('');
    try {
      const resp = await fetch(`/api/admin/reviews/${encodeURIComponent(traceId)}`);
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '加载病例详情失败'));
      const item = (data?.item || null) as ReviewDetail | null;
      setSelected(item);
      setAssignExpertId(item?.assigned_expert_id || '');
      setFlowStatus(item?.review_flow_status || 'normal');
      setFlowNote(item?.review_flow_note || '');
    } catch (error) {
      console.error(error);
      setSelected(null);
      setReviewTip('加载病例详情失败。');
    }
  };

  const assignExpert = async () => {
    if (!selected?.trace_id || !assignExpertId.trim()) return;
    setUpdatingReview(true);
    setReviewTip('');
    try {
      const resp = await fetch(`/api/admin/reviews/${encodeURIComponent(selected.trace_id)}/assign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ assigned_expert_id: assignExpertId.trim(), review_flow_note: flowNote }),
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
        body: JSON.stringify({ review_flow_status: flowStatus, review_flow_note: flowNote }),
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
    }
  }, [pageType, statusFilter]);

  const configSummary = useMemo(() => {
    return `补充诊断轮次上限 ${config.workflow.confirm_round_limit} · 最大重写次数 ${config.workflow.validator_rewrite_limit} · 文本后端 ${config.model_fusion.text_backend}`;
  }, [config]);

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
            <Button size="sm" className="bg-[#c8f7c5] text-black" onClick={() => { void saveConfig(); }} disabled={configSaving}>
              <Save className="w-4 h-4 mr-1" />{configSaving ? '保存中...' : '保存配置'}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-5 text-white">
          {configLoading ? <p className="text-sm text-white/70 flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" />正在加载配置...</p> : null}
          {configTip ? <p className="text-sm text-[#c8f7c5]">{configTip}</p> : null}

          <section className="grid md:grid-cols-2 gap-4 rounded-xl border border-white/10 p-3">
            <h3 className="md:col-span-2 font-semibold text-[#c8f7c5]">流程参数</h3>
            <div>
              <Label>补充诊断轮次上限</Label>
              <Input type="number" value={config.workflow.confirm_round_limit} onChange={(e) => setConfig((prev) => ({ ...prev, workflow: { ...prev.workflow, confirm_round_limit: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" />
            </div>
            <div>
              <Label>校验智能体最大重写次数</Label>
              <Input type="number" value={config.workflow.validator_rewrite_limit} onChange={(e) => setConfig((prev) => ({ ...prev, workflow: { ...prev.workflow, validator_rewrite_limit: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" />
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
              <Label>图像可靠性阈值</Label>
              <Input type="number" step="0.01" value={config.model_fusion.image_reliable_threshold} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, image_reliable_threshold: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" />
            </div>
            <div>
              <Label>文本可靠性阈值</Label>
              <Input type="number" step="0.01" value={config.model_fusion.text_reliable_threshold} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, text_reliable_threshold: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" />
            </div>
            <div>
              <Label>冲突判定阈值</Label>
              <Input type="number" step="0.01" value={config.model_fusion.conflict_margin} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, conflict_margin: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" />
            </div>
            <div>
              <Label>低置信度阈值</Label>
              <Input type="number" step="0.01" value={config.model_fusion.need_confirm_threshold} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, need_confirm_threshold: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" />
            </div>
          </section>

          <section className="grid md:grid-cols-3 gap-4 rounded-xl border border-white/10 p-3">
            <h3 className="md:col-span-3 font-semibold text-[#c8f7c5]">大语言模型参数</h3>
            <div className="flex items-center justify-between rounded-lg border border-white/10 p-3"><Label>启用大语言模型</Label><Switch checked={config.llm.enable_llm} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, llm: { ...prev.llm, enable_llm: v } }))} /></div>
            <div className="flex items-center justify-between rounded-lg border border-white/10 p-3"><Label>启用治疗建议生成</Label><Switch checked={config.llm.enable_treatment_generation} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, llm: { ...prev.llm, enable_treatment_generation: v } }))} /></div>
            <div className="flex items-center justify-between rounded-lg border border-white/10 p-3"><Label>启用约束校验</Label><Switch checked={config.llm.enable_constraint_validation} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, llm: { ...prev.llm, enable_constraint_validation: v } }))} /></div>
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
      <CardContent className="grid lg:grid-cols-2 gap-4">
        <div className="space-y-2">
          {reviewLoading ? <p className="text-sm text-white/70 flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" />正在加载...</p> : null}
          {!reviewLoading && reviewItems.length === 0 ? <p className="text-sm text-white/60">当前筛选下暂无病例</p> : null}
          {reviewItems.map((item) => (
            <button key={item.trace_id} type="button" onClick={() => { void loadReviewDetail(item.trace_id); }} className="w-full text-left rounded-xl border border-white/10 p-3 bg-white/5 hover:border-[#c8f7c5]/40">
              <p className="text-xs text-white/50">病例追踪号</p>
              <p className="text-sm text-white">{item.trace_id.slice(0, 18)}...</p>
              <p className="text-xs text-white/70 mt-1">用户：{item.farmer_name || item.farmer_id || '-'}</p>
              <p className="text-xs text-white/70">系统 top1：{item.top1_disease || '-'}</p>
              <p className="text-xs text-white/70">状态：{item.status || '-'} / {item.expert_review_status || '-'} / {item.review_flow_status || 'normal'}</p>
              <p className="text-xs text-white/40">更新时间：{formatTime(item.updated_at)}</p>
            </button>
          ))}
        </div>

        <div className="rounded-xl border border-white/10 p-3 bg-white/5 text-sm text-white space-y-3">
          {!selected ? <p className="text-white/60">请选择左侧病例查看详情</p> : (
            <>
              <p><span className="text-white/50">病例追踪号：</span>{selected.trace_id}</p>
              <p><span className="text-white/50">症状摘要：</span>{selected.symptoms_text || '-'}</p>
              <p><span className="text-white/50">当前 top1：</span>{selected.top1_disease || '-'}</p>
              <p><span className="text-white/50">复核结果：</span>{selected.expert_review_result || '-'}</p>
              <p><span className="text-white/50">复核备注：</span>{selected.expert_review_notes || '-'}</p>
              <p><span className="text-white/50">最终置信度：</span>{typeof selected.model_outputs?.final_confidence === 'number' ? `${(selected.model_outputs.final_confidence * 100).toFixed(2)}%` : '-'}</p>

              <div>
                <Label>分配专家账号</Label>
                <Input value={assignExpertId} onChange={(e) => setAssignExpertId(e.target.value)} className="bg-white/5 border-white/20 text-white" placeholder="例如 EXPERT_001" />
              </div>

              <div>
                <Label>复核流程状态</Label>
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
                <Label>干预备注</Label>
                <Textarea value={flowNote} onChange={(e) => setFlowNote(e.target.value)} className="bg-white/5 border-white/20 text-white" />
              </div>

              {reviewTip ? <p className="text-[#c8f7c5] text-xs">{reviewTip}</p> : null}

              <div className="flex gap-2">
                <Button onClick={() => { void assignExpert(); }} disabled={updatingReview || !assignExpertId.trim()} className="bg-[#c8f7c5] text-black">分配复核任务</Button>
                <Button variant="outline" onClick={() => { void updateFlowStatus(); }} disabled={updatingReview}>更新流程状态</Button>
              </div>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
