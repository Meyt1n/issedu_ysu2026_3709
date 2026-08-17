# 一键构建安卓调试版 APK
# 用法：powershell -ExecutionPolicy Bypass -File scripts/build-apk.ps1
# 可选参数：-JavaHome 指定 JDK 21+（默认使用 Android Studio 自带 JBR）

param(
    [string]$JavaHome = "C:\Program Files\Android\Android Studio\jbr"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path (Join-Path $JavaHome "bin\java.exe"))) {
    throw "未找到 JDK：$JavaHome；请安装 Android Studio 或用 -JavaHome 指定 JDK 21+"
}
if (-not $env:ANDROID_HOME) {
    $env:ANDROID_HOME = Join-Path $env:LOCALAPPDATA "Android\Sdk"
}
if (-not (Test-Path $env:ANDROID_HOME)) {
    throw "未找到 Android SDK：$env:ANDROID_HOME；请安装 Android Studio 或设置 ANDROID_HOME"
}

# local.properties 不入库，首次构建时按本机 SDK 生成。
$localProps = Join-Path $RepoRoot "android\local.properties"
if (-not (Test-Path $localProps)) {
    "sdk.dir=$($env:ANDROID_HOME -replace '\\', '\\\\')" | Set-Content -Path $localProps -Encoding ASCII
    Write-Host "已生成 android/local.properties"
}

Set-Location $RepoRoot
npm run android:sync
if ($LASTEXITCODE -ne 0) { throw "Web 构建或 Capacitor 同步失败" }

$env:JAVA_HOME = $JavaHome
Set-Location (Join-Path $RepoRoot "android")
.\gradlew.bat assembleDebug
if ($LASTEXITCODE -ne 0) { throw "Gradle 构建失败" }

$apk = Join-Path $RepoRoot "android\app\build\outputs\apk\debug\app-debug.apk"
Write-Host ""
Write-Host "构建完成：$apk"
Write-Host "把该文件传到手机安装（需允许安装未知来源应用）。"
