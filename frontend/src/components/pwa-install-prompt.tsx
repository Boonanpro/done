'use client';

import { useState, useEffect, useCallback } from 'react';
import { X, Download, Share, MoreVertical, Bell, BellOff, MessageSquare } from 'lucide-react';
import { Button } from '@/components/ui/button';

const DISMISSED_KEY = 'pwa-install-dismissed-v4';

// Fake notification preview component
function NotificationPreview({ enabled }: { enabled: boolean }) {
  return (
    <div className={`rounded-xl p-3 ${enabled ? 'bg-muted/60 border border-border' : 'bg-muted/20 border border-dashed border-muted-foreground/20'}`}>
      <div className="flex items-center gap-2 mb-2">
        {enabled ? (
          <Bell className="h-3.5 w-3.5 text-green-400" />
        ) : (
          <BellOff className="h-3.5 w-3.5 text-muted-foreground/40" />
        )}
        <span className={`text-[10px] font-medium ${enabled ? 'text-green-400' : 'text-muted-foreground/40'}`}>
          {enabled ? 'インストール後' : '今の状態'}
        </span>
      </div>
      {enabled ? (
        <div className="flex items-start gap-2.5 bg-background/80 rounded-lg p-2.5 shadow-sm">
          <div className="h-8 w-8 rounded-lg bg-primary/20 flex items-center justify-center shrink-0">
            <MessageSquare className="h-4 w-4 text-primary" />
          </div>
          <div className="min-w-0">
            <p className="text-xs font-semibold">Done</p>
            <p className="text-[11px] text-muted-foreground truncate">たく: 来週の土曜なら空いてるよ</p>
          </div>
          <span className="text-[10px] text-muted-foreground shrink-0">今</span>
        </div>
      ) : (
        <div className="flex items-center justify-center py-3">
          <p className="text-xs text-muted-foreground/40">通知は届きません</p>
        </div>
      )}
    </div>
  );
}

