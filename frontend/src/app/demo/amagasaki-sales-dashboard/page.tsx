"use client";

import { useMemo, useState } from "react";
import {
  Home,
  Building2,
  FileSearch,
  Star,
  Send,
  Phone,
  MapPin,
  Briefcase,
  BarChart3,
  Search,
  Bell,
  Filter,
  ChevronRight,
  Sparkles,
  Download,
  Check,
  Loader2,
  Globe,
  Mail,
  ArrowLeft,
  Plus,
  CircleDot,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Separator } from "@/components/ui/separator";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import {
  companies,
  todayActions,
  notifications,
  kpi,
  funnel,
  industryReplyRate,
  aiInsight,
  draftMessage,
  type Company,
} from "./mock-data";

type View =
  | { kind: "home" }
  | { kind: "companies" }
  | {
      kind: "detail";
      companyId: string;
      tab: "basic" | "diag" | "issues" | "proto" | "history";
    }
  | { kind: "proto"; companyId: string }
  | { kind: "outbox" }
  | { kind: "kpi" };

const navItems = [
  { key: "home", label: "ホーム", icon: Home },
  { key: "companies", label: "企業一覧", icon: Building2, badge: "5000" },
  { key: "diag", label: "診断レポート", icon: FileSearch },
  { key: "proto", label: "プロトタイプ", icon: Star },
  { key: "outbox", label: "送信キュー", icon: Send, badge: "8" },
  { key: "tel", label: "電話リスト", icon: Phone },
  { key: "route", label: "訪問ルート", icon: MapPin },
  { key: "deals", label: "商談管理", icon: Briefcase },
  { key: "kpi", label: "KPI", icon: BarChart3 },
];

export default function AmagasakiSalesDashboard() {
  const [view, setView] = useState<View>({ kind: "home" });

  const renderView = () => {
    switch (view.kind) {
      case "home":
        return <HomeView onNavigate={setView} />;
      case "companies":
        return <CompaniesView onNavigate={setView} />;
      case "detail":
        return (
          <DetailView
            companyId={view.companyId}
            tab={view.tab}
            onNavigate={setView}
          />
        );
      case "proto":
        return (
          <PrototypeView companyId={view.companyId} onNavigate={setView} />
        );
      case "outbox":
        return <OutboxView />;
      case "kpi":
        return <KpiView />;
    }
  };

  const activeNav: string = (() => {
    switch (view.kind) {
      case "home":
        return "home";
      case "companies":
      case "detail":
        return "companies";
      case "proto":
        return "proto";
      case "outbox":
        return "outbox";
      case "kpi":
        return "kpi";
    }
  })();

  return (
    <div className="flex h-screen bg-background text-foreground">
      <Sidebar
        active={activeNav}
        onNavigate={(key) => {
          if (key === "home") setView({ kind: "home" });
          else if (key === "companies") setView({ kind: "companies" });
          else if (key === "outbox") setView({ kind: "outbox" });
          else if (key === "kpi") setView({ kind: "kpi" });
          else if (key === "proto") setView({ kind: "companies" });
        }}
      />
      <main className="flex-1 overflow-auto">{renderView()}</main>
    </div>
  );
}

/* ================= Sidebar ================= */
function Sidebar({
  active,
  onNavigate,
}: {
  active: string;
  onNavigate: (key: string) => void;
}) {
  return (
    <aside className="w-64 shrink-0 border-r border-border bg-card flex flex-col">
      <div className="px-5 py-5 border-b border-border">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-lg bg-gradient-to-br from-primary to-blue-500 flex items-center justify-center">
            <Sparkles className="h-5 w-5 text-primary-foreground" />
          </div>
          <div>
            <div className="text-sm font-semibold">本田AI営業</div>
            <div className="text-[10px] text-muted-foreground tracking-wider">
              尼崎DX事業部
            </div>
          </div>
        </div>
      </div>

      <nav className="flex-1 py-4 space-y-0.5 px-2">
        <div className="text-[10px] text-muted-foreground px-3 py-1.5 tracking-wider">
          メイン
        </div>
        {navItems.slice(0, 4).map((item) => (
          <NavLink
            key={item.key}
            item={item}
            active={active === item.key}
            onClick={() => onNavigate(item.key)}
          />
        ))}
        <div className="text-[10px] text-muted-foreground px-3 py-1.5 tracking-wider mt-4">
          営業
        </div>
        {navItems.slice(4, 8).map((item) => (
          <NavLink
            key={item.key}
            item={item}
            active={active === item.key}
            onClick={() => onNavigate(item.key)}
          />
        ))}
        <div className="text-[10px] text-muted-foreground px-3 py-1.5 tracking-wider mt-4">
          分析
        </div>
        {navItems.slice(8).map((item) => (
          <NavLink
            key={item.key}
            item={item}
            active={active === item.key}
            onClick={() => onNavigate(item.key)}
          />
        ))}
      </nav>

      <div className="border-t border-border p-3">
        <div className="flex items-center gap-3">
          <Avatar className="h-9 w-9">
            <AvatarFallback className="bg-primary/20 text-primary text-xs">
              本田
            </AvatarFallback>
          </Avatar>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium truncate">本田 樹</div>
            <div className="text-[10px] text-muted-foreground">CEO / 尼崎</div>
          </div>
        </div>
      </div>
    </aside>
  );
}

