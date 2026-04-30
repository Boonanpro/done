"use client";

import { useState } from "react";
import { FolderOpen, RotateCw } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useInspectionStore } from "../store";

export function SettingsView() {
  const saveDirHandle = useInspectionStore((s) => s.saveDirHandle);
  const saveDirName = useInspectionStore((s) => s.saveDirName);
  const setSaveDir = useInspectionStore((s) => s.setSaveDir);
  const reset = useInspectionStore((s) => s.reset);

  const [error, setError] = useState<string | null>(null);

  const pickDir = async () => {
    setError(null);
    if (typeof window === "undefined" || !("showDirectoryPicker" in window)) {
      setError("お使いのブラウザは保存先フォルダ選択に対応していません（Chrome/Edge推奨）");
      return;
    }
    try {
      // @ts-expect-error - File System Access API
      const handle: FileSystemDirectoryHandle = await window.showDirectoryPicker({ mode: "readwrite" });
      setSaveDir(handle, handle.name);
    } catch (e) {
      // ユーザーキャンセル時は何もしない
      if ((e as Error).name !== "AbortError") {
        setError(`エラー：${(e as Error).message}`);
      }
    }
  };

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h2 className="text-2xl font-semibold mb-1">設定</h2>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">報告書の保存先フォルダ</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            選んだフォルダにWord/PDFが自動で保存されます。
            初回はChromeに「許可しますか？」と聞かれます。
          </p>
          <div className="flex items-center gap-3">
            <Button variant="outline" onClick={pickDir}>
              <FolderOpen className="h-4 w-4 mr-2" />
              保存先フォルダを選ぶ
            </Button>
            {saveDirHandle ? (
              <span className="text-sm text-muted-foreground">
                現在：<b>{saveDirName}</b>（このセッション中のみ）
              </span>
            ) : saveDirName ? (
              <span className="text-sm text-muted-foreground">
                前回：{saveDirName}（再選択が必要）
              </span>
            ) : (
              <span className="text-sm text-muted-foreground">未設定</span>
            )}
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <p className="text-xs text-muted-foreground">
            ※ ブラウザのセキュリティ仕様により、ブラウザを閉じると次回起動時に再選択が必要です。
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">PDF出力について</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            このプロトタイプ版はWord出力に対応しています。
            PDFが必要な場合は、Wordを開いて「ファイル → 印刷 → Microsoft Print to PDF」で保存できます。
            完全自動のPDF出力は次のバージョンで対応予定です。
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">データのリセット</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            登録したクライアント・機器・計測器を初期状態に戻します（島津組のサンプルだけが残ります）。
          </p>
          <Button
            variant="outline"
            onClick={() => {
              if (confirm("本当にすべてのデータを初期化しますか？")) reset();
            }}
          >
            <RotateCw className="h-4 w-4 mr-2" />初期化する
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
