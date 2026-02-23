import { useState } from 'react';
import { Navbar } from './components/Navbar';
import { DiagnosePage } from './pages/DiagnosePage';
import { DashboardPage } from './pages/DashboardPage';
import { ProfilesPage } from './pages/ProfilesPage';
import { KBPage } from './pages/KBPage';

type Page = 'diagnose' | 'dashboard' | 'profiles' | 'kb';

function App() {
  const [currentPage, setCurrentPage] = useState<Page>('diagnose');

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
