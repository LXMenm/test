import { useMemo, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { AuthUser, UserRole } from '@/auth';

interface LoginPageProps {
  onLogin: (user: AuthUser) => void;
}

export function LoginPage({ onLogin }: LoginPageProps) {
  const [userId, setUserId] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [role, setRole] = useState<UserRole>('USER');

  const disabled = useMemo(() => !userId.trim() || !displayName.trim(), [userId, displayName]);

  const handleSubmit = () => {
    if (disabled) return;
    onLogin({ userId: userId.trim(), displayName: displayName.trim(), role });
  };

  return (
    <div className="min-h-screen bg-black text-white flex items-center justify-center px-4">
      <Card className="w-full max-w-md glass-card">
        <CardHeader>
          <CardTitle className="text-white">轻量登录（演示版）</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label className="text-white/80">用户 ID</Label>
            <Input
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              placeholder="例如：F0001 / expert01 / admin"
              className="bg-white/5 border-white/20 text-white"
            />
          </div>
          <div className="space-y-2">
            <Label className="text-white/80">显示名称</Label>
            <Input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="请输入显示名称"
              className="bg-white/5 border-white/20 text-white"
            />
          </div>
          <div className="space-y-2">
            <Label className="text-white/80">角色</Label>
            <Select value={role} onValueChange={(value) => setRole(value as UserRole)}>
              <SelectTrigger className="bg-white/5 border-white/20 text-white">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-[#111] text-white border-white/20">
                <SelectItem value="USER">USER</SelectItem>
                <SelectItem value="EXPERT">EXPERT</SelectItem>
                <SelectItem value="ADMIN">ADMIN</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Button
            disabled={disabled}
            onClick={handleSubmit}
            className="w-full bg-[#c8f7c5] text-black hover:bg-[#b8e7b5]"
          >
            登录
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
