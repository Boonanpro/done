'use client';

import { useState, useRef, useEffect } from 'react';
import {
  Search, FileText, FolderOpen, Star, Plus, ChevronRight, ChevronDown,
  Upload, Image, FileSpreadsheet, Film, MoreHorizontal, Sparkles,
  Hash, List, Type, Code, Quote, Minus, CheckSquare, Table,
  Calendar, LayoutGrid, MessageSquare, Send, X, File,
} from 'lucide-react';
import { cn } from '@/lib/utils';

// ============================================================
// Mock Data
// ============================================================

interface PageNode {
  id: string;
  title: string;
  icon: string;
  children?: PageNode[];
  isStarred?: boolean;
}

interface FileItem {
  id: string;
  name: string;
  type: 'pdf' | 'image' | 'video' | 'doc' | 'spreadsheet';
  category: string;
  date: string;
  size: string;
  thumbnail?: string;
}

interface Block {
  id: string;
  type: 'heading1' | 'heading2' | 'heading3' | 'paragraph' | 'bullet' | 'todo' | 'divider' | 'callout' | 'code';
  content: string;
  checked?: boolean;
}

const WORKSPACE_TREE: PageNode[] = [
  {
    id: 'projects', title: 'プロジェクト', icon: '📁', children: [
      { id: 'yoshikawa', title: '吉川特装自動車', icon: '🚛', children: [
        { id: 'y-hp', title: 'ホームページ', icon: '🌐' },
        { id: 'y-proposal', title: '提案書', icon: '📝' },
        { id: 'y-assets', title: '素材', icon: '🖼' },
      ]},
      { id: 'gojo', title: 'OBANZAI bar 五条', icon: '🍶', children: [
        { id: 'g-hp', title: 'ホームページ', icon: '🌐' },
        { id: 'g-menu', title: 'メニュー', icon: '📋' },
      ]},
      { id: 'bird', title: 'バードSTC', icon: '🎾', children: [
        { id: 'b-hp', title: 'ホームページ', icon: '🌐' },
      ]},
    ],
  },
  {
    id: 'company', title: '会社資料', icon: '🏢', children: [
      { id: 'amex', title: 'AMEX明細', icon: '💳' },
      { id: 'tax', title: '税務書類', icon: '📊' },
      { id: 'invoices', title: '請求書', icon: '📄' },
      { id: 'receipts', title: '領収書', icon: '🧾' },
    ],
  },
  {
    id: 'templates', title: 'テンプレート', icon: '📐', children: [
      { id: 'tpl-proposal', title: '提案書テンプレート', icon: '📝' },
      { id: 'tpl-invoice', title: '請求書テンプレート', icon: '📄' },
    ],
  },
];

const STARRED: PageNode[] = [
  { id: 'yoshikawa', title: '吉川特装自動車', icon: '🚛', isStarred: true },
  { id: 'amex', title: 'AMEX明細', icon: '💳', isStarred: true },
];

const MOCK_FILES: FileItem[] = [
  { id: '1', name: 'AMEX明細_2026年3月.pdf', type: 'pdf', category: 'AMEX明細', date: '2026/03/15', size: '2.4 MB' },
  { id: '2', name: 'AMEX明細_2026年2月.pdf', type: 'pdf', category: 'AMEX明細', date: '2026/02/15', size: '1.8 MB' },
  { id: '3', name: 'AMEX明細_2026年1月.pdf', type: 'pdf', category: 'AMEX明細', date: '2026/01/15', size: '2.1 MB' },
  { id: '4', name: '確定申告書_2025.pdf', type: 'pdf', category: '税務書類', date: '2026/03/01', size: '4.2 MB' },
  { id: '5', name: '法人税納付書.pdf', type: 'pdf', category: '税務書類', date: '2026/02/28', size: '1.1 MB' },
  { id: '6', name: '吉川特装_トップページ.png', type: 'image', category: '吉川特装自動車', date: '2026/03/20', size: '3.8 MB' },
  { id: '7', name: '吉川特装_サービス一覧.png', type: 'image', category: '吉川特装自動車', date: '2026/03/20', size: '2.9 MB' },
  { id: '8', name: '五条_メニュー写真.jpg', type: 'image', category: 'OBANZAI bar 五条', date: '2026/03/10', size: '5.1 MB' },
  { id: '9', name: 'HP制作提案書_吉川様.pdf', type: 'pdf', category: '吉川特装自動車', date: '2026/02/15', size: '3.3 MB' },
  { id: '10', name: '売上管理表_Q1.xlsx', type: 'spreadsheet', category: '会社資料', date: '2026/04/01', size: '890 KB' },
  { id: '11', name: 'デモ動画_v2.mp4', type: 'video', category: '吉川特装自動車', date: '2026/03/25', size: '28.5 MB' },
  { id: '12', name: '請求書_五条_3月.pdf', type: 'pdf', category: '請求書', date: '2026/03/31', size: '420 KB' },
];

