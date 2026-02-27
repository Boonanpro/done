'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { FileText, Sparkles, Send, Trash2, Loader2, Plus, ExternalLink, ArrowLeft, PenLine, Tag, X, Clock, Calendar, Ban, CheckCircle, AlertCircle } from 'lucide-react';

import { MainLayout } from '@/components/layout/main-layout';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { api } from '@/lib/api-client';
import { useAuthStore } from '@/stores/auth-store';

type Draft = {
  id: string;
  title: string;
  content: string;
  tags: string[];
  status: string;
  created_at: string;
};

type Polished = {
  draft_id: string;
  title: string;
  tags: string[];
  full_text: string;
  hook: string | null;
  summary: string | null;
  polished_at: string;
  status: string;
};

type Post = {
  draft_id: string;
  note_url: string;
  title: string;
  published: boolean;
  posted_at: string;
  status: string;
};

type Schedule = {
  id: string;
  draft_id: string;
  scheduled_at: string;
  status: string;
  article_type: string;
  price: number | null;
  error_message: string | null;
  published_url: string | null;
  draft_title: string | null;
  created_at: string;
  updated_at: string;
};

type Stats = {
  total_drafts: number;
  total_posts: number;
  published: number;
  draft_on_note: number;
  pending_drafts: number;
  polished_drafts: number;
  scheduled: number;
};

// ==================== Status Badge ====================

function StatusBadge({ status }: { status: string }) {
  const variants: Record<string, { variant: 'default' | 'secondary' | 'outline' | 'destructive'; label: string }> = {
    draft: { variant: 'outline', label: '下書き' },
    polished: { variant: 'secondary', label: '清書済み' },
    posted: { variant: 'default', label: '投稿済み' },
    published: { variant: 'default', label: '公開済み' },
    scheduled: { variant: 'secondary', label: '予約中' },
    publishing: { variant: 'secondary', label: '投稿中' },
    failed: { variant: 'destructive', label: '失敗' },
    cancelled: { variant: 'outline', label: 'キャンセル' },
  };
  const v = variants[status] || { variant: 'outline' as const, label: status };
  return <Badge variant={v.variant}>{v.label}</Badge>;
}

// ==================== Stats Card ====================

