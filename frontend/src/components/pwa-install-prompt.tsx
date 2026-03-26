'use client';

import { useState, useEffect, useCallback } from 'react';
import { X, Download, Share, Smartphone } from 'lucide-react';
import { Button } from '@/components/ui/button';

const DISMISSED_KEY = 'pwa-install-dismissed';

export function PWAInstallPrompt() {
  const [show, setShow] = useState(false);
  const [platform, setPlatform] = useState<'ios' | 'android' | 'desktop'>('desktop');
  const [deferredPrompt, setDeferredPrompt] = useState<any>(null);

  useEffect(() => {
    // Don't show if already installed as PWA
    if (window.matchMedia('(display-mode: standalone)').matches) return;
    // Don't show if dismissed recently (24h)
    const dismissed = localStorage.getItem(DISMISSED_KEY);
    if (dismissed && Date.now() - parseInt(dismissed) < 24 * 60 * 60 * 1000) return;

    const ua = navigator.userAgent;
    const ios = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    const android = /Android/.test(ua);

    if (ios) {
      setPlatform('ios');
    } else if (android) {
      setPlatform('android');
    } else {
      setPlatform('desktop');
    }

    // Listen for beforeinstallprompt (Chrome/Edge on Android & desktop)
    const handler = (e: Event) => {
      e.preventDefault();
      setDeferredPrompt(e);
      setShow(true);
    };
    window.addEventListener('beforeinstallprompt', handler);

    // Show after delay for iOS and as fallback for others
    const timer = setTimeout(() => setShow(true), 3000);

    return () => {
      window.removeEventListener('beforeinstallprompt', handler);
      clearTimeout(timer);
    };
  }, []);

  const handleInstall = useCallback(async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    const result = await deferredPrompt.userChoice;
    if (result.outcome === 'accepted') {
      setShow(false);
    }
    setDeferredPrompt(null);
  }, [deferredPrompt]);

  const handleDismiss = () => {
    setShow(false);
    localStorage.setItem(DISMISSED_KEY, Date.now().toString());
  };

  if (!show) return null;

  return (
    <div className="fixed bottom-20 left-4 right-4 z-50 animate-in slide-in-from-bottom duration-300">
      <div className="bg-card border rounded-xl shadow-lg p-4 max-w-md mx-auto">
        <div className="flex items-start gap-3">
          <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
            <Smartphone className="h-5 w-5 text-primary" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="font-semibold text-sm">アプリとしてインストール</h3>
            {platform === 'ios' ? (
              <div className="text-xs text-muted-foreground mt-1 space-y-1">
                <p>通知を受け取るにはホーム画面に追加してください:</p>
                <div className="flex items-center gap-1.5 bg-muted/50 rounded-md px-2 py-1.5">
                  <span>1.</span>
                  <Share className="h-3.5 w-3.5" />
                  <span>画面下の共有ボタンをタップ</span>
                </div>
                <div className="flex items-center gap-1.5 bg-muted/50 rounded-md px-2 py-1.5">
                  <span>2.</span>
                  <span>「ホーム画面に追加」をタップ</span>
                </div>
              </div>
            ) : deferredPrompt ? (
              <p className="text-xs text-muted-foreground mt-1">
                アプリとしてインストールすると、通知を受け取れるようになります
              </p>
            ) : (
              <div className="text-xs text-muted-foreground mt-1 space-y-1">
                <p>アプリとしてインストールできます:</p>
                <div className="flex items-center gap-1.5 bg-muted/50 rounded-md px-2 py-1.5">
                  <span>ブラウザのメニュー →「アプリをインストール」</span>
                </div>
              </div>
            )}
          </div>
          <button onClick={handleDismiss} className="text-muted-foreground hover:text-foreground shrink-0">
            <X className="h-4 w-4" />
          </button>
        </div>
        {deferredPrompt && (
          <Button className="w-full mt-3" size="sm" onClick={handleInstall}>
            <Download className="h-4 w-4 mr-1.5" />
            インストール
          </Button>
        )}
      </div>
    </div>
  );
}
