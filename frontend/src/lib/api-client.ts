/**
 * API Client for Done Backend
 * Handles all HTTP requests to the backend API
 */

import { useAuthStore } from '@/stores/auth-store';

// API Base URL - env 値に trailing whitespace / 改行が混入すると URL が壊れるので trim
const API_BASE_URL = '';

// SSE streaming - 同様に trim
const SSE_BASE_URL = '';

// ==================== Types ====================

export const OWNER_USER_ID = '2582a188-ff24-4a4f-b989-6063034d90b2';

export interface AchievementEvidence {
  kind: 'commit' | 'room' | 'cli' | 'watch' | 'url' | 'mail';
  label: string;
  ref: string;
}

export interface AchievementItem {
  id: string;
  day: string;
  title: string;
  detail: string | null;
  status: 'done' | 'in_progress' | 'dismissed';
  tags: string[];
  evidence: AchievementEvidence[];
  sources: string[];
  first_seen: string;
  done_at: string | null;
  updated_at: string;
}

export interface AchievementsResponse {
  day: string;
  today: string;
  items: AchievementItem[];
  days: string[];
  last_run: string | null;
}

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
  guest_tokens?: string[];
}

export interface RegisterRequest {
  email: string;
  password: string;
  display_name: string;
  guest_tokens?: string[];
}

export interface TokenResponse {
  access_token: string;
}

export interface ReplyToMessage {
  id: string;
  sender_name: string;
  sender_type: 'human' | 'ai';
  content: string;
  created_at: string;
}

export type TurnBlock =
  | { type: 'text'; text: string }
  | { type: 'tool'; name?: string; label?: string; detail?: string }
  | { type: 'reasoning'; text?: string }
  | { type: 'error'; text?: string };

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
    blocks?: TurnBlock[];
    turn_id?: string;
  };
  reply_to_id?: string;
  reply_to_message?: ReplyToMessage;
  // ダン作業中の追い連絡で、まだ「読まれて反映」されていない仮送信状態（半透明表示）。
  // クライアント側のみで付与し、ダンの応答到着でクリアする（DB列ではない）。
  pendingFollowup?: boolean;
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
  image_urls?: string[];
  file_urls?: { name: string; url: string }[];
  reply_to_id?: string;
  replace_message_id?: string;
  timeline_refs?: { content_id: string; title: string }[];
  client_message_id?: string;
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
  icon: string | null;
  metadata: Record<string, unknown> | null;
  unread_count: number;
  last_message_at: string | null;
  pinned_at: string | null;
  // ダンがこのプロジェクトで今まさに作業中か（一覧の「作業中」インジケーター用）
  has_active_run?: boolean;
  created_at: string;
  updated_at: string | null;
}

export interface ProjectListResponse {
  projects: ProjectResponse[];
}

export interface ProjectProposalResponse {
  id: string;
  project_id: string;
  run_id?: string | null;
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
  project_id: string | null;
  run_id?: string | null;
  turn_id?: string | null;
  room_id: string;
  event_type: 'tool_use' | 'reasoning' | 'phase' | 'error' | 'text' | 'done';
  tool_name: string | null;
  tool_label: string | null;
  content: string | null;
  metadata: Record<string, unknown> | null;
  seq: number | null;
  created_at: string;
}

export interface ActiveSessionStatus {
  active: boolean;
  session_id: string;
  started_at: number | null;
  origin_message_id?: string | null;
}

export type AgentRunState =
  | 'running'
  | 'awaiting_approval'
  | 'awaiting_confirmation'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'superseded';

export interface AgentRunResponse {
  id: string;
  project_id: string;
  room_id: string;
  claude_session_id?: string | null;
  parent_run_id?: string | null;
  state: AgentRunState;
  active_proposal_id?: string | null;
  superseded_by_run_id?: string | null;
  metadata?: Record<string, unknown> | null;
  created_at: string;
  updated_at?: string | null;
}

export type StreamInterruptionReason = 'stream_ended' | 'transient_error';

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

// ==================== Studio Types ====================

