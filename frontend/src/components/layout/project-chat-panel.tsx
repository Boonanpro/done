'use client';

import { X, FolderKanban, Loader2 } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

import { Button } from '@/components/ui/button';
import { api } from '@/lib/api-client';
import { useProjectStore } from '@/stores/project-store';

interface ProjectChatPanelProps {
  projectId: string;
}

export function ProjectChatPanel({ projectId }: ProjectChatPanelProps) {
  const selectProject = useProjectStore((s) => s.selectProject);

  const { data: project, isLoading } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.projects.get(projectId),
    enabled: !!projectId,
  });

  return (
    <div className="flex flex-col h-full overflow-hidden border-r border-border bg-background">
      {/* Header */}
      <div className="shrink-0 flex items-center gap-3 px-4 py-3 border-b border-border">
        <FolderKanban className="h-5 w-5 text-primary shrink-0" />
        <div className="flex-1 min-w-0">
          {isLoading ? (
            <div className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              <span className="text-sm text-muted-foreground">読み込み中...</span>
            </div>
          ) : (
            <>
              <h2 className="font-semibold text-sm truncate">{project?.title}</h2>
              <p className="text-xs text-muted-foreground truncate">{project?.description || 'プロジェクト'}</p>
            </>
          )}
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0"
          onClick={() => selectProject(null)}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Placeholder body */}
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="text-center">
          <FolderKanban className="h-12 w-12 text-muted-foreground/30 mx-auto mb-4" />
          <p className="text-sm text-muted-foreground">
            プロジェクトチャット (Step 4で実装)
          </p>
        </div>
      </div>
    </div>
  );
}
