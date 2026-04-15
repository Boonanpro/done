'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, Search, Loader2, Trash2, Building2, Phone, Mail, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { toast } from 'sonner';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const TOKEN_KEY = 'done-token';

function getToken() {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

async function apiFetch(path: string, options: RequestInit = {}) {
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/v1/contacts${path}`, {
    ...options,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  if (!res.ok) throw new Error('API error');
  if (res.status === 204) return {};
  return res.json();
}

interface Contact {
  id: string;
  name: string;
  company: string | null;
  email: string | null;
  phone: string | null;
  memo: string | null;
  created_at: string;
  updated_at: string;
}

export default function ContactsPage() {
  const queryClient = useQueryClient();
  const [searchQuery, setSearchQuery] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [formData, setFormData] = useState({ name: '', company: '', email: '', phone: '', memo: '' });

  const { data: contacts = [], isLoading } = useQuery<Contact[]>({
    queryKey: ['contacts'],
    queryFn: () => apiFetch(''),
  });

  const createMutation = useMutation({
    mutationFn: (data: typeof formData) => apiFetch('', { method: 'POST', body: JSON.stringify(data) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['contacts'] });
      setShowForm(false);
      setFormData({ name: '', company: '', email: '', phone: '', memo: '' });
      toast.success('連絡先を追加しました');
    },
    onError: () => toast.error('追加に失敗しました'),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiFetch(`/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['contacts'] });
      toast.success('削除しました');
    },
  });

  const filtered = contacts.filter((c) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      c.name.toLowerCase().includes(q) ||
      (c.company?.toLowerCase().includes(q)) ||
      (c.email?.toLowerCase().includes(q)) ||
      (c.phone?.includes(q))
    );
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.name.trim()) return;
    createMutation.mutate(formData);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-foreground">連絡先</h1>
        <Button onClick={() => setShowForm(!showForm)} variant={showForm ? 'outline' : 'default'}>
          {showForm ? <><X className="h-4 w-4 mr-2" />閉じる</> : <><Plus className="h-4 w-4 mr-2" />追加</>}
        </Button>
      </div>

      {showForm && (
        <form onSubmit={handleSubmit} className="border rounded-lg p-4 space-y-3 bg-card">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Input
              placeholder="名前 *"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              required
            />
            <Input
              placeholder="会社名"
              value={formData.company}
              onChange={(e) => setFormData({ ...formData, company: e.target.value })}
            />
            <Input
              placeholder="メールアドレス"
              type="email"
              value={formData.email}
              onChange={(e) => setFormData({ ...formData, email: e.target.value })}
            />
            <Input
              placeholder="電話番号"
              type="tel"
              value={formData.phone}
              onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
            />
          </div>
          <Input
            placeholder="メモ"
            value={formData.memo}
            onChange={(e) => setFormData({ ...formData, memo: e.target.value })}
          />
          <Button type="submit" disabled={createMutation.isPending || !formData.name.trim()}>
            {createMutation.isPending ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Plus className="h-4 w-4 mr-2" />}
            保存
          </Button>
        </form>
      )}

      <div className="relative max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="名前・会社名・メールで検索..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="pl-10"
        />
      </div>

      {filtered.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">
          {contacts.length === 0 ? '連絡先がありません。「追加」ボタンから登録してください。' : '検索結果がありません。'}
        </div>
      ) : (
        <div className="border rounded-lg divide-y">
          {filtered.map((contact) => (
            <div key={contact.id} className="p-4 flex items-start justify-between gap-4 hover:bg-muted/50 transition-colors">
              <div className="min-w-0 flex-1">
                <div className="font-medium text-foreground">{contact.name}</div>
                <div className="flex flex-wrap gap-x-4 gap-y-1 mt-1 text-sm text-muted-foreground">
                  {contact.company && (
                    <span className="flex items-center gap-1">
                      <Building2 className="h-3.5 w-3.5" />{contact.company}
                    </span>
                  )}
                  {contact.email && (
                    <a href={`mailto:${contact.email}`} className="flex items-center gap-1 hover:text-foreground">
                      <Mail className="h-3.5 w-3.5" />{contact.email}
                    </a>
                  )}
                  {contact.phone && (
                    <a href={`tel:${contact.phone}`} className="flex items-center gap-1 hover:text-foreground">
                      <Phone className="h-3.5 w-3.5" />{contact.phone}
                    </a>
                  )}
                </div>
                {contact.memo && <div className="text-xs text-muted-foreground mt-1">{contact.memo}</div>}
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="shrink-0 text-muted-foreground hover:text-destructive"
                onClick={() => {
                  if (confirm(`「${contact.name}」を削除しますか？`)) {
                    deleteMutation.mutate(contact.id);
                  }
                }}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
        </div>
      )}

      <div className="text-xs text-muted-foreground">{filtered.length} 件</div>
    </div>
  );
}
