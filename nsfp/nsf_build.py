"""
Use cffi to access the NotSoFatso dynamic library.

The library is built from source (vendored from FamiStudio) using CMake
during package installation via scikit-build-core.

Original source: https://github.com/BleuBleu/FamiStudio
"""

import sys
from pathlib import Path
from typing import Any

from cffi import FFI

ffibuilder = FFI()

ffibuilder.cdef(
    """
    void* NsfOpen(const char* file);
    int NsfGetTrackCount(void* nsfPtr);
    int NsfIsPal(void* nsfPtr);
    int NsfGetExpansion(void* nsfPtr);
    char* NsfGetTitle(void* nsfPtr);
    char* NsfGetArtist(void* nsfPtr);
    const char* NsfGetCopyright(void* nsfPtr);
    const char* NsfGetTrackName(void* nsfPtr, int track);
    void NsfClose(void* nsfPtr);
    void NsfSetTrack(void* nsfPtr, int track);
    int NsfRunFrame(void* nsfPtr);
    int NsfGetState(void* nsfPtr, int channel, int state, int sub);"""
)


def _find_library() -> str:
    """Find the NotSoFatso shared library in the package directory."""
    package_dir = Path(__file__).parent

    if sys.platform == "win32":
        lib_name = "NotSoFatso.dll"
    elif sys.platform == "darwin":
        lib_name = "libNotSoFatso.dylib"
    else:
        lib_name = "libNotSoFatso.so"

    lib_path = package_dir / lib_name
    if not lib_path.exists():
        raise RuntimeError(
            f"NotSoFatso library not found at {lib_path}. "
            "The package may not have been built correctly. "
            "Try reinstalling with: uv sync --reinstall"
        )
    return str(lib_path)


# Load the library from the package directory
# Type as Any since cffi Lib attributes are defined dynamically via cdef()
NSF_LIB: Any = ffibuilder.dlopen(_find_library())