export interface StudioChannel {
  id: string;
  name: string;
  description?: string;
  concept?: string;
  character_name?: string;
  character_description?: string;
  character_image_url?: string;
  youtube_channel_id?: string;
  youtube_channel_url?: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface StudioEpisode {
  id: string;
  channel_id: string;
  episode_number?: number;
  title: string;
  description?: string;
  script?: string;
  script_messages: Array<{ role: string; content: string }>;
  status: string;
  youtube_video_id?: string;
  youtube_url?: string;
  scheduled_at?: string;
  published_at?: string;
  created_at: string;
  updated_at: string;
}

export interface StudioVoiceTrack {
  id: string;
  episode_id: string;
  label?: string;
  text_content: string;
  voice_id?: string;
  file_url?: string;
  duration_seconds?: number;
  status: string;
  created_at: string;
}

export interface StudioVideoClip {
  id: string;
  episode_id: string;
  label?: string;
  prompt: string;
  file_url?: string;
  thumbnail_url?: string;
  kling_task_id?: string;
  kling_status: string;
  sort_order: number;
  created_at: string;
  updated_at: string;
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
    credentials: 'include',
    body: formData,
  });

  if (!response.ok) {
    // 失敗時はレスポンス body と一部ヘッダも保持する（PWA等で原因切り分けが必要なため）
    let bodyText = '';
    try { bodyText = await response.text(); } catch { /* ignore */ }
    const debugInfo = {
      body: bodyText.slice(0, 500),
      server: response.headers.get('server') || '',
      via: response.headers.get('via') || '',
      cfRay: response.headers.get('cf-ray') || '',
    };
    throw new ApiError(response.status, response.statusText, debugInfo);
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
    credentials: options.credentials ?? 'include',
  });

  if (!response.ok) {
    // 401 Unauthorized: セッション切れ → ログインページにリダイレクト
    if (response.status === 401) {
      // ログインエンドポイント自体の401はリダイレクトしない（パスワード間違い等）
      const isLoginEndpoint = endpoint === '/chat/login' || endpoint === '/chat/register';
      if (!isLoginEndpoint) {
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
    }

    let data: unknown;
    try {
      data = await response.json();
    } catch {
      data = { message: 'Unknown error' };
    }
    throw new ApiError(response.status, response.statusText, data);
  }

  // Handle empty responses (e.g. 204 No Content)
  if (response.status === 204) {
    return {} as T;
  }

  const contentType = response.headers.get('content-type');
  if (!contentType || !contentType.includes('application/json')) {
    return {} as T;
  }

  return response.json();
}

// ==================== Helpers ====================

/**
 * 一時的なネットワークエラーかどうかを判定
 * モバイルでのタブ切り替え等で発生する接続断を検出する
 */
