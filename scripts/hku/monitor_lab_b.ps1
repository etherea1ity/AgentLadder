param(
    [string]$Submission = ".tmp/hku/lab-b-submission.json"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$submissionPath = (Resolve-Path (Join-Path $repositoryRoot $Submission)).Path
$record = Get-Content -Raw -LiteralPath $submissionPath | ConvertFrom-Json
$jobId = [string]$record.job_id
if ($jobId -notmatch "^[0-9]+$") {
    throw "Submission record contains an invalid Slurm Job ID"
}
$expectedLog = "/userhome/cs2/u3665453/AgentLadder/logs/lab-b-$jobId.log"
if ([string]$record.remote_log -ne $expectedLog) {
    throw "Submission record log path is outside the expected job path"
}

ssh -o BatchMode=yes -o ConnectTimeout=15 hku-gpu2 "squeue -j '$jobId' -o '%i|%P|%j|%T|%M|%l|%R'; tail -n 120 '$expectedLog' 2>/dev/null || true"
if ($LASTEXITCODE -ne 0) {
    throw "Could not read the exact Slurm job state and log"
}
