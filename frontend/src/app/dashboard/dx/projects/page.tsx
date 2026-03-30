'use client';

import { useEffect, useState } from 'react';
import { ExternalLink, FolderOpen } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';

const API_BASE = 'http://127.0.0.1:8000/api';

interface Project {
  id: string;
  client_id: string;
  name: string;
  project_type: string;
  tech_stack: string[];
  deploy_url: string | null;
  repo_url: string | null;
  status: string;
  estimated_amount: number;
  notes: string | null;
  started_at: string | null;
  deployed_at: string | null;
  created_at: string;
  dx_clients: { name: string } | null;
}

const statusConfig: Record<string, { label: string; className: string }> = {
  planning: { label: '計画中', className: 'text-yellow-400 border-yellow-400/30' },
  in_progress: { label: '制作中', className: 'text-blue-400 border-blue-400/30' },
  review: { label: 'レビュー', className: 'text-violet-400 border-violet-400/30' },
  deployed: { label: '公開済み', className: 'text-emerald-400 border-emerald-400/30' },
  maintenance: { label: '保守中', className: 'text-cyan-400 border-cyan-400/30' },
  archived: { label: 'アーカイブ', className: 'text-muted-foreground border-border' },
};

const typeLabels: Record<string, string> = {
  homepage: 'ホームページ',
  lp: 'LP',
  ec: 'ECサイト',
  dx_tool: 'DXツール',
  redesign: 'リデザイン',
  other: 'その他',
};

export default function DxProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState('all');

  useEffect(() => {
    const params = new URLSearchParams();
    if (filterStatus !== 'all') params.set('status', filterStatus);
    fetch(`${API_BASE}/dashboard/dx/projects?${params}`)
      .then((r) => r.json())
      .then((d) => setProjects(d.projects || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [filterStatus]);

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-foreground mb-1">プロジェクト</h1>
        <p className="text-sm text-muted-foreground">{projects.length} 件</p>
      </div>

      {/* Filter Tabs */}
      <Tabs value={filterStatus} onValueChange={setFilterStatus}>
        <TabsList>
          <TabsTrigger value="all">すべて</TabsTrigger>
          <TabsTrigger value="planning">計画中</TabsTrigger>
          <TabsTrigger value="in_progress">制作中</TabsTrigger>
          <TabsTrigger value="deployed">公開済み</TabsTrigger>
          <TabsTrigger value="maintenance">保守中</TabsTrigger>
        </TabsList>
      </Tabs>

      {/* Projects */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="pt-6 space-y-3">
                <Skeleton className="h-5 w-20" />
                <Skeleton className="h-5 w-40" />
                <Skeleton className="h-4 w-32" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : projects.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <FolderOpen className="h-10 w-10 text-muted-foreground mb-3" />
            <p className="text-muted-foreground">プロジェクトがありません</p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {projects.map((project) => {
            const st = statusConfig[project.status] || statusConfig.planning;
            return (
              <Card key={project.id} className="hover:bg-secondary/30 transition-colors">
                <CardContent className="pt-6">
                  <div className="flex items-center gap-2 mb-3">
                    <Badge variant="outline" className={st.className}>
                      {st.label}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {typeLabels[project.project_type] || project.project_type}
                    </span>
                  </div>

                  <h3 className="text-base font-medium text-foreground mb-1">{project.name}</h3>
                  <p className="text-sm text-muted-foreground mb-3">
                    {project.dx_clients?.name || '不明なクライアント'}
                  </p>

                  {/* Tech Stack */}
                  {project.tech_stack && project.tech_stack.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mb-3">
                      {project.tech_stack.map((tech) => (
                        <Badge key={tech} variant="secondary" className="text-xs">
                          {tech}
                        </Badge>
                      ))}
                    </div>
                  )}

                  {/* Deploy URL */}
                  {project.deploy_url && (
                    <a
                      href={project.deploy_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                    >
                      <ExternalLink className="h-3 w-3" />
                      {project.deploy_url.replace('https://', '')}
                    </a>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