function isTransientNetworkError(message?: string): boolean {
  if (!message) return false;
  const m = message.toLowerCase();
  return (
    m.includes('networkerror') ||
    m.includes('failed to fetch') ||
    m.includes('network request failed') ||
    m.includes('load failed') ||               // iOS Safari
    m.includes('the operation was aborted') ||  // Chrome Android
    m.includes('connection was lost') ||        // Safari generic
    m.includes('network connection') ||         // Android WebView
    m.includes('aborted')                       // fetch abort by OS
  );
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

    searchMessages: (roomId: string, q: string, limit = 50) => {
      const query = new URLSearchParams({ q, limit: limit.toString() });
      return request<MessagesListResponse>(
        `/chat/rooms/${roomId}/messages/search?${query.toString()}`
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
    list: (params?: { status?: ProposalStatus; limit?: number; types?: string; excludeTypes?: string }) => {
      const query = new URLSearchParams();
      if (params?.status) query.set('status', params.status);
      if (params?.limit) query.set('limit', params.limit.toString());
      if (params?.types) query.set('types', params.types);
      if (params?.excludeTypes) query.set('exclude_types', params.excludeTypes);
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

    // 提案への自由指示（書き換え/依頼/質問）
    instruct: (proposalId: string, instruction: string) =>
      request<{ mode: 'revise' | 'delegate' | 'answer'; message: string; proposal?: ProposalResponse }>(
        `/chat/proposals/${proposalId}/instruct`,
        {
          method: 'POST',
          body: JSON.stringify({ instruction }),
        }
      ),
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
        onFollowupQueued?: (messageId: string, sessionId?: string) => void;
        onComplete?: (sessionId?: string) => void;
        onError?: (error: string, sessionId?: string) => void;
        onInterrupted?: (reason: StreamInterruptionReason, sessionId?: string) => void;
        onSkillAvailable?: (browserSessionId: string, sessionId?: string) => void;
        onProjectCreated?: (projectId: string) => void;
      },
      signal?: AbortSignal
    ): Promise<void> => {
      let token: string | null = null;
      try {
        token = useAuthStore.getState().token;
      } catch (e) {
        console.error('[SSE] Failed to get token', e);
      }
      const baseUrl = SSE_BASE_URL;

      try {
        const response = await fetch(`${baseUrl}/api/v1/chat/dan/messages/stream`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ content: data.message, session_id: data.session_id, ...(data.image_urls?.length ? { image_urls: data.image_urls } : {}), ...(data.file_urls?.length ? { file_urls: data.file_urls } : {}), ...(data.reply_to_id ? { reply_to_id: data.reply_to_id } : {}), ...(data.replace_message_id ? { replace_message_id: data.replace_message_id } : {}), ...(data.timeline_refs?.length ? { timeline_refs: data.timeline_refs } : {}), ...(data.client_message_id ? { client_message_id: data.client_message_id } : {}) }),
          signal,  // AbortSignal追加
        });

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
        let lastEventSessionId = data.session_id;

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
                if (eventSessionId) {
                  lastEventSessionId = eventSessionId;
                }

                if (parsed.type === 'process' && callbacks.onProcessStep) {
                  callbacks.onProcessStep(parsed.step, eventSessionId);
                } else if (parsed.type === 'voice_announcement' && callbacks.onVoiceAnnouncement) {
                  callbacks.onVoiceAnnouncement(parsed.text, eventSessionId);
                } else if (parsed.type === 'user_message' && callbacks.onUserMessage) {
                  callbacks.onUserMessage(parsed.message, eventSessionId);
                } else if (parsed.type === 'ai_message' && callbacks.onAIMessage) {
                  callbacks.onAIMessage(parsed.message, eventSessionId);
                } else if (parsed.type === 'followup_queued' && callbacks.onFollowupQueued) {
                  callbacks.onFollowupQueued(parsed.message_id, eventSessionId);
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
        if (!completeCalled && callbacks.onInterrupted) {
          console.warn('[SSE] Stream ended without done event, switching to recovery');
          callbacks.onInterrupted('stream_ended', lastEventSessionId);
        }
      } catch (error) {
        // AbortErrorは意図的なキャンセルなのでエラーとして扱わない
        if (error instanceof DOMException && error.name === 'AbortError') {
          // キャンセル時もクリーンアップ
          if (callbacks.onComplete) {
            callbacks.onComplete();
          }
          return;
        }

        const errorMsg = error instanceof Error ? error.message : String(error);
        const isTransient = isTransientNetworkError(errorMsg);

        if (isTransient) {
          callbacks.onInterrupted?.('transient_error', data.session_id);
          return;
        }

        if (callbacks.onError) {
          callbacks.onError(errorMsg);
        }
        // 一時的ネットワークエラー時はonCompleteを呼ばない → スピナー維持
        // useProjectRecovery がタブ復帰時に引き継ぐ
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
    cancelSession: (sessionId: string, options?: { cancelledUserMessageId?: string | null }) =>
      request<{ success: boolean; session_id: string }>('/chat/dan/cancel', {
        method: 'POST',
        body: JSON.stringify({
          session_id: sessionId,
          cancelled_user_message_id: options?.cancelledUserMessageId || undefined,
        }),
      }),

    /**
     * セッションがバックエンドで実行中かどうかを確認
     * ページ読み込み時やタブ復帰時に呼び出す
     */
    getActiveStatus: (sessionId: string) =>
      request<ActiveSessionStatus>(`/chat/dan/sessions/${sessionId}/active`),

    /**
     * セッションの実行イベントを取得（差分取得対応）
     * since_seq を指定するとそれ以降のイベントのみ返す
     * currentOnly=true で最後のdone以降のみ返す（現在の実行分のみ）
     */
    getSessionEvents: (sessionId: string, sinceSeq?: number, currentOnly?: boolean) => {
      const params = new URLSearchParams();
      if (sinceSeq !== undefined) params.set('since_seq', String(sinceSeq));
      if (currentOnly) params.set('current_only', 'true');
      const qs = params.toString();
      return request<ExecutionEvent[]>(`/chat/dan/sessions/${sessionId}/execution-events${qs ? `?${qs}` : ''}`);
    },
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

    suggestTitle: (roomId?: string) =>
      request<{ title: string }>(`/projects/suggest-title${roomId ? `?room_id=${roomId}` : ''}`),

    create: (data: { title: string; description?: string; origin_room_id?: string; model?: string }) =>
      request<ProjectResponse>('/projects', {
        method: 'POST',
        body: JSON.stringify(data),
      }),

    update: (projectId: string, data: { title?: string; status?: ProjectStatusType; summary?: string; icon?: string; pinned?: boolean }) =>
      request<ProjectResponse>(`/projects/${projectId}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),

    delete: (projectId: string) =>
      request<void>(`/projects/${projectId}`, {
        method: 'DELETE',
      }),

    currentRun: (projectId: string) =>
      request<AgentRunResponse>(`/projects/${projectId}/current-run`),

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
      list: (projectId: string, limit = 500, runId?: string) =>
        request<ExecutionEvent[]>(
          `/projects/${projectId}/execution-events?limit=${limit}${runId ? `&run_id=${runId}` : ''}`
        ),
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
  achievements: {
    list: (day?: string) =>
      request<AchievementsResponse>(`/achievements${day ? `?day=${day}` : ''}`),
    refresh: () =>
      request<{ judged: boolean; changed: number }>('/achievements/refresh', { method: 'POST' }),
    patch: (id: string, data: { status?: string; title?: string; detail?: string; tags?: string[] }) =>
      request<AchievementItem>(`/achievements/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  },

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

  // Studio - AI Vlog Production
  studio: {
    // Channels
    listChannels: () => request<StudioChannel[]>('/studio/channels'),
    createChannel: (data: { name: string; description?: string; concept?: string; character_name?: string; character_description?: string }) =>
      request<StudioChannel>('/studio/channels', { method: 'POST', body: JSON.stringify(data) }),
    updateChannel: (id: string, data: Partial<StudioChannel>) =>
      request<StudioChannel>(`/studio/channels/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

    // Episodes
    listEpisodes: (channelId: string) => request<StudioEpisode[]>(`/studio/channels/${channelId}/episodes`),
    createEpisode: (data: { channel_id: string; title: string; episode_number?: number; description?: string }) =>
      request<StudioEpisode>('/studio/episodes', { method: 'POST', body: JSON.stringify(data) }),
    getEpisode: (episodeId: string) => request<StudioEpisode>(`/studio/episodes/${episodeId}`),
    updateEpisode: (episodeId: string, data: Partial<StudioEpisode>) =>
      request<StudioEpisode>(`/studio/episodes/${episodeId}`, { method: 'PATCH', body: JSON.stringify(data) }),

    // Script chat
    chatScript: (episodeId: string, message: string) =>
      request<{ response: string }>('/studio/script/chat', {
        method: 'POST',
        body: JSON.stringify({ episode_id: episodeId, message }),
      }),

    // Voice
    generateVoice: (episodeId: string, text: string, label?: string, voiceId?: string) =>
      request<StudioVoiceTrack>('/studio/voice/generate', {
        method: 'POST',
        body: JSON.stringify({ episode_id: episodeId, text, label, voice_id: voiceId }),
      }),
    listVoiceTracks: (episodeId: string) => request<StudioVoiceTrack[]>(`/studio/episodes/${episodeId}/voice`),

    // Video
    generateVideo: (episodeId: string, prompt: string, duration?: number, mode?: string, label?: string) =>
      request<StudioVideoClip>('/studio/video/generate', {
        method: 'POST',
        body: JSON.stringify({ episode_id: episodeId, prompt, duration: duration ?? 5, mode: mode ?? 'std', label }),
      }),
    checkVideoStatus: (clipId: string) => request<StudioVideoClip>(`/studio/video/${clipId}/status`),
    listVideoClips: (episodeId: string) => request<StudioVideoClip[]>(`/studio/episodes/${episodeId}/clips`),
  },

  // Collab endpoints
  collab: {
    createRoom: (data: { title: string; description?: string; project_ref?: string; ai_auto_assist?: boolean }) =>
      request<CollabRoomResponse>('/collab/rooms', {
        method: 'POST',
        body: JSON.stringify(data),
      }),

    listRooms: () => request<{ rooms: CollabRoomResponse[] }>('/collab/rooms'),

    getRoom: (roomId: string) => request<CollabRoomResponse>(`/collab/rooms/${roomId}`),

    updateRoom: (roomId: string, data: Partial<{ title: string; status: string; ai_auto_assist: boolean }>) =>
      request<CollabRoomResponse>(`/collab/rooms/${roomId}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),

    deleteRoom: (roomId: string) =>
      request<{ success: boolean }>(`/collab/rooms/${roomId}`, {
        method: 'DELETE',
      }),

    createInvite: (roomId: string, data?: { role?: string; expires_hours?: number }) =>
      request<CollabInviteResponse>(`/collab/rooms/${roomId}/invites`, {
        method: 'POST',
        body: JSON.stringify(data ?? {}),
      }),

    listInvites: (roomId: string) => request<{ invites: CollabInviteRaw[] }>(`/collab/rooms/${roomId}/invites`),

    getInviteInfo: (token: string) => request<CollabInviteInfo>(`/collab/join/${token}`),

    joinRoom: (token: string, guestName: string) =>
      request<CollabJoinResponse>(`/collab/join/${token}`, {
        method: 'POST',
        body: JSON.stringify({ guest_name: guestName }),
      }),

    getMessages: (roomId: string, limit?: number, token?: string) => {
      const headers: Record<string, string> = {};
      if (token) headers['X-Guest-Token'] = token;
      return request<{ messages: CollabMessageResponse[] }>(
        `/collab/rooms/${roomId}/messages?limit=${limit ?? 50}`,
        { headers }
      );
    },

    sendMessage: (roomId: string, content: string, token?: string) => {
      const headers: Record<string, string> = {};
      if (token) headers['X-Guest-Token'] = token;
      return request<CollabMessageResponse>(`/collab/rooms/${roomId}/messages`, {
        method: 'POST',
        body: JSON.stringify({ content }),
        headers,
      });
    },

    getFiles: (roomId: string, token?: string) => {
      const headers: Record<string, string> = {};
      if (token) headers['X-Guest-Token'] = token;
      return request<{ files: CollabFileResponse[] }>(`/collab/rooms/${roomId}/files`, { headers });
    },

    generateReply: (roomId: string, messageId: string, content: string) =>
      request<{ reply: string; message_id: string }>(`/collab/rooms/${roomId}/generate-reply`, {
        method: 'POST',
        body: JSON.stringify({ message_id: messageId, content }),
      }),

    generateReplyGuest: (roomId: string, messageId: string, content: string, token: string) =>
      request<{ reply: string; message_id: string }>(`/collab/rooms/${roomId}/generate-reply-guest`, {
        method: 'POST',
        body: JSON.stringify({ message_id: messageId, content }),
        headers: { 'X-Guest-Token': token },
      }),
  },
};

// ==================== Collab Types ====================

export interface CollabRoomResponse {
  id: string;
  owner_id: string;
  title: string;
  description: string | null;
  project_ref: string | null;
  status: string;
  ai_auto_assist: boolean;
  ai_assist_config: Record<string, boolean> | null;
  guest_count: number;
  last_message: string | null;
  last_message_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CollabInviteResponse {
  id: string;
  room_id: string;
  token: string;
  invite_url: string;
  role: string;
  status: string;
  expires_at: string;
  created_at: string;
}

export interface CollabInviteRaw {
  id: string;
  room_id: string;
  token: string;
  role: string;
  status: string;
  guest_name: string | null;
  expires_at: string;
  joined_at: string | null;
}

export interface CollabInviteInfo {
  room_title: string;
  room_description: string | null;
  role: string;
  status: string;
  already_joined: boolean;
  guest_name: string | null;
}

export interface CollabJoinResponse {
  room_id: string;
  room_title: string;
  guest_token: string;
  guest_name: string;
  role: string;
}

export interface CollabMessageResponse {
  id: string;
  room_id: string;
  sender_type: string;
  sender_name: string;
  content: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface CollabFileResponse {
  id: string;
  room_id: string;
  uploaded_by: string;
  file_name: string;
  file_path: string;
  file_type: string | null;
  file_size: number | null;
  created_at: string;
}

// ==================== Document Types ====================

export type DocType = 'folder' | 'file' | 'collection';

export interface DocumentResponse {
  id: string;
  parent_id: string | null;
  title: string;
  description: string | null;
  content: Record<string, unknown>[] | null;
  doc_type: DocType;
  category_id: string | null;
  icon: string | null;
  tags: string[];
  metadata: Record<string, unknown> | null;
  sort_order: number;
  is_starred: boolean;
  is_deleted: boolean;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
  children_count?: number;
  files?: DocumentFileResponse[];
  category?: DocumentCategoryResponse | null;
}

export interface DocumentTreeNode {
  id: string;
  title: string;
  doc_type: DocType;
  icon: string | null;
  parent_id: string | null;
  children_count: number;
  is_starred: boolean;
}

export interface DocumentFileResponse {
  id: string;
  document_id: string;
  filename: string;
  original_name: string;
  file_url: string;
  mime_type: string | null;
  file_size: number;
  version: number;
  is_current: boolean;
  created_at: string;
}

export interface DocumentCategoryResponse {
  id: string;
  name: string;
  slug: string;
  icon: string | null;
  parent_id: string | null;
  description: string | null;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface DocumentSearchResult {
  documents: DocumentResponse[];
  total: number;
  query: string;
}

// ==================== Document API ====================

export function listDocuments(params?: {
  parent_id?: string | null;
  category_id?: string;
  doc_type?: DocType;
  starred?: boolean;
  deleted?: boolean;
  limit?: number;
  offset?: number;
}) {
  const searchParams = new URLSearchParams();
  if (params) {
    if (params.parent_id !== undefined) searchParams.set('parent_id', params.parent_id ?? '');
    if (params.category_id) searchParams.set('category_id', params.category_id);
    if (params.doc_type) searchParams.set('doc_type', params.doc_type);
    if (params.starred !== undefined) searchParams.set('starred', String(params.starred));
    if (params.deleted !== undefined) searchParams.set('deleted', String(params.deleted));
    if (params.limit) searchParams.set('limit', String(params.limit));
    if (params.offset) searchParams.set('offset', String(params.offset));
  }
  const qs = searchParams.toString();
  return request<DocumentResponse[]>(`/documents${qs ? `?${qs}` : ''}`);
}

export function createDocument(data: {
  title: string;
  doc_type?: DocType;
  parent_id?: string | null;
  content?: Record<string, unknown>[];
  description?: string;
  category_id?: string;
  icon?: string;
  tags?: string[];
  metadata?: Record<string, unknown>;
}) {
  return request<DocumentResponse>('/documents', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function getDocument(id: string) {
  return request<DocumentResponse>(`/documents/${id}`);
}

export function updateDocument(id: string, data: {
  title?: string;
  content?: Record<string, unknown>[];
  description?: string;
  category_id?: string;
  icon?: string;
  tags?: string[];
  metadata?: Record<string, unknown>;
  is_starred?: boolean;
  sort_order?: number;
}) {
  return request<DocumentResponse>(`/documents/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export function deleteDocument(id: string) {
  return request<void>(`/documents/${id}`, { method: 'DELETE' });
}

export function restoreDocument(id: string) {
  return request<DocumentResponse>(`/documents/${id}/restore`, { method: 'POST' });
}

export function moveDocument(id: string, data: { parent_id?: string | null; sort_order?: number }) {
  return request<DocumentResponse>(`/documents/${id}/move`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function getDocumentTree() {
  return request<DocumentTreeNode[]>('/documents/tree');
}

export function getRecentDocuments(limit?: number) {
  const qs = limit ? `?limit=${limit}` : '';
  return request<DocumentResponse[]>(`/documents/recent${qs}`);
}

export function getStarredDocuments() {
  return request<DocumentResponse[]>('/documents/starred');
}

export function searchDocuments(q: string, params?: { category_id?: string; limit?: number }) {
  const searchParams = new URLSearchParams({ q });
  if (params?.category_id) searchParams.set('category_id', params.category_id);
  if (params?.limit) searchParams.set('limit', String(params.limit));
  return request<DocumentSearchResult>(`/documents/search?${searchParams.toString()}`);
}

export function listCategories() {
  return request<DocumentCategoryResponse[]>('/documents/categories');
}

export function createCategory(data: {
  name: string;
  slug: string;
  icon?: string;
  parent_id?: string;
  description?: string;
  sort_order?: number;
}) {
  return request<DocumentCategoryResponse>('/documents/categories', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function listDocumentFiles(docId: string) {
  return request<DocumentFileResponse[]>(`/documents/${docId}/files`);
}

export function uploadDocumentFile(docId: string, file: File) {
  return uploadFile(`/documents/${docId}/files`, file);
}

export function deleteDocumentFile(fileId: string) {
  return request<void>(`/documents/files/${fileId}`, { method: 'DELETE' });
}

// ==================== Blocks API (Dan Workspace) ====================

export type BlockType =
  | 'page' | 'paragraph' | 'heading' | 'bullet_list' | 'numbered_list'
  | 'checklist' | 'task' | 'quote' | 'code' | 'divider' | 'callout'
  | 'image' | 'video' | 'audio' | 'pdf' | 'file' | 'embed'
  | 'email' | 'calendar_event' | 'table' | 'database' | 'bookmark';

export type BlockSource =
  | 'manual' | 'gmail' | 'calendar' | 'collab' | 'chat' | 'file_upload' | 'agent';

export interface BlockFileResponse {
  id: string;
  storage_path: string;
  original_name: string;
  mime_type: string;
  file_size: number;
  version: number;
  is_current: boolean;
  thumbnail_path: string | null;
  width: number | null;
  height: number | null;
  duration_ms: number | null;
  created_at: string;
}

export interface BlockResponse {
  id: string;
  user_id: string;
  parent_id: string | null;
  type: BlockType;
  order_key: string;
  properties: Record<string, unknown>;
  content: unknown[];
  icon: string | null;
  cover_url: string | null;
  is_starred: boolean;
  tags: string[];
  created_by: 'user' | 'ai' | 'system';
  source: BlockSource;
  source_id: string | null;
  created_at: string;
  updated_at: string;
  files?: BlockFileResponse[];
  children_count?: number;
}

export interface BlockTreeNode {
  id: string;
  parent_id: string | null;
  type: BlockType;
  title: string;
  icon: string | null;
  is_starred: boolean;
  order_key: string;
  has_children: boolean;
}

export function createBlock(data: {
  type: BlockType;
  parent_id?: string | null;
  properties?: Record<string, unknown>;
  content?: unknown[];
  icon?: string;
  cover_url?: string;
  tags?: string[];
  after_block_id?: string;
  before_block_id?: string;
  source?: BlockSource;
  source_id?: string;
  created_by?: 'user' | 'ai' | 'system';
}) {
  return request<BlockResponse>('/blocks', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function getBlockTree() {
  return request<{ nodes: BlockTreeNode[] }>('/blocks/tree');
}

export function getStarredBlocks() {
  return request<{ blocks: BlockResponse[] }>('/blocks/starred');
}

export function getRecentBlocks(limit = 20) {
  return request<{ blocks: BlockResponse[] }>(`/blocks/recent?limit=${limit}`);
}

export function listChildBlocks(parentId: string | null) {
  const qs = parentId ? `?parent_id=${parentId}` : '';
  return request<{ blocks: BlockResponse[]; total: number }>(`/blocks/children${qs}`);
}

export function getBlock(blockId: string) {
  return request<BlockResponse>(`/blocks/${blockId}`);
}

export function updateBlock(blockId: string, data: {
  type?: BlockType;
  properties?: Record<string, unknown>;
  content?: unknown[];
  icon?: string;
  cover_url?: string;
  is_starred?: boolean;
  tags?: string[];
}) {
  return request<BlockResponse>(`/blocks/${blockId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export function deleteBlock(blockId: string) {
  return request<{ deleted: boolean }>(`/blocks/${blockId}`, { method: 'DELETE' });
}

export function restoreBlock(blockId: string) {
  return request<{ restored: boolean }>(`/blocks/${blockId}/restore`, { method: 'POST' });
}

export function moveBlock(blockId: string, data: {
  parent_id?: string | null;
  after_block_id?: string;
  before_block_id?: string;
}) {
  return request<BlockResponse>(`/blocks/${blockId}/move`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function uploadBlockFile(blockId: string, file: File) {
  return uploadFile(`/blocks/${blockId}/files`, file);
}

export function listBlockFiles(blockId: string) {
  return request<{ files: BlockFileResponse[] }>(`/blocks/${blockId}/files`);
}

// ==================== Triggers / Agents (Phase 3/4) ====================

export type TriggerKind = 'gmail' | 'calendar' | 'file' | 'cron' | 'collab' | 'chat_command';

export interface TriggerResponse {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  kind: TriggerKind;
  config: Record<string, unknown>;
  actions: Array<Record<string, unknown>>;
  is_enabled: boolean;
  last_fired_at: string | null;
  fire_count: number;
  created_at: string;
  updated_at: string;
}

export interface TriggerRunResponse {
  id: string;
  trigger_id: string;
  user_id: string;
  status: 'running' | 'succeeded' | 'failed' | 'cancelled';
  payload: Record<string, unknown>;
  result: Record<string, unknown>;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface AgentTrace {
  id: string;
  user_id: string;
  trigger_run_id: string | null;
  agent_name: string;
  event_type: string;
  content: Record<string, unknown>;
  parent_trace_id: string | null;
  created_at: string;
}

export function listTriggers(kind?: TriggerKind) {
  const q = kind ? `?kind=${kind}` : '';
  return request<{ triggers: TriggerResponse[] }>(`/triggers${q}`);
}

export function createTrigger(data: {
  name: string;
  description?: string;
  kind: TriggerKind;
  config?: Record<string, unknown>;
  actions?: Array<Record<string, unknown>>;
  is_enabled?: boolean;
}) {
  return request<TriggerResponse>('/triggers', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function updateTrigger(id: string, data: Partial<{
  name: string;
  description: string;
  config: Record<string, unknown>;
  actions: Array<Record<string, unknown>>;
  is_enabled: boolean;
}>) {
  return request<TriggerResponse>(`/triggers/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export function deleteTrigger(id: string) {
  return request<{ ok: boolean }>(`/triggers/${id}`, { method: 'DELETE' });
}

export function fireTrigger(id: string, payload: Record<string, unknown> = {}) {
  return request<TriggerRunResponse>(`/triggers/${id}/fire`, {
    method: 'POST',
    body: JSON.stringify({ payload }),
  });
}

export function listTriggerRuns(id: string, limit = 50) {
  return request<{ runs: TriggerRunResponse[] }>(`/triggers/${id}/runs?limit=${limit}`);
}

export function listAgentTraces(triggerRunId?: string, limit = 200) {
  const q = new URLSearchParams();
  if (triggerRunId) q.set('trigger_run_id', triggerRunId);
  q.set('limit', String(limit));
  return request<{ traces: AgentTrace[] }>(`/agents/traces?${q}`);
}
