#!/bin/bash
# Inside the compiler's container (build.sh runs it): OpenAL Soft and DSOAL from the archives in /out/cache, built in
# /tmp, their two libraries into /out, stripped.
set -euo pipefail
# Unpacked in the container's own /tmp: the output folder gets the two libraries only.
cd /tmp
tar xzf "/out/cache/$OPENAL_TAR"
tar xzf "/out/cache/$DSOAL_TAR"
# Each archive holds one folder named after its release or commit.
AL=$(echo openal-soft-*/)
DS=$(echo dsoal-*/)
# OpenAL Soft: only its WASAPI backend (the way a Windows 10 or 11 PC plays), none of its programs or examples, the
# compiler's runtimes linked in (the library needs nothing beside Windows), no build version from Git (an archive
# has none), and no C++ modules (GCC 14's are not complete). No STL hardening (both projects' default turns on
# libstdc++'s assertions): at the game's exit a condition variable whose waiting thread Windows has already ended
# failed its assertion, and the abort it calls is a runtime error box on the player's screen as the game closes.
cmake -S "$AL" -B al -G Ninja -DCMAKE_TOOLCHAIN_FILE="$PWD/$AL/XCompile.txt" -DHOST=i686-w64-mingw32 \
  -DCMAKE_BUILD_TYPE=Release -DALSOFT_UTILS=OFF -DALSOFT_EXAMPLES=OFF -DALSOFT_TESTS=OFF -DALSOFT_INSTALL=OFF \
  -DALSOFT_UPDATE_BUILD_VERSION=OFF -DALSOFT_BACKEND_DSOUND=OFF -DALSOFT_BACKEND_WINMM=OFF -DALSOFT_REQUIRE_WASAPI=ON \
  -DALSOFT_ENABLE_MODULES=OFF -DALSOFT_STATIC_LIBGCC=ON -DALSOFT_STATIC_STDCXX=ON -DALSOFT_STATIC_WINPTHREAD=ON \
  -DALSOFT_STL_HARDENING=None \
  > /tmp/al-cmake.log 2>&1 || { tail -30 /tmp/al-cmake.log; exit 1; }
# Two compilers at a time: the build shares the machine.
ninja -C al -j2 > /tmp/al-build.log 2>&1 || { tail -30 /tmp/al-build.log; exit 1; }
# DSOAL: its own CMake, the same compiler and the runtimes linked in too, with no STL hardening either (above).
cmake -S "$DS" -B ds -G Ninja -DCMAKE_TOOLCHAIN_FILE="$PWD/$AL/XCompile.txt" -DHOST=i686-w64-mingw32 \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_SHARED_LINKER_FLAGS="-static -static-libgcc -static-libstdc++" \
  -DDSOAL_STL_HARDENING=None \
  > /tmp/ds-cmake.log 2>&1 || { tail -30 /tmp/ds-cmake.log; exit 1; }
ninja -C ds -j2 > /tmp/ds-build.log 2>&1 || { tail -30 /tmp/ds-build.log; exit 1; }
# Under the names openal.c loads them by, stripped of their symbols.
i686-w64-mingw32-strip -o /out/dsoal-aldrv.dll al/OpenAL32.dll
i686-w64-mingw32-strip -o /out/openDMT3-dsoal.dll ds/dsound.dll
# Neither may need a library beside it that Windows does not have (a runtime left out of the static link would).
for f in /out/dsoal-aldrv.dll /out/openDMT3-dsoal.dll; do
  i686-w64-mingw32-objdump -p "$f" | sed -n 's/^\tDLL Name: //p' | while read -r dll; do
    case "${dll,,}" in
      kernel32.dll|msvcrt.dll|ole32.dll|shell32.dll|avrt.dll|user32.dll|advapi32.dll|winmm.dll) ;;
      *) echo "$f needs $dll, which is not part of Windows"; exit 1 ;;
    esac
  done
done
