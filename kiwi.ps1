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
        @(
            "LLM_API_KEY=$llmApiKey"
            "LLM_PROVIDER=$llmProvider"
            "LLM_MODEL=$llmProvider/$llmModel"
        ) | Set-Content -Path $composeEnvFile -Encoding utf8

        try {
            docker compose --env-file $composeEnvFile -f (Join-Path $PSScriptRoot "docker-compose.cognee.yml") up -d | Out-Null

            $cogneeReady = $false
            for ($i = 0; $i -lt 30; $i++) {
                try {
                    $resp = Invoke-WebRequest -Uri "http://localhost:8010/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
                    if ($resp.StatusCode -eq 200) { $cogneeReady = $true; break }
                } catch {}
                Start-Sleep -Seconds 1
            }
            if (-not $cogneeReady) {
                Write-Warning "Cognee server did not respond healthy within 30s; continuing anyway (it may still be starting up, or has no network access to its LLM provider)."
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
