# Project Chat Runtime Contract

## 目的
プロジェクトチャットの動き方を1つにそろえるための共通ルール。
実装を変えるときは、このファイルを先に更新する。

## 基本方針
1. すべての作業は AI の自律実行を前提にする
2. 人間の事前準備（ツール作成・コード修正・手順準備）を前提にしない
3. ただし Green / Yellow / Red の提案・報告・停止基準は必ず守る

## Green / Yellow / Red の単一参照先
- `app/agent/risk_bands.py`

## プロジェクト状態の流れ
1. `planning`
2. `proposed`
3. `approved`
4. `in_progress`
5. `awaiting_confirmation`（Red操作の確認待ち時のみ）
6. `completed` または `paused`

## 必須イベント（プロセスモニター）
以下は調査・計画段階と実装段階の両方で記録対象とする。

- `phase`: いま何の段階か
- `reasoning`: なぜその行動をしているか（要約）
- `tool_use`: どのツールを使ったか
- `error`: 失敗内容
- `step_verification`: ステップ検証結果
- `done`: 完了または中断

## キャンセル
- 停止ボタンまたは `Esc` で中断を受け付ける
- その時点でイベントと状態を保存する
- 再開可能な形で残す

## 方針変更
- 提案後でも実装中でも、ユーザー方針が変わったら再計画を許可する
- 必要な場合は再調査して、新方針で続行する

