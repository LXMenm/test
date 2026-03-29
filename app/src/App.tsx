import { Component, useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import { Navbar } from './components/Navbar';
import { Button } from './components/ui/button';
import { Input } from './components/ui/input';
import { Label } from './components/ui/label';
import { DiagnosePage } from './pages/DiagnosePage';
import { DashboardPage } from './pages/DashboardPage';
import { ProfilesPage } from './pages/ProfilesPage';
import { KBPage } from './pages/KBPage';
import { LoginPage } from './pages/LoginPage';
import { ExpertReviewPage } from './pages/ExpertReviewPage';
import { AdminPage } from './pages/AdminPage';
import { AccountManagementPage } from './pages/AccountManagementPage';
import {
  authFetch,
  clearAuthUser,
  getAllowedPages,
  getDefaultPage,
  loadAuthUser,
  normalizeAuthUserFromPayload,
  PAGE_TO_PATH,
  pathToPage,
  saveAuthUser,
  type AppPage,
  type AuthUser,
} from './auth';

function getKbDiseaseFromPath(pathname: string): string {
  if (!pathname.startsWith('/kb/')) return '';
  const raw = pathname.replace('/kb/', '').trim();
  if (!raw) return '';
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

function normalizeLegacyAdminPath(pathname: string): string {
  if (pathname === '/admin/global-dashboard') return '/dashboard';
  if (pathname === '/admin/profiles-management') return '/profiles';
  if (pathname === '/admin/kb-management') return '/kb';
  return pathname;
}

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  message: string;
}

class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = {
    hasError: false,
    message: '',
  };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return {
      hasError: true,
      message: error?.message || '页面渲染异常',
    };
  }

  componentDidCatch(error: Error, errorInfo: unknown) {
    console.error('App render error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-black text-white flex items-center justify-center p-6">
          <div className="max-w-xl w-full rounded-2xl border border-red-500/40 bg-red-500/10 p-6">
            <h2 className="text-xl font-semibold text-red-300 mb-2">页面发生错误</h2>
            <p className="text-white/80 text-sm mb-4">{this.state.message || '请刷新页面重试。'}</p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="px-4 py-2 rounded-lg bg-[#c8f7c5] text-black font-medium"
            >
              刷新页面
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

interface InlinePasswordFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  autoComplete: string;
  inputName: string;
  inputId: string;
  hint?: string;
  hintClassName?: string;
  onEnter?: () => void;
}

function InlinePasswordField({
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
}: InlinePasswordFieldProps) {
  const [revealed, setRevealed] = useState(false);
  const reveal = () => setRevealed(true);
  const hide = () => setRevealed(false);

  return (
    <div className="space-y-2">
      <Label htmlFor={inputId} className="text-white/80 text-sm">{label}</Label>
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
          className="bg-black/20 border-white/20 text-white pr-10"
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
          {revealed ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
        </button>
      </div>
      {hint ? <p className={hintClassName || 'text-xs text-white/60'}>{hint}</p> : null}
    </div>
  );
}

function App() {
  const [authUser, setAuthUser] = useState<AuthUser | null>(() => loadAuthUser());
  const [authChecking, setAuthChecking] = useState<boolean>(() => Boolean(loadAuthUser()));
  const [authNotice, setAuthNotice] = useState('');
  const [currentPage, setCurrentPage] = useState<AppPage>(() => pathToPage(window.location.pathname));
  const [kbDiseaseName, setKbDiseaseName] = useState<string>(() => getKbDiseaseFromPath(window.location.pathname));
  const [passwordPanelOpen, setPasswordPanelOpen] = useState(false);
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [passwordSaving, setPasswordSaving] = useState(false);
  const [passwordMessage, setPasswordMessage] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [passwordPanelKey, setPasswordPanelKey] = useState(0);

  const allowedPages = useMemo(() => (authUser ? getAllowedPages(authUser.role) : []), [authUser]);

  useEffect(() => {
    if (!authUser) return;
    const defaultPage = getDefaultPage(authUser.role);
    if (!allowedPages.includes(currentPage)) {
      setCurrentPage(defaultPage);
      window.history.replaceState(null, '', PAGE_TO_PATH[defaultPage]);
    }
  }, [allowedPages, authUser, currentPage]);

  useEffect(() => {
    const normalized = normalizeLegacyAdminPath(window.location.pathname);
    if (normalized !== window.location.pathname) {
      window.history.replaceState(null, '', normalized);
    }
    const handlePopState = () => {
      const normalizedPath = normalizeLegacyAdminPath(window.location.pathname);
      if (normalizedPath !== window.location.pathname) {
        window.history.replaceState(null, '', normalizedPath);
      }
      const nextPage = pathToPage(normalizedPath);
      if (authUser && !allowedPages.includes(nextPage)) {
        const fallback = getDefaultPage(authUser.role);
        setCurrentPage(fallback);
        window.history.replaceState(null, '', PAGE_TO_PATH[fallback]);
      } else {
        setCurrentPage(nextPage);
      }
      setKbDiseaseName(getKbDiseaseFromPath(normalizedPath));
    };

    window.addEventListener('popstate', handlePopState);
    return () => {
      window.removeEventListener('popstate', handlePopState);
    };
  }, [allowedPages, authUser]);

  const resetPasswordPanelState = useCallback(() => {
    setOldPassword('');
    setNewPassword('');
    setConfirmPassword('');
    setPasswordError('');
    setPasswordMessage('');
    setPasswordPanelKey((prev) => prev + 1);
  }, []);

  const applyAuthUser = useCallback((nextUser: AuthUser | null) => {
    if (!nextUser) return;
    setAuthUser(nextUser);
    saveAuthUser(nextUser);
  }, []);

  const clearCurrentSession = useCallback((reason?: string) => {
    clearAuthUser();
    setAuthUser(null);
    setPasswordPanelOpen(false);
    resetPasswordPanelState();
    if (reason) setAuthNotice(reason);
  }, [resetPasswordPanelState]);

  const verifyCurrentAuth = useCallback(async (options?: { silent?: boolean }) => {
    if (!authUser) {
      setAuthChecking(false);
      return;
    }
    const silent = Boolean(options?.silent);
    if (!silent) setAuthChecking(true);
    try {
      const resp = await authFetch('/api/auth/me', undefined, authUser);
      const data = await resp.json().catch(() => null);
      if (!resp.ok) {
        if (resp.status === 401 || resp.status === 403) {
          clearCurrentSession('登录状态已失效，请重新登录');
          return;
        }
        throw new Error(String((data as Record<string, unknown> | null)?.detail || '登录状态校验失败'));
      }
      const nextUser = normalizeAuthUserFromPayload(data, authUser);
      applyAuthUser(nextUser);
    } catch (error) {
      setAuthNotice(error instanceof Error ? error.message : '登录状态校验失败');
    } finally {
      if (!silent) setAuthChecking(false);
    }
  }, [applyAuthUser, authUser, clearCurrentSession]);

  useEffect(() => {
    void verifyCurrentAuth();
  }, [verifyCurrentAuth]);

  useEffect(() => {
    const handleFocus = () => {
      if (!authUser) return;
      void verifyCurrentAuth({ silent: true });
    };
    window.addEventListener('focus', handleFocus);
    return () => {
      window.removeEventListener('focus', handleFocus);
    };
  }, [authUser, verifyCurrentAuth]);

  const handleLogin = (user: AuthUser) => {
    applyAuthUser(user);
    setAuthNotice('');
    const defaultPage = getDefaultPage(user.role);
    setCurrentPage(defaultPage);
    window.history.replaceState(null, '', PAGE_TO_PATH[defaultPage]);
  };

  const handleLogout = () => {
    clearCurrentSession();
  };

  const handleChangePassword = async () => {
    if (!oldPassword || !newPassword || !confirmPassword) {
      setPasswordError('请完整填写当前密码、新密码和确认密码');
      return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordError('两次输入的新密码不一致');
      return;
    }
    setPasswordSaving(true);
    setPasswordError('');
    setPasswordMessage('');
    try {
      const resp = await authFetch('/api/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          old_password: oldPassword,
          new_password: newPassword,
          confirm_password: confirmPassword,
        }),
      }, authUser);
      const data = await resp.json().catch(() => null);
      if (!resp.ok) throw new Error(String((data as Record<string, unknown> | null)?.detail || '修改密码失败'));
      setOldPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setPasswordMessage('密码修改成功');
    } catch (error) {
      setPasswordError(error instanceof Error ? error.message : '修改密码失败');
    } finally {
      setPasswordSaving(false);
    }
  };

  const renderPage = () => {
    switch (currentPage) {
      case 'diagnose':
        return <DiagnosePage />;
      case 'dashboard':
        return <DashboardPage />;
      case 'profiles':
        return <ProfilesPage />;
      case 'kb':
        return <KBPage focusDiseaseName={kbDiseaseName} />;
      case 'expert_review':
        return <ExpertReviewPage />;
      case 'system_config':
        return <AdminPage pageType="system" />;
      case 'account_management':
        return <AccountManagementPage />;
      case 'review_management':
        return <AdminPage pageType="review" />;
      default:
        return <DiagnosePage />;
    }
  };

  if (!authUser) {
    return (
      <ErrorBoundary>
        <div className="space-y-3">
          {authNotice ? <div className="max-w-md mx-auto mt-6 px-4 py-3 rounded-lg border border-amber-300/40 bg-amber-300/10 text-amber-200 text-sm">{authNotice}</div> : null}
          <LoginPage onLogin={handleLogin} />
        </div>
      </ErrorBoundary>
    );
  }

  if (authChecking) {
    return (
      <ErrorBoundary>
        <div className="min-h-screen bg-black text-white flex items-center justify-center">
          <div className="text-sm text-white/70">正在校验登录状态...</div>
        </div>
      </ErrorBoundary>
    );
  }

  return (
    <ErrorBoundary>
      <div className="min-h-screen bg-black text-white">
        <Navbar
          currentPage={currentPage}
          availablePages={allowedPages}
          onPageChange={setCurrentPage}
          authUser={authUser}
          onOpenChangePassword={() => {
            setPasswordPanelOpen((prev) => {
              const nextOpen = !prev;
              if (!nextOpen) resetPasswordPanelState();
              if (nextOpen) {
                setPasswordError('');
                setPasswordMessage('');
              }
              return nextOpen;
            });
          }}
          onLogout={handleLogout}
        />
        <main className="pt-20 pb-8 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
          {passwordPanelOpen ? (
            <div key={`password-panel-${passwordPanelKey}`} className="mb-4 rounded-xl border border-white/10 bg-white/5 p-4">
              <h3 className="text-[#c8f7c5] font-medium mb-3">修改密码</h3>
              <div className="grid md:grid-cols-3 gap-3">
                <InlinePasswordField
                  label="当前密码"
                  value={oldPassword}
                  onChange={setOldPassword}
                  placeholder="当前密码"
                  autoComplete="current-password"
                  inputName="change-password-old"
                  inputId="change-password-old"
                  onEnter={() => { void handleChangePassword(); }}
                />
                <InlinePasswordField
                  label="新密码"
                  value={newPassword}
                  onChange={setNewPassword}
                  placeholder="新密码（至少 6 位）"
                  autoComplete="new-password"
                  inputName="change-password-new"
                  inputId="change-password-new"
                  hint={newPassword && newPassword.length < 6 ? '密码长度至少 6 位' : undefined}
                  hintClassName="text-xs text-amber-300"
                  onEnter={() => { void handleChangePassword(); }}
                />
                <InlinePasswordField
                  label="确认新密码"
                  value={confirmPassword}
                  onChange={setConfirmPassword}
                  placeholder="确认新密码"
                  autoComplete="new-password"
                  inputName="change-password-confirm"
                  inputId="change-password-confirm"
                  hint={confirmPassword && confirmPassword !== newPassword ? '两次输入的新密码不一致' : undefined}
                  hintClassName="text-xs text-amber-300"
                  onEnter={() => { void handleChangePassword(); }}
                />
              </div>
              <div className="mt-3 flex items-center gap-3">
                <Button
                  type="button"
                  onClick={() => { void handleChangePassword(); }}
                  disabled={passwordSaving}
                  className="bg-[#c8f7c5] text-black hover:bg-[#b8e7b5] disabled:opacity-60"
                >
                  {passwordSaving ? '提交中...' : '提交修改'}
                </Button>
                {passwordError ? <span className="text-sm text-red-300">{passwordError}</span> : null}
                {passwordMessage ? <span className="text-sm text-emerald-300">{passwordMessage}</span> : null}
              </div>
            </div>
          ) : null}
          {renderPage()}
        </main>
      </div>
    </ErrorBoundary>
  );
}

export default App;
