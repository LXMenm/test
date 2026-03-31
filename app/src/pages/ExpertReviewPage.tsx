import { useEffect, useState, useCallback, useMemo } from 'react';
import { Eye, Loader2, Stethoscope, CheckCircle2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import { authFetch, loadAuthUser } from '@/auth';

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
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  const seconds = String(date.getSeconds()).padStart(2, '0');
  return `${year}/${month}/${day}/${hours}:${minutes}:${seconds}`;
}

export function ExpertReviewPage() {
  const authUser = useMemo(() => loadAuthUser(), []);
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<PendingCaseItem[]>([]);
  const [listError, setListError] = useState<string>('');
  const [selectedTraceId, setSelectedTraceId] = useState<string>('');
  const [detailLoading, setDetailLoading] = useState(false);
  const [detail, setDetail] = useState<ReviewCaseDetail | null>(null);
  const [detailError, setDetailError] = useState<string>('');
  const [open, setOpen] = useState(false);
  const [submitLoading, setSubmitLoading] = useState(false);
  const [form, setForm] = useState({
    expert_review_result: '',
    expert_review_supplement_symptoms: '',
    expert_review_notes: '',
  });

  const pendingCount = items.length;

  const loadPending = useCallback(async () => {
    setLoading(true);
    setListError('');
    try {
      const resp = await authFetch('/api/expert-reviews/pending?limit=30', undefined, authUser);
      const data = await resp.json();
      if (!resp.ok) {
        if (resp.status === 403) {
          throw new Error('当前请求未携带专家身份，或当前账号无专家权限');
        }
        throw new Error(String(data?.detail || '加载待复核列表失败'));
      }
      const nextItems = Array.isArray(data?.items) ? data.items as PendingCaseItem[] : [];
      nextItems.sort((a, b) => new Date(b.submitted_at || 0).getTime() - new Date(a.submitted_at || 0).getTime());
      setItems(nextItems);
    } catch (error) {
      console.error(error);
      setItems([]);
      setListError(error instanceof Error ? error.message : '加载待复核列表失败');
    } finally {
      setLoading(false);
    }
  }, [authUser]);

  const loadDetail = async (traceId: string) => {
    setSelectedTraceId(traceId);
    setDetailLoading(true);
    setDetailError('');
    try {
      const resp = await authFetch(`/api/expert-reviews/${encodeURIComponent(traceId)}`, undefined, authUser);
      const data = await resp.json();
      if (!resp.ok) {
        if (resp.status === 403) {
          throw new Error('当前请求未携带专家身份，或当前账号无专家权限');
        }
        throw new Error(String(data?.detail || '加载病例详情失败'));
      }
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
      setOpen(false);
      setDetailError(error instanceof Error ? error.message : '加载病例详情失败');
    } finally {
      setDetailLoading(false);
    }
  };

  const submitReview = async () => {
    if (!selectedTraceId || !form.expert_review_result.trim()) return;
    setSubmitLoading(true);
    setDetailError('');
    try {
      const resp = await authFetch(`/api/expert-reviews/${encodeURIComponent(selectedTraceId)}/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      }, authUser);
      const data = await resp.json();
      if (!resp.ok) {
        if (resp.status === 403) {
          throw new Error('当前请求未携带专家身份，或当前账号无专家权限');
        }
        throw new Error(String(data?.detail || '提交复核失败'));
      }
      setOpen(false);
      await loadPending();
    } catch (error) {
      console.error(error);
      setDetailError(error instanceof Error ? error.message : '提交复核失败');
    } finally {
      setSubmitLoading(false);
    }
  };

  useEffect(() => {
    void loadPending();
  }, [loadPending]);

  const getReviewTag = (item: PendingCaseItem) => {
    if (item.expert_review_status === 'COMPLETED' || item.status === 'completed') {
      return <Badge className="bg-emerald-400 text-black">已复核</Badge>;
    }
    return <Badge className="bg-orange-400 text-black">待复核</Badge>;
  };

  return (
    <div className="space-y-6 animate-fadeIn">
      <div>
        <h1 className="text-3xl font-bold text-white"><span className="text-[#c8f7c5]">专家复核</span></h1>
        <p className="text-white/60 mt-1">专家对系统诊断结果进行复核确认，确保诊断准确性</p>
      </div>

      <Card className="glass-card">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-white flex items-center gap-2">
            <Stethoscope className="w-5 h-5 text-[#c8f7c5]" />
            待复核病例列表
          </CardTitle>
          {pendingCount > 0 && (
            <Badge className="bg-orange-400/20 text-orange-300 border-orange-400/30 px-3 py-1">
              {pendingCount} 个待处理
            </Badge>
          )}
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-8 h-8 animate-spin text-[#c8f7c5]" />
              <span className="ml-3 text-white/70">加载中...</span>
            </div>
          ) : listError ? (
            <div className="text-center py-12">
              <p className="text-red-300 text-base font-medium">{listError}</p>
            </div>
          ) : items.length === 0 ? (
            <div className="text-center py-16">
              <CheckCircle2 className="w-16 h-16 text-[#c8f7c5]/30 mx-auto mb-4" />
              <h3 className="text-xl text-white/80 mb-2">所有病例已复核完成</h3>
              <p className="text-white/50 text-sm">暂无待复核病例</p>
            </div>
          ) : (
            <div className="space-y-3">
              {items.map((item) => (
                <div key={item.trace_id} className="group rounded-xl border border-white/10 bg-white/5 hover:bg-white/[0.08] p-4 transition-all duration-300 hover:border-[#c8f7c5]/30">
                  <div className="grid grid-cols-1 md:grid-cols-12 gap-4 items-center">
                    <div className="md:col-span-3">
                      <p className="text-white/40 text-xs mb-1 font-mono">trace_id</p>
                      <p className="text-white font-mono text-sm">{item.trace_id.slice(0, 16)}...</p>
                    </div>
                    <div className="md:col-span-2">
                      <p className="text-white/40 text-xs mb-1">用户</p>
                      <p className="text-white font-medium text-sm">{item.farmer_name || item.farmer_id || '-'}</p>
                    </div>
                    <div className="md:col-span-3">
                      <p className="text-white/40 text-xs mb-1">提交时间</p>
                      <p className="text-white text-sm">{formatTime(item.submitted_at)}</p>
                    </div>
                    <div className="md:col-span-2">
                      <p className="text-white/40 text-xs mb-1">系统诊断</p>
                      <p className="text-[#c8f7c5] font-medium text-sm">{item.top1_disease || '-'}</p>
                    </div>
                    <div className="md:col-span-1">
                      {getReviewTag(item)}
                    </div>
                    <div className="md:col-span-1 flex justify-end">
                      <Button 
                        size="sm" 
                        variant="outline" 
                        className="border-[#c8f7c5]/30 text-[#c8f7c5] hover:bg-[#c8f7c5]/10 hover:border-[#c8f7c5] transition-all duration-200"
                        onClick={() => { void loadDetail(item.trace_id); }}
                      >
                        <Eye className="w-4 h-4 mr-1" />
                        详情
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
      {detailError && !open ? (
        <div className="rounded-xl border border-red-300/40 bg-red-500/10 px-4 py-3 text-red-200 text-sm">
          {detailError}
        </div>
      ) : null}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className={cn(
          "!max-w-[85vw] !w-[1000px] max-h-[90vh] overflow-y-auto bg-gradient-to-b from-[#0f1614] to-[#0a120e] border-[#86b89d]/30 text-white shadow-2xl dashboard-scrollbar"
        )}>
          <DialogHeader className="pb-3 border-b border-white/10">
            <DialogTitle className="flex items-center gap-2 text-xl">
              <div className="p-1.5 rounded-lg bg-[#c8f7c5]/10">
                <Stethoscope className="w-5 h-5 text-[#c8f7c5]" />
              </div>
              专家复核详情
              {detail ? getReviewTag(detail) : null}
            </DialogTitle>
          </DialogHeader>
          {!detail || detailLoading ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="w-8 h-8 animate-spin text-[#c8f7c5]" />
              <span className="ml-3 text-white/70 text-base">加载中...</span>
            </div>
          ) : (
            <div className="space-y-4 py-4 px-3">
              <section className="rounded-xl border border-[#86b89d]/20 bg-gradient-to-br from-[#13221c] to-[#0f1a15] p-5 space-y-4">
                <h3 className="text-[#c8f7c5] font-semibold text-lg flex items-center gap-2">
                  <div className="w-1 h-5 bg-[#c8f7c5] rounded-full" />
                  A. 用户输入
                </h3>
                <div className="space-y-3">
                  {detail.image_url && (
                    <div className="rounded-lg overflow-hidden border border-white/10 bg-black/40">
                      <img 
                        src={detail.image_url} 
                        alt="病例图片" 
                        className="w-full max-h-64 object-contain mx-auto" 
                      />
                    </div>
                  )}
                  <div className="space-y-1.5">
                    <p className="text-white/40 text-[10px] uppercase tracking-wider">症状文本</p>
                    <div className="bg-white/5 rounded-lg p-3 min-h-[72px]">
                      <p className="text-white/90 break-words leading-relaxed text-sm">{detail.symptoms_text || '-'}</p>
                    </div>
                  </div>
                  <div className="grid md:grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <p className="text-white/40 text-[10px] uppercase tracking-wider">基地 / 环境</p>
                      <div className="bg-white/5 rounded-lg p-3 min-h-[60px]">
                        <p className="text-white/90 break-words leading-relaxed text-sm">{detail.base_name || detail.base_id || '-'} / {detail.environment || '-'}</p>
                      </div>
                    </div>
                    <div className="space-y-1.5">
                      <p className="text-white/40 text-[10px] uppercase tracking-wider">生育期</p>
                      <div className="bg-white/5 rounded-lg p-3 min-h-[60px]">
                        <p className="text-white/90 text-sm">{detail.growth_stage || '-'}</p>
                      </div>
                    </div>
                  </div>
                </div>
              </section>

              <section className="rounded-xl border border-[#86b89d]/20 bg-gradient-to-br from-[#13221c] to-[#0f1a15] p-5 space-y-4">
                <h3 className="text-[#c8f7c5] font-semibold text-lg flex items-center gap-2">
                  <div className="w-1 h-5 bg-[#c8f7c5] rounded-full" />
                  B. 模型输出
                </h3>
                <div className="grid lg:grid-cols-3 gap-4">
                  <div className="bg-white/5 rounded-lg p-4 border border-white/5">
                    <p className="text-white/40 text-[10px] uppercase tracking-wider mb-3">Image Top 3</p>
                    <div className="space-y-2">
                      {(detail.model_outputs?.image_top3 || []).map((it, idx) => (
                        <div key={idx} className="flex justify-between items-center py-1.5 border-b border-white/5 last:border-0">
                          <span className="text-white/90 font-medium text-sm">{it[0]}</span>
                          <span className="text-[#c8f7c5] font-mono text-base">{formatProb(it[1])}</span>
                        </div>
                      ))}
                      {(detail.model_outputs?.image_top3 || []).length === 0 && (
                        <div className="text-white/40 text-xs py-3">无数据</div>
                      )}
                    </div>
                  </div>
                  <div className="bg-white/5 rounded-lg p-4 border border-white/5">
                    <p className="text-white/40 text-[10px] uppercase tracking-wider mb-3">Text Top 3</p>
                    <div className="space-y-2">
                      {(detail.model_outputs?.text_top3 || []).map((it, idx) => (
                        <div key={idx} className="flex justify-between items-center py-1.5 border-b border-white/5 last:border-0">
                          <span className="text-white/90 font-medium text-sm">{it[0]}</span>
                          <span className="text-[#c8f7c5] font-mono text-base">{formatProb(it[1])}</span>
                        </div>
                      ))}
                      {(detail.model_outputs?.text_top3 || []).length === 0 && (
                        <div className="text-white/40 text-xs py-3">无数据</div>
                      )}
                    </div>
                  </div>
                  <div className="bg-white/5 rounded-lg p-4 border border-white/5">
                    <p className="text-white/40 text-[10px] uppercase tracking-wider mb-3">Fusion Top 3</p>
                    <div className="space-y-2">
                      {(detail.model_outputs?.fusion_top3 || []).map((it, idx) => (
                        <div key={idx} className="flex justify-between items-center py-1.5 border-b border-white/5 last:border-0">
                          <span className="text-white/90 font-medium text-sm">{it[0]}</span>
                          <span className="text-[#c8f7c5] font-mono text-base font-bold">{formatProb(it[1])}</span>
                        </div>
                      ))}
                      {(detail.model_outputs?.fusion_top3 || []).length === 0 && (
                        <div className="text-white/40 text-xs py-3">无数据</div>
                      )}
                    </div>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="bg-white/5 rounded-lg p-4 border border-white/5 text-center">
                    <p className="text-white/40 text-[10px] uppercase tracking-wider mb-2">最终置信度</p>
                    <p className="text-3xl font-bold text-[#c8f7c5]">{formatProb(detail.model_outputs?.final_confidence)}</p>
                  </div>
                  <div className="bg-white/5 rounded-lg p-4 border border-white/5 text-center">
                    <p className="text-white/40 text-[10px] uppercase tracking-wider mb-2">图文冲突</p>
                    <p className={`text-2xl font-bold ${detail.model_outputs?.modality_conflict_flag ? 'text-orange-400' : 'text-emerald-400'}`}>
                      {detail.model_outputs?.modality_conflict_flag ? '是' : '否'}
                    </p>
                  </div>
                </div>
              </section>

              <section className="rounded-xl border border-[#86b89d]/20 bg-gradient-to-br from-[#13221c] to-[#0f1a15] p-5 space-y-4">
                <h3 className="text-[#c8f7c5] font-semibold text-lg flex items-center gap-2">
                  <div className="w-1 h-5 bg-[#c8f7c5] rounded-full" />
                  C. 专家填写
                </h3>
                <div className="space-y-3">
                  <div>
                    <Label className="text-white/70 mb-2 block text-xs uppercase tracking-wider">最终确认病害</Label>
                    <Input
                      value={form.expert_review_result}
                      onChange={(e) => setForm((prev) => ({ ...prev, expert_review_result: e.target.value }))}
                      className="bg-white/5 border-white/20 text-white focus:border-[#c8f7c5] focus:ring-[#c8f7c5]/20 h-11 text-base"
                      placeholder="请输入最终确认的病害名称"
                    />
                  </div>
                  <div>
                    <Label className="text-white/70 mb-2 block text-xs uppercase tracking-wider">复核备注</Label>
                    <Textarea
                      value={form.expert_review_notes}
                      onChange={(e) => setForm((prev) => ({ ...prev, expert_review_notes: e.target.value }))}
                      className="bg-white/5 border-white/20 text-white focus:border-[#c8f7c5] focus:ring-[#c8f7c5]/20 min-h-[110px] text-base resize-none"
                      placeholder="请输入复核备注"
                    />
                  </div>
                </div>
              </section>

              <section className="pt-3">
                {detailError ? (
                  <div className="rounded-lg border border-red-300/40 bg-red-500/10 px-3 py-2 text-red-200 text-xs">
                    {detailError}
                  </div>
                ) : null}
                <div className="flex justify-end">
                  <Button 
                    onClick={() => { void submitReview(); }} 
                    disabled={submitLoading || !form.expert_review_result.trim()} 
                    className="bg-gradient-to-r from-[#c8f7c5] to-[#9ed8bf] text-black hover:from-[#b8e7b5] hover:to-[#8ec8af] px-6 py-5 text-base font-semibold shadow-lg shadow-[#c8f7c5]/25 transition-all duration-300 rounded-lg"
                  >
                    {submitLoading ? (
                      <><Loader2 className="w-4 h-4 animate-spin mr-2" />提交中...</>
                    ) : (
                      <><CheckCircle2 className="w-4 h-4 mr-2" />提交复核结果</>
                    )}
                  </Button>
                </div>
              </section>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
