'use client';

import { useEffect, useState } from 'react';

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

const statusStyles: Record<string, { bg: string; label: string }> = {
  planning: { bg: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30', label: '計画中' },
  in_progress: { bg: 'bg-blue-500/20 text-blue-400 border-blue-500/30', label: '制作中' },
  review: { bg: 'bg-violet-500/20 text-violet-400 border-violet-500/30', label: 'レビュー' },
  deployed: { bg: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30', label: '公開済み' },
  maintenance: { bg: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30', label: '保守中' },
  archived: { bg: 'bg-neutral-500/20 text-neutral-400 border-neutral-500/30', label: 'アーカイブ' },
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
  const [filterStatus, setFilterStatus] = useState('');

  useEffect(() => {
    const params = new URLSearchParams();
    if (filterStatus) params.set('status', filterStatus);
    fetch(`${API_BASE}/dashboard/dx/projects?${params}`)
      .then((r) => r.json())
      .then((d) => setProjects(d.projects || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [filterStatus]);

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-white mb-1">プロジェクト</h1>
          <p className="text-sm text-neutral-500">{projects.length} 件</p>
        </div>
      </div>

      {/* Filter */}
      <div className="flex gap-2 flex-wrap">
        {['', 'planning', 'in_progress', 'deployed', 'maintenance'].map((s) => (
          <button
            key={s}
            onClick={() => setFilterStatus(s)}
            className={`px-3 py-1.5 rounded-lg text-xs transition-colors ${
              filterStatus === s
                ? 'bg-white text-neutral-900'
                : 'bg-neutral-800 text-neutral-400 hover:text-white'
            }`}
          >
            {s === '' ? 'すべて' : statusStyles[s]?.label || s}
          </button>
        ))}
      </div>

      {/* Projects */}
      {loading ? (
        <div className="flex items-center justify-center h-32">
          <div className="w-6 h-6 border-2 border-neutral-600 border-t-white rounded-full animate-spin" />
        </div>
      ) : projects.length === 0 ? (
        <div className="text-center py-16 text-neutral-500">
          <p className="text-lg mb-2">プロジェクトがありません</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {projects.map((project) => {
            const st = statusStyles[project.status] || statusStyles.planning;
            return (
              <div
                key={project.id}
                className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-5 hover:bg-neutral-800/60 hover:border-neutral-700 transition-all"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className={`text-xs px-2 py-0.5 rounded-full border ${st.bg}`}>
                      {st.label}
                    </span>
                    <span className="text-xs text-neutral-600">
                      {typeLabels[project.project_type] || project.project_type}
                    </span>
                  </div>
                </div>
                <h3 className="text-base font-medium text-white mb-1">{project.name}</h3>
                <p className="text-sm text-neutral-500 mb-3">
                  {project.dx_clients?.name || '不明なクライアント'}
                </p>

                {/* Tech Stack */}
                {project.tech_stack && project.tech_stack.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mb-3">
                    {project.tech_stack.map((tech) => (
                      <span
                        key={tech}
                        className="text-xs px-2 py-0.5 rounded bg-neutral-800 text-neutral-400"
                      >
                        {tech}
                      </span>
                    ))}
                  </div>
                )}

                {/* Links */}
                {project.deploy_url && (
                  <a
                    href={project.deploy_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
                  >
                    {project.deploy_url.replace('https://', '')}
                  </a>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
