/**
 * @openuidev/react-lang は開発用の画面（next dev）で読み込まれると、右下に点検用の小窓
 * 「OpenUI Inspect」（犬のマーク）を自動で付け、その中身を CDN（jsDelivr）から取ってくる。
 * 成果物タブ（/preview/<slug>）は開発用サーバー（3001）から出ているので、本人の画面に出ていた（2026-10-19）。
 *
 * react-lang は読み込まれた時に globalThis[Symbol.for('openui.devtools.autoMount')] を見て、
 * 立っていれば付けない。だからこのファイルは react-lang より先に import する（chat-shapes.tsx の先頭）。
 */
(globalThis as Record<symbol, unknown>)[Symbol.for('openui.devtools.autoMount')] = true;

export {};
