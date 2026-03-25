'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';

const API_BASE = 'http://127.0.0.1:8000/api';

interface Client {
  id: string;
  name: string;
  industry: string | null;
  contact_person: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  website_url: string | null;
  status: string;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

const statusStyles: Record<string, { bg: string; label: string }> = {
  lead: { bg: 'bg-blue-500/20 text-blue-400 border-blue-500/30', label: 'リード' },
  active: { bg: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30', label: 'アクティブ' },
  paused: { bg: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30', label: '一時停止' },
  churned: { bg: 'bg-red-500/20 text-red-400 border-red-500/30', label: '解約' },
};

export default function DxClientsPage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [formData, setFormData] = useState({ name: '', industry: '', contact_person: '', contact_email: '', contact_phone: '' });
  const [saving, setSaving] = useState(false);

  const fetchClients = () => {
    const params = new URLSearchParams();
    if (search) params.set('search', search);
    fetch(`${API_BASE}/dashboard/dx/clients?${params}`)
      .then((r) => r.json())
      .then((d) => setClients(d.clients || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchClients();
  }, [search]);

  const handleCreate = async () => {
    if (!formData.name.trim()) return;
    setSaving(true);
    try {
      const res = await fetch(`${API_BASE}/dashboard/dx/clients`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: formData.name,
          industry: formData.industry || null,
          contact_person: formData.contact_person || null,
          contact_email: formData.contact_email || null,
          contact_phone: formData.contact_phone || null,
        }),
      });
      if (res.ok) {
        setFormData({ name: '', industry: '', contact_person: '', contact_email: '', contact_phone: '' });
        setShowForm(false);
        fetchClients();
      }
    } catch {}
    setSaving(false);
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-white mb-1">クライアント</h1>
          <p className="text-sm text-neutral-500">{clients.length} 件</p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 rounded-lg text-sm bg-white text-neutral-900 hover:bg-neutral-200 transition-colors"
        >
          + 新規クライアント
        </button>
      </div>

      {/* New Client Form */}
      {showForm && (
        <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-5 space-y-4">
          <h3 className="text-sm font-medium text-neutral-300">新規クライアント登録</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <input
              placeholder="会社名 *"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="px-3 py-2 rounded-lg bg-neutral-800 border border-neutral-700 text-sm text-white placeholder-neutral-500 focus:outline-none focus:border-neutral-500"
            />
            <input
              placeholder="業種"
              value={formData.industry}
              onChange={(e) => setFormData({ ...formData, industry: e.target.value })}
              className="px-3 py-2 rounded-lg bg-neutral-800 border border-neutral-700 text-sm text-white placeholder-neutral-500 focus:outline-none focus:border-neutral-500"
            />
            <input
              placeholder="担当者名"
              value={formData.contact_person}
              onChange={(e) => setFormData({ ...formData, contact_person: e.target.value })}
              className="px-3 py-2 rounded-lg bg-neutral-800 border border-neutral-700 text-sm text-white placeholder-neutral-500 focus:outline-none focus:border-neutral-500"
            />
            <input
              placeholder="メール"
              value={formData.contact_email}
              onChange={(e) => setFormData({ ...formData, contact_email: e.target.value })}
              className="px-3 py-2 rounded-lg bg-neutral-800 border border-neutral-700 text-sm text-white placeholder-neutral-500 focus:outline-none focus:border-neutral-500"
            />
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleCreate}
              disabled={saving || !formData.name.trim()}
              className="px-4 py-2 rounded-lg text-sm bg-white text-neutral-900 hover:bg-neutral-200 transition-colors disabled:opacity-50"
            >
              {saving ? '保存中...' : '登録'}
            </button>
            <button
              onClick={() => setShowForm(false)}
              className="px-4 py-2 rounded-lg text-sm text-neutral-400 hover:text-white transition-colors"
            >
              キャンセル
            </button>
          </div>
        </div>
      )}

      {/* Search */}
      <div>
        <input
          placeholder="クライアント検索..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full max-w-sm px-3 py-2 rounded-lg bg-neutral-900 border border-neutral-800 text-sm text-white placeholder-neutral-500 focus:outline-none focus:border-neutral-600"
        />
      </div>

      {/* Client List */}
      {loading ? (
        <div className="flex items-center justify-center h-32">
          <div className="w-6 h-6 border-2 border-neutral-600 border-t-white rounded-full animate-spin" />
        </div>
      ) : clients.length === 0 ? (
        <div className="text-center py-16 text-neutral-500">
          <p className="text-lg mb-2">クライアントがありません</p>
        </div>
      ) : (
        <div className="space-y-2">
          {clients.map((client) => {
            const st = statusStyles[client.status] || statusStyles.active;
            return (
              <div
                key={client.id}
                className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-4 hover:bg-neutral-800/60 hover:border-neutral-700 transition-all"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3 mb-1">
                      <h3 className="text-base font-medium text-white">{client.name}</h3>
                      <span className={`text-xs px-2 py-0.5 rounded-full border ${st.bg}`}>
                        {st.label}
                      </span>
                    </div>
                    <div className="flex items-center gap-4 text-sm text-neutral-500">
                      {client.industry && <span>{client.industry}</span>}
                      {client.contact_person && <span>担当: {client.contact_person}</span>}
                      {client.contact_email && <span>{client.contact_email}</span>}
                    </div>
                    {client.notes && (
                      <p className="text-xs text-neutral-600 mt-2">{client.notes}</p>
                    )}
                  </div>
                  <span className="text-xs text-neutral-600 shrink-0">
                    {new Date(client.created_at).toLocaleDateString('ja-JP')}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
