param([string]$PackageResult = ".tmp/hku/package-result.json")
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$packagePath = (Resolve-Path (Join-Path $root $PackageResult)).Path
$package = Get-Content -Raw $packagePath | ConvertFrom-Json
$archive = (Resolve-Path $package.archive).Path
$hash=[string]$package.sha256; $parent=[string]$package.parent_commit
if($hash -notmatch '^[0-9a-f]{64}$' -or $parent -notmatch '^[0-9a-f]{40}$'){throw 'Malformed package lineage'}
if((Get-FileHash $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hash){throw 'Archive drift'}
$remoteRoot='/userhome/cs2/u3665453/AgentLadder'; $remoteArchive="$remoteRoot/incoming/source-$hash.tar.gz"; $deploy="$remoteRoot/deployments/$hash"
$identity=@(ssh -o BatchMode=yes -o ConnectTimeout=15 hku-gpu2 'hostname; id -un; pwd')
if($LASTEXITCODE -ne 0 -or $identity.Count -lt 3 -or $identity[1].Trim() -ne 'u3665453' -or $identity[2].Trim() -ne '/userhome/cs2/u3665453'){throw 'HKU identity mismatch'}
$jobs=@(ssh -o BatchMode=yes hku-gpu2 "squeue -h -u u3665453 -o '%i|%P|%j|%T|%M|%l|%R'")
if($LASTEXITCODE -ne 0){throw 'Queue inspection failed'}
if($jobs.Count -gt 0 -and ($jobs -join '').Trim()){$jobs;throw 'Active job exists'}
$preflight=ssh -o BatchMode=yes hku-gpu2 "squeue -u u3665453 -o '%i|%P|%j|%T|%M|%l|%R'; quota -s 2>/dev/null || true; df -h /userhome/cs2/u3665453 | tail -n 1; if [ -e '$remoteArchive' ] || [ -e '$deploy' ]; then exit 17; fi"
if($LASTEXITCODE -ne 0){$preflight;throw 'Remote preflight failed'}; $preflight
ssh -o BatchMode=yes hku-gpu2 "mkdir -p '$remoteRoot/incoming' '$remoteRoot/deployments' '$remoteRoot/logs' '$remoteRoot/artifacts/lab-d-tiny-moe'"
if($LASTEXITCODE -ne 0){throw 'Remote directory setup failed'}
scp $archive "hku-gpu2:$remoteArchive"; if($LASTEXITCODE -ne 0){throw 'Upload failed'}
$remoteHash=(ssh -o BatchMode=yes hku-gpu2 "sha256sum '$remoteArchive' | awk '{print `$1}'").Trim()
if($LASTEXITCODE -ne 0 -or $remoteHash -ne $hash){throw 'Remote hash mismatch'}
ssh -o BatchMode=yes hku-gpu2 "mkdir '$deploy' && tar -xzf '$remoteArchive' -C '$deploy' && test -f '$deploy/scripts/hku/lab_d_tiny_moe.sbatch'"
if($LASTEXITCODE -ne 0){throw 'Extraction failed'}
ssh -o BatchMode=yes hku-gpu2 "cd '$deploy' && AGENTLADDER_SOURCE_DIR='$deploy' bash scripts/hku/bootstrap_agentladder.sh"
if($LASTEXITCODE -ne 0){throw 'Bootstrap failed'}
$exports="ALL,AGENTLADDER_SOURCE_DIR=$deploy,AGENTLADDER_SOURCE_BUNDLE_SHA256=$hash,AGENTLADDER_PARENT_COMMIT=$parent"
$job=(ssh -o BatchMode=yes hku-gpu2 "cd '$deploy' && sbatch --parsable --export='$exports' scripts/hku/lab_d_tiny_moe.sbatch").Trim()
if($LASTEXITCODE -ne 0 -or $job -notmatch '^[0-9]+$'){throw "Invalid Job ID: $job"}
$record=[ordered]@{schema_version='klara.hku-submission.v1';job_id=$job;source_bundle_sha256=$hash;parent_commit=$parent;remote_deployment=$deploy;remote_log="$remoteRoot/logs/lab-d-$job.log";remote_artifacts="$remoteRoot/artifacts/lab-d-tiny-moe/job-$job"}
$utf8=New-Object Text.UTF8Encoding($false); [IO.File]::WriteAllText((Join-Path (Split-Path $packagePath) 'lab-d-submission.json'),(($record|ConvertTo-Json)+"`n"),$utf8);$record|ConvertTo-Json
