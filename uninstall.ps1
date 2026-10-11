<#
    bl-fast uninstaller (Windows)

    Deletes bl_fast.py from every Blender user "scripts/modules" folder.

    Usage:
        powershell -ExecutionPolicy Bypass -File uninstall.ps1

    ASCII-only output on purpose - see the note in install.ps1.
#>

$ErrorActionPreference = "Stop"
$base = Join-Path $env:APPDATA "Blender Foundation\Blender"

if (-not (Test-Path $base)) {
    Write-Host "[X] Blender user config folder not found: $base" -ForegroundColor Red
    exit 1
}

$count = 0
foreach ($v in (Get-ChildItem $base -Directory | Sort-Object Name)) {
    $f = Join-Path $v.FullName "scripts\modules\bl_fast.py"
    if (Test-Path $f) {
        Remove-Item $f -Force
        Write-Host ("  [removed] Blender {0}  ({1})" -f $v.Name, $f) -ForegroundColor Green
        $count++
    }
}

Write-Host ""
if ($count -gt 0) {
    Write-Host ("Removed from {0} Blender version(s)." -f $count)
} else {
    Write-Host "bl_fast.py was not installed anywhere." -ForegroundColor Yellow
}
