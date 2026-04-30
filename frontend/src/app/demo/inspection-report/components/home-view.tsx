"use client";

import { Building2, Cpu, Wrench, FileText, Sparkles } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useInspectionStore } from "../store";

type View =
  | { kind: "home" }
  | { kind: "clients" }
  | { kind: "client_detail"; id: string }
  | { kind: "equipments" }
  | { kind: "instruments" }
  | { kind: "generate" }
  | { kind: "confirm" }
  | { kind: "settings" };

export function HomeView({ onNavigate }: { onNavigate: (v: View) => void }) {
  const clients = useInspectionStore((s) => s.clients);
  const equipments = useInspectionStore((s) => s.equipments);
  const instruments = useInspectionStore((s) => s.instruments);

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-semibold mb-2">点検報告書ジェネレーター</h2>
        <p className="text-muted-foreground">
          クライアントを選んでボタンを押すと、検査項目の数値が自動で入った報告書ができます。
        </p>
      </div>

      {/* メイン CTA */}
      <Card className="border-primary/30 bg-primary/5">
        <CardContent className="py-8 flex items-center gap-6">
          <div className="h-16 w-16 rounded-full bg-primary/15 flex items-center justify-center">
            <Sparkles className="h-7 w-7 text-primary" />
          </div>
          <div className="flex-1">
            <h3 className="text-lg font-semibold mb-1">今日の点検報告書を作る</h3>
            <p className="text-sm text-muted-foreground">
              クライアントを選んでクリック1回で報告書を生成。確認画面で値を編集できます。
            </p>
          </div>
          <Button size="lg" onClick={() => onNavigate({ kind: "generate" })}>
            報告書を作る
          </Button>
        </CardContent>
      </Card>

      {/* 統計 */}
      <div className="grid grid-cols-3 gap-4">
        <Card className="cursor-pointer hover:bg-secondary/30 transition" onClick={() => onNavigate({ kind: "clients" })}>
          <CardContent className="py-6">
            <div className="flex items-center gap-3 mb-2">
              <Building2 className="h-5 w-5 text-muted-foreground" />
              <span className="text-sm text-muted-foreground">クライアント</span>
            </div>
            <p className="text-3xl font-semibold">{clients.length}</p>
            <p className="text-xs text-muted-foreground mt-1">件登録</p>
          </CardContent>
        </Card>
        <Card className="cursor-pointer hover:bg-secondary/30 transition" onClick={() => onNavigate({ kind: "equipments" })}>
          <CardContent className="py-6">
            <div className="flex items-center gap-3 mb-2">
              <Cpu className="h-5 w-5 text-muted-foreground" />
              <span className="text-sm text-muted-foreground">機器マスタ</span>
            </div>
            <p className="text-3xl font-semibold">{equipments.length}</p>
            <p className="text-xs text-muted-foreground mt-1">型式登録</p>
          </CardContent>
        </Card>
        <Card className="cursor-pointer hover:bg-secondary/30 transition" onClick={() => onNavigate({ kind: "instruments" })}>
          <CardContent className="py-6">
            <div className="flex items-center gap-3 mb-2">
              <Wrench className="h-5 w-5 text-muted-foreground" />
              <span className="text-sm text-muted-foreground">計測器</span>
            </div>
            <p className="text-3xl font-semibold">{instruments.length}</p>
            <p className="text-xs text-muted-foreground mt-1">機材登録</p>
          </CardContent>
        </Card>
      </div>

      {/* 使い方 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">使い方</CardTitle>
        </CardHeader>
        <CardContent>
          <ol className="space-y-3 text-sm">
            <li className="flex gap-3">
              <span className="h-6 w-6 rounded-full bg-secondary flex items-center justify-center text-xs flex-shrink-0">1</span>
              <span><b>クライアント</b> でクライアント情報・設備構成・機器を登録します（最初は島津組がサンプルとして入っています）</span>
            </li>
            <li className="flex gap-3">
              <span className="h-6 w-6 rounded-full bg-secondary flex items-center justify-center text-xs flex-shrink-0">2</span>
              <span><b>機器マスタ</b> で継電器・PASなどの型式情報を登録します（複数のクライアントで使い回せます）</span>
            </li>
            <li className="flex gap-3">
              <span className="h-6 w-6 rounded-full bg-secondary flex items-center justify-center text-xs flex-shrink-0">3</span>
              <span><b>報告書を作る</b> でクライアントを選んで、ボタンを押すと数値・判定が自動で埋まります</span>
            </li>
            <li className="flex gap-3">
              <span className="h-6 w-6 rounded-full bg-secondary flex items-center justify-center text-xs flex-shrink-0">4</span>
              <span>確認画面で値や判定を編集して、Wordをダウンロード（必要なら印刷からPDF保存）</span>
            </li>
          </ol>
        </CardContent>
      </Card>
    </div>
  );
}
