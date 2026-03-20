'use client';

import { useEffect, useState } from 'react';
import { useRouter, useParams } from 'next/navigation';
import { api, StudioChannel, StudioEpisode } from '@/lib/api-client';
import { Plus, ChevronLeft, Film, CheckCircle2, Clock, FileText } from 'lucide-react';

const STATUS_LABEL: Record<string, string> = {
  draft: '下書き',
  scripting: '脚本作成中',
  producing: '制作中',
  published: '公開済み',
};

const STATUS_COLOR: Record<string, string> = {
  draft: 'text-zinc-500',
  scripting: 'text-yellow-500',
  producing: 'text-blue-400',
  published: 'text-green-500',
};

export default function ChannelPage() {
  const router = useRouter();
  const { channelId } = useParams<{ channelId: string }>();
  const [channel, setChannel] = useState<StudioChannel | null>(null);
  const [episodes, setEpisodes] = useState<StudioEpisode[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ title: '', episode_number: '', description: '' });

  useEffect(() => {
    Promise.all([
      api.studio.listChannels().then(chs => chs.find(c => c.id === channelId)),
      api.studio.listEpisodes(channelId),
    ]).then(([ch, eps]) => {
      if (ch) setChannel(ch);
      setEpisodes(eps);
    }).catch(console.error).finally(() => setLoading(false));
  }, [channelId]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!form.title.trim()) return;
    setCreating(true);
    try {
      const ep = await api.studio.createEpisode({
        channel_id: channelId,
        title: form.title,
        episode_number: form.episode_number ? parseInt(form.episode_number) : undefined,
        description: form.description || undefined,
      });
      router.push(`/studio/${channelId}/${ep.id}`);
    } catch (err) {
      console.error(err);
      setCreating(false);
    }
  }

  if (loading) return <div className="min-h-screen bg-black text-zinc-500 flex items-center justify-center text-sm">読み込み中...</div>;

  return (
    <div className="min-h-screen bg-black text-white p-6">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <button onClick={() => router.push('/studio')} className="text-zinc-500 hover:text-white">
            <ChevronLeft size={20} />
          </button>
          <div className="flex-1">
            <h1 className="text-xl font-bold">{channel?.name ?? 'チャンネル'}</h1>
            {channel?.concept && (
              <p className="text-zinc-400 text-xs mt-0.5 line-clamp-1">{channel.concept}</p>
            )}
          </div>
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-2 bg-white text-black px-4 py-2 rounded-lg text-sm font-medium hover:bg-zinc-200 transition-colors"
          >
            <Plus size={14} />
            新規エピソード
          </button>
        </div>

        {/* New Episode Form */}
        {showForm && (
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 mb-6">
            <h2 className="font-semibold mb-4">エピソード作成</h2>
            <form onSubmit={handleCreate} className="space-y-4">
              <div className="flex gap-3">
                <div className="w-24">
                  <label className="text-xs text-zinc-400 block mb-1">話数</label>
                  <input
                    className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-zinc-500"
                    placeholder="1"
                    type="number"
                    value={form.episode_number}
                    onChange={e => setForm(f => ({ ...f, episode_number: e.target.value }))}
                  />
                </div>
                <div className="flex-1">
                  <label className="text-xs text-zinc-400 block mb-1">タイトル *</label>
                  <input
                    className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-zinc-500"
                    placeholder="例: 俺が一人ゴールドマンを始める理由"
                    value={form.title}
                    onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
                    required
                  />
                </div>
              </div>
              <div>
                <label className="text-xs text-zinc-400 block mb-1">概要</label>
                <textarea
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-zinc-500 resize-none"
                  rows={2}
                  placeholder="このエピソードで伝えたいこと"
                  value={form.description}
                  onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                />
              </div>
              <div className="flex gap-3 pt-2">
                <button
                  type="submit"
                  disabled={creating}
                  className="bg-white text-black px-4 py-2 rounded-lg text-sm font-medium hover:bg-zinc-200 disabled:opacity-50 transition-colors"
                >
                  {creating ? '作成中...' : '作成して編集'}
                </button>
                <button
                  type="button"
                  onClick={() => setShowForm(false)}
                  className="text-zinc-400 px-4 py-2 rounded-lg text-sm hover:text-white"
                >
                  キャンセル
                </button>
              </div>
            </form>
          </div>
        )}

        {/* Episode List */}
        {episodes.length === 0 ? (
          <div className="text-center py-16 text-zinc-500">
            <Film size={40} className="mx-auto mb-3 opacity-30" />
            <p className="text-sm">エピソードがまだありません</p>
            <button
              onClick={() => setShowForm(true)}
              className="mt-4 text-zinc-400 hover:text-white text-sm underline"
            >
              最初のエピソードを作成する
            </button>
          </div>
        ) : (
          <div className="grid gap-3">
            {episodes.map(ep => (
              <button
                key={ep.id}
                onClick={() => router.push(`/studio/${channelId}/${ep.id}`)}
                className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 text-left hover:border-zinc-600 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 bg-zinc-800 rounded-lg flex items-center justify-center text-xs font-mono text-zinc-400 shrink-0">
                    {ep.episode_number ?? '–'}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm truncate">{ep.title}</span>
                      <span className={`text-xs shrink-0 ${STATUS_COLOR[ep.status] ?? 'text-zinc-500'}`}>
                        {STATUS_LABEL[ep.status] ?? ep.status}
                      </span>
                    </div>
                    {ep.description && (
                      <p className="text-zinc-500 text-xs mt-0.5 truncate">{ep.description}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2 text-zinc-600 shrink-0">
                    {ep.script_messages.length > 0 && <FileText size={14} />}
                    {ep.status === 'published' && <CheckCircle2 size={14} className="text-green-500" />}
                    {ep.scheduled_at && ep.status !== 'published' && <Clock size={14} className="text-yellow-500" />}
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
