/**
 * Auth Hook - Authentication utilities
 */

'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/auth-store';
import { api, ApiError, type LoginRequest, type RegisterRequest } from '@/lib/api-client';

export function useAuth() {
  const router = useRouter();
  const { user, isAuthenticated, isLoading, setUser, setLoading, logout: clearAuth } = useAuthStore();
  const [isLoggingOut, setIsLoggingOut] = useState(false);

  // Check authentication on mount
  useEffect(() => {
    const checkAuth = async () => {
      try {
        const userData = await api.auth.me();
        setUser(userData);
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          // Try to refresh token
          try {
            await api.auth.refresh();
            const userData = await api.auth.me();
            setUser(userData);
          } catch {
            setUser(null);
          }
        } else {
          setUser(null);
        }
      }
    };

    if (isLoading) {
      checkAuth();
    }
  }, [isLoading, setUser]);

  const login = useCallback(
    async (data: LoginRequest) => {
      setLoading(true);
      try {
        await api.auth.login(data);
        const userData = await api.auth.me();
        setUser(userData);
        router.push('/chat');
        return { success: true };
      } catch (error) {
        setLoading(false);
        if (error instanceof ApiError) {
          return { success: false, error: error.data };
        }
        throw error;
      }
    },
    [router, setUser, setLoading]
  );

  const register = useCallback(
    async (data: RegisterRequest) => {
      setLoading(true);
      try {
        await api.auth.register(data);
        // Auto-login after registration
        await api.auth.login({ email: data.email, password: data.password });
        const userData = await api.auth.me();
        setUser(userData);
        router.push('/chat');
        return { success: true };
      } catch (error) {
        setLoading(false);
        if (error instanceof ApiError) {
          return { success: false, error: error.data };
        }
        throw error;
      }
    },
    [router, setUser, setLoading]
  );

  const logout = useCallback(async () => {
    setIsLoggingOut(true);
    try {
      await api.auth.logout();
    } catch {
      // Ignore logout errors
    } finally {
      clearAuth();
      setIsLoggingOut(false);
      router.push('/login');
    }
  }, [clearAuth, router]);

  return {
    user,
    isAuthenticated,
    isLoading,
    isLoggingOut,
    login,
    register,
    logout,
  };
}
