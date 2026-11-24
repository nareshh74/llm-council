$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backend = Join-Path $root '.venv\Scripts\python.exe'
$frontend = Join-Path $root 'frontend'
$vite = Join-Path $frontend 'node_modules\vite\bin\vite.js'
$node = (Get-Command node.exe -ErrorAction Stop).Source
if (!(Test-Path $backend) -or !(Test-Path $vite) -or !(Test-Path (Join-Path $root '.env'))) {
    throw 'Install dependencies and configure .env before starting LLM Council.'
}

function Test-Service($port, $kind) {
    try {
        $response = Invoke-WebRequest "http://127.0.0.1:$port/" -UseBasicParsing -TimeoutSec 3
        if ($kind -eq 'backend') {
            $health = $response.Content | ConvertFrom-Json
            return $health.status -eq 'ok' -and $health.service -eq 'LLM Council API'
        }
        return $response.StatusCode -eq 200 -and $response.Content -match '/src/main.jsx'
    } catch { return $false }
}

function Assert-PortFree($port) {
    $probe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
    try { $probe.Start() } catch { throw "Port $port is occupied by an unhealthy or unrelated service." } finally { $probe.Stop() }
}

$mutex = [System.Threading.Mutex]::new($false, 'Local\LLMCouncilStartup')
$locked = $false
$started = @()
try {
    $locked = $mutex.WaitOne([TimeSpan]::FromSeconds(60))
    if (!$locked) { throw 'Another LLM Council startup is still running.' }
    $apiReady = Test-Service 8001 'backend'
    $uiReady = Test-Service 5173 'frontend'
    if (!$apiReady) { Assert-PortFree 8001 }
    if (!$uiReady) { Assert-PortFree 5173 }
    $env:PYTHONUTF8 = '1'
    if (!$apiReady) {
        $started += Start-Process -FilePath $backend -ArgumentList '-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8001' -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root 'backend.out.log') -RedirectStandardError (Join-Path $root 'backend.err.log') -PassThru
    }
    if (!$uiReady) {
        $started += Start-Process -FilePath $node -ArgumentList "`"$vite`"",'--host','127.0.0.1','--port','5173','--strictPort' -WorkingDirectory $frontend -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root 'frontend.out.log') -RedirectStandardError (Join-Path $root 'frontend.err.log') -PassThru
    }
    foreach ($service in @(@(8001, 'backend'), @(5173, 'frontend'))) {
        $ready = $false
        for ($i = 0; $i -lt 30; $i++) {
            if (Test-Service $service[0] $service[1]) { $ready = $true; break }
            Start-Sleep -Seconds 1
        }
        if (!$ready) { throw "Service failed to start on port $($service[0]). Check logs in $root." }
    }
    Write-Output 'LLM Council ready: http://localhost:5173/ (backend http://127.0.0.1:8001/)'
} catch {
    foreach ($process in $started) { Stop-Process -Id $process.Id -ErrorAction SilentlyContinue }
    throw
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
