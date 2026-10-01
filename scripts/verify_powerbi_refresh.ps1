param(
    [Parameter(Mandatory=$true)][ValidateRange(1,65535)][int]$Port,
    [string]$Data = 'analytics/artifacts/powerbi',
    [string]$Output = 'artifacts/powerbi-refresh-validation.json'
)
$ErrorActionPreference = 'Stop'
$pbiBin = Join-Path $env:ProgramFiles 'Microsoft Power BI Desktop\bin'
foreach ($assembly in @('Microsoft.AnalysisServices.Server.Core.dll', 'Microsoft.AnalysisServices.Server.Tabular.dll', 'Microsoft.PowerBI.AdomdClient.dll')) {
    [System.Reflection.Assembly]::LoadFrom((Join-Path $pbiBin $assembly)) | Out-Null
}
$server = New-Object Microsoft.AnalysisServices.Tabular.Server
$server.Connect('Data Source=localhost:' + $Port)
try {
    $matches = @($server.Databases | Where-Object { $_.Model.Tables.Contains('Energy') -and $_.Model.Tables.Contains('Forecast') })
    if ($matches.Count -ne 1) { throw 'Expected exactly one Energy/Forecast model at this local port.' }
    $database = $matches[0]
    $partitions = @($database.Model.Tables | ForEach-Object { $_.Partitions } | ForEach-Object {
        if ($_.State.ToString() -ne 'Ready' -or $_.ErrorMessage) { throw 'A model partition is not ready.' }
        [ordered]@{ table=$_.Name; state=$_.State.ToString(); refreshed_at=$_.RefreshedTime.ToString('o') }
    })
    $connection = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection
    $connection.ConnectionString = 'Data Source=localhost:' + $Port + ';Initial Catalog=' + $database.Name
    $connection.Open()
    try {
        $command = $connection.CreateCommand()
        $command.CommandText = 'EVALUATE ROW("energy_kwh", [Observed energy kWh], "coverage", [Mean coverage], "devices", [Device count], "energy_rows", COUNTROWS(Energy), "forecast_rows", COUNTROWS(Forecast), "source_count", DISTINCTCOUNT(Energy[source_kind]), "source_kind", SELECTEDVALUE(Energy[source_kind]))'
        $reader = $command.ExecuteReader()
        try {
            if (-not $reader.Read()) { throw 'No model result was returned.' }
            $actual = [ordered]@{}
            for ($i=0; $i -lt $reader.FieldCount; $i++) { $actual[$reader.GetName($i).Trim('[',']')] = $reader.GetValue($i) }
            if ($reader.Read()) { throw 'Unexpected extra model result.' }
        } finally { $reader.Close() }
    } finally { $connection.Close() }
} finally { $server.Disconnect() }
if ($actual.source_count -ne 1) { throw 'The report must contain exactly one source cohort.' }
$energy = @(Import-Csv -LiteralPath (Join-Path $Data 'gold_device_daily.csv') | Where-Object { $_.source_kind -eq $actual.source_kind })
$forecast = @(Import-Csv -LiteralPath (Join-Path $Data 'forecast_daily.csv') | Where-Object { $_.source_kind -eq $actual.source_kind })
if ($energy.Count -eq 0 -or $forecast.Count -eq 0) { throw 'Reference export is empty for the loaded cohort.' }
$culture = [System.Globalization.CultureInfo]::InvariantCulture
$energySum = 0.0
$coverageSum = 0.0
foreach ($row in $energy) { $energySum += [double]::Parse($row.energy_wh, $culture); $coverageSum += [double]::Parse($row.coverage_ratio, $culture) }
$expected = [ordered]@{
    energy_kwh=$energySum/1000.0; coverage=$coverageSum/$energy.Count
    devices=@($energy.device_id | Sort-Object -Unique).Count
    energy_rows=$energy.Count; forecast_rows=$forecast.Count
}
foreach ($name in $expected.Keys) {
    if ([Math]::Abs([double]$actual[$name] - [double]$expected[$name]) -gt 0.0000001) { throw "Model/reference mismatch: $name" }
}
$result = [ordered]@{
    verified_at_utc=[DateTime]::UtcNow.ToString('o'); result='passed'
    scope='Read-only query of an already refreshed local Power BI Desktop model; no cloud connector or hosted refresh claim'
    partitions=$partitions; actual=$actual; expected=$expected; absolute_tolerance=0.0000001
}
$parent = Split-Path -Parent $Output
if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
$json = $result | ConvertTo-Json -Depth 8
Set-Content -LiteralPath $Output -Value $json -Encoding utf8
$json
