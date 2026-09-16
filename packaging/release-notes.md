**Downloads** — pick your platform; no Python required for the binaries.

| Asset | Platform |
| --- | --- |
| `orca-linux-x64.tar.gz` | Linux x86-64 |
| `orca-linux-arm64.tar.gz` | Linux ARM64 |
| `orca-macos-arm64.tar.gz` | macOS Apple Silicon |
| `orca-windows-x64.exe` | Windows x86-64 |
| `orca-windows-arm64.exe` | Windows ARM64 |
| `orca.pyz` | any OS with Python 3.9+ (single file, zero install) |

| `*_py3-none-any.whl` | install via `pip` / `pipx` |

Intel Macs: no prebuilt binary (hosted Intel macOS runners are retired) —
use `pip install` or `orca.pyz`, both fully supported.

Quick start (Linux, x64):

```
curl -fsSL https://github.com/Nethyric/orca-code/releases/latest/download/orca-linux-x64.tar.gz | tar -xz
./orca --version
```

Quick start (Windows): download `orca-windows-x64.exe`, then run
`orca-windows-x64.exe --version`.

Quick start (any OS with Python 3.9+):

```
python orca.pyz --version
```

Every binary is built and smoke-tested by CI (`--version`, `--help`,
`auth list`) before this release is published. Checksums for all assets
are in `sha256sums.txt`.

Notes:
- macOS quarantines unsigned binaries — clear it with
  `xattr -d com.apple.quarantine orca`.
- Windows SmartScreen may warn on first run ("More info" → "Run anyway");
  the file's SHA-256 is listed in `sha256sums.txt` for verification.
