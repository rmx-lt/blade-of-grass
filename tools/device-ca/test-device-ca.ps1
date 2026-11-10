# Throwaway CA test for tools/device-ca/device-ca.ps1. wiki Device-CA.
# Uses -PassFile, which is test-only. Deletes the CA directory before exiting.
$ErrorActionPreference = 'Stop'

$openssl = $null
$cmd = Get-Command openssl -ErrorAction SilentlyContinue
if ($cmd) { $openssl = $cmd.Source }
if (-not $openssl) { $openssl = 'C:\Program Files\Git\usr\bin\openssl.exe' }
if (-not (Test-Path -LiteralPath $openssl)) { throw "openssl not found: $openssl" }

$tool = Join-Path $PSScriptRoot 'device-ca.ps1'
$pwsh = (Get-Command pwsh).Source
$work = Join-Path $env:TEMP ("rmx device-ca test " + [guid]::NewGuid().ToString('n'))
$defaultCa = Join-Path $env:USERPROFILE '.rmx-device-ca'
$defaultBefore = Test-Path -LiteralPath $defaultCa
$proto = Join-Path $env:TEMP 'rmx ca proto'

function Invoke-Tool {
    param([string[]]$ArgumentList)
    & $pwsh -NoProfile -File $tool @ArgumentList | Write-Host
    return $LASTEXITCODE
}

function Assert-Exit([int]$Actual, [int]$Expected, [string]$What) {
    if ($Actual -ne $Expected) { throw "$What : exit $Actual, expected $Expected" }
}

