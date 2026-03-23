import { Leaf, BarChart3, Users, BookOpen, Stethoscope, ClipboardList, UserCheck, Shield, Settings, Database, LayoutDashboard, LogOut } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { AppPage, AuthUser } from '@/auth';
import { PAGE_TO_PATH } from '@/auth';

interface NavbarProps {
  currentPage: AppPage;
  availablePages: AppPage[];
  onPageChange: (page: AppPage) => void;
  authUser: AuthUser;
  onLogout: () => void;
}

const NAV_META: Record<AppPage, { label: string; icon: React.ElementType }> = {
  diagnose: { label: '诊断页', icon: Stethoscope },
  cases: { label: '我的病例', icon: ClipboardList },
  dashboard: { label: '我的数据看板', icon: BarChart3 },
  profiles: { label: '我的农户档案', icon: Users },
  kb: { label: '知识库(只读)', icon: BookOpen },
  expert_review: { label: '专家复核区', icon: UserCheck },
  system_config: { label: '系统配置', icon: Settings },
  review_management: { label: '复核管理', icon: Shield },
  global_dashboard: { label: '全局看板', icon: LayoutDashboard },
  kb_admin: { label: '知识库管理', icon: Database },
  profiles_admin: { label: '全量档案管理', icon: Users },
};

export function Navbar({ currentPage, availablePages, onPageChange, authUser, onLogout }: NavbarProps) {
  const navItems = availablePages.map((page) => ({ id: page, ...NAV_META[page] }));

  const handlePageChange = (page: AppPage) => {
    onPageChange(page);
    const targetPath = PAGE_TO_PATH[page];
    if (window.location.pathname !== targetPath) {
      window.history.pushState(null, '', targetPath);
    }
  };

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 bg-[#c8f7c5]/95 backdrop-blur-md border-b border-white/10">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16 gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 bg-black rounded-full flex items-center justify-center">
              <Leaf className="w-5 h-5 text-[#c8f7c5]" />
            </div>
            <span className="text-xl font-bold text-black tracking-tight truncate">病害图像诊断</span>
          </div>

          <div className="hidden md:flex items-center gap-1 flex-1 justify-center overflow-x-auto">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = currentPage === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => handlePageChange(item.id)}
                  className={cn(
                    'flex items-center gap-2 px-3 py-2 rounded-full text-sm font-medium transition-all duration-300 whitespace-nowrap',
                    isActive ? 'bg-black text-[#c8f7c5] shadow-lg' : 'text-black/70 hover:text-black hover:bg-black/10',
                  )}
                >
                  <Icon className="w-4 h-4" />
                  {item.label}
                </button>
              );
            })}
          </div>

          <div className="hidden md:flex items-center gap-3 text-black">
            <div className="text-right text-xs leading-tight">
              <div className="font-semibold">{authUser.displayName}</div>
              <div className="opacity-70">{authUser.role} · {authUser.userId}</div>
            </div>
            <button onClick={onLogout} className="p-2 rounded-lg bg-black/10 text-black hover:bg-black/20" title="退出登录">
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </nav>
  );
}
