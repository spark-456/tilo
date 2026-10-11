param(
    [Parameter(Mandatory=$true)][string]$ApiUrl,
    [Parameter(Mandatory=$true)][string]$MeetingId
)
$ErrorActionPreference = 'Stop'
if($ApiUrl -notmatch '^https://[A-Za-z0-9-]+\.run\.app$' -or
   $MeetingId -notmatch '^mt_[A-Za-z0-9_]{1,48}$') { throw 'Invalid API URL or meeting ID' }

function Read-LocalToken([string]$Label) {
    $secure = Read-Host $Label -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer); $secure.Dispose() }
}

$headers = @{}
try {
    $headers['Authorization'] = 'Bearer ' + (Read-LocalToken 'Owner Firebase ID token')
    $headers['X-Firebase-AppCheck'] = Read-LocalToken 'Owner App Check token'
    $headers['X-Tilo-Channel'] = 'mobile_web'
    Invoke-RestMethod -Method Post -Uri "$ApiUrl/v1/meetings/$MeetingId/attend" `
        -Headers $headers -ContentType 'application/json' -Body '{}' -TimeoutSec 3540
} catch {
    throw 'Attendance did not complete. Inspect the owner meeting state before retrying.'
} finally {
    $headers.Clear()
}
