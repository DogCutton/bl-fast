<#
    bl-fast: create a GitHub Release and attach the package.

    Usage:
        powershell -ExecutionPolicy Bypass -File publish_release.ps1 -Tag v1.0.2
        powershell -ExecutionPolicy Bypass -File publish_release.ps1 -Tag v1.0.2 -DryRun

    Authentication: reuses the GitHub credential that git already has cached (Git
    Credential Manager on this machine). The token is read into a variable, used for
    the API calls, and never printed or written to disk.

    DryRun shows exactly what would happen without calling the API that writes.

    WHY THIS FILE IS PURE ASCII - and you should keep it that way:

    Windows PowerShell 5.1 decodes a BOM-less .ps1 using the system codepage (GBK on
    this machine), while the file on disk is UTF-8. Chinese text is 3 bytes in UTF-8
    but 2 in GBK, so the byte count stops lining up, and a stray byte at end of line
    combines with the newline (0x0A) into one GBK character. The newline disappears and
    the NEXT LINE of code gets absorbed into the preceding comment.

    Measured: a Chinese comment on line 29 swallowed line 30 ($ver = ...), so $ver was
    always empty and the script looked for "bl-fast-.zip". No error, no warning.

    Same family as the Get-Content / Set-Content -Encoding trap: silently wrong, not
    loudly broken.
#>

param(
    [Parameter(Mandatory = $true)][string]$Tag,
    [string]$Repo      = "DogCutton/bl-fast",
    [string]$Asset     = "",
    [string]$NotesFile = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# Package lives beside the project or up to two levels above it (this workspace keeps
# it at the workspace root). Pass -Asset to point somewhere else.

$ver = $Tag -replace '^v', ''
if (-not $Asset) {
    $cands = @(
        (Join-Path $here "bl-fast-$ver.zip"),
        (Join-Path (Split-Path -Parent $here) "bl-fast-$ver.zip"),
        (Join-Path (Split-Path -Parent (Split-Path -Parent $here)) "bl-fast-$ver.zip")
    )
    $Asset = @($cands | Where-Object { Test-Path $_ })[0]
    if (-not $Asset) { $Asset = $cands[2] }
}
if (-not $NotesFile) { $NotesFile = Join-Path $here "RELEASE_NOTES.md" }

Write-Host "=============================================="
Write-Host "bl-fast release publisher"
Write-Host "=============================================="
Write-Host "  repo   : $Repo"
Write-Host "  tag    : $Tag"
Write-Host "  version: $ver"
Write-Host "  asset  : $Asset"

if (-not (Test-Path $Asset))     { Write-Host "  [X] asset not found" -ForegroundColor Red; exit 1 }
if (-not (Test-Path $NotesFile)) { Write-Host "  [X] notes not found: $NotesFile" -ForegroundColor Red; exit 1 }

$assetItem = Get-Item $Asset
$assetName = $assetItem.Name
$sha = (Get-FileHash $Asset -Algorithm SHA256).Hash
Write-Host ("         {0:N1} KB" -f ($assetItem.Length / 1KB))
Write-Host "         SHA256 $sha"
Write-Host "  notes  : $NotesFile"

# Fill the placeholders in the release notes.
$notes = Get-Content $NotesFile -Raw -Encoding UTF8
$notes = $notes.Replace("{{VERSION}}", $ver).Replace("{{SHA256}}", $sha).Replace("{{ASSET}}", $assetName)
Write-Host "         ($($notes.Length) chars)"

# Read the cached credential. Never printed.
$cred  = ("protocol=https`nhost=github.com`n`n" | git credential fill 2>$null) -join "`n"
$user  = [regex]::Match($cred, '(?m)^username=(.+)$').Groups[1].Value
$token = [regex]::Match($cred, '(?m)^password=(.+)$').Groups[1].Value

if (-not $token) {
    Write-Host "  [X] no cached GitHub credential." -ForegroundColor Red
    Write-Host "      Run 'git push' once so Git Credential Manager caches one, then retry."
    exit 1
}
Write-Host "  auth   : ok (user '$user', token $($token.Length) chars)"

$H = @{
    "Authorization"        = "Bearer $token"
    "Accept"               = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent"           = "bl-fast-release-script"
}

# Does a release for this tag already exist?
$api = "https://api.github.com/repos/$Repo"
$existing = $null
try {
    $existing = Invoke-RestMethod -Uri "$api/releases/tags/$Tag" -Headers $H -Method Get -TimeoutSec 60
} catch {
    if ($_.Exception.Response.StatusCode.value__ -ne 404) { throw }
}

if ($existing) {
    Write-Host ""
    Write-Host "  release for $Tag already exists: $($existing.html_url)" -ForegroundColor Yellow
    $have = @($existing.assets | ForEach-Object { $_.name })
    Write-Host "  assets already there: $($have -join ', ')"
    if ($have -contains $assetName) {
        Write-Host "  [=] $assetName is already uploaded - nothing to do." -ForegroundColor Green
        exit 0
    }
    Write-Host "  -> will upload $assetName to the existing release"
}

if ($DryRun) {
    Write-Host ""
    Write-Host "  [DRY RUN] would create/attach:" -ForegroundColor Cyan
    Write-Host "            tag    $Tag"
    Write-Host "            title  bl-fast $ver"
    Write-Host "            asset  $assetName ($([math]::Round($assetItem.Length / 1KB, 1)) KB)"
    if ($existing) { Write-Host "            (to the EXISTING release $($existing.html_url))" }
    Write-Host "  nothing was written."
    exit 0
}

# Create the release if needed.
if (-not $existing) {
    $body = @{
        tag_name   = $Tag
        name       = "bl-fast $ver"
        body       = $notes
        draft      = $false
        prerelease = $false
    } | ConvertTo-Json -Depth 5

    $rel = Invoke-RestMethod -Uri "$api/releases" -Headers $H -Method Post `
                             -Body $body -ContentType "application/json; charset=utf-8" -TimeoutSec 120
    Write-Host ""
    Write-Host "  [OK] release created: $($rel.html_url)" -ForegroundColor Green
} else {
    $rel = $existing
    Write-Host ""
    Write-Host "  [OK] using existing release: $($rel.html_url)" -ForegroundColor Green
}

# Upload the asset.
$upload = ($rel.upload_url -replace '\{[^}]*\}$', '') + "?name=$assetName"
$asset2 = Invoke-RestMethod -Uri $upload -Headers $H -Method Post `
                            -InFile $Asset -ContentType "application/zip" -TimeoutSec 600

Write-Host "  [OK] asset uploaded ($([math]::Round($asset2.size / 1KB, 1)) KB)" -ForegroundColor Green
Write-Host "       $($asset2.browser_download_url)"
Write-Host ""
Write-Host "  release page: $($rel.html_url)"
Write-Host "  done."
