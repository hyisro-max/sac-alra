# AlmaLinux 9 connected bundle builder

The internet-connected machine may be AlmaLinux 9.x rather than RHEL. It must
be x86_64/AMD64 because the disconnected production host is RHEL 9.5 AMD64.
AlmaLinux documents RHEL ABI compatibility, but SAC-ALRA still treats the final
disconnected RHEL smoke test as mandatory because containers use the host
kernel, GPU driver, filesystem, and security policy.

The Apple Silicon Mac prepares only a clean source archive. It does not resolve
production wheels on macOS: macOS/ARM wheels are incompatible with Linux/AMD64.
The AlmaLinux machine runs all Python resolution inside the pinned
`python:3.11-slim-bookworm` Linux/AMD64 container.

## 1. Create the clean source bundle on this Mac

```bash
cd /Users/hiya_38/ISRO_SAC/sacai/sacai-platform
chmod +x scripts/*.sh
./scripts/create_alma_source_bundle_macos.sh
cd dist
shasum -a 256 -c sacai-alma-builder-source.tar.gz.sha256
```

Copy these two files to the AlmaLinux host:

- `sacai-alma-builder-source.tar.gz`
- `sacai-alma-builder-source.tar.gz.sha256`

The archive contains OpenWebUI v0.10.2 source, PySTAC Client source, and the
complete `sacai-platform` implementation. It excludes `.git`, `.github`, GitHub
workflow/templates, `.gitignore`, `.gitattributes`, caches, generated wheels,
models, and image archives. License files and ordinary documentation remain.

## 2. Verify and extract on AlmaLinux

```bash
mkdir -p "$HOME/sacai-builder"
cd "$HOME/sacai-builder"
sha256sum --check sacai-alma-builder-source.tar.gz.sha256
tar -xzf sacai-alma-builder-source.tar.gz
cd sacai-alma-builder
sha256sum --check SOURCE_MANIFEST.sha256
```

Install an organization-approved Docker Engine/Compose v2 combination before
continuing. Verify it rather than relying on a package name:

```bash
uname -m
cat /etc/os-release
docker version
docker compose version
docker run --rm --platform=linux/amd64 python:3.11-slim-bookworm python --version
```

The first command must print `x86_64`; `/etc/os-release` must identify
AlmaLinux 9.x; and the container must print Python 3.11. The final command is
allowed to pull because this is the connected machine.

## 3. Build and prove the complete offline dependency set

Run the builder. It defaults to the required container proxy
`http://http.docker.internal:3128`; set `SACAI_BUILD_PROXY_URL` first only when
that value differs.

Docker Desktop registry pulls do not use project build arguments. Configure its
Docker Desktop and Containers proxies in **Settings → Proxies**, then require
`docker pull --platform=linux/amd64 python:3.11-slim-bookworm` to pass. On the
current network, use `unset SACAI_BUILD_PROXY_URL`, not an empty export, so the
container-download default remains enabled. The preparation script performs an
Alpine repository preflight before building dependency images.

```bash
cd "$HOME/sacai-builder/sacai-alma-builder/sacai-platform"
./scripts/run_on_alma_builder.sh
```

The preparation script deliberately empties stale wheels, then runs
`pip download --only-binary=:all:` inside Linux/AMD64. Pip resolves direct and
transitive requirements together. The build then installs with
`pip install --no-index --find-links=/wheelhouse` in clean service, test, and
optional ISIS worker images, runs `pip check`, runs pytest, and only then emits:

- every resolved wheel under `offline/wheelhouse/`;
- `offline/WHEELHOUSE_SHA256SUMS`;
- `offline/requirements-linux-amd64.lock.txt` containing installed versions;
- OCI image archives, the staged `libexpat1` rootfs, OpenWebUI caches, and
  `offline/SHA256SUMS` covering the offline tree.

Ollama is not an image in this Compose stack and its existing models are not
copied. Each production host connects to its already-running external Ollama
API.

If a dependency has no compatible Linux/AMD64 Python 3.11 wheel, resolution or
the no-index image build fails. Do not bypass `--only-binary`, add a source
archive, or ignore `pip check`; select a compatible pinned version and rerun the
entire stage.

## 4. Create the RHEL transfer archive

Mount the encrypted transfer disk, then use a destination outside the extracted
repository. For example:

```bash
cd "$HOME/sacai-builder/sacai-alma-builder/sacai-platform"
./scripts/create_offline_transfer_archive.sh /mnt/encrypted-transfer
cd /mnt/encrypted-transfer
sha256sum --check sacai-rhel95-offline-amd64.tar.sha256
```

Transfer the `.tar` and `.sha256` files to RHEL 9.5. The tar is intentionally
uncompressed because OCI archives, wheels, and model blobs are already compressed.
On RHEL, verify the outer checksum, extract, then run the steps in
`OFFLINE_DEPLOYMENT.md`. Keep networking disabled for that rebuild and smoke test.

## Compatibility references

- AlmaLinux FAQ: `https://wiki.almalinux.org/FAQ.html` documents its RHEL ABI
  compatibility goal.
- Red Hat container compatibility matrix:
  `https://access.redhat.com/support/policy/rhel-container-compatibility`
  explains why image/host architecture must match and why final validation on
  the actual RHEL host remains necessary.
