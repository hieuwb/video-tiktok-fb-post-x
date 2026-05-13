<#
.SYNOPSIS
  Launcher cho video-x-bot — boot Redis + Celery worker + beat + Telegram bot, tail logs.

.USAGE
  Start + tail (default):     .\scripts\run.ps1
  Chỉ start:                  .\scripts\run.ps1 start
  Tail logs (services đã chạy): .\scripts\run.ps1 logs
  Status:                     .\scripts\run.ps1 status
  Stop tất cả:                .\scripts\run.ps1 stop
  Restart:                    .\scripts\run.ps1 restart
  Trigger crawl ngay:         .\scripts\run.ps1 find

.NOTES
  Ctrl+C khi đang tail logs CHỈ thoát tail — services vẫn chạy nền.
  Dùng "stop" để kill hết.
#>

param(
    [Parameter(Position=0)]
    [ValidateSet('start','stop','restart','logs','status','find','')]
    [string]$Action = ''
)

$ErrorActionPreference = 'Stop'
$ProjectDir = (Resolve-Path "$PSScriptRoot\..").Path
$LogDir = Join-Path $ProjectDir 'storage\logs'
$PidFile = Join-Path $LogDir 'service_pids.txt'
$RedisServer = "$env:USERPROFILE\redis-portable\redis-server.exe"
$RedisCli = "$env:USERPROFILE\redis-portable\redis-cli.exe"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Get-RunningServices {
    $procs = Get-WmiObject Win32_Process -Filter "Name='python.exe' OR Name='redis-server.exe'" -ErrorAction SilentlyContinue
    $out = @{}
    foreach ($p in $procs) {
        $cmd = $p.CommandLine
        # NOTE: pattern phải chặt vì path "app.workers.celery_app" chứa "worker"
        # → match nhầm beat process. Dùng arg cụ thể " worker " hoặc " beat ".
        if ($p.Name -eq 'redis-server.exe') { $out['redis'] = $p.ProcessId }
        elseif ($cmd -match '\sworker\s.*--loglevel|\sworker\s.*-P\ssolo') { $out['worker'] = $p.ProcessId }
        elseif ($cmd -match '\sbeat\s.*--loglevel|\sbeat$') { $out['beat'] = $p.ProcessId }
        elseif ($cmd -match 'app\.bot\.main') { $out['bot'] = $p.ProcessId }
    }
    return $out
}

function Start-Services {
    Push-Location $ProjectDir
    try {
        $running = Get-RunningServices

        # Redis
        if (-not $running.ContainsKey('redis')) {
            if (-not (Test-Path $RedisServer)) {
                Write-Host "ERROR: redis-server.exe not found at $RedisServer" -ForegroundColor Red
                Write-Host "Download portable Redis từ https://github.com/tporadowski/redis/releases" -ForegroundColor Yellow
                return
            }
            $r = Start-Process -PassThru -FilePath $RedisServer -WindowStyle Hidden
            Write-Host "Redis              started PID $($r.Id)" -ForegroundColor Green
            Start-Sleep 2
        } else { Write-Host "Redis              already running PID $($running['redis'])" -ForegroundColor DarkGray }

        # Verify Redis ping
        $ping = & $RedisCli ping 2>$null
        if ($ping -ne 'PONG') {
            Write-Host "ERROR: Redis ping failed" -ForegroundColor Red; return
        }

        # Worker
        if (-not $running.ContainsKey('worker')) {
            $w = Start-Process -PassThru -FilePath python -ArgumentList "-m","celery","-A","app.workers.celery_app.celery_app","worker","--loglevel=info","-P","solo" `
                -RedirectStandardOutput "$LogDir\worker.out" -RedirectStandardError "$LogDir\worker.err" `
                -WorkingDirectory $ProjectDir -WindowStyle Hidden
            Write-Host "Celery worker      started PID $($w.Id)" -ForegroundColor Green
        } else { Write-Host "Celery worker      already running PID $($running['worker'])" -ForegroundColor DarkGray }

        # Beat
        if (-not $running.ContainsKey('beat')) {
            $b = Start-Process -PassThru -FilePath python -ArgumentList "-m","celery","-A","app.workers.celery_app.celery_app","beat","--loglevel=info" `
                -RedirectStandardOutput "$LogDir\beat.out" -RedirectStandardError "$LogDir\beat.err" `
                -WorkingDirectory $ProjectDir -WindowStyle Hidden
            Write-Host "Celery beat        started PID $($b.Id)" -ForegroundColor Green
        } else { Write-Host "Celery beat        already running PID $($running['beat'])" -ForegroundColor DarkGray }

        # Bot
        if (-not $running.ContainsKey('bot')) {
            $bot = Start-Process -PassThru -FilePath python -ArgumentList "-m","app.bot.main" `
                -RedirectStandardOutput "$LogDir\bot.out" -RedirectStandardError "$LogDir\bot.err" `
                -WorkingDirectory $ProjectDir -WindowStyle Hidden
            Write-Host "Telegram bot       started PID $($bot.Id)" -ForegroundColor Green
        } else { Write-Host "Telegram bot       already running PID $($running['bot'])" -ForegroundColor DarkGray }

        Start-Sleep 3
        $final = Get-RunningServices
        $final.GetEnumerator() | Sort-Object Key | ForEach-Object {
            "$($_.Key)=$($_.Value)"
        } | Out-File $PidFile -Encoding ascii
    } finally { Pop-Location }
}