try {
    if (Test-Path -LiteralPath $proto) { Remove-Item -LiteralPath $proto -Recurse -Force }
    New-Item -ItemType Directory -Path $work | Out-Null
    $passFile = Join-Path $work 'pass.txt'
    $passphrase = 'throwaway-test-passphrase'
    [IO.File]::WriteAllText($passFile, $passphrase)

    $ca = Join-Path $work 'ca'
    $code = Invoke-Tool @('init', '-CaDir', $ca, '-PassFile', $passFile)
    Assert-Exit $code 0 'init'

    foreach ($name in @('root.key.pem', 'issuing.key.pem')) {
        $keyPath = Join-Path $ca "private\$name"
        $head = Get-Content -LiteralPath $keyPath -TotalCount 1
        if ($head -notmatch 'ENCRYPTED PRIVATE KEY') { throw "$name is not an encrypted private key: $head" }
    }

    $deviceKey = Join-Path $work 'device.key.pem'
    & $openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out $deviceKey
    if ($LASTEXITCODE -ne 0) { throw 'device key generation failed' }
    $csr = Join-Path $work 'mower-01.csr'
    & $openssl req -new -key $deviceKey -out $csr -sha256 -subj '/CN=mower-01'
    if ($LASTEXITCODE -ne 0) { throw 'device CSR failed' }

    $code = Invoke-Tool @('sign', $csr, '-CaDir', $ca, '-PassFile', $passFile)
    Assert-Exit $code 0 'sign'
    $device = Join-Path $work 'mower-01.device.pem'
    $chain = Join-Path $work 'mower-01.chain.pem'
    if (-not (Test-Path -LiteralPath $device) -or -not (Test-Path -LiteralPath $chain)) {
        throw 'sign did not write the device certificate and chain'
    }

    Write-Output '===== VERIFY ====='
    & $openssl verify -CAfile (Join-Path $ca 'root.pem') -untrusted (Join-Path $ca 'issuing.pem') $device
    if ($LASTEXITCODE -ne 0) { throw 'verify did not return OK' }

    Write-Output '===== VERIFY CRL BEFORE REVOKE ====='
    & $openssl verify -CAfile (Join-Path $ca 'root.pem') -untrusted (Join-Path $ca 'issuing.pem') -crl_check -CRLfile (Join-Path $ca 'crl.pem') $device
    if ($LASTEXITCODE -ne 0) { throw 'crl_check before revoke should succeed' }

    Write-Output '===== DEVICE CERTIFICATE ====='
    & $openssl x509 -in $device -noout -text

    $badKey = Join-Path $work 'bad.key.pem'
    & $openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out $badKey
    if ($LASTEXITCODE -ne 0) { throw 'bad key generation failed' }
    $badCsr = Join-Path $work 'bad.csr'
    & $openssl req -new -key $badKey -out $badCsr -sha256 -subj '/CN=mower.01'
    if ($LASTEXITCODE -ne 0) { throw 'bad CSR failed' }
    Write-Output '===== BAD CN ====='
    $code = Invoke-Tool @('sign', $badCsr, '-CaDir', $ca, '-PassFile', $passFile)
    Write-Output "bad CN exit: $code"
    if ($code -eq 0) { throw 'bad CN was signed' }
    if (Test-Path -LiteralPath (Join-Path $work 'bad.device.pem')) { throw 'bad CN wrote a certificate' }

    $longCn = 'a' * 33
    $longCsr = Join-Path $work 'long.csr'
    & $openssl req -new -key $badKey -out $longCsr -sha256 -subj "/CN=$longCn"
    if ($LASTEXITCODE -ne 0) { throw 'long CN CSR failed' }
    $code = Invoke-Tool @('sign', $longCsr, '-CaDir', $ca, '-PassFile', $passFile)
    if ($code -eq 0) { throw '33-character CN was signed' }

    $rsaKey = Join-Path $work 'rsa.key.pem'
    $rsaCsr = Join-Path $work 'rsa.csr'
    & $openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out $rsaKey
    if ($LASTEXITCODE -ne 0) { throw 'rsa key failed' }
    & $openssl req -new -key $rsaKey -out $rsaCsr -sha256 -subj '/CN=mower-02'
    if ($LASTEXITCODE -ne 0) { throw 'rsa CSR failed' }
    $code = Invoke-Tool @('sign', $rsaCsr, '-CaDir', $ca, '-PassFile', $passFile)
    if ($code -eq 0) { throw 'non-P-256 CSR was signed' }

    $code = Invoke-Tool @('revoke', '01', '-CaDir', $ca, '-PassFile', $passFile)
    Assert-Exit $code 0 'revoke serial'
    Write-Output '===== VERIFY REVOKED ====='
    & $openssl verify -CAfile (Join-Path $ca 'root.pem') -untrusted (Join-Path $ca 'issuing.pem') -crl_check -CRLfile (Join-Path $ca 'crl.pem') $device
    if ($LASTEXITCODE -eq 0) { throw 'revoked certificate still verified' }

    $csr2 = Join-Path $work 'mower-02.csr'
    & $openssl req -new -key $deviceKey -out $csr2 -sha256 -subj '/CN=mower_02'
    if ($LASTEXITCODE -ne 0) { throw 'second CSR failed' }
    $code = Invoke-Tool @('sign', $csr2, '-CaDir', $ca, '-PassFile', $passFile)
    Assert-Exit $code 0 'sign second'
    $device2 = Join-Path $work 'mower-02.device.pem'
    $code = Invoke-Tool @('revoke', $device2, '-CaDir', $ca, '-PassFile', $passFile)
    Assert-Exit $code 0 'revoke cert path'
    & $openssl verify -CAfile (Join-Path $ca 'root.pem') -untrusted (Join-Path $ca 'issuing.pem') -crl_check -CRLfile (Join-Path $ca 'crl.pem') $device2
    if ($LASTEXITCODE -eq 0) { throw 'certificate-path revoke did not stick' }

    $wrong = Join-Path $work 'wrong.txt'
    [IO.File]::WriteAllText($wrong, 'not-the-passphrase')
    $code = Invoke-Tool @('crl', '-CaDir', $ca, '-PassFile', $wrong)
    if ($code -eq 0) { throw 'wrong passphrase was accepted' }

    $capCa = Join-Path $work 'cap'
    $code = Invoke-Tool @('init', '-CaDir', $capCa, '-PassFile', $passFile, '-RootDays', '40', '-IssuingDays', '30', '-DeviceDays', '3650', '-CrlDays', '10')
    Assert-Exit $code 0 'short init'
    $capCsr = Join-Path $work 'cap.csr'
    & $openssl req -new -key $deviceKey -out $capCsr -sha256 -subj '/CN=mower-03'
    if ($LASTEXITCODE -ne 0) { throw 'cap CSR failed' }
    $code = Invoke-Tool @('sign', $capCsr, '-CaDir', $capCa, '-PassFile', $passFile, '-DeviceDays', '3650')
    Assert-Exit $code 0 'cap sign'
    $capCert = Join-Path $work 'cap.device.pem'
    $endLine = & $openssl x509 -in $capCert -noout -enddate
    $issEnd = & $openssl x509 -in (Join-Path $capCa 'issuing.pem') -noout -enddate
    if ($LASTEXITCODE -ne 0) { throw 'could not read cap dates' }
    Write-Output "cap device $endLine"
    Write-Output "cap issuing $issEnd"
    $deviceEnd = [DateTime]::ParseExact(($endLine -replace '^notAfter=', '' -replace '\s+', ' ').Trim(), 'MMM d HH:mm:ss yyyy GMT', [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::AssumeUniversal)
    $issuingEnd = [DateTime]::ParseExact(($issEnd -replace '^notAfter=', '' -replace '\s+', ' ').Trim(), 'MMM d HH:mm:ss yyyy GMT', [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::AssumeUniversal)
    if ($deviceEnd -ge $issuingEnd) { throw 'device certificate outlives the issuing CA' }
    if (($deviceEnd - [DateTime]::UtcNow).TotalDays -gt 40) { throw 'device lifetime was not capped by the issuing CA' }

    $hits = Get-ChildItem -LiteralPath $ca -Recurse -File | Where-Object {
        $text = [IO.File]::ReadAllText($_.FullName)
        $text.Contains($passphrase)
    }
    if ($hits) { throw "passphrase was written into the CA directory: $($hits.FullName -join ', ')" }

    $createdDefault = (-not $defaultBefore) -and (Test-Path -LiteralPath $defaultCa)
    if ($createdDefault) { throw "test created the default CA directory $defaultCa" }

    Write-Output '===== TEST PASSED ====='
}
finally {
    if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force }
    if (Test-Path -LiteralPath $proto) { Remove-Item -LiteralPath $proto -Recurse -Force }
}
