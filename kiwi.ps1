function Read-DotEnvValue {
    param([string]$Name)
    foreach ($candidate in @(".env.local", ".env")) {
        $path = Join-Path $PSScriptRoot $candidate
        if (Test-Path $path) {
            $line = Get-Content $path | Where-Object { $_ -match "^\s*$Name\s*=" } | Select-Object -Last 1
            if ($line) {
                return ($line -split '=', 2)[1].Trim()
            }
        }
    }
    return $null
}

$backendProcess = $null
try {
    $anthropicKey = Read-DotEnvValue "ANTHROPIC_API_KEY"
    $openaiKey = Read-DotEnvValue "OPENAI_API_KEY"
    $geminiKey = Read-DotEnvValue "GEMINI_API_KEY"

    $llmApiKey = $null
    $llmProvider = $null
    $llmModel = $null
    if ($anthropicKey -and $anthropicKey -ne "your_anthropic_key_here") {
        $llmApiKey = $anthropicKey
        $llmProvider = "anthropic"
        $llmModel = "claude-opus-4-8"
    } elseif ($openaiKey -and $openaiKey -ne "your_openai_key_here") {
        $llmApiKey = $openaiKey
        $llmProvider = "openai"
        $llmModel = "gpt-5.5"
    } elseif ($geminiKey -and $geminiKey -ne "your_gemini_key_here") {
        $llmApiKey = $geminiKey
        $llmProvider = "gemini"
        $llmModel = "gemini-3-flash-preview"
    }

    if ($llmApiKey) {
        # docker compose on this Windows/Docker Desktop setup does not reliably
        # substitute ${VAR} from inherited process env vars set via $env: before
        # `up -d` (silently defaults them to blank) - write a transient env file
        # and pass it explicitly instead. Never committed (gitignored).
        $composeEnvFile = Join-Path $PSScriptRoot ".cognee_compose.env"
        # -Encoding ascii (not utf8, which emits a BOM in Windows PowerShell 5.1
        # that docker compose's --env-file parser can mishandle on the first key).
        # Keys/values here are always plain ASCII.
        @(
            "LLM_API_KEY=$llmApiKey"
            "LLM_PROVIDER=$llmProvider"
            "LLM_MODEL=$llmProvider/$llmModel"
            "ENABLE_BACKEND_ACCESS_CONTROL=false"
        ) | Set-Content -Path $composeEnvFile -Encoding ascii

        try {
            try {
                docker compose --env-file $composeEnvFile -f (Join-Path $PSScriptRoot "docker-compose.cognee.yml") up -d 2>&1 | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    throw "docker compose exited with code $LASTEXITCODE"
                }

                # First boot (or first boot after an image/schema change) runs a long
                # alembic migration chain before the server starts - observed to take
                # 80s+ even on an empty local sqlite DB. 30s was too short and produced
                # a false "not healthy" warning while the container was still fine.
                # curl.exe, not Invoke-WebRequest: IWR's System.Net.HttpWebRequest stack
                # (even with -DisableKeepAlive) hangs unreliably against Cognee's uvicorn
                # server until its 2s timeout on this setup - confirmed via 15+ back-to-back
                # calls where curl.exe was always instant/200 and IWR intermittently or
                # consistently timed out. curl.exe ships with Windows 10/11 by default.
                $cogneeReady = $false
                for ($i = 0; $i -lt 90; $i++) {
                    $code = & curl.exe -s -o NUL -w "%{http_code}" --max-time 2 "http://localhost:8010/health" 2>$null
                    if ($code -eq "200") { $cogneeReady = $true; break }
                    Start-Sleep -Seconds 1
                }
                if (-not $cogneeReady) {
                    Write-Warning "Cognee server did not respond healthy within 90s; continuing anyway (it may still be starting up, or has no network access to its LLM provider)."
                }
            } catch {
                Write-Warning "Could not start the Cognee server (is Docker installed and running?): $_. Continuing without it."
            }
        } finally {
            Remove-Item -Path $composeEnvFile -Force -ErrorAction SilentlyContinue
        }
    } else {
        Write-Warning "No LLM API key found in .env; skipping Cognee server auto-start. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY."
    }

    $outLog = Join-Path $env:TEMP "kiwi_backend_out.log"
    $errLog = Join-Path $env:TEMP "kiwi_backend_err.log"
    $backendProcess = Start-Process uv -ArgumentList "run", "uvicorn", "app.main:app", "--port", "8000" -PassThru -NoNewWindow -WorkingDirectory $PSScriptRoot -RedirectStandardOutput $outLog -RedirectStandardError $errLog
    Start-Sleep -Seconds 2
    pnpm --silent --dir kiwi-ui start
} finally {
    if ($backendProcess) {
        Stop-Process -Id $backendProcess.Id -Force -ErrorAction SilentlyContinue
    }
    Clear-Host
}
