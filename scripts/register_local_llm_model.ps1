[CmdletBinding()]
param(
    [string]$ModelName = "hct402-qlora-v5"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$modelDirectory = Join-Path $repoRoot "src\models\llm\hct402-qlora-v5"
$modelFile = Join-Path $modelDirectory "hct402-v5-merged-q8_0.gguf"
$modelfile = Join-Path $modelDirectory "Modelfile"

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    throw "Ollama is not installed or is not available on PATH."
}
if (-not (Test-Path -LiteralPath $modelFile)) {
    throw "Local LLM weight not found: $modelFile"
}
if (-not (Test-Path -LiteralPath $modelfile)) {
    throw "Ollama Modelfile not found: $modelfile"
}

Write-Host "Registering local model '$ModelName' from $modelFile"
& ollama create $ModelName -f $modelfile
if ($LASTEXITCODE -ne 0) {
    throw "Ollama model registration failed with exit code $LASTEXITCODE."
}
Write-Host "Local model ready: $ModelName"
