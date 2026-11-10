<#
.SYNOPSIS
  Two-tier device CA for Blade of Grass client certificates. wiki Device-CA.

.DESCRIPTION
  Shells out to openssl (Git for Windows is fine). Creates an offline root and
  an issuing CA, signs device CSRs, and writes the issuing CA's CRL.

  The passphrase is typed at the prompt. It is handed to the openssl child
  process only, and is never written to a file, the repo, or the log.
  -PassFile is for the automated test: do not use it for the real CA.

.EXAMPLE
  pwsh -File tools/device-ca/device-ca.ps1 init

.EXAMPLE
  pwsh -File tools/device-ca/device-ca.ps1 sign C:\csr\mower-01.csr

.EXAMPLE
  pwsh -File tools/device-ca/device-ca.ps1 revoke 01

.EXAMPLE
  pwsh -File tools/device-ca/device-ca.ps1 crl
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('init', 'sign', 'revoke', 'crl')]
    [string]$Command,

    [Parameter(Position = 1)]
    [string]$Argument,

    [string]$CaDir = (Join-Path $env:USERPROFILE '.rmx-device-ca'),

    [string]$OutDir,

    # Test only. Reads the passphrase from a file. Never use this for the real CA.
    [string]$PassFile,

    [int]$RootDays = 7300,
    [int]$IssuingDays = 3650,
    [int]$DeviceDays = 3650,
    [int]$CrlDays = 3650
)

$ErrorActionPreference = 'Stop'

$RootCn = 'RMX Device Root CA'
$IssuingCn = 'RMX Device Issuing CA'
$CnPattern = '^[A-Za-z0-9_-]{1,32}$'

function Write-Err([string]$Message) {
    [Console]::Error.WriteLine($Message)
}

function Find-OpenSsl {
    $cmd = Get-Command openssl -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }
    $candidates = @(
        (Join-Path $env:ProgramFiles 'Git\usr\bin\openssl.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Git\usr\bin\openssl.exe')
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    throw 'openssl was not found. Install Git for Windows or put openssl on PATH.'
}

function ConvertTo-OpenSslPath([string]$Path) {
    return ([IO.Path]::GetFullPath($Path) -replace '\\', '/')
}

function Protect-Directory([string]$Path) {
    & icacls $Path /inheritance:r /grant:r "${env:USERNAME}:(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Err "warning: could not restrict the ACL on $Path (icacls exit $LASTEXITCODE)."
    }
}

