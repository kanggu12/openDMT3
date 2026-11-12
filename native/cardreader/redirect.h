/*
 * Which of the game's paths are openDMT3's own files, and where those are (files.c asks; no Windows calls here, so the
 * native tests run it as it is).
 *
 * openDMT3 leaves the game folder as the player brought it. What a PC needs changed (the settings, the server's
 * address, the hidden patterns shown, the operator data the game writes as it is played) are openDMT3's own files in
 * its own folder, and the game is given them in place of its own. A list beside the DLL (openDMT3-files.txt, UTF-8,
 * written by the launcher before each PLAY) says which: one line a file,
 *
 *     <path relative to the game folder><TAB><openDMT3's file, relative to the DLL's folder>
 *
 * or, for an original an earlier openDMT3 kept in the game folder's backup, "<game>\" and its path relative to the game
 * folder on the right. A path on the left that ends in a backslash stands for a folder and everything in it (the
 * operator data's). No path on either side may be whole or step up (".."): the list can only name files in the game
 * folder and in openDMT3's own. Lines that are empty or start with # say nothing. Names are matched without letter
 * case, as Windows matches them.
 */
#ifndef OPENDMT3_REDIRECT_H
#define OPENDMT3_REDIRECT_H

#include <stddef.h>
#include <wchar.h>

/* What starts a path on the right named from the game folder (a name cannot hold "<", so no file is named so). */
#define REDIRECT_GAME_MARK L"<game>\\"
/* The most lines the list may hold: openDMT3 names a handful; anything past this many is not the launcher's list. */
#define REDIRECT_MAX 64
/* The longest path either side of a line may be, in UTF-16 units (Windows' own limit for a path given whole). */
#define REDIRECT_PATH 1024

typedef struct {
    /* Relative to the game folder, with backslashes, without letter case (upper case); ends in '\\' for a folder. */
    wchar_t from[REDIRECT_PATH];
    /* The absolute path openDMT3's file or folder has (a folder without its last backslash). */
    wchar_t to[REDIRECT_PATH];
    /* 1 when the line stands for a folder and everything in it. */
    int folder;
} Redirect;

typedef struct {
    /* The game folder, absolute, upper case, without a backslash at its end: every path the game opens is matched
     * against it first. */
    wchar_t game[REDIRECT_PATH];
    int count;
    Redirect r[REDIRECT_MAX];
} Redirects;

/* Read the list (`text` holds `len` bytes of UTF-8) for the game folder `game` (absolute), with `base` the DLL's folder
 * (absolute) that paths on the right are in (or the game folder, after "<game>\"). How many lines it took; -1 when the
 * list is not one the launcher writes (a line without a tab, a path too long, too many lines, a whole path, a path
 * that leaves the game folder or the DLL's folder): the caller then serves nothing, which is the game as it is. */
int redirect_parse(Redirects *out, const wchar_t *game, const wchar_t *base, const char *text, size_t len);

/* `full` is an absolute path as Windows makes it whole (GetFullPathNameW). When it is one of openDMT3's (the game
 * folder's file or a file in a folder the list names), the path to open in its place goes in `out` (room for `room`
 * units) and the result is 1; 0 otherwise, with `out` untouched. A path too long for `out` is not served (0). */
int redirect_lookup(const Redirects *rs, const wchar_t *full, wchar_t *out, size_t room);

/* UTF-8 to UTF-16 (`out` has room for `room` units, the end included): how many units, -1 when it does not fit or the
 * bytes are not UTF-8. Used for the list, which may name a folder outside the ANSI code page. */
int redirect_utf8(const char *in, size_t len, wchar_t *out, size_t room);

#endif
