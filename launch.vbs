' Camoufox Profile Manager silent launcher (no console window).
' Runs the venv entry point directly, from the repo directory,
' with CPM_DB_PATH pinned to an absolute path inside the repo.
'
' We DO NOT use `uv run` here: it re-resolves the environment on every
' launch, which costs seconds before the window appears and would fail
' outright with no network. The venv entry point needs neither.

Option Explicit

Dim sh, fso, scriptDir, dbPath, exePath, cmd
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
dbPath    = scriptDir & "\data\profiles.db"
exePath   = scriptDir & "\.venv\Scripts\camoufox-pm.exe"

' Environment variables for the child process
sh.Environment("Process").Item("CPM_DB_PATH") = dbPath

' cmd /c to set CWD and launch the venv entry point.
cmd = "cmd /c cd /d """ & scriptDir & """ && """ & exePath & """ --desktop"

' 0 = hidden console window, False = do not wait for completion
' (the pywebview GUI window is created by the child and is not affected)
sh.Run cmd, 0, False
