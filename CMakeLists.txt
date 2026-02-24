cmake_minimum_required(VERSION 3.15)
project(nsfp LANGUAGES C CXX)

# Set C++ standard
set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Position independent code for shared library
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Set output directory to be alongside the Python source files
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}/nsfp)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}/nsfp)

# Define source files for NotSoFatso library
set(NOTSOFATSO_SOURCES
    vendor/notsofatso/fmopl.c
    vendor/notsofatso/NSF_Core.cpp
    vendor/notsofatso/NSF_File.cpp
    vendor/notsofatso/NSF_6502.cpp
    vendor/notsofatso/Wave_VRC7.cpp
    vendor/notsofatso/DllWrapper.cpp
)

# Create shared library
add_library(NotSoFatso SHARED ${NOTSOFATSO_SOURCES})

# Include directory for headers
target_include_directories(NotSoFatso PRIVATE vendor/notsofatso)

# Platform-specific settings
if(UNIX AND NOT APPLE)
    # Linux
    target_compile_definitions(NotSoFatso PRIVATE LINUX)
    target_compile_options(NotSoFatso PRIVATE -Wno-narrowing)
    # Static link libstdc++ and libgcc for portability
    target_link_options(NotSoFatso PRIVATE -static-libgcc -static-libstdc++)
    set_target_properties(NotSoFatso PROPERTIES OUTPUT_NAME "NotSoFatso")
elseif(APPLE)
    # macOS
    target_compile_options(NotSoFatso PRIVATE -Wno-deprecated -Wno-ignored-attributes -Wno-comment)
    set_target_properties(NotSoFatso PROPERTIES OUTPUT_NAME "NotSoFatso")
elseif(WIN32)
    # Windows
    set_target_properties(NotSoFatso PROPERTIES OUTPUT_NAME "NotSoFatso")
endif()

# Optimization
target_compile_options(NotSoFatso PRIVATE -O2)

# Install the library into the Python package
install(TARGETS NotSoFatso
    LIBRARY DESTINATION nsfp
    RUNTIME DESTINATION nsfp
)
