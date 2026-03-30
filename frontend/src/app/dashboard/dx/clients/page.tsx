'use client';

import { useEffect, useState } from 'react';
import { Plus, Search, FolderOpen } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Separator } from '@/components/ui/separator';

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

const statusConfig: Record<string, { variant: 'default' | 'outline' | 'secondary' | 'destructive'; label: string; className: string }> = {
  lead: { variant: 'outline', label: 'リード', className: 'text-blue-400 border-blue-400/30' },
  active: { variant: 'outline', label: 'アクティブ', className: 'text-emerald-400 border-emerald-400/30' },
  paused: { variant: 'outline', label: '一時停止', className: 'text-yellow-400 border-yellow-400/30' },
  churned: { variant: 'outline', label: '解約', className: 'text-red-400 border-red-400/30' },
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
          <h1 className="text-2xl font-semibold text-foreground mb-1">クライアント</h1>
          <p className="text-sm text-muted-foreground">{clients.length} 件</p>
        </div>
        <Button onClick={() => setShowForm(!showForm)}>
          <Plus className="h-4 w-4 mr-2" />
          新規クライアント
        </Button>
      </div>

      {/* New Client Form */}
      {showForm && (
        <Card>
          <CardContent className="pt-6 space-y-4">
            <h3 className="text-sm font-medium text-foreground">新規クライアント登録</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="name">会社名 *</Label>
                <Input
                  id="name"
                  placeholder="会社名"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="industry">業種</Label>
                <Input
                  id="industry"
                  placeholder="業種"
                  value={formData.industry}
                  onChange={(e) => setFormData({ ...formData, industry: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="contact_person">担当者名</Label>
                <Input
                  id="contact_person"
                  placeholder="担当者名"
                  value={formData.contact_person}
                  onChange={(e) => setFormData({ ...formData, contact_person: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="contact_email">メール</Label>
                <Input
                  id="contact_email"
                  type="email"
                  placeholder="メール"
                  value={formData.contact_email}
                  onChange={(e) => setFormData({ ...formData, contact_email: e.target.value })}
                />
              </div>
            </div>
            <div className="flex gap-2">
              <Button onClick={handleCreate} disabled={saving || !formData.name.trim()}>
                {saving ? '保存中...' : '登録'}
              </Button>
              <Button variant="ghost" onClick={() => setShowForm(false)}>
                キャンセル
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Search */}
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="クライアント検索..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
      </div>

      {/* Client List */}
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="pt-6 space-y-3">
                <Skeleton className="h-5 w-40" />
                <Skeleton className="h-4 w-64" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : clients.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <FolderOpen className="h-10 w-10 text-muted-foreground mb-3" />
            <p className="text-muted-foreground">クライアントがありません</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {clients.map((client) => {
            const st = statusConfig[client.status] || statusConfig.active;
            return (
              <Card key={client.id} className="hover:bg-secondary/30 transition-colors">
                <CardContent className="pt-6">
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-3 mb-1">
                        <h3 className="text-base font-medium text-foreground">{client.name}</h3>
                        <Badge variant={st.variant} className={st.className}>
                          {st.label}
                        </Badge>
                      </div>
                      <div className="flex items-center gap-4 text-sm text-muted-foreground">
                        {client.industry && <span>{client.industry}</span>}
                        {client.contact_person && (
                          <>
                            <Separator orientation="vertical" className="h-4" />
                            <span>担当: {client.contact_person}</span>
                          </>
                        )}
                        {client.contact_email && (
                          <>
                            <Separator orientation="vertical" className="h-4" />
                            <span>{client.contact_email}</span>
                          </>
                        )}
                      </div>
                      {client.notes && (
                        <p className="text-xs text-muted-foreground mt-2">{client.notes}</p>
                      )}
                    </div>
                    <span className="text-xs text-muted-foreground shrink-0">
                      {new Date(client.created_at).toLocaleDateString('ja-JP')}
                    </span>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
