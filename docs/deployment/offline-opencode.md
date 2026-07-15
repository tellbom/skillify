# Offline OpenCode v1.15.11 deployment

This procedure installs the S1-approved OpenCode v1.15.11 binary on disconnected
Linux endpoints. Runtime public downloads are prohibited. The six approved
source URLs, platform selectors, immutable local bundle URIs, and SHA-256 values
are exactly those in `infra/offline/opencode-manifest.json`.

## Stage and approve the bundle

On an internet-connected staging host, select the manifest entry matching the
target's architecture, libc, and CPU. For an x86-64 glibc host without AVX2:

```bash
install -d -m 0755 /var/tmp/skillify-opencode/v1.15.11
install -m 0644 infra/offline/opencode-manifest.json \
  /var/tmp/skillify-opencode/opencode-manifest.json
cd /var/tmp/skillify-opencode/v1.15.11
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
storage without renaming them. The staging commands copy the repository manifest
unchanged to the root of the transfer tree, with versioned artifacts below it.
Never publish a mutable `latest` alias.

## Transfer and disconnected install

Transfer `/var/tmp/skillify-opencode/` through the controlled media gateway and
mount or copy it at `/media/skillify-opencode/` on the disconnected endpoint.
Install the manifest and selected artifact explicitly into the layout referenced
by their configured paths:

```bash
install -d -m 0755 /opt/skillify/offline/opencode/v1.15.11
install -m 0644 /media/skillify-opencode/opencode-manifest.json \
  /opt/skillify/offline/opencode/opencode-manifest.json
install -m 0644 /media/skillify-opencode/v1.15.11/opencode-linux-x64-baseline.tar.gz \
  /opt/skillify/offline/opencode/v1.15.11/opencode-linux-x64-baseline.tar.gz
```

Before extracting, run the same `sha256sum --check --strict` command using the
selected manifest digest. A failure stops installation.

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
If existing OpenCode preferences are needed, set the explicit absolute
`opencode_user_config_path` (or `SKILLIFY_OPENCODE_USER_CONFIG_PATH`). Skillify
accepts only safe `theme` and string-to-string `keybinds` values, rejects every
runtime/security/provider/plugin field, and writes a separate mode-0600 config;
it never reads an ambient HOME configuration implicitly.

The launcher must set:

```bash
export OPENCODE_DISABLE_AUTOUPDATE=true
export OPENCODE_DISABLE_LSP_DOWNLOAD=true
export OPENCODE_DISABLE_DEFAULT_PLUGINS=true
export OPENCODE_DISABLE_MODELS_FETCH=true
export NO_PROXY=localhost,127.0.0.1
```

## skillctl approval gate

The same manifest records skillctl version, supported Linux platforms, MIT
license, canonical source, immutable local URI, and SHA-256 independently from
OpenCode. The repository-owned `skillctl-0.1.0-approval-placeholder.json` is a
deterministic approval record, not an executable package. Its manifest entry has
`installable: false`; disconnected installation must therefore fail closed until
the release pipeline replaces it with reviewed wheel bytes and a freshly
computed checksum. Never interpret the placeholder checksum as approval of a
wheel and never invent or copy a digest from another artifact.

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
  --task /srv/skillify-test/task.txt --format json
ss -ltnp
ps -ef | grep '[o]pencode serve'
skillctl agent stop --format json
ps -ef | grep '[o]pencode serve'
```

Retain evidence that doctor reports the exact manifest/platform/version/checksum,
the example task produced the expected edit/test/diff summary, every OpenCode
listener is on `127.0.0.1`, cancellation and SIGTERM complete within their bounds,
and the final process query has no OpenCode server. Any failure blocks G1.
