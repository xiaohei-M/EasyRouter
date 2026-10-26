# 易路由 EasyRouter —— Windows 演示模式启动器
# 自动查找可用 Python，启动模拟数据的管理界面并打开浏览器。
param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "SilentlyContinue"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

function Write-Info($msg)  { Write-Host $msg -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host $msg -ForegroundColor Green }
function Write-Warn2($msg) { Write-Host $msg -ForegroundColor Yellow }
function Write-Err2($msg)  { Write-Host $msg -ForegroundColor Red }

Write-Host ""
Write-Host "=============================================" -ForegroundColor DarkCyan
Write-Host "  易路由 EasyRouter · 演示模式启动器" -ForegroundColor White
Write-Host "=============================================" -ForegroundColor DarkCyan
Write-Host ""

# ---------- 0. 已有演示服务则直接打开 ----------
function Test-DemoRunning {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8080/api/health" -TimeoutSec 2
        return ($r.StatusCode -eq 200 -and $r.Content -like "*EasyRouter*")
    } catch {
        return $false
    }
}

if (Test-DemoRunning) {
    Write-Ok "✓ 演示服务已经在运行：http://127.0.0.1:8080"
    if (-not $NoBrowser) {
        Start-Process "http://127.0.0.1:8080"

    }
    exit 0
}

# ---------- 1. 查找可用的 Python ----------
function Test-Python($exe, $argsPrefix) {
    try {
        if ($argsPrefix) {
            $out = & $exe $argsPrefix -c "import sys; print(sys.version_info[0])" 2>$null
        } else {
            $out = & $exe -c "import sys; print(sys.version_info[0])" 2>$null
        }
        if ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq "3") { return $true }
    } catch { }
    return $false
}

$pythonExe = $null
$pythonArgs = @()

# 1) DSH 自带 Python（本机安装 Harness 时可用）
$bundled = Join-Path $env:USERPROFILE ".dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if (Test-Path $bundled) {
    if (Test-Python $bundled $null) {
        $pythonExe = $bundled
        Write-Ok "✓ 使用 DSH 内置 Python：$bundled"
    }
}

# 2) PATH 中的 python（跳过微软商店占位符）
if (-not $pythonExe) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike "*\WindowsApps\*") {
        if (Test-Python $cmd.Source $null) {
            $pythonExe = $cmd.Source
            Write-Ok "✓ 使用系统 Python：$($cmd.Source)"
        }
    }
}

# 3) py 启动器
if (-not $pythonExe) {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py -and (Test-Python $py.Source @("-3"))) {
        $pythonExe = $py.Source
        $pythonArgs = @("-3")
        Write-Ok "✓ 使用 py 启动器：$($py.Source)"
    }
}

if (-not $pythonExe) {
    Write-Err2 "✗ 未找到可用的 Python 3。"
    Write-Host ""
    Write-Host "请安装 Python 3.9 或更高版本："
    Write-Host "    https://www.python.org/downloads/"
    Write-Host "安装时请勾选 “Add python.exe to PATH”。"
    Write-Host ""
   
    exit 1
}

# ---------- 2. 检查项目完整性 ----------
& $pythonExe @pythonArgs -c "import easyrouter; print(easyrouter.VERSION)" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Err2 "✗ 无法导入 easyrouter 模块，请确认从完整项目目录运行（包含 easyrouter 子目录）。"
   
    exit 1
}

# ---------- 3. 启动演示服务 ----------
$url = "http://127.0.0.1:8080"
Write-Info "正在启动演示服务，管理地址：$url"
Write-Info "演示账号：admin    演示密码：admin123"
Write-Host ""
Write-Host "提示：本窗口是演示服务进程，关闭窗口即停止服务。" -ForegroundColor DarkGray
Write-Host ""

if (-not $NoBrowser) {
    Start-Process -WindowStyle Hidden powershell -ArgumentList @(
        "-NoProfile", "-Command",
        "Start-Sleep -Seconds 2; Start-Process '$url'"
    ) | Out-Null
}

& $pythonExe @pythonArgs -m easyrouter demo --port 8080

Write-Host ""
Write-Warn2 "演示服务已停止。"
