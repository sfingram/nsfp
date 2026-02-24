# nsfp - NSF Parser

An educational NSF (NES Sound Format) file parser using the [NotSoFatso](http://www.vgmpf.com/Wiki/index.php/Not_So,_Fatso!) library to transcribe NSF files to musical notation. Based largely on the code in [FamiStudio](https://github.com/BleuBleu/FamiStudio).

## Requirements

- Python 3.8+
- CMake 3.15+
- C++ compiler (clang, gcc, or MSVC)
- [uv](https://docs.astral.sh/uv/) package manager (recommended)

## Installation

### From source (development)

```bash
# Clone the repository
git clone https://github.com/sfingram/nsfp.git
cd nsfp

# Install with uv (builds the native library automatically)
uv sync
```

### From wheel

```bash
uv pip install nsfp
```

## Usage

```python
from nsfp.nsfp import NSF

# Load an NSF file
nsf = NSF("path/to/file.nsf")

# Access metadata
print(f"Title: {nsf.title}")
print(f"Artist: {nsf.artist}")
print(f"Tracks: {nsf.track_count}")

# Access songs
for song in nsf.songs:
    print(f"  - {song.name}")
```

## Development

### Building

```bash
# Install dependencies and build the native library
uv sync

# Rebuild after changes
uv sync --reinstall-package nsfp
```

### Building wheels

```bash
# Build a wheel for distribution
uv build --wheel
```

### Project structure

```
nsfp/
├── CMakeLists.txt          # CMake build for NotSoFatso library
├── pyproject.toml          # Project configuration (scikit-build-core)
├── nsfp/                   # Python package
│   ├── __init__.py
│   ├── constants.py        # NES audio channel constants
│   ├── nsf_build.py        # cffi library loader
│   └── nsfp.py             # Main NSF parser classes
└── vendor/
    └── notsofatso/         # Vendored C++ source from FamiStudio
```

## License

This project is licensed under the **GNU General Public License v2.0 or later** (GPL-2.0-or-later).

The NotSoFatso library (in `vendor/notsofatso/`) is Copyright (C) 2004 Disch and licensed under GPL v2+. See the source file headers and [LICENSE](LICENSE) for details.