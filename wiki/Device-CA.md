# Device CA

The device CA signs the per-device client certificates used for MQTT over TLS. It lives on the owner's PC. The server receives only the root certificate and the issuing CA's CRL. Decided 2026-11-10, part of [blade-of-grass#51](https://github.com/rmx-lt/blade-of-grass/issues/51).

The tool is `tools/device-ca/device-ca.ps1`. It shells out to `openssl` (on Windows, Git for Windows puts it on PATH). Keys are ECDSA P-256.

## 1. Two tiers

| Tier | Key | Validity | Constraint | Role |
|---|---|---|---|---|
| Root | ECDSA P-256, encrypted | 20 years (7300 days) | `CA:TRUE, pathlen:1` | Signs the issuing CA only. Stays on the PC. |
| Issuing CA | ECDSA P-256, encrypted | 10 years (3650 days) | `CA:TRUE, pathlen:0` | Signs device certificates. Cannot sign another CA. |
| Device | ECDSA P-256, from the CSR | 10 years, cut short so it ends before the issuing CA | `CA:FALSE` | Client certificate. CN is the device name. |

`pathlen:1` on the root means exactly one CA may follow it in a chain. `pathlen:0` on the issuing CA means that CA signs end-entity certificates only. Putting `pathlen:0` on the root would forbid the issuing CA, and device chains would not verify.

The root key is used to create the issuing CA, and later only to replace that issuing CA by hand. Day to day, only the issuing key is used. The two keys are encrypted with AES-256-CBC under different passphrases. The root passphrase protects `private/root.key.pem` and stays on the PC, stored apart from the issuing passphrase. The issuing passphrase protects `private/issuing.key.pem` and is the only one `sign`, `revoke`, and `crl` ask for. They must differ, so moving the issuing CA to the server does not also hand over the root passphrase. The tool passes each passphrase to the `openssl` child process and does not write it to a file, the environment of the shell, the repo, or a log. `-PassFile` (issuing) and `-RootPassFile` (root) exist so the automated test can run; they are not for the real CA.

A device certificate is valid for 3650 days or until the day before the issuing CA expires, whichever is sooner. A certificate is not renewed automatically. Revocation is a CRL.

## 2. Files

The default directory is `%USERPROFILE%\.rmx-device-ca`. `-CaDir` overrides it. The tool refuses a directory inside a clone of this repo, and it refuses to run `init` again over an existing root key. On Windows it removes inherited ACLs and grants the current user full control.

```
.rmx-device-ca/
  root.pem            public root certificate
  issuing.pem         public issuing certificate
  crl.pem             public issuing-CA CRL
  openssl.cnf
  private/
    root.key.pem      encrypted root key
    issuing.key.pem   encrypted issuing key
  db/
    index.txt         openssl CA index (serial, CN, revoked or not)
    serial
    crlnumber
    newcerts/         copy of each issued device certificate
```

Names: root subject `CN=RMX Device Root CA`, issuing subject `CN=RMX Device Issuing CA`.

## 3. Create the CA

```powershell
pwsh -File tools/device-ca/device-ca.ps1 init
```

`init` asks for the root passphrase twice, then the issuing passphrase twice. The two passphrases must differ. It writes the files in section 2, and generates an empty CRL so a server can load `crl.pem` before any device is revoked. The CRL lifetime defaults to 3650 days (`-CrlDays`) so an untouched CRL does not expire and cut the devices off. Regenerate it on revoke, and again before `nextUpdate`.

## 4. Sign a device certificate

The CSR common name must match `^[A-Za-z0-9_-]{1,32}$`, the same rule as the device name, and must not be `app`, `events` or `status` (any case): the broker takes the CN as the username, so such a certificate would get a server login's ACL (all of `mower/#`) or collide with the shared topic `mower/status/server` (`events` stays reserved for the removed `mower/events/#` topics). The CSR key must be ECDSA P-256. Anything else is refused and nothing is issued. The openssl index has `unique_subject = yes`: revoke the current certificate before signing the same CN again.

```powershell
pwsh -File tools/device-ca/device-ca.ps1 sign C:\csr\mower-01.csr
```

The command asks for the issuing passphrase. It does not ask for the root passphrase.

Outputs, next to the CSR (or in `-OutDir`):

- `mower-01.device.pem`, the device certificate
- `mower-01.chain.pem`, the device certificate followed by the issuing certificate

That chain is what the device sends. Extensions on the device certificate: `basicConstraints=CA:FALSE`, `keyUsage=digitalSignature`, `extendedKeyUsage=clientAuth`, plus subject and authority key identifiers. The serial and CN are appended to `db/index.txt`.

The command prints the serial. That serial is the argument to `revoke`.

## 5. Revoke and the CRL

```powershell
pwsh -File tools/device-ca/device-ca.ps1 revoke 01
pwsh -File tools/device-ca/device-ca.ps1 revoke C:\csr\mower-01.device.pem
pwsh -File tools/device-ca/device-ca.ps1 crl
```

`revoke` and `crl` ask for the issuing passphrase. `revoke` accepts a serial from the index or a path to the certificate, marks the row revoked, and regenerates `crl.pem`. `crl` regenerates the CRL without changing the index. The CRL is PEM and is signed by the issuing CA.

Mosquitto checks the CRL of the CA that issued the client certificate. For these devices that is the issuing CA, not the root. `crl.pem` is the file to point `crlfile` at.

## 6. What is copied to the server

| File | Mosquitto setting | Notes |
|---|---|---|
| `root.pem` | `cafile` | Trust anchor for device client certificates. |
| `crl.pem` | `crlfile` | Issuing-CA CRL. Replace this file on every revoke, then reload Mosquitto. |

The device listener is port 8884 ([rmx-server-infra#67](https://github.com/rmx-lt/rmx-server-infra/issues/67)). Password logins stay on 8883. The device sends `mower-01.chain.pem` (device certificate plus issuing certificate). The server does not need a copy of the issuing certificate when the device sends that chain.

## 7. What never leaves the PC

- `private/root.key.pem` and the root passphrase. Keep that passphrase on the PC, separate from the issuing passphrase, including after the move in section 8.
- `private/issuing.key.pem` and the issuing passphrase, until the move in section 8
- `db/` (the index, serials, and copies of issued certificates)

`root.pem`, `issuing.pem`, and `crl.pem` are the public files. The chain file goes to the device it belongs to.

## 8. Moving the issuing CA later

Device management on the server ([rmx-server-app#42](https://github.com/rmx-lt/rmx-server-app/issues/42)) can take over signing without reissuing device certificates. The issuing certificate stays the same, so existing device certificates still chain to the same root.

What moves is this issuing key, its passphrase, `issuing.pem`, and `db/` (the index has to come with the key, or a serial could be reused). The root key and the root passphrase stay on the PC. Devices keep the certificates they already have, because the issuer is the same certificate. Minting a second issuing CA is a different change: it does not invalidate certificates the current issuing CA already signed, and it is not required for the move.

Replacing the issuing CA is not a command in this tool. Do it by hand on the PC: create a new issuing key encrypted with the issuing passphrase, then sign that request with `openssl x509 -req -CA root.pem -CAkey private/root.key.pem` and the root passphrase. `sign`, `revoke`, and `crl` never use the root key.
