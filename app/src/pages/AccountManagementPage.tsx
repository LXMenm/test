import { useEffect, useState } from 'react';
import { Loader2, Plus, RefreshCcw, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

const ROLE_OPTIONS = ['USER', 'EXPERT', 'ADMIN'] as const;

type AccountRole = (typeof ROLE_OPTIONS)[number];

interface AdminAccountItem {
  user_id: string;
  username: string;
  display_name: string;
  role: AccountRole;
  status: string;
  farmer_id?: string;
}

interface NewAccountForm {
  username: string;
  display_name: string;
  password: string;
  role: AccountRole;
}

const DEFAULT_FORM: NewAccountForm = {
  username: '',
  display_name: '',
  password: '',
  role: 'USER',
};

export function AccountManagementPage() {
  const [items, setItems] = useState<AdminAccountItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [tip, setTip] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState<NewAccountForm>(DEFAULT_FORM);

  const loadAccounts = async () => {
    setLoading(true);
    setTip('');
    try {
      const resp = await fetch('/api/admin/accounts');
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '加载账号列表失败'));
      setItems(Array.isArray(data?.items) ? data.items : []);
    } catch (error) {
      console.error(error);
      setTip('加载账号列表失败，请稍后重试。');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadAccounts();
  }, []);

  const createAccount = async () => {
    const payload = {
      username: form.username.trim(),
      display_name: form.display_name.trim(),
      password: form.password,
      role: form.role,
    };
    if (!payload.username || !payload.display_name || !payload.password) {
      setTip('请完整填写用户名、显示名和初始密码。');
      return;
    }
    setSubmitting(true);
    setTip('');
    try {
      const resp = await fetch('/api/admin/accounts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '新增账号失败'));
      setTip('账号已创建，并自动生成对应空档案。');
      setCreateOpen(false);
      setForm(DEFAULT_FORM);
      await loadAccounts();
    } catch (error) {
      console.error(error);
      setTip(error instanceof Error ? error.message : '新增账号失败，请稍后重试。');
    } finally {
      setSubmitting(false);
    }
  };

  const updateRole = async (userId: string, role: AccountRole) => {
    try {
      const resp = await fetch(`/api/admin/accounts/${encodeURIComponent(userId)}/role`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '更新角色失败'));
      setTip(`账号 ${userId} 角色已更新为 ${role}。`);
      await loadAccounts();
    } catch (error) {
      console.error(error);
      setTip(error instanceof Error ? error.message : '更新角色失败，请稍后重试。');
    }
  };

  const deleteAccount = async (userId: string) => {
    if (!window.confirm(`确认删除账号 ${userId} 吗？这会同时删除对应档案。`)) return;
    try {
      const resp = await fetch(`/api/admin/accounts/${encodeURIComponent(userId)}`, {
        method: 'DELETE',
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '删除账号失败'));
      setTip(`账号 ${userId} 已删除，对应档案已同步删除。`);
      await loadAccounts();
    } catch (error) {
      console.error(error);
      setTip(error instanceof Error ? error.message : '删除账号失败，请稍后重试。');
    }
  };

  return (
    <Card className="glass-card">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-white">账号管理</CardTitle>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => { void loadAccounts(); }}>
            <RefreshCcw className="w-4 h-4 mr-1" />刷新列表
          </Button>
          <Button size="sm" className="bg-[#c8f7c5] text-black" onClick={() => setCreateOpen((prev) => !prev)}>
            <Plus className="w-4 h-4 mr-1" />新增账号
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 text-white">
        {tip ? <p className="text-sm text-[#c8f7c5]">{tip}</p> : null}
        {createOpen ? (
          <div className="rounded-xl border border-white/10 bg-white/5 p-4 space-y-3">
            <h3 className="text-sm font-semibold">新增账号</h3>
            <div className="grid md:grid-cols-4 gap-3">
              <div>
                <Label>用户名</Label>
                <Input value={form.username} onChange={(e) => setForm((prev) => ({ ...prev, username: e.target.value }))} className="bg-white/5 border-white/20 text-white" />
              </div>
              <div>
                <Label>显示名</Label>
                <Input value={form.display_name} onChange={(e) => setForm((prev) => ({ ...prev, display_name: e.target.value }))} className="bg-white/5 border-white/20 text-white" />
              </div>
              <div>
                <Label>初始密码</Label>
                <Input type="password" value={form.password} onChange={(e) => setForm((prev) => ({ ...prev, password: e.target.value }))} className="bg-white/5 border-white/20 text-white" />
              </div>
              <div>
                <Label>初始角色</Label>
                <Select value={form.role} onValueChange={(value) => setForm((prev) => ({ ...prev, role: value as AccountRole }))}>
                  <SelectTrigger className="bg-white/5 border-white/20 text-white"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {ROLE_OPTIONS.map((role) => <SelectItem key={role} value={role}>{role}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => setCreateOpen(false)}>取消</Button>
              <Button size="sm" className="bg-[#c8f7c5] text-black" onClick={() => { void createAccount(); }} disabled={submitting}>
                {submitting ? '创建中...' : '确认创建'}
              </Button>
            </div>
          </div>
        ) : null}

        <div className="rounded-xl border border-white/10 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-white/10 text-left">
              <tr>
                <th className="px-3 py-2">用户ID</th>
                <th className="px-3 py-2">用户名</th>
                <th className="px-3 py-2">显示名</th>
                <th className="px-3 py-2">角色</th>
                <th className="px-3 py-2">状态</th>
                <th className="px-3 py-2">操作</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td className="px-3 py-6 text-white/70" colSpan={6}><Loader2 className="w-4 h-4 animate-spin inline mr-2" />正在加载账号...</td>
                </tr>
              ) : null}
              {!loading && items.length === 0 ? (
                <tr><td className="px-3 py-6 text-white/60" colSpan={6}>暂无账号数据</td></tr>
              ) : null}
              {!loading ? items.map((item) => (
                <tr key={item.user_id} className="border-t border-white/10">
                  <td className="px-3 py-2">{item.user_id}</td>
                  <td className="px-3 py-2">{item.username}</td>
                  <td className="px-3 py-2">{item.display_name}</td>
                  <td className="px-3 py-2">
                    <Select value={item.role} onValueChange={(value) => { void updateRole(item.user_id, value as AccountRole); }}>
                      <SelectTrigger className="w-[132px] bg-white/5 border-white/20 text-white h-8"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {ROLE_OPTIONS.map((role) => <SelectItem key={role} value={role}>{role}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </td>
                  <td className="px-3 py-2">{item.status}</td>
                  <td className="px-3 py-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => { void deleteAccount(item.user_id); }}
                      className="border-red-500/40 text-red-300 hover:bg-red-500/10"
                    >
                      <Trash2 className="w-4 h-4 mr-1" />删除
                    </Button>
                  </td>
                </tr>
              )) : null}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
