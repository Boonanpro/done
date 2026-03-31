'use client';

// Document Management - Dan版Notion
import { Suspense, useEffect, useState, useCallback, useRef } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import {
  FileStack, FolderOpen, Upload, Search, Grid3X3, List, Table2,
  Star, StarOff, MoreHorizontal, Trash2, Edit3, FolderPlus,
  File, FileText, FileImage, FileVideo, FileAudio, FileArchive,
  ChevronRight, ChevronDown, MessageSquare, Send, X, Sparkles,
  Eye, Download, Clock, Tag, Filter,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Separator } from '@/components/ui/separator';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';

const API_BASE = 'http://127.0.0.1:8000/api/dashboard/documents';

// ============================================================
// Types
// ============================================================

interface DocumentFile {
  id: string;
  filename: string;
  original_name: string;
  file_url: string;
  mime_type: string;
  file_size: number;
  version: number;
  is_current: boolean;
  thumbnail_path: string | null;
}

interface Document {
  id: string;
  parent_id: string | null;
  title: string;
  description: string | null;
  content: string | null;
  doc_type: 'folder' | 'file' | 'collection';
  category_id: string | null;
  icon: string | null;
  tags: string[];
  is_starred: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  document_files?: DocumentFile[];
  document_categories?: Category | null;
}

interface Category {
  id: string;
  name: string;
  slug: string;
  icon: string;
  parent_id: string | null;
  description: string | null;
  sort_order: number;
}

interface TreeData {
  categories: Category[];
  folders: Document[];
  recent: Document[];
}

interface Stats {
  total_documents: number;
  total_size_bytes: number;
  total_categories: number;
  starred_count: number;
  category_distribution: Record<string, number>;
}

// ============================================================
// Helpers
// ============================================================

function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

function getFileIcon(mimeType?: string, docType?: string) {
  if (docType === 'folder') return <FolderOpen className="h-5 w-5 text-amber-400" />;
  if (!mimeType) return <File className="h-5 w-5 text-muted-foreground" />;
  if (mimeType.startsWith('image/')) return <FileImage className="h-5 w-5 text-emerald-400" />;
  if (mimeType.startsWith('video/')) return <FileVideo className="h-5 w-5 text-purple-400" />;
  if (mimeType.startsWith('audio/')) return <FileAudio className="h-5 w-5 text-pink-400" />;
  if (mimeType.includes('pdf')) return <FileText className="h-5 w-5 text-red-400" />;
  if (mimeType.includes('zip') || mimeType.includes('archive') || mimeType.includes('compressed'))
    return <FileArchive className="h-5 w-5 text-yellow-400" />;
  return <FileText className="h-5 w-5 text-blue-400" />;
}

function getMimeColor(mimeType?: string): string {
  if (!mimeType) return 'from-secondary/50 to-secondary/20';
  if (mimeType.startsWith('image/')) return 'from-emerald-500/10 to-emerald-500/5';
  if (mimeType.startsWith('video/')) return 'from-purple-500/10 to-purple-500/5';
  if (mimeType.includes('pdf')) return 'from-red-500/10 to-red-500/5';
  if (mimeType.includes('html')) return 'from-blue-500/10 to-blue-500/5';
  return 'from-secondary/50 to-secondary/20';
}

// ============================================================
// Main Component
// ============================================================

export default function DocumentsPage() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center h-full text-muted-foreground">読み込み中...</div>}>
      <DocumentsPageInner />
    </Suspense>
  );
}

function DocumentsPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const fileInputRef = useRef<HTMLInputElement>(null);

  // State
  const [documents, setDocuments] = useState<Document[]>([]);
  const [treeData, setTreeData] = useState<TreeData | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState<'gallery' | 'table' | 'list'>('gallery');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<Document[] | null>(null);
  const [selectedDoc, setSelectedDoc] = useState<Document | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [currentParentId, setCurrentParentId] = useState<string | null>(null);
  const [currentCategoryId, setCurrentCategoryId] = useState<string | null>(null);
  const [breadcrumbs, setBreadcrumbs] = useState<{ id: string | null; title: string }[]>([
    { id: null, title: 'すべてのファイル' },
  ]);
  const [uploading, setUploading] = useState(false);

  // AI Chat state
  const [chatOpen, setChatOpen] = useState(false);
  const [chatMessages, setChatMessages] = useState<{ role: 'user' | 'assistant'; content: string }[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);

  // Sidebar collapse on mobile
  const [sidebarOpen, setSidebarOpen] = useState(true);

  // ============================================================
  // Data Fetching
  // ============================================================

  const fetchDocuments = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (currentParentId) params.set('parent_id', currentParentId);
      if (currentCategoryId) params.set('category_id', currentCategoryId);
      const starred = searchParams.get('starred');
      if (starred === 'true') params.set('is_starred', 'true');

      const res = await fetch(`${API_BASE}?${params}`);
      if (res.ok) {
        const data = await res.json();
        setDocuments(data.documents ?? []);
      }
    } catch (e) {
      console.error('Failed to fetch documents:', e);
    } finally {
      setLoading(false);
    }
  }, [currentParentId, currentCategoryId, searchParams]);

  const fetchTree = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/tree`);
      if (res.ok) {
        const data = await res.json();
        setTreeData(data);
      }
    } catch (e) {
      console.error('Failed to fetch tree:', e);
    }
  }, []);

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/stats`);
      if (res.ok) {
        setStats(await res.json());
      }
    } catch (e) {
      console.error('Failed to fetch stats:', e);
    }
  }, []);

  useEffect(() => {
    fetchDocuments();
    fetchTree();
    fetchStats();
  }, [fetchDocuments, fetchTree, fetchStats]);

  // ============================================================
  // Search
  // ============================================================

  useEffect(() => {
    if (!searchQuery.trim()) {
      setSearchResults(null);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const res = await fetch(`${API_BASE}/search?q=${encodeURIComponent(searchQuery)}`);
        if (res.ok) {
          const data = await res.json();
          setSearchResults(data.results);
        }
      } catch (e) {
        console.error('Search failed:', e);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // ============================================================
  // Actions
  // ============================================================

  const handleUpload = async (files: FileList) => {
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        const formData = new FormData();
        formData.append('file', file);
        if (currentParentId) formData.append('parent_id', currentParentId);
        if (currentCategoryId) formData.append('category_id', currentCategoryId);

        await fetch(`${API_BASE}/upload`, {
          method: 'POST',
          body: formData,
        });
      }
      fetchDocuments();
      fetchStats();
    } catch (e) {
      console.error('Upload failed:', e);
    } finally {
      setUploading(false);
    }
  };

  const handleToggleStar = async (doc: Document) => {
    try {
      await fetch(`${API_BASE}/${doc.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_starred: !doc.is_starred }),
      });
      setDocuments((prev) =>
        prev.map((d) => (d.id === doc.id ? { ...d, is_starred: !d.is_starred } : d))
      );
    } catch (e) {
      console.error('Toggle star failed:', e);
    }
  };

  const handleDelete = async (doc: Document) => {
    try {
      await fetch(`${API_BASE}/${doc.id}`, { method: 'DELETE' });
      setDocuments((prev) => prev.filter((d) => d.id !== doc.id));
      fetchStats();
    } catch (e) {
      console.error('Delete failed:', e);
    }
  };

  const navigateToFolder = (doc: Document) => {
    setCurrentParentId(doc.id);
    setCurrentCategoryId(null);
    setBreadcrumbs((prev) => [...prev, { id: doc.id, title: doc.title }]);
  };

  const navigateToCategory = (cat: Category) => {
    setCurrentCategoryId(cat.id);
    setCurrentParentId(null);
    setBreadcrumbs([
      { id: null, title: 'すべてのファイル' },
      { id: cat.id, title: cat.name },
    ]);
  };

  const navigateToBreadcrumb = (index: number) => {
    const bc = breadcrumbs[index];
    if (index === 0) {
      setCurrentParentId(null);
      setCurrentCategoryId(null);
    } else {
      setCurrentParentId(bc.id);
    }
    setBreadcrumbs(breadcrumbs.slice(0, index + 1));
  };

  const handleCreateFolder = async () => {
    const name = prompt('フォルダ名:');
    if (!name) return;
    try {
      await fetch(API_BASE, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: name,
          doc_type: 'folder',
          parent_id: currentParentId,
          category_id: currentCategoryId,
        }),
      });
      fetchDocuments();
    } catch (e) {
      console.error('Create folder failed:', e);
    }
  };

  // ============================================================
  // AI Chat
  // ============================================================

  const sendChatMessage = async () => {
    if (!chatInput.trim() || chatLoading) return;
    const userMsg = chatInput.trim();
    setChatInput('');
    setChatMessages((prev) => [...prev, { role: 'user', content: userMsg }]);
    setChatLoading(true);

    try {
      // Send to backend which will use Claude CLI for processing
      const res = await fetch(`${API_BASE}/ai-chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMsg }),
      });
      if (res.ok) {
        const data = await res.json();
        setChatMessages((prev) => [...prev, { role: 'assistant', content: data.response }]);
        // Refresh data if AI made changes
        if (data.actions_taken) {
          fetchDocuments();
          fetchTree();
          fetchStats();
        }
      } else {
        setChatMessages((prev) => [
          ...prev,
          { role: 'assistant', content: 'エラーが発生しました。もう一度お試しください。' },
        ]);
      }
    } catch {
      setChatMessages((prev) => [
        ...prev,
        { role: 'assistant', content: '通信エラーが発生しました。' },
      ]);
    } finally {
      setChatLoading(false);
    }
  };

  // ============================================================
  // Display data
  // ============================================================

  const displayDocs = searchResults ?? documents;

  // ============================================================
  // Render
  // ============================================================

  return (
    <div className="flex h-full gap-0 -m-6 lg:-m-8">
      {/* ===== Sidebar (Tree) ===== */}
      <aside
        className={cn(
          'w-60 flex-shrink-0 border-r border-border bg-background overflow-y-auto transition-all',
          sidebarOpen ? 'block' : 'hidden lg:block'
        )}
      >
        <div className="p-3">
          {/* Search */}
          <div className="relative mb-4">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              placeholder="検索..."
              className="pl-8 h-8 text-xs"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>

          {/* Categories */}
          {treeData?.categories && treeData.categories.length > 0 && (
            <div className="mb-4">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground px-2 mb-1.5">
                カテゴリ
              </div>
              {treeData.categories.map((cat) => (
                <button
                  key={cat.id}
                  onClick={() => navigateToCategory(cat)}
                  className={cn(
                    'w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-xs transition-colors text-left',
                    currentCategoryId === cat.id
                      ? 'bg-accent text-foreground'
                      : 'text-muted-foreground hover:bg-secondary hover:text-foreground'
                  )}
                >
                  <Tag className="h-3.5 w-3.5 flex-shrink-0" />
                  <span className="truncate">{cat.name}</span>
                </button>
              ))}
            </div>
          )}

          {/* Folders */}
          {treeData?.folders && treeData.folders.length > 0 && (
            <div className="mb-4">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground px-2 mb-1.5">
                フォルダ
              </div>
              {treeData.folders.map((folder) => (
                <button
                  key={folder.id}
                  onClick={() => navigateToFolder(folder)}
                  className={cn(
                    'w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-xs transition-colors text-left',
                    currentParentId === folder.id
                      ? 'bg-accent text-foreground'
                      : 'text-muted-foreground hover:bg-secondary hover:text-foreground'
                  )}
                >
                  <FolderOpen className="h-3.5 w-3.5 flex-shrink-0 text-amber-400" />
                  <span className="truncate">{folder.title}</span>
                </button>
              ))}
            </div>
          )}

          <Separator className="my-3" />

          {/* Recent */}
          {treeData?.recent && treeData.recent.length > 0 && (
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground px-2 mb-1.5">
                最近のファイル
              </div>
              {treeData.recent.map((doc) => (
                <button
                  key={doc.id}
                  onClick={() => {
                    setSelectedDoc(doc);
                    setPreviewOpen(true);
                  }}
                  className="w-full flex items-center gap-2 px-2 py-1 rounded-md text-xs text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors text-left"
                >
                  <File className="h-3 w-3 flex-shrink-0" />
                  <span className="truncate">{doc.title}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </aside>

      {/* ===== Main Content ===== */}
      <div className="flex-1 min-w-0 overflow-y-auto">
        <div className="p-6">
          {/* KPI Cards */}
          {stats && !currentParentId && !currentCategoryId && (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
              <Card>
                <CardContent className="pt-5 pb-4">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-muted-foreground">総ファイル数</span>
                    <FileStack className="h-3.5 w-3.5 text-muted-foreground" />
                  </div>
                  <span className="text-xl font-semibold tabular-nums">{stats.total_documents}</span>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="pt-5 pb-4">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-muted-foreground">総容量</span>
                    <FileText className="h-3.5 w-3.5 text-muted-foreground" />
                  </div>
                  <span className="text-xl font-semibold tabular-nums">{formatFileSize(stats.total_size_bytes)}</span>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="pt-5 pb-4">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-muted-foreground">カテゴリ数</span>
                    <Tag className="h-3.5 w-3.5 text-muted-foreground" />
                  </div>
                  <span className="text-xl font-semibold tabular-nums">{stats.total_categories}</span>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="pt-5 pb-4">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-muted-foreground">お気に入り</span>
                    <Star className="h-3.5 w-3.5 text-muted-foreground" />
                  </div>
                  <span className="text-xl font-semibold tabular-nums">{stats.starred_count}</span>
                </CardContent>
              </Card>
            </div>
          )}

          {/* Toolbar */}
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2 min-w-0">
              {/* Breadcrumbs */}
              <nav className="flex items-center gap-1 text-sm">
                {breadcrumbs.map((bc, i) => (
                  <span key={i} className="flex items-center gap-1">
                    {i > 0 && <ChevronRight className="h-3 w-3 text-muted-foreground" />}
                    <button
                      onClick={() => navigateToBreadcrumb(i)}
                      className={cn(
                        'hover:text-foreground transition-colors truncate max-w-[150px]',
                        i === breadcrumbs.length - 1 ? 'text-foreground font-medium' : 'text-muted-foreground'
                      )}
                    >
                      {bc.title}
                    </button>
                  </span>
                ))}
              </nav>
            </div>

            <div className="flex items-center gap-2">
              {/* View toggle */}
              <Tabs value={viewMode} onValueChange={(v) => setViewMode(v as typeof viewMode)}>
                <TabsList className="h-8">
                  <TabsTrigger value="gallery" className="h-6 px-2">
                    <Grid3X3 className="h-3.5 w-3.5" />
                  </TabsTrigger>
                  <TabsTrigger value="table" className="h-6 px-2">
                    <Table2 className="h-3.5 w-3.5" />
                  </TabsTrigger>
                  <TabsTrigger value="list" className="h-6 px-2">
                    <List className="h-3.5 w-3.5" />
                  </TabsTrigger>
                </TabsList>
              </Tabs>

              <Button variant="outline" size="sm" className="h-8 gap-1.5" onClick={handleCreateFolder}>
                <FolderPlus className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">フォルダ</span>
              </Button>

              <Button
                size="sm"
                className="h-8 gap-1.5"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
              >
                <Upload className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">{uploading ? 'アップロード中...' : 'アップロード'}</span>
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                onChange={(e) => e.target.files && handleUpload(e.target.files)}
              />
            </div>
          </div>

          {/* Content */}
          {loading ? (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
              {Array.from({ length: 8 }).map((_, i) => (
                <Card key={i}>
                  <CardContent className="p-3 space-y-2">
                    <Skeleton className="h-24 w-full rounded-md" />
                    <Skeleton className="h-4 w-3/4" />
                    <Skeleton className="h-3 w-1/2" />
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : displayDocs.length === 0 ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16">
                <FolderOpen className="h-10 w-10 text-muted-foreground mb-3" />
                <p className="text-muted-foreground mb-1">ファイルがありません</p>
                <p className="text-sm text-muted-foreground">
                  アップロードするか、AIに整理を指示してください
                </p>
              </CardContent>
            </Card>
          ) : viewMode === 'gallery' ? (
            /* ===== Gallery View ===== */
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
              {displayDocs.map((doc) => {
                const currentFile = doc.document_files?.find((f) => f.is_current);
                const mime = currentFile?.mime_type;
                return (
                  <Card
                    key={doc.id}
                    className="group cursor-pointer hover:border-border/80 transition-colors overflow-hidden"
                    onClick={() => {
                      if (doc.doc_type === 'folder') {
                        navigateToFolder(doc);
                      } else {
                        setSelectedDoc(doc);
                        setPreviewOpen(true);
                      }
                    }}
                  >
                    {/* Thumbnail */}
                    <div
                      className={cn(
                        'h-28 flex items-center justify-center bg-gradient-to-br relative',
                        getMimeColor(mime)
                      )}
                    >
                      {currentFile && mime?.startsWith('image/') ? (
                        <img
                          src={`http://127.0.0.1:8000${currentFile.file_url}`}
                          alt={doc.title}
                          className="w-full h-full object-cover"
                        />
                      ) : (
                        <div className="scale-150">
                          {getFileIcon(mime, doc.doc_type)}
                        </div>
                      )}
                      {/* Star button */}
                      <button
                        className="absolute top-1.5 right-1.5 opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded-md bg-background/80 hover:bg-background"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleToggleStar(doc);
                        }}
                      >
                        {doc.is_starred ? (
                          <Star className="h-3.5 w-3.5 text-amber-400 fill-amber-400" />
                        ) : (
                          <Star className="h-3.5 w-3.5 text-muted-foreground" />
                        )}
                      </button>
                    </div>
                    {/* Info */}
                    <CardContent className="p-3">
                      <div className="flex items-start justify-between gap-1">
                        <div className="min-w-0">
                          <p className="text-xs font-medium truncate">{doc.title}</p>
                          <div className="flex items-center gap-2 mt-1 text-[10px] text-muted-foreground">
                            {currentFile && (
                              <span>{formatFileSize(currentFile.file_size)}</span>
                            )}
                            <span>{formatDate(doc.updated_at)}</span>
                          </div>
                        </div>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <button
                              className="opacity-0 group-hover:opacity-100 transition-opacity p-0.5 rounded hover:bg-secondary"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <MoreHorizontal className="h-3.5 w-3.5 text-muted-foreground" />
                            </button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="w-36">
                            <DropdownMenuItem onClick={() => handleToggleStar(doc)}>
                              {doc.is_starred ? (
                                <>
                                  <StarOff className="h-3.5 w-3.5 mr-2" /> お気に入り解除
                                </>
                              ) : (
                                <>
                                  <Star className="h-3.5 w-3.5 mr-2" /> お気に入り
                                </>
                              )}
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              className="text-destructive"
                              onClick={() => handleDelete(doc)}
                            >
                              <Trash2 className="h-3.5 w-3.5 mr-2" /> 削除
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                      {/* Tags */}
                      {doc.tags.length > 0 && (
                        <div className="flex gap-1 mt-1.5 flex-wrap">
                          {doc.tags.slice(0, 2).map((tag) => (
                            <Badge key={tag} variant="outline" className="text-[9px] px-1 py-0 h-4">
                              {tag}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          ) : viewMode === 'table' ? (
            /* ===== Table View ===== */
            <Card>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground">名前</th>
                      <th className="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground hidden sm:table-cell">タグ</th>
                      <th className="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground hidden md:table-cell">サイズ</th>
                      <th className="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground">更新日</th>
                      <th className="w-10"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {displayDocs.map((doc) => {
                      const currentFile = doc.document_files?.find((f) => f.is_current);
                      return (
                        <tr
                          key={doc.id}
                          className="border-b border-border/50 hover:bg-secondary/30 cursor-pointer transition-colors"
                          onClick={() => {
                            if (doc.doc_type === 'folder') navigateToFolder(doc);
                            else {
                              setSelectedDoc(doc);
                              setPreviewOpen(true);
                            }
                          }}
                        >
                          <td className="px-4 py-2.5">
                            <div className="flex items-center gap-2.5">
                              {getFileIcon(currentFile?.mime_type, doc.doc_type)}
                              <span className="font-medium truncate max-w-[200px]">{doc.title}</span>
                              {doc.is_starred && <Star className="h-3 w-3 text-amber-400 fill-amber-400 flex-shrink-0" />}
                            </div>
                          </td>
                          <td className="px-4 py-2.5 hidden sm:table-cell">
                            <div className="flex gap-1">
                              {doc.tags.slice(0, 3).map((tag) => (
                                <Badge key={tag} variant="outline" className="text-[10px] px-1.5 py-0">
                                  {tag}
                                </Badge>
                              ))}
                            </div>
                          </td>
                          <td className="px-4 py-2.5 text-muted-foreground text-xs hidden md:table-cell">
                            {currentFile ? formatFileSize(currentFile.file_size) : '—'}
                          </td>
                          <td className="px-4 py-2.5 text-muted-foreground text-xs">
                            {formatDate(doc.updated_at)}
                          </td>
                          <td className="px-2">
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <button
                                  className="p-1 rounded hover:bg-secondary"
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  <MoreHorizontal className="h-3.5 w-3.5 text-muted-foreground" />
                                </button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end" className="w-36">
                                <DropdownMenuItem onClick={() => handleToggleStar(doc)}>
                                  {doc.is_starred ? 'お気に入り解除' : 'お気に入り'}
                                </DropdownMenuItem>
                                <DropdownMenuItem className="text-destructive" onClick={() => handleDelete(doc)}>
                                  削除
                                </DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
          ) : (
            /* ===== List View ===== */
            <div className="space-y-1">
              {displayDocs.map((doc) => {
                const currentFile = doc.document_files?.find((f) => f.is_current);
                return (
                  <div
                    key={doc.id}
                    className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-secondary/40 cursor-pointer transition-colors"
                    onClick={() => {
                      if (doc.doc_type === 'folder') navigateToFolder(doc);
                      else {
                        setSelectedDoc(doc);
                        setPreviewOpen(true);
                      }
                    }}
                  >
                    {getFileIcon(currentFile?.mime_type, doc.doc_type)}
                    <span className="text-sm font-medium flex-1 truncate">{doc.title}</span>
                    {doc.is_starred && <Star className="h-3 w-3 text-amber-400 fill-amber-400" />}
                    <span className="text-xs text-muted-foreground">{formatDate(doc.updated_at)}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* ===== Preview Dialog ===== */}
      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
          {selectedDoc && (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  {getFileIcon(
                    selectedDoc.document_files?.find((f) => f.is_current)?.mime_type,
                    selectedDoc.doc_type
                  )}
                  {selectedDoc.title}
                </DialogTitle>
              </DialogHeader>

              <div className="space-y-4">
                {/* File preview */}
                {(() => {
                  const currentFile = selectedDoc.document_files?.find((f) => f.is_current);
                  if (!currentFile) return null;
                  const mime = currentFile.mime_type || '';

                  if (mime.startsWith('image/')) {
                    return (
                      <img
                        src={`http://127.0.0.1:8000${currentFile.file_url}`}
                        alt={selectedDoc.title}
                        className="max-w-full rounded-lg border border-border"
                      />
                    );
                  }
                  if (mime.includes('pdf')) {
                    return (
                      <iframe
                        src={`http://127.0.0.1:8000${currentFile.file_url}`}
                        className="w-full h-[500px] rounded-lg border border-border"
                      />
                    );
                  }
                  return (
                    <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                      <File className="h-12 w-12 mb-3" />
                      <p className="text-sm">プレビュー非対応</p>
                    </div>
                  );
                })()}

                {/* Metadata */}
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <span className="text-muted-foreground text-xs">更新日</span>
                    <p className="font-medium">{new Date(selectedDoc.updated_at).toLocaleString('ja-JP')}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground text-xs">作成日</span>
                    <p className="font-medium">{new Date(selectedDoc.created_at).toLocaleString('ja-JP')}</p>
                  </div>
                  {selectedDoc.document_files?.find((f) => f.is_current) && (
                    <div>
                      <span className="text-muted-foreground text-xs">サイズ</span>
                      <p className="font-medium">
                        {formatFileSize(selectedDoc.document_files.find((f) => f.is_current)!.file_size)}
                      </p>
                    </div>
                  )}
                  {selectedDoc.document_files && selectedDoc.document_files.length > 1 && (
                    <div>
                      <span className="text-muted-foreground text-xs">バージョン</span>
                      <p className="font-medium">{selectedDoc.document_files.length}個</p>
                    </div>
                  )}
                </div>

                {/* Tags */}
                {selectedDoc.tags.length > 0 && (
                  <div>
                    <span className="text-muted-foreground text-xs mb-1 block">タグ</span>
                    <div className="flex gap-1.5 flex-wrap">
                      {selectedDoc.tags.map((tag) => (
                        <Badge key={tag} variant="outline">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}

                {/* Actions */}
                <div className="flex gap-2">
                  {selectedDoc.document_files?.find((f) => f.is_current) && (
                    <Button variant="outline" size="sm" asChild>
                      <a
                        href={`http://127.0.0.1:8000${selectedDoc.document_files.find((f) => f.is_current)!.file_url}`}
                        download={selectedDoc.document_files.find((f) => f.is_current)!.original_name}
                      >
                        <Download className="h-3.5 w-3.5 mr-1.5" />
                        ダウンロード
                      </a>
                    </Button>
                  )}
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleToggleStar(selectedDoc)}
                  >
                    {selectedDoc.is_starred ? (
                      <>
                        <StarOff className="h-3.5 w-3.5 mr-1.5" />
                        お気に入り解除
                      </>
                    ) : (
                      <>
                        <Star className="h-3.5 w-3.5 mr-1.5" />
                        お気に入り
                      </>
                    )}
                  </Button>
                </div>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* ===== AI Chat Panel ===== */}
      <div
        className={cn(
          'fixed bottom-4 right-4 z-50 transition-all',
          chatOpen ? 'w-80' : 'w-auto'
        )}
      >
        {chatOpen ? (
          <Card className="shadow-xl border-border">
            <CardHeader className="pb-2 pt-3 px-4">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm flex items-center gap-1.5">
                  <Sparkles className="h-4 w-4 text-primary" />
                  AI整理アシスタント
                </CardTitle>
                <button onClick={() => setChatOpen(false)} className="p-1 rounded hover:bg-secondary">
                  <X className="h-3.5 w-3.5 text-muted-foreground" />
                </button>
              </div>
            </CardHeader>
            <CardContent className="px-4 pb-3">
              {/* Messages */}
              <div className="h-64 overflow-y-auto space-y-2 mb-3 pr-1">
                {chatMessages.length === 0 && (
                  <div className="text-xs text-muted-foreground text-center py-8">
                    <p>ファイルの整理方法を指示できます</p>
                    <p className="mt-1.5">例: 「AMEX明細を月別に整理して」</p>
                  </div>
                )}
                {chatMessages.map((msg, i) => (
                  <div
                    key={i}
                    className={cn(
                      'text-xs rounded-lg px-3 py-2 max-w-[90%]',
                      msg.role === 'user'
                        ? 'bg-primary text-primary-foreground ml-auto'
                        : 'bg-secondary text-foreground'
                    )}
                  >
                    {msg.content}
                  </div>
                ))}
                {chatLoading && (
                  <div className="bg-secondary rounded-lg px-3 py-2 max-w-[90%]">
                    <div className="flex gap-1">
                      <div className="h-1.5 w-1.5 rounded-full bg-muted-foreground animate-bounce" />
                      <div className="h-1.5 w-1.5 rounded-full bg-muted-foreground animate-bounce delay-100" />
                      <div className="h-1.5 w-1.5 rounded-full bg-muted-foreground animate-bounce delay-200" />
                    </div>
                  </div>
                )}
              </div>
              {/* Input */}
              <div className="flex gap-1.5">
                <Input
                  placeholder="整理の指示を入力..."
                  className="h-8 text-xs"
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && sendChatMessage()}
                  disabled={chatLoading}
                />
                <Button size="sm" className="h-8 w-8 p-0" onClick={sendChatMessage} disabled={chatLoading}>
                  <Send className="h-3.5 w-3.5" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ) : (
          <Button
            size="sm"
            className="h-10 w-10 rounded-full shadow-lg p-0"
            onClick={() => setChatOpen(true)}
          >
            <Sparkles className="h-4 w-4" />
          </Button>
        )}
      </div>
    </div>
  );
}
