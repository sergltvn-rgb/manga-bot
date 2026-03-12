Set WshShell = CreateObject("WScript.Shell")

' Получаем папку, где лежит этот скрипт (чтобы не прописывать пути вручную)
strPath = Wscript.ScriptFullName
Set objFSO = CreateObject("Scripting.FileSystemObject")
strFolder = objFSO.GetParentFolderName(strPath)

' Запускаем твой run.bat в скрытом режиме (0 означает скрыть черное окно)
WshShell.Run chr(34) & strFolder & "\run.bat" & chr(34), 0

Set WshShell = Nothing