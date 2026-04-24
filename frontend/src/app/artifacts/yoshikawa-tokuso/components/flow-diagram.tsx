import { FileText, Send, MessageCircle } from "lucide-react";

const STEPS = [
  {
    num: "01",
    icon: FileText,
    title: "情報を準備",
    body: "車検証の写真／破損箇所の画像・動画／型式・車台番号をご用意ください。フォーム上で準備できる項目を案内します。",
  },
  {
    num: "02",
    icon: Send,
    title: "フォーム送信",
    body: "電話で毎回ヒアリングしていた内容をオンラインで一度にお送りいただけます。受付番号が即時発行されます。",
  },
  {
    num: "03",
    icon: MessageCircle,
    title: "折り返しご連絡",
    body: "受付後1営業日以内に担当者より折り返します。部品手配・概算見積・入庫日程までをワンストップでお伝えします。",
  },
];

export function FlowDiagram() {
  return (
    <div className="relative">
      <div className="hidden md:block absolute top-12 left-[8%] right-[8%] h-px bg-gradient-to-r from-[var(--yk-navy)]/20 via-[var(--yk-navy)]/60 to-[var(--yk-navy)]/20" />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-8 md:gap-6 relative">
        {STEPS.map((s) => {
          const Icon = s.icon;
          return (
            <div
              key={s.num}
              className="relative bg-white rounded-sm border border-border p-7 space-y-4"
            >
              <div className="flex items-center gap-4">
                <span className="font-eyebrow text-sm text-[var(--yk-gold-dark)]">
                  STEP {s.num}
                </span>
                <div className="h-px flex-1 bg-border" />
              </div>
              <div className="flex items-start gap-4">
                <div className="shrink-0 h-12 w-12 rounded-sm bg-[var(--yk-navy)] text-white flex items-center justify-center">
                  <Icon className="h-6 w-6" />
                </div>
                <div className="space-y-2">
                  <h3 className="font-headline text-xl font-bold text-[var(--yk-navy)]">
                    {s.title}
                  </h3>
                  <p className="text-sm text-[var(--yk-steel)] leading-relaxed">
                    {s.body}
                  </p>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
