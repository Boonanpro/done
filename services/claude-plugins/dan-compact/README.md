# dan-compact

ダン専用の薄い Claude Code プラグイン（function hooks）。会話が長くなった時の
Claude Code の要約（compact）を、「要らなくなった道具の呼び出しと結果だけを捨てた元の会話」
で置き換える。発言の文章は一字も変えない。判定は TypeSafe の Jev
（ライブラリ [fast-jev-compaction](https://github.com/tamaratran/fast-jev-compaction) 0.4.1）。

上流の `hooks/fast-jev.ts` との違い（ダン用に足したもの）:

- 設定は環境変数（ダンの cli_runner が起動ごとに渡す。`userConfig` や settings.json は使わない）
- 月の費用の上限と台帳 `~/.dan/workspace/memory/.compact_jev_ledger.json`（`{month, yen, runs, last}`）
- 費用は Jev が返す `usage.input_tokens`（無ければライブラリの推定）× 単価で積む
- 失敗（鍵なし・Jev エラー・縮みが足りない・文脈が収まらない）は必ず組み込み要約へ戻す。鍵はログにも台帳にも出さない
- 結果を 1 行で `$.ui.log`（Claude Code のログ）に出し、台帳の `last` にも残す

## 置き場所と読み込み

`claude --plugin-dir <このフォルダの絶対パス>` で起動ごとに渡す（`claude plugin install` はしない）。
`CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` が必要。`app/agent/cli_runner.py` の `_dan_compact_launch()` が、
`DAN_COMPACT_JEV` が "0" でなく、資格情報サービスから TypeSafe の鍵が取れた時だけ両方を付ける。

```
.claude-plugin/plugin.json   マニフェスト
hooks/hooks.json             modules: ./dan-compact.mjs
hooks/dan-compact.mjs        register(on): $ を core.mjs に配線する（session.compact / turn.complete）
hooks/core.mjs               エンジン無しの本体（設定・台帳・費用・フォールバック）
test/core.test.mjs           node --test（偽の Jev・メモリ上の台帳）
```

依存の `node_modules/` は `npm install` で入れる（コミットしない）。

## 環境変数

| 名前 | 既定 | 意味 |
|---|---|---|
| `TYPESAFE_API_KEY` | (無し) | Jev の鍵。無ければ組み込み要約 |
| `TYPESAFE_MODEL` / `TYPESAFE_BASE_URL` | `jev-latest` / 公式 | モデル名・接続先 |
| `DAN_COMPACT_KEEP_THRESHOLD` | `0.3` | 残す確率の下限（結果はこれ以上で原文のまま、呼び出しはこれ以上で入力+先頭300字） |
| `DAN_COMPACT_MONTHLY_CAP_JPY` | `100` | 月の上限（円）。台帳の `yen` がこれ以上なら Jev を呼ばない |
| `DAN_COMPACT_LEDGER_PATH` | `~/.dan/workspace/memory/.compact_jev_ledger.json` | 台帳 |
| `DAN_COMPACT_AT_PERCENT` | `0` | turn.complete で文脈がこの%に達したら短縮を頼む。`0` で止める（既定）。ダンの `-p` 起動では `$.session.compact()` が使えない（2.1.289 実測）ので意味が無く、組み込みの auto トリガーだけで動く。対話セッションで使う時に上げる |
| `DAN_COMPACT_MIN_REDUCTION` | `0.25` | これ未満しか縮まなければ組み込み要約へ |
| `DAN_COMPACT_PRESERVE_RECENT` | `6` | 直近この件数は触らない（最初の発言も常に残す）。**進行中のターン（最後の発言以降）は件数に関わらず全部残す**（auto 短縮はターンの途中で走り、まだ使っていない道具の結果が捨てられたため） |
| `DAN_COMPACT_JPY_PER_MTOKEN` | `6.3` | 入力100万トークンあたりの円（$42/10億トークン × 150円） |

## 確かめ方

```
cd services/claude-plugins/dan-compact
npm install
npm test                # node --test
claude plugin validate .
```