function NavLink({
  item,
  active,
  onClick,
}: {
  item: (typeof navItems)[number];
  active: boolean;
  onClick: () => void;
}) {
  const Icon = item.icon;
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
        active
          ? "bg-primary/15 text-primary"
          : "text-muted-foreground hover:text-foreground hover:bg-accent"
      }`}
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span className="flex-1 text-left">{item.label}</span>
      {item.badge && (
        <Badge
          variant="outline"
          className="text-[10px] h-5 px-1.5 bg-primary/10 text-primary border-primary/30"
        >
          {item.badge}
        </Badge>
      )}
    </button>
  );
}

/* ================= Home ================= */
function HomeView({ onNavigate }: { onNavigate: (v: View) => void }) {
  return (
    <div className="p-4 md:p-8 space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">
            おはようございます、本田さん
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            今日は 2026年4月18日（土）
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative w-72">
            <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input placeholder="企業名で検索..." className="pl-9" />
          </div>
          <Button variant="outline" size="icon">
            <Bell className="h-4 w-4" />
          </Button>
        </div>
      </header>

      <div className="grid grid-cols-4 gap-4">
        <KpiCard
          label="今月の接触"
          value="27"
          sub="+8 今週"
          tone="rose"
          icon={<Mail className="h-4 w-4" />}
        />
        <KpiCard
          label="返信率"
          value="14.8%"
          sub="+1.2pt"
          tone="emerald"
          icon={<BarChart3 className="h-4 w-4" />}
        />
        <KpiCard
          label="商談中"
          value="4"
          sub="今週アポ 2件"
          tone="violet"
          icon={<Briefcase className="h-4 w-4" />}
        />
        <KpiCard
          label="今月売上"
          value="¥480k"
          sub="目標 ¥800k"
          tone="amber"
          icon={<Sparkles className="h-4 w-4" />}
        />
      </div>

      <div className="grid grid-cols-3 gap-4">
        <Card className="col-span-2 bg-emerald-500/10 border-emerald-500/30">
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="text-base">今日やること</CardTitle>
            <Badge variant="outline">5件</Badge>
          </CardHeader>
          <CardContent className="space-y-2">
            {todayActions.map((a) => {
              const company = companies.find((c) => c.id === a.companyId);
              return (
                <button
                  key={a.id}
                  onClick={() =>
                    company &&
                    onNavigate({
                      kind: "detail",
                      companyId: company.id,
                      tab: "diag",
                    })
                  }
                  className="w-full flex items-center gap-3 px-3 py-3 rounded-lg bg-accent/40 hover:bg-accent transition-colors text-left"
                >
                  <div
                    className={`h-8 w-8 rounded-lg flex items-center justify-center shrink-0 ${
                      a.urgent
                        ? "bg-rose-500/20 text-rose-400"
                        : "bg-primary/15 text-primary"
                    }`}
                  >
                    <CircleDot className="h-4 w-4" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium truncate">
                      {company?.name ?? a.companyName} / {a.action}
                    </div>
                  </div>
                  {a.urgent && (
                    <Badge
                      variant="outline"
                      className="text-rose-400 border-rose-400/40 bg-rose-500/10"
                    >
                      要対応
                    </Badge>
                  )}
                  <ChevronRight className="h-4 w-4 text-muted-foreground" />
                </button>
              );
            })}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="text-base">リアルタイム通知</CardTitle>
            <Bell className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent className="space-y-3">
            {notifications.map((n) => (
              <div key={n.id} className="flex gap-3">
                <div className="text-xs text-muted-foreground tabular-nums w-10 shrink-0 pt-0.5">
                  {n.time}
                </div>
                <div className="text-sm leading-tight">{n.text}</div>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <div className="relative overflow-hidden rounded-2xl border border-border/50">
        <video
          src="/amagasaki-hero.mp4"
          autoPlay
          loop
          muted
          playsInline
          poster="/amagasaki-hero.png"
          className="w-full h-[280px] object-cover"
        />
        <div className="absolute inset-0 bg-gradient-to-r from-background/80 via-background/20 to-transparent" />
        <div className="absolute inset-y-0 left-0 flex flex-col justify-center px-10 max-w-[55%]">
          <div className="text-xs tracking-[0.25em] text-violet-300 mb-2">TODAY'S MISSION</div>
          <div className="text-3xl font-bold text-white leading-tight">
            尼崎の街を、<br />
            AIで前に進める。
          </div>
          <div className="text-sm text-white/70 mt-3">
            今日も5,000社があなたの判断を待っています。
          </div>
        </div>
      </div>
    </div>
  );
}

function KpiCard({
  label,
  value,
  sub,
  tone,
  icon,
}: {
  label: string;
  value: string;
  sub: string;
  tone: "blue" | "emerald" | "violet" | "amber" | "rose";
  icon: React.ReactNode;
}) {
  const toneMap = {
    blue: "text-sky-400 bg-sky-500/10",
    emerald: "text-emerald-400 bg-emerald-500/10",
    violet: "text-violet-400 bg-violet-500/10",
    amber: "text-amber-400 bg-amber-500/10",
    rose: "text-rose-400 bg-rose-500/10",
  };
  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs text-muted-foreground">{label}</span>
          <div
            className={`h-7 w-7 rounded-md flex items-center justify-center ${toneMap[tone]}`}
          >
            {icon}
          </div>
        </div>
        <div className="text-3xl font-semibold tabular-nums">{value}</div>
        <div className="text-xs text-muted-foreground mt-1">{sub}</div>
      </CardContent>
    </Card>
  );
}

/* ================= Companies List ================= */
function CompaniesView({ onNavigate }: { onNavigate: (v: View) => void }) {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<string | null>(null);

  const filtered = useMemo(() => {
    return companies.filter((c) => {
      if (q && !c.name.includes(q) && !c.industry.includes(q)) return false;
      if (filter === "hpなし" && c.hpStatus !== "none") return false;
      if (filter === "スマホ未対応" && c.mobileOk) return false;
      if (filter === "要対応" && c.score < 75) return false;
      if (filter === "製造業" && c.industry !== "製造業") return false;
      return true;
    });
  }, [q, filter]);

  const chips = ["hpなし", "スマホ未対応", "要対応", "製造業", "未接触"];

  return (
    <div className="p-8 space-y-6">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold">企業一覧</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            尼崎市5,000社の法人リストから診断済み・要対応順に表示
          </p>
        </div>
        <div className="flex gap-2">
          <div className="relative w-64">
            <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="企業名・業種で検索..."
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className="pl-9"
            />
          </div>
          <Button variant="outline">
            <Download className="h-4 w-4 mr-2" />
            エクスポート
          </Button>
        </div>
      </header>

      <div className="flex items-center gap-2 flex-wrap">
        <Filter className="h-4 w-4 text-muted-foreground mr-1" />
        {chips.map((c) => (
          <button
            key={c}
            onClick={() => setFilter((prev) => (prev === c ? null : c))}
            className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
              filter === c
                ? "bg-primary text-primary-foreground border-primary"
                : "bg-accent/40 text-muted-foreground border-border hover:text-foreground"
            }`}
          >
            {c}
          </button>
        ))}
        <div className="ml-auto text-xs text-muted-foreground">
          {filtered.length}社 / スコア高い順
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">フックと目的別営業候補</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">#</TableHead>
                <TableHead>企業名</TableHead>
                <TableHead>業種</TableHead>
                <TableHead>規模</TableHead>
                <TableHead>主要課題</TableHead>
                <TableHead>ステータス</TableHead>
                <TableHead className="text-right">スコア</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((c, i) => (
                <TableRow
                  key={c.id}
                  className="cursor-pointer"
                  onClick={() =>
                    onNavigate({
                      kind: "detail",
                      companyId: c.id,
                      tab: "diag",
                    })
                  }
                >
                  <TableCell className="text-muted-foreground">
                    {i + 1}
                  </TableCell>
                  <TableCell className="font-medium">{c.name}</TableCell>
                  <TableCell>
                    <Badge variant="outline">{c.industry}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    従業員{c.employees}名
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground max-w-[240px] truncate">
                    {c.issues[0]?.title}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={c.status} />
                  </TableCell>
                  <TableCell className="text-right">
                    <span
                      className={`tabular-nums font-semibold ${
                        c.score >= 80
                          ? "text-emerald-400"
                          : c.score >= 70
                            ? "text-amber-400"
                            : "text-muted-foreground"
                      }`}
                    >
                      {c.score}
                    </span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function StatusBadge({ status }: { status: Company["status"] }) {
  const map: Record<
    Company["status"],
    { color: string; border: string; bg: string }
  > = {
    診断済み: {
      color: "text-sky-400",
      border: "border-sky-400/30",
      bg: "bg-sky-500/10",
    },
    プロト生成済: {
      color: "text-violet-400",
      border: "border-violet-400/30",
      bg: "bg-violet-500/10",
    },
    送信済: {
      color: "text-amber-400",
      border: "border-amber-400/30",
      bg: "bg-amber-500/10",
    },
    商談中: {
      color: "text-emerald-400",
      border: "border-emerald-400/30",
      bg: "bg-emerald-500/10",
    },
    受注: {
      color: "text-primary",
      border: "border-primary/40",
      bg: "bg-primary/15",
    },
  };
  const s = map[status];
  return (
    <Badge variant="outline" className={`${s.color} ${s.border} ${s.bg}`}>
      {status}
    </Badge>
  );
}

/* ================= Detail ================= */
function DetailView({
  companyId,
  tab,
  onNavigate,
}: {
  companyId: string;
  tab: "basic" | "diag" | "issues" | "proto" | "history";
  onNavigate: (v: View) => void;
}) {
  const company = companies.find((c) => c.id === companyId);
  if (!company) return null;

  return (
    <div className="p-8 space-y-6">
      <button
        onClick={() => onNavigate({ kind: "companies" })}
        className="text-sm text-muted-foreground hover:text-foreground flex items-center gap-1"
      >
        <ArrowLeft className="h-4 w-4" /> 企業一覧に戻る
      </button>

      <div className="flex items-start justify-between gap-6">
        <div className="flex items-start gap-4">
          <div className="h-14 w-14 rounded-lg bg-gradient-to-br from-primary/40 to-violet-500/40 flex items-center justify-center text-xl font-semibold">
            {company.name.slice(0, 1)}
          </div>
          <div>
            <h1 className="text-2xl font-semibold">{company.name}</h1>
            <div className="flex items-center gap-3 mt-1 text-sm text-muted-foreground flex-wrap">
              <Badge variant="outline">{company.industry}</Badge>
              <span>{company.address}</span>
              <span>従業員{company.employees}名</span>
              <span>創業 {company.founded}</span>
              <Badge
                variant="outline"
                className="text-rose-400 border-rose-400/30 bg-rose-500/10"
              >
                HP{company.hpStatus === "none" ? "なし" : "要更新"}
              </Badge>
            </div>
          </div>
        </div>
        <div className="flex gap-2 shrink-0">
          <Button variant="outline">
            <Phone className="h-4 w-4 mr-2" />
            {company.phone}
          </Button>
          <Button
            onClick={() =>
              onNavigate({ kind: "proto", companyId: company.id })
            }
          >
            <Star className="h-4 w-4 mr-2" />
            プロトタイプを生成
          </Button>
        </div>
      </div>

      <Tabs
        value={tab}
        onValueChange={(v) =>
          onNavigate({
            kind: "detail",
            companyId: company.id,
            tab: v as typeof tab,
          })
        }
      >
        <TabsList>
          <TabsTrigger value="basic">基本情報</TabsTrigger>
          <TabsTrigger value="diag">HP診断</TabsTrigger>
          <TabsTrigger value="issues">AI課題仮説</TabsTrigger>
          <TabsTrigger value="proto">プロトタイプ</TabsTrigger>
          <TabsTrigger value="history">営業履歴</TabsTrigger>
        </TabsList>

        <TabsContent value="basic" className="pt-4">
          <Card>
            <CardContent className="pt-6 grid grid-cols-2 gap-6 text-sm">
              <InfoRow label="所在地" value={company.address} />
              <InfoRow label="電話番号" value={company.phone} />
              <InfoRow label="業種" value={company.industry} />
              <InfoRow label="従業員数" value={`${company.employees}名`} />
              <InfoRow label="創業" value={company.founded} />
              <InfoRow label="ステータス" value={company.status} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="diag" className="pt-4 space-y-4">
          <div className="grid grid-cols-4 gap-4">
            <DiagCard
              label="HP存在"
              value={company.hpStatus === "none" ? "×" : "△"}
              sub={company.hpStatus === "none" ? "サイトなし" : "要更新"}
              tone="rose"
            />
            <DiagCard
              label="スマホ対応"
              value={company.mobileOk ? "○" : "—"}
              sub={company.mobileOk ? "OK" : "N/A"}
              tone={company.mobileOk ? "emerald" : "muted"}
            />
            <DiagCard
              label="問い合わせ動線"
              value={company.inquiryForm ? "○" : "0"}
              sub={company.inquiryForm ? "フォーム有" : "不在"}
              tone={company.inquiryForm ? "emerald" : "rose"}
            />
            <DiagCard
              label="総合スコア"
              value={String(company.score)}
              sub="要改善"
              tone="amber"
            />
          </div>

          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle className="text-base">検出された問題</CardTitle>
              <Badge
                variant="outline"
                className="text-primary border-primary/30 bg-primary/10"
              >
                AI分析
              </Badge>
            </CardHeader>
            <CardContent className="space-y-3">
              {company.issues.map((issue, i) => (
                <div
                  key={i}
                  className="flex items-start gap-3 p-4 rounded-lg bg-accent/40 border border-border"
                >
                  <div className="h-2 w-2 rounded-full bg-rose-400 mt-2" />
                  <div className="flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <div className="font-medium text-sm">{issue.title}</div>
                      <div className="text-xs text-muted-foreground shrink-0">
                        確信度{" "}
                        <span className="text-emerald-400 font-semibold">
                          {issue.confidence}%
                        </span>
                      </div>
                    </div>
                    <div className="text-xs text-muted-foreground mt-1">
                      {issue.detail}
                    </div>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="issues" className="pt-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">AI課題仮説</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <p>
                {company.name}
                はGBPのみでの発信にとどまり、採用・新規取引の両面で獲得機会を逃している可能性が高い。
              </p>
              <p>
                提案フック:{" "}
                <span className="text-primary">
                  採用HP + 技術紹介サイト（AI生成）
                </span>
                。初期費用15万円・月3万円運用プランが適合。
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="proto" className="pt-4">
          <Card>
            <CardContent className="pt-6 flex items-center justify-between">
              <div className="text-sm text-muted-foreground">
                まだプロトタイプが生成されていません
              </div>
              <Button
                onClick={() =>
                  onNavigate({ kind: "proto", companyId: company.id })
                }
              >
                <Plus className="h-4 w-4 mr-2" /> 生成する
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="history" className="pt-4">
          <Card>
            <CardContent className="pt-6 text-sm text-muted-foreground">
              まだ接触履歴がありません
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1">{value}</div>
    </div>
  );
}

function DiagCard({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub: string;
  tone: "rose" | "emerald" | "amber" | "muted";
}) {
  const toneMap = {
    rose: "text-rose-400",
    emerald: "text-emerald-400",
    amber: "text-amber-400",
    muted: "text-muted-foreground",
  };
  return (
    <Card>
      <CardContent className="pt-6">
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className={`text-3xl font-semibold mt-2 ${toneMap[tone]}`}>
          {value}
        </div>
        <div className="text-xs text-muted-foreground mt-1">{sub}</div>
      </CardContent>
    </Card>
  );
}

/* ================= Prototype Generator ================= */
function PrototypeView({
  companyId,
  onNavigate,
}: {
  companyId: string;
  onNavigate: (v: View) => void;
}) {
  const company = companies.find((c) => c.id === companyId);
  const [theme, setTheme] = useState("採用重視 / プロフェッショナル");
  const [target, setTarget] = useState("技術系求職者 + 直取引先候補");
  const [sections, setSections] = useState({
    identity: true,
    cases: true,
    recruit: true,
    contact: true,
    video: false,
  });
  const [generating, setGenerating] = useState(false);
  const [generated, setGenerated] = useState(false);

  const handleGenerate = () => {
    setGenerating(true);
    setGenerated(false);
    setTimeout(() => {
      setGenerating(false);
      setGenerated(true);
    }, 2400);
  };

  if (!company) return null;

  return (
    <div className="p-8 space-y-6">
      <button
        onClick={() =>
          onNavigate({
            kind: "detail",
            companyId: company.id,
            tab: "diag",
          })
        }
        className="text-sm text-muted-foreground hover:text-foreground flex items-center gap-1"
      >
        <ArrowLeft className="h-4 w-4" /> 企業詳細に戻る
      </button>

      <div>
        <h1 className="text-2xl font-semibold">
          {company.name}
          <span className="text-muted-foreground mx-2">/</span>
          <span className="text-primary">プロトタイプ生成</span>
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          AI課題仮説に基づき自動でカスタマイズHPを作成します
        </p>
      </div>

      <div className="grid grid-cols-[360px_1fr] gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">生成パラメータ</CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <div>
              <Label className="text-xs text-muted-foreground">テーマ</Label>
              <Input
                value={theme}
                onChange={(e) => setTheme(e.target.value)}
                className="mt-2"
              />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">
                ターゲット
              </Label>
              <Input
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                className="mt-2"
              />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">
                含めるセクション
              </Label>
              <div className="space-y-2.5 mt-3">
                {[
                  { key: "identity", label: "企業ヒーロー（理念）" },
                  { key: "cases", label: "技術力ショーケース" },
                  { key: "recruit", label: "採用LP" },
                  { key: "contact", label: "問い合わせフォーム" },
                  { key: "video", label: "職人インタビュー動画" },
                ].map((s) => (
                  <div
                    key={s.key}
                    className="flex items-center justify-between"
                  >
                    <span className="text-sm">{s.label}</span>
                    <Switch
                      checked={sections[s.key as keyof typeof sections]}
                      onCheckedChange={(v) =>
                        setSections((prev) => ({ ...prev, [s.key]: v }))
                      }
                    />
                  </div>
                ))}
              </div>
            </div>
            <Button
              onClick={handleGenerate}
              disabled={generating}
              className="w-full"
            >
              {generating ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  生成中...
                </>
              ) : (
                <>
                  <Sparkles className="h-4 w-4 mr-2" />
                  プロトタイプを生成
                </>
              )}
            </Button>
          </CardContent>
        </Card>

        <Card className="overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-2 border-b border-border bg-accent/40">
            <div className="flex gap-1.5">
              <div className="h-3 w-3 rounded-full bg-rose-400/60" />
              <div className="h-3 w-3 rounded-full bg-amber-400/60" />
              <div className="h-3 w-3 rounded-full bg-emerald-400/60" />
            </div>
            <div className="flex-1 mx-4 px-3 py-1 rounded bg-background text-xs text-muted-foreground truncate">
              {generated
                ? `${company.id}.preview.miki-honda.jp`
                : "プレビューを生成してください"}
            </div>
          </div>

          <div className="relative min-h-[560px]">
            {generating && (
              <div className="absolute inset-0 bg-background/70 backdrop-blur-sm flex flex-col items-center justify-center gap-3 z-10">
                <Loader2 className="h-8 w-8 animate-spin text-primary" />
                <div className="text-sm text-muted-foreground">
                  AIがHPを設計しています...
                </div>
                <div className="w-48">
                  <Progress value={65} />
                </div>
              </div>
            )}

            {generated ? (
              <PreviewSite company={company} />
            ) : (
              <div className="flex flex-col items-center justify-center py-32 text-muted-foreground">
                <Globe className="h-10 w-10 mb-3 opacity-40" />
                <div className="text-sm">
                  パラメータを設定して「生成」ボタンを押してください
                </div>
              </div>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

function PreviewSite({ company }: { company: Company }) {
  return (
    <div className="text-foreground">
      <div className="px-10 py-16 bg-gradient-to-br from-sky-600 via-indigo-700 to-violet-800 text-white">
        <div className="flex items-center justify-between mb-12 text-sm">
          <div className="font-semibold">{company.name}</div>
          <div className="flex gap-6 opacity-90">
            <span>技術</span>
            <span>採用</span>
            <span>会社案内</span>
            <span>お問い合わせ</span>
          </div>
        </div>
        <h2 className="text-4xl font-bold leading-snug">
          0.005mmの世界を、
          <br />
          50年つくってきた。
        </h2>
        <p className="mt-5 text-sm opacity-90 max-w-lg">
          尼崎の町工場から医療機器・航空宇宙部品まで、精密加工のプロフェッショナル。
        </p>
        <button className="mt-8 px-5 py-2 bg-white/95 text-indigo-900 rounded text-sm font-semibold">
          採用情報を見る →
        </button>
      </div>
      <div className="grid grid-cols-3 gap-4 p-6 bg-card">
        {[
          {
            t: "精密加工技術",
            d: "マイクロメートル単位の加工精度±0.005mm対応",
          },
          {
            t: "医療機器認証",
            d: "ISO13485取得済み。滅菌後の品質検証にも対応",
          },
          {
            t: "技術者募集",
            d: "二代目候補と一緒に会社を次の時代へ繋ぐ募集中",
          },
        ].map((s) => (
          <div key={s.t} className="p-4 rounded-lg bg-accent/40">
            <div className="h-8 w-8 rounded bg-indigo-500/30 mb-3" />
            <div className="font-semibold text-sm">{s.t}</div>
            <div className="text-xs text-muted-foreground mt-1">{s.d}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ================= Outbox ================= */
function OutboxView() {
  const [msg, setMsg] = useState(draftMessage);
  const [sent, setSent] = useState(false);

  return (
    <div className="p-8 space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">
            送信キュー
            <span className="text-muted-foreground mx-2">/</span>
            <span className="text-primary">田中精密工業</span>
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            AI作成のメール文面を確認して、承認後にSMTP送信します
          </p>
        </div>
        <Button variant="outline" size="sm">
          もっと見る
        </Button>
      </header>

      <div className="grid grid-cols-[1fr_340px] gap-6">
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="text-base">メール プレビュー</CardTitle>
            <Badge
              variant="outline"
              className="text-primary border-primary/30 bg-primary/10"
            >
              AIが作成
            </Badge>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="text-xs text-muted-foreground">
              宛先: 田中精密工業（公式フォーム） / contact@tanaka-seimitsu.jp
            </div>
            <Textarea
              value={msg}
              onChange={(e) => setMsg(e.target.value)}
              rows={18}
              className="font-mono text-xs"
            />
            <div className="flex items-center gap-3 justify-end pt-2">
              <Button variant="outline">AIで再作成</Button>
              <Button variant="outline">保留</Button>
              <Button onClick={() => setSent(true)} disabled={sent}>
                {sent ? (
                  <>
                    <Check className="h-4 w-4 mr-2" /> 送信済み
                  </>
                ) : (
                  <>
                    <Send className="h-4 w-4 mr-2" /> 承認＆送信
                  </>
                )}
              </Button>
            </div>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">狙いと仮説</CardTitle>
            </CardHeader>
            <CardContent className="text-sm space-y-2">
              <div>
                <span className="text-muted-foreground">ターゲット</span>
                <div>二代目候補 田中様</div>
              </div>
              <Separator />
              <div>
                <span className="text-muted-foreground">フック</span>
                <div>採用×技術訴求のサンプルHPを無料提示</div>
              </div>
              <Separator />
              <div>
                <span className="text-muted-foreground">期待反応率</span>
                <div className="text-emerald-400 font-semibold">22%</div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">送信ステータス</CardTitle>
            </CardHeader>
            <CardContent>
              {sent ? (
                <div className="flex flex-col items-center py-8 gap-3 text-center">
                  <div className="h-12 w-12 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center">
                    <Check className="h-6 w-6" />
                  </div>
                  <div className="font-semibold">送信完了</div>
                  <div className="text-xs text-muted-foreground">
                    送信キューに記録しました
                  </div>
                </div>
              ) : (
                <div className="text-sm text-muted-foreground flex items-center gap-2">
                  <CircleDot className="h-4 w-4" /> 承認待ち
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

/* ================= KPI ================= */
function KpiView() {
  const maxFunnel = Math.max(...funnel.map((f) => f.value));
  const maxRate = Math.max(...industryReplyRate.map((r) => r.rate));

  return (
    <div className="p-8 space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">KPI ダッシュボード</h1>
          <p className="text-sm text-muted-foreground mt-1">
            2026年4月 / 尼崎AI営業パイプライン
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm">
            今月 ▾
          </Button>
          <Button variant="outline" size="sm">
            <Download className="h-4 w-4 mr-2" />
            エクスポート
          </Button>
        </div>
      </header>

      <div className="grid grid-cols-5 gap-3">
        <KpiMiniCard
          label="TOTAL LIST"
          value={kpi.total.toLocaleString()}
          sub="尼崎市 全法人"
        />
        <KpiMiniCard
          label="DIAGNOSED"
          value={kpi.diagnosed.toLocaleString()}
          sub="HP診断完了"
        />
        <KpiMiniCard
          label="PROTOTYPED"
          value={String(kpi.prototyped)}
          sub="プロト完成"
        />
        <KpiMiniCard
          label="APPROACHED"
          value={String(kpi.approached)}
          sub="営業実施"
        />
        <KpiMiniCard
          label="DEALS"
          value={String(kpi.deals)}
          sub="受注"
          highlight
        />
      </div>

      <div className="grid grid-cols-[1fr_420px] gap-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              コンバージョンファネル
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 pt-2">
            {funnel.map((f, i) => {
              const w = (f.value / maxFunnel) * 100;
              const colors = [
                "from-sky-500 to-sky-400",
                "from-indigo-500 to-indigo-400",
                "from-violet-500 to-violet-400",
                "from-fuchsia-500 to-fuchsia-400",
                "from-rose-500 to-rose-400",
                "from-amber-500 to-amber-400",
              ];
              return (
                <div key={f.key} className="flex items-center gap-3">
                  <div className="w-44 text-xs text-muted-foreground text-right shrink-0">
                    {f.label}
                  </div>
                  <div className="flex-1 relative h-8">
                    <div
                      className={`absolute left-0 top-0 h-full bg-gradient-to-r ${colors[i]} rounded flex items-center px-3`}
                      style={{ width: `${w}%` }}
                    >
                      <span className="text-xs font-bold text-white drop-shadow">
                        {f.key}
                      </span>
                    </div>
                    <div
                      className="absolute top-1/2 -translate-y-1/2 text-xs tabular-nums font-semibold"
                      style={{ left: `calc(${w}% + 8px)` }}
                    >
                      {f.value.toLocaleString()}
                    </div>
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">業種別 返信率</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-end gap-2 h-40 mt-4">
              {industryReplyRate.map((r) => (
                <div
                  key={r.industry}
                  className="flex-1 h-full flex flex-col items-center justify-end"
                >
                  <div className="text-[10px] tabular-nums text-muted-foreground mb-1">
                    {r.rate}%
                  </div>
                  <div
                    className="w-full rounded-t bg-gradient-to-t from-primary/80 to-sky-400/80"
                    style={{ height: `${(r.rate / maxRate) * 92}%` }}
                  />
                </div>
              ))}
            </div>
            <div className="flex gap-2 mt-2">
              {industryReplyRate.map((r) => (
                <div
                  key={r.industry}
                  className="flex-1 text-[10px] text-muted-foreground text-center"
                >
                  {r.industry}
                </div>
              ))}
            </div>
            <Separator className="my-4" />
            <div className="flex gap-3 text-sm items-start">
              <div className="h-8 w-8 rounded-md bg-primary/15 text-primary flex items-center justify-center shrink-0">
                <Sparkles className="h-4 w-4" />
              </div>
              <div>
                <div className="font-semibold text-xs mb-0.5">
                  AIインサイト
                </div>
                <div className="text-xs text-muted-foreground leading-relaxed">
                  {aiInsight}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function KpiMiniCard({
  label,
  value,
  sub,
  highlight,
}: {
  label: string;
  value: string;
  sub: string;
  highlight?: boolean;
}) {
  return (
    <Card className={highlight ? "border-primary/40 bg-primary/5" : ""}>
      <CardContent className="pt-5 pb-5">
        <div className="text-[10px] text-muted-foreground tracking-wider">
          {label}
        </div>
        <div
          className={`text-3xl font-semibold mt-2 tabular-nums ${
            highlight ? "text-primary" : ""
          }`}
        >
          {value}
        </div>
        <div className="text-[10px] text-muted-foreground mt-1">{sub}</div>
      </CardContent>
    </Card>
  );
}
