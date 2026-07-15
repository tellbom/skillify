# Offline OpenCode v1.15.11 deployment

This procedure installs the S1-approved OpenCode v1.15.11 binary on disconnected
Linux endpoints. Runtime public downloads are prohibited. The six approved
source URLs, platform selectors, immutable local bundle URIs, and SHA-256 values
are exactly those in `infra/offline/opencode-manifest.json`.

## Stage and approve the bundle

On an internet-connected staging host, select the manifest entry matching the
target's architecture, libc, and CPU. For an x86-64 glibc host without AVX2:

```bash
mkdir -p /var/tmp/opencode-1.15.11
cd /var/tmp/opencode-1.15.11
curl -fL --proto '=https' --tlsv1.2 \
  -o opencode-linux-x64-baseline.tar.gz \
  https://github.com/anomalyco/opencode/releases/download/v1.15.11/opencode-linux-x64-baseline.tar.gz
printf '%s  %s\n' \
  eb19eabc9cb7fa8a73898328b69720738d35e0cad716898bfdbc2547f88b2450 \
  opencode-linux-x64-baseline.tar.gz | sha256sum --check --strict
sha256sum opencode-linux-x64-baseline.tar.gz
```

The check output and independently recomputed digest must both equal
`eb19eabc9cb7fa8a73898328b69720738d35e0cad716898bfdbc2547f88b2450`.
Perform malware scanning and OSS/security approval, retain the upstream MIT
license notice beside the bundle, and record approver, scanner version, scan
result, source URL, and digest. Publish the approved bytes to immutable internal
storage without renaming them. Copy the repository manifest unchanged beside
the bundle set. Never publish a mutable `latest` alias.

## Transfer and disconnected install

Transfer the approved directory through the controlled media gateway to
`/opt/skillify/offline/opencode/v1.15.11/`. Before extracting, run the same
`sha256sum --check --strict` command using the selected manifest digest. A
failure stops installation.

```bash
install -d -m 0755 /opt/skillify/opencode/1.15.11/bin
tar -xzf /opt/skillify/offline/opencode/v1.15.11/opencode-linux-x64-baseline.tar.gz \
  -C /opt/skillify/opencode/1.15.11/bin
/opt/skillify/opencode/1.15.11/bin/opencode --version
ln -sfn /opt/skillify/opencode/1.15.11 /opt/skillify/opencode/current
ln -sfn /opt/skillify/opencode/current/bin/opencode /usr/local/bin/opencode
```

The version command must print `1.15.11`. Configure doctor with absolute local
paths only:

```bash
export SKILLIFY_OPENCODE_MANIFEST_PATH=/opt/skillify/offline/opencode/opencode-manifest.json
export SKILLIFY_OPENCODE_ARTIFACT_ROOT=/opt/skillify/offline/opencode/v1.15.11
```

## Endpoint configuration

In the endpoint agent YAML, set `model_endpoint` to the approved internal HTTPS
endpoint, `model_provider` and `model_name` to approved identifiers,
`allowed_model_hosts` to that endpoint's exact host, and
`credential_env_names` to the approved secret variable name. Store the secret
value in the endpoint secret manager/environment, never in YAML or logs.

The launcher must set:

```bash
export OPENCODE_DISABLE_AUTOUPDATE=true
export OPENCODE_DISABLE_LSP_DOWNLOAD=true
export OPENCODE_DISABLE_DEFAULT_PLUGINS=true
export NO_PROXY=localhost,127.0.0.1
```

OpenCode must bind `127.0.0.1` only. Firewall policy must deny endpoint inbound
access and permit only the approved outbound model/MCP destinations.

## Upgrade, downgrade, and rollback

Stage every new version as a separate immutable directory and reviewed manifest;
do not overwrite v1.15.11. Stop the agent, verify no owned process remains,
install and verify the new version, atomically repoint `current`, then rerun the
acceptance checklist. To downgrade or roll back, stop the agent, repoint
`/opt/skillify/opencode/current` to the previously approved directory, verify its
manifest checksum and version, and rerun the checklist. Preserve failed-version
logs and approval evidence; never bypass an incompatible libc/CPU selector.

## `[test-env]` acceptance evidence

On the disconnected target, record OS, architecture, libc, and CPU flags, then run:

```bash
uname -a
getconf GNU_LIBC_VERSION || ldd --version
grep -m1 -E '^(flags|Features)' /proc/cpuinfo
opencode --version
skillctl agent doctor --format json
skillctl agent run --workspace /srv/skillify-test/repository \
  --prompt-file /srv/skillify-test/task.txt --format json
ss -ltnp
ps -ef | grep '[o]pencode serve'
skillctl agent stop --format json
ps -ef | grep '[o]pencode serve'
```

Retain evidence that doctor reports the exact manifest/platform/version/checksum,
the example task produced the expected edit/test/diff summary, every OpenCode
listener is on `127.0.0.1`, cancellation and SIGTERM complete within their bounds,
and the final process query has no OpenCode server. Any failure blocks G1.
