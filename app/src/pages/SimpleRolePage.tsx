import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface SimpleRolePageProps {
  title: string;
  description: string;
}

export function SimpleRolePage({ title, description }: SimpleRolePageProps) {
  return (
    <Card className="glass-card">
      <CardHeader>
        <CardTitle className="text-white">{title}</CardTitle>
      </CardHeader>
      <CardContent className="text-white/80 text-sm">
        {description}
      </CardContent>
    </Card>
  );
}
