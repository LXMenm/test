import { useState, useEffect } from 'react';
import { Users, Plus, RefreshCw, Save, Trash2, MapPin, Sprout, Ban } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { cn } from '@/lib/utils';

interface FarmerProfile {
  farmer_id: string;
  name: string;
  active_base_id: string;
  confirm_when_low_confidence: boolean;
  schema_version: string;
  updated_at: string;
  constraints: {
    prefer_organic: boolean;
    harvest_window_days: number;
    banned_ingredients: string[];
  };
  bases: Array<{
    base_id: string;
    name: string;
    location: string;
    province: string;
    facility_type: string;
    environment: string;
    growth_stage: string;
    notes: string;
  }>;
}

export function ProfilesPage() {
  const [profiles, setProfiles] = useState<FarmerProfile[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<FarmerProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [newProfileName, setNewProfileName] = useState('');
  const [editedProfile, setEditedProfile] = useState<FarmerProfile | null>(null);
  const [newIngredient, setNewIngredient] = useState('');
  const [showAddBaseDialog, setShowAddBaseDialog] = useState(false);
  const [newBaseId, setNewBaseId] = useState('');

  const fetchProfiles = async () => {
    setLoading(true);
    try {
      const resp = await fetch('/api/profiles');
      const data = await resp.json();
      setProfiles(data.profiles || []);
    } catch (error) {
      console.error('Failed to fetch profiles:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchProfileDetail = async (farmerId: string) => {
    try {
      const resp = await fetch(`/api/profiles/${farmerId}`);
      const data = await resp.json();
      setSelectedProfile(data);
      setEditedProfile(JSON.parse(JSON.stringify(data)));
    } catch (error) {
      console.error('Failed to fetch profile detail:', error);
    }
  };

  const saveProfile = async () => {
    if (!editedProfile) return;
    
    try {
      const resp = await fetch(`/api/profiles/${editedProfile.farmer_id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editedProfile)
      });
      
      if (resp.ok) {
        fetchProfiles();
        setSelectedProfile(editedProfile);
      }
    } catch (error) {
      console.error('Failed to save profile:', error);
    }
  };

  const createProfile = async () => {
    if (!newProfileName.trim()) return;
    
    try {
      const resp = await fetch('/api/profiles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newProfileName,
          confirm_when_low_confidence: true,
          constraints: {
            prefer_organic: false,
            harvest_window_days: 30,
            banned_ingredients: []
          }
        })
      });
      
      const data = await resp.json();
      if (data.id) {
        fetchProfiles();
        fetchProfileDetail(data.id);
        setShowAddDialog(false);
        setNewProfileName('');
      }
    } catch (error) {
      console.error('Failed to create profile:', error);
    }
  };

  const deleteProfile = async () => {
    if (!selectedProfile) return;
    
    try {
      const resp = await fetch(`/api/profiles/${selectedProfile.farmer_id}`, {
        method: 'DELETE'
      });
      
      if (resp.ok) {
        setSelectedProfile(null);
        setEditedProfile(null);
        fetchProfiles();
      }
    } catch (error) {
      console.error('Failed to delete profile:', error);
    }
  };

  const addIngredient = () => {
    if (!newIngredient.trim() || !editedProfile) return;
    
    setEditedProfile({
      ...editedProfile,
      constraints: {
        ...editedProfile.constraints,
        banned_ingredients: [...editedProfile.constraints.banned_ingredients, newIngredient.trim()]
      }
    });
    setNewIngredient('');
  };

  const removeIngredient = (idx: number) => {
    if (!editedProfile) return;
    
    setEditedProfile({
      ...editedProfile,
      constraints: {
        ...editedProfile.constraints,
        banned_ingredients: editedProfile.constraints.banned_ingredients.filter((_, i) => i !== idx)
      }
    });
  };

  const addBase = () => {
    if (!newBaseId.trim() || !editedProfile) return;
    
    setEditedProfile({
      ...editedProfile,
      bases: [...editedProfile.bases, {
        base_id: newBaseId,
        name: '',
        location: '',
        province: '',
        facility_type: '',
        environment: '',
        growth_stage: '',
        notes: ''
      }]
    });
    setShowAddBaseDialog(false);
    setNewBaseId('');
  };

  const removeBase = (idx: number) => {
    if (!editedProfile) return;
    
    setEditedProfile({
      ...editedProfile,
      bases: editedProfile.bases.filter((_, i) => i !== idx)
    });
  };

  useEffect(() => {
    fetchProfiles();
  }, []);

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-white">
            农户<span className="text-[#c8f7c5]">档案管理</span>
          </h1>
          <p className="text-white/60 mt-1">管理农户信息、治疗约束与基地数据</p>
        </div>
        <Button
          onClick={() => setShowAddDialog(true)}
          className="bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
        >
          <Plus className="w-4 h-4 mr-2" />
          新增农户
        </Button>
      </div>

      <div className="grid lg:grid-cols-4 gap-6">
        {/* Profile List */}
        <Card className="glass-card lg:col-span-1">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-white flex items-center gap-2">
              <Users className="w-5 h-5 text-[#c8f7c5]" />
              农户列表
            </CardTitle>
            <Button
              variant="ghost"
              size="sm"
              onClick={fetchProfiles}
              disabled={loading}
              className="text-white/60 hover:text-white"
            >
              <RefreshCw className={cn("w-4 h-4", loading && "animate-spin")} />
            </Button>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {profiles.map((profile) => (
                <div
                  key={profile.farmer_id}
                  onClick={() => fetchProfileDetail(profile.farmer_id)}
                  className={cn(
                    "p-3 rounded-xl cursor-pointer transition-all duration-300",
                    selectedProfile?.farmer_id === profile.farmer_id
                      ? "bg-[#c8f7c5]/20 border border-[#c8f7c5]/50"
                      : "bg-white/5 hover:bg-white/10 border border-transparent"
                  )}
                >
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 bg-[#c8f7c5]/20 rounded-full flex items-center justify-center">
                      <span className="text-[#c8f7c5] text-xs font-bold">
                        {profile.name.charAt(0)}
                      </span>
                    </div>
                    <div>
                      <p className="text-white font-medium">{profile.name}</p>
                      <p className="text-white/40 text-xs">{profile.farmer_id}</p>
                    </div>
                  </div>
                </div>
              ))}
              {profiles.length === 0 && (
                <div className="text-center py-8 text-white/40">
                  <Users className="w-10 h-10 mx-auto mb-2 opacity-50" />
                  <p className="text-sm">暂无农户档案</p>
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Profile Detail */}
        <Card className="glass-card lg:col-span-3">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-white">
              {selectedProfile ? `当前农户: ${selectedProfile.farmer_id}` : '请选择农户'}
            </CardTitle>
            {selectedProfile && editedProfile && (
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => fetchProfileDetail(selectedProfile.farmer_id)}
                  className="border-white/20 text-white hover:bg-white/10"
                >
                  <RefreshCw className="w-4 h-4" />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={saveProfile}
                  className="border-[#c8f7c5]/50 text-[#c8f7c5] hover:bg-[#c8f7c5]/10"
                >
                  <Save className="w-4 h-4 mr-1" />
                  保存
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={deleteProfile}
                  className="border-red-500/50 text-red-400 hover:bg-red-500/10"
                >
                  <Trash2 className="w-4 h-4" />
                </Button>
              </div>
            )}
          </CardHeader>
          <CardContent>
            {editedProfile ? (
              <div className="space-y-6 animate-fadeIn">
                {/* Basic Info */}
                <div>
                  <h3 className="text-[#c8f7c5] font-medium mb-4 flex items-center gap-2">
                    <Users className="w-4 h-4" />
                    农户基本信息
                  </h3>
                  <div className="grid sm:grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label className="text-white/60">农户ID</Label>
                      <Input
                        value={editedProfile.farmer_id}
                        disabled
                        className="bg-white/5 border-white/20 text-white/60"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-white/60">农户姓名</Label>
                      <Input
                        value={editedProfile.name}
                        onChange={(e) => setEditedProfile({ ...editedProfile, name: e.target.value })}
                        className="bg-white/5 border-white/20 text-white focus:border-[#c8f7c5]"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-white/60">当前基地</Label>
                      <Select
                        value={editedProfile.active_base_id}
                        onValueChange={(v) => setEditedProfile({ ...editedProfile, active_base_id: v })}
                      >
                        <SelectTrigger className="bg-white/5 border-white/20 text-white">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-[#1a1a1a] border-white/20">
                          {editedProfile.bases.map((base) => (
                            <SelectItem key={base.base_id} value={base.base_id}>
                              {base.name || base.base_id}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label className="text-white/60">档案版本</Label>
                      <Input
                        value={editedProfile.schema_version}
                        disabled
                        className="bg-white/5 border-white/20 text-white/60"
                      />
                    </div>
                    <div className="flex items-center gap-2">
                      <Checkbox
                        checked={editedProfile.confirm_when_low_confidence}
                        onCheckedChange={(v) => setEditedProfile({ ...editedProfile, confirm_when_low_confidence: v as boolean })}
                        className="border-white/30 data-[state=checked]:bg-[#c8f7c5] data-[state=checked]:text-black"
                      />
                      <Label className="text-white/80">低置信度需确认</Label>
                    </div>
                  </div>
                </div>

                <Separator className="bg-white/10" />

                {/* Constraints */}
                <div>
                  <h3 className="text-[#c8f7c5] font-medium mb-4 flex items-center gap-2">
                    <Ban className="w-4 h-4" />
                    治疗约束
                  </h3>
                  <div className="space-y-4">
                    <div className="flex items-center gap-2">
                      <Checkbox
                        checked={editedProfile.constraints.prefer_organic}
                        onCheckedChange={(v) => setEditedProfile({
                          ...editedProfile,
                          constraints: { ...editedProfile.constraints, prefer_organic: v as boolean }
                        })}
                        className="border-white/30 data-[state=checked]:bg-[#c8f7c5] data-[state=checked]:text-black"
                      />
                      <Label className="text-white/80">有机/低残留偏好</Label>
                    </div>
                    <div className="space-y-2">
                      <Label className="text-white/60">距离采收期（天）</Label>
                      <Input
                        type="number"
                        value={editedProfile.constraints.harvest_window_days}
                        onChange={(e) => setEditedProfile({
                          ...editedProfile,
                          constraints: { ...editedProfile.constraints, harvest_window_days: parseInt(e.target.value) || 0 }
                        })}
                        className="bg-white/5 border-white/20 text-white focus:border-[#c8f7c5]"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-white/60">禁用成分关键词</Label>
                      <div className="flex gap-2">
                        <Input
                          placeholder="输入成分"
                          value={newIngredient}
                          onChange={(e) => setNewIngredient(e.target.value)}
                          onKeyPress={(e) => e.key === 'Enter' && addIngredient()}
                          className="bg-white/5 border-white/20 text-white focus:border-[#c8f7c5]"
                        />
                        <Button
                          onClick={addIngredient}
                          variant="outline"
                          className="border-white/20 text-white hover:bg-white/10"
                        >
                          添加
                        </Button>
                      </div>
                      <div className="flex flex-wrap gap-2 mt-2">
                        {editedProfile.constraints.banned_ingredients.map((ing, idx) => (
                          <Badge
                            key={idx}
                            variant="outline"
                            className="border-red-400/50 text-red-400 cursor-pointer hover:bg-red-400/10"
                            onClick={() => removeIngredient(idx)}
                          >
                            {ing} ×
                          </Badge>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>

                <Separator className="bg-white/10" />

                {/* Bases */}
                <div>
                  <h3 className="text-[#c8f7c5] font-medium mb-4 flex items-center gap-2">
                    <MapPin className="w-4 h-4" />
                    基地信息
                  </h3>
                  <div className="space-y-4">
                    <div className="flex gap-2">
                      <Button
                        onClick={() => setShowAddBaseDialog(true)}
                        variant="outline"
                        size="sm"
                        className="border-[#c8f7c5]/50 text-[#c8f7c5] hover:bg-[#c8f7c5]/10"
                      >
                        <Plus className="w-4 h-4 mr-1" />
                        新增基地
                      </Button>
                    </div>
                    
                    {editedProfile.bases.map((base, idx) => (
                      <div key={base.base_id} className="bg-white/5 rounded-xl p-4 space-y-3">
                        <div className="flex items-center justify-between">
                          <Badge className="bg-[#c8f7c5]/20 text-[#c8f7c5]">{base.base_id}</Badge>
                          <Button
                            onClick={() => removeBase(idx)}
                            variant="ghost"
                            size="sm"
                            className="text-red-400 hover:text-red-300 hover:bg-red-400/10"
                          >
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </div>
                        <div className="grid sm:grid-cols-2 gap-3">
                          <div className="space-y-1">
                            <Label className="text-white/60 text-xs">基地名称</Label>
                            <Input
                              value={base.name}
                              onChange={(e) => {
                                const newBases = [...editedProfile.bases];
                                newBases[idx].name = e.target.value;
                                setEditedProfile({ ...editedProfile, bases: newBases });
                              }}
                              className="bg-white/10 border-white/20 text-white text-sm"
                            />
                          </div>
                          <div className="space-y-1">
                            <Label className="text-white/60 text-xs">位置/地址</Label>
                            <Input
                              value={base.location}
                              onChange={(e) => {
                                const newBases = [...editedProfile.bases];
                                newBases[idx].location = e.target.value;
                                setEditedProfile({ ...editedProfile, bases: newBases });
                              }}
                              className="bg-white/10 border-white/20 text-white text-sm"
                            />
                          </div>
                          <div className="space-y-1">
                            <Label className="text-white/60 text-xs">省份</Label>
                            <Input
                              value={base.province}
                              onChange={(e) => {
                                const newBases = [...editedProfile.bases];
                                newBases[idx].province = e.target.value;
                                setEditedProfile({ ...editedProfile, bases: newBases });
                              }}
                              className="bg-white/10 border-white/20 text-white text-sm"
                            />
                          </div>
                          <div className="space-y-1">
                            <Label className="text-white/60 text-xs">设施类型</Label>
                            <Input
                              value={base.facility_type}
                              onChange={(e) => {
                                const newBases = [...editedProfile.bases];
                                newBases[idx].facility_type = e.target.value;
                                setEditedProfile({ ...editedProfile, bases: newBases });
                              }}
                              className="bg-white/10 border-white/20 text-white text-sm"
                            />
                          </div>
                          <div className="space-y-1">
                            <Label className="text-white/60 text-xs">环境描述</Label>
                            <Input
                              value={base.environment}
                              onChange={(e) => {
                                const newBases = [...editedProfile.bases];
                                newBases[idx].environment = e.target.value;
                                setEditedProfile({ ...editedProfile, bases: newBases });
                              }}
                              className="bg-white/10 border-white/20 text-white text-sm"
                            />
                          </div>
                          <div className="space-y-1">
                            <Label className="text-white/60 text-xs">生长阶段</Label>
                            <Input
                              value={base.growth_stage}
                              onChange={(e) => {
                                const newBases = [...editedProfile.bases];
                                newBases[idx].growth_stage = e.target.value;
                                setEditedProfile({ ...editedProfile, bases: newBases });
                              }}
                              className="bg-white/10 border-white/20 text-white text-sm"
                            />
                          </div>
                        </div>
                      </div>
                    ))}
                    
                    {editedProfile.bases.length === 0 && (
                      <div className="text-center py-6 text-white/40">
                        <MapPin className="w-8 h-8 mx-auto mb-2 opacity-50" />
                        <p className="text-sm">暂无基地信息</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <div className="text-center py-16 text-white/40">
                <Sprout className="w-16 h-16 mx-auto mb-4 opacity-50" />
                <p>从左侧列表选择农户查看详情</p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Add Profile Dialog */}
      <Dialog open={showAddDialog} onOpenChange={setShowAddDialog}>
        <DialogContent className="bg-[#1a1a1a] border-white/20 text-white">
          <DialogHeader>
            <DialogTitle>新增农户档案</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>农户姓名 <span className="text-red-400">*</span></Label>
              <Input
                placeholder="请输入农户姓名"
                value={newProfileName}
                onChange={(e) => setNewProfileName(e.target.value)}
                className="bg-white/5 border-white/20 text-white focus:border-[#c8f7c5]"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowAddDialog(false)}
              className="border-white/20 text-white hover:bg-white/10"
            >
              取消
            </Button>
            <Button
              onClick={createProfile}
              disabled={!newProfileName.trim()}
              className="bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
            >
              确认创建
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Add Base Dialog */}
      <Dialog open={showAddBaseDialog} onOpenChange={setShowAddBaseDialog}>
        <DialogContent className="bg-[#1a1a1a] border-white/20 text-white">
          <DialogHeader>
            <DialogTitle>新增基地</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>基地ID</Label>
              <Input
                placeholder="例如：B0002"
                value={newBaseId}
                onChange={(e) => setNewBaseId(e.target.value)}
                className="bg-white/5 border-white/20 text-white focus:border-[#c8f7c5]"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowAddBaseDialog(false)}
              className="border-white/20 text-white hover:bg-white/10"
            >
              取消
            </Button>
            <Button
              onClick={addBase}
              disabled={!newBaseId.trim()}
              className="bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
            >
              确定
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
