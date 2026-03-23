import { useEffect, useMemo, useState } from 'react';
import { Bell, Eye, Loader2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';

interface PendingCaseItem {
  trace_id: string;
  case_id?: string;
  submitted_at?: string;
  farmer_id?: string;
  farmer_name?: string;
  top1_disease?: string;
  status?: string;
  expert_review_status?: string;
  assigned_expert_id?: string;
}

interface ReviewCaseDetail extends PendingCaseItem {
  image_url?: string;
  symptoms?: string[];
  symptoms_text?: string;
  crop_type?: string;
  growth_stage?: string;
  base_id?: string;
  base_name?: string;
  environment?: string;
  profile_summary?: {
    farm_scale?: string;
    pesticide_access_level?: string;
    equipment?: string[];
    cultivation_mode?: string;
  };
  model_outputs?: {
    image_top3?: [string, number][];
    text_top3?: [string, number][];
    fusion_top3?: [string, number][];
    final_confidence?: number;
    modality_conflict_flag?: boolean;
  };
  expert_review_result?: string;
  expert_review_supplement_symptoms?: string;
  expert_review_notes?: string;
  expert_reviewed_at?: string;
}

function formatProb(value: number | undefined): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '-';
  return `${(value <= 1 ? value * 100 : value).toFixed(2)}%`;
}

