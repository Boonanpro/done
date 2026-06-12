import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: '電管ナレッジ検索 | 電気管理技術者ブログ横断検索',
  description:
    '全国の電気管理技術者が書いた現場ブログを横断して検索できます。点検・試験・トラブル事例など、教科書にない実務知識を一度に探せます。',
  applicationName: '電管ナレッジ検索',
  appleWebApp: {
    capable: true,
    title: '電管ナレッジ検索',
    statusBarStyle: 'default',
  },
};

export default function DenkiKnowledgeLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
