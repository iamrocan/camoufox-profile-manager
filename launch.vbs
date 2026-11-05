' Camoufox Profile Manager silent launcher (no console window).
' Runs scripts\prelaunch.py on the venv's pythonw.exe from the repo
' directory, with CPM_DB_PATH pinned to an absolute path inside the repo.
' prelaunch updates the browser and prunes old builds before handing over
' to the manager; when there is nothing to download it is silent, and when
' there is it opens a console window of its own that says so.
'
' We DO NOT call camoufox-pm.exe. pip and uv do not ship that file, they
' build it on the machine from a stub, so it is an unsigned binary with no
' reputation -- which is what Windows 11's Smart App Control blocks
' ("part of this app has been blocked", CodeIntegrity 3033/3077/3118).
' pythonw.exe is signed by the Python Software Foundation and -m loads the
' same code, so this route works whether SAC is on or off.
'
' We DO NOT use `uv run` here either: it re-resolves the environment on
' every launch, which costs seconds before the window appears and would
' fail outright with no network. Neither route needs it.

Option Explicit

Dim sh, fso, scriptDir, dbPath, exePath, scriptPath, cmd, q
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir  = fso.GetParentFolderName(WScript.ScriptFullName)
dbPath     = scriptDir & "\data\profiles.db"
exePath    = scriptDir & "\.venv\Scripts\pythonw.exe"
scriptPath = scriptDir & "\scripts\prelaunch.py"

' Environment variables for the child process
sh.Environment("Process").Item("CPM_DB_PATH") = dbPath

' cmd /c to set CWD and launch the signed interpreter on the launcher.
' Built with Chr(34) rather than doubled quotes: three paths have to be
' quoted here, and escaped quotes inside an escaped string is how you ship
' a command that is subtly unbalanced and only fails on paths with spaces.
q = Chr(34)
cmd = "cmd /c cd /d " & q & scriptDir & q & " && " & _
      q & exePath & q & " " & q & scriptPath & q & " --desktop"

' 0 = hidden console window, False = do not wait for completion
' (the pywebview GUI window is created by the child and is not affected)
sh.Run cmd, 0, False
