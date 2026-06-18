'use client';

import { useState, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Bell, ChevronDown, ChevronUp, FileText, Mail, Zap, X, Check, Edit, Loader2, Send } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { api, type ProposalResponse } from '@/lib/api-client';

const iconMap = {
  invoice: FileText,
  mail: Mail,
  task: Zap,
  reply: Mail,
  payment: FileText,
  booking: Zap,
};

type ProposalIconType = keyof typeof iconMap;

function getProposalIconType(proposal: ProposalResponse): ProposalIconType {
  const type = proposal.type?.toLowerCase() || '';
  if (type.includes('payment')) return 'invoice';
  if (type.includes('reply')) return 'mail';
  if (type.includes('schedule') || type.includes('reminder')) return 'task';
  return 'task';
}

interface NotificationPanelProps {
  inline?: boolean;
}

export function NotificationPanel({ inline = false }: NotificationPanelProps) {
  const queryClient = useQueryClient();
  const [isExpanded, setIsExpanded] = useState(false);
  const [selectedProposal, setSelectedProposal] = useState<ProposalResponse | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [editedContent, setEditedContent] = useState('');
  const [question, setQuestion] = useState('');
  const [instructReply, setInstructReply] = useState('');
  const [showOriginal, setShowOriginal] = useState(false);
  const questionInputRef = useRef<HTMLInputElement>(null);

  // 要対応の提案（フォーム/メール返信など）。情報通知(observation)は除外してバッジもこちらで数える
  const { data: proposalsData, isLoading } = useQuery({
    queryKey: ['proposals', 'pending', 'actionable'],
    queryFn: () => api.proposals.list({ status: 'pending', limit: 20, excludeTypes: 'observation' }),
    refetchInterval: 30000, // Refetch every 30 seconds
  });

  // 情報通知(observation)。要対応とは分けて、控えめに別枠表示する
  const { data: infoData } = useQuery({
    queryKey: ['proposals', 'pending', 'observation'],
    queryFn: () => api.proposals.list({ status: 'pending', limit: 20, types: 'observation' }),
    refetchInterval: 60000,
    enabled: isExpanded,
  });

  const proposals = proposalsData?.proposals || [];
  const pendingCount = proposalsData?.pending_count || proposals.length;
  const infoProposals = infoData?.proposals || [];

  // Respond to proposal mutation
  const respondMutation = useMutation({
    mutationFn: ({
      proposalId,
      action,
      editedContent,
    }: {
      proposalId: string;
      action: 'approve' | 'reject' | 'edit';
      editedContent?: string;
    }) => api.proposals.respond(proposalId, action, editedContent),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['proposals'] });
      setSelectedProposal(null);
      setEditMode(false);
      setEditedContent('');
      
      const actionText = variables.action === 'approve' ? '承認' : variables.action === 'edit' ? '編集して承認' : '却下';
      toast.success(`提案を${actionText}しました`);
    },
    onError: () => {
      toast.error('処理に失敗しました');
    },
  });

  // Instruct Dan about this proposal (rewrite draft / delegate task / answer)
  const instructMutation = useMutation({
    mutationFn: async (instruction: string) => {
      if (!selectedProposal) throw new Error('no proposal');
      return api.proposals.instruct(selectedProposal.id, instruction);
    },
    onSuccess: (res) => {
      setQuestion('');
      if (res.mode === 'revise' && res.proposal) {
        // 草案がその場で更新される
        setSelectedProposal(res.proposal);
        setEditMode(false);
        setEditedContent('');
        queryClient.invalidateQueries({ queryKey: ['proposals'] });
      }
      setInstructReply(res.message || '');
      toast.success(
        res.mode === 'revise' ? '返信案を書き換えました' :
        res.mode === 'delegate' ? 'ダンに依頼しました' : '回答しました'
      );
    },
    onError: () => {
      toast.error('指示の処理に失敗しました');
    },
  });

  const handleApprove = () => {
    if (!selectedProposal) return;
    respondMutation.mutate({ proposalId: selectedProposal.id, action: 'approve' });
  };

  const handleEdit = () => {
    if (!selectedProposal) return;
    if (editMode) {
      // Submit edit
      respondMutation.mutate({
        proposalId: selectedProposal.id,
        action: 'edit',
        editedContent: editedContent,
      });
    } else {
      // Enter edit mode
      setEditMode(true);
      setEditedContent(selectedProposal.content || '');
    }
  };

  const handleAskQuestion = () => {
    if (!question.trim()) return;
    instructMutation.mutate(question.trim());
  };

  const handleProposalClick = (proposal: ProposalResponse) => {
    setSelectedProposal(proposal);
    setEditMode(false);
    setEditedContent('');
    setInstructReply('');
    setShowOriginal(false);
  };

  const handleDismiss = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    // Reject the proposal to dismiss it
    respondMutation.mutate({ proposalId: id, action: 'reject' });
  };

  return (
    <motion.div
      initial={false}
      className={inline ? "relative" : "absolute z-50 md:top-4 md:right-4 top-4 right-4"}
    >
      <AnimatePresence mode="wait">
        {selectedProposal ? (
          <motion.div
            key="detail"
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            className={cn("bg-card border border-border rounded-xl shadow-2xl max-h-[80vh] flex flex-col", inline ? "w-full" : "w-96")}
            style={{ borderRadius: '0.75rem' }}
          >
            {/* Detail Header */}
            <div className="flex items-center justify-between p-3 border-b border-border bg-muted/30 shrink-0 rounded-t-xl">
              <div className="flex items-center gap-2 min-w-0 flex-1">
                {(() => {
                  const Icon = iconMap[getProposalIconType(selectedProposal)];
                  return <Icon className="h-4 w-4 text-muted-foreground shrink-0" />;
                })()}
                <span className="text-sm font-medium truncate">{selectedProposal.title}</span>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 shrink-0"
                onClick={() => {
                  setSelectedProposal(null);
                  setEditMode(false);
                  setEditedContent('');
                }}
              >
                <X className="h-3 w-3" />
              </Button>
            </div>

            {/* Detail Content */}
            <div className="p-4 space-y-4 overflow-y-auto" style={{ maxHeight: 'calc(80vh - 52px)' }}>
              {/* 自然文の経緯（誰から何の件か） */}
              {(() => {
                const summary = (selectedProposal.action_data as { summary?: string } | null)?.summary;
                if (!summary) return null;
                const isReply = selectedProposal.type === 'reply';
                return (
                  <div className="text-sm bg-muted/40 border border-border rounded-lg p-3 space-y-1">
                    <p className="whitespace-pre-wrap break-words">{summary}</p>
                    {isReply && (
                      <p className="text-xs text-muted-foreground">以下の内容で返信しますか？</p>
                    )}
                  </div>
                );
              })()}

              {/* 元のメールを開閉表示 */}
              {(() => {
                const original = (selectedProposal.action_data as { original_body?: string } | null)?.original_body;
                if (!original) return null;
                return (
                  <div>
                    <button
                      onClick={() => setShowOriginal((v) => !v)}
                      className="text-xs text-muted-foreground hover:text-foreground underline underline-offset-2"
                    >
                      {showOriginal ? '元のメールを隠す' : '元のメールを見る'}
                    </button>
                    {showOriginal && (
                      <pre className="mt-2 text-xs text-muted-foreground whitespace-pre-wrap break-words bg-muted/30 border border-border rounded-lg p-2 max-h-60 overflow-y-auto font-sans">
                        {original}
                      </pre>
                    )}
                  </div>
                );
              })()}

              {editMode ? (
                <textarea
                  value={editedContent}
                  onChange={(e) => setEditedContent(e.target.value)}
                  className="w-full h-24 p-2 text-sm bg-input border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-ring resize-none"
                  placeholder="内容を編集..."
                />
              ) : (
                <p className="text-sm text-muted-foreground whitespace-pre-wrap break-words">
                  {selectedProposal.content || selectedProposal.title}
                </p>
              )}

              {/* Type indicator */}
              <div className="text-xs text-muted-foreground/70">
                <p>タイプ: {selectedProposal.type}</p>
              </div>

              {/* Actions */}
              {(['observation', 'notify'].includes(selectedProposal.type as string)) ? (
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    className="flex-1 gap-1"
                    onClick={handleApprove}
                    disabled={respondMutation.isPending}
                  >
                    {respondMutation.isPending ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Check className="h-3 w-3" />
                    )}
                    確認済み
                  </Button>
                </div>
              ) : (
                <>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      className="flex-1 gap-1"
                      onClick={handleApprove}
                      disabled={respondMutation.isPending || editMode}
                    >
                      {respondMutation.isPending && respondMutation.variables?.action === 'approve' ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Check className="h-3 w-3" />
                      )}
                      承認
                    </Button>
                    <Button
                      size="sm"
                      variant={editMode ? 'default' : 'outline'}
                      className="flex-1 gap-1"
                      onClick={handleEdit}
                      disabled={respondMutation.isPending && respondMutation.variables?.action !== 'edit'}
                    >
                      {respondMutation.isPending && respondMutation.variables?.action === 'edit' ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Edit className="h-3 w-3" />
                      )}
                      {editMode ? '保存' : '編集'}
                    </Button>
                  </div>

                  {editMode && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="w-full"
                      onClick={() => {
                        setEditMode(false);
                        setEditedContent('');
                      }}
                    >
                      キャンセル
                    </Button>
                  )}
                </>
              )}

              {/* ダンに指示（書き換え・依頼・質問） */}
              <div className="pt-3 border-t border-border">
                {instructReply && (
                  <p className="text-xs text-foreground bg-muted/40 border border-border rounded-lg p-2 mb-2 whitespace-pre-wrap break-words">
                    {instructReply}
                  </p>
                )}
                <div className="flex gap-2">
                  <input
                    ref={questionInputRef}
                    type="text"
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        handleAskQuestion();
                      }
                    }}
                    placeholder="質問・指示"
                    className="flex-1 h-8 px-3 text-sm bg-input border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-ring"
                    disabled={instructMutation.isPending}
                  />
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={handleAskQuestion}
                    disabled={!question.trim() || instructMutation.isPending}
                  >
                    {instructMutation.isPending ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Send className="h-3 w-3" />
                    )}
                  </Button>
                </div>
              </div>
            </div>
          </motion.div>
        ) : (
          <motion.div
            key="list"
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            className={cn(
              'bg-card border border-border rounded-xl overflow-hidden transition-all',
              inline ? 'w-full shadow-none' : 'w-72 shadow-2xl',
              !isExpanded && !inline && 'w-auto'
            )}
          >
            {/* Header */}
            <button
              onClick={() => setIsExpanded(!isExpanded)}
              className="w-full flex items-center justify-between p-3 hover:bg-muted/30 transition-colors"
            >
              <div className="flex items-center gap-2">
                <Bell className="h-4 w-4 text-muted-foreground" />
                <span className="text-sm font-medium">通知</span>
                {pendingCount > 0 && (
                  <Badge variant="default" className="h-5 px-1.5 text-xs">
                    {pendingCount}
                  </Badge>
                )}
              </div>
              {isExpanded ? (
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              ) : (
                <ChevronUp className="h-4 w-4 text-muted-foreground" />
              )}
            </button>

            {/* Notifications List */}
            <AnimatePresence>
              {isExpanded && (
                <motion.div
                  initial={{ height: 0 }}
                  animate={{ height: 'auto' }}
                  exit={{ height: 0 }}
                  className="overflow-hidden"
                >
                  <div className="max-h-80 overflow-y-auto">
                    <div className="p-2 space-y-1">
                      {isLoading ? (
                        // Loading state
                        Array.from({ length: 3 }).map((_, i) => (
                          <div key={i} className="flex items-start gap-3 p-2 animate-pulse">
                            <div className="w-8 h-8 rounded-lg bg-muted" />
                            <div className="flex-1 space-y-2">
                              <div className="h-4 w-24 bg-muted rounded" />
                              <div className="h-3 w-32 bg-muted rounded" />
                            </div>
                          </div>
                        ))
                      ) : proposals.length === 0 ? (
                        <p className="text-sm text-muted-foreground text-center py-4">
                          通知はありません
                        </p>
                      ) : (
                        proposals.map((proposal) => {
                          const Icon = iconMap[getProposalIconType(proposal)];
                          return (
                            <motion.div
                              key={proposal.id}
                              initial={{ opacity: 0, x: -10 }}
                              animate={{ opacity: 1, x: 0 }}
                              className={cn(
                                'group flex items-start gap-3 p-2 rounded-lg cursor-pointer hover:bg-muted/50 transition-colors',
                                proposal.status === 'pending' && 'bg-primary/5'
                              )}
                              onClick={() => handleProposalClick(proposal)}
                            >
                              <div className="shrink-0 w-8 h-8 rounded-lg bg-muted flex items-center justify-center">
                                <Icon className="h-4 w-4 text-muted-foreground" />
                              </div>
                              <div className="flex-1 min-w-0">
                                <p className="text-sm font-medium truncate">
                                  {proposal.title}
                                </p>
                                <p className="text-xs text-muted-foreground truncate">
                                  {(() => {
                                    const summary = (proposal.action_data as { summary?: string } | null)?.summary;
                                    return summary || proposal.content || proposal.type;
                                  })()}
                                </p>
                                <p className="text-xs text-muted-foreground/70 mt-0.5">
                                  {proposal.created_at
                                    ? new Date(proposal.created_at).toLocaleString('ja-JP', {
                                        month: 'short',
                                        day: 'numeric',
                                        hour: '2-digit',
                                        minute: '2-digit',
                                      })
                                    : ''}
                                </p>
                              </div>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity"
                                onClick={(e) => handleDismiss(proposal.id, e)}
                                disabled={respondMutation.isPending}
                              >
                                <X className="h-3 w-3" />
                              </Button>
                            </motion.div>
                          );
                        })
                      )}

                      {/* 情報通知(observation)。要対応とは分けて控えめに表示 */}
                      {infoProposals.length > 0 && (
                        <div className="pt-2 mt-1 border-t border-border/60">
                          <p className="px-2 py-1 text-[10px] uppercase tracking-wide text-muted-foreground/60">
                            情報 ({infoProposals.length})
                          </p>
                          {infoProposals.map((proposal) => (
                            <div
                              key={proposal.id}
                              className="group flex items-start gap-3 p-2 rounded-lg cursor-pointer hover:bg-muted/40 transition-colors opacity-70"
                              onClick={() => handleProposalClick(proposal)}
                            >
                              <div className="shrink-0 w-7 h-7 rounded-lg bg-muted/60 flex items-center justify-center">
                                <Bell className="h-3.5 w-3.5 text-muted-foreground" />
                              </div>
                              <div className="flex-1 min-w-0">
                                <p className="text-xs font-medium truncate">{proposal.title}</p>
                                <p className="text-[11px] text-muted-foreground truncate">
                                  {proposal.content || proposal.type}
                                </p>
                              </div>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity"
                                onClick={(e) => handleDismiss(proposal.id, e)}
                                disabled={respondMutation.isPending}
                              >
                                <X className="h-3 w-3" />
                              </Button>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