function StatsCard({ stats }: { stats: Stats }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
      <Card className="py-4">
        <CardContent className="flex flex-col items-center gap-1 px-3">
          <span className="text-2xl font-bold">{stats.total_drafts}</span>
          <span className="text-xs text-muted-foreground">下書き</span>
        </CardContent>
      </Card>
      <Card className="py-4">
        <CardContent className="flex flex-col items-center gap-1 px-3">
          <span className="text-2xl font-bold">{stats.polished_drafts}</span>
          <span className="text-xs text-muted-foreground">清書済み</span>
        </CardContent>
      </Card>
      <Card className="py-4">
        <CardContent className="flex flex-col items-center gap-1 px-3">
          <span className="text-2xl font-bold">{stats.published}</span>
          <span className="text-xs text-muted-foreground">公開済み</span>
        </CardContent>
      </Card>
      {stats.scheduled > 0 && (
        <Card className="py-4">
          <CardContent className="flex flex-col items-center gap-1 px-3">
            <span className="text-2xl font-bold">{stats.scheduled}</span>
            <span className="text-xs text-muted-foreground">予約中</span>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ==================== Draft Editor ====================

function DraftEditor({
  onSave,
  onCancel,
  initialData,
  isLoading,
}: {
  onSave: (data: { title: string; content: string; tags: string[] }) => void;
  onCancel: () => void;
  initialData?: Draft | null;
  isLoading: boolean;
}) {
  const [title, setTitle] = useState(() => initialData?.title || '');
  const [content, setContent] = useState(() => initialData?.content || '');
  const [tagInput, setTagInput] = useState('');
  const [tags, setTags] = useState<string[]>(() => initialData?.tags || []);

  const addTag = () => {
    const tag = tagInput.trim();
    if (tag && tags.length < 5 && !tags.includes(tag)) {
      setTags([...tags, tag]);
      setTagInput('');
    }
  };

  const removeTag = (index: number) => {
    setTags(tags.filter((_, i) => i !== index));
  };

  const handleSubmit = () => {
    if (!title.trim() || !content.trim()) return;
    onSave({ title: title.trim(), content: content.trim(), tags });
  };

  return (
    <div className="space-y-4">
      {/* Title */}
      <div>
        <label className="text-sm font-medium text-foreground mb-1.5 block">
          タイトル
        </label>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="記事のタイトル（ラフでOK）"
          className="w-full h-10 px-3 rounded-md border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
        />
      </div>

      {/* Content */}
      <div>
        <label className="text-sm font-medium text-foreground mb-1.5 block">
          本文
        </label>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="記事の内容を書いてください。箇条書きでもOKです。AIが読みやすく清書します。"
          rows={12}
          className="w-full px-3 py-2 rounded-md border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring resize-y min-h-[200px]"
        />
      </div>

      {/* Tags */}
      <div>
        <label className="text-sm font-medium text-foreground mb-1.5 block">
          タグ（最大5個）
        </label>
        <div className="flex gap-2 mb-2 flex-wrap">
          {tags.map((tag, i) => (
            <Badge key={tag} variant="secondary" className="gap-1">
              {tag}
              <button onClick={() => removeTag(i)} className="hover:text-destructive">
                <X className="size-3" />
              </button>
            </Badge>
          ))}
        </div>
        {tags.length < 5 && (
          <div className="flex gap-2">
            <input
              type="text"
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addTag())}
              placeholder="タグを入力してEnter"
              className="flex-1 h-8 px-3 rounded-md border bg-background text-foreground text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
            <Button size="sm" variant="outline" onClick={addTag} disabled={!tagInput.trim()}>
              <Tag className="size-3" />
              追加
            </Button>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex gap-2 pt-2">
        <Button onClick={handleSubmit} disabled={!title.trim() || !content.trim() || isLoading}>
          {isLoading ? <Loader2 className="size-4 animate-spin" /> : <FileText className="size-4" />}
          {initialData ? '更新する' : '下書き保存'}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          キャンセル
        </Button>
      </div>
    </div>
  );
}

// ==================== Polish Preview ====================

function PolishPreview({
  draft,
  polished,
  onPolish,
  onPost,
  onSchedule,
  isPolishing,
}: {
  draft: Draft;
  polished: Polished | null;
  onPolish: (articleType: 'free' | 'paid', price?: number) => void;
  onPost: (isPaid: boolean, price?: number) => void;
  onSchedule: (scheduledAt: string, articleType: 'free' | 'paid', price?: number) => void;
  isPolishing: boolean;
}) {
  const [articleType, setArticleType] = useState<'free' | 'paid'>('free');
  const [price, setPrice] = useState(1500);
  const [showScheduler, setShowScheduler] = useState(false);
  const [scheduleDate, setScheduleDate] = useState('');
  const [scheduleTime, setScheduleTime] = useState('07:00');

  return (
    <div className="space-y-4">
      {/* Original Draft */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <PenLine className="size-4" />
            元の下書き
          </CardTitle>
        </CardHeader>
        <CardContent>
          <h3 className="font-semibold mb-2">{draft.title}</h3>
          <p className="text-sm text-muted-foreground whitespace-pre-wrap">{draft.content}</p>
        </CardContent>
      </Card>

      {/* Article Type Selection */}
      {!polished && (
        <Card>
          <CardContent className="pt-4 space-y-3">
            <div className="flex gap-2">
              <Button
                variant={articleType === 'free' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setArticleType('free')}
              >
                無料記事
              </Button>
              <Button
                variant={articleType === 'paid' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setArticleType('paid')}
              >
                有料記事
              </Button>
            </div>
            {articleType === 'paid' && (
              <div className="flex items-center gap-2">
                <label className="text-sm font-medium">価格:</label>
                <input
                  type="number"
                  value={price}
                  onChange={(e) => setPrice(Math.max(100, Math.min(50000, Number(e.target.value))))}
                  min={100}
                  max={50000}
                  step={100}
                  className="w-28 h-8 px-2 rounded-md border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
                <span className="text-sm text-muted-foreground">円</span>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Polish Button */}
      {!polished && (
        <Button
          onClick={() => onPolish(articleType, articleType === 'paid' ? price : undefined)}
          disabled={isPolishing}
          className="w-full"
          size="lg"
        >
          {isPolishing ? (
            <>
              <Loader2 className="size-4 animate-spin" />
              AIが清書中...（30秒ほどかかります）
            </>
          ) : (
            <>
              <Sparkles className="size-4" />
              AIで{articleType === 'paid' ? `有料記事（${price}円）` : '無料記事'}として清書する
            </>
          )}
        </Button>
      )}

      {/* Polished Result */}
      {polished && (
        <Card className="border-primary/50">
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <Sparkles className="size-4 text-primary" />
              AI清書結果
            </CardTitle>
            <CardDescription>
              {polished.summary}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <h3 className="font-bold text-lg">{polished.title}</h3>
            {polished.tags.length > 0 && (
              <div className="flex gap-1 flex-wrap">
                {polished.tags.map((tag, i) => (
                  <Badge key={i} variant="outline" className="text-xs">#{tag}</Badge>
                ))}
              </div>
            )}
            <div className="text-sm whitespace-pre-wrap leading-relaxed border rounded-md p-4 bg-muted/30 max-h-[400px] overflow-y-auto">
              {polished.full_text}
            </div>
            <div className="flex gap-2 pt-2">
              <Button
                onClick={() => onPost(articleType === 'paid', articleType === 'paid' ? price : undefined)}
                size="lg"
                className="flex-1"
              >
                <Send className="size-4" />
                noteに{articleType === 'paid' ? `有料（${price}円）で` : ''}投稿する
              </Button>
              <Button
                onClick={() => setShowScheduler(!showScheduler)}
                variant="outline"
              >
                <Clock className="size-4" />
                予約
              </Button>
              <Button
                onClick={() => onPolish(articleType, articleType === 'paid' ? price : undefined)}
                variant="outline"
                disabled={isPolishing}
              >
                {isPolishing ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
                再清書
              </Button>
            </div>
            {showScheduler && (
              <Card className="border-dashed">
                <CardContent className="pt-4 space-y-3">
                  <p className="text-sm font-medium">投稿予約</p>
                  <div className="flex gap-2">
                    <input
                      type="date"
                      value={scheduleDate}
                      onChange={(e) => setScheduleDate(e.target.value)}
                      min={new Date().toISOString().split('T')[0]}
                      className="h-8 px-2 rounded-md border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    />
                    <input
                      type="time"
                      value={scheduleTime}
                      onChange={(e) => setScheduleTime(e.target.value)}
                      className="h-8 px-2 rounded-md border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    />
                  </div>
                  <p className="text-xs text-muted-foreground">
                    朝7時と夜8時が最も読まれやすい時間帯です
                  </p>
                  <Button
                    onClick={() => {
                      if (scheduleDate && scheduleTime) {
                        const dt = new Date(`${scheduleDate}T${scheduleTime}:00+09:00`);
                        onSchedule(
                          dt.toISOString(),
                          articleType,
                          articleType === 'paid' ? price : undefined
                        );
                        setShowScheduler(false);
                      }
                    }}
                    disabled={!scheduleDate}
                    size="sm"
                  >
                    <Calendar className="size-3.5" />
                    この日時で予約する
                  </Button>
                </CardContent>
              </Card>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ==================== Main Page ====================

export default function NotesPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const hasToken = typeof window !== 'undefined' && !!localStorage.getItem('done-token');

  const [activeTab, setActiveTab] = useState('drafts');
  const [showEditor, setShowEditor] = useState(false);
  const [selectedDraft, setSelectedDraft] = useState<Draft | null>(null);
  const [viewDraft, setViewDraft] = useState<Draft | null>(null);

  // Auth check
  useEffect(() => {
    if (!isAuthenticated && !hasToken) {
      router.push('/login');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated, hasToken]);

  // Queries
  const { data: draftsData, isLoading: draftsLoading } = useQuery({
    queryKey: ['note-drafts'],
    queryFn: () => api.notes.listDrafts(),
    enabled: isAuthenticated || hasToken,
  });

  const { data: postsData } = useQuery({
    queryKey: ['note-posts'],
    queryFn: () => api.notes.listPosts(),
    enabled: isAuthenticated || hasToken,
  });

  const { data: statsData } = useQuery({
    queryKey: ['note-stats'],
    queryFn: () => api.notes.getStats(),
    enabled: isAuthenticated || hasToken,
  });

  const { data: schedulesData } = useQuery({
    queryKey: ['note-schedules'],
    queryFn: () => api.notes.listSchedules(),
    enabled: isAuthenticated || hasToken,
  });

  // Mutations
  const createDraft = useMutation({
    mutationFn: (data: { title: string; content: string; tags: string[] }) =>
      api.notes.createDraft(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['note-drafts'] });
      queryClient.invalidateQueries({ queryKey: ['note-stats'] });
      setShowEditor(false);
    },
  });

  const updateDraft = useMutation({
    mutationFn: ({ id, data }: { id: string; data: { title?: string; content?: string; tags?: string[] } }) =>
      api.notes.updateDraft(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['note-drafts'] });
      setShowEditor(false);
      setSelectedDraft(null);
    },
  });

  const deleteDraft = useMutation({
    mutationFn: (id: string) => api.notes.deleteDraft(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['note-drafts'] });
      queryClient.invalidateQueries({ queryKey: ['note-stats'] });
    },
  });

  const createSchedule = useMutation({
    mutationFn: (data: { draft_id: string; scheduled_at: string; article_type?: 'free' | 'paid'; price?: number }) =>
      api.notes.createSchedule(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['note-schedules'] });
      queryClient.invalidateQueries({ queryKey: ['note-stats'] });
    },
  });

  const cancelSchedule = useMutation({
    mutationFn: (scheduleId: string) => api.notes.cancelSchedule(scheduleId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['note-schedules'] });
      queryClient.invalidateQueries({ queryKey: ['note-stats'] });
    },
  });

  const executePolish = useMutation({
    mutationFn: ({ draftId, articleType, price }: { draftId: string; articleType?: 'free' | 'paid'; price?: number }) =>
      api.notes.executePolish(draftId, { article_type: articleType, price }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['note-drafts'] });
      queryClient.invalidateQueries({ queryKey: ['note-stats'] });
    },
  });

  // Polished data for view draft
  const { data: polishedData } = useQuery({
    queryKey: ['note-polished', viewDraft?.id],
    queryFn: () => viewDraft ? api.notes.getPolished(viewDraft.id) : null,
    enabled: !!viewDraft && viewDraft.status !== 'draft',
  });

  const handleSaveDraft = (data: { title: string; content: string; tags: string[] }) => {
    if (selectedDraft) {
      updateDraft.mutate({ id: selectedDraft.id, data });
    } else {
      createDraft.mutate(data);
    }
  };

  const handlePolish = (articleType: 'free' | 'paid', price?: number) => {
    if (viewDraft) {
      executePolish.mutate({ draftId: viewDraft.id, articleType, price });
    }
  };

  const handleSchedule = (scheduledAt: string, articleType: 'free' | 'paid', price?: number) => {
    if (viewDraft) {
      createSchedule.mutate({
        draft_id: viewDraft.id,
        scheduled_at: scheduledAt,
        article_type: articleType,
        price,
      });
    }
  };

  const handlePost = (isPaid: boolean, price?: number) => {
    // noteへの投稿はダンに依頼する形で実装
    // チャットに遷移してダンに投稿依頼
    if (viewDraft) {
      const priceInfo = isPaid && price ? ` 有料記事として${price}円で設定してください。` : '';
      const message = `noteに以下の記事を投稿してください。下書きID: ${viewDraft.id}${priceInfo}`;
      router.push(`/chat?message=${encodeURIComponent(message)}`);
    }
  };

  // Draft detail view
  if (viewDraft) {
    return (
      <MainLayout showNotifications={false}>
        <div className="flex flex-col h-full overflow-hidden">
          <div className="flex items-center gap-3 px-6 py-4 border-b shrink-0">
            <Button variant="ghost" size="icon" onClick={() => setViewDraft(null)}>
              <ArrowLeft className="size-4" />
            </Button>
            <div className="flex-1">
              <h2 className="font-semibold">{viewDraft.title}</h2>
              <div className="flex items-center gap-2 mt-0.5">
                <StatusBadge status={viewDraft.status} />
                <span className="text-xs text-muted-foreground">
                  {new Date(viewDraft.created_at).toLocaleDateString('ja-JP')}
                </span>
              </div>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-6">
            <PolishPreview
              draft={viewDraft}
              polished={polishedData || (executePolish.data?.draft_id === viewDraft.id ? executePolish.data : null)}
              onPolish={handlePolish}
              onPost={handlePost}
              onSchedule={handleSchedule}
              isPolishing={executePolish.isPending}
            />
          </div>
        </div>
      </MainLayout>
    );
  }

  // Editor view
  if (showEditor) {
    return (
      <MainLayout showNotifications={false}>
        <div className="flex flex-col h-full overflow-hidden">
          <div className="flex items-center gap-3 px-6 py-4 border-b shrink-0">
            <Button variant="ghost" size="icon" onClick={() => { setShowEditor(false); setSelectedDraft(null); }}>
              <ArrowLeft className="size-4" />
            </Button>
            <h2 className="font-semibold">{selectedDraft ? '下書きを編集' : '新しい下書き'}</h2>
          </div>
          <div className="flex-1 overflow-y-auto p-6">
            <DraftEditor
              initialData={selectedDraft}
              onSave={handleSaveDraft}
              onCancel={() => { setShowEditor(false); setSelectedDraft(null); }}
              isLoading={createDraft.isPending || updateDraft.isPending}
            />
          </div>
        </div>
      </MainLayout>
    );
  }

  // Main list view
  return (
    <MainLayout showNotifications={false}>
      <div className="flex flex-col h-full overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b shrink-0">
          <div>
            <h1 className="text-xl font-bold">note投稿システム</h1>
            <p className="text-sm text-muted-foreground">下書き → AI清書 → noteに自動投稿</p>
          </div>
          <Button onClick={() => setShowEditor(true)}>
            <Plus className="size-4" />
            新しい下書き
          </Button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* Stats */}
          {statsData && <StatsCard stats={statsData} />}

          {/* Tabs */}
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList>
              <TabsTrigger value="drafts">
                <FileText className="size-3.5 mr-1" />
                下書き
              </TabsTrigger>
              <TabsTrigger value="schedules">
                <Clock className="size-3.5 mr-1" />
                予約
              </TabsTrigger>
              <TabsTrigger value="posts">
                <Send className="size-3.5 mr-1" />
                投稿済み
              </TabsTrigger>
            </TabsList>

            {/* Drafts Tab */}
            <TabsContent value="drafts">
              {draftsLoading ? (
                <div className="flex justify-center py-12">
                  <Loader2 className="size-6 animate-spin text-muted-foreground" />
                </div>
              ) : !draftsData?.drafts.length ? (
                <Card className="py-12">
                  <CardContent className="flex flex-col items-center gap-3">
                    <FileText className="size-8 text-muted-foreground" />
                    <p className="text-muted-foreground">まだ下書きがありません</p>
                    <Button onClick={() => setShowEditor(true)} variant="outline">
                      <Plus className="size-4" />
                      最初の下書きを作成
                    </Button>
                  </CardContent>
                </Card>
              ) : (
                <div className="space-y-2">
                  {draftsData.drafts.map((draft) => (
                    <Card
                      key={draft.id}
                      className="py-3 cursor-pointer hover:bg-accent/50 transition-colors"
                      onClick={() => setViewDraft(draft)}
                    >
                      <CardContent className="flex items-center gap-3 px-4">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <h3 className="font-medium truncate">{draft.title}</h3>
                            <StatusBadge status={draft.status} />
                          </div>
                          <p className="text-xs text-muted-foreground truncate mt-0.5">
                            {draft.content.slice(0, 80)}...
                          </p>
                          <div className="flex items-center gap-2 mt-1">
                            {draft.tags.map((tag, i) => (
                              <span key={i} className="text-xs text-muted-foreground">#{tag}</span>
                            ))}
                            <span className="text-xs text-muted-foreground">
                              {new Date(draft.created_at).toLocaleDateString('ja-JP')}
                            </span>
                          </div>
                        </div>
                        <div className="flex gap-1 shrink-0">
                          <Button
                            size="icon-sm"
                            variant="ghost"
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedDraft(draft);
                              setShowEditor(true);
                            }}
                          >
                            <PenLine className="size-3.5" />
                          </Button>
                          <Button
                            size="icon-sm"
                            variant="ghost"
                            onClick={(e) => {
                              e.stopPropagation();
                              if (confirm('この下書きを削除しますか？')) {
                                deleteDraft.mutate(draft.id);
                              }
                            }}
                          >
                            <Trash2 className="size-3.5 text-destructive" />
                          </Button>
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}
            </TabsContent>

            {/* Schedules Tab */}
            <TabsContent value="schedules">
              {!schedulesData?.schedules.length ? (
                <Card className="py-12">
                  <CardContent className="flex flex-col items-center gap-3">
                    <Clock className="size-8 text-muted-foreground" />
                    <p className="text-muted-foreground">予約された投稿はありません</p>
                    <p className="text-xs text-muted-foreground">下書きの清書後に「予約」ボタンから設定できます</p>
                  </CardContent>
                </Card>
              ) : (
                <div className="space-y-2">
                  {schedulesData.schedules.map((schedule) => (
                    <Card key={schedule.id} className="py-3">
                      <CardContent className="flex items-center gap-3 px-4">
                        <div className="shrink-0">
                          {schedule.status === 'scheduled' ? (
                            <Clock className="size-5 text-blue-500" />
                          ) : schedule.status === 'published' ? (
                            <CheckCircle className="size-5 text-green-500" />
                          ) : schedule.status === 'failed' ? (
                            <AlertCircle className="size-5 text-destructive" />
                          ) : schedule.status === 'cancelled' ? (
                            <Ban className="size-5 text-muted-foreground" />
                          ) : (
                            <Loader2 className="size-5 animate-spin" />
                          )}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <h3 className="font-medium truncate">
                              {schedule.draft_title || '無題'}
                            </h3>
                            <StatusBadge status={schedule.status} />
                            {schedule.article_type === 'paid' && schedule.price && (
                              <Badge variant="outline" className="text-xs">
                                {schedule.price.toLocaleString()}円
                              </Badge>
                            )}
                          </div>
                          <div className="flex items-center gap-2 mt-0.5">
                            <Calendar className="size-3 text-muted-foreground" />
                            <span className="text-xs text-muted-foreground">
                              {new Date(schedule.scheduled_at).toLocaleString('ja-JP', {
                                month: 'long',
                                day: 'numeric',
                                weekday: 'short',
                                hour: '2-digit',
                                minute: '2-digit',
                              })}
                            </span>
                          </div>
                          {schedule.error_message && (
                            <p className="text-xs text-destructive mt-1">{schedule.error_message}</p>
                          )}
                          {schedule.published_url && (
                            <a
                              href={schedule.published_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-xs text-primary hover:underline mt-1 inline-flex items-center gap-1"
                            >
                              <ExternalLink className="size-3" />
                              noteで見る
                            </a>
                          )}
                        </div>
                        {schedule.status === 'scheduled' && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => {
                              if (confirm('この予約をキャンセルしますか？')) {
                                cancelSchedule.mutate(schedule.id);
                              }
                            }}
                          >
                            <Ban className="size-3.5" />
                            取消
                          </Button>
                        )}
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}
            </TabsContent>

            {/* Posts Tab */}
            <TabsContent value="posts">
              {!postsData?.posts.length ? (
                <Card className="py-12">
                  <CardContent className="flex flex-col items-center gap-3">
                    <Send className="size-8 text-muted-foreground" />
                    <p className="text-muted-foreground">まだ投稿がありません</p>
                  </CardContent>
                </Card>
              ) : (
                <div className="space-y-2">
                  {postsData.posts.map((post) => (
                    <Card key={post.draft_id} className="py-3">
                      <CardContent className="flex items-center gap-3 px-4">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <h3 className="font-medium truncate">{post.title}</h3>
                            <StatusBadge status={post.status} />
                          </div>
                          <span className="text-xs text-muted-foreground">
                            {new Date(post.posted_at).toLocaleDateString('ja-JP')}
                          </span>
                        </div>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => window.open(post.note_url, '_blank')}
                        >
                          <ExternalLink className="size-3.5" />
                          noteで見る
                        </Button>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </MainLayout>
  );
}
