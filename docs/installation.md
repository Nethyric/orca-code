# Installation

Orca Code is a single Python package with **zero runtime dependencies**. If you
have Python 3.9 or newer, you already have everything you need.

- [Requirements](#requirements)
- [Prebuilt binaries (no Python needed)](#prebuilt-binaries-no-python-needed)
- [One-liner (macOS / Linux / Windows)](#one-liner-macos--linux--windows)
- [pip](#pip)
- [pipx (recommended for CLI tools)](#pipx-recommended-for-cli-tools)
- [From source](#from-source)
- [Windows](#windows)
- [Offline / air-gapped machines](#offline--air-gapped-machines)
- [Local models with Ollama or LM Studio](#local-models-with-ollama-or-lm-studio)
- [Verifying the install](#verifying-the-install)
- [Upgrading](#upgrading)
- [Uninstalling](#uninstalling)
- [Troubleshooting](#troubleshooting)

## Requirements

| | |
| --- | --- |
| Python | **3.9 – 3.13** (`python3 --version`) |
| OS | macOS, Linux, Windows (WSL recommended, native works) |
| Dependencies | **None** — pure standard library |
| API key | Only for cloud providers. Ollama / LM Studio need nothing. |

## Prebuilt binaries (no Python needed)

Every release ships standalone executables — a full copy of the Python
runtime and Orca in one file. Download from the
[releases page](https://github.com/Nethyric/orca-code/releases/latest):

| Asset | Platform |
| --- | --- |
| `orca-linux-x64.tar.gz` | Linux x86-64 |
| `orca-linux-arm64.tar.gz` | Linux ARM64 |
| `orca-macos-arm64.tar.gz` | macOS Apple Silicon |
| `orca-windows-x64.exe` | Windows x86-64 (direct download, no unzip) |
| `orca-windows-arm64.exe` | Windows ARM64 |
| `orca.pyz` | any OS **with** Python 3.9+ — one file, zero install |

Linux / macOS:

```bash
curl -fsSL https://github.com/Nethyric/orca-code/releases/latest/download/orca-linux-x64.tar.gz | tar -xz
sudo mv orca /usr/local/bin/     # or: chmod +x orca && sudo mv orca /usr/local/bin/
orca --version
```

(adjust the filename for your platform — on Apple Silicon use
`orca-macos-arm64.tar.gz`)

Intel Macs: no prebuilt binary — hosted Intel macOS runners no longer
exist. Use `pip install` or `orca.pyz` (both fully supported).

macOS quarantines unsigned binaries; clear it once:

```bash
xattr -d com.apple.quarantine /usr/local/bin/orca
```

Windows: download `orca-windows-x64.exe` and run it from a terminal
(`orca-windows-x64.exe --version`). SmartScreen may warn on first run —
"More info" → "Run anyway", or verify the SHA-256 against `sha256sums.txt`
on the release page.

Every binary is built and smoke-tested by CI (`--version`, `--help`,
`auth list`) before the release is published, and all assets are
checksummed in `sha256sums.txt`.

## One-liner (macOS / Linux / Windows)

macOS / Linux (any POSIX shell):

```bash
curl -fsSL https://raw.githubusercontent.com/Nethyric/orca-code/main/install.sh | bash
```

Windows (PowerShell — press Start, type "powershell", Enter):

```powershell
irm https://raw.githubusercontent.com/Nethyric/orca-code/main/install.ps1 | iex
```

Both scripts check your Python version and install Orca from the repo zip —
**no git required**. The bash script falls back to `--user` /
`--break-system-packages` on externally-managed systems (Ubuntu 23.04+ /
Debian 12+ / Fedora 38+). Read before running, as you should with any
installer you pipe into a shell:

```bash
curl -fsSL https://raw.githubusercontent.com/Nethyric/orca-code/main/install.sh
```

## pip

```bash
# from the repo zip — no git needed
python3 -m pip install https://github.com/Nethyric/orca-code/archive/refs/heads/main.zip

# or straight from git if you have it installed
python3 -m pip install git+https://github.com/Nethyric/orca-code
```

If you see `error: externally-managed-environment` (newer Debian/Ubuntu/Fedora),
use one of these instead:

```bash
# into your user site (no venv needed)
python3 -m pip install --user ZIP_URL          # see ZIP_URL below

# or bypass the guard if you know why it exists
python3 -m pip install --break-system-packages ZIP_URL
```

where `ZIP_URL` is `https://github.com/Nethyric/orca-code/archive/refs/heads/main.zip`.

Make sure `~/.local/bin` (or its Windows equivalent) is on your `PATH`:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
```

## pipx (recommended for CLI tools)

[pipx](https://pipx.pypa.io) installs each CLI in its own isolated environment,
so Orca can never clash with your project dependencies — and since Orca has no
dependencies, the venv is just Orca itself.

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath

pipx install ZIP_URL
```

## From source

For hacking on Orca itself:

```bash
git clone https://github.com/Nethyric/orca-code.git
cd orca-code

# editable install into a venv
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python3 -m pip install -e .

# run the test suite (offline, no keys needed)
python3 -m unittest discover -s tests
```

No venv needed to just run it: `PYTHONPATH=. python3 -m orca` works from the
repo root.

## Windows

**Option A — PowerShell one-liner (native, easiest):**

```powershell
irm https://raw.githubusercontent.com/Nethyric/orca-code/main/install.ps1 | iex
```

The script finds Python (via the `py` launcher or `python`), verifies it's
3.9+, installs from the repo zip, and checks that `orca --version` works.

**Option B — manual, native:** with Python from python.org:

```powershell
py -m pip install https://github.com/Nethyric/orca-code/archive/refs/heads/main.zip
py -m orca --version
```

**Option C — WSL:** the Deep Ocean UI is tuned for ANSI-capable terminals.
In WSL, follow the macOS/Linux steps above.

Orca detects the console automatically: in plain `cmd.exe` it switches to a
clean ASCII look (correct colors, no mojibake); in Windows Terminal you get
the full Deep Ocean UI with glyphs. If anything still looks off, `orca doctor`
reports the console capabilities and `orca config` offers the `mono` theme.

## Offline / air-gapped machines

Orca never fetches anything at runtime except your chosen provider's API — so a
wheel built elsewhere installs cleanly with no network:

```bash
# online machine
python3 -m pip download git+https://github.com/Nethyric/orca-code -d wheels/

# copy wheels/ to the target machine, then
python3 -m pip install --no-index --find-links wheels/ orca-code
```

## Local models with Ollama or LM Studio

No account, no key, no internet:

```bash
ollama serve                      # or start LM Studio's local server
orca config                       # provider → ollama (or lmstudio)
orca                              # done
```

Default endpoints: `http://localhost:11434/v1` (Ollama) and
`http://localhost:1234/v1` (LM Studio).

## Verifying the install

```bash
orca --version          # → orca-code 0.0.1
orca doctor             # checks config, provider, connectivity
orca -p "hello" -P mock # full agent loop, no network, no key
```

Then add a real key:

```bash
orca auth login         # picker → paste key → validated live
```

## Upgrading

```bash
python3 -m pip install --upgrade git+https://github.com/Nethyric/orca-code   # pip
pipx upgrade orca-code                                                       # pipx
```

Your settings, keys, and session history live in `~/.config/orca/` (or
`%ORCA_HOME%`) and survive every upgrade.

## Uninstalling

```bash
python3 -m pip uninstall orca-code   # or: pipx uninstall orca-code
rm -rf ~/.config/orca                # settings + keys + history (optional)
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `orca: command not found` | `~/.local/bin` not on `PATH` — see the pip section |
| `externally-managed-environment` | use `--user`, `--break-system-packages`, or pipx |
| `python3: command not found` (Windows) | use `py` instead of `python3` |
| Colors/glyphs broken | `orca config` → theme `plain` (ASCII-safe) |
| Provider 401 after `auth login` | re-run `orca auth login <provider>` — it validates keys live |
| Behind a proxy | `export HTTPS_PROXY=http://proxy:port` (urllib honors it) |

Still stuck? [Open an issue](https://github.com/Nethyric/orca-code/issues).