function Stop-Services {
    $running = Get-RunningServices
    if ($running.Count -eq 0) { Write-Host "No services running" -ForegroundColor DarkGray; return }
    foreach ($entry in $running.GetEnumerator()) {
        Stop-Process -Id $entry.Value -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped $($entry.Key) PID $($entry.Value)" -ForegroundColor Yellow
    }
    if (Test-Path $PidFile) { Remove-Item $PidFile }
}

function Show-Status {
    Write-Host "=== Service status ===" -ForegroundColor Cyan
    $running = Get-RunningServices
    foreach ($svc in @('redis','worker','beat','bot')) {
        if ($running.ContainsKey($svc)) {
            $proc = Get-Process -Id $running[$svc] -ErrorAction SilentlyContinue
            $upMin = if ($proc) { [Math]::Round(((Get-Date) - $proc.StartTime).TotalMinutes, 1) } else { '?' }
            Write-Host ("  {0,-10} ALIVE  PID {1,-6}  up {2} min" -f $svc, $running[$svc], $upMin) -ForegroundColor Green
        } else {
            Write-Host ("  {0,-10} STOPPED" -f $svc) -ForegroundColor Red
        }
    }
    if ((& $RedisCli ping 2>$null) -eq 'PONG') {
        Write-Host "  redis ping: PONG" -ForegroundColor Green
    } else {
        Write-Host "  redis ping: FAIL" -ForegroundColor Red
    }
}

function Tail-Logs {
    Write-Host "=== Tailing logs (Ctrl+C để thoát, services vẫn chạy nền) ===" -ForegroundColor Cyan
    Write-Host "Logs: worker.err | beat.err | bot.out" -ForegroundColor DarkGray
    Write-Host ""
    $files = @(
        @{Path = "$LogDir\worker.err"; Tag = 'worker'},
        @{Path = "$LogDir\beat.err"; Tag = 'beat  '},
        @{Path = "$LogDir\bot.out"; Tag = 'bot   '}
    )
    # Touch nếu chưa có
    foreach ($f in $files) { if (-not (Test-Path $f.Path)) { New-Item -ItemType File -Force -Path $f.Path | Out-Null } }
    # Tail song song bằng Get-Content -Wait. PowerShell không native multi-tail nên dùng Start-Job.
    $jobs = foreach ($f in $files) {
        Start-Job -ArgumentList $f.Path, $f.Tag -ScriptBlock {
            param($path, $tag)
            Get-Content $path -Wait -Tail 5 | ForEach-Object { "[$tag] $_" }
        }
    }
    try {
        while ($true) {
            $jobs | ForEach-Object {
                Receive-Job $_ | Where-Object { $_ } | ForEach-Object {
                    if ($_ -match 'ERROR|FAIL|Exception|Traceback') { Write-Host $_ -ForegroundColor Red }
                    elseif ($_ -match 'WARNING') { Write-Host $_ -ForegroundColor Yellow }
                    elseif ($_ -match 'posted on X|Tweet URL captured|succeeded|Modal closed') { Write-Host $_ -ForegroundColor Green }
                    else { Write-Host $_ }
                }
            }
            Start-Sleep -Milliseconds 500
        }
    } finally {
        $jobs | Stop-Job -PassThru | Remove-Job -Force
    }
}

function Trigger-Find {
    Push-Location $ProjectDir
    try {
        python -X utf8 -c "from app.workers.celery_app import celery_app; r = celery_app.send_task('app.workers.tasks_reup.auto_crawl_and_prepare'); print(f'Crawl task dispatched: {r.id}')"
    } finally { Pop-Location }
}

# ───── Dispatch ─────
switch ($Action) {
    'start'   { Start-Services; Show-Status }
    'stop'    { Stop-Services }
    'restart' { Stop-Services; Start-Sleep 2; Start-Services; Show-Status }
    'status'  { Show-Status }
    'logs'    { Tail-Logs }
    'find'    { Trigger-Find }
    default   { Start-Services; Show-Status; Write-Host ""; Tail-Logs }
}
