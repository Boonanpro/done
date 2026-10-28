'use client';

import { useEffect, useState, useCallback, useRef } from 'react';

const API_URL = '';

export function usePushNotification(roomId: string, senderType: string, guestToken?: string | null) {
  const [permission, setPermission] = useState<NotificationPermission>('default');
  const [subscribed, setSubscribed] = useState(false);
  const inFlight = useRef(false);
  const attemptedRoom = useRef('');
  const [error, setError] = useState('');

  useEffect(() => { setSubscribed(false); setError(''); }, [roomId, senderType]);

  useEffect(() => {
    if (typeof window !== 'undefined' && 'Notification' in window) {
      setPermission(Notification.permission);
    }
  }, []);

  const subscribe = useCallback(async () => {
    if (inFlight.current || !roomId) return false;
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
      console.warn('Push not supported');
      return false;
    }

    inFlight.current = true;
    setError('');
    try {
      // Request permission
      const perm = await Notification.requestPermission();
      setPermission(perm);
      if (perm !== 'granted') return false;

      // Register service worker
      const reg = await navigator.serviceWorker.register('/sw.js');
      await Promise.race([
        navigator.serviceWorker.ready,
        new Promise((_, reject) => setTimeout(() => reject(new Error('通知の準備が時間内に終わりませんでした')), 20_000)),
      ]);

      // Get VAPID key
      const vapidRes = await fetch(`${API_URL}/api/v1/push/vapid-key`);
      if (!vapidRes.ok) throw new Error('通知の準備ができませんでした');
      const { publicKey } = await vapidRes.json();
      if (!publicKey) throw new Error('通知の準備ができませんでした');

      // Convert VAPID key
      const applicationServerKey = urlBase64ToUint8Array(publicKey) as any;

      const existingSubscription = await reg.pushManager.getSubscription();
      // Subscribe
      const subscription = existingSubscription || await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey,
      });

      // Save to backend
      const ownerToken = guestToken ? null : localStorage.getItem('done-token');
      const saved = await fetch(`${API_URL}/api/v1/push/subscribe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(guestToken ? { 'X-Guest-Token': guestToken } : {}),
          ...(ownerToken ? { Authorization: `Bearer ${ownerToken}` } : {}) },
        credentials: 'include',
        body: JSON.stringify({
          room_id: roomId,
          sender_type: senderType,
          subscription: subscription.toJSON(),
          // 通知タップで開く先。ゲストは今開いている本人専用URL（/collab/join/<token>）。
          // オーナーは部屋URL。これが無いとゲストがオーナー用URLに飛ばされてログイン画面になる
          landing_url: senderType === 'guest' ? window.location.pathname : `/collab/${roomId}`,
        }),
      });
      if (!saved.ok) throw new Error('通知先を保存できませんでした');

      setSubscribed(true);
      return true;
    } catch (e) {
      console.error('Push subscription error:', e);
      setError(e instanceof Error ? e.message : '通知を登録できませんでした');
      return false;
    } finally {
      inFlight.current = false;
    }
  }, [roomId, senderType, guestToken]);

  const sendTest = useCallback(async (): Promise<{ ok: boolean; message?: string }> => {
    const token = localStorage.getItem('done-token');

    try {
      const headers: HeadersInit = {};
      if (token) headers.Authorization = `Bearer ${token}`;
      const res = await fetch(`${API_URL}/api/v1/push/test`, {
        method: 'POST',
        headers,
        credentials: 'include',
      });
      if (res.ok) return { ok: true };
      const data = await res.json().catch(() => null);
      const detail = data?.detail;
      if (detail?.attempted === 0) {
        return { ok: false, message: 'この端末の通知購読がまだ保存されていません' };
      }
      if (detail?.failed) {
        return { ok: false, message: '通知サービスへの送信に失敗しました' };
      }
      return { ok: false };
    } catch (e) {
      console.error('Push test error:', e);
      return { ok: false };
    }
  }, []);

  // Auto-subscribe if permission already granted
  useEffect(() => {
    const key = `${roomId}:${senderType}`;
    if (permission === 'granted' && roomId && senderType && attemptedRoom.current !== key) {
      attemptedRoom.current = key;
      void subscribe();
    }
  }, [permission, roomId, senderType, subscribed, subscribe]);

  return { permission, subscribed, subscribe, sendTest, error };
}

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}
