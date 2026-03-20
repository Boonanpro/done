'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { api, StudioChannel } from '@/lib/api-client';
import { Plus, Video, Youtube } from 'lucide-react';

export default function StudioPage() {
  const router = useRouter();
  const [channels, setChannels] = useState<StudioChannel[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: '', description: '', concept: '', character_name: '' });

  useEffect(() => {
    api.studio.listChannels()
      .then(setChannels)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) return;
    setCreating(true);
    try {
      const ch = await api.studio.createChannel(form);
      router.push(`/studio/${ch.id}`);
    } catch (err) {
      console.error(err);
      setCreating(false);
    }
  }

  return (
    <div className="min-h-screen bg-black text-white p-6">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold">Studio</h1>
            <p className="text-zinc-400 text-sm mt-1">AI Vlog 制作ダッシュボード</p>
          </div>
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-2 bg-white text-black px-4 py-2 rounded-lg text-sm font-medium hover:bg-zinc-200 transition-colors"
          >
            <Plus size={16} />
            新規チャンネル
          </button>
        </div>

        {/* New Channel Form */}
        {showForm && (
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 mb-6">
            <h2 className="font-semibold mb-4">チャンネル作成</h2>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="text-xs text-zinc-400 block mb-1">チャンネル名 *</label>
                <input
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-zinc-500"
                  placeholder="例: 一人ゴールドマン計画"
                  value={form.name}
                  onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  required
                />
              </div>
              <div>
                <label className="text-xs text-zinc-400 block mb-1">コンセプト</label>
                <textarea
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-zinc-500 resize-none"
                  rows={3}
                  placeholder="例: 25歳の男が金融素人から一人で投資ビジネスを立ち上げ年商10億円を目指す実録Vlog"
                  value={form.concept}
                  onChange={e => setForm(f => ({ ...f, concept: e.target.value }))}
                />
              </div>
              <div>
                <label className="text-xs text-zinc-400 block mb-1">主人公キャラクター名</label>
                <input
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-zinc-500"
                  placeholder="例: 蓮（れん）"
                  value={form.character_name}
                  onChange={e => setForm(f => ({ ...f, character_name: e.target.value }))}
                />
              </div>
              <div className="flex gap-3 pt-2">
                <button
                  type="submit"
                  disabled={creating}
                  className="bg-white text-black px-4 py-2 rounded-lg text-sm font-medium hover:bg-zinc-200 disabled:opacity-50 transition-colors"
                >
                  {creating ? '作成中...' : '作成'}
                </button>
                <button
                  type="button"
                  onClick={() => setShowForm(false)}
                  className="text-zinc-400 px-4 py-2 rounded-lg text-sm hover:text-white transition-colors"
                >
                  キャンセル
                </button>
              </div>
            </form>
          </div>
        )}

        {/* Channel List */}
        {loading ? (
          <div className="text-zinc-500 text-sm">読み込み中...</div>
        ) : channels.length === 0 ? (
          <div className="text-center py-16 text-zinc-500">
            <Video size={40} className="mx-auto mb-3 opacity-30" />
            <p className="text-sm">チャンネルがまだありません</p>
            <button
              onClick={() => setShowForm(true)}
              className="mt-4 text-zinc-400 hover:text-white text-sm underline"
            >
              最初のチャンネルを作成する
            </button>
          </div>
        ) : (
          <div className="grid gap-4">
            {channels.map(ch => (
              <button
                key={ch.id}
                onClick={() => router.push(`/studio/${ch.id}`)}
                className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 text-left hover:border-zinc-600 transition-colors"
              >
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="font-semibold">{ch.name}</h3>
                    {ch.concept && (
                      <p className="text-zinc-400 text-xs mt-1 line-clamp-2">{ch.concept}</p>
                    )}
                    {ch.character_name && (
                      <p className="text-zinc-500 text-xs mt-2">主人公: {ch.character_name}</p>
                    )}
                  </div>
                  {ch.youtube_channel_url && (
                    <Youtube size={16} className="text-red-500 shrink-0 mt-1" />
                  )}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
