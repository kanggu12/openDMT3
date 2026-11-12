# The compiler for DSOAL and OpenAL Soft (native/openal/build.sh): MinGW-w64's C++ for 32-bit Windows with POSIX
# threads (both use the C++ standard library's threads), GCC 14 for the C++20 they are written in, CMake and Ninja.
FROM debian:13
RUN apt-get update && apt-get install -y --no-install-recommends g++-mingw-w64-i686-posix gcc-mingw-w64-i686-posix \
    mingw-w64-i686-dev cmake ninja-build && rm -rf /var/lib/apt/lists/*
