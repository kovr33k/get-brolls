# Release gates for the current checkout or an explicitly selected commit.
#requires -Version 7.0
param(
    [string]$Ref,
    [string]$Version,
    [string]$CiRepository,
    [string]$CiRun,
    [string]$NotesFile
)
$ErrorActionPreference = 'Stop'
$preflightArgs = @()
foreach ($entry in @{
    '--ref' = $Ref; '--version' = $Version; '--ci-repository' = $CiRepository;
    '--ci-run' = $CiRun; '--notes-file' = $NotesFile
}.GetEnumerator()) {
    if ($entry.Value) { $preflightArgs += @($entry.Key, $entry.Value) }
}
& python (Join-Path $PSScriptRoot 'preflight.py') @preflightArgs
if ($LASTEXITCODE -ne 0) { throw "Release preflight failed (exit $LASTEXITCODE)" }