function Assert-CaDirOutsideRepo([string]$Path) {
    $resolved = [IO.Path]::GetFullPath($Path)
    $git = & git -C $PSScriptRoot rev-parse --show-toplevel 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($git)) { return }
    $repo = [IO.Path]::GetFullPath($git.Trim())
    $prefix = $repo.TrimEnd('\', '/')
    if ($resolved.Equals($prefix, [StringComparison]::OrdinalIgnoreCase) -or
        $resolved.StartsWith($prefix + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "CA directory must be outside the git repo ($repo). The default is `$env:USERPROFILE\.rmx-device-ca."
    }
}

function Read-Passphrase([bool]$Confirm) {
    if ($PassFile) {
        Write-Err '-PassFile is for tests only. Do not store the real CA passphrase in a file.'
        if (-not (Test-Path -LiteralPath $PassFile)) { throw "PassFile not found: $PassFile" }
        $text = [IO.File]::ReadAllText($PassFile) -replace '[\r\n]+$', ''
        if ([string]::IsNullOrEmpty($text)) { throw 'PassFile is empty.' }
        return $text
    }
    $first = Read-Host -AsSecureString 'CA passphrase'
    $plain = ConvertFrom-SecureStringPlain $first
    if ([string]::IsNullOrEmpty($plain)) { throw 'A passphrase is required.' }
    if ($Confirm) {
        $second = Read-Host -AsSecureString 'Confirm CA passphrase'
        $again = ConvertFrom-SecureStringPlain $second
        if ($plain -cne $again) {
            $plain = $null
            $again = $null
            throw 'Passphrases did not match.'
        }
        $again = $null
    }
    return $plain
}

function ConvertFrom-SecureStringPlain([Security.SecureString]$Secure) {
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Invoke-OpenSsl {
    param(
        [Parameter(Mandatory)][string[]]$ArgumentList,
        [string]$Passphrase,
        [string]$WorkingDirectory
    )
    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $script:OpenSsl
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    if ($WorkingDirectory) { $psi.WorkingDirectory = $WorkingDirectory }
    foreach ($arg in $ArgumentList) { [void]$psi.ArgumentList.Add($arg) }
    if ($null -ne $Passphrase) { $psi.Environment['RMX_DEVICE_CA_PASS'] = $Passphrase }
    $proc = [System.Diagnostics.Process]::new()
    $proc.StartInfo = $psi
    [void]$proc.Start()
    $outTask = $proc.StandardOutput.ReadToEndAsync()
    $errTask = $proc.StandardError.ReadToEndAsync()
    if (-not $proc.WaitForExit(120000)) {
        try { $proc.Kill($true) } catch { $proc.Kill() }
        throw "openssl timed out ($($ArgumentList[0]))."
    }
    $proc.WaitForExit()
    return [pscustomobject]@{
        ExitCode = $proc.ExitCode
        StdOut   = $outTask.Result
        StdErr   = $errTask.Result
    }
}

function Assert-OpenSsl($Result, [string]$What) {
    if ($Result.ExitCode -ne 0) {
        $detail = (($Result.StdErr + "`n" + $Result.StdOut).Trim())
        throw "$What failed (openssl exit $($Result.ExitCode)): $detail"
    }
}

function Get-CaPaths([string]$Root) {
    $db = Join-Path $Root 'db'
    return [pscustomobject]@{
        Root        = $Root
        Config      = Join-Path $Root 'openssl.cnf'
        RootCert    = Join-Path $Root 'root.pem'
        IssuingCert = Join-Path $Root 'issuing.pem'
        Crl         = Join-Path $Root 'crl.pem'
        Private     = Join-Path $Root 'private'
        RootKey     = Join-Path $Root 'private\root.key.pem'
        IssuingKey  = Join-Path $Root 'private\issuing.key.pem'
        Db          = $db
        Index       = Join-Path $db 'index.txt'
        NewCerts    = Join-Path $db 'newcerts'
        RootSerial  = Join-Path $db 'root.srl'
    }
}

function Assert-CaReady($Paths) {
    foreach ($file in @($Paths.RootCert, $Paths.IssuingCert, $Paths.IssuingKey, $Paths.Config, $Paths.Index)) {
        if (-not (Test-Path -LiteralPath $file)) {
            throw "CA is not initialised in $($Paths.Root) (missing $file). Run init first."
        }
    }
}

function Write-CaConfig($Paths) {
    $db = ConvertTo-OpenSslPath $Paths.Db
    $cert = ConvertTo-OpenSslPath $Paths.IssuingCert
    $key = ConvertTo-OpenSslPath $Paths.IssuingKey
    $crl = ConvertTo-OpenSslPath $Paths.Crl
    $text = @"
# Generated by tools/device-ca/device-ca.ps1. wiki Device-CA §2.
# Paths point at this CA directory. The private keys stay in private/.

[ ca ]
default_ca = issuing

[ issuing ]
dir              = $db
database         = `$dir/index.txt
new_certs_dir    = `$dir/newcerts
certificate      = $cert
private_key      = $key
serial           = `$dir/serial
crlnumber        = `$dir/crlnumber
crl              = $crl
crl_extensions   = crl_ext
default_crl_days = $CrlDays
default_md       = sha256
default_days     = $DeviceDays
policy           = device_policy
unique_subject   = yes
copy_extensions  = none
x509_extensions  = device_ext

[ device_policy ]
commonName             = supplied
countryName            = optional
stateOrProvinceName    = optional
localityName           = optional
organizationName       = optional
organizationalUnitName = optional
emailAddress           = optional

[ device_ext ]
basicConstraints       = critical,CA:FALSE
keyUsage               = critical,digitalSignature
extendedKeyUsage       = clientAuth
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid,issuer

[ crl_ext ]
authorityKeyIdentifier = keyid:always

[ req ]
distinguished_name = req_dn
prompt             = no
string_mask        = utf8only
default_md         = sha256

[ req_dn ]
commonName = unused

[ v3_root ]
basicConstraints     = critical,CA:TRUE,pathlen:1
keyUsage             = critical,keyCertSign,cRLSign
subjectKeyIdentifier = hash

[ v3_issuing ]
basicConstraints       = critical,CA:TRUE,pathlen:0
keyUsage               = critical,keyCertSign,cRLSign
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always,issuer
"@
    $utf8 = [Text.UTF8Encoding]::new($false)
    [IO.File]::WriteAllText($Paths.Config, $text.Replace("`r`n", "`n"), $utf8)
}

function Write-TextFile([string]$Path, [string]$Content) {
    $utf8 = [Text.UTF8Encoding]::new($false)
    [IO.File]::WriteAllText($Path, $Content, $utf8)
}

function New-EncryptedKey([string]$Path, [string]$Passphrase, [string]$WorkingDirectory) {
    $result = Invoke-OpenSsl -WorkingDirectory $WorkingDirectory -Passphrase $Passphrase -ArgumentList @(
        'genpkey', '-algorithm', 'EC', '-pkeyopt', 'ec_paramgen_curve:P-256',
        '-aes-256-cbc', '-pass', 'env:RMX_DEVICE_CA_PASS', '-out', $Path
    )
    Assert-OpenSsl $result "generate key $Path"
}

function Get-CsrCommonName([string]$CsrPath) {
    $result = Invoke-OpenSsl -ArgumentList @('req', '-in', $CsrPath, '-noout', '-verify', '-subject', '-nameopt', 'RFC2253')
    if ($result.ExitCode -ne 0) {
        $detail = ($result.StdErr + $result.StdOut).Trim()
        throw "Cannot read CSR ($detail)."
    }
    $blob = ($result.StdOut + "`n" + $result.StdErr)
    if ($blob -notmatch 'verify OK') { throw 'CSR signature did not verify.' }
    $subjectLine = ($blob -split '\r?\n' | Where-Object { $_ -match 'CN=' } | Select-Object -First 1)
    if (-not $subjectLine) { throw 'CSR has no CN.' }
    $subject = ($subjectLine -replace '^subject=', '').Trim()
    $names = @()
    foreach ($part in ($subject -split '(?<!\\),')) {
        $part = $part.Trim()
        if ($part -match '^CN=(.*)$') { $names += $Matches[1] }
    }
    if ($names.Count -ne 1) { throw "CSR must contain exactly one CN (found $($names.Count))." }
    return $names[0]
}

function Assert-DeviceCsr([string]$CsrPath) {
    $cn = Get-CsrCommonName $CsrPath
    if ($cn -notmatch $CnPattern) {
        Write-Err "Refusing CSR: CN '$cn' does not match $CnPattern (the device-name rule)."
        exit 2
    }
    $text = Invoke-OpenSsl -ArgumentList @('req', '-in', $CsrPath, '-noout', '-text')
    Assert-OpenSsl $text 'read CSR key'
    if ($text.StdOut -notmatch 'prime256v1') {
        Write-Err "Refusing CSR: CN '$cn' must use an ECDSA P-256 key (prime256v1)."
        exit 2
    }
    return $cn
}

function Get-CertificateEnd([string]$CertPath) {
    $result = Invoke-OpenSsl -ArgumentList @('x509', '-in', $CertPath, '-noout', '-enddate')
    Assert-OpenSsl $result 'read certificate end date'
    $line = ($result.StdOut.Trim() -split '\r?\n' | Select-Object -First 1)
    if ($line -notmatch '^notAfter=(.+)$') { throw "Unexpected end date line: $line" }
    $raw = ($Matches[1].Trim() -replace '\s+', ' ')
    $parsed = [DateTime]::ParseExact(
        $raw,
        'MMM d HH:mm:ss yyyy GMT',
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::AssumeUniversal -bor [Globalization.DateTimeStyles]::AdjustToUniversal)
    return $parsed
}

function Get-DeviceDays([string]$IssuingCert) {
    $end = Get-CertificateEnd $IssuingCert
    $remaining = [int][Math]::Floor(($end - [DateTime]::UtcNow).TotalDays) - 1
    $days = [Math]::Min($DeviceDays, $remaining)
    if ($days -lt 1) { throw 'The issuing CA expires too soon to sign a device certificate.' }
    return $days
}

function Write-Chain([string]$DeviceCert, [string]$IssuingCert, [string]$ChainPath) {
    $leaf = [IO.File]::ReadAllText($DeviceCert)
    $issuer = [IO.File]::ReadAllText($IssuingCert)
    if (-not $leaf.EndsWith("`n")) { $leaf += "`n" }
    $utf8 = [Text.UTF8Encoding]::new($false)
    [IO.File]::WriteAllText($ChainPath, $leaf + $issuer, $utf8)
}

function Update-Crl($Paths, [string]$Passphrase) {
    $result = Invoke-OpenSsl -WorkingDirectory $Paths.Root -Passphrase $Passphrase -ArgumentList @(
        'ca', '-config', $Paths.Config, '-gencrl', '-crldays', "$CrlDays",
        '-out', $Paths.Crl, '-passin', 'env:RMX_DEVICE_CA_PASS'
    )
    Assert-OpenSsl $result 'generate CRL'
}

function Get-IssuedSerial($Paths, [string]$CommonName) {
    $rows = @(Get-IndexRows $Paths)
    $pattern = '(^|/)' + [regex]::Escape("CN=$CommonName") + '($|/)'
    $match = $rows | Where-Object { $_.Status -eq 'V' -and $_.Subject -match $pattern } | Select-Object -Last 1
    if (-not $match) { throw "Signed $CommonName but it is not a valid row in the CA index." }
    return $match.Serial
}

function Get-IndexRows($Paths) {
    $rows = @()
    foreach ($line in [IO.File]::ReadAllLines($Paths.Index)) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $fields = $line -split "`t", 6
        if ($fields.Count -lt 6) { continue }
        $rows += [pscustomobject]@{
            Status  = $fields[0]
            Expiry  = $fields[1]
            Revoked = $fields[2]
            Serial  = $fields[3]
            File    = $fields[4]
            Subject = $fields[5]
        }
    }
    return $rows
}

function Resolve-RevokeCert($Paths, [string]$SerialOrCert) {
    if (Test-Path -LiteralPath $SerialOrCert) {
        return [IO.Path]::GetFullPath($SerialOrCert)
    }
    $want = ($SerialOrCert -replace '^(?i)0x', '').Trim()
    $rows = @(Get-IndexRows $Paths)
    $match = $rows | Where-Object { $_.Serial -eq $want -or ($_.Serial.TrimStart('0') -eq $want.TrimStart('0') -and $_.Serial -match '^[0-9A-Fa-f]+$' -and $want -match '^[0-9A-Fa-f]+$') } | Select-Object -Last 1
    if (-not $match) { throw "No issued certificate for serial '$SerialOrCert'." }
    if ($match.Status -eq 'R') {
        return [pscustomobject]@{ Already = $true; Serial = $match.Serial }
    }
    $fileName = $match.Serial + '.pem'
    $path = Join-Path $Paths.NewCerts $fileName
    if (-not (Test-Path -LiteralPath $path)) { throw "Index lists serial $($match.Serial) but $path is missing." }
    return [pscustomobject]@{ Already = $false; Path = $path; Serial = $match.Serial }
}

function Initialize-Ca([string]$Passphrase) {
    Assert-CaDirOutsideRepo $CaDir
    if ($RootDays -lt 2) { throw '-RootDays must be at least 2.' }
    if ($IssuingDays -ge $RootDays) { throw '-IssuingDays must be shorter than -RootDays so the issuing certificate expires first.' }
    if ($DeviceDays -lt 1 -or $CrlDays -lt 1) { throw '-DeviceDays and -CrlDays must be at least 1.' }
    if (Test-Path -LiteralPath (Join-Path $CaDir 'private\root.key.pem')) {
        throw "A CA already exists in $CaDir. Refusing to overwrite it."
    }
    New-Item -ItemType Directory -Path $CaDir -Force | Out-Null
    Protect-Directory $CaDir
    $paths = Get-CaPaths $CaDir
    New-Item -ItemType Directory -Path $paths.Private -Force | Out-Null
    New-Item -ItemType Directory -Path $paths.Db -Force | Out-Null
    New-Item -ItemType Directory -Path $paths.NewCerts -Force | Out-Null
    Protect-Directory $paths.Private
    Write-TextFile $paths.Index ''
    Write-TextFile (Join-Path $paths.Db 'index.txt.attr') "unique_subject = yes`n"
    Write-TextFile (Join-Path $paths.Db 'serial') "01`n"
    Write-TextFile (Join-Path $paths.Db 'crlnumber') "01`n"
    Write-CaConfig $paths

    New-EncryptedKey $paths.RootKey $Passphrase $paths.Root
    $root = Invoke-OpenSsl -WorkingDirectory $paths.Root -Passphrase $Passphrase -ArgumentList @(
        'req', '-new', '-x509', '-key', $paths.RootKey, '-passin', 'env:RMX_DEVICE_CA_PASS',
        '-out', $paths.RootCert, '-days', "$RootDays", '-sha256',
        '-subj', "/CN=$RootCn", '-config', $paths.Config, '-extensions', 'v3_root'
    )
    Assert-OpenSsl $root 'create root certificate'

    New-EncryptedKey $paths.IssuingKey $Passphrase $paths.Root
    $csr = Join-Path $paths.Db 'issuing.csr.pem'
    $request = Invoke-OpenSsl -WorkingDirectory $paths.Root -Passphrase $Passphrase -ArgumentList @(
        'req', '-new', '-key', $paths.IssuingKey, '-passin', 'env:RMX_DEVICE_CA_PASS',
        '-out', $csr, '-sha256', '-subj', "/CN=$IssuingCn"
    )
    Assert-OpenSsl $request 'create issuing CSR'
    $issued = Invoke-OpenSsl -WorkingDirectory $paths.Root -Passphrase $Passphrase -ArgumentList @(
        'x509', '-req', '-in', $csr, '-CA', $paths.RootCert, '-CAkey', $paths.RootKey,
        '-passin', 'env:RMX_DEVICE_CA_PASS', '-CAserial', $paths.RootSerial, '-CAcreateserial',
        '-out', $paths.IssuingCert, '-days', "$IssuingDays", '-sha256',
        '-extfile', $paths.Config, '-extensions', 'v3_issuing'
    )
    Assert-OpenSsl $issued 'sign issuing CA'
    Remove-Item -LiteralPath $csr -Force
    Update-Crl $paths $Passphrase

    Write-Output "Root certificate: $($paths.RootCert)"
    Write-Output "Issuing certificate: $($paths.IssuingCert)"
    Write-Output "CRL: $($paths.Crl)"
    Write-Output "Private keys stay in $($paths.Private)"
}

function Sign-Device([string]$Passphrase) {
    if ([string]::IsNullOrWhiteSpace($Argument)) { throw 'sign needs a CSR path.' }
    if (-not (Test-Path -LiteralPath $Argument)) { throw "CSR not found: $Argument" }
    $csr = [IO.Path]::GetFullPath($Argument)
    Assert-CaDirOutsideRepo $CaDir
    $paths = Get-CaPaths ([IO.Path]::GetFullPath($CaDir))
    Assert-CaReady $paths
    $cn = Assert-DeviceCsr $csr
    $days = Get-DeviceDays $paths.IssuingCert
    $destDir = if ($OutDir) { [IO.Path]::GetFullPath($OutDir) } else { [IO.Path]::GetDirectoryName($csr) }
    New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    $base = [IO.Path]::GetFileNameWithoutExtension($csr)
    $deviceCert = Join-Path $destDir "$base.device.pem"
    $chain = Join-Path $destDir "$base.chain.pem"
    $signed = Invoke-OpenSsl -WorkingDirectory $paths.Root -Passphrase $Passphrase -ArgumentList @(
        'ca', '-config', $paths.Config, '-in', $csr, '-out', $deviceCert,
        '-batch', '-notext', '-days', "$days", '-md', 'sha256',
        '-passin', 'env:RMX_DEVICE_CA_PASS'
    )
    Assert-OpenSsl $signed "sign $cn"
    Write-Chain $deviceCert $paths.IssuingCert $chain
    $serial = Get-IssuedSerial $paths $cn
    Write-Output "Serial: $serial"
    Write-Output "CN: $cn"
    Write-Output "Days: $days"
    Write-Output "Device certificate: $deviceCert"
    Write-Output "Chain: $chain"
}

function Revoke-Device([string]$Passphrase) {
    if ([string]::IsNullOrWhiteSpace($Argument)) { throw 'revoke needs a serial or a certificate path.' }
    Assert-CaDirOutsideRepo $CaDir
    $paths = Get-CaPaths ([IO.Path]::GetFullPath($CaDir))
    Assert-CaReady $paths
    $target = Resolve-RevokeCert $paths $Argument
    if ($target -is [string]) {
        $revoked = Invoke-OpenSsl -WorkingDirectory $paths.Root -Passphrase $Passphrase -ArgumentList @(
            'ca', '-config', $paths.Config, '-revoke', $target, '-batch',
            '-passin', 'env:RMX_DEVICE_CA_PASS'
        )
        Assert-OpenSsl $revoked 'revoke certificate'
        Write-Output "Revoked certificate: $target"
    }
    elseif ($target.Already) {
        Write-Output "Serial $($target.Serial) is already revoked."
    }
    else {
        $revoked = Invoke-OpenSsl -WorkingDirectory $paths.Root -Passphrase $Passphrase -ArgumentList @(
            'ca', '-config', $paths.Config, '-revoke', $target.Path, '-batch',
            '-passin', 'env:RMX_DEVICE_CA_PASS'
        )
        Assert-OpenSsl $revoked "revoke serial $($target.Serial)"
        Write-Output "Revoked serial: $($target.Serial)"
    }
    Update-Crl $paths $Passphrase
    Write-Output "CRL: $($paths.Crl)"
}

function Export-Crl([string]$Passphrase) {
    Assert-CaDirOutsideRepo $CaDir
    $paths = Get-CaPaths ([IO.Path]::GetFullPath($CaDir))
    Assert-CaReady $paths
    Update-Crl $paths $Passphrase
    Write-Output "CRL: $($paths.Crl)"
}

if (-not $Command) {
    Write-Err 'Usage: device-ca.ps1 init|sign|revoke|crl [csr|serial|cert] [-CaDir path] [-PassFile test-only]'
    exit 2
}

$script:OpenSsl = Find-OpenSsl
$pass = $null
try {
    $needsConfirm = $Command -eq 'init' -and -not $PassFile
    $pass = Read-Passphrase $needsConfirm
    switch ($Command) {
        'init' { Initialize-Ca $pass }
        'sign' { Sign-Device $pass }
        'revoke' { Revoke-Device $pass }
        'crl' { Export-Crl $pass }
    }
}
catch {
    Write-Err $_.Exception.Message
    exit 1
}
finally {
    if ($null -ne $pass) {
        $pass = $null
    }
}
exit 0
