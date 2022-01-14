"""
use cffi to access the notsofatso dynamic library distributed in the Famistudio repository
https://github.com/BleuBleu/FamiStudio
"""

import sys
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

# based on the operating system, load the appropriate dynamic/shared library
if sys.platform == "win32":
    NSF_LIB = ffibuilder.dlopen("./libNotSoFatSo.dll")
elif sys.platform == "darwin":
    NSF_LIB = ffibuilder.dlopen("./libNotSoFatSo.dylib")
else:
    NSF_LIB = ffibuilder.dlopen("./libNotSoFatso.so")
