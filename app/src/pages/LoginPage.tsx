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
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [username, setUsername] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const disabled = useMemo(() => {
    if (loading) return true;
    if (mode === 'login') return !identifier.trim();
    return !username.trim() || !displayName.trim() || !password || !confirmPassword;
  }, [mode, loading, identifier, username, displayName, password, confirmPassword]);

  const handleSubmit = async () => {
    if (disabled) return;
    setLoading(true);
    setError('');
    try {
      if (mode === 'register' && password !== confirmPassword) {
        throw new Error('两次输入的密码不一致');
      }

      const endpoint = mode === 'login' ? '/api/auth/login' : '/api/auth/register';
      const body = mode === 'login'
        ? { identifier: identifier.trim(), password }
        : {
          username: username.trim(),
          display_name: displayName.trim(),
          password,
        };
      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || (mode === 'login' ? '登录失败' : '注册失败')));
      const resolvedUserId = String(data?.user_id || (mode === 'login' ? identifier : '')).trim();
      const resolvedDisplayName = String(data?.display_name || (mode === 'login' ? identifier : displayName)).trim();
      onLogin({
        userId: resolvedUserId,
        displayName: resolvedDisplayName,
        role: String(data?.role || 'USER').toUpperCase() as AuthUser['role'],
        linkedFarmerId: typeof data?.linked_farmer_id === 'string' ? data.linked_farmer_id : null,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : mode === 'login' ? '登录失败' : '注册失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-black text-white flex items-center justify-center px-4">
      <Card className="w-full max-w-md glass-card">
        <CardHeader>
          <CardTitle className="text-white">账户{mode === 'login' ? '登录' : '注册'}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-2">
            <Button
              type="button"
              variant={mode === 'login' ? 'default' : 'outline'}
              className={mode === 'login' ? 'flex-1 bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]' : 'flex-1 border-white/20 text-white hover:bg-white/10'}
              onClick={() => {
                setMode('login');
                setError('');
              }}
            >
              登录
            </Button>
            <Button
              type="button"
              variant={mode === 'register' ? 'default' : 'outline'}
              className={mode === 'register' ? 'flex-1 bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]' : 'flex-1 border-white/20 text-white hover:bg-white/10'}
              onClick={() => {
                setMode('register');
                setError('');
              }}
            >
              注册
            </Button>
          </div>
          {mode === 'login' ? (
            <>
              <div className="space-y-2">
                <Label className="text-white/80">用户名或账户 ID</Label>
                <Input
                  value={identifier}
                  onChange={(e) => setIdentifier(e.target.value)}
                  placeholder="例如：F0001 / f0001"
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
            </>
          ) : (
            <>
              <div className="space-y-2">
                <Label className="text-white/80">用户名</Label>
                <Input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="请输入用户名"
                  className="bg-white/5 border-white/20 text-white"
                />
              </div>
              <div className="space-y-2">
                <Label className="text-white/80">显示名</Label>
                <Input
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="请输入显示名"
                  className="bg-white/5 border-white/20 text-white"
                />
              </div>
              <div className="space-y-2">
                <Label className="text-white/80">密码</Label>
                <Input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="请输入密码"
                  className="bg-white/5 border-white/20 text-white"
                />
              </div>
              <div className="space-y-2">
                <Label className="text-white/80">确认密码</Label>
                <Input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="请再次输入密码"
                  className="bg-white/5 border-white/20 text-white"
                />
              </div>
            </>
          )}
          {error ? <p className="text-red-300 text-sm">{error}</p> : null}
          <Button
            disabled={disabled}
            onClick={() => { void handleSubmit(); }}
            className="w-full bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
          >
            {loading ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" />{mode === 'login' ? '登录中...' : '注册中...'}</> : mode === 'login' ? '登录' : '注册并进入系统'}
          </Button>
          <p className="text-xs text-white/50">测试账户：F0001/F0002/E0001/E0002/A0001，默认密码 123456。</p>
        </CardContent>
      </Card>
    </div>
  );
}
