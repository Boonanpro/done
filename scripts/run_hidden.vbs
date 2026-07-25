' Generic hidden launcher for Task Scheduler.
' wscript.exe is a GUI-subsystem host, so no console window is ever created.
' Running python.exe or a .bat directly from Task Scheduler opens a visible
' console window (e.g. "C:\Program Files\Python310\python.exe") on every run;
' route the action through this script instead to keep it invisible.
'
' Usage: wscript.exe D:\done\scripts\run_hidden.vbs <exe/bat/py path> [args...]
'   - if the first argument ends with .py it is run with python.exe
'   - cwd is fixed to D:\done
'   - output is appended to D:\done\logs\scheduled_tasks.log
'     (a .bat that redirects its own output keeps doing so)
' Run(..., 0, True): 0 = SW_HIDE, True = wait for exit so the task's run time
' and exit code are recorded and IgnoreNew (no-overlap) keeps working.
'
' NOTE: comments here must stay ASCII-only. VBScript files are read in the
' ANSI codepage (CP932); UTF-8 Japanese comment bytes can swallow the
' following newline and comment out the next code line (2026-07-25 incident:
' "Set sh" was absorbed, wscript hung forever on a hidden error dialog).
Set sh = CreateObject("WScript.Shell")
If WScript.Arguments.Count = 0 Then WScript.Quit 2
first = WScript.Arguments(0)
If LCase(Right(first, 3)) = ".py" Then
  cmd = """C:\Program Files\Python310\python.exe"" """ & first & """"
Else
  cmd = """" & first & """"
End If
For i = 1 To WScript.Arguments.Count - 1
  cmd = cmd & " """ & WScript.Arguments(i) & """"
Next
full = "cmd.exe /c cd /d D:\done && " & cmd & " >> D:\done\logs\scheduled_tasks.log 2>&1"
WScript.Quit sh.Run(full, 0, True)
