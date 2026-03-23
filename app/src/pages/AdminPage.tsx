import { useEffect, useMemo, useState } from 'react';
import { Loader2, RefreshCcw, Save } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
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
    modality_conflict_flag?: boolean;
  };
  expert_review_result?: string;
  expert_review_notes?: string;
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

const REVIEW_STATUSES = ['pending', 'assigned', 'completed'] as const;

function formatTime(v?: string) {
  if (!v) return '-';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return v;
  return d.toLocaleString();
}

export function AdminPage({ defaultTab = 'system-config' }: { defaultTab?: 'system-config' | 'review-management' }) {
  const [activeTab, setActiveTab] = useState<'system-config' | 'review-management'>(defaultTab);
  const [config, setConfig] = useState<AdminConfig>(DEFAULT_CONFIG);
  const [configLoading, setConfigLoading] = useState(false);
  const [configSaving, setConfigSaving] = useState(false);

  const [statusFilter, setStatusFilter] = useState<(typeof REVIEW_STATUSES)[number]>('pending');
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([]);
  const [selected, setSelected] = useState<ReviewDetail | null>(null);
  const [assignExpertId, setAssignExpertId] = useState('');
  const [flowStatus, setFlowStatus] = useState<'normal' | 'abnormal' | 'closed'>('normal');
  const [flowNote, setFlowNote] = useState('');
  const [updatingReview, setUpdatingReview] = useState(false);

  const loadConfig = async () => {
    setConfigLoading(true);
    try {
      const resp = await fetch('/api/admin/system-config');
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '加载配置失败'));
      setConfig((data?.config || DEFAULT_CONFIG) as AdminConfig);
    } catch (error) {
      console.error(error);
      setConfig(DEFAULT_CONFIG);
    } finally {
      setConfigLoading(false);
    }
  };

  const saveConfig = async () => {
    setConfigSaving(true);
    try {
      const resp = await fetch('/api/admin/system-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '保存配置失败'));
      setConfig((data?.config || config) as AdminConfig);
    } catch (error) {
      console.error(error);
    } finally {
      setConfigSaving(false);
    }
  };

  const loadReviews = async () => {
    setReviewLoading(true);
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
    } finally {
      setReviewLoading(false);
    }
  };

  const loadReviewDetail = async (traceId: string) => {
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
    }
  };

  const assignExpert = async () => {
    if (!selected?.trace_id || !assignExpertId.trim()) return;
    setUpdatingReview(true);
    try {
      const resp = await fetch(`/api/admin/reviews/${encodeURIComponent(selected.trace_id)}/assign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ assigned_expert_id: assignExpertId.trim(), review_flow_note: flowNote }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '分配失败'));
      await loadReviewDetail(selected.trace_id);
      await loadReviews();
    } catch (error) {
      console.error(error);
    } finally {
      setUpdatingReview(false);
    }
  };

  const updateFlowStatus = async () => {
    if (!selected?.trace_id) return;
    setUpdatingReview(true);
    try {
      const resp = await fetch(`/api/admin/reviews/${encodeURIComponent(selected.trace_id)}/flow-status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ review_flow_status: flowStatus, review_flow_note: flowNote }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '更新流程状态失败'));
      await loadReviewDetail(selected.trace_id);
      await loadReviews();
    } catch (error) {
      console.error(error);
    } finally {
      setUpdatingReview(false);
    }
  };

  useEffect(() => {
    setActiveTab(defaultTab);
  }, [defaultTab]);

  useEffect(() => {
    void loadConfig();
  }, []);

  useEffect(() => {
    if (activeTab === 'review-management') {
      void loadReviews();
    }
  }, [activeTab, statusFilter]);

  const configSummary = useMemo(() => {
    return [
      `confirm_round_limit=${config.workflow.confirm_round_limit}`,
      `validator_rewrite_limit=${config.workflow.validator_rewrite_limit}`,
      `text_backend=${config.model_fusion.text_backend}`,
      `need_confirm_threshold=${config.model_fusion.need_confirm_threshold}`,
    ].join(' · ');
  }, [config]);

  return (
    <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as 'system-config' | 'review-management')} className="space-y-4">
      <TabsList className="bg-white/5 border border-white/10">
        <TabsTrigger value="system-config">系统配置</TabsTrigger>
        <TabsTrigger value="review-management">复核管理</TabsTrigger>
      </TabsList>

      <TabsContent value="system-config" className="space-y-4">
        <Card className="glass-card">
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle className="text-white">管理员系统配置</CardTitle>
              <p className="text-xs text-white/60 mt-1">{configSummary}</p>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => { void loadConfig(); }}>
                <RefreshCcw className="w-4 h-4 mr-1" />刷新
              </Button>
              <Button size="sm" className="bg-[#c8f7c5] text-black" onClick={() => { void saveConfig(); }} disabled={configSaving}>
                <Save className="w-4 h-4 mr-1" />{configSaving ? '保存中...' : '保存配置'}
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-5 text-white">
            {configLoading ? <p className="text-sm text-white/70 flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" />加载配置中...</p> : null}

            <section className="grid md:grid-cols-2 gap-4 rounded-xl border border-white/10 p-3">
              <h3 className="md:col-span-2 font-semibold text-[#c8f7c5]">A. 工作流</h3>
              <div>
                <Label>confirm_round_limit</Label>
                <Input type="number" value={config.workflow.confirm_round_limit} onChange={(e) => setConfig((prev) => ({ ...prev, workflow: { ...prev.workflow, confirm_round_limit: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" />
              </div>
              <div>
                <Label>validator_rewrite_limit</Label>
                <Input type="number" value={config.workflow.validator_rewrite_limit} onChange={(e) => setConfig((prev) => ({ ...prev, workflow: { ...prev.workflow, validator_rewrite_limit: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" />
              </div>
              <div className="flex items-center justify-between rounded-lg border border-white/10 p-3">
                <Label>enable_validator_agent</Label><Switch checked={config.workflow.enable_validator_agent} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, workflow: { ...prev.workflow, enable_validator_agent: v } }))} />
              </div>
              <div className="flex items-center justify-between rounded-lg border border-white/10 p-3">
                <Label>enable_personalization_agent</Label><Switch checked={config.workflow.enable_personalization_agent} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, workflow: { ...prev.workflow, enable_personalization_agent: v } }))} />
              </div>
            </section>

            <section className="grid md:grid-cols-2 gap-4 rounded-xl border border-white/10 p-3">
              <h3 className="md:col-span-2 font-semibold text-[#c8f7c5]">B. 模型与融合</h3>
              <div className="flex items-center justify-between rounded-lg border border-white/10 p-3">
                <Label>enable_image_model</Label><Switch checked={config.model_fusion.enable_image_model} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, enable_image_model: v } }))} />
              </div>
              <div className="flex items-center justify-between rounded-lg border border-white/10 p-3">
                <Label>enable_text_model</Label><Switch checked={config.model_fusion.enable_text_model} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, enable_text_model: v } }))} />
              </div>
              <div>
                <Label>text_backend</Label>
                <Select value={config.model_fusion.text_backend} onValueChange={(v) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, text_backend: v as 'auto' | 'bert' | 'rule' } }))}>
                  <SelectTrigger className="bg-white/5 border-white/20 text-white"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="auto">auto</SelectItem>
                    <SelectItem value="bert">bert</SelectItem>
                    <SelectItem value="rule">rule</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>image_reliable_threshold</Label>
                <Input type="number" step="0.01" value={config.model_fusion.image_reliable_threshold} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, image_reliable_threshold: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" />
              </div>
              <div>
                <Label>text_reliable_threshold</Label>
                <Input type="number" step="0.01" value={config.model_fusion.text_reliable_threshold} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, text_reliable_threshold: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" />
              </div>
              <div>
                <Label>conflict_margin</Label>
                <Input type="number" step="0.01" value={config.model_fusion.conflict_margin} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, conflict_margin: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" />
              </div>
              <div>
                <Label>need_confirm_threshold</Label>
                <Input type="number" step="0.01" value={config.model_fusion.need_confirm_threshold} onChange={(e) => setConfig((prev) => ({ ...prev, model_fusion: { ...prev.model_fusion, need_confirm_threshold: Number(e.target.value || 0) } }))} className="bg-white/5 border-white/20 text-white" />
              </div>
            </section>

            <section className="grid md:grid-cols-3 gap-4 rounded-xl border border-white/10 p-3">
              <h3 className="md:col-span-3 font-semibold text-[#c8f7c5]">C. LLM</h3>
              <div className="flex items-center justify-between rounded-lg border border-white/10 p-3"><Label>enable_llm</Label><Switch checked={config.llm.enable_llm} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, llm: { ...prev.llm, enable_llm: v } }))} /></div>
              <div className="flex items-center justify-between rounded-lg border border-white/10 p-3"><Label>enable_treatment_generation</Label><Switch checked={config.llm.enable_treatment_generation} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, llm: { ...prev.llm, enable_treatment_generation: v } }))} /></div>
              <div className="flex items-center justify-between rounded-lg border border-white/10 p-3"><Label>enable_constraint_validation</Label><Switch checked={config.llm.enable_constraint_validation} onCheckedChange={(v) => setConfig((prev) => ({ ...prev, llm: { ...prev.llm, enable_constraint_validation: v } }))} /></div>
            </section>
          </CardContent>
        </Card>
      </TabsContent>

      <TabsContent value="review-management" className="space-y-4">
        <Card className="glass-card">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-white">管理员复核管理</CardTitle>
            <div className="flex gap-2">
              {REVIEW_STATUSES.map((status) => (
                <Button key={status} size="sm" variant={statusFilter === status ? 'default' : 'outline'} onClick={() => setStatusFilter(status)} className={statusFilter === status ? 'bg-[#c8f7c5] text-black' : ''}>{status}</Button>
              ))}
              <Button variant="outline" size="sm" onClick={() => { void loadReviews(); }}><RefreshCcw className="w-4 h-4 mr-1" />刷新</Button>
            </div>
          </CardHeader>
          <CardContent className="grid lg:grid-cols-2 gap-4">
            <div className="space-y-2">
              {reviewLoading ? <p className="text-sm text-white/70 flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" />加载中...</p> : null}
              {!reviewLoading && reviewItems.length === 0 ? <p className="text-sm text-white/60">暂无该状态病例</p> : null}
              {reviewItems.map((item) => (
                <button key={item.trace_id} type="button" onClick={() => { void loadReviewDetail(item.trace_id); }} className="w-full text-left rounded-xl border border-white/10 p-3 bg-white/5 hover:border-[#c8f7c5]/40">
                  <p className="text-xs text-white/50">trace_id</p>
                  <p className="text-sm text-white">{item.trace_id.slice(0, 18)}...</p>
                  <p className="text-xs text-white/70 mt-1">用户：{item.farmer_name || item.farmer_id || '-'} · top1：{item.top1_disease || '-'}</p>
                  <p className="text-xs text-white/70">状态：{item.status || '-'} / {item.expert_review_status || '-'} / {item.review_flow_status || 'normal'}</p>
                  <p className="text-xs text-white/40">更新时间：{formatTime(item.updated_at)}</p>
                </button>
              ))}
            </div>

            <div className="rounded-xl border border-white/10 p-3 bg-white/5 text-sm text-white space-y-3">
              {!selected ? <p className="text-white/60">请选择左侧病例查看详情</p> : (
                <>
                  <p><span className="text-white/50">trace_id：</span>{selected.trace_id}</p>
                  <p><span className="text-white/50">症状：</span>{selected.symptoms_text || '-'}</p>
                  <p><span className="text-white/50">当前top1：</span>{selected.top1_disease || '-'}</p>
                  <p><span className="text-white/50">复核结果：</span>{selected.expert_review_result || '-'}</p>
                  <p><span className="text-white/50">专家备注：</span>{selected.expert_review_notes || '-'}</p>
                  <p><span className="text-white/50">final_confidence：</span>{typeof selected.model_outputs?.final_confidence === 'number' ? `${(selected.model_outputs.final_confidence * 100).toFixed(2)}%` : '-'}</p>

                  <div>
                    <Label>分配专家 assigned_expert_id</Label>
                    <Input value={assignExpertId} onChange={(e) => setAssignExpertId(e.target.value)} className="bg-white/5 border-white/20 text-white" placeholder="例如 EXPERT_001" />
                  </div>

                  <div>
                    <Label>review_flow_status</Label>
                    <Select value={flowStatus} onValueChange={(v) => setFlowStatus(v as 'normal' | 'abnormal' | 'closed')}>
                      <SelectTrigger className="bg-white/5 border-white/20 text-white"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="normal">normal</SelectItem>
                        <SelectItem value="abnormal">abnormal</SelectItem>
                        <SelectItem value="closed">closed</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div>
                    <Label>备注</Label>
                    <Textarea value={flowNote} onChange={(e) => setFlowNote(e.target.value)} className="bg-white/5 border-white/20 text-white" />
                  </div>

                  <div className="flex gap-2">
                    <Button onClick={() => { void assignExpert(); }} disabled={updatingReview || !assignExpertId.trim()} className="bg-[#c8f7c5] text-black">分配任务</Button>
                    <Button variant="outline" onClick={() => { void updateFlowStatus(); }} disabled={updatingReview}>更新流程状态</Button>
                  </div>
                </>
              )}
            </div>
          </CardContent>
        </Card>
      </TabsContent>
    </Tabs>
  );
}