const MOCK_BLOCKS: Block[] = [
  { id: 'b1', type: 'heading1', content: '吉川特装自動車 プロジェクト' },
  { id: 'b2', type: 'paragraph', content: '鳥取県吉川特装自動車のホームページ制作プロジェクト。新明和認定のサービス工場として、特装車の修理・整備を専門に行う企業のWebサイト。' },
  { id: 'b3', type: 'divider', content: '' },
  { id: 'b4', type: 'heading2', content: '進捗状況' },
  { id: 'b5', type: 'todo', content: 'デザインカンプ作成', checked: true },
  { id: 'b6', type: 'todo', content: 'トップページ実装', checked: true },
  { id: 'b7', type: 'todo', content: 'サービスページ実装', checked: true },
  { id: 'b8', type: 'todo', content: 'お問い合わせフォーム', checked: true },
  { id: 'b9', type: 'todo', content: 'Vercelデプロイ', checked: true },
  { id: 'b10', type: 'todo', content: 'SEO最適化', checked: false },
  { id: 'b11', type: 'divider', content: '' },
  { id: 'b12', type: 'heading2', content: '技術スタック' },
  { id: 'b13', type: 'bullet', content: 'Astro + Tailwind CSS' },
  { id: 'b14', type: 'bullet', content: 'shadcn/ui コンポーネント' },
  { id: 'b15', type: 'bullet', content: 'Vercel (無料プラン)' },
  { id: 'b16', type: 'bullet', content: 'Google Imagen (画像生成)' },
  { id: 'b17', type: 'divider', content: '' },
  { id: 'b18', type: 'callout', content: '💡 クライアントから「スマホでの見え方を重視してほしい」とリクエストあり。レスポンシブ対応を優先。' },
  { id: 'b19', type: 'heading2', content: 'リンク' },
  { id: 'b20', type: 'paragraph', content: '🌐 本番URL: https://yoshikawa-tokuso.vercel.app' },
];

// ============================================================
// Sub Components
// ============================================================

