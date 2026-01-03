/**
 * API Client for Done Backend
 * Handles all HTTP requests to the backend API
 */

// API Base URL - use environment variable or default to localhost
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

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
}

export interface MessagesListResponse {
  messages: MessageResponse[];
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
      request<MessageResponse>('/chat/dan/messages', {
        method: 'POST',
        body: JSON.stringify({ content }),
      }),

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
  },

  // Invite endpoints
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
};

