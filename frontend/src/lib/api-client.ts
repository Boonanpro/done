/**
 * API Client for Done Backend
 * Handles all HTTP requests to the backend API
 */

import { useAuthStore } from '@/stores/auth-store';

// API Base URL - use environment variable or empty string (relative URL via Next.js rewrites proxy)
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? '';

// SSE streaming - use relative URL so requests go through Next.js proxy (works from any device)
const SSE_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '';

// ==================== Types ====================

export interface UserResponse {
  id: string;
  email: string;
  display_name: string;
  avatar_url: string | null;
  created_at: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface RegisterRequest {
  email: string;
  password: string;
  display_name: string;
}

export interface TokenResponse {
  access_token: string;
}

export interface MessageResponse {
  id: string;
  room_id: string;
  sender_id: string;
  sender_name: string;
  sender_type: 'human' | 'ai';
  content: string;
  created_at: string;
  ai_context?: {
    reasoning_steps?: string[];
    reasoning_full?: string[];
  };
}

export interface MessagesListResponse {
  messages: MessageResponse[];
}

export interface ProcessStep {
  id: string;
  label: string;
  status: 'pending' | 'running' | 'completed' | 'error';
}

export interface DanMessageResponse {
  user_message: MessageResponse;
  ai_message: MessageResponse;
  process_steps: ProcessStep[];
}

export interface DanRoomResponse {
  id: string;
  user_id: string;
  unread_count: number;
  pending_proposals_count: number;
  created_at: string;
  updated_at: string;
}

export interface FriendResponse {
  id: string;
  user_id: string;
  friend_id: string;
  display_name: string;
  avatar_url: string | null;
  created_at: string;
}

export interface FriendsListResponse {
  friends: FriendResponse[];
}

export interface RoomResponse {
  id: string;
  name: string;
  type: 'dm' | 'group' | 'dan';
  last_message?: string;
  last_message_at?: string;
  unread_count: number;
  created_at: string;
}

export interface RoomsListResponse {
  rooms: RoomResponse[];
}

// Session types
export interface SessionResponse {
  id: string;
  title: string;
  last_message?: string;
  last_message_at?: string;
  message_count: number;
  created_at: string;
}

export interface SessionsListResponse {
  sessions: SessionResponse[];
  current_session_id: string | null;
}

export interface SessionCreateResponse {
  id: string;
  title: string;
  created_at: string;
}

export interface SessionActivateResponse {
  success: boolean;
  session_id: string;
}

export interface SessionSwitchResponse {
  success: boolean;
  session_id: string;
  room: DanRoomResponse;
  messages: MessagesListResponse;
}

// Proposal types
export type ProposalStatus = 'pending' | 'approved' | 'rejected' | 'expired';
export type ProposalType = 'reply' | 'action' | 'schedule' | 'reminder';

export interface ProposalResponse {
  id: string;
  user_id: string;
  type: ProposalType;
  status: ProposalStatus;
  title: string;
  content: string;
  source_room_id?: string | null;
  source_message_id?: string | null;
  action_data?: Record<string, unknown> | null;
  expires_at?: string | null;
  responded_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProposalsListResponse {
  proposals: ProposalResponse[];
  total_count: number;
  pending_count: number;
}

// AI Settings types
export type AIMode = 'off' | 'assist' | 'auto';

export interface AISettingsResponse {
  room_id: string;
  enabled: boolean;
  mode: AIMode;
  personality?: string | null;
  auto_reply_delay_ms: number;
}

export interface AISettingsUpdateRequest {
  enabled?: boolean | null;
  mode?: AIMode | null;
  personality?: string | null;
  auto_reply_delay_ms?: number | null;
}

// StateMachine types
export type StateMachineState = 
  | 'intake'
  | 'plan'
  | 'research'
  | 'propose'
  | 'confirm'
  | 'execute'
  | 'verify'
  | 'report'
  | 'chat'
  | 'error';

export interface StateMachineProposal {
  recommendation: {
    id?: string;
    title: string;
    price?: number;
    details?: Record<string, unknown>;
  };
  recommendation_reason: string;
  alternatives?: Array<{
    title: string;
    reason?: string;
    note?: string;
  }>;
  risks?: string[];
  next_action?: string;
  reasoning_steps?: string[];
}

export interface StateMachineResponse {
  session_id: string;
  state: StateMachineState;
  response: string;
  reasoning_steps: string[];
  needs_confirmation: boolean;
  is_chat: boolean;
  proposal: StateMachineProposal | null;
  error: string | null;
}

export interface StateMachineMessageRequest {
  message: string;
  session_id?: string;
  user_id?: string;
}

export interface StateMachineConfirmRequest {
  action: 'confirm' | 'revise';
  revision?: string;
  user_id?: string;
}

export interface StateMachineReviseRequest {
  revision: string;
  user_id?: string;
}

// Task types
export type TaskStatus =
  | 'pending'
  | 'analyzing'
  | 'proposed'
  | 'confirmed'
  | 'executing'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type TaskType =
  | 'email'
  | 'line'
  | 'purchase'
  | 'payment'
  | 'research'
  | 'travel'
  | 'phone'
  | 'other';

export type ExecutionStatus =
  | 'pending'
  | 'executing'
  | 'awaiting_credentials'
  | 'completed'
  | 'failed';

export interface TaskResponse {
  id: string;
  user_id: string | null;
  type: TaskType;
  status: TaskStatus;
  original_wish: string;
  proposed_actions: string[];
  execution_result?: Record<string, unknown> | null;
  created_at: string;
  updated_at?: string | null;
}

export interface TasksListResponse {
  tasks: TaskResponse[];
}

export interface ExecutionProgress {
  current_step?: string | null;
  steps_completed?: string[];
  steps_remaining?: string[];
  screenshot_url?: string | null;
}

export interface ExecutionStatusResponse {
  task_id: string;
  status: ExecutionStatus;
  progress?: ExecutionProgress | null;
  required_service?: string | null;
  execution_result?: Record<string, unknown> | null;
  error_message?: string | null;
}

// Project types
export type ProjectStatusType =
  | 'planning'
  | 'proposed'
  | 'approved'
  | 'in_progress'
  | 'completed'
  | 'paused'
  | 'cancelled';

export interface ProjectResponse {
  id: string;
  user_id: string;
  title: string;
  description: string | null;
  status: ProjectStatusType;
  room_id: string | null;
  origin_room_id: string | null;
  summary: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string | null;
}

export interface ProjectListResponse {
  projects: ProjectResponse[];
}

export interface ProjectProposalResponse {
  id: string;
  project_id: string;
  content: string;
  proposal_type: string;
  status: 'pending' | 'approved' | 'rejected' | 'superseded';
  steps: Record<string, unknown>[] | null;
  metadata: Record<string, unknown> | null;
  approved_at: string | null;
  created_at: string;
}

export interface ExecutionEvent {
  id: string;
  project_id: string;
  room_id: string;
  event_type: 'tool_use' | 'reasoning' | 'phase' | 'error';
  tool_name: string | null;
  tool_label: string | null;
  content: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

// Note types
export interface NoteDraftResponse {
  id: string;
  title: string;
  content: string;
  tags: string[];
  status: string;
  created_at: string;
}

export interface NotePolishedResponse {
  draft_id: string;
  title: string;
  tags: string[];
  full_text: string;
  hook: string | null;
  summary: string | null;
  polished_at: string;
  status: string;
}

export interface NotePostResponse {
  draft_id: string;
  note_url: string;
  title: string;
  published: boolean;
  posted_at: string;
  status: string;
}

export interface NoteScheduleResponse {
  id: string;
  draft_id: string;
  scheduled_at: string;
  status: string;
  article_type: string;
  price: number | null;
  error_message: string | null;
  published_url: string | null;
  draft_title: string | null;
  created_at: string;
  updated_at: string;
}

export interface NoteStatsResponse {
  total_drafts: number;
  total_posts: number;
  published: number;
  draft_on_note: number;
  pending_drafts: number;
  polished_drafts: number;
  scheduled: number;
}

// File upload types
export interface FileUploadResponse {
  id: string;
  filename: string;
  url: string;
  content_type: string;
  size: number;
  created_at: string;
}

// ==================== API Error Class ====================

export class ApiError extends Error {
  status: number;
  statusText: string;
  data: unknown;

