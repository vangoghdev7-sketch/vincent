param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "Vincent OS Runtime"

Set-Location -LiteralPath $Root

Write-Host "==================================================="
Write-Host "  Vincent OS runtime"
Write-Host "  Dashboard: http://localhost:3000"
Write-Host "  Close this window or press Ctrl+C to stop."
Write-Host "==================================================="
Write-Host ""

try {
    & node "frontend\scripts\dev-all.cjs"
    $exitCode = $LASTEXITCODE
} catch {
    Write-Host ""
    Write-Host "[!] Runtime failed: $($_.Exception.Message)"
    $exitCode = 1
}

Write-Host ""
Write-Host "==================================================="
Write-Host "  Vincent OS has stopped. Exit code: $exitCode"
Write-Host "==================================================="
Read-Host "Press Enter to close"
exit $exitCode
