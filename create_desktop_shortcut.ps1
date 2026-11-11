$ScriptDir = $PSScriptRoot
$WshShell = New-Object -comObject WScript.Shell
$Desktop = [Environment]::GetFolderPath("Desktop")
$Shortcut = $WshShell.CreateShortcut("$Desktop\PCleaner.lnk")
$Shortcut.TargetPath = Join-Path $ScriptDir "run_pcleaner.bat"
$Shortcut.WorkingDirectory = $ScriptDir
$Shortcut.Description = "PCleaner - C: Drive Space Detective & Safe Cleaner"
$Shortcut.IconLocation = "$env:SystemRoot\System32\cleanmgr.exe,0"
$Shortcut.Save()
Write-Host "Shortcut created at $Desktop\PCleaner.lnk"
