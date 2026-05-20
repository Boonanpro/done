' DanStackWatchdog 用の非表示ランチャー。
' wscript.exe は GUI サブシステムなのでコンソール窓を作らない。
' Run の第2引数 0 = SW_HIDE。子プロセス(powershell)を最初から非表示で起動するため、
' タスクスケジューラ直起動時のような一瞬の窓のチラつきが出ない。
' 第3引数 True = 完了まで待機。タスクの実行時間と終了コードが正しく記録され、
' IgnoreNew(多重起動防止)も機能する。
WScript.Quit CreateObject("WScript.Shell").Run("powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""D:\done\scripts\ensure_dan_stack.ps1""", 0, True)