  constructor(status: number, statusText: string, data: unknown) {
    super(`API Error: ${status} ${statusText}`);
    this.name = 'ApiError';
    this.status = status;
    this.statusText = statusText;
    this.data = data;
  }
}

// ==================== Token Management ====================

// Simple token storage key
const TOKEN_KEY = 'done-token';

// Get token from localStorage
function getStoredToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

// File upload function
async function uploadFile(
  endpoint: string,
  file: File
): Promise<FileUploadResponse> {
  const url = `${API_BASE_URL}/api/v1${endpoint}`;
  const token = immediateToken || getStoredToken();

  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: formData,
  });

  if (!response.ok) {
    throw new ApiError(response.status, response.statusText, null);
  }

  return response.json();
}

// Set token in localStorage
export function setStoredToken(token: string | null) {
  if (typeof window === 'undefined') return;
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
}

// ==================== HTTP Client ====================

// Temporary token storage for immediate use after login
let immediateToken: string | null = null;

export function setImmediateToken(token: string | null) {
  immediateToken = token;
}

async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL}/api/v1${endpoint}`;

  // Use immediate token if available, otherwise get from localStorage
  const token = immediateToken || getStoredToken();

  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers,
  };

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    // 401 Unauthorized: セッション切れ → ログインページにリダイレクト
    if (response.status === 401) {
      // トークンをクリア
      setStoredToken(null);
      immediateToken = null;
      // auth-storeをクリア
      try {
        useAuthStore.getState().logout();
      } catch {
        // store未初期化時は無視
      }
      // ログインページにリダイレクト（ブラウザ環境のみ）
      if (typeof window !== 'undefined') {
        window.location.href = '/login';
        // リダイレクト中はエラーをスローしない
        return new Promise(() => {});
      }
    }

    let data: unknown;
    try {
      data = await response.json();
    } catch {
      data = { message: 'Unknown error' };
    }
    throw new ApiError(response.status, response.statusText, data);
  }

  // Handle empty responses
  const contentType = response.headers.get('content-type');
  if (!contentType || !contentType.includes('application/json')) {
    return {} as T;
  }

  return response.json();
}

// ==================== API Methods ====================

export const api = {
  // Auth endpoints
  auth: {
    login: (data: LoginRequest) =>
      request<TokenResponse>('/chat/login', {
        method: 'POST',
        body: JSON.stringify(data),
      }),

    register: (data: RegisterRequest) =>
      request<UserResponse>('/chat/register', {
        method: 'POST',
        body: JSON.stringify(data),
      }),

    logout: () =>
      request<void>('/chat/logout', {
        method: 'POST',
      }),

    refresh: () =>
      request<TokenResponse>('/chat/refresh', {
        method: 'POST',
      }),

    me: () => request<UserResponse>('/chat/me'),

    updateMe: (data: Partial<UserResponse>) =>
      request<UserResponse>('/chat/me', {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
  },

  // Dan (AI Assistant) endpoints
  dan: {
    getRoom: () => request<DanRoomResponse>('/chat/dan'),

    getMessages: (params?: { limit?: number; before?: string }) => {
      const query = new URLSearchParams();
      if (params?.limit) query.set('limit', params.limit.toString());
      if (params?.before) query.set('before', params.before);
      const queryString = query.toString();
      return request<MessagesListResponse>(
        `/chat/dan/messages${queryString ? `?${queryString}` : ''}`
      );
    },

    sendMessage: (content: string) =>
      request<DanMessageResponse>('/chat/dan/messages', {
        method: 'POST',
        body: JSON.stringify({ content }),
      }),

    // SSEストリーミング版メッセージ送信
    sendMessageStream: async (
      content: string,
      onProcess: (step: ProcessStep) => void,
      onUserMessage: (message: MessageResponse) => void,
      onAiMessage: (message: MessageResponse) => void,
      onError: (error: string) => void,
      onDone: () => void
    ) => {
      const token = typeof window !== 'undefined' ? localStorage.getItem('done-token') : null;
      
      const response = await fetch(`${SSE_BASE_URL}/api/v1/chat/dan/messages/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        credentials: 'include',
        body: JSON.stringify({ content }),
      });

      if (!response.ok) {
        throw new ApiError(response.status, response.statusText, null);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error('No reader available');
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              switch (data.type) {
                case 'process':
                  onProcess(data.step);
                  break;
                case 'user_message':
                  onUserMessage(data.message);
                  break;
                case 'ai_message':
                  onAiMessage(data.message);
                  break;
                case 'error':
                  onError(data.message);
                  break;
                case 'done':
                  onDone();
                  break;
              }
            } catch {
              // Skip malformed JSON
            }
          }
        }
      }
    },

    markAsRead: () =>
      request<{ success: boolean; read_at: string }>('/chat/dan/read', {
        method: 'POST',
      }),

    // Sessions
    getSessions: () => request<SessionsListResponse>('/chat/dan/sessions'),

    createSession: () =>
      request<SessionCreateResponse>('/chat/dan/sessions', {
        method: 'POST',
      }),

    activateSession: (sessionId: string) =>
      request<SessionActivateResponse>(
        `/chat/dan/sessions/${sessionId}/activate`,
        {
          method: 'POST',
        }
      ),

    // Optimized session switch - returns room and messages in one call
    switchSession: (sessionId: string, limit: number = 50) =>
      request<SessionSwitchResponse>(
        `/chat/dan/sessions/${sessionId}/switch?limit=${limit}`,
        {
          method: 'POST',
        }
      ),

    // Delete session
    deleteSession: (sessionId: string) =>
      request<{ message: string; new_active_session_id: string | null }>(
        `/chat/dan/sessions/${sessionId}`,
        {
          method: 'DELETE',
        }
      ),
  },

  // Friends endpoints
  friends: {
    list: () => request<FriendsListResponse>('/chat/friends'),

    delete: (friendId: string) =>
      request<void>(`/chat/friends/${friendId}`, {
        method: 'DELETE',
      }),
  },

  // Rooms endpoints
  rooms: {
    list: () => request<RoomsListResponse>('/chat/rooms'),

    get: (roomId: string) => request<RoomResponse>(`/chat/rooms/${roomId}`),

    getMessages: (
      roomId: string,
      params?: { limit?: number; before?: string }
    ) => {
      const query = new URLSearchParams();
      if (params?.limit) query.set('limit', params.limit.toString());
      if (params?.before) query.set('before', params.before);
      const queryString = query.toString();
      return request<MessagesListResponse>(
        `/chat/rooms/${roomId}/messages${queryString ? `?${queryString}` : ''}`
      );
    },

    sendMessage: (roomId: string, content: string) =>
      request<MessageResponse>(`/chat/rooms/${roomId}/messages`, {
        method: 'POST',
        body: JSON.stringify({ content }),
      }),

    markAsRead: (roomId: string) =>
      request<{ success: boolean; read_at: string }>(
        `/chat/rooms/${roomId}/read`,
        {
          method: 'POST',
        }
      ),

    // AI Settings
    getAiSettings: (roomId: string) =>
      request<AISettingsResponse>(`/chat/rooms/${roomId}/ai`),

    updateAiSettings: (roomId: string, data: AISettingsUpdateRequest) =>
      request<AISettingsResponse>(`/chat/rooms/${roomId}/ai`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
  },

  // Invite endpoints (also available as 'invites' for compatibility)
  invite: {
    create: (params?: { max_uses?: number; expires_in_hours?: number }) =>
      request<{
        id: string;
        code: string;
        invite_url: string;
        max_uses: number;
        use_count: number;
        expires_at: string | null;
        created_at: string;
      }>('/chat/invite', {
        method: 'POST',
        body: JSON.stringify(params || {}),
      }),

    get: (code: string) =>
      request<{
        code: string;
        creator_name: string;
        creator_avatar_url: string | null;
        expires_at: string | null;
        is_valid: boolean;
      }>(`/chat/invite/${code}`),

    accept: (code: string) =>
      request<{
        success: boolean;
        friend_id: string;
        message: string;
      }>(`/chat/invite/${code}/accept`, {
        method: 'POST',
      }),
  },

  // Proposals endpoints
  proposals: {
    list: (params?: { status?: ProposalStatus; limit?: number }) => {
      const query = new URLSearchParams();
      if (params?.status) query.set('status', params.status);
      if (params?.limit) query.set('limit', params.limit.toString());
      const queryString = query.toString();
      return request<ProposalsListResponse>(
        `/chat/proposals${queryString ? `?${queryString}` : ''}`
      );
    },

    get: (proposalId: string) =>
      request<ProposalResponse>(`/chat/proposals/${proposalId}`),

    respond: (
      proposalId: string,
      action: 'approve' | 'reject' | 'edit',
      editedContent?: string
    ) =>
      request<ProposalResponse>(`/chat/proposals/${proposalId}/respond`, {
        method: 'POST',
        body: JSON.stringify({
          action,
          edited_content: editedContent,
        }),
      }),
  },

  // User endpoints
  user: {
    update: (data: { display_name?: string; avatar_url?: string }) =>
      request<UserResponse>('/chat/me', {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
  },

  // Task endpoints
  tasks: {
    list: (params?: { user_id?: string; limit?: number }) => {
      const query = new URLSearchParams();
      if (params?.user_id) query.set('user_id', params.user_id);
      if (params?.limit) query.set('limit', params.limit.toString());
      const queryString = query.toString();
      return request<TasksListResponse>(
        `/tasks${queryString ? `?${queryString}` : ''}`
      );
    },

    get: (taskId: string) => request<TaskResponse>(`/task/${taskId}`),

    getExecutionStatus: (taskId: string) =>
      request<ExecutionStatusResponse>(`/task/${taskId}/execution-status`),

    confirm: (taskId: string) =>
      request<TaskResponse>(`/task/${taskId}/confirm`, {
        method: 'POST',
      }),

    revise: (taskId: string, revision: string) =>
      request<TaskResponse>(`/task/${taskId}/revise`, {
        method: 'POST',
        body: JSON.stringify({ revision }),
      }),
  },

  // Voice endpoints
  voice: {
    tts: async (text: string, language?: string): Promise<ArrayBuffer> => {
      const token = typeof window !== 'undefined' ? localStorage.getItem('done-token') : null;
      const baseUrl = API_BASE_URL;
      const response = await fetch(`${baseUrl}/api/v1/voice/tts`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ text, language }),
      });
      if (!response.ok) {
        throw new ApiError(response.status, response.statusText, null);
      }
      return response.arrayBuffer();
    },
  },

  // Alias: invites points to invite for compatibility
  get invites() {
    return this.invite;
  },

  // StateMachine endpoints (new architecture)
  sm: {
    sendMessage: (data: StateMachineMessageRequest) =>
      request<StateMachineResponse>('/sm/message', {
        method: 'POST',
        body: JSON.stringify(data),
      }),

    /**
     * SSEストリーミング版のsendMessage
     * ナレーション（reasoning_steps）をリアルタイムで受信する
     *
     * @param data リクエストデータ
     * @param callbacks コールバック関数群
     * @param signal AbortSignal（キャンセル用）
     */
    sendMessageStream: async (
      data: StateMachineMessageRequest,
      callbacks: {
        onProcessStep?: (step: ProcessStep, sessionId?: string) => void;
        onUserMessage?: (message: MessageResponse, sessionId?: string) => void;
        onAIMessage?: (message: MessageResponse, sessionId?: string) => void;
        onVoiceAnnouncement?: (text: string, sessionId?: string) => void;
        onComplete?: (sessionId?: string) => void;
        onError?: (error: string, sessionId?: string) => void;
        onSkillAvailable?: (browserSessionId: string, sessionId?: string) => void;
        onProjectCreated?: (projectId: string) => void;
      },
      signal?: AbortSignal
    ): Promise<void> => {
      console.log('[SSE] sendMessageStream called');
      let token: string | null = null;
      try {
        token = useAuthStore.getState().token;
      } catch (e) {
        console.error('[SSE] Failed to get token', e);
      }
      const baseUrl = SSE_BASE_URL;

      console.log('[SSE] Starting stream request', { data, baseUrl, hasToken: !!token });

      try {
        const response = await fetch(`${baseUrl}/api/v1/chat/dan/messages/stream`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ content: data.message, session_id: data.session_id }),
          signal,  // AbortSignal追加
        });

        console.log('[SSE] Response received', { status: response.status, ok: response.ok });

        // 401エラー時はログインページにリダイレクト
        if (response.status === 401) {
          setStoredToken(null);
          try {
            useAuthStore.getState().logout();
          } catch {
            // store未初期化時は無視
          }
          if (typeof window !== 'undefined') {
            window.location.href = '/login';
          }
          return;
        }

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error('No response body');
        }

        const decoder = new TextDecoder();
        let buffer = '';
        let completeCalled = false;

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // SSEイベントをパース (data: {...}\n\n形式)
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const eventData = line.slice(6);
              try {
                const parsed = JSON.parse(eventData);

                // session_idを抽出（バックエンドから送信される）
                const eventSessionId = parsed.session_id as string | undefined;

                if (parsed.type === 'process' && callbacks.onProcessStep) {
                  callbacks.onProcessStep(parsed.step, eventSessionId);
                } else if (parsed.type === 'voice_announcement' && callbacks.onVoiceAnnouncement) {
                  callbacks.onVoiceAnnouncement(parsed.text, eventSessionId);
                } else if (parsed.type === 'user_message' && callbacks.onUserMessage) {
                  callbacks.onUserMessage(parsed.message, eventSessionId);
                } else if (parsed.type === 'ai_message' && callbacks.onAIMessage) {
                  callbacks.onAIMessage(parsed.message, eventSessionId);
                } else if (parsed.type === 'done') {
                  // スキル化可能な場合、コールバックを呼び出す
                  if (parsed.can_create_skill && parsed.browser_session_id && callbacks.onSkillAvailable) {
                    callbacks.onSkillAvailable(parsed.browser_session_id, eventSessionId);
                  }
                  // プロジェクト作成通知
                  if (parsed.created_project_id && callbacks.onProjectCreated) {
                    callbacks.onProjectCreated(parsed.created_project_id);
                  }
                  if (callbacks.onComplete) {
                    completeCalled = true;
                    callbacks.onComplete(eventSessionId);
                  }
                } else if (parsed.type === 'cancelled' && callbacks.onComplete) {
                  // キャンセルも完了として処理
                  completeCalled = true;
                  callbacks.onComplete(eventSessionId);
                } else if (parsed.type === 'error' && callbacks.onError) {
                  callbacks.onError(parsed.message, eventSessionId);
                }
              } catch (err) {
                console.error('Failed to parse SSE data:', eventData, err);
              }
            }
          }
        }

        // ストリーム終了時の安全弁: done イベントなしで終了した場合もクリーンアップ
        if (!completeCalled && callbacks.onComplete) {
          console.warn('[SSE] Stream ended without done event, forcing cleanup');
          callbacks.onComplete();
        }
      } catch (error) {
        // AbortErrorは意図的なキャンセルなのでエラーとして扱わない
        if (error instanceof DOMException && error.name === 'AbortError') {
          console.log('[SSE] Request cancelled by user');
          // キャンセル時もクリーンアップ
          if (callbacks.onComplete) {
            callbacks.onComplete();
          }
          return;
        }
        if (callbacks.onError) {
          callbacks.onError(error instanceof Error ? error.message : String(error));
        }
        // エラー時もスピナー停止のためクリーンアップ
        if (callbacks.onComplete) {
          callbacks.onComplete();
        }
      }
    },

    confirm: (sessionId: string, userId?: string) =>
      request<StateMachineResponse>(`/sm/${sessionId}/confirm`, {
        method: 'POST',
        body: JSON.stringify({ user_id: userId }),
      }),

    revise: (sessionId: string, revision: string, userId?: string) =>
      request<StateMachineResponse>(`/sm/${sessionId}/revise`, {
        method: 'POST',
        body: JSON.stringify({ revision, user_id: userId }),
      }),

    getState: (sessionId: string) =>
      request<StateMachineResponse>(`/sm/${sessionId}/state`),

    /**
     * セッションをキャンセル
     * バックエンドのツール実行を停止する
     */
    cancelSession: (sessionId: string) =>
      request<{ success: boolean; session_id: string }>('/chat/dan/cancel', {
        method: 'POST',
        body: JSON.stringify({ session_id: sessionId }),
      }),
  },

  // Projects endpoints
  projects: {
    list: (status?: ProjectStatusType) => {
      const query = new URLSearchParams();
      if (status) query.set('status', status);
      const qs = query.toString();
      return request<ProjectListResponse>(`/projects${qs ? `?${qs}` : ''}`);
    },

    get: (projectId: string) =>
      request<ProjectResponse>(`/projects/${projectId}`),

    create: (data: { title: string; description?: string; origin_room_id?: string }) =>
      request<ProjectResponse>('/projects', {
        method: 'POST',
        body: JSON.stringify(data),
      }),

    update: (projectId: string, data: { title?: string; status?: ProjectStatusType; summary?: string }) =>
      request<ProjectResponse>(`/projects/${projectId}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),

    delete: (projectId: string) =>
      request<void>(`/projects/${projectId}`, {
        method: 'DELETE',
      }),

    proposals: {
      list: (projectId: string) =>
        request<ProjectProposalResponse[]>(`/projects/${projectId}/proposals`),

      action: (projectId: string, proposalId: string, action: 'approve' | 'reject') =>
        request<ProjectProposalResponse>(`/projects/${projectId}/proposals/${proposalId}/action`, {
          method: 'POST',
          body: JSON.stringify({ action }),
        }),
    },

    executionEvents: {
      list: (projectId: string, limit = 100) =>
        request<ExecutionEvent[]>(`/projects/${projectId}/execution-events?limit=${limit}`),
    },
  },

  // Skills endpoints
  skills: {
    analyze: (sessionId: string, instruction?: string) =>
      request<{
        success: boolean;
        // 複数提案対応（新規）
        proposals: Array<{
          proposal_id: string;
          skill_name: string;
          description: string;
          site: string;
          actions: string[];
          parameters: Array<{
            name: string;
            type: string;
            required: boolean;
            description: string;
          }>;
          decision: string;  // create / extend / skip
          target_skill?: string | null;
          new_actions?: string[] | null;
        }>;
        message: string;
        // 後方互換（deprecated）
        proposal_id: string | null;
        status: string | null;
        skill_name: string | null;
        description: string | null;
        site: string | null;
        actions: string[];
        parameters: Array<{
          name: string;
          type: string;
          required: boolean;
          description: string;
        }>;
        analysis?: Record<string, unknown> | null;
        steps?: string[] | null;
        decision?: string | null;  // create / extend / skip
        decision_reason?: string | null;
        skip_reason?: string | null;
      }>('/skills/analyze', {
        method: 'POST',
        body: JSON.stringify({
          session_id: sessionId,
          instruction,
        }),
      }),

    generate: (proposalId: string, skillName?: string, instruction?: string) =>
      request<{
        success: boolean;
        proposal_id: string | null;
        status: string | null;
        skill_name: string;
        skill_path: string | null;
        files_created: string[] | null;
        message: string;
      }>('/skills/generate', {
        method: 'POST',
        body: JSON.stringify({
          proposal_id: proposalId,
          skill_name: skillName,
          instruction,
        }),
      }),

    listProposals: (sessionId?: string, status?: string, limit: number = 10) =>
      request<{
        proposals: Array<{
          id: string;
          session_id: string;
          instruction?: string | null;
          status: string;
          skill_name?: string | null;
          description?: string | null;
          site?: string | null;
          actions: string[];
          parameters: Array<{
            name: string;
            type: string;
            required: boolean;
            description: string;
          }>;
          analysis?: Record<string, unknown> | null;
          steps?: string[] | null;
          created_at?: string | null;
          updated_at?: string | null;
        }>;
      }>(`/skills/proposals?${new URLSearchParams({
        ...(sessionId ? { session_id: sessionId } : {}),
        ...(status ? { status } : {}),
        ...(limit ? { limit: String(limit) } : {}),
      }).toString()}`),

    getProposal: (proposalId: string) =>
      request<{
        id: string;
        session_id: string;
        instruction?: string | null;
        status: string;
        skill_name?: string | null;
        description?: string | null;
        site?: string | null;
        actions: string[];
        parameters: Array<{
          name: string;
          type: string;
          required: boolean;
          description: string;
        }>;
        analysis?: Record<string, unknown> | null;
        steps?: string[] | null;
        created_at?: string | null;
        updated_at?: string | null;
      }>(`/skills/proposals/${proposalId}`),

    dismissProposal: (proposalId: string, status: string = 'dismissed') =>
      request<{
        id: string;
        session_id: string;
        instruction?: string | null;
        status: string;
        skill_name?: string | null;
        description?: string | null;
        site?: string | null;
        actions: string[];
        parameters: Array<{
          name: string;
          type: string;
          required: boolean;
          description: string;
        }>;
        analysis?: Record<string, unknown> | null;
        steps?: string[] | null;
        created_at?: string | null;
        updated_at?: string | null;
      }>(`/skills/proposals/${proposalId}/dismiss`, {
        method: 'POST',
        body: JSON.stringify({ status }),
      }),

    list: () =>
      request<{
        skills: Array<{
          name: string;
          title: string;
          path: string;
          generated_at: string | null;
          has_actions: boolean;
        }>;
      }>('/skills/list'),

    get: (skillName: string) =>
      request<{
        name: string;
        skill_md: string;
        actions: Record<string, string>;
        selectors: string | null;
      }>(`/skills/${skillName}`),

    delete: (skillName: string) =>
      request<{ success: boolean; message: string }>(`/skills/${skillName}`, {
        method: 'DELETE',
      }),
  },

  // Notes endpoints
  notes: {
    // Drafts
    listDrafts: () =>
      request<{ drafts: NoteDraftResponse[] }>('/notes/drafts'),

    createDraft: (data: { title: string; content: string; tags?: string[] }) =>
      request<NoteDraftResponse>('/notes/drafts', {
        method: 'POST',
        body: JSON.stringify(data),
      }),

    getDraft: (draftId: string) =>
      request<NoteDraftResponse>(`/notes/drafts/${draftId}`),

    updateDraft: (draftId: string, data: { title?: string; content?: string; tags?: string[] }) =>
      request<NoteDraftResponse>(`/notes/drafts/${draftId}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),

    deleteDraft: (draftId: string) =>
      request<{ ok: boolean }>(`/notes/drafts/${draftId}`, {
        method: 'DELETE',
      }),

    // Polish
    getPolishPrompt: (draftId: string) =>
      request<{ draft_id: string; prompt: string; draft_title: string; draft_content: string }>(
        '/notes/polish',
        {
          method: 'POST',
          body: JSON.stringify({ draft_id: draftId }),
        }
      ),

    executePolish: (draftId: string, options?: { article_type?: 'free' | 'paid'; price?: number }) =>
      request<NotePolishedResponse>(`/notes/polish/${draftId}/execute`, {
        method: 'POST',
        body: JSON.stringify(options || {}),
      }),

    getPolished: (draftId: string) =>
      request<NotePolishedResponse>(`/notes/polish/${draftId}`),

    // Posts
    recordPost: (data: { draft_id: string; note_url: string; published?: boolean }) =>
      request<NotePostResponse>('/notes/posts', {
        method: 'POST',
        body: JSON.stringify(data),
      }),

    listPosts: () =>
      request<{ posts: NotePostResponse[] }>('/notes/posts'),

    // Schedules
    createSchedule: (data: {
      draft_id: string;
      scheduled_at: string;
      article_type?: 'free' | 'paid';
      price?: number;
    }) =>
      request<NoteScheduleResponse>('/notes/schedules', {
        method: 'POST',
        body: JSON.stringify(data),
      }),

    listSchedules: () =>
      request<{ schedules: NoteScheduleResponse[] }>('/notes/schedules'),

    getSchedule: (scheduleId: string) =>
      request<NoteScheduleResponse>(`/notes/schedules/${scheduleId}`),

    updateSchedule: (scheduleId: string, data: {
      scheduled_at?: string;
      article_type?: 'free' | 'paid';
      price?: number;
    }) =>
      request<NoteScheduleResponse>(`/notes/schedules/${scheduleId}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),

    cancelSchedule: (scheduleId: string) =>
      request<NoteScheduleResponse>(`/notes/schedules/${scheduleId}`, {
        method: 'DELETE',
      }),

    // Stats
    getStats: () =>
      request<NoteStatsResponse>('/notes/stats'),
  },

  // File upload endpoint
  files: {
    upload: (file: File) => uploadFile('/files/upload', file),
  },
};