export function PWAInstallPrompt() {
  const [show, setShow] = useState(false);
  const [step, setStep] = useState(0);
  const [platform, setPlatform] = useState<'ios' | 'android' | 'desktop'>('desktop');
  const [deferredPrompt, setDeferredPrompt] = useState<any>(null);

  useEffect(() => {
    if (window.matchMedia('(display-mode: standalone)').matches) return;
    const dismissed = localStorage.getItem(DISMISSED_KEY);
    if (dismissed) return; // 1回閉じたら再表示しない

    const ua = navigator.userAgent;
    const ios = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    const android = /Android/.test(ua);

    // PC（デスクトップ）では表示しない — スマホのみ
    if (!ios && !android) return;

    setPlatform(ios ? 'ios' : 'android');

    const handler = (e: Event) => {
      e.preventDefault();
      setDeferredPrompt(e);
    };
    window.addEventListener('beforeinstallprompt', handler);

    const timer = setTimeout(() => setShow(true), 1000);

    return () => {
      window.removeEventListener('beforeinstallprompt', handler);
      clearTimeout(timer);
    };
  }, []);

  const handleInstall = useCallback(async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    const result = await deferredPrompt.userChoice;
    if (result.outcome === 'accepted') setShow(false);
    setDeferredPrompt(null);
  }, [deferredPrompt]);

  const handleDismiss = () => {
    setShow(false);
    localStorage.setItem(DISMISSED_KEY, Date.now().toString());
  };

  if (!show) return null;

  // Step-by-step guide
  if (step === 1) {
    return (
      <div className="fixed inset-0 z-50 bg-background/90 backdrop-blur-sm flex items-center justify-center p-4">
        <div className="bg-card border rounded-2xl shadow-xl p-5 w-full max-w-sm space-y-4 relative max-h-[90vh] overflow-y-auto">
          <button onClick={handleDismiss} className="absolute top-3 right-3 text-muted-foreground hover:text-foreground">
            <X className="h-5 w-5" />
          </button>

          <h3 className="font-bold text-base">アプリをインストール</h3>

          {/* Before / After comparison */}
          <div className="grid grid-cols-2 gap-2">
            <NotificationPreview enabled={false} />
            <NotificationPreview enabled={true} />
          </div>

          <p className="text-xs text-muted-foreground">ブラウザのままでも使えますが、新着メッセージに気づけません。ホーム画面に追加すると、LINEのように通知が届くようになります。</p>

          {platform === 'ios' ? (
            <div className="space-y-3">
              <div className="flex items-center gap-3 bg-muted/50 rounded-xl p-3">
                <div className="h-9 w-9 rounded-full bg-blue-500/20 flex items-center justify-center text-lg font-bold text-blue-400 shrink-0">1</div>
                <div>
                  <p className="text-sm font-medium">画面下の共有ボタンをタップ</p>
                  <div className="flex items-center gap-1 mt-0.5">
                    <Share className="h-4 w-4 text-blue-400" />
                    <span className="text-xs text-muted-foreground">四角に上矢印のアイコン</span>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-3 bg-muted/50 rounded-xl p-3">
                <div className="h-9 w-9 rounded-full bg-blue-500/20 flex items-center justify-center text-lg font-bold text-blue-400 shrink-0">2</div>
                <div>
                  <p className="text-sm font-medium">下にスクロールして</p>
                  <p className="text-sm font-medium">「ホーム画面に追加」をタップ</p>
                  <span className="text-xs text-muted-foreground">＋マークが目印です</span>
                </div>
              </div>

              <div className="flex items-center gap-3 bg-muted/50 rounded-xl p-3">
                <div className="h-9 w-9 rounded-full bg-green-500/20 flex items-center justify-center text-lg font-bold text-green-400 shrink-0">3</div>
                <div>
                  <p className="text-sm font-medium">右上の「追加」をタップ</p>
                  <span className="text-xs text-muted-foreground">ホーム画面にアイコンが追加されます</span>
                </div>
              </div>
            </div>
          ) : platform === 'android' ? (
            <div className="space-y-3">
              {deferredPrompt ? (
                <div className="flex items-center gap-3 bg-muted/50 rounded-xl p-3">
                  <div className="h-9 w-9 rounded-full bg-green-500/20 flex items-center justify-center shrink-0">
                    <Download className="h-5 w-5 text-green-400" />
                  </div>
                  <div className="flex-1">
                    <p className="text-sm font-medium">下のボタンを押すだけ！</p>
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-3 bg-muted/50 rounded-xl p-3">
                    <div className="h-9 w-9 rounded-full bg-blue-500/20 flex items-center justify-center text-lg font-bold text-blue-400 shrink-0">1</div>
                    <div>
                      <p className="text-sm font-medium">右上の「⋮」メニューをタップ</p>
                      <div className="flex items-center gap-1 mt-0.5">
                        <MoreVertical className="h-4 w-4 text-blue-400" />
                        <span className="text-xs text-muted-foreground">3つの点のアイコン</span>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 bg-muted/50 rounded-xl p-3">
                    <div className="h-9 w-9 rounded-full bg-blue-500/20 flex items-center justify-center text-lg font-bold text-blue-400 shrink-0">2</div>
                    <div>
                      <p className="text-sm font-medium">「アプリをインストール」</p>
                      <p className="text-sm font-medium">または「ホーム画面に追加」</p>
                    </div>
                  </div>
                </>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-3 bg-muted/50 rounded-xl p-3">
              <Download className="h-5 w-5 text-blue-400 shrink-0" />
              <p className="text-sm">ブラウザのアドレスバー右端のインストールアイコンをクリック</p>
            </div>
          )}

          {deferredPrompt && (
            <Button className="w-full" onClick={handleInstall}>
              <Download className="h-4 w-4 mr-2" />
              今すぐインストール
            </Button>
          )}

          <button onClick={handleDismiss} className="w-full text-center text-xs text-muted-foreground hover:text-foreground py-1">
            あとで
          </button>
        </div>
      </div>
    );
  }

  // Initial banner
  return (
    <div className="fixed bottom-4 left-4 right-4 z-50 animate-in slide-in-from-bottom duration-300">
      <div className="bg-card border rounded-xl shadow-lg p-3 max-w-md mx-auto space-y-2">
        <div className="flex items-start gap-3">
          <div className="h-10 w-10 rounded-xl bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
            <Bell className="h-5 w-5 text-primary" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium">メッセージの通知を受け取る</p>
            <p className="text-xs text-muted-foreground">ブラウザのままでも使えますが、新着に気づけません。インストールするとLINEのように通知が届きます</p>
          </div>
          <button onClick={handleDismiss} className="text-muted-foreground shrink-0 p-1">
            <X className="h-4 w-4" />
          </button>
        </div>
        {/* Notification preview */}
        <div className="grid grid-cols-2 gap-2">
          <NotificationPreview enabled={false} />
          <NotificationPreview enabled={true} />
        </div>
        <div className="flex gap-2">
          {deferredPrompt ? (
            <Button className="flex-1" size="sm" onClick={handleInstall}>
              <Download className="h-4 w-4 mr-1" />
              インストール
            </Button>
          ) : (
            <Button className="flex-1" size="sm" onClick={() => setStep(1)}>
              やり方を見る
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
