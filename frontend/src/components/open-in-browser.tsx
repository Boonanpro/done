'use client';

import { useState, useEffect } from 'react';
import { ExternalLink, X } from 'lucide-react';
import { Button } from '@/components/ui/button';

function isInAppBrowser(): boolean {
  if (typeof window === 'undefined') return false;
  const ua = navigator.userAgent;
  // LINE, Facebook, Instagram, Twitter, etc.
  return /Line\/|FBAV|FBAN|Instagram|Twitter|Snapchat|WeChat|MicroMessenger/i.test(ua);
}

function isIOS(): boolean {
  if (typeof window === 'undefined') return false;
  return /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
}

export function OpenInBrowserPrompt() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (isInAppBrowser()) {
      setShow(true);
    }
  }, []);

  if (!show) return null;

  const currentUrl = typeof window !== 'undefined' ? window.location.href : '';
  const ios = isIOS();

  const handleOpenInBrowser = () => {
    if (ios) {
      // iOS: Safari で開く intent URL は無いので、コピーして案内
      try {
        const textarea = document.createElement('textarea');
        textarea.value = currentUrl;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      } catch {}
    } else {
      // Android: intent URL で Chrome を開く
      window.location.href = `intent://${currentUrl.replace(/^https?:\/\//, '')}#Intent;scheme=https;package=com.android.chrome;end`;
      return;
    }
  };

  return (
    <div className="fixed inset-0 z-[100] bg-background flex flex-col items-center justify-center p-6">
      <div className="w-full max-w-sm space-y-5 text-center">
        <div className="h-16 w-16 rounded-2xl bg-primary/10 flex items-center justify-center mx-auto">
          <ExternalLink className="h-8 w-8 text-primary" />
        </div>

        <div>
          <h2 className="text-lg font-bold">ブラウザで開いてください</h2>
          <p className="text-sm text-muted-foreground mt-2">
            このアプリはLINE内のブラウザでは正常に動作しません。
            {ios ? 'Safari' : 'Chrome'}で開いてください。
          </p>
        </div>

        {ios ? (
          <div className="space-y-3 text-left">
            <div className="flex items-center gap-3 bg-muted/50 rounded-xl p-3">
              <div className="h-8 w-8 rounded-full bg-blue-500/20 flex items-center justify-center text-sm font-bold text-blue-400 shrink-0">1</div>
              <p className="text-sm">右下の「<b>⋯</b>」メニューをタップ</p>
            </div>
            <div className="flex items-center gap-3 bg-muted/50 rounded-xl p-3">
              <div className="h-8 w-8 rounded-full bg-blue-500/20 flex items-center justify-center text-sm font-bold text-blue-400 shrink-0">2</div>
              <p className="text-sm">「<b>Safariで開く</b>」をタップ</p>
            </div>
          </div>
        ) : (
          <Button className="w-full" onClick={handleOpenInBrowser}>
            <ExternalLink className="h-4 w-4 mr-2" />
            Chromeで開く
          </Button>
        )}

        <button
          onClick={() => setShow(false)}
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          このまま続ける
        </button>
      </div>
    </div>
  );
}
