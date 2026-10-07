'use client';

/**
 * 並行作業バー: 1つの部屋の中で、メインの会話と並行して走っている作業の一覧。
 *
 * - 一覧が空なら何も描かない。あれば1行の折りたたみバー「並行作業 N件（進行中 M）」。
 * - 開くと各作業の題名・モデル・状態・最新の進み具合を1行ずつ出し、
 *   指示を足す / モデルを替える / 止める / 結果を見る の操作ができる。
 * - 動いている作業がある間（かつ画面が見えている間）は4秒ごと、それ以外は30秒ごとに取り直す。
 *
 * API: GET/POST /api/v1/projects/{id}/parallel-jobs, POST .../{job_id}/control
 */

import { useCallback, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { ChevronDown, ChevronRight, Layers, Loader2, Plus, X } from 'lucide-react';

export type ParallelJobState =
  | 'queued'
  | 'running'
  | 'waiting'
  | 'awaiting_confirmation'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface ParallelJob {
  id: string;
  title: string;
  task: string;
  model: string;
  model_label: string;
  state: ParallelJobState;
  state_label: string;
  waiting_for: string | null;
  last_progress: string | null;
  result_excerpt: string | null;
  report_message_id: string | null;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ParallelJobModel {
  id: string;
  label: string;
}

interface ParallelJobsResponse {
  jobs: ParallelJob[];
  models: ParallelJobModel[];
  default_model: string;
}

type ControlBody =
  | { operation: 'update'; text: string }
  | { operation: 'cancel' }
  | { operation: 'switch_model'; model: string };

// 既存の api-client と同じ認証（localStorage の Bearer + Cookie）で叩く。
async function jobsRequest<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('done-token') : null;
  const res = await fetch(`/api/v1${path}`, {
    method: init?.method ?? 'GET',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    credentials: 'include',
    body: init?.body === undefined ? undefined : JSON.stringify(init.body),
  });
  if (!res.ok) {
    let detail = '';
    try {
      const data = (await res.json()) as { detail?: unknown };
      const d = data?.detail;
      detail =
        typeof d === 'string'
          ? d
          : d && typeof d === 'object' && typeof (d as { message?: unknown }).message === 'string'
            ? (d as { message: string }).message
            : '';
    } catch {
      // 本文が JSON でない
    }
    throw new Error(detail || `通信に失敗しました（${res.status}）`);
  }
  return (await res.json()) as T;
}

function pageVisible() {
  return typeof document === 'undefined' || document.visibilityState === 'visible';
}

interface ParallelJobsBarProps {
  projectId: string;
  /** 結果メッセージへ移動する。画面に読み込まれていなければ false を返す。 */
  onShowMessage?: (messageId: string) => boolean;
}

export function ParallelJobsBar({ projectId, onShowMessage }: ParallelJobsBarProps) {
  const queryClient = useQueryClient();
  const queryKey = ['parallel-jobs', projectId];
  const [expanded, setExpanded] = useState(false);
  const [busyJobId, setBusyJobId] = useState<string | null>(null);
  const [addingFor, setAddingFor] = useState<string | null>(null);
  const [addText, setAddText] = useState('');
  const [newOpen, setNewOpen] = useState(false);
  const [newTask, setNewTask] = useState('');
  const [newModel, setNewModel] = useState<string>('');
  const [starting, setStarting] = useState(false);

  const { data } = useQuery<ParallelJobsResponse>({
    queryKey,
    queryFn: () => jobsRequest<ParallelJobsResponse>(`/projects/${projectId}/parallel-jobs`),
    enabled: !!projectId,
    retry: false,
    refetchIntervalInBackground: true,
    refetchInterval: (query) => {
      const anyActive = !!query.state.data?.jobs?.some((j) => j.active);
      return anyActive && pageVisible() ? 4000 : 30000;
    },
  });

  const refetch = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ['parallel-jobs', projectId] });
  }, [queryClient, projectId]);

  const control = useCallback(
    async (job: ParallelJob, body: ControlBody, okMessage: string) => {
      setBusyJobId(job.id);
      try {
        await jobsRequest<{ job: ParallelJob }>(
          `/projects/${projectId}/parallel-jobs/${encodeURIComponent(job.id)}/control`,
          { method: 'POST', body },
        );
        toast.success(okMessage);
        return true;
      } catch (err) {
        toast.error('操作できませんでした', { description: (err as Error).message.slice(0, 200) });
        return false;
      } finally {
        setBusyJobId(null);
        refetch();
      }
    },
    [projectId, refetch],
  );

  const jobs = data?.jobs ?? [];
  if (jobs.length === 0) return null;

  const models = data?.models ?? [];
  const defaultModel = data?.default_model ?? models[0]?.id ?? '';
  const activeCount = jobs.filter((j) => j.active).length;
  const modelLabel = (id: string) => models.find((m) => m.id === id)?.label ?? id;

  const submitAdd = async (job: ParallelJob) => {
    const text = addText.trim();
    if (!text) return;
    const ok = await control(job, { operation: 'update', text }, '指示を足しました');
    if (ok) {
      setAddingFor(null);
      setAddText('');
    }
  };

  const switchModel = (job: ParallelJob, model: string) => {
    if (!model || model === job.model) return;
    if (!window.confirm(`作業を止めて、${modelLabel(model)} で最初からやり直します。よろしいですか？`)) return;
    void control(job, { operation: 'switch_model', model }, `${modelLabel(model)} でやり直します`);
  };

  const cancel = (job: ParallelJob) => {
    if (!window.confirm(`「${job.title}」を止めますか？`)) return;
    void control(job, { operation: 'cancel' }, '止めました');
  };

  const showResult = (job: ParallelJob) => {
    if (!job.report_message_id) return;
    const ok = onShowMessage?.(job.report_message_id) ?? false;
    if (!ok) toast('結果のメッセージはまだ画面に読み込まれていません', { description: '上へスクロールして探してください' });
  };

  const start = async () => {
    const task = newTask.trim();
    if (!task) return;
    setStarting(true);
    try {
      await jobsRequest<{ job: ParallelJob }>(`/projects/${projectId}/parallel-jobs`, {
        method: 'POST',
        body: { task, model: newModel || defaultModel },
      });
      toast.success('並行作業を始めました');
      setNewTask('');
      setNewOpen(false);
    } catch (err) {
      toast.error('始められませんでした', { description: (err as Error).message.slice(0, 200) });
    } finally {
      setStarting(false);
      refetch();
    }
  };

  return (
    <div className="sticky top-0 z-20 border-b border-border bg-background text-xs shadow-sm">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-1.5 px-4 py-1.5 text-left text-muted-foreground hover:text-foreground"
        aria-expanded={expanded}
      >
        {expanded ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
        <Layers className="h-3.5 w-3.5 shrink-0" />
        <span className="font-medium text-foreground">並行作業 {jobs.length}件</span>
        <span>（進行中 {activeCount}）</span>
        {activeCount > 0 ? <Loader2 className="h-3 w-3 shrink-0 animate-spin" /> : null}
      </button>

      {expanded ? (
        <div className="max-h-[40vh] overflow-y-auto px-4 pb-2">
          <ul className="flex flex-col divide-y divide-border/60">
            {jobs.map((job) => {
              const busy = busyJobId === job.id;
              const status = job.waiting_for ? `${job.state_label}・${job.waiting_for}` : job.state_label;
              const detail = job.active ? job.last_progress : job.result_excerpt ?? job.last_progress;
              const stateTone =
                job.state === 'failed'
                  ? 'text-destructive'
                  : job.state === 'awaiting_confirmation'
                    ? 'text-amber-600 dark:text-amber-400'
                    : job.active
                      ? 'text-primary'
                      : 'text-muted-foreground';
              return (
                <li key={job.id} className="py-1.5">
                  <div className="flex min-w-0 items-center gap-1.5">
                    <span className="min-w-0 truncate font-medium text-foreground" title={job.task}>
                      {job.title}
                    </span>
                    <span className="shrink-0 rounded border border-border px-1 py-px text-[10px] text-muted-foreground">
                      {job.model_label}
                    </span>
                    <span className={`min-w-0 truncate ${stateTone}`} title={status}>
                      {status}
                    </span>
                    {busy ? <Loader2 className="h-3 w-3 shrink-0 animate-spin text-muted-foreground" /> : null}
                  </div>
                  {detail ? (
                    <div className="mt-0.5 truncate text-muted-foreground" title={detail}>
                      {detail}
                    </div>
                  ) : null}

                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px]">
                    {job.active ? (
                      <>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => {
                            setAddingFor((cur) => (cur === job.id ? null : job.id));
                            setAddText('');
                          }}
                          className="text-muted-foreground underline-offset-2 hover:text-foreground hover:underline disabled:opacity-50"
                        >
                          指示を足す
                        </button>
                        {models.length > 1 ? (
                          <select
                            value={job.model}
                            disabled={busy}
                            onChange={(e) => switchModel(job, e.target.value)}
                            className="rounded border border-border bg-background px-1 py-px text-[11px] text-muted-foreground disabled:opacity-50"
                            aria-label="モデルを切り替える"
                            title="モデルを切り替える（作業はやり直しになります）"
                          >
                            {models.map((m) => (
                              <option key={m.id} value={m.id}>
                                {m.label}
                              </option>
                            ))}
                          </select>
                        ) : null}
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => cancel(job)}
                          className="text-muted-foreground underline-offset-2 hover:text-destructive hover:underline disabled:opacity-50"
                        >
                          止める
                        </button>
                      </>
                    ) : null}
                    {!job.active && job.report_message_id && onShowMessage ? (
                      <button
                        type="button"
                        onClick={() => showResult(job)}
                        className="text-primary underline-offset-2 hover:underline"
                      >
                        結果を見る
                      </button>
                    ) : null}
                  </div>

                  {addingFor === job.id ? (
                    <form
                      className="mt-1 flex items-center gap-1.5"
                      onSubmit={(e) => {
                        e.preventDefault();
                        void submitAdd(job);
                      }}
                    >
                      <input
                        autoFocus
                        value={addText}
                        onChange={(e) => setAddText(e.target.value)}
                        placeholder="この作業への追加の指示"
                        className="min-w-0 flex-1 rounded border border-border bg-background px-2 py-1 text-xs text-foreground outline-none focus:border-primary"
                      />
                      <button
                        type="submit"
                        disabled={busy || !addText.trim()}
                        className="shrink-0 rounded bg-primary px-2 py-1 text-[11px] font-medium text-primary-foreground disabled:opacity-50"
                      >
                        送る
                      </button>
                      <button
                        type="button"
                        onClick={() => setAddingFor(null)}
                        className="shrink-0 text-muted-foreground hover:text-foreground"
                        aria-label="閉じる"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </form>
                  ) : null}
                </li>
              );
            })}
          </ul>

          {newOpen ? (
            <form
              className="mt-1.5 flex flex-wrap items-center gap-1.5"
              onSubmit={(e) => {
                e.preventDefault();
                void start();
              }}
            >
              <input
                autoFocus
                value={newTask}
                onChange={(e) => setNewTask(e.target.value)}
                placeholder="並行で頼みたいこと"
                className="min-w-[12rem] flex-1 rounded border border-border bg-background px-2 py-1 text-xs text-foreground outline-none focus:border-primary"
              />
              {models.length > 0 ? (
                <select
                  value={newModel || defaultModel}
                  onChange={(e) => setNewModel(e.target.value)}
                  className="rounded border border-border bg-background px-1 py-1 text-[11px] text-muted-foreground"
                  aria-label="モデル"
                >
                  {models.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label}
                    </option>
                  ))}
                </select>
              ) : null}
              <button
                type="submit"
                disabled={starting || !newTask.trim()}
                className="shrink-0 rounded bg-primary px-2 py-1 text-[11px] font-medium text-primary-foreground disabled:opacity-50"
              >
                {starting ? '開始中…' : '頼む'}
              </button>
              <button
                type="button"
                onClick={() => setNewOpen(false)}
                className="shrink-0 text-muted-foreground hover:text-foreground"
                aria-label="閉じる"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </form>
          ) : (
            <button
              type="button"
              onClick={() => setNewOpen(true)}
              className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
            >
              <Plus className="h-3 w-3" />
              並行で頼む
            </button>
          )}
        </div>
      ) : null}
    </div>
  );
}
