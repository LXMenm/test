import { useState, useEffect } from 'react';
import { Plus, Save, Trash2, Search, Pill, Stethoscope, Link2, FileText } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { loadAuthUser } from '@/auth';


interface Disease {
  name: string;
  description: string;
}

interface TreatmentActions {
  immediate_actions?: string[];
  treatment_plan?: {
    FAMILY?: string[];
    MID?: string[];
    ENTERPRISE?: string[];
  };
  prevention_plan?: string[];
  resistance_management?: string[];
  safety_notes?: string[];
  follow_up?: string[];
}

interface Treatment {
  disease: string;
  treatment: string;
  prevention: string;
  actions?: TreatmentActions;
  ingredients?: string[];
}

interface Rule {
  rule_id: string;
  crop_type: string;
  symptoms: string;
  disease: string;
  confidence: number;
  evidence: string;
}

interface SymptomMap {
  symptom: string;
  diseases: string[];
}

type TabType = 'diseases' | 'treatments' | 'rules' | 'symptom-map';

interface DiseaseDetail {
  name: string;
  description: string;
  treatment: string;
  prevention: string;
  actions?: TreatmentActions;
  ingredients?: string[];
}

interface KBPageProps {
  focusDiseaseName?: string;
}

export function KBPage({ focusDiseaseName = '' }: KBPageProps) {
  const authUser = loadAuthUser();
  const canEdit = authUser?.role === 'ADMIN';
  const [activeTab, setActiveTab] = useState<TabType>('diseases');
  const [, setLoading] = useState(false);
  
  // Data states
  const [diseases, setDiseases] = useState<Disease[]>([]);
  const [treatments, setTreatments] = useState<Treatment[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [symptomMaps, setSymptomMaps] = useState<SymptomMap[]>([]);
  
  // Filter states
  const [diseaseFilter, setDiseaseFilter] = useState('');
  const [treatmentFilter, setTreatmentFilter] = useState('');
  const [ruleFilter, setRuleFilter] = useState('');
  const [symptomMapFilter, setSymptomMapFilter] = useState('');
  
  // Selection states
  const [selectedDiseases, setSelectedDiseases] = useState<string[]>([]);
  const [selectedTreatments, setSelectedTreatments] = useState<string[]>([]);
  const [selectedRules, setSelectedRules] = useState<string[]>([]);
  const [selectedSymptomMaps, setSelectedSymptomMaps] = useState<string[]>([]);
  
  // Dialog states
  const [showDiseaseDialog, setShowDiseaseDialog] = useState(false);
  const [showTreatmentDialog, setShowTreatmentDialog] = useState(false);
  const [showRuleDialog, setShowRuleDialog] = useState(false);
  const [showSymptomMapDialog, setShowSymptomMapDialog] = useState(false);
  
  // Edit states
  const [editingDisease, setEditingDisease] = useState<Disease | null>(null);
  const [editingTreatment, setEditingTreatment] = useState<Treatment | null>(null);
  const [editingRule, setEditingRule] = useState<Rule | null>(null);
  const [editingSymptomMap, setEditingSymptomMap] = useState<SymptomMap | null>(null);
  const [diseaseDialogMode, setDiseaseDialogMode] = useState<'create' | 'edit'>('create');
  const [symptomDialogMode, setSymptomDialogMode] = useState<'create' | 'edit'>('create');
  const [editingDiseaseOriginalName, setEditingDiseaseOriginalName] = useState('');
  const [editingSymptomOriginalName, setEditingSymptomOriginalName] = useState('');
  const [editingTreatmentActionsJson, setEditingTreatmentActionsJson] = useState('');
  const [editingTreatmentActionsError, setEditingTreatmentActionsError] = useState('');
  const [showActionsEditor, setShowActionsEditor] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [focusDiseaseDetail, setFocusDiseaseDetail] = useState<DiseaseDetail | null>(null);
  const [showDiseaseDetailDialog, setShowDiseaseDetailDialog] = useState(false);

  const clearFocusDisease = () => {
    setFocusDiseaseDetail(null);
    setDetailError('');
    setShowDiseaseDetailDialog(false);
    if (window.location.pathname.startsWith('/kb/')) {
      window.history.pushState(null, '', '/kb');
      window.dispatchEvent(new PopStateEvent('popstate'));
    }
  };

  const fetchDiseases = async () => {
    try {
      const resp = await fetch('/api/kb/diseases');
      const data = await resp.json();
      setDiseases(data.items || []);
    } catch (error) {
      console.error('Failed to fetch diseases:', error);
    }
  };

  const fetchData = async (tab: TabType) => {
    setLoading(true);
    try {
      let endpoint = '';
      switch (tab) {
        case 'diseases':
          await fetchDiseases();
          return;
        case 'treatments':
          endpoint = '/api/kb/treatments';
          break;
        case 'rules':
          endpoint = '/api/kb/rules';
          break;
        case 'symptom-map':
          endpoint = '/api/kb/symptom-map';
          break;
      }
      
      const resp = await fetch(endpoint);
      const data = await resp.json();
      
      switch (tab) {
        case 'treatments':
          setTreatments(data.items || []);
          break;
        case 'rules':
          setRules(data.items || []);
          break;
        case 'symptom-map':
          setSymptomMaps(data.items || []);
          break;
      }
    } catch (error) {
      console.error(`Failed to fetch ${tab}:`, error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'diseases') {
      fetchData(activeTab);
      return;
    }
    fetchDiseases();
    fetchData(activeTab);
  }, [activeTab]);

  useEffect(() => {
    const diseaseName = focusDiseaseName.trim();
    if (!diseaseName) {
      setFocusDiseaseDetail(null);
      setDetailError('');
      setShowDiseaseDetailDialog(false);
      return;
    }

    const fetchDetail = async () => {
      setDetailLoading(true);
      setDetailError('');
      try {
        const resp = await fetch(`/api/kb/diseases/${encodeURIComponent(diseaseName)}`);
        const data = await resp.json();
        if (!resp.ok) {
          throw new Error(typeof data?.detail === 'string' ? data.detail : '获取病害详情失败');
        }
        setFocusDiseaseDetail(data as DiseaseDetail);
        setShowDiseaseDetailDialog(true);
      } catch (error) {
        setFocusDiseaseDetail(null);
        setDetailError(error instanceof Error ? error.message : '获取病害详情失败');
        setShowDiseaseDetailDialog(true);
      } finally {
        setDetailLoading(false);
      }
    };

    setActiveTab('diseases');
    fetchDetail();
  }, [focusDiseaseName]);

  // CRUD operations
  const saveDisease = async () => {
    if (!editingDisease) return;

    const isNew = diseaseDialogMode === 'create';
    const targetName = isNew ? editingDisease.name : editingDiseaseOriginalName;
    try {
      const resp = await fetch(`/api/kb/diseases${isNew ? '' : '/' + encodeURIComponent(targetName)}`, {
        method: isNew ? 'POST' : 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editingDisease)
      });
      
      if (resp.ok) {
        fetchDiseases();
        setShowDiseaseDialog(false);
        setEditingDisease(null);
        setEditingDiseaseOriginalName('');
      } else if (resp.status === 409) {
        alert('病害已存在');
      }
    } catch (error) {
      console.error('Failed to save disease:', error);
    }
  };

  const deleteDiseases = async () => {
    try {
      const resp = await fetch('/api/kb/diseases', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ names: selectedDiseases })
      });
      
      if (resp.ok) {
        setSelectedDiseases([]);
        fetchDiseases();
      }
    } catch (error) {
      console.error('Failed to delete diseases:', error);
    }
  };

  const saveTreatment = async () => {
    if (!editingTreatment) return;

    let parsedActions: TreatmentActions | undefined;
    if (editingTreatmentActionsJson.trim()) {
      try {
        const parsed: unknown = JSON.parse(editingTreatmentActionsJson);
        parsedActions = (parsed && typeof parsed === 'object' ? parsed : {}) as TreatmentActions;
        setEditingTreatmentActionsError('');
      } catch {
        setEditingTreatmentActionsError('actions JSON 格式不合法');
        return;
      }
    }

    const payload: Treatment = {
      ...editingTreatment,
      actions: parsedActions,
      ingredients: Array.isArray(editingTreatment.ingredients)
        ? editingTreatment.ingredients.map((item) => String(item).trim()).filter(Boolean)
        : [],
    };

    const isNew = !treatments.find(t => t.disease === editingTreatment.disease);
    try {
      const resp = await fetch(`/api/kb/treatments${isNew ? '' : '/' + encodeURIComponent(editingTreatment.disease)}`, {
        method: isNew ? 'POST' : 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (resp.ok) {
        fetchData('treatments');
        setShowTreatmentDialog(false);
        setEditingTreatment(null);
        setEditingTreatmentActionsJson('');
        setEditingTreatmentActionsError('');
        setShowActionsEditor(false);
      }
    } catch (error) {
      console.error('Failed to save treatment:', error);
    }
  };

  const deleteTreatments = async () => {
    try {
      const resp = await fetch('/api/kb/treatments', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ diseases: selectedTreatments })
      });
      
      if (resp.ok) {
        setSelectedTreatments([]);
        fetchData('treatments');
      }
    } catch (error) {
      console.error('Failed to delete treatments:', error);
    }
  };

  const saveRule = async () => {
    if (!editingRule) return;
    
    const isNew = !editingRule.rule_id;
    try {
      const resp = await fetch(`/api/kb/rules${isNew ? '' : '/' + editingRule.rule_id}`, {
        method: isNew ? 'POST' : 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editingRule)
      });
      
      if (resp.ok) {
        fetchData('rules');
        setShowRuleDialog(false);
        setEditingRule(null);
      }
    } catch (error) {
      console.error('Failed to save rule:', error);
    }
  };

  const deleteRules = async () => {
    try {
      const resp = await fetch('/api/kb/rules', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rule_ids: selectedRules })
      });
      
      if (resp.ok) {
        setSelectedRules([]);
        fetchData('rules');
      }
    } catch (error) {
      console.error('Failed to delete rules:', error);
    }
  };

  const saveSymptomMap = async () => {
    if (!editingSymptomMap) return;

    const isNew = symptomDialogMode === 'create';
    const targetSymptom = isNew ? editingSymptomMap.symptom : editingSymptomOriginalName;
    try {
      const resp = await fetch(`/api/kb/symptom-map${isNew ? '' : '/' + encodeURIComponent(targetSymptom)}`, {
        method: isNew ? 'POST' : 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editingSymptomMap)
      });
      
      if (resp.ok) {
        fetchData('symptom-map');
        setShowSymptomMapDialog(false);
        setEditingSymptomMap(null);
        setEditingSymptomOriginalName('');
      } else if (resp.status === 409) {
        alert('症状已存在');
      }
    } catch (error) {
      console.error('Failed to save symptom map:', error);
    }
  };

  const deleteSymptomMaps = async () => {
    try {
      const resp = await fetch('/api/kb/symptom-map', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symptoms: selectedSymptomMaps })
      });
      
      if (resp.ok) {
        setSelectedSymptomMaps([]);
        fetchData('symptom-map');
      }
    } catch (error) {
      console.error('Failed to delete symptom maps:', error);
    }
  };

  const filteredDiseases = diseases.filter(d => 
    d.name.toLowerCase().includes(diseaseFilter.toLowerCase()) ||
    d.description.toLowerCase().includes(diseaseFilter.toLowerCase())
  );

  const filteredTreatments = treatments.filter(t =>
    t.disease.toLowerCase().includes(treatmentFilter.toLowerCase())
  );

  const filteredRules = rules.filter(r =>
    r.crop_type.toLowerCase().includes(ruleFilter.toLowerCase()) ||
    r.symptoms.toLowerCase().includes(ruleFilter.toLowerCase()) ||
    r.disease.toLowerCase().includes(ruleFilter.toLowerCase())
  );

  const filteredSymptomMaps = symptomMaps.filter(s =>
    s.symptom.toLowerCase().includes(symptomMapFilter.toLowerCase())
  );

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-white">
          知识库<span className="text-[#c8f7c5]">模块</span>
        </h1>
        <p className="text-white/60 mt-1">维护病害描述、治疗方案、诊断规则与症状映射</p>
      </div>

      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as TabType)}>
        <TabsList className="bg-white/5 border border-white/10 p-1">
          <TabsTrigger 
            value="diseases" 
            className="data-[state=active]:bg-[#c8f7c5] data-[state=active]:text-black text-white/70"
          >
            <Stethoscope className="w-4 h-4 mr-2" />
            病害及描述
          </TabsTrigger>
          <TabsTrigger 
            value="treatments"
            className="data-[state=active]:bg-[#c8f7c5] data-[state=active]:text-black text-white/70"
          >
            <Pill className="w-4 h-4 mr-2" />
            治疗/预防
          </TabsTrigger>
          <TabsTrigger 
            value="rules"
            className="data-[state=active]:bg-[#c8f7c5] data-[state=active]:text-black text-white/70"
          >
            <FileText className="w-4 h-4 mr-2" />
            诊断规则
          </TabsTrigger>
          <TabsTrigger 
            value="symptom-map"
            className="data-[state=active]:bg-[#c8f7c5] data-[state=active]:text-black text-white/70"
          >
            <Link2 className="w-4 h-4 mr-2" />
            症状-病害映射
          </TabsTrigger>
        </TabsList>

        {/* Diseases Tab */}
        <TabsContent value="diseases" className="mt-6">
          <Card className="glass-card">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-white flex items-center gap-2">
                <Stethoscope className="w-5 h-5 text-[#c8f7c5]" />
                病害及描述
              </CardTitle>
              <div className="flex gap-2">
                {canEdit ? <Button
                  onClick={() => {
                    setDiseaseDialogMode('create');
                    setEditingDiseaseOriginalName('');
                    setEditingDisease({ name: '', description: '' });
                    setShowDiseaseDialog(true);
                  }}
                  className="bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
                >
                  <Plus className="w-4 h-4 mr-1" />
                  新增
                </Button> : null}
                {canEdit && selectedDiseases.length > 0 && (
                  <Button
                    onClick={deleteDiseases}
                    variant="outline"
                    className="border-red-500/50 text-red-400 hover:bg-red-500/10"
                  >
                    <Trash2 className="w-4 h-4 mr-1" />
                    删除所选
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
                  <Input
                    placeholder="搜索病害或描述..."
                    value={diseaseFilter}
                    onChange={(e) => setDiseaseFilter(e.target.value)}
                    className="pl-10 bg-white/5 border-white/20 text-white focus:border-[#c8f7c5]"
                  />
                </div>
                
                <div className="rounded-xl border border-white/10 overflow-hidden">
                  <table className="w-full">
                    <thead className="bg-white/5">
                      <tr>
                        <th className="p-3 text-left">
                          <Checkbox
                            checked={selectedDiseases.length === filteredDiseases.length && filteredDiseases.length > 0}
                            onCheckedChange={(v) => setSelectedDiseases(v ? filteredDiseases.map(d => d.name) : [])}
                            className="border-white/30"
                          />
                        </th>
                        <th className="p-3 text-left text-white/80 font-medium">病害</th>
                        <th className="p-3 text-left text-white/80 font-medium">描述</th>
                        <th className="p-3 text-right text-white/80 font-medium">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredDiseases.map((disease) => (
                        <tr key={disease.name} className="border-t border-white/10 hover:bg-white/5">
                          <td className="p-3">
                            <Checkbox
                              checked={selectedDiseases.includes(disease.name)}
                              onCheckedChange={(v) => {
                                if (v) setSelectedDiseases([...selectedDiseases, disease.name]);
                                else setSelectedDiseases(selectedDiseases.filter(n => n !== disease.name));
                              }}
                              className="border-white/30"
                            />
                          </td>
                          <td className="p-3 text-white font-medium">{disease.name}</td>
                          <td className="p-3 text-white/70">{disease.description}</td>
                          <td className="p-3 text-right">
                            {canEdit ? <Button
                              onClick={() => {
                                setDiseaseDialogMode('edit');
                                setEditingDiseaseOriginalName(disease.name);
                                setEditingDisease(disease);
                                setShowDiseaseDialog(true);
                              }}
                              variant="ghost"
                              size="sm"
                              className="text-[#c8f7c5] hover:bg-[#c8f7c5]/10"
                            >
                              编辑
                            </Button> : <span className="text-white/40 text-xs">只读</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Treatments Tab */}
        <TabsContent value="treatments" className="mt-6">
          <Card className="glass-card">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-white flex items-center gap-2">
                <Pill className="w-5 h-5 text-[#c8f7c5]" />
                治疗/预防方案
              </CardTitle>
              <div className="flex gap-2">
                {canEdit ? <Button
                  onClick={() => { setEditingTreatment({ disease: '', treatment: '', prevention: '', actions: undefined, ingredients: [] }); setEditingTreatmentActionsJson(''); setEditingTreatmentActionsError(''); setShowActionsEditor(false); setShowTreatmentDialog(true); }}
                  className="bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
                >
                  <Plus className="w-4 h-4 mr-1" />
                  新增
                </Button> : null}
                {canEdit && selectedTreatments.length > 0 && (
                  <Button
                    onClick={deleteTreatments}
                    variant="outline"
                    className="border-red-500/50 text-red-400 hover:bg-red-500/10"
                  >
                    <Trash2 className="w-4 h-4 mr-1" />
                    删除所选
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
                  <Input
                    placeholder="搜索病害..."
                    value={treatmentFilter}
                    onChange={(e) => setTreatmentFilter(e.target.value)}
                    className="pl-10 bg-white/5 border-white/20 text-white focus:border-[#c8f7c5]"
                  />
                </div>
                
                <div className="grid gap-4">
                  {filteredTreatments.map((treatment) => (
                    <div key={treatment.disease} className="bg-white/5 rounded-xl p-4 border border-white/10">
                      <div className="flex items-start justify-between">
                        <div className="flex items-center gap-3">
                          <Checkbox
                            checked={selectedTreatments.includes(treatment.disease)}
                            onCheckedChange={(v) => {
                              if (v) setSelectedTreatments([...selectedTreatments, treatment.disease]);
                              else setSelectedTreatments(selectedTreatments.filter(d => d !== treatment.disease));
                            }}
                            className="border-white/30"
                          />
                          <Badge className="bg-[#c8f7c5]/20 text-[#c8f7c5]">{treatment.disease}</Badge>
                        </div>
                        {canEdit ? <Button
                          onClick={() => { setEditingTreatment(treatment); setEditingTreatmentActionsJson(JSON.stringify(treatment.actions || {}, null, 2)); setEditingTreatmentActionsError(''); setShowActionsEditor(false); setShowTreatmentDialog(true); }}
                          variant="ghost"
                          size="sm"
                          className="text-[#c8f7c5] hover:bg-[#c8f7c5]/10"
                        >
                          编辑
                        </Button> : <span className="text-white/40 text-xs">只读</span>}
                      </div>
                      <div className="mt-3 grid sm:grid-cols-2 gap-3">
                        <div>
                          <p className="text-white/60 text-xs mb-1">治疗方案</p>
                          <p className="text-white/80 text-sm line-clamp-2">{treatment.treatment}</p>
                        </div>
                        <div>
                          <p className="text-white/60 text-xs mb-1">预防措施</p>
                          <p className="text-white/80 text-sm line-clamp-2">{treatment.prevention}</p>
                        </div>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-2 text-xs">
                        {Array.isArray(treatment.ingredients) && treatment.ingredients.length > 0 ? (
                          <Badge className="bg-emerald-900/40 border border-emerald-600/50 text-emerald-100">成分: {treatment.ingredients.join('、')}</Badge>
                        ) : null}
                        {treatment.actions ? (
                          <Badge className="bg-white/10 border border-white/20 text-white/80">含结构化 actions</Badge>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Rules Tab */}
        <TabsContent value="rules" className="mt-6">
          <Card className="glass-card">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-white flex items-center gap-2">
                <FileText className="w-5 h-5 text-[#c8f7c5]" />
                诊断规则
              </CardTitle>
              <div className="flex gap-2">
                {canEdit ? <Button
                  onClick={() => { setEditingRule({ rule_id: '', crop_type: '', symptoms: '', disease: '', confidence: 0.8, evidence: '' }); setShowRuleDialog(true); }}
                  className="bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
                >
                  <Plus className="w-4 h-4 mr-1" />
                  新增
                </Button> : null}
                {canEdit && selectedRules.length > 0 && (
                  <Button
                    onClick={deleteRules}
                    variant="outline"
                    className="border-red-500/50 text-red-400 hover:bg-red-500/10"
                  >
                    <Trash2 className="w-4 h-4 mr-1" />
                    删除所选
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
                  <Input
                    placeholder="搜索作物、症状或病害..."
                    value={ruleFilter}
                    onChange={(e) => setRuleFilter(e.target.value)}
                    className="pl-10 bg-white/5 border-white/20 text-white focus:border-[#c8f7c5]"
                  />
                </div>
                
                <div className="rounded-xl border border-white/10 overflow-hidden">
                  <table className="w-full">
                    <thead className="bg-white/5">
                      <tr>
                        <th className="p-3 text-left">
                          <Checkbox
                            checked={selectedRules.length === filteredRules.length && filteredRules.length > 0}
                            onCheckedChange={(v) => setSelectedRules(v ? filteredRules.map(r => r.rule_id) : [])}
                            className="border-white/30"
                          />
                        </th>
                        <th className="p-3 text-left text-white/80 font-medium">作物</th>
                        <th className="p-3 text-left text-white/80 font-medium">症状</th>
                        <th className="p-3 text-left text-white/80 font-medium">病害</th>
                        <th className="p-3 text-left text-white/80 font-medium">置信度</th>
                        <th className="p-3 text-right text-white/80 font-medium">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredRules.map((rule) => (
                        <tr key={rule.rule_id} className="border-t border-white/10 hover:bg-white/5">
                          <td className="p-3">
                            <Checkbox
                              checked={selectedRules.includes(rule.rule_id)}
                              onCheckedChange={(v) => {
                                if (v) setSelectedRules([...selectedRules, rule.rule_id]);
                                else setSelectedRules(selectedRules.filter(id => id !== rule.rule_id));
                              }}
                              className="border-white/30"
                            />
                          </td>
                          <td className="p-3 text-white">{rule.crop_type}</td>
                          <td className="p-3 text-white/70">{rule.symptoms}</td>
                          <td className="p-3">
                            <Badge className="bg-[#c8f7c5]/20 text-[#c8f7c5]">{rule.disease}</Badge>
                          </td>
                          <td className="p-3 text-[#c8f7c5] font-mono">{(rule.confidence * 100).toFixed(0)}%</td>
                          <td className="p-3 text-right">
                            {canEdit ? <Button
                              onClick={() => { setEditingRule(rule); setShowRuleDialog(true); }}
                              variant="ghost"
                              size="sm"
                              className="text-[#c8f7c5] hover:bg-[#c8f7c5]/10"
                            >
                              编辑
                            </Button> : <span className="text-white/40 text-xs">只读</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Symptom Map Tab */}
        <TabsContent value="symptom-map" className="mt-6">
          <Card className="glass-card">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-white flex items-center gap-2">
                <Link2 className="w-5 h-5 text-[#c8f7c5]" />
                症状-病害映射
              </CardTitle>
              <div className="flex gap-2">
                {canEdit ? <Button
                  onClick={() => {
                    setSymptomDialogMode('create');
                    setEditingSymptomOriginalName('');
                    setEditingSymptomMap({ symptom: '', diseases: [] });
                    setShowSymptomMapDialog(true);
                  }}
                  className="bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
                >
                  <Plus className="w-4 h-4 mr-1" />
                  新增
                </Button> : null}
                {canEdit && selectedSymptomMaps.length > 0 && (
                  <Button
                    onClick={deleteSymptomMaps}
                    variant="outline"
                    className="border-red-500/50 text-red-400 hover:bg-red-500/10"
                  >
                    <Trash2 className="w-4 h-4 mr-1" />
                    删除所选
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
                  <Input
                    placeholder="搜索症状..."
                    value={symptomMapFilter}
                    onChange={(e) => setSymptomMapFilter(e.target.value)}
                    className="pl-10 bg-white/5 border-white/20 text-white focus:border-[#c8f7c5]"
                  />
                </div>
                
                <div className="grid gap-3">
                  {filteredSymptomMaps.map((map) => (
                    <div key={map.symptom} className="bg-white/5 rounded-xl p-4 border border-white/10 flex items-start justify-between">
                      <div className="flex items-start gap-3">
                        <Checkbox
                          checked={selectedSymptomMaps.includes(map.symptom)}
                          onCheckedChange={(v) => {
                            if (v) setSelectedSymptomMaps([...selectedSymptomMaps, map.symptom]);
                            else setSelectedSymptomMaps(selectedSymptomMaps.filter(s => s !== map.symptom));
                          }}
                          className="border-white/30 mt-1"
                        />
                        <div>
                          <Badge className="bg-white/10 text-white mb-2">{map.symptom}</Badge>
                          <div className="flex flex-wrap gap-2">
                            {map.diseases.map((disease, idx) => (
                              <span key={idx} className="text-sm text-[#c8f7c5]">{disease}</span>
                            ))}
                          </div>
                        </div>
                      </div>
                      {canEdit ? <Button
                        onClick={() => {
                          setSymptomDialogMode('edit');
                          setEditingSymptomOriginalName(map.symptom);
                          setEditingSymptomMap(map);
                          setShowSymptomMapDialog(true);
                        }}
                        variant="ghost"
                        size="sm"
                        className="text-[#c8f7c5] hover:bg-[#c8f7c5]/10"
                      >
                        编辑
                      </Button> : <span className="text-white/40 text-xs">只读</span>}
                    </div>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Disease Dialog */}
      <Dialog open={showDiseaseDialog} onOpenChange={setShowDiseaseDialog}>
        <DialogContent className="bg-[#1a1a1a] border-white/20 text-white max-w-lg">
          <DialogHeader>
            <DialogTitle>{diseaseDialogMode === 'edit' ? '编辑病害' : '新增病害'}</DialogTitle>
          </DialogHeader>
          {editingDisease && (
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label>病害名称</Label>
                <Input
                  value={editingDisease.name}
                  onChange={(e) => setEditingDisease({ ...editingDisease, name: e.target.value })}
                  disabled={diseaseDialogMode === 'edit'}
                  className="bg-white/5 border-white/20 text-white focus:border-[#c8f7c5]"
                />
              </div>
              <div className="space-y-2">
                <Label>描述</Label>
                <textarea
                  value={editingDisease.description}
                  onChange={(e) => setEditingDisease({ ...editingDisease, description: e.target.value })}
                  rows={4}
                  className="w-full bg-white/5 border border-white/20 rounded-lg p-3 text-white focus:border-[#c8f7c5] outline-none resize-none"
                />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowDiseaseDialog(false)}
              className="border-white/20 text-white hover:bg-white/10"
            >
              取消
            </Button>
            <Button
              onClick={saveDisease}
              disabled={!editingDisease?.name || !editingDisease?.description}
              className="bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
            >
              <Save className="w-4 h-4 mr-1" />
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Treatment Dialog */}
      <Dialog open={showTreatmentDialog} onOpenChange={setShowTreatmentDialog}>
        <DialogContent className="bg-[#1a1a1a] border-white/20 text-white max-w-lg">
          <DialogHeader>
            <DialogTitle>{editingTreatment && treatments.find(t => t.disease === editingTreatment.disease) ? '编辑治疗方案' : '新增治疗方案'}</DialogTitle>
          </DialogHeader>
          {editingTreatment && (
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label>病害</Label>
                <select
                  value={editingTreatment.disease}
                  onChange={(e) => setEditingTreatment({ ...editingTreatment, disease: e.target.value })}
                  disabled={treatments.find(t => t.disease === editingTreatment.disease) !== undefined}
                  className="w-full bg-white/5 border border-white/20 rounded-lg px-3 py-2 text-white focus:border-[#c8f7c5] outline-none"
                >
                  <option value="" className="bg-[#1a1a1a]">请选择病害</option>
                  {diseases.map((disease) => (
                    <option key={disease.name} value={disease.name} className="bg-[#1a1a1a]">
                      {disease.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-2">
                <Label>治疗方案</Label>
                <textarea
                  value={editingTreatment.treatment}
                  onChange={(e) => setEditingTreatment({ ...editingTreatment, treatment: e.target.value })}
                  rows={3}
                  className="w-full bg-white/5 border border-white/20 rounded-lg p-3 text-white focus:border-[#c8f7c5] outline-none resize-none"
                />
              </div>
              <div className="space-y-2">
                <Label>预防措施</Label>
                <textarea
                  value={editingTreatment.prevention}
                  onChange={(e) => setEditingTreatment({ ...editingTreatment, prevention: e.target.value })}
                  rows={3}
                  className="w-full bg-white/5 border border-white/20 rounded-lg p-3 text-white focus:border-[#c8f7c5] outline-none resize-none"
                />
              </div>
              <div className="space-y-2">
                <Label>成分关键词（逗号分隔）</Label>
                <Input
                  value={(editingTreatment.ingredients || []).join(',')}
                  onChange={(e) => setEditingTreatment({
                    ...editingTreatment,
                    ingredients: e.target.value.split(',').map((item) => item.trim()).filter(Boolean),
                  })}
                  className="bg-white/5 border-white/20 text-white focus:border-[#c8f7c5]"
                />
              </div>
              <div className="space-y-2">
                <button
                  type="button"
                  onClick={() => setShowActionsEditor((v) => !v)}
                  className="text-xs text-[#c8f7c5] hover:underline"
                >
                  {showActionsEditor ? '收起 actions JSON 编辑器' : '展开 actions JSON 编辑器'}
                </button>
                {showActionsEditor ? (
                  <textarea
                    value={editingTreatmentActionsJson}
                    onChange={(e) => setEditingTreatmentActionsJson(e.target.value)}
                    rows={12}
                    className="w-full font-mono text-xs bg-white/5 border border-white/20 rounded-lg p-3 text-white focus:border-[#c8f7c5] outline-none resize-y"
                  />
                ) : null}
                {editingTreatmentActionsError ? <p className="text-xs text-red-400">{editingTreatmentActionsError}</p> : null}
              </div>
            </div>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowTreatmentDialog(false)}
              className="border-white/20 text-white hover:bg-white/10"
            >
              取消
            </Button>
            <Button
              onClick={saveTreatment}
              disabled={!editingTreatment?.disease}
              className="bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
            >
              <Save className="w-4 h-4 mr-1" />
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Rule Dialog */}
      <Dialog open={showRuleDialog} onOpenChange={setShowRuleDialog}>
        <DialogContent className="bg-[#1a1a1a] border-white/20 text-white max-w-lg">
          <DialogHeader>
            <DialogTitle>{editingRule?.rule_id ? '编辑规则' : '新增规则'}</DialogTitle>
          </DialogHeader>
          {editingRule && (
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label>作物类型</Label>
                <Input
                  value={editingRule.crop_type}
                  onChange={(e) => setEditingRule({ ...editingRule, crop_type: e.target.value })}
                  className="bg-white/5 border-white/20 text-white focus:border-[#c8f7c5]"
                />
              </div>
              <div className="space-y-2">
                <Label>症状</Label>
                <Input
                  value={editingRule.symptoms}
                  onChange={(e) => setEditingRule({ ...editingRule, symptoms: e.target.value })}
                  className="bg-white/5 border-white/20 text-white focus:border-[#c8f7c5]"
                />
              </div>
              <div className="space-y-2">
                <Label>病害</Label>
                <select
                  value={editingRule.disease}
                  onChange={(e) => setEditingRule({ ...editingRule, disease: e.target.value })}
                  className="w-full bg-white/5 border border-white/20 rounded-lg px-3 py-2 text-white focus:border-[#c8f7c5] outline-none"
                >
                  <option value="" className="bg-[#1a1a1a]">请选择病害</option>
                  {diseases.map((disease) => (
                    <option key={disease.name} value={disease.name} className="bg-[#1a1a1a]">
                      {disease.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-2">
                <Label>置信度 (0-1)</Label>
                <Input
                  type="number"
                  step="0.01"
                  min="0"
                  max="1"
                  value={editingRule.confidence}
                  onChange={(e) => setEditingRule({ ...editingRule, confidence: parseFloat(e.target.value) || 0 })}
                  className="bg-white/5 border-white/20 text-white focus:border-[#c8f7c5]"
                />
              </div>
              <div className="space-y-2">
                <Label>依据</Label>
                <Input
                  value={editingRule.evidence}
                  onChange={(e) => setEditingRule({ ...editingRule, evidence: e.target.value })}
                  className="bg-white/5 border-white/20 text-white focus:border-[#c8f7c5]"
                />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowRuleDialog(false)}
              className="border-white/20 text-white hover:bg-white/10"
            >
              取消
            </Button>
            <Button
              onClick={saveRule}
              disabled={!editingRule?.crop_type || !editingRule?.symptoms || !editingRule?.disease}
              className="bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
            >
              <Save className="w-4 h-4 mr-1" />
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Symptom Map Dialog */}
      <Dialog open={showSymptomMapDialog} onOpenChange={setShowSymptomMapDialog}>
        <DialogContent className="bg-[#1a1a1a] border-white/20 text-white max-w-lg">
          <DialogHeader>
            <DialogTitle>{symptomDialogMode === 'edit' ? '编辑映射' : '新增映射'}</DialogTitle>
          </DialogHeader>
          {editingSymptomMap && (
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label>症状</Label>
                <Input
                  value={editingSymptomMap.symptom}
                  onChange={(e) => setEditingSymptomMap({ ...editingSymptomMap, symptom: e.target.value })}
                  disabled={symptomDialogMode === 'edit'}
                  className="bg-white/5 border-white/20 text-white focus:border-[#c8f7c5]"
                />
              </div>
              <div className="space-y-2">
                <Label>关联病害（可多选）</Label>
                <div className="max-h-44 overflow-y-auto rounded-lg border border-white/20 bg-white/5 p-3 space-y-2">
                  {diseases.map((disease) => {
                    const checked = editingSymptomMap.diseases.includes(disease.name);
                    return (
                      <label key={disease.name} className="flex items-center gap-2 text-sm text-white/80 cursor-pointer">
                        <Checkbox
                          checked={checked}
                          onCheckedChange={(v) => {
                            const nextDiseases = v
                              ? [...editingSymptomMap.diseases, disease.name]
                              : editingSymptomMap.diseases.filter((item) => item !== disease.name);
                            setEditingSymptomMap({ ...editingSymptomMap, diseases: nextDiseases });
                          }}
                          className="border-white/30"
                        />
                        <span>{disease.name}</span>
                      </label>
                    );
                  })}
                  {diseases.length === 0 && (
                    <p className="text-sm text-white/50">暂无病害，请先在“病害及描述”中新增病害。</p>
                  )}
                </div>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowSymptomMapDialog(false)}
              className="border-white/20 text-white hover:bg-white/10"
            >
              取消
            </Button>
            <Button
              onClick={saveSymptomMap}
              disabled={!editingSymptomMap?.symptom || editingSymptomMap?.diseases.length === 0}
              className="bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
            >
              <Save className="w-4 h-4 mr-1" />
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Disease Detail Dialog */}
      <Dialog open={showDiseaseDetailDialog} onOpenChange={setShowDiseaseDetailDialog}>
        <DialogContent className="bg-[#1a1a1a] border-white/20 text-white max-w-2xl">
          <DialogHeader>
            <DialogTitle className="text-white">病害知识详情</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            {detailLoading && <p className="text-white/70 text-sm">正在加载病害详情...</p>}
            {!detailLoading && detailError && <p className="text-red-300 text-sm">{detailError}</p>}
            {!detailLoading && !detailError && focusDiseaseDetail && (
              <div className="space-y-4 text-sm">
                <div>
                  <div className="text-white/60 mb-1">病害名称</div>
                  <div className="text-[#c8f7c5] font-semibold text-lg">{focusDiseaseDetail.name}</div>
                </div>
                <div>
                  <div className="text-white/60 mb-1">病害描述</div>
                  <div className="text-white whitespace-pre-wrap">{focusDiseaseDetail.description || '暂无描述'}</div>
                </div>
                <div>
                  <div className="text-white/60 mb-1">治疗建议</div>
                  <div className="text-white whitespace-pre-wrap">{focusDiseaseDetail.treatment || '暂无治疗建议'}</div>
                </div>
                <div>
                  <div className="text-white/60 mb-1">预防建议</div>
                  <div className="text-white whitespace-pre-wrap">{focusDiseaseDetail.prevention || '暂无预防建议'}</div>
                </div>
                {Array.isArray(focusDiseaseDetail.ingredients) && focusDiseaseDetail.ingredients.length > 0 && (
                  <div>
                    <div className="text-white/60 mb-1">有效成分</div>
                    <div className="flex flex-wrap gap-2">
                      {focusDiseaseDetail.ingredients.map((item) => (
                        <Badge key={item} className="bg-[#c8f7c5]/20 text-[#c8f7c5] border border-[#c8f7c5]/40">{item}</Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              className="border-white/20 text-white hover:bg-white/10"
              onClick={clearFocusDisease}
            >
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
