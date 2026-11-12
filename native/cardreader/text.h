/*
 * The in-game layer's words: GDI text in the product's faces (the setup puts them beside the DLL), loaded for the
 * game's process only, measured and drawn as coverage into a canvas (look.h TextFn). Windows' GDI is the only
 * dependency, so the variant renderer used while designing runs the same code as the game.
 */
#ifndef OPENDMT3_TEXT_H
#define OPENDMT3_TEXT_H

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

#include "look.h"

/* Load the faces from the folder that holds `module` (NULL: the program's own), for this process only. Returns how
 * many of the three files were found (each one missing falls back to Windows' own face). */
int text_load_fonts(HMODULE module);
/* look.h TextFn backed by GDI: the words drawn white on black into a DIB whose green channel is the coverage, then
 * blended into the canvas in `rgb` (or a chrome ramp with TEXT_CHROME). With no canvas, only measured. */
float text_gdi(void *ctx, Canvas *c, const char *utf8, float px, float cx, float cy, uint32_t rgb, int flags);
/* How many times GDI has drawn words so far (each new word, size and face once; the chip's updates add none). */
long text_renders(void);

#endif