function formatTime(value?: string): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export function ExpertReviewPage() {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<PendingCaseItem[]>([]);
  const [selectedTraceId, setSelectedTraceId] = useState<string>('');
  const [detailLoading, setDetailLoading] = useState(false);
  const [detail, setDetail] = useState<ReviewCaseDetail | null>(null);
  const [open, setOpen] = useState(false);
  const [submitLoading, setSubmitLoading] = useState(false);
  const [form, setForm] = useState({
    expert_review_result: '',
    expert_review_supplement_symptoms: '',
    expert_review_notes: '',
  });

  const pendingCount = items.length;

  const loadPending = async () => {
    setLoading(true);
    try {
      const resp = await fetch('/api/expert-reviews/pending?limit=30');
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '加载待复核列表失败'));
      const nextItems = Array.isArray(data?.items) ? data.items as PendingCaseItem[] : [];
      nextItems.sort((a, b) => new Date(b.submitted_at || 0).getTime() - new Date(a.submitted_at || 0).getTime());
      setItems(nextItems);
    } catch (error) {
      console.error(error);
      setItems([]);
    } finally {
      setLoading(false);
    }
  };

  const loadDetail = async (traceId: string) => {
    setSelectedTraceId(traceId);
    setDetailLoading(true);
    try {
      const resp = await fetch(`/api/expert-reviews/${encodeURIComponent(traceId)}`);
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '加载病例详情失败'));
      const item = (data?.item || null) as ReviewCaseDetail | null;
      setDetail(item);
      setForm({
        expert_review_result: item?.expert_review_result || item?.top1_disease || '',
        expert_review_supplement_symptoms: item?.expert_review_supplement_symptoms || '',
        expert_review_notes: item?.expert_review_notes || '',
      });
      setOpen(true);
    } catch (error) {
      console.error(error);
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const submitReview = async () => {
    if (!selectedTraceId || !form.expert_review_result.trim()) return;
    setSubmitLoading(true);
    try {
      const resp = await fetch(`/api/expert-reviews/${encodeURIComponent(selectedTraceId)}/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '提交复核失败'));
      setOpen(false);
      await loadPending();
    } catch (error) {
      console.error(error);
    } finally {
      setSubmitLoading(false);
    }
  };

  useEffect(() => {
    void loadPending();
  }, []);

  const recentPending = useMemo(() => items.slice(0, 5), [items]);
  const getReviewTag = (item: PendingCaseItem) => {
    if (item.expert_review_status === 'COMPLETED' || item.status === 'completed') {
      return <Badge className="bg-emerald-400 text-black">已复核</Badge>;
    }
    return <Badge className="bg-orange-400 text-black">待复核</Badge>;
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white">专家复核区</h1>
          <p className="text-sm text-white/60 mt-1">最小闭环：待复核列表 → 详情查看 → 提交专家确认</p>
        </div>
        <div className="rounded-xl border border-white/20 bg-white/5 p-4 min-w-72">
          <div className="flex items-center gap-2 text-white mb-2">
            <Bell className="w-4 h-4 text-[#c8f7c5]" />
            <span className="font-medium">待复核提醒</span>
            <Badge className="bg-[#c8f7c5] text-black">{pendingCount}</Badge>
          </div>
          <div className="space-y-1 text-xs text-white/75">
            {recentPending.length === 0 ? (
              <p>暂无待复核病例</p>
            ) : recentPending.map((item) => (
              <button
                key={item.trace_id}
                type="button"
                className="block w-full text-left hover:text-[#c8f7c5]"
                onClick={() => { void loadDetail(item.trace_id); }}
              >
                {item.trace_id.slice(0, 10)}... · {item.farmer_name || item.farmer_id || '未知用户'}
              </button>
            ))}
          </div>
        </div>
      </div>

      <Card className="glass-card">
        <CardHeader>
          <CardTitle className="text-white">待复核病例列表</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="text-white/70 text-sm flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" />加载中...</div>
          ) : items.length === 0 ? (
            <p className="text-white/60 text-sm">暂无 pending_expert_review 病例</p>
          ) : (
            <div className="space-y-3">
              {items.map((item) => (
                <div key={item.trace_id} className="rounded-xl border border-white/10 bg-white/5 hover:bg-white/[0.07] p-3 grid md:grid-cols-6 gap-2 text-sm text-white/85">
                  <div>
                    <p className="text-white/50 text-xs">trace_id</p>
                    <p>{item.trace_id.slice(0, 16)}...</p>
                  </div>
                  <div>
                    <p className="text-white/50 text-xs">用户/农户</p>
                    <p>{item.farmer_name || item.farmer_id || '-'}</p>
                  </div>
                  <div>
                    <p className="text-white/50 text-xs">提交时间</p>
                    <p>{formatTime(item.submitted_at)}</p>
                  </div>
                  <div>
                    <p className="text-white/50 text-xs">系统 top1</p>
                    <p>{item.top1_disease || '-'}</p>
                  </div>
                  <div>
                    <p className="text-white/50 text-xs">当前状态</p>
                    <div className="flex items-center gap-2">
                      {getReviewTag(item)}
                      <span className="text-xs text-white/70">{item.status || '-'} / {item.expert_review_status || '-'}</span>
                    </div>
                  </div>
                  <div className="flex items-end justify-end">
                    <Button size="sm" variant="outline" className="border-[#c8f7c5]/60 text-[#c8f7c5]" onClick={() => { void loadDetail(item.trace_id); }}>
                      <Eye className="w-4 h-4 mr-1" />详情
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto bg-[#0f1614] border-[#86b89d]/30 text-white">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              专家复核详情
              {detail ? getReviewTag(detail) : null}
            </DialogTitle>
          </DialogHeader>
          {!detail || detailLoading ? (
            <div className="text-sm text-white/70">加载中...</div>
          ) : (
            <div className="space-y-4 text-sm">
              <section className="rounded-xl border border-[#86b89d]/20 bg-[#13221c] p-3 space-y-2">
                <h3 className="text-[#c8f7c5] font-semibold">A. 用户输入</h3>
                {detail.image_url ? <img src={detail.image_url} alt="病例图片" className="max-h-56 rounded-lg object-contain bg-black/30" /> : null}
                <p>症状文本：{detail.symptoms_text || '-'}</p>
                <p>生育期：{detail.growth_stage || '-'}</p>
                <p>基地/环境：{detail.base_name || detail.base_id || '-'} / {detail.environment || '-'}</p>
                <p>档案摘要：规模 {detail.profile_summary?.farm_scale || '-'}，购药能力 {detail.profile_summary?.pesticide_access_level || '-'}，设备 {(detail.profile_summary?.equipment || []).join('、') || '-'}</p>
              </section>

              <section className="rounded-xl border border-[#86b89d]/20 bg-[#13221c] p-3 space-y-2">
                <h3 className="text-[#c8f7c5] font-semibold">B. 模型输出</h3>
                <p>image top3：{(detail.model_outputs?.image_top3 || []).map((it) => `${it[0]}(${formatProb(it[1])})`).join('；') || '-'}</p>
                <p>text top3：{(detail.model_outputs?.text_top3 || []).map((it) => `${it[0]}(${formatProb(it[1])})`).join('；') || '-'}</p>
                <p>fusion top3：{(detail.model_outputs?.fusion_top3 || []).map((it) => `${it[0]}(${formatProb(it[1])})`).join('；') || '-'}</p>
                <p>final_confidence：{formatProb(detail.model_outputs?.final_confidence)}</p>
                <p>modality_conflict_flag：{detail.model_outputs?.modality_conflict_flag ? '是' : '否'}</p>
              </section>

              <section className="rounded-xl border border-[#86b89d]/20 bg-[#13221c] p-3 space-y-3">
                <h3 className="text-[#c8f7c5] font-semibold">C. 专家填写</h3>
                <div>
                  <Label>最终确认病害</Label>
                  <Input
                    value={form.expert_review_result}
                    onChange={(e) => setForm((prev) => ({ ...prev, expert_review_result: e.target.value }))}
                    className="bg-white/5 border-white/20 text-white"
                  />
                </div>
                <div>
                  <Label>补充症状</Label>
                  <Input
                    value={form.expert_review_supplement_symptoms}
                    onChange={(e) => setForm((prev) => ({ ...prev, expert_review_supplement_symptoms: e.target.value }))}
                    className="bg-white/5 border-white/20 text-white"
                  />
                </div>
                <div>
                  <Label>复核备注</Label>
                  <Textarea
                    value={form.expert_review_notes}
                    onChange={(e) => setForm((prev) => ({ ...prev, expert_review_notes: e.target.value }))}
                    className="bg-white/5 border-white/20 text-white"
                  />
                </div>
              </section>

              <section className="pt-1">
                <h3 className="text-[#c8f7c5] font-semibold mb-2">D. 提交按钮</h3>
                <Button onClick={() => { void submitReview(); }} disabled={submitLoading || !form.expert_review_result.trim()} className="bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]">
                  {submitLoading ? '提交中...' : '提交复核结果'}
                </Button>
              </section>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
