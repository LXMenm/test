import { Leaf, BarChart3, Users, BookOpen, Stethoscope } from 'lucide-react';
import { cn } from '@/lib/utils';

type Page = 'diagnose' | 'dashboard' | 'profiles' | 'kb';

interface NavbarProps {
  currentPage: Page;
  onPageChange: (page: Page) => void;
}

const navItems: { id: Page; label: string; icon: React.ElementType }[] = [
  { id: 'diagnose', label: '诊断', icon: Stethoscope },
  { id: 'kb', label: '知识库管理', icon: BookOpen },
  { id: 'dashboard', label: '数据看板', icon: BarChart3 },
  { id: 'profiles', label: '农户档案', icon: Users },
];

export function Navbar({ currentPage, onPageChange }: NavbarProps) {
  return (
    <nav className="fixed top-0 left-0 right-0 z-50 bg-[#c8f7c5]/95 backdrop-blur-md border-b border-white/10">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-black rounded-full flex items-center justify-center">
              <Leaf className="w-5 h-5 text-[#c8f7c5]" />
            </div>
            <span className="text-xl font-bold text-black tracking-tight">
              病害图像诊断
            </span>
          </div>

          {/* Navigation Links */}
          <div className="hidden md:flex items-center gap-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = currentPage === item.id;
              
              return (
                <button
                  key={item.id}
                  onClick={() => onPageChange(item.id)}
                  className={cn(
                    "flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium transition-all duration-300",
                    isActive
                      ? "bg-black text-[#c8f7c5] shadow-lg"
                      : "text-black/70 hover:text-black hover:bg-black/10"
                  )}
                >
                  <Icon className="w-4 h-4" />
                  {item.label}
                </button>
              );
            })}
          </div>

          {/* Mobile Menu Button */}
          <div className="md:hidden">
            <button className="p-2 rounded-lg bg-black/10 text-black">
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Navigation */}
      <div className="md:hidden border-t border-black/10 bg-[#c8f7c5]/98">
        <div className="px-4 py-2 space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = currentPage === item.id;
            
            return (
              <button
                key={item.id}
                onClick={() => onPageChange(item.id)}
                className={cn(
                  "flex items-center gap-3 w-full px-4 py-3 rounded-xl text-sm font-medium transition-all duration-300",
                  isActive
                    ? "bg-black text-[#c8f7c5]"
                    : "text-black/70 hover:text-black hover:bg-black/10"
                )}
              >
                <Icon className="w-5 h-5" />
                {item.label}
              </button>
            );
          })}
        </div>
      </div>
    </nav>
  );
}
