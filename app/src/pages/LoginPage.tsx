import { useMemo, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { normalizeAuthUserFromPayload, type AuthUser } from '@/auth';

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

  const usernameHint = useMemo(() => {
    const trimmed = username.trim();
    if (!trimmed) return '';
    if (trimmed.length < 3 || trimmed.length > 32) return '用户名长度建议为 3~32 位';
    if (!/^[A-Za-z0-9_.-]+$/.test(trimmed)) return '用户名建议仅使用字母、数字、下划线、点、短横线';
    return '用户名格式可用';
  }, [username]);

  const disabled = useMemo(() => {
    if (loading) return true;
    if (mode === 'login') return !identifier.trim();
    return !username.trim() || !displayName.trim() || !password || !confirmPassword;
  }, [mode, loading, identifier, username, displayName, password, confirmPassword]);

  const normalizeInputs = () => {
    setIdentifier((prev) => prev.trim());
    setUsername((prev) => prev.trim());
    setDisplayName((prev) => prev.trim());
  };

  const handleSubmit = async () => {
    normalizeInputs();
    if (disabled) return;
    setLoading(true);
    setError('');
    try {
      if (mode === 'register' && password !== confirmPassword) {
        throw new Error('两次输入的密码不一致');
      }
      if (mode === 'register' && password.length < 6) {
        throw new Error('密码长度不能少于 6 位');
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
      const nextUser = normalizeAuthUserFromPayload(data, {
        userId: identifier.trim(),
        displayName: displayName.trim() || identifier.trim(),
        role: 'USER',
        linkedFarmerId: null,
      });
      if (!nextUser) throw new Error(mode === 'login' ? '登录返回数据异常' : '注册返回数据异常');
      onLogin(nextUser);
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
                  onBlur={() => setIdentifier((prev) => prev.trim())}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      void handleSubmit();
                    }
                  }}
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
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      void handleSubmit();
                    }
                  }}
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
                  onBlur={() => setUsername((prev) => prev.trim())}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      void handleSubmit();
                    }
                  }}
                  placeholder="请输入用户名"
                  className="bg-white/5 border-white/20 text-white"
                />
                {usernameHint ? <p className={`text-xs ${usernameHint === '用户名格式可用' ? 'text-emerald-300' : 'text-amber-300'}`}>{usernameHint}</p> : null}
              </div>
              <div className="space-y-2">
                <Label className="text-white/80">显示名</Label>
                <Input
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  onBlur={() => setDisplayName((prev) => prev.trim())}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      void handleSubmit();
                    }
                  }}
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
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      void handleSubmit();
                    }
                  }}
                  placeholder="请输入密码"
                  className="bg-white/5 border-white/20 text-white"
                />
                {password && password.length < 6 ? <p className="text-xs text-amber-300">密码长度至少 6 位</p> : null}
              </div>
              <div className="space-y-2">
                <Label className="text-white/80">确认密码</Label>
                <Input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      void handleSubmit();
                    }
                  }}
                  placeholder="请再次输入密码"
                  className="bg-white/5 border-white/20 text-white"
                />
                {confirmPassword && confirmPassword !== password ? <p className="text-xs text-amber-300">两次输入的密码不一致</p> : null}
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
