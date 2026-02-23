import { useEffect, useState } from 'react';
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
    <div className="min-h-screen bg-black text-white">
      <Navbar currentPage={currentPage} onPageChange={setCurrentPage} />
      <main className="pt-20 pb-8 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto">
        {renderPage()}
      </main>
    </div>
  );
}

export default App;
