'use client';

/**
 * AIX事業ダッシュボード
 * 課題分析 → 提案 → 営業 → 商談 → 契約 → 運用 をワンストップで管理。
 */
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Plus, Search, Loader2, Building2, Target, Send, FileText, Briefcase, Activity,
  CheckCircle2, Clock, AlertTriangle, Sparkles, ArrowUpRight, MoreHorizontal,
  TrendingUp, Phone, Mail, Calendar, ExternalLink, Trash2, ChevronRight,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogTrigger } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Progress } from '@/components/ui/progress';
import { Separator } from '@/components/ui/separator';
import { Skeleton } from '@/components/ui/skeleton';

const API_BASE = '/api/v1/aix';

// ===== Types =====
type Stage = 'research' | 'proposal' | 'negotiation' | 'contracted' | 'live' | 'paused' | 'lost';
type Zone = 'green' | 'yellow' | 'red';

interface Client {
  id: string;
  name: string;
  industry?: string;
  region?: string;
  contact_name?: string;
  contact_email?: string;
  contact_phone?: string;
  stage: Stage;
  health_score: number;
  estimated_value?: number;
  notes?: string;
  tags: string[];
  updated_at: string;
}

interface Task {
  id: string;
  client_id?: string;
  title: string;
  description?: string;
  zone: Zone;
  status: string;
  priority: string;
  requested_action?: string;
  result_summary?: string;
  artifact_urls: string[];
  due_at?: string;
  created_at: string;
}

interface Engagement {
  id: string;
  client_id: string;
  deliverable_name: string;
  deliverable_type?: string;
  deliverable_url?: string;
  status: string;
  health_score: number;
  notes?: string;
}

interface PipelineKPI {
  active_clients: number;
  proposals_sent: number;
  proposals_responded: number;
  response_rate: number;
  contracted: number;
  monthly_estimated_value: number;
  open_tasks: number;
}

interface PipelineStageBucket {
  stage: string;
  count: number;
  estimated_value_total: number;
}

const STAGE_LABEL: Record<Stage, string> = {
  research: '課題分析',
  proposal: '提案準備',
  negotiation: '商談中',
  contracted: '契約',
  live: '運用中',
  paused: '一時停止',
  lost: 'ロスト',
};

const STAGE_COLOR: Record<Stage, string> = {
  research: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
  proposal: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  negotiation: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  contracted: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  live: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  paused: 'bg-zinc-500/15 text-zinc-400 border-zinc-500/30',
  lost: 'bg-red-500/15 text-red-400 border-red-500/30',
};

const ZONE_COLOR: Record<Zone, string> = {
  green: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  yellow: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  red: 'bg-red-500/15 text-red-400 border-red-500/30',
};

const ZONE_LABEL: Record<Zone, string> = {
  green: 'Green / 即実行',
  yellow: 'Yellow / 事後報告',
  red: 'Red / 要承認',
};

