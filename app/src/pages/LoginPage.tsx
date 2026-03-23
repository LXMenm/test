import { useMemo, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import type { AuthUser } from '@/auth';

interface LoginPageProps {
  onLogin: (user: AuthUser) => void;
}

export function LoginPage({ onLogin }: LoginPageProps) {
  const [userId, setUserId] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const disabled = useMemo(() => !userId.trim() || loading, [userId, loading]);

  const handleSubmit = async () => {
    if (disabled) return;
    setLoading(true);
    setError('');
    try {
      const resp = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId.trim(), password }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || '登录失败'));
      onLogin({
        userId: String(data?.user_id || userId).trim(),
        displayName: String(data?.display_name || userId).trim(),
        role: String(data?.role || 'USER').toUpperCase() as AuthUser['role'],
        linkedFarmerId: typeof data?.linked_farmer_id === 'string' ? data.linked_farmer_id : null,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-black text-white flex items-center justify-center px-4">
      <Card className="w-full max-w-md glass-card">
        <CardHeader>
          <CardTitle className="text-white">账户登录（数据库校验）</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label className="text-white/80">账户 ID</Label>
            <Input
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              placeholder="例如：F0001 / E0001 / A0001"
              className="bg-white/5 border-white/20 text-white"
            />
          </div>
          <div className="space-y-2">
            <Label className="text-white/80">密码（演示默认 123456）</Label>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="请输入密码"
              className="bg-white/5 border-white/20 text-white"
            />
          </div>
          {error ? <p className="text-red-300 text-sm">{error}</p> : null}
          <Button
            disabled={disabled}
            onClick={() => { void handleSubmit(); }}
            className="w-full bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
          >
            {loading ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" />登录中...</> : '登录'}
          </Button>
          <p className="text-xs text-white/50">测试账户：F0001/F0002/E0001/E0002/A0001，默认密码 123456。</p>
        </CardContent>
      </Card>
    </div>
  );
}