function TreeItem({ node, depth = 0, selectedId, onSelect }: {
  node: PageNode;
  depth?: number;
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(depth < 1);
  const hasChildren = node.children && node.children.length > 0;

  return (
    <div>
      <div
        className={cn(
          'flex items-center gap-1 py-[3px] px-2 rounded-md cursor-pointer text-sm group',
          'hover:bg-[rgba(255,255,255,0.06)]',
          selectedId === node.id && 'bg-[rgba(255,255,255,0.08)]'
        )}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onClick={() => {
          onSelect(node.id);
          if (hasChildren) setExpanded(!expanded);
        }}
      >
        {hasChildren ? (
          <span className="w-4 h-4 flex items-center justify-center text-[#999] shrink-0">
            {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          </span>
        ) : (
          <span className="w-4 shrink-0" />
        )}
        <span className="shrink-0">{node.icon}</span>
        <span className={cn(
          'truncate',
          selectedId === node.id ? 'text-[#ebebeb]' : 'text-[#999]'
        )}>
          {node.title}
        </span>
      </div>
      {expanded && hasChildren && node.children!.map(child => (
        <TreeItem key={child.id} node={child} depth={depth + 1} selectedId={selectedId} onSelect={onSelect} />
      ))}
    </div>
  );
}

function BlockRenderer({ block }: { block: Block }) {
  switch (block.type) {
    case 'heading1':
      return <h1 className="text-3xl font-bold text-[#ebebeb] mt-8 mb-2">{block.content}</h1>;
    case 'heading2':
      return <h2 className="text-xl font-semibold text-[#ebebeb] mt-6 mb-2">{block.content}</h2>;
    case 'heading3':
      return <h3 className="text-lg font-medium text-[#ebebeb] mt-4 mb-1">{block.content}</h3>;
    case 'paragraph':
      return <p className="text-[#b4b4b4] leading-relaxed my-1">{block.content}</p>;
    case 'bullet':
      return (
        <div className="flex items-start gap-2 my-[2px] text-[#b4b4b4]">
          <span className="mt-[6px] w-[5px] h-[5px] rounded-full bg-[#666] shrink-0" />
          <span>{block.content}</span>
        </div>
      );
    case 'todo':
      return (
        <div className="flex items-center gap-2 my-[2px]">
          <input
            type="checkbox"
            checked={block.checked}
            readOnly
            className="w-4 h-4 rounded border-[#555] accent-blue-500"
          />
          <span className={cn('text-[#b4b4b4]', block.checked && 'line-through text-[#666]')}>
            {block.content}
          </span>
        </div>
      );
    case 'divider':
      return <hr className="border-[#333] my-4" />;
    case 'callout':
      return (
        <div className="bg-[#1e1e2e] border-l-4 border-blue-500/50 px-4 py-3 rounded-r-md my-3 text-[#b4b4b4]">
          {block.content}
        </div>
      );
    case 'code':
      return (
        <pre className="bg-[#1a1a2e] p-4 rounded-md my-3 text-sm text-[#a0d0a0] font-mono overflow-x-auto">
          {block.content}
        </pre>
      );
    default:
      return <p className="text-[#b4b4b4]">{block.content}</p>;
  }
}

function FileCard({ file }: { file: FileItem }) {
  const typeColors: Record<string, string> = {
    pdf: 'bg-red-500/20 text-red-400',
    image: 'bg-amber-500/20 text-amber-400',
    video: 'bg-purple-500/20 text-purple-400',
    doc: 'bg-blue-500/20 text-blue-400',
    spreadsheet: 'bg-green-500/20 text-green-400',
  };
  const typeIcons: Record<string, React.ReactNode> = {
    pdf: <FileText className="w-8 h-8" />,
    image: <Image className="w-8 h-8" />,
    video: <Film className="w-8 h-8" />,
    doc: <FileText className="w-8 h-8" />,
    spreadsheet: <FileSpreadsheet className="w-8 h-8" />,
  };

  return (
    <div className="bg-[#1e1e1e] border border-[#333] rounded-lg p-4 hover:border-[#555] transition-colors cursor-pointer group">
      <div className={cn('w-full h-24 rounded-md mb-3 flex items-center justify-center', typeColors[file.type])}>
        {typeIcons[file.type]}
      </div>
      <div className="text-sm text-[#ebebeb] truncate font-medium">{file.name}</div>
      <div className="flex items-center justify-between mt-2">
        <span className="text-xs text-[#666]">{file.date}</span>
        <span className="text-xs text-[#666]">{file.size}</span>
      </div>
    </div>
  );
}

// ============================================================
// Slash Command Menu
// ============================================================

function SlashMenu({ visible, position }: { visible: boolean; position: { x: number; y: number } }) {
  if (!visible) return null;
  const items = [
    { icon: <Type className="w-4 h-4" />, label: 'テキスト', desc: 'プレーンテキスト' },
    { icon: <Hash className="w-4 h-4" />, label: '見出し1', desc: '大見出し' },
    { icon: <Hash className="w-4 h-4 opacity-70" />, label: '見出し2', desc: '中見出し' },
    { icon: <List className="w-4 h-4" />, label: '箇条書き', desc: 'リスト' },
    { icon: <CheckSquare className="w-4 h-4" />, label: 'To-Do', desc: 'チェックリスト' },
    { icon: <Table className="w-4 h-4" />, label: 'テーブル', desc: 'データテーブル' },
    { icon: <Code className="w-4 h-4" />, label: 'コード', desc: 'コードブロック' },
    { icon: <Quote className="w-4 h-4" />, label: 'コールアウト', desc: '注意書き' },
    { icon: <Minus className="w-4 h-4" />, label: '区切り線', desc: '水平線' },
    { icon: <Image className="w-4 h-4" />, label: '画像', desc: '画像を埋め込み' },
    { icon: <Upload className="w-4 h-4" />, label: 'ファイル', desc: 'ファイルを添付' },
  ];

  return (
    <div
      className="absolute z-50 w-72 bg-[#252525] border border-[#444] rounded-lg shadow-2xl py-2 overflow-hidden"
      style={{ left: position.x, top: position.y }}
    >
      <div className="px-3 py-1 text-xs text-[#777] uppercase tracking-wider">ブロックを追加</div>
      {items.map((item, i) => (
        <div
          key={i}
          className={cn(
            'flex items-center gap-3 px-3 py-2 cursor-pointer',
            i === 0 ? 'bg-[rgba(255,255,255,0.06)]' : 'hover:bg-[rgba(255,255,255,0.06)]'
          )}
        >
          <span className="text-[#888]">{item.icon}</span>
          <div>
            <div className="text-sm text-[#ddd]">{item.label}</div>
            <div className="text-xs text-[#666]">{item.desc}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

// ============================================================
// AI Chat Panel
// ============================================================

function AIChatPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [messages, setMessages] = useState([
    { role: 'assistant' as const, content: 'こんにちは！資料について何でも聞いてください。' },
  ]);
  const [input, setInput] = useState('');
  const [typing, setTyping] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = () => {
    if (!input.trim()) return;
    const userMsg = input;
    setMessages(prev => [...prev, { role: 'user', content: userMsg }]);
    setInput('');
    setTyping(true);

    setTimeout(() => {
      let reply = 'すみません、その質問にはまだ対応していません。';
      if (userMsg.includes('請求書')) {
        reply = 'はい、最新の請求書はこちらです。\n\n📄 請求書_五条_3月.pdf (420 KB)\n📅 2026/03/31\n📁 請求書カテゴリに保存済み';
      } else if (userMsg.includes('吉川') || userMsg.includes('HP')) {
        reply = '吉川特装自動車のプロジェクトファイル一覧です。\n\n🌐 トップページ.png\n📝 HP制作提案書_吉川様.pdf\n🎬 デモ動画_v2.mp4\n\n計11ファイル、最終更新: 2026/03/25';
      } else if (userMsg.includes('AMEX') || userMsg.includes('明細')) {
        reply = 'AMEX明細の直近3ヶ月分です。\n\n💳 2026年3月 (2.4 MB)\n💳 2026年2月 (1.8 MB)\n💳 2026年1月 (2.1 MB)\n\n自動分類済み、税務書類カテゴリにも関連付けされています。';
      }
      setMessages(prev => [...prev, { role: 'assistant', content: reply }]);
      setTyping(false);
    }, 1200);
  };

  if (!open) return null;

  return (
    <div className="w-96 border-l border-[#333] bg-[#191919] flex flex-col">
      <div className="h-12 flex items-center justify-between px-4 border-b border-[#333]">
        <div className="flex items-center gap-2 text-sm font-medium text-[#ebebeb]">
          <Sparkles className="w-4 h-4 text-amber-400" />
          ダン AI
        </div>
        <button onClick={onClose} className="text-[#666] hover:text-[#999]">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((msg, i) => (
          <div key={i} className={cn('flex', msg.role === 'user' ? 'justify-end' : 'justify-start')}>
            <div className={cn(
              'max-w-[85%] px-3 py-2 rounded-lg text-sm whitespace-pre-wrap',
              msg.role === 'user'
                ? 'bg-blue-600/30 text-[#ddd]'
                : 'bg-[#252525] text-[#b4b4b4]'
            )}>
              {msg.content}
            </div>
          </div>
        ))}
        {typing && (
          <div className="flex justify-start">
            <div className="bg-[#252525] px-3 py-2 rounded-lg text-sm text-[#666]">
              入力中...
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="p-3 border-t border-[#333]">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSend()}
            placeholder="資料について聞く..."
            className="flex-1 bg-[#252525] border border-[#444] rounded-lg px-3 py-2 text-sm text-[#ddd] placeholder-[#555] outline-none focus:border-[#666]"
          />
          <button
            onClick={handleSend}
            className="bg-blue-600/30 hover:bg-blue-600/50 text-blue-400 rounded-lg px-3 py-2 transition-colors"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

// ============================================================
// Main Page
// ============================================================

export default function NotionDemoPage() {
  const [selectedPage, setSelectedPage] = useState('yoshikawa');
  const [view, setView] = useState<'editor' | 'files'>('editor');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<FileItem[] | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [slashMenu, setSlashMenu] = useState(false);
  const [sidebarSections, setSidebarSections] = useState({ starred: true, workspace: true });

  // Search
  useEffect(() => {
    if (!searchQuery.trim()) {
      setSearchResults(null);
      return;
    }
    const timer = setTimeout(() => {
      const results = MOCK_FILES.filter(f =>
        f.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        f.category.toLowerCase().includes(searchQuery.toLowerCase())
      );
      setSearchResults(results);
    }, 200);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const currentFiles = searchResults ?? MOCK_FILES.filter(f => {
    if (selectedPage === 'amex') return f.category === 'AMEX明細';
    if (selectedPage === 'tax') return f.category === '税務書類';
    if (selectedPage === 'invoices') return f.category === '請求書';
    if (selectedPage === 'yoshikawa') return f.category === '吉川特装自動車';
    if (selectedPage === 'gojo') return f.category.includes('五条');
    return true;
  });

  return (
    <div className="flex h-screen bg-[#191919] text-[#b4b4b4] overflow-hidden">
      {/* Sidebar */}
      <aside className="w-60 bg-[#1e1e1e] border-r border-[#2a2a2a] flex flex-col shrink-0">
        {/* Workspace header */}
        <div className="h-12 flex items-center px-4 border-b border-[#2a2a2a]">
          <span className="text-sm font-semibold text-[#ebebeb]">📋 ダン ワークスペース</span>
        </div>

        {/* Search */}
        <div className="p-2">
          <div className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-[#252525] text-[#666]">
            <Search className="w-3.5 h-3.5" />
            <input
              type="text"
              placeholder="検索..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="bg-transparent text-sm outline-none text-[#ddd] placeholder-[#555] w-full"
            />
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto py-1 px-1">
          {/* Starred */}
          <div className="mb-2">
            <button
              onClick={() => setSidebarSections(s => ({ ...s, starred: !s.starred }))}
              className="flex items-center gap-1 px-2 py-1 text-xs text-[#666] uppercase tracking-wider hover:text-[#999] w-full"
            >
              {sidebarSections.starred ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
              <Star className="w-3 h-3" />
              お気に入り
            </button>
            {sidebarSections.starred && STARRED.map(node => (
              <TreeItem key={node.id} node={node} selectedId={selectedPage} onSelect={setSelectedPage} />
            ))}
          </div>

          {/* Workspace tree */}
          <div>
            <button
              onClick={() => setSidebarSections(s => ({ ...s, workspace: !s.workspace }))}
              className="flex items-center gap-1 px-2 py-1 text-xs text-[#666] uppercase tracking-wider hover:text-[#999] w-full"
            >
              {sidebarSections.workspace ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
              ワークスペース
            </button>
            {sidebarSections.workspace && WORKSPACE_TREE.map(node => (
              <TreeItem key={node.id} node={node} selectedId={selectedPage} onSelect={setSelectedPage} />
            ))}
          </div>
        </nav>

        {/* Bottom actions */}
        <div className="p-2 border-t border-[#2a2a2a] space-y-1">
          <button
            onClick={() => setChatOpen(!chatOpen)}
            className="flex items-center gap-2 px-3 py-2 rounded-md text-sm text-[#999] hover:bg-[rgba(255,255,255,0.06)] w-full"
          >
            <Sparkles className="w-4 h-4 text-amber-400" />
            ダン AI に聞く
          </button>
          <button className="flex items-center gap-2 px-3 py-2 rounded-md text-sm text-[#999] hover:bg-[rgba(255,255,255,0.06)] w-full">
            <Plus className="w-4 h-4" />
            新規ページ
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <header className="h-12 flex items-center justify-between px-6 border-b border-[#2a2a2a] shrink-0">
          <div className="flex items-center gap-3">
            <span className="text-sm text-[#666]">
              プロジェクト / 吉川特装自動車
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setView('editor')}
              className={cn(
                'px-3 py-1 rounded text-sm transition-colors',
                view === 'editor' ? 'bg-[#333] text-[#ebebeb]' : 'text-[#666] hover:text-[#999]'
              )}
            >
              <FileText className="w-4 h-4 inline mr-1" />
              エディタ
            </button>
            <button
              onClick={() => setView('files')}
              className={cn(
                'px-3 py-1 rounded text-sm transition-colors',
                view === 'files' ? 'bg-[#333] text-[#ebebeb]' : 'text-[#666] hover:text-[#999]'
              )}
            >
              <LayoutGrid className="w-4 h-4 inline mr-1" />
              ファイル
            </button>
            <button
              onClick={() => setChatOpen(!chatOpen)}
              className="px-3 py-1 rounded text-sm text-[#666] hover:text-[#999] transition-colors"
            >
              <MessageSquare className="w-4 h-4 inline mr-1" />
              AI
            </button>
          </div>
        </header>

        <div className="flex flex-1 overflow-hidden">
          {/* Content area */}
          <main className="flex-1 overflow-y-auto">
            {view === 'editor' ? (
              /* Block Editor View */
              <div className="max-w-3xl mx-auto px-16 py-12 relative">
                {MOCK_BLOCKS.map(block => (
                  <BlockRenderer key={block.id} block={block} />
                ))}

                {/* Empty block with slash command hint */}
                <div className="mt-4 relative">
                  <div
                    className="text-[#555] cursor-text py-1 hover:bg-[rgba(255,255,255,0.02)] rounded px-1"
                    onClick={() => setSlashMenu(!slashMenu)}
                  >
                    「/」でブロックを追加...
                  </div>
                  <SlashMenu visible={slashMenu} position={{ x: 0, y: 30 }} />
                </div>
              </div>
            ) : (
              /* File Gallery View */
              <div className="p-6">
                <div className="flex items-center justify-between mb-6">
                  <h2 className="text-lg font-semibold text-[#ebebeb]">
                    {searchResults ? `検索結果: "${searchQuery}"` : 'ファイル一覧'}
                  </h2>
                  <div className="flex items-center gap-2">
                    <button className="flex items-center gap-2 px-3 py-1.5 rounded-md text-sm bg-blue-600/20 text-blue-400 hover:bg-blue-600/30 transition-colors">
                      <Upload className="w-4 h-4" />
                      アップロード
                    </button>
                  </div>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
                  {currentFiles.map(file => (
                    <FileCard key={file.id} file={file} />
                  ))}
                </div>
              </div>
            )}
          </main>

          {/* AI Chat Panel */}
          <AIChatPanel open={chatOpen} onClose={() => setChatOpen(false)} />
        </div>
      </div>
    </div>
  );
}