// ===== Page =====
export default function AIXDashboardPage() {
  const [activeTab, setActiveTab] = useState('overview');
  const [searchQuery, setSearchQuery] = useState('');

  return (
    <div className="max-w-[1400px] mx-auto p-6 space-y-6">
      {/* ヘッダー */}
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <Sparkles className="h-5 w-5 text-primary" />
            <span className="text-xs font-bold uppercase tracking-[0.2em] text-primary">AIX OPS</span>
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-foreground">AIX事業ダッシュボード</h1>
          <p className="text-sm text-muted-foreground mt-1">
            企業の課題分析・提案・営業・商談・契約・運用を、ワンストップで管理。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <NewClientDialog />
          <NewTaskDialog />
        </div>
      </header>

      {/* KPI */}
      <KPISection />

      {/* タブ */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
        <TabsList className="bg-card border border-border">
          <TabsTrigger value="overview">オーバービュー</TabsTrigger>
          <TabsTrigger value="clients">クライアント</TabsTrigger>
          <TabsTrigger value="tasks">ダンタスクハブ</TabsTrigger>
          <TabsTrigger value="engagements">運用</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6">
          <PipelineStagesSection />
          <div className="grid lg:grid-cols-3 gap-4">
            <div className="lg:col-span-2">
              <ClientListSection compact searchQuery={searchQuery} />
            </div>
            <div>
              <TaskHubSection compact />
            </div>
          </div>
        </TabsContent>

        <TabsContent value="clients">
          <div className="mb-4">
            <SearchBox value={searchQuery} onChange={setSearchQuery} />
          </div>
          <ClientListSection searchQuery={searchQuery} />
        </TabsContent>

        <TabsContent value="tasks">
          <TaskHubSection />
        </TabsContent>

        <TabsContent value="engagements">
          <EngagementSection />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ===== KPI Section =====
function KPISection() {
  const { data: kpi, isLoading } = useQuery<PipelineKPI>({
    queryKey: ['aix', 'kpi'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/pipeline/kpi`);
      if (!res.ok) throw new Error();
      return res.json();
    },
  });

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}
      </div>
    );
  }

  if (!kpi) return null;

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <KPICard
        icon={<Building2 className="h-4 w-4" />}
        label="アクティブ案件"
        value={kpi.active_clients.toString()}
        sub="調査中・提案中・商談中・契約済・運用中"
      />
      <KPICard
        icon={<Send className="h-4 w-4" />}
        label="提案送付"
        value={kpi.proposals_sent.toString()}
        sub={`反応率 ${Math.round(kpi.response_rate * 100)}%`}
      />
      <KPICard
        icon={<TrendingUp className="h-4 w-4" />}
        label="月次収益見込"
        value={`¥${(kpi.monthly_estimated_value || 0).toLocaleString()}`}
        sub={`${kpi.contracted}件の運用契約`}
      />
      <KPICard
        icon={<CheckCircle2 className="h-4 w-4" />}
        label="オープンタスク"
        value={kpi.open_tasks.toString()}
        sub="ダンへの依頼"
        accent
      />
    </div>
  );
}

function KPICard({ icon, label, value, sub, accent = false }: { icon: React.ReactNode; label: string; value: string; sub: string; accent?: boolean }) {
  return (
    <Card className={accent ? 'border-primary/40 bg-primary/5' : ''}>
      <CardContent className="pt-6">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-muted-foreground">{label}</span>
          <span className={`${accent ? 'text-primary' : 'text-muted-foreground'}`}>{icon}</span>
        </div>
        <div className="text-2xl font-bold tabular-nums tracking-tight">{value}</div>
        <div className="text-xs text-muted-foreground mt-1">{sub}</div>
      </CardContent>
    </Card>
  );
}

// ===== Pipeline Stages =====
function PipelineStagesSection() {
  const { data: stages, isLoading } = useQuery<PipelineStageBucket[]>({
    queryKey: ['aix', 'stages'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/pipeline/stages`);
      if (!res.ok) throw new Error();
      return res.json();
    },
  });

  if (isLoading) return <Skeleton className="h-32" />;
  if (!stages || stages.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12">
          <Target className="h-10 w-10 text-muted-foreground mb-3" />
          <p className="text-sm text-muted-foreground">
            まだクライアントが登録されていません。「新規クライアント」から追加してください。
          </p>
        </CardContent>
      </Card>
    );
  }

  // 全ステージを表示（0件のものも含む）
  const allStages: Stage[] = ['research', 'proposal', 'negotiation', 'contracted', 'live'];
  const map = new Map(stages.map((s) => [s.stage, s]));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <Activity className="h-4 w-4 text-primary" /> パイプライン
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {allStages.map((s) => {
            const bucket = map.get(s) || { stage: s, count: 0, estimated_value_total: 0 };
            return (
              <div key={s} className="rounded-md border border-border bg-background/50 p-4">
                <div className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold border ${STAGE_COLOR[s]}`}>
                  {STAGE_LABEL[s]}
                </div>
                <div className="text-3xl font-bold tabular-nums mt-3">{bucket.count}</div>
                <div className="text-[10px] text-muted-foreground mt-1">
                  ¥{bucket.estimated_value_total.toLocaleString()} (見込)
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

// ===== Client List =====
function ClientListSection({ compact = false, searchQuery = '' }: { compact?: boolean; searchQuery?: string }) {
  const { data: clients, isLoading } = useQuery<Client[]>({
    queryKey: ['aix', 'clients'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/clients`);
      if (!res.ok) throw new Error();
      return res.json();
    },
  });

  const filtered = (clients || []).filter((c) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return c.name.toLowerCase().includes(q) || (c.industry || '').toLowerCase().includes(q);
  });

  const display = compact ? filtered.slice(0, 6) : filtered;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base flex items-center gap-2">
          <Building2 className="h-4 w-4 text-primary" /> クライアント
          <span className="text-xs text-muted-foreground font-normal">({filtered.length})</span>
        </CardTitle>
        {compact && filtered.length > 6 && (
          <Button variant="ghost" size="sm">すべて表示 <ChevronRight className="ml-1 h-3 w-3" /></Button>
        )}
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => <Skeleton key={i} className="h-14" />)}
          </div>
        ) : display.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <Building2 className="h-8 w-8 text-muted-foreground mb-2" />
            <p className="text-sm text-muted-foreground">クライアントがいません</p>
          </div>
        ) : (
          <div className="space-y-2">
            {display.map((c) => <ClientRow key={c.id} client={c} />)}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ClientRow({ client }: { client: Client }) {
  return (
    <div className="flex items-center gap-4 p-3 rounded-md border border-border bg-background/30 hover:border-primary/40 transition cursor-pointer group">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="font-medium truncate">{client.name}</span>
          <Badge variant="outline" className={`text-[10px] ${STAGE_COLOR[client.stage]}`}>
            {STAGE_LABEL[client.stage]}
          </Badge>
        </div>
        <div className="text-xs text-muted-foreground flex flex-wrap items-center gap-3">
          {client.industry && <span>{client.industry}</span>}
          {client.region && <span>{client.region}</span>}
          {client.contact_name && <span>担当: {client.contact_name}</span>}
        </div>
      </div>
      <div className="hidden sm:block text-right">
        <div className="text-xs text-muted-foreground">想定</div>
        <div className="font-mono text-sm font-semibold">
          {client.estimated_value ? `¥${client.estimated_value.toLocaleString()}` : '—'}
        </div>
      </div>
      <div className="hidden md:flex flex-col items-end gap-1 w-24">
        <span className="text-[10px] text-muted-foreground">Health {client.health_score}</span>
        <Progress value={client.health_score} className="h-1.5 w-full" />
      </div>
      <ChevronRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition" />
    </div>
  );
}

// ===== Task Hub =====
function TaskHubSection({ compact = false }: { compact?: boolean }) {
  const { data: tasks, isLoading } = useQuery<Task[]>({
    queryKey: ['aix', 'tasks', 'open'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/tasks?status=todo`);
      if (!res.ok) throw new Error();
      const todo = await res.json();
      const res2 = await fetch(`${API_BASE}/tasks?status=in_progress`);
      const ip = res2.ok ? await res2.json() : [];
      const res3 = await fetch(`${API_BASE}/tasks?status=awaiting_approval`);
      const wa = res3.ok ? await res3.json() : [];
      return [...todo, ...ip, ...wa];
    },
  });

  const display = compact ? (tasks || []).slice(0, 8) : (tasks || []);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" /> ダンタスクハブ
          <span className="text-xs text-muted-foreground font-normal">({(tasks || []).length})</span>
        </CardTitle>
        {!compact && <NewTaskDialog />}
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-14" />)}</div>
        ) : display.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <CheckCircle2 className="h-8 w-8 text-muted-foreground mb-2" />
            <p className="text-sm text-muted-foreground">オープン中のタスクはありません</p>
          </div>
        ) : (
          <div className="space-y-2">
            {display.map((t) => <TaskRow key={t.id} task={t} />)}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function TaskRow({ task }: { task: Task }) {
  const queryClient = useQueryClient();
  const completeMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE}/tasks/${task.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'done', completed_at: new Date().toISOString() }),
      });
      if (!res.ok) throw new Error();
      return res.json();
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['aix'] }),
  });

  return (
    <div className="p-3 rounded-md border border-border bg-background/30 hover:border-primary/40 transition">
      <div className="flex items-start gap-2 mb-2">
        <Badge variant="outline" className={`text-[10px] ${ZONE_COLOR[task.zone]}`}>
          {task.zone === 'green' ? '●' : task.zone === 'yellow' ? '◐' : '◯'}
        </Badge>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium leading-snug">{task.title}</div>
          {task.description && (
            <div className="text-xs text-muted-foreground mt-1 line-clamp-2">{task.description}</div>
          )}
        </div>
      </div>
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-muted-foreground">
          {task.status === 'awaiting_approval' ? '⚠ 承認待ち' : task.status === 'in_progress' ? '⏳ 実行中' : '📋 待機中'}
        </span>
        <Button
          size="xs"
          variant="ghost"
          onClick={() => completeMutation.mutate()}
          disabled={completeMutation.isPending}
        >
          完了
        </Button>
      </div>
    </div>
  );
}

// ===== Engagement Section =====
function EngagementSection() {
  const { data: engagements, isLoading } = useQuery<Engagement[]>({
    queryKey: ['aix', 'engagements'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/engagements`);
      if (!res.ok) throw new Error();
      return res.json();
    },
  });

  if (isLoading) return <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-20" />)}</div>;

  if (!engagements || engagements.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12">
          <Briefcase className="h-10 w-10 text-muted-foreground mb-3" />
          <p className="text-sm text-muted-foreground mb-4">運用中の成果物はまだありません</p>
          <NewEngagementDialog />
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <NewEngagementDialog />
      </div>
      <div className="grid md:grid-cols-2 gap-3">
        {engagements.map((e) => (
          <Card key={e.id}>
            <CardContent className="pt-6">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <div className="text-xs text-muted-foreground">{e.deliverable_type || 'deliverable'}</div>
                  <h3 className="font-semibold text-base mt-0.5">{e.deliverable_name}</h3>
                </div>
                <Badge variant="outline" className="text-[10px]">{e.status}</Badge>
              </div>
              {e.deliverable_url && (
                <a href={e.deliverable_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
                  {e.deliverable_url} <ExternalLink className="h-3 w-3" />
                </a>
              )}
              <div className="mt-4">
                <div className="flex items-center justify-between text-xs text-muted-foreground mb-1">
                  <span>Health Score</span>
                  <span className="font-mono">{e.health_score}</span>
                </div>
                <Progress value={e.health_score} className="h-1.5" />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

// ===== Search Box =====
function SearchBox({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="relative max-w-md">
      <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
      <Input
        placeholder="クライアント名・業界で検索..."
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="pl-10"
      />
    </div>
  );
}

// ===== New Client Dialog =====
function NewClientDialog() {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    name: '', industry: '', region: '', contact_name: '', contact_email: '', stage: 'research' as Stage,
    estimated_value: '', notes: '',
  });
  const queryClient = useQueryClient();
  const createMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE}/clients`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...form,
          estimated_value: form.estimated_value ? parseInt(form.estimated_value) : null,
          tags: [],
        }),
      });
      if (!res.ok) throw new Error();
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['aix'] });
      setOpen(false);
      setForm({ name: '', industry: '', region: '', contact_name: '', contact_email: '', stage: 'research', estimated_value: '', notes: '' });
    },
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus className="h-4 w-4 mr-1" /> クライアント
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>新規クライアント</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div>
            <Label>会社名 *</Label>
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="吉川特装自動車" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>業界</Label>
              <Input value={form.industry} onChange={(e) => setForm({ ...form, industry: e.target.value })} placeholder="特装車整備" />
            </div>
            <div>
              <Label>地域</Label>
              <Input value={form.region} onChange={(e) => setForm({ ...form, region: e.target.value })} placeholder="鳥取県米子市" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>担当者名</Label>
              <Input value={form.contact_name} onChange={(e) => setForm({ ...form, contact_name: e.target.value })} />
            </div>
            <div>
              <Label>担当者メール</Label>
              <Input type="email" value={form.contact_email} onChange={(e) => setForm({ ...form, contact_email: e.target.value })} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>ステージ</Label>
              <Select value={form.stage} onValueChange={(v) => setForm({ ...form, stage: v as Stage })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.entries(STAGE_LABEL).map(([k, v]) => (
                    <SelectItem key={k} value={k}>{v}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>想定収益（円）</Label>
              <Input type="number" value={form.estimated_value} onChange={(e) => setForm({ ...form, estimated_value: e.target.value })} placeholder="500000" />
            </div>
          </div>
          <div>
            <Label>メモ</Label>
            <Textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} rows={3} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>キャンセル</Button>
          <Button onClick={() => createMutation.mutate()} disabled={!form.name || createMutation.isPending}>
            {createMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : '作成'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ===== New Task Dialog =====
function NewTaskDialog() {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    title: '', description: '', zone: 'green' as Zone, priority: 'normal', requested_action: '',
  });
  const queryClient = useQueryClient();
  const createMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE}/tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (!res.ok) throw new Error();
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['aix'] });
      setOpen(false);
      setForm({ title: '', description: '', zone: 'green', priority: 'normal', requested_action: '' });
    },
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline">
          <Sparkles className="h-4 w-4 mr-1" /> タスク
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>ダンへの新規タスク</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div>
            <Label>タイトル *</Label>
            <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="吉川特装HPに修理事例を追加" />
          </div>
          <div>
            <Label>依頼内容</Label>
            <Textarea value={form.requested_action} onChange={(e) => setForm({ ...form, requested_action: e.target.value })} rows={3} placeholder="ダンに具体的に依頼する内容" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>ゾーン</Label>
              <Select value={form.zone} onValueChange={(v) => setForm({ ...form, zone: v as Zone })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="green">Green / 即実行</SelectItem>
                  <SelectItem value="yellow">Yellow / 事後報告</SelectItem>
                  <SelectItem value="red">Red / 要承認</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>優先度</Label>
              <Select value={form.priority} onValueChange={(v) => setForm({ ...form, priority: v })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="low">低</SelectItem>
                  <SelectItem value="normal">通常</SelectItem>
                  <SelectItem value="high">高</SelectItem>
                  <SelectItem value="urgent">緊急</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>キャンセル</Button>
          <Button onClick={() => createMutation.mutate()} disabled={!form.title || createMutation.isPending}>
            {createMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : '作成'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ===== New Engagement Dialog =====
function NewEngagementDialog() {
  const [open, setOpen] = useState(false);
  const { data: clients } = useQuery<Client[]>({
    queryKey: ['aix', 'clients'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/clients`);
      return res.ok ? res.json() : [];
    },
  });
  const [form, setForm] = useState({
    client_id: '', deliverable_name: '', deliverable_type: 'website',
    deliverable_url: '', status: 'live', health_score: 80, notes: '',
  });
  const queryClient = useQueryClient();
  const createMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE}/engagements`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (!res.ok) throw new Error();
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['aix'] });
      setOpen(false);
    },
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline">
          <Plus className="h-4 w-4 mr-1" /> 運用成果物
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>新規運用成果物</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div>
            <Label>クライアント *</Label>
            <Select value={form.client_id} onValueChange={(v) => setForm({ ...form, client_id: v })}>
              <SelectTrigger><SelectValue placeholder="選択" /></SelectTrigger>
              <SelectContent>
                {(clients || []).map((c) => (
                  <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>成果物名 *</Label>
            <Input value={form.deliverable_name} onChange={(e) => setForm({ ...form, deliverable_name: e.target.value })} placeholder="吉川特装HP" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>種類</Label>
              <Select value={form.deliverable_type} onValueChange={(v) => setForm({ ...form, deliverable_type: v })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="website">Website</SelectItem>
                  <SelectItem value="tool">Tool</SelectItem>
                  <SelectItem value="dashboard">Dashboard</SelectItem>
                  <SelectItem value="other">Other</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>ステータス</Label>
              <Select value={form.status} onValueChange={(v) => setForm({ ...form, status: v })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="building">構築中</SelectItem>
                  <SelectItem value="live">運用中</SelectItem>
                  <SelectItem value="maintenance">メンテナンス</SelectItem>
                  <SelectItem value="paused">一時停止</SelectItem>
                  <SelectItem value="sunset">終了</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div>
            <Label>URL</Label>
            <Input value={form.deliverable_url} onChange={(e) => setForm({ ...form, deliverable_url: e.target.value })} placeholder="https://..." />
          </div>
          <div>
            <Label>メモ</Label>
            <Textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} rows={2} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>キャンセル</Button>
          <Button onClick={() => createMutation.mutate()} disabled={!form.client_id || !form.deliverable_name || createMutation.isPending}>
            {createMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : '作成'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
