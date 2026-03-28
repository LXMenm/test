import { useMemo, useState } from 'react';
import { Eye, Loader2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { normalizeAuthUserFromPayload, type AuthUser } from '@/auth';

interface LoginPageProps {
  onLogin: (user: AuthUser) => void;
}

interface PasswordFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  autoComplete?: string;
  inputName?: string;
  inputId?: string;
  hint?: string;
  hintClassName?: string;
  onEnter?: () => void;
}

function PasswordField({
  label,
  value,
  onChange,
  placeholder,
  autoComplete,
  inputName,
  inputId,
  hint,
  hintClassName,
  onEnter,
}: PasswordFieldProps) {
  const [revealed, setRevealed] = useState(false);

  const reveal = () => setRevealed(true);
  const hide = () => setRevealed(false);

  return (
    <div className="space-y-2">
      <Label htmlFor={inputId} className="text-white/80">{label}</Label>
      <div className="relative">
        <Input
          id={inputId}
          name={inputName}
          autoComplete={autoComplete}
          type={revealed ? 'text' : 'password'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && onEnter) {
              e.preventDefault();
              onEnter();
            }
          }}
          placeholder={placeholder}
          className="bg-white/5 border-white/20 text-white pr-10"
        />
        <button
          type="button"
          aria-label={revealed ? '松开后隐藏密码' : '按住显示密码'}
          onMouseDown={reveal}
          onMouseUp={hide}
          onMouseLeave={hide}
          onTouchStart={reveal}
          onTouchEnd={hide}
          onTouchCancel={hide}
          onBlur={hide}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-white/70 hover:text-white"
        >
          <Eye className="w-4 h-4" />
        </button>
      </div>
      {hint ? <p className={hintClassName || 'text-xs text-white/60'}>{hint}</p> : null}
    </div>
  );
}

export function LoginPage({ onLogin }: LoginPageProps) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [identifier, setIdentifier] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [username, setUsername] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [registerPassword, setRegisterPassword] = useState('');
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
    if (mode === 'login') return !identifier.trim() || !loginPassword;
    return !username.trim() || !displayName.trim() || !registerPassword || !confirmPassword;
  }, [mode, loading, identifier, loginPassword, username, displayName, registerPassword, confirmPassword]);

  const switchMode = (nextMode: 'login' | 'register') => {
    setMode(nextMode);
    setError('');
    if (nextMode === 'login') {
      setRegisterPassword('');
      setConfirmPassword('');
    } else {
      setLoginPassword('');
    }
  };

  const handleSubmit = async () => {
    const normalizedIdentifier = identifier.trim();
    const normalizedUsername = username.trim();
    const normalizedDisplayName = displayName.trim();
    if (loading) return;
    if (mode === 'login' && (!normalizedIdentifier || !loginPassword)) return;
    if (mode === 'register' && (!normalizedUsername || !normalizedDisplayName || !registerPassword || !confirmPassword)) return;

    setIdentifier(normalizedIdentifier);
    setUsername(normalizedUsername);
    setDisplayName(normalizedDisplayName);

    setLoading(true);
    setError('');
    try {
      if (mode === 'register' && registerPassword !== confirmPassword) {
        throw new Error('两次输入的密码不一致');
      }
      if (mode === 'register' && registerPassword.length < 6) {
        throw new Error('密码长度不能少于 6 位');
      }

      const endpoint = mode === 'login' ? '/api/auth/login' : '/api/auth/register';
      const body = mode === 'login'
        ? { identifier: normalizedIdentifier, password: loginPassword }
        : {
          username: normalizedUsername,
          display_name: normalizedDisplayName,
          password: registerPassword,
        };
      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(String(data?.detail || (mode === 'login' ? '登录失败' : '注册失败')));
      const nextUser = normalizeAuthUserFromPayload(data, {
        userId: normalizedIdentifier,
        username: mode === 'login' ? normalizedIdentifier : normalizedUsername,
        displayName: normalizedDisplayName || normalizedIdentifier,
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
              onClick={() => switchMode('login')}
            >
              登录
            </Button>
            <Button
              type="button"
              variant={mode === 'register' ? 'default' : 'outline'}
              className={mode === 'register' ? 'flex-1 bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]' : 'flex-1 border-white/20 text-white hover:bg-white/10'}
              onClick={() => switchMode('register')}
            >
              注册
            </Button>
          </div>
          {mode === 'login' ? (
            <div key="login-mode" className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="login-identifier" className="text-white/80">用户名或账户 ID</Label>
                <Input
                  id="login-identifier"
                  name="login-identifier"
                  autoComplete="username"
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
              <PasswordField
                label="密码"
                value={loginPassword}
                onChange={setLoginPassword}
                placeholder="请输入密码"
                autoComplete="current-password"
                inputName="login-password"
                inputId="login-password"
                onEnter={() => { void handleSubmit(); }}
              />
            </div>
          ) : (
            <div key="register-mode" className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="register-username" className="text-white/80">用户名</Label>
                <Input
                  id="register-username"
                  name="register-username"
                  autoComplete="username"
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
                <Label htmlFor="register-display-name" className="text-white/80">显示名</Label>
                <Input
                  id="register-display-name"
                  name="register-display-name"
                  autoComplete="nickname"
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
              <PasswordField
                label="密码"
                value={registerPassword}
                onChange={setRegisterPassword}
                placeholder="请输入密码"
                autoComplete="new-password"
                inputName="register-password"
                inputId="register-password"
                hint={registerPassword && registerPassword.length < 6 ? '密码长度至少 6 位' : undefined}
                hintClassName="text-xs text-amber-300"
                onEnter={() => { void handleSubmit(); }}
              />
              <PasswordField
                label="确认密码"
                value={confirmPassword}
                onChange={setConfirmPassword}
                placeholder="请再次输入密码"
                autoComplete="new-password"
                inputName="register-confirm-password"
                inputId="register-confirm-password"
                hint={confirmPassword && confirmPassword !== registerPassword ? '两次输入的密码不一致' : undefined}
                hintClassName="text-xs text-amber-300"
                onEnter={() => { void handleSubmit(); }}
              />
            </div>
          )}
          {error ? <p className="text-red-300 text-sm">{error}</p> : null}
          <Button
            disabled={disabled}
            onClick={() => { void handleSubmit(); }}
            className="w-full bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
          >
            {loading ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" />{mode === 'login' ? '登录中...' : '注册中...'}</> : mode === 'login' ? '登录' : '注册并进入系统'}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
