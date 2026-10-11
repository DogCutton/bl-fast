<#
    bl-fast installer (Windows)

    Copies bl_fast.py into Blender's user "scripts/modules" folder, which is already
    on Blender's sys.path - so after this, any Blender script can `import bl_fast`.

    Usage:
        powershell -ExecutionPolicy Bypass -File install.ps1
        (or right-click -> Run with PowerShell)

    Uninstall: run uninstall.ps1, or delete the copied bl_fast.py.

    NOTE ON LANGUAGE: the output here is deliberately ASCII-only. Windows PowerShell
    5.1 decodes a .ps1 file as the system codepage (GBK on this machine) when the file
    has no BOM, so non-ASCII text would come out garbled. The Chinese documentation
    lives in INSTALL.md instead.
#>

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$src  = Join-Path $here "bl_fast.py"

if (-not (Test-Path $src)) {
    Write-Host "[X] bl_fast.py not found next to this script." -ForegroundColor Red
    exit 1
}

$base = Join-Path $env:APPDATA "Blender Foundation\Blender"
if (-not (Test-Path $base)) {
    Write-Host "[X] Blender user config folder not found: $base" -ForegroundColor Red
    exit 1
}

Write-Host "Blender config root : $base"
Write-Host "Source              : $src"
Write-Host ""

$count = 0
foreach ($v in (Get-ChildItem $base -Directory | Sort-Object Name)) {
    $scripts = Join-Path $v.FullName "scripts"
    if (-not (Test-Path $scripts)) {
        Write-Host ("  skip Blender {0} (no scripts folder)" -f $v.Name)
        continue
    }
    $dst = Join-Path $scripts "modules"
    New-Item -ItemType Directory -Path $dst -Force | Out-Null
    Copy-Item $src (Join-Path $dst "bl_fast.py") -Force
    Write-Host ("  [OK] Blender {0}  ->  {1}\bl_fast.py" -f $v.Name, $dst) -ForegroundColor Green
    $count++
}

Write-Host ""
if ($count -gt 0) {
    Write-Host ("Installed into {0} Blender version(s)." -f $count) -ForegroundColor Green
    Write-Host ""
    Write-Host "Verify in Blender (Python Console or Text Editor):"
    Write-Host "    import bl_fast as bf"
    Write-Host "    print(bf.__file__)"
    Write-Host ""
    Write-Host "Uninstall: run uninstall.ps1, or delete the bl_fast.py listed above."
} else {
    Write-Host "Nothing installed." -ForegroundColor Yellow
    exit 1
}
