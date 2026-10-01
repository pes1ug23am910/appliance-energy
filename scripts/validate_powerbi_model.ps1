param([string]$Project = "artifacts/powerbi")
$ErrorActionPreference = 'Stop'
$pbiBin = Join-Path $env:ProgramFiles 'Microsoft Power BI Desktop\bin'
foreach ($assembly in @('Microsoft.AnalysisServices.Server.Core.dll', 'Microsoft.AnalysisServices.Server.Tabular.dll', 'Microsoft.AnalysisServices.Server.Tabular.Json.dll')) {
    [System.Reflection.Assembly]::LoadFrom((Join-Path $pbiBin $assembly)) | Out-Null
}
$modelPath = Join-Path $Project 'Energy.SemanticModel\model.bim'
$modelDatabase = [Microsoft.AnalysisServices.Tabular.JsonSerializer]::DeserializeDatabase((Get-Content -LiteralPath $modelPath -Raw))
[pscustomobject]@{
    Name = $modelDatabase.Name
    Tables = $modelDatabase.Model.Tables.Count
    Measures = $modelDatabase.Model.Tables[0].Measures.Count
    Compatibility = $modelDatabase.CompatibilityLevel
    Scope = 'Tabular deserialization only; no refresh, query execution or visual rendering'
} | ConvertTo-Json
