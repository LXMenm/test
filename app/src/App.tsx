import { Component, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Navbar } from './components/Navbar';
import { DiagnosePage } from './pages/DiagnosePage';
import { DashboardPage } from './pages/DashboardPage';
import { ProfilesPage } from './pages/ProfilesPage';
import { KBPage } from './pages/KBPage';
import { LoginPage } from './pages/LoginPage';
import { SimpleRolePage } from './pages/SimpleRolePage';
import { ExpertReviewPage } from './pages/ExpertReviewPage';
import {
  clearAuthUser,
  getAllowedPages,
  getDefaultPage,
  loadAuthUser,
  PAGE_TO_PATH,
  pathToPage,
  saveAuthUser,
  withAuthHeaders,
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

function App() {
  const [authUser, setAuthUser] = useState<AuthUser | null>(() => loadAuthUser());
  const [currentPage, setCurrentPage] = useState<AppPage>(() => pathToPage(window.location.pathname));
  const [kbDiseaseName, setKbDiseaseName] = useState<string>(() => getKbDiseaseFromPath(window.location.pathname));

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
    const handlePopState = () => {
      const nextPage = pathToPage(window.location.pathname);
      if (authUser && !allowedPages.includes(nextPage)) {
        const fallback = getDefaultPage(authUser.role);
        setCurrentPage(fallback);
        window.history.replaceState(null, '', PAGE_TO_PATH[fallback]);
      } else {
        setCurrentPage(nextPage);
      }
      setKbDiseaseName(getKbDiseaseFromPath(window.location.pathname));
    };

    window.addEventListener('popstate', handlePopState);
    return () => {
      window.removeEventListener('popstate', handlePopState);
    };
  }, [allowedPages, authUser]);

  useEffect(() => {
    const originalFetch = window.fetch.bind(window);
    window.fetch = (input: RequestInfo | URL, init?: RequestInit) => originalFetch(input, withAuthHeaders(init, authUser));
    return () => {
      window.fetch = originalFetch;
    };
  }, [authUser]);

  const handleLogin = (user: AuthUser) => {
    setAuthUser(user);
    saveAuthUser(user);
    const defaultPage = getDefaultPage(user.role);
    setCurrentPage(defaultPage);
    window.history.replaceState(null, '', PAGE_TO_PATH[defaultPage]);
  };

  const handleLogout = () => {
    clearAuthUser();
    setAuthUser(null);
  };

  const renderPage = () => {
    switch (currentPage) {
      case 'diagnose':
        return <DiagnosePage />;
      case 'cases':
        return <SimpleRolePage title="我的病例" description="用于论文演示：可在此扩展为病例列表/复诊入口（当前为轻量占位页）。" />;
      case 'dashboard':
        return <DashboardPage />;
      case 'profiles':
        return <ProfilesPage />;
      case 'kb':
      case 'kb_admin':
        return <KBPage focusDiseaseName={kbDiseaseName} />;
      case 'expert_review':
        return <ExpertReviewPage />;
      case 'system_config':
        return <SimpleRolePage title="系统配置页" description="ADMIN 可见。用于演示系统级配置入口。" />;
      case 'review_management':
        return <SimpleRolePage title="复核管理页" description="ADMIN 可见。用于演示复核任务分配与状态管理入口。" />;
      case 'global_dashboard':
        return <SimpleRolePage title="全局看板" description="ADMIN 可见。用于展示全局统计维度入口。" />;
      case 'profiles_admin':
        return <SimpleRolePage title="全量农户档案管理" description="ADMIN 可见。当前复用档案接口并通过角色控制数据范围。" />;
      default:
        return <DiagnosePage />;
    }
  };

  if (!authUser) {
    return (
      <ErrorBoundary>
        <LoginPage onLogin={handleLogin} />
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
          onLogout={handleLogout}
        />
        <main className="pt-20 pb-8 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
          {renderPage()}
        </main>
      </div>
    </ErrorBoundary>
  );
}

export default App;
