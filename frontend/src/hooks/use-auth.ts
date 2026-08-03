/**
 * Auth Hook - Authentication utilities
 */

'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/auth-store';
import { api, ApiError, OWNER_USER_ID, setImmediateToken, setStoredToken, type LoginRequest, type RegisterRequest } from '@/lib/api-client';

/** Collect all collab guest tokens from localStorage */
function collectGuestTokens(): string[] {
  if (typeof window === 'undefined') return [];
  const tokens: string[] = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key?.startsWith('collab-guest-token-')) {
      const val = localStorage.getItem(key);
      if (val) tokens.push(val);
    }
  }
  return tokens;
}

export function useAuth() {
  const router = useRouter();
  const { user, token, isAuthenticated, isLoading, setUser, setToken, setLoading, logout: clearAuth } = useAuthStore();
  const [isLoggingOut, setIsLoggingOut] = useState(false);

  // Check authentication on mount
  useEffect(() => {
    const checkAuth = async () => {
      // If we have a stored token, try to use it
      if (token) {
        try {
          const userData = await api.auth.me();
          setUser(userData);
          return;
        } catch (error) {
          if (error instanceof ApiError && error.status === 401) {
            // Token expired, try to refresh
            try {
              const refreshResponse = await api.auth.refresh();
              setToken(refreshResponse.access_token);
              const userData = await api.auth.me();
              setUser(userData);
              return;
            } catch {
              // Refresh failed, clear auth
              setUser(null);
              setToken(null);
            }
          } else {
            setUser(null);
            setToken(null);
          }
        }
      } else {
        setUser(null);
        setLoading(false);
      }
    };

    if (isLoading) {
      checkAuth();
    }
  }, [isLoading, setUser, setToken, setLoading, token]);

  const login = useCallback(
    async (data: LoginRequest) => {
      setLoading(true);
      try {
        const guestTokens = collectGuestTokens();
        const tokenResponse = await api.auth.login({ ...data, guest_tokens: guestTokens.length > 0 ? guestTokens : undefined });
        const newToken = tokenResponse.access_token;
        // Save token to localStorage and memory
        setStoredToken(newToken);
        setImmediateToken(newToken);
        setToken(newToken);
        const userData = await api.auth.me();
        setUser(userData);
        // Redirect based on role: owner → /chat, others → /collab
        window.location.href = userData.id === OWNER_USER_ID ? '/chat' : '/collab';
        return { success: true };
      } catch (error) {
        setLoading(false);
        setImmediateToken(null);
        setStoredToken(null);
        if (error instanceof ApiError) {
          // status を返して呼び出し側が「認証情報が違う(401)」と「サーバーに
          // 届かない(502/503等)」を表示し分けられるようにする。従来は全部
          // まとめて「認証情報が正しくない」と誤表示していた。
          return { success: false, error: error.data, status: error.status };
        }
        throw error;
      }
    },
    [setUser, setToken, setLoading]
  );

  const register = useCallback(
    async (data: RegisterRequest) => {
      setLoading(true);
      try {
        const guestTokens = collectGuestTokens();
        await api.auth.register({ ...data, guest_tokens: guestTokens.length > 0 ? guestTokens : undefined });
        // Auto-login after registration
        const tokenResponse = await api.auth.login({ email: data.email, password: data.password, guest_tokens: guestTokens.length > 0 ? guestTokens : undefined });
        const newToken = tokenResponse.access_token;
        // Save token to localStorage and memory
        setStoredToken(newToken);
        setImmediateToken(newToken);
        setToken(newToken);
        const userData = await api.auth.me();
        setUser(userData);
        window.location.href = userData.id === OWNER_USER_ID ? '/chat' : '/collab';
        return { success: true };
      } catch (error) {
        setLoading(false);
        setImmediateToken(null);
        setStoredToken(null);
        if (error instanceof ApiError) {
          return { success: false, error: error.data };
        }
        throw error;
      }
    },
    [setUser, setToken, setLoading]
  );

  const logout = useCallback(async () => {
    setIsLoggingOut(true);
    // Clear auth state locally
    setStoredToken(null);
    setImmediateToken(null);
    clearAuth();
    setIsLoggingOut(false);
    router.push('/login');
  }, [clearAuth, router]);

  return {
    user,
    token,
    isAuthenticated,
    isLoading,
    isLoggingOut,
    login,
    register,
    logout,
  };
}
