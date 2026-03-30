import { Fragment, useEffect, useState } from 'react';
import { Loader2, RefreshCcw, Trash2, UserPlus, Users } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { loadAuthUser, withAuthHeaders } from '@/auth';

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

interface ResetPasswordForm {
  password: string;
  confirmPassword: string;
}

const DEFAULT_FORM: NewAccountForm = {
  username: '',
  display_name: '',
  password: '',
  role: 'USER',
};

const DEFAULT_RESET_FORM: ResetPasswordForm = {
  password: '',
  confirmPassword: '',
};

export function AccountManagementPage() {
  const authUser = loadAuthUser();
  const [items, setItems] = useState<AdminAccountItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [tip, setTip] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState<NewAccountForm>(DEFAULT_FORM);
  const [resetTargetUserId, setResetTargetUserId] = useState('');
  const [resetForm, setResetForm] = useState<ResetPasswordForm>(DEFAULT_RESET_FORM);
  const [resetSubmitting, setResetSubmitting] = useState(false);

  const loadAccounts = async () => {
    setLoading(true);
    setTip('');
    try {
      const resp = await fetch('/api/admin/accounts', withAuthHeaders(undefined, authUser));
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
      const resp = await fetch('/api/admin/accounts', withAuthHeaders({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }, authUser));
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '新增账号失败'));
      setTip('账号已创建，并自动生成对应空档案。');
      setCreateOpen(false);
      setForm(DEFAULT_FORM);
      await loadAccounts();
      window.dispatchEvent(new CustomEvent('profiles:invalidate'));
    } catch (error) {
      console.error(error);
      setTip(error instanceof Error ? error.message : '新增账号失败，请稍后重试。');
    } finally {
      setSubmitting(false);
    }
  };

  const updateRole = async (userId: string, role: AccountRole) => {
    try {
      const resp = await fetch(`/api/admin/accounts/${encodeURIComponent(userId)}/role`, withAuthHeaders({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role }),
      }, authUser));
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
      const resp = await fetch(`/api/admin/accounts/${encodeURIComponent(userId)}`, withAuthHeaders({
        method: 'DELETE',
      }, authUser));
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '删除账号失败'));
      setTip(`账号 ${userId} 已删除，对应档案已同步删除。`);
      await loadAccounts();
      window.dispatchEvent(new CustomEvent('profiles:invalidate'));
    } catch (error) {
      console.error(error);
      setTip(error instanceof Error ? error.message : '删除账号失败，请稍后重试。');
    }
  };

  const updateStatus = async (userId: string, status: 'ACTIVE' | 'DISABLED') => {
    if (status === 'DISABLED' && authUser?.userId === userId) {
      setTip('不允许禁用当前登录管理员账号。');
      return;
    }
    try {
      const resp = await fetch(`/api/admin/accounts/${encodeURIComponent(userId)}/status`, withAuthHeaders({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      }, authUser));
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '更新状态失败'));
      setTip(`账号 ${userId} 状态已更新为 ${status}。`);
      await loadAccounts();
    } catch (error) {
      console.error(error);
      setTip(error instanceof Error ? error.message : '更新状态失败，请稍后重试。');
    }
  };

  const toggleResetPassword = (userId: string) => {
    if (resetTargetUserId === userId) {
      setResetTargetUserId('');
      setResetForm(DEFAULT_RESET_FORM);
      return;
    }
    setResetTargetUserId(userId);
    setResetForm(DEFAULT_RESET_FORM);
    setTip('');
  };

  const submitResetPassword = async (userId: string) => {
    const password = resetForm.password;
    const confirm_password = resetForm.confirmPassword;
    if (!password || !confirm_password) {
      setTip('请填写新密码和确认新密码。');
      return;
    }
    if (password.length < 6) {
      setTip('新密码长度不能少于 6 位。');
      return;
    }
    if (password !== confirm_password) {
      setTip('两次输入的新密码不一致。');
      return;
    }
    setResetSubmitting(true);
    setTip('');
    try {
      const resp = await fetch(`/api/admin/accounts/${encodeURIComponent(userId)}/reset-password`, withAuthHeaders({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password, confirm_password }),
      }, authUser));
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '重置密码失败'));
      setTip(`账号 ${userId} 密码已重置。`);
      setResetTargetUserId('');
      setResetForm(DEFAULT_RESET_FORM);
    } catch (error) {
      console.error(error);
      setTip(error instanceof Error ? error.message : '重置密码失败，请稍后重试。');
    } finally {
      setResetSubmitting(false);
    }
  };

  return (
    <div className="space-y-6 animate-fadeIn">
      <div>
        <h1 className="text-3xl font-bold text-white"><span className="text-[#c8f7c5]">账号管理</span></h1>
        <p className="text-white/60 mt-1">管理系统用户账号、角色权限和访问控制</p>
      </div>

      <Card className="glass-card">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-white flex items-center gap-2"><Users className="w-5 h-5 text-[#c8f7c5]" />账号列表</CardTitle>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => { void loadAccounts(); }} className="border-white/20 text-white hover:bg-white/10">
              <RefreshCcw className={cn('w-4 h-4', loading && 'animate-spin')} />
            </Button>
            <Button size="sm" className="bg-[#c8f7c5] text-black" onClick={() => setCreateOpen((prev) => !prev)}>
              <UserPlus className="w-4 h-4 mr-1" />新增账号
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {tip ? <div className="rounded-lg bg-[#c8f7c5]/10 border border-[#c8f7c5]/30 p-3 text-sm text-[#c8f7c5]">{tip}</div> : null}
          
          {createOpen ? (
            <div className="rounded-xl border border-white/10 bg-white/5 p-4 space-y-4">
              <h3 className="text-[#c8f7c5] font-medium flex items-center gap-2"><UserPlus className="w-4 h-4" />新增账号</h3>
              <div className="grid md:grid-cols-4 gap-4">
                <div className="space-y-2">
                  <Label className="text-white/60 text-sm">用户名</Label>
                  <Input 
                    value={form.username} 
                    onChange={(e) => setForm((prev) => ({ ...prev, username: e.target.value }))} 
                    className="bg-white/10 border-white/20 text-white"
                    placeholder="请输入用户名"
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-white/60 text-sm">显示名</Label>
                  <Input 
                    value={form.display_name} 
                    onChange={(e) => setForm((prev) => ({ ...prev, display_name: e.target.value }))} 
                    className="bg-white/10 border-white/20 text-white"
                    placeholder="请输入显示名"
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-white/60 text-sm">初始密码</Label>
                  <Input 
                    type="password" 
                    value={form.password} 
                    onChange={(e) => setForm((prev) => ({ ...prev, password: e.target.value }))} 
                    className="bg-white/10 border-white/20 text-white"
                    placeholder="请输入初始密码"
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-white/60 text-sm">初始角色</Label>
                  <Select value={form.role} onValueChange={(value) => setForm((prev) => ({ ...prev, role: value as AccountRole }))}>
                    <SelectTrigger className="bg-white/10 border-white/20 text-white"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {ROLE_OPTIONS.map((role) => <SelectItem key={role} value={role}>{role}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="outline" size="sm" onClick={() => setCreateOpen(false)} className="border-white/20 text-white hover:bg-white/10">取消</Button>
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
                  <th className="px-4 py-3 text-white/80">用户ID</th>
                  <th className="px-4 py-3 text-white/80">用户名</th>
                  <th className="px-4 py-3 text-white/80">显示名</th>
                  <th className="px-4 py-3 text-white/80">角色</th>
                  <th className="px-4 py-3 text-white/80">状态</th>
                  <th className="px-4 py-3 text-white/80 text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td className="px-4 py-8 text-white/70" colSpan={6}>
                      <div className="flex items-center justify-center gap-2">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>正在加载账号...</span>
                      </div>
                    </td>
                  </tr>
                ) : null}
                {!loading && items.length === 0 ? (
                  <tr>
                    <td className="px-4 py-8 text-white/60 text-center" colSpan={6}>
                      <div className="flex flex-col items-center gap-2">
                        <Users className="w-12 h-12 opacity-30" />
                        <span>暂无账号数据</span>
                      </div>
                    </td>
                  </tr>
                ) : null}
                {!loading ? items.map((item) => (
                  <Fragment key={item.user_id}>
                    <tr className="border-t border-white/10 hover:bg-white/5 transition-colors">
                      <td className="px-4 py-3 font-mono text-white/90">{item.user_id}</td>
                      <td className="px-4 py-3 text-white">{item.username}</td>
                      <td className="px-4 py-3 text-white">{item.display_name}</td>
                      <td className="px-4 py-3">
                        <Select value={item.role} onValueChange={(value) => { void updateRole(item.user_id, value as AccountRole); }}>
                          <SelectTrigger className="w-[132px] bg-white/10 border-white/20 text-white h-8">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {ROLE_OPTIONS.map((role) => <SelectItem key={role} value={role}>{role}</SelectItem>)}
                          </SelectContent>
                        </Select>
                      </td>
                      <td className="px-4 py-3">
                        <Badge
                          variant={item.status === 'ACTIVE' ? 'outline' : 'secondary'}
                          className={cn(
                            item.status === 'ACTIVE'
                              ? 'border-emerald-400/50 text-emerald-300 bg-emerald-900/20'
                              : 'border-red-400/50 text-red-300 bg-red-900/20'
                          )}
                        >
                          {item.status === 'ACTIVE' ? '正常' : '禁用'}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex justify-end gap-2">
                          {item.user_id === authUser?.userId ? null : (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => toggleResetPassword(item.user_id)}
                              className="border-sky-500/40 text-sky-300 hover:bg-sky-500/10 transition-all"
                            >
                              重置密码
                            </Button>
                          )}
                          {item.status === 'ACTIVE' ? (
                            item.user_id === authUser?.userId ? null : (
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => { void updateStatus(item.user_id, 'DISABLED'); }}
                                className="border-amber-500/40 text-amber-300 hover:bg-amber-500/10 transition-all"
                              >
                                禁用
                              </Button>
                            )
                          ) : (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => { void updateStatus(item.user_id, 'ACTIVE'); }}
                              className="border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/10 transition-all"
                            >
                              启用
                            </Button>
                          )}
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => { void deleteAccount(item.user_id); }}
                            className="border-red-500/40 text-red-300 hover:bg-red-500/10 transition-all"
                          >
                            <Trash2 className="w-4 h-4 mr-1" />删除
                          </Button>
                        </div>
                      </td>
                    </tr>
                    {resetTargetUserId === item.user_id ? (
                      <tr className="border-t border-white/10 bg-white/[0.03]">
                        <td colSpan={6} className="px-4 py-4">
                          <div className="grid md:grid-cols-3 gap-3 items-end">
                            <div className="space-y-2">
                              <Label className="text-white/60 text-sm">新密码（至少 6 位）</Label>
                              <Input
                                type="password"
                                value={resetForm.password}
                                onChange={(e) => setResetForm((prev) => ({ ...prev, password: e.target.value }))}
                                className="bg-white/10 border-white/20 text-white"
                              />
                            </div>
                            <div className="space-y-2">
                              <Label className="text-white/60 text-sm">确认新密码</Label>
                              <Input
                                type="password"
                                value={resetForm.confirmPassword}
                                onChange={(e) => setResetForm((prev) => ({ ...prev, confirmPassword: e.target.value }))}
                                className="bg-white/10 border-white/20 text-white"
                              />
                            </div>
                            <div className="flex justify-end gap-2">
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => toggleResetPassword(item.user_id)}
                                className="border-white/20 text-white hover:bg-white/10"
                                disabled={resetSubmitting}
                              >
                                取消
                              </Button>
                              <Button
                                size="sm"
                                className="bg-sky-300 text-black hover:bg-sky-200"
                                onClick={() => { void submitResetPassword(item.user_id); }}
                                disabled={resetSubmitting}
                              >
                                {resetSubmitting ? '提交中...' : '确认重置'}
                              </Button>
                            </div>
                          </div>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                )) : null}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
