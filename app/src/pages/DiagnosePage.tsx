import { useState, useRef } from 'react';
import { Upload, Send, RefreshCw, AlertCircle, CheckCircle, Loader2, Image as ImageIcon, ChevronDown, ChevronUp } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { cn } from '@/lib/utils';
import { AgentWorkflowPanel } from '@/components/AgentWorkflowPanel';

interface DiagnosisResult {
  image_url: string;
  final_disease: string;
  displayConfidencePct: number | null;
  model_display_name: string;
  top3: Array<{ disease: string; confidence: number }>;
  treatment: unknown;
  prevention: unknown;
  trace_id: string;
}

interface TraceEvent {
  timestamp: string;
  agent: string;
  status: string;
  message?: string;
}

export function DiagnosePage() {
  const [file, setFile] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string>('');
  const [symptoms, setSymptoms] = useState('');
  const [cropType, setCropType] = useState('番茄');
  const [growthStage, setGrowthStage] = useState('');
  const [modelId, setModelId] = useState('default');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<DiagnosisResult | null>(null);
  const [traceEvents, setTraceEvents] = useState<TraceEvent[]>([]);
  const [traceId, setTraceId] = useState('');
  const [imageId, setImageId] = useState('');
  const [confirmMode, setConfirmMode] = useState(false);
  const [confirmChoice, setConfirmChoice] = useState('other');
  const [confirmSymptoms, setConfirmSymptoms] = useState('');
  const [confirmSubmitting, setConfirmSubmitting] = useState(false);
  const [showRawTrace, setShowRawTrace] = useState(false);
  const [diagnosisStartTime, setDiagnosisStartTime] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0];
    if (selectedFile) {
      setFile(selectedFile);
      const reader = new FileReader();
      reader.onloadend = () => {
        setImagePreview(reader.result as string);
      };
      reader.readAsDataURL(selectedFile);
    }
  };





  const toNumber = (value: unknown): number | null => {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string' && value.trim()) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
    return null;
  };

  const resolveDisplayConfidencePct = (payload: any): number | null => {
    const finalConfidence = toNumber(payload?.final_confidence);
    if (finalConfidence !== null) {
      return finalConfidence <= 1 ? finalConfidence * 100 : finalConfidence;
    }

    const imageConfidencePct = toNumber(payload?.image_result?.confidence_pct);
    if (imageConfidencePct !== null) {
      return imageConfidencePct;
    }

    const imageConfidence = toNumber(payload?.image_result?.confidence);
    if (imageConfidence !== null) {
      return imageConfidence * 100;
    }

    return null;
  };



  const normalizeTop3 = (payload: any): Array<{ disease: string; confidence: number }> => {
    const rawTop3 = payload?.image_result?.top3 ?? payload?.top3 ?? [];
    if (!Array.isArray(rawTop3)) return [];
    return rawTop3
      .map((item: any) => {
        const disease = typeof item?.disease === 'string' ? item.disease : '';
        const pctFromProb = toNumber(item?.prob) !== null ? (toNumber(item?.prob) as number) * 100 : null;
        const confidence =
          toNumber(item?.confidence) ??
          toNumber(item?.confidence_pct) ??
          toNumber(item?.prob_pct) ??
          pctFromProb ??
          0;
        return { disease, confidence };
      })
      .filter((item) => item.disease);
  };

  const shouldEnterConfirmMode = (payload: any): boolean => {
    if (payload?.need_confirm === true) return true;
    const reasons = Array.isArray(payload?.fallback_reason) ? payload.fallback_reason : [];
    return reasons.includes('low_confidence') || reasons.includes('low_margin');
  };

  const buildResultFromPayload = (payload: any): DiagnosisResult => ({
    image_url: payload?.image_url || '',
    final_disease: payload?.final_disease || payload?.image_result?.disease || '未知',
    displayConfidencePct: resolveDisplayConfidencePct(payload),
    model_display_name: payload?.model_display_name || payload?.model_id || '-',
    top3: normalizeTop3(payload),
    treatment: payload?.treatment,
    prevention: payload?.prevention ?? payload?.treatment?.prevention,
    trace_id: payload?.trace_id || '',
  });

  const handleSubmit = async () => {
    if (!file) return;

    setLoading(true);
    setResult(null);
    setTraceEvents([]);
    setConfirmMode(false);
    setConfirmChoice('other');
    setConfirmSymptoms('');
    setDiagnosisStartTime(Date.now());

    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('crop_type', cropType || '番茄');
      if (symptoms.trim()) fd.append('symptoms', symptoms.trim());
      if (growthStage.trim()) fd.append('growth_stage', growthStage.trim());
      if (modelId) fd.append('model_id', modelId);

      const resp = await fetch('/api/diagnose-image', {
        method: 'POST',
        body: fd
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data?.detail || `诊断失败: ${resp.status}`);
      }

      if (data.trace_id) {
        setTraceId(data.trace_id);
      }
      if (data.image_id) {
        setImageId(data.image_id);
      }

      const normalizedResult = buildResultFromPayload(data);
      setResult(normalizedResult);

      if (shouldEnterConfirmMode(data)) {
        setConfirmMode(true);
        const defaultChoice = normalizedResult.top3[0]?.disease || 'other';
        setConfirmChoice(defaultChoice);
      }
    } catch (error) {
      console.error('Diagnosis failed:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleConfirmSubmit = async () => {
    if (!traceId || !imageId) return;
    setConfirmSubmitting(true);
    try {
      const additionalSymptoms = confirmSymptoms
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean);
      const symptomsForConfirm = confirmChoice !== 'other'
        ? [confirmChoice, ...additionalSymptoms]
        : additionalSymptoms;

      const resp = await fetch('/api/diagnose-confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          trace_id: traceId,
          image_id: imageId,
          crop_type: cropType || '番茄',
          symptoms: symptomsForConfirm,
          growth_stage: growthStage || null,
          model_id: modelId || null,
          choice: confirmChoice,
          notes: confirmSymptoms || null,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data?.detail || `确认失败: ${resp.status}`);
      }

      if (data.trace_id) {
        setTraceId(data.trace_id);
      }

      const mergedPayload = {
        ...data,
        image_url: result?.image_url || '',
        prevention: data?.treatment?.prevention,
      };
      setResult(buildResultFromPayload(mergedPayload));
      setConfirmMode(false);
    } catch (error) {
      console.error('Confirm diagnose failed:', error);
    } finally {
      setConfirmSubmitting(false);
    }
  };

  const renderRichValue = (value: unknown) => {
    if (value === null || value === undefined) return null;
    if (typeof value === 'string') {
      return <div className="whitespace-pre-wrap">{value}</div>;
    }
    if (typeof value === 'object') {
      const data = value as Record<string, unknown>;
      const plan = data.plan;
      const prevention = data.prevention;
      if (typeof plan === 'string' || typeof prevention === 'string') {
        return (
          <div className="space-y-3">
            {typeof plan === 'string' && plan.trim() && (
              <div>
                <div className="text-[#c8f7c5] text-xs mb-1">处方/方案</div>
                <div className="whitespace-pre-wrap">{plan}</div>
              </div>
            )}
            {typeof prevention === 'string' && prevention.trim() && (
              <div>
                <div className="text-[#c8f7c5] text-xs mb-1">预防/管理</div>
                <div className="whitespace-pre-wrap">{prevention}</div>
              </div>
            )}
          </div>
        );
      }
      return <pre className="whitespace-pre-wrap break-words">{JSON.stringify(value, null, 2)}</pre>;
    }
    return <div className="whitespace-pre-wrap">{String(value)}</div>;
  };

  const renderTreatment = (t: unknown) => renderRichValue(t);

  const refreshTrace = async () => {
    if (!traceId) return;
    
    try {
      const resp = await fetch(`/api/trace-events?trace_id=${encodeURIComponent(traceId)}`);
      const data = await resp.json();
      if (data.events) {
        setTraceEvents(data.events.map((evt: any) => ({
          timestamp: evt.timestamp || new Date().toISOString(),
          agent: evt.agent || evt.node,
          status: evt.status,
          message: evt.message
        })));
      }
    } catch (error) {
      console.error('Failed to fetch trace events:', error);
    }
  };

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Header */}
      <div className="text-center mb-8">
        <h1 className="text-4xl font-bold text-white mb-3">
          智能<span className="text-[#c8f7c5]">病害诊断</span>
        </h1>
        <p className="text-white/60 max-w-2xl mx-auto">
          上传作物图像，AI智能识别病害，提供精准治疗方案
        </p>
      </div>

      <div className="grid lg:grid-cols-5 gap-6">
        {/* Left Column - Upload Form */}
        <Card className="lg:col-span-2 glass-card">
          <CardHeader>
            <CardTitle className="text-white flex items-center gap-2">
              <Upload className="w-5 h-5 text-[#c8f7c5]" />
              上传信息
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            {/* File Upload */}
            <div className="space-y-2">
              <Label className="text-white/80">图片文件</Label>
              <div
                onClick={() => fileInputRef.current?.click()}
                className={cn(
                  "border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all duration-300",
                  imagePreview 
                    ? "border-[#c8f7c5]/50 bg-[#c8f7c5]/5" 
                    : "border-white/20 hover:border-[#c8f7c5]/50 hover:bg-white/5"
                )}
              >
                {imagePreview ? (
                  <img 
                    src={imagePreview} 
                    alt="Preview" 
                    className="max-h-40 mx-auto rounded-lg object-contain"
                  />
                ) : (
                  <div className="space-y-2">
                    <ImageIcon className="w-10 h-10 text-white/40 mx-auto" />
                    <p className="text-white/60 text-sm">点击选择或拖拽图片</p>
                  </div>
                )}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  onChange={handleFileChange}
                  className="hidden"
                />
              </div>
            </div>

            {/* Symptoms */}
            <div className="space-y-2">
              <Label className="text-white/80">症状（逗号分隔）</Label>
              <Input
                placeholder="例如：斑点, 发黄"
                value={symptoms}
                onChange={(e) => setSymptoms(e.target.value)}
                className="bg-white/5 border-white/20 text-white placeholder:text-white/40 focus:border-[#c8f7c5]"
              />
            </div>

            {/* Crop Type */}
            <div className="space-y-2">
              <Label className="text-white/80">作物类型</Label>
              <Input
                placeholder="番茄"
                value={cropType}
                onChange={(e) => setCropType(e.target.value)}
                className="bg-white/5 border-white/20 text-white placeholder:text-white/40 focus:border-[#c8f7c5]"
              />
            </div>

            {/* Growth Stage */}
            <div className="space-y-2">
              <Label className="text-white/80">生长阶段（可选）</Label>
              <Input
                placeholder="例如：开花期"
                value={growthStage}
                onChange={(e) => setGrowthStage(e.target.value)}
                className="bg-white/5 border-white/20 text-white placeholder:text-white/40 focus:border-[#c8f7c5]"
              />
            </div>

            {/* Model Selection */}
            <div className="space-y-2">
              <Label className="text-white/80">识别模型</Label>
              <Select value={modelId} onValueChange={setModelId}>
                <SelectTrigger className="bg-white/5 border-white/20 text-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-[#1a1a1a] border-white/20">
                  <SelectItem value="default">默认高精度模型 (tf)</SelectItem>
                  <SelectItem value="lightweight">轻量模型V1 (tf)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Submit Button */}
            <Button
              onClick={handleSubmit}
              disabled={!file || loading}
              className="w-full bg-[#c8f7c5] text-black hover:bg-[#b8e7b5] font-semibold h-12 rounded-xl transition-all duration-300 disabled:opacity-50"
            >
              {loading ? (
                <>
                  <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                  诊断中...
                </>
              ) : (
                <>
                  <Send className="w-5 h-5 mr-2" />
                  开始诊断
                </>
              )}
            </Button>
          </CardContent>
        </Card>

        {/* Right Column - Results */}
        <div className="lg:col-span-3 space-y-6">
          {/* Diagnosis Result Card */}
          <Card className="glass-card">
            <CardHeader>
              <CardTitle className="text-white flex items-center gap-2">
                <CheckCircle className="w-5 h-5 text-[#c8f7c5]" />
                诊断结果
              </CardTitle>
            </CardHeader>
            <CardContent>
              {result ? (
                <div className="space-y-5 animate-fadeIn">
                  {/* Result Image */}
                  {result.image_url && (
                    <div className="rounded-xl overflow-hidden bg-black/30">
                      <img 
                        src={result.image_url} 
                        alt="Diagnosed" 
                        className="w-full max-h-64 object-contain"
                      />
                    </div>
                  )}

                  {/* Main Result */}
                  <div className="grid sm:grid-cols-3 gap-4">
                    <div className="bg-white/5 rounded-xl p-4">
                      <p className="text-white/60 text-sm mb-1">最终病害</p>
                      <p className="text-xl font-bold text-[#c8f7c5]">{result.final_disease}</p>
                    </div>
                    <div className="bg-white/5 rounded-xl p-4">
                      <p className="text-white/60 text-sm mb-1">置信度</p>
                      <p className="text-xl font-bold text-[#c8f7c5]">{result.displayConfidencePct !== null ? `${result.displayConfidencePct.toFixed(2)}%` : "—"}</p>
                    </div>
                    <div className="bg-white/5 rounded-xl p-4">
                      <p className="text-white/60 text-sm mb-1">使用模型</p>
                      <p className="text-sm font-medium text-white">{result.model_display_name}</p>
                    </div>
                  </div>

                  {/* Top 3 */}
                  {result.top3 && result.top3.length > 0 && (
                    <div>
                      <h4 className="text-white/80 font-medium mb-3">Top 3 识别结果</h4>
                      <div className="space-y-2">
                        {result.top3.map((item, idx) => (
                          <div key={idx} className="flex items-center gap-3">
                            <Badge 
                              variant={idx === 0 ? "default" : "outline"}
                              className={cn(
                                "min-w-[3rem] text-center",
                                idx === 0 ? "bg-[#c8f7c5] text-black" : "border-white/30 text-white"
                              )}
                            >
                              #{idx + 1}
                            </Badge>
                            <span className="text-white flex-1">{item.disease}</span>
                            <span className="text-[#c8f7c5] font-mono">{item.confidence?.toFixed(2)}%</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}


                  {confirmMode && (
                    <div className="bg-[#c8f7c5]/10 border border-[#c8f7c5]/30 rounded-xl p-4 space-y-4">
                      <h4 className="text-[#c8f7c5] font-medium">二次诊断 / 确认入口</h4>
                      <div className="space-y-2">
                        <Label className="text-white/80">候选病害选择</Label>
                        {(Array.isArray(result.top3) ? result.top3 : []).map((item) => (
                          <label key={item.disease} className="flex items-center gap-2 text-sm text-white/80 cursor-pointer">
                            <input
                              type="radio"
                              name="confirmDisease"
                              value={item.disease}
                              checked={confirmChoice === item.disease}
                              onChange={(e) => setConfirmChoice(e.target.value)}
                            />
                            <span>{item.disease}</span>
                          </label>
                        ))}
                        <label className="flex items-center gap-2 text-sm text-white/80 cursor-pointer">
                          <input
                            type="radio"
                            name="confirmDisease"
                            value="other"
                            checked={confirmChoice === 'other'}
                            onChange={(e) => setConfirmChoice(e.target.value)}
                          />
                          <span>仍不确定 / 其他</span>
                        </label>
                      </div>

                      <div className="space-y-2">
                        <Label className="text-white/80">补充症状（可选，逗号分隔）</Label>
                        <Input
                          value={confirmSymptoms}
                          onChange={(e) => setConfirmSymptoms(e.target.value)}
                          placeholder="例如：叶片卷曲, 发黄"
                          className="bg-white/5 border-white/20 text-white placeholder:text-white/40"
                        />
                      </div>

                      <Button
                        onClick={handleConfirmSubmit}
                        disabled={confirmSubmitting || !traceId || !imageId}
                        className="bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
                      >
                        {confirmSubmitting ? '提交中...' : '提交确认'}
                      </Button>
                    </div>
                  )}

                  <Separator className="bg-white/10" />

                  {/* Treatment */}
                  {result.treatment && (
                    <div>
                      <h4 className="text-white/80 font-medium mb-2 flex items-center gap-2">
                        <AlertCircle className="w-4 h-4 text-[#c8f7c5]" />
                        治疗方案
                      </h4>
                      <div className="bg-white/5 rounded-xl p-4 text-white/80 text-sm leading-relaxed whitespace-pre-line">
                        {renderTreatment(result.treatment)}
                      </div>
                    </div>
                  )}

                  {/* Prevention */}
                  {result.prevention && (
                    <div>
                      <h4 className="text-white/80 font-medium mb-2">预防建议</h4>
                      <div className="bg-white/5 rounded-xl p-4 text-white/80 text-sm leading-relaxed whitespace-pre-line">
                        {renderRichValue(result.prevention)}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-center py-12 text-white/40">
                  <ImageIcon className="w-16 h-16 mx-auto mb-4 opacity-50" />
                  <p>上传图片并点击诊断按钮获取结果</p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Trace Events Card */}
          <Card className="glass-card">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-white flex items-center gap-2">
                <RefreshCw className="w-5 h-5 text-[#c8f7c5]" />
                多智能体协作流程
              </CardTitle>
              {traceId && (
                <div className="flex items-center gap-3">
                  <span className="text-white/40 text-sm">追踪ID: {traceId.slice(0, 16)}...</span>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={refreshTrace}
                    className="border-white/20 text-white hover:bg-white/10"
                  >
                    <RefreshCw className="w-4 h-4" />
                  </Button>
                </div>
              )}
            </CardHeader>
            <CardContent className="space-y-4">
              <AgentWorkflowPanel
                traceId={traceId || undefined}
                lastConfidencePct={result?.displayConfidencePct ?? undefined}
              />

              <div className="flex items-center justify-between">
                <p className="text-xs text-white/50">调试事件流（开发排查）</p>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowRawTrace((prev) => !prev)}
                  className="text-white/70 hover:bg-white/10"
                >
                  {showRawTrace ? <ChevronUp className="w-4 h-4 mr-1" /> : <ChevronDown className="w-4 h-4 mr-1" />}
                  {showRawTrace ? '收起事件' : '展开事件'}
                </Button>
              </div>

              {showRawTrace && (traceEvents.length > 0 ? (
                <div className="space-y-3 max-h-80 overflow-y-auto">
                  {traceEvents.map((event, idx) => (
                    <div 
                      key={`${event.timestamp}-${idx}`}
                      className="flex items-start gap-3 p-3 rounded-lg bg-white/5 animate-slideIn"
                      style={{ animationDelay: `${idx * 30}ms` }}
                    >
                      <div className={cn(
                        "w-2 h-2 rounded-full mt-2 flex-shrink-0",
                        event.status === '完成' || event.status === 'done' || event.status === 'completed'
                          ? "bg-green-400" 
                          : event.status === '错误' || event.status === 'error'
                          ? "bg-red-400"
                          : "bg-[#c8f7c5] animate-pulse"
                      )} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-white/40 text-xs font-mono">
                            {new Date(event.timestamp).toLocaleTimeString()}
                          </span>
                          <Badge variant="outline" className="border-[#c8f7c5]/50 text-[#c8f7c5] text-xs">
                            {event.agent}
                          </Badge>
                          <span className="text-white text-sm">{event.status}</span>
                        </div>
                        {event.message && (
                          <p className="text-white/50 text-xs mt-1">{event.message}</p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-8 text-white/40">
                  <RefreshCw className="w-10 h-10 mx-auto mb-3 opacity-50" />
                  <p className="text-sm">暂未收到追踪事件，面板将使用模拟进度降级展示</p>
                </div>
              ))}

              {diagnosisStartTime && (
                <p className="text-xs text-white/40">诊断启动时间：{new Date(diagnosisStartTime).toLocaleTimeString()}</p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
