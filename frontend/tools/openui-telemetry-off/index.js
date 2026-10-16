// @openuidev/lang-core の導入時の計測（postinstall が PostHog に送る匿名の導入情報）を止める。
// lang-core は環境変数 OPENUI_TELEMETRY_DISABLED=1（か DO_NOT_TRACK=1）だけを見る。npm には
// 「依存の postinstall にだけ環境変数を渡す」設定が無いので、frontend/.npmrc の node-options で
// npm が起こす全ての node（スクリプト・依存の postinstall）にこのファイルを --require させ、ここで立てる。
// 本番の `npm install` / `npm ci` でも同じ .npmrc が読まれるので、手元で環境変数を付け忘れても送らない。
process.env.OPENUI_TELEMETRY_DISABLED = '1';
