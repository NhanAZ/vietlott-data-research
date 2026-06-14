$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent $PSScriptRoot
$statusPath = Join-Path $root "data\full-backfill-status.json"
$logPath = Join-Path $root "data\full-backfill.log"
$pidPath = Join-Path $root "data\full-backfill.pid"
$Host.UI.RawUI.WindowTitle = "Vietlott full backfill progress"

function Format-Duration([double]$seconds) {
    $duration = [TimeSpan]::FromSeconds([Math]::Max(0, $seconds))
    return "{0:00}d {1:00}h {2:00}m {3:00}s" -f `
        $duration.Days, $duration.Hours, $duration.Minutes, $duration.Seconds
}

while ($true) {
    Clear-Host
    Write-Host "VIETLOTT FULL BACKFILL" -ForegroundColor Cyan
    Write-Host ("Local time: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
    Write-Host ""

    $running = $false
    if (Test-Path $pidPath) {
        $processId = [int](Get-Content $pidPath)
        $running = $null -ne (Get-Process -Id $processId)
        Write-Host ("Process: " + $(if ($running) { "RUNNING (PID $processId)" } else { "STOPPED" })) `
            -ForegroundColor $(if ($running) { "Green" } else { "Red" })
    }

    if (Test-Path $statusPath) {
        $status = Get-Content $statusPath -Raw | ConvertFrom-Json
        $details = $status.details
        Write-Host ("Phase:             " + $status.phase)
        Write-Host ("Current product:   " + $details.current_product)
        Write-Host ("Product page:      {0}/{1} ({2}%)" -f `
            $details.current_page, $details.estimated_product_pages, $details.product_percent)
        Write-Host ("Overall progress:  " + $details.overall_percent + "%")
        Write-Host ("Draw rows:         " + $details.draw_rows)
        Write-Host ("Prize rows:        " + $details.prize_rows)
        $finishLocal = [DateTimeOffset]::Parse($details.estimated_finish_at).ToLocalTime()
        Write-Host ("Estimated finish:  " + $finishLocal.ToString("yyyy-MM-dd HH:mm:ss zzz"))
        Write-Host ("Time remaining:    " + (Format-Duration $details.estimated_seconds_remaining))
        Write-Host ("Last update UTC:   " + $details.updated_at)
    } else {
        Write-Host "Waiting for the first progress update..."
    }

    Write-Host ""
    Write-Host "RECENT LOG" -ForegroundColor Yellow
    if (Test-Path $logPath) {
        Get-Content $logPath -Tail 8
    }

    if (-not $running -and (Test-Path $statusPath)) {
        $status = Get-Content $statusPath -Raw | ConvertFrom-Json
        if ($status.phase -eq "complete") {
            Write-Host ""
            Write-Host "Backfill completed. This window may be closed." -ForegroundColor Green
            break
        }
    }
    Start-Sleep -Seconds 5
}
