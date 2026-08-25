[CmdletBinding()]
param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$AdminActorId = "demo-parent",
    [string]$AdminPassword = "DemoOnly-ChangeMe!",
    [string]$HouseholdName = "爷爷奶奶家（本地演示）",
    [string]$GrandpaActorId = "grandpa-demo",
    [string]$GrandmaActorId = "grandma-demo"
)

$ErrorActionPreference = "Stop"
$ApiRoot = "$($ApiBaseUrl.TrimEnd('/'))/api/v1"

function Get-StatusCode {
    param([System.Management.Automation.ErrorRecord]$ErrorRecord)
    if ($ErrorRecord.Exception.Response -and $ErrorRecord.Exception.Response.StatusCode) {
        return [int]$ErrorRecord.Exception.Response.StatusCode
    }
    return 0
}

function Invoke-Json {
    param(
        [ValidateSet("GET", "POST", "PATCH")][string]$Method,
        [string]$Path,
        [hashtable]$Headers,
        [object]$Body
    )
    $params = @{
        Method = $Method
        Uri = "$ApiRoot$Path"
        Headers = $Headers
        ErrorAction = "Stop"
    }
    if ($null -ne $Body) {
        $params.ContentType = "application/json"
        $params.Body = ($Body | ConvertTo-Json -Depth 8)
    }
    return Invoke-RestMethod @params
}

Write-Host "Checking API: $ApiRoot"
$health = Invoke-RestMethod -Method Get -Uri "$($ApiBaseUrl.TrimEnd('/'))/health" -TimeoutSec 5
if ($health.status -ne "ok") {
    throw "API health check did not return status=ok."
}

try {
    Invoke-Json -Method POST -Path "/auth/register" -Headers @{} -Body @{
        actor_id = $AdminActorId
        password = $AdminPassword
    } | Out-Null
    Write-Host "Registered local owner account: $AdminActorId"
} catch {
    if ((Get-StatusCode $_) -ne 409) { throw }
    Write-Host "Owner account already exists; reusing it: $AdminActorId"
}

$login = Invoke-Json -Method POST -Path "/auth/login" -Headers @{} -Body @{
    actor_id = $AdminActorId
    password = $AdminPassword
}
$headers = @{
    Authorization = "Bearer $($login.session_token)"
    "X-Access-Purpose" = "family-care"
}

$households = @(Invoke-Json -Method GET -Path "/households" -Headers $headers)
$household = $households | Where-Object {
    $_.name -eq $HouseholdName -and $_.created_by -eq $AdminActorId
} | Select-Object -First 1
if (-not $household) {
    $household = Invoke-Json -Method POST -Path "/households" -Headers $headers -Body @{
        name = $HouseholdName
        time_zone = "Asia/Shanghai"
    }
    Write-Host "Created household: $($household.name) [$($household.id)]"
} else {
    Write-Host "Reusing household: $($household.name) [$($household.id)]"
}

$members = @(Invoke-Json -Method GET -Path "/households/$($household.id)/members" -Headers $headers)
$desiredMembers = @(
    @{ display_name = "爷爷"; role = "DEPENDENT"; actor_id = $GrandpaActorId },
    @{ display_name = "奶奶"; role = "DEPENDENT"; actor_id = $GrandmaActorId }
)

foreach ($desired in $desiredMembers) {
    $member = $members | Where-Object {
        $_.actor_id -eq $desired.actor_id -or $_.display_name -eq $desired.display_name
    } | Select-Object -First 1
    if (-not $member) {
        $member = Invoke-Json -Method POST -Path "/households/$($household.id)/members" -Headers $headers -Body $desired
        Write-Host "Created member: $($member.display_name) [$($member.actor_id)]"
    } elseif ($member.actor_id -and $member.actor_id -ne $desired.actor_id) {
        throw "Member '$($desired.display_name)' already belongs to actor '$($member.actor_id)'; refusing to overwrite it."
    } elseif (-not $member.actor_id) {
        $member = Invoke-Json -Method PATCH -Path "/households/$($household.id)/members/$($member.id)/account" -Headers $headers -Body @{ actor_id = $desired.actor_id }
        Write-Host "Bound member account: $($member.display_name) [$($member.actor_id)]"
    } else {
        Write-Host "Reusing member: $($member.display_name) [$($member.actor_id)]"
    }
    $members = @($members | Where-Object { $_.id -ne $member.id }) + $member
}

[pscustomobject]@{
    household_id = $household.id
    household_name = $household.name
    owner_actor_id = $AdminActorId
    members = @($members | Where-Object { $_.display_name -in @("爷爷", "奶奶") } | Select-Object id, display_name, actor_id, role)
    next = @(
        "已尝试写入关联的虚构病史/过敏/药品/计划（幂等）；可用风险页与关系图核对。"
        "用 $AdminActorId 登录后打开 人脸凭证，为爷爷和奶奶各采集 2～3 帧动态画面。"
        "绑定本机家庭后退出，选择 正式账号登录 → 人脸识别，系统会在本家庭内 1:N 匹配。"
        "使用 docs/demo/vision-samples 中的合成药盒完成 扫描 → 人工复核 → 确认保存。"
    )
} | ConvertTo-Json -Depth 8

Write-Host "Seeding interconnected synthetic health events (disease/allergy/med/plan)..."
$seedArgs = @(
    "run", "python", "scripts/seed_formal_demo_health.py",
    "--base", $ApiBaseUrl,
    "--password", $AdminPassword
)
try {
    & uv @seedArgs
    if ($LASTEXITCODE -ne 0) { throw "seed_formal_demo_health.py failed with exit $LASTEXITCODE" }
} catch {
    Write-Warning "Health seed skipped or failed: $_"
    Write-Host "You can retry: uv run python scripts/seed_formal_demo_health.py --base $ApiBaseUrl"
}

Write-Host "Demo family is ready. Face templates remain explicit UI actions; health facts above are synthetic teaching data only."
