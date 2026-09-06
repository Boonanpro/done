'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { api, type SessionModelResponse } from '@/lib/api-client';

interface ModelSwitcherProps {
  roomId: string;
}

/**
 * Per-room model / backend switcher (Claude CLI ⇄ Codex CLI).
 *
 * Switching mid-conversation is supported: persona, memory and history live in
 * Dan's DB, so the next turn on the other backend starts from a DB reseed.
 * The server refuses the change while a turn is running (409).
 */
export function ModelSwitcher({ roomId }: ModelSwitcherProps) {
  const queryClient = useQueryClient();
  const queryKey = ['session-model', roomId];
  const { data } = useQuery<SessionModelResponse>({
    queryKey,
    queryFn: () => api.dan.getSessionModel(roomId),
    staleTime: 60_000,
  });

  const mutation = useMutation({
    mutationFn: (model: string) => api.dan.setSessionModel(roomId, model),
    onSuccess: (res) => {
      queryClient.setQueryData(queryKey, res);
      const label = res.options.find((o) => o.id === res.effective_model)?.label ?? res.effective_model;
      toast.success(`次の返答から ${label} で動きます`, {
        description: '会話・記憶・人格はそのまま引き継がれます',
      });
    },
    onError: (err) => {
      toast.error('モデルを切り替えられませんでした', { description: String(err).slice(0, 160) });
    },
  });

  if (!data) return null;
  const current = data.effective_model;
  const isCodex = data.backend === 'codex';

  return (
    <label
      className={`flex shrink-0 items-center gap-1 rounded-md border px-1.5 py-1 text-xs font-medium transition-colors ${
        isCodex
          ? 'border-sky-700 bg-sky-900/30 text-sky-200'
          : 'border-border bg-background text-foreground'
      }`}
      title={
        data.can_switch
          ? 'この部屋のモデル。会話の途中でも切り替えられます（作業中は不可）'
          : 'この部屋はモデルを保存できません'
      }
    >
      <span className="hidden sm:inline">{isCodex ? 'GPT' : 'Claude'}</span>
      <select
        value={current}
        disabled={!data.can_switch || mutation.isPending}
        onChange={(e) => mutation.mutate(e.target.value)}
        className="max-w-[9.5rem] cursor-pointer bg-transparent text-xs outline-none disabled:cursor-not-allowed"
      >
        {data.options.map((o) => (
          <option key={o.id} value={o.id} className="bg-background text-foreground">
            {o.label}
          </option>
        ))}
        {!data.options.some((o) => o.id === current) && (
          <option value={current} className="bg-background text-foreground">
            {current}
          </option>
        )}
      </select>
    </label>
  );
}
