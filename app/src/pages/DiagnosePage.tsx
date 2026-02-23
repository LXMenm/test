import { useState, useRef, useEffect } from 'react';
import { Upload, Send, RefreshCw, AlertCircle, CheckCircle, Loader2, Image as ImageIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { cn } from '@/lib/utils';

interface DiagnosisResult {
  image_url: string;
  final_disease: string;
  confidence: number;
  model_display_name: string;
  top3: Array<{ disease: string; confidence: number }>;
  treatment: string;
  prevention: string;
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
  const fileInputRef = useRef<HTMLInputElement>(null);
  const traceSourceRef = useRef<EventSource | null>(null);

  // Cleanup EventSource on unmount
  useEffect(() => {
    return () => {
      if (traceSourceRef.current) {
        traceSourceRef.current.close();
      }
    };
  }, []);

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

  const openTraceStream = (tid: string) => {
    if (traceSourceRef.current) {
      traceSourceRef.current.close();
    }
    
    const es = new EventSource(`/api/traces/${encodeURIComponent(tid)}/stream`);
    traceSourceRef.current = es;
    
    es.addEventListener('trace', (evt) => {
      const payload = JSON.parse(evt.data || '{}');
      if (payload.node && payload.status) {
        setTraceEvents(prev => [...prev, {
          timestamp: new Date().toISOString(),
          agent: payload.node,
          status: payload.status,
          message: payload.message
        }]);
      }
    });
    
    es.onerror = () => {
      es.close();
    };
  };

  const handleSubmit = async () => {
    if (!file) return;
    
    setLoading(true);
    setResult(null);
    setTraceEvents([]);
    
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
      
      if (data.trace_id) {
        setTraceId(data.trace_id);
        openTraceStream(data.trace_id);
      }
      
      setResult({
        image_url: data.image_url,
        final_disease: data.final_disease,
        confidence: data.confidence,
        model_display_name: data.model_display_name,
        top3: data.top3 || [],
        treatment: data.treatment,
        prevention: data.prevention,
        trace_id: data.trace_id
      });
    } catch (error) {
      console.error('Diagnosis failed:', error);
    } finally {
      setLoading(false);
    }
  };

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
                      <p className="text-xl font-bold text-[#c8f7c5]">{result.confidence?.toFixed(2)}%</p>
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

                  <Separator className="bg-white/10" />

                  {/* Treatment */}
                  {result.treatment && (
                    <div>
                      <h4 className="text-white/80 font-medium mb-2 flex items-center gap-2">
                        <AlertCircle className="w-4 h-4 text-[#c8f7c5]" />
                        治疗方案
                      </h4>
                      <div className="bg-white/5 rounded-xl p-4 text-white/80 text-sm leading-relaxed whitespace-pre-line">
                        {result.treatment}
                      </div>
                    </div>
                  )}

                  {/* Prevention */}
                  {result.prevention && (
                    <div>
                      <h4 className="text-white/80 font-medium mb-2">预防建议</h4>
                      <div className="bg-white/5 rounded-xl p-4 text-white/80 text-sm leading-relaxed whitespace-pre-line">
                        {result.prevention}
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
            <CardContent>
              {traceEvents.length > 0 ? (
                <div className="space-y-3 max-h-80 overflow-y-auto">
                  {traceEvents.map((event, idx) => (
                    <div 
                      key={idx}
                      className="flex items-start gap-3 p-3 rounded-lg bg-white/5 animate-slideIn"
                      style={{ animationDelay: `${idx * 50}ms` }}
                    >
                      <div className={cn(
                        "w-2 h-2 rounded-full mt-2 flex-shrink-0",
                        event.status === '完成' || event.status === 'done' 
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
                  <p className="text-sm">诊断流程追踪将在此显示</p>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
