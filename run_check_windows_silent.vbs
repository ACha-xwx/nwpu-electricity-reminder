Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.Run Chr(34) & scriptDir & "\run_check_windows.bat" & Chr(34), 0, False
