import { Component, ReactNode, useEffect, useState } from 'react';
import { Navbar } from './components/Navbar';
import { DiagnosePage } from './pages/DiagnosePage';
import { DashboardPage } from './pages/DashboardPage';
import { ProfilesPage } from './pages/ProfilesPage';
import { KBPage } from './pages/KBPage';

type Page = 'diagnose' | 'dashboard' | 'profiles' | 'kb';

const PATH_TO_PAGE: Record<string, Page> = {
  '/': 'diagnose',
  '/dashboard': 'dashboard',
  '/profiles': 'profiles',
  '/kb': 'kb',
};

function getPageFromPath(pathname: string): Page {
  return PATH_TO_PAGE[pathname] ?? 'diagnose';
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
  const [currentPage, setCurrentPage] = useState<Page>(() => getPageFromPath(window.location.pathname));

  useEffect(() => {
    const handlePopState = () => {
      setCurrentPage(getPageFromPath(window.location.pathname));
    };

    window.addEventListener('popstate', handlePopState);
    return () => {
      window.removeEventListener('popstate', handlePopState);
    };
  }, []);

  const renderPage = () => {
    switch (currentPage) {
      case 'diagnose':
        return <DiagnosePage />;
      case 'dashboard':
        return <DashboardPage />;
      case 'profiles':
        return <ProfilesPage />;
      case 'kb':
        return <KBPage />;
      default:
        return <DiagnosePage />;
    }
  };

  return (
    <ErrorBoundary>
      <div className="min-h-screen bg-black text-white">
        <Navbar currentPage={currentPage} onPageChange={setCurrentPage} />
        <main className="pt-20 pb-8 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
          {renderPage()}
        </main>
      </div>
    </ErrorBoundary>
  );
}

export default App;
