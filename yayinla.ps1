# Botu, paneli ve tuneli birlikte baslatir, panele public bir link verir.
#
# Kullanim:
#   .\yayinla.ps1                 parolasiz, herkes linkle girer
#   .\yayinla.ps1 -Parola gizli   parola sorar
#
# Guvenlik notu: Streamlit yalnizca 127.0.0.1 adresine baglanir, yerel aginda
# hicbir cihaz erisemez. Disariya acilan tek sey tunelin proxyledigi 8511
# portudur. Tunel dosya sistemine, terminale ya da baska bir porta erisim
# vermez. Ctrl+C ile her sey kapanir ve link aninda olur.

param(
    [string]$Parola = "",
    [int]$Port = 8511
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if ($Parola) {
    $env:APP_PASSWORD = $Parola
    Write-Host "Parola korumasi acik." -ForegroundColor Green
} else {
    Write-Host "Parola yok. Linki bilen herkes paneli gorur." -ForegroundColor Yellow
}

# Ziyaretcilerin sunucuda is baslatmasini engelle.
$env:PUBLIC_TUNNEL = "1"

Write-Host "Bot baslatiliyor..." -ForegroundColor Cyan
$bot = Start-Process -FilePath "python" -ArgumentList "runner.py" `
    -PassThru -NoNewWindow -RedirectStandardOutput "runner.log" `
    -RedirectStandardError "runner.err.log"

Write-Host "Panel baslatiliyor (yalniz 127.0.0.1:$Port)..." -ForegroundColor Cyan
$panel = Start-Process -FilePath "streamlit" `
    -ArgumentList "run", "app.py", "--server.address", "127.0.0.1", `
                  "--server.port", "$Port" `
    -PassThru -NoNewWindow -RedirectStandardOutput "panel.log" `
    -RedirectStandardError "panel.err.log"

Start-Sleep -Seconds 6

Write-Host "Tunel aciliyor..." -ForegroundColor Cyan
Write-Host "Link asagida cikacak, trycloudflare.com ile biter." -ForegroundColor Green
Write-Host "Durdurmak icin Ctrl+C." -ForegroundColor Yellow
Write-Host ""

try {
    & cloudflared tunnel --url "http://127.0.0.1:$Port"
} finally {
    Write-Host ""
    Write-Host "Kapatiliyor..." -ForegroundColor Yellow
    foreach ($p in @($bot, $panel)) {
        if ($p -and -not $p.HasExited) {
            try { Stop-Process -Id $p.Id -Force -ErrorAction Stop } catch {}
        }
    }
    Write-Host "Bot, panel ve tunel kapandi. Link artik calismiyor." -ForegroundColor Green
}
