'use client';

import { useState } from 'react';
import { FileText, Zap } from 'lucide-react';

import { MainLayout } from '@/components/layout/main-layout';
import { PagesView } from '@/components/notebook/pages-view';
import { AutomationsView } from '@/components/notebook/automations-view';

type Tab = 'pages' | 'automations';

export default function NotebookPage() {
  const [tab, setTab] = useState<Tab>('pages');

  return (
    <MainLayout>
      <div className="flex flex-col h-full">
        <div className="border-b px-4 flex items-center gap-1 bg-background">
          <button
            onClick={() => setTab('pages')}
            className={`flex items-center gap-2 px-3 py-2.5 text-sm border-b-2 -mb-px ${
              tab === 'pages' ? 'border-primary text-foreground font-medium' : 'border-transparent text-muted-foreground'
            }`}
          >
            <FileText className="w-4 h-4" /> ページ
          </button>
          <button
            onClick={() => setTab('automations')}
            className={`flex items-center gap-2 px-3 py-2.5 text-sm border-b-2 -mb-px ${
              tab === 'automations' ? 'border-primary text-foreground font-medium' : 'border-transparent text-muted-foreground'
            }`}
          >
            <Zap className="w-4 h-4" /> 自動化
          </button>
        </div>
        <div className="flex-1 min-h-0">
          {tab === 'pages' ? <PagesView /> : <AutomationsView />}
        </div>
      </div>
    </MainLayout>
  );
}
