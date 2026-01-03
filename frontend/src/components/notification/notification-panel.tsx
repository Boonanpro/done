'use client';

import { useState, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Bell,
  ChevronDown,
  ChevronUp,
  FileText,
  Mail,
  Zap,
  X,
  Check,
  Edit,
  Loader2,
  Send,
} from 'lucide-react';
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

export function NotificationPanel() {
  const queryClient = useQueryClient();
  const [isExpanded, setIsExpanded] = useState(false);
  const [selectedProposal, setSelectedProposal] = useState<ProposalResponse | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [editedContent, setEditedContent] = useState('');
  const [question, setQuestion] = useState('');
  const questionInputRef = useRef<HTMLInputElement>(null);

  // Fetch proposals from API
  const { data: proposalsData, isLoading } = useQuery({
    queryKey: ['proposals', 'pending'],
    queryFn: () => api.proposals.list({ status: 'pending', limit: 20 }),
    refetchInterval: 30000, // Refetch every 30 seconds
  });

  const proposals = proposalsData?.proposals || [];
  const pendingCount = proposalsData?.pending_count || proposals.length;

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

  // Send question about proposal (sends to Dan)
  const askQuestionMutation = useMutation({
    mutationFn: async (content: string) => {
      // Send message to Dan about this proposal
      const questionContent = selectedProposal
        ? `【${selectedProposal.title}について質問】\n${content}`
        : content;
      return api.dan.sendMessage(questionContent);
    },
    onSuccess: () => {
      setQuestion('');
      toast.success('質問を送信しました');
    },
    onError: () => {
      toast.error('質問の送信に失敗しました');
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
    askQuestionMutation.mutate(question.trim());
  };

  const handleProposalClick = (proposal: ProposalResponse) => {
    setSelectedProposal(proposal);
    setEditMode(false);
    setEditedContent('');
  };

  const handleDismiss = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    // Reject the proposal to dismiss it
    respondMutation.mutate({ proposalId: id, action: 'reject' });
  };

  return (
    <motion.div
      initial={false}
      className="absolute bottom-4 right-4 z-50"
    >
      <AnimatePresence mode="wait">
        {selectedProposal ? (
          <motion.div
            key="detail"
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            className="w-96 bg-card border border-border rounded-xl shadow-2xl overflow-hidden"
          >
            {/* Detail Header */}
            <div className="flex items-center justify-between p-3 border-b border-border bg-muted/30">
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
            <div className="p-4 space-y-4">
              {editMode ? (
                <textarea
                  value={editedContent}
                  onChange={(e) => setEditedContent(e.target.value)}
                  className="w-full h-24 p-2 text-sm bg-input border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-ring resize-none"
                  placeholder="内容を編集..."
                />
              ) : (
                <p className="text-sm text-muted-foreground">
                  {selectedProposal.content || selectedProposal.title}
                </p>
              )}

              {/* Type indicator */}
              <div className="text-xs text-muted-foreground/70">
                <p>タイプ: {selectedProposal.type}</p>
              </div>

              {/* Actions */}
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

              {/* Mini Chat */}
              <div className="pt-3 border-t border-border">
                <p className="text-xs text-muted-foreground mb-2">
                  この件についてダンに質問できます
                </p>
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
                    placeholder="質問を入力..."
                    className="flex-1 h-8 px-3 text-sm bg-input border border-border rounded-lg focus:outline-none focus:ring-1 focus:ring-ring"
                    disabled={askQuestionMutation.isPending}
                  />
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={handleAskQuestion}
                    disabled={!question.trim() || askQuestionMutation.isPending}
                  >
                    {askQuestionMutation.isPending ? (
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
              'w-72 bg-card border border-border rounded-xl shadow-2xl overflow-hidden transition-all',
              !isExpanded && 'w-auto'
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
                  <ScrollArea className="max-h-80">
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
                                  {proposal.content || proposal.type}
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
                    </div>
                  </ScrollArea>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
