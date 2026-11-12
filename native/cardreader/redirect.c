/*
 * The list of openDMT3's own files in the game's place (redirect.h): read once when the game starts, asked at every
 * file the game opens. Plain C with no Windows calls, so the native tests run it.
 */
#include "redirect.h"

#include <string.h>
#include <wctype.h>

/* One character as the file system compares names: upper case (both sides of a comparison go through this). */
static wchar_t fold(wchar_t c)
{
    return (wchar_t)towupper(c);
}

int redirect_utf8(const char *in, size_t len, wchar_t *out, size_t room)
{
    size_t n = 0;
    const unsigned char *s = (const unsigned char *)in;
    for (size_t i = 0; i < len;) {
        unsigned long c = s[i];
        int more;
        /* The lead byte says how many bytes follow and gives the code point's top bits. */
        if (c < 0x80)
            more = 0;
        else if ((c & 0xE0) == 0xC0)
            more = 1, c &= 0x1F;
        else if ((c & 0xF0) == 0xE0)
            more = 2, c &= 0x0F;
        else if ((c & 0xF8) == 0xF0)
            more = 3, c &= 0x07;
        else
            return -1;
        /* The sequence must be whole: a list cut off inside a character is not the launcher's. */
        if (more && i + (size_t)more >= len)
            return -1;
        for (int k = 1; k <= more; k++) {
            /* Every byte after the lead is a continuation byte (10xxxxxx). */
            if ((s[i + k] & 0xC0) != 0x80)
                return -1;
            c = (c << 6) | (s[i + k] & 0x3F);
        }
        i += (size_t)more + 1;
        if (c >= 0x10000) {
            /* Past the BMP: two units (a surrogate pair), as Windows keeps it; room for them and the end. */
            if (c > 0x10FFFF || n + 2 >= room)
                return -1;
            c -= 0x10000;
            out[n++] = (wchar_t)(0xD800 + (c >> 10));
            out[n++] = (wchar_t)(0xDC00 + (c & 0x3FF));
        } else {
            /* One unit; room for it and the end. */
            if (n + 1 >= room)
                return -1;
            out[n++] = (wchar_t)c;
        }
    }
    out[n] = 0;
    return (int)n;
}

/* Whether a relative path from the list stays in the game folder: no drive, no root, no step up. */
static int stays_inside(const wchar_t *p)
{
    if (!p[0] || p[0] == L'\\' || p[0] == L'/' || p[1] == L':')
        return 0;
    /* Each component in turn: ".." anywhere would leave the folder. */
    const wchar_t *c = p;
    while (*c) {
        const wchar_t *end = c;
        while (*end && *end != L'\\' && *end != L'/')
            end++;
        if (end - c == 2 && c[0] == L'.' && c[1] == L'.')
            return 0;
        c = *end ? end + 1 : end;
    }
    return 1;
}

/* Whether a path from the list is absolute: a drive and its root ("C:\") or a share ("\\server\..."). */
static int absolute(const wchar_t *p)
{
    if (p[0] && p[1] == L':' && (p[2] == L'\\' || p[2] == L'/'))
        return 1;
    return p[0] == L'\\' && p[1] == L'\\';
}

/* A path with forward slashes made backslashes and each run of them one (a share's two at the start kept): `out` as
 * spelled and `folded` the same characters folded, position for position. Its length; 0 when it does not fit. */
static size_t tidy(const wchar_t *in, wchar_t *out, wchar_t *folded, size_t room)
{
    size_t n = 0;
    for (size_t i = 0; in[i]; i++) {
        wchar_t c = in[i] == L'/' ? L'\\' : in[i];
        /* A second backslash in a row says nothing more (past a share's opening two). */
        if (c == L'\\' && n > 1 && out[n - 1] == L'\\')
            continue;
        if (n + 1 >= room)
            return 0;
        out[n] = c;
        if (folded)
            folded[n] = fold(c);
        n++;
    }
    out[n] = 0;
    if (folded)
        folded[n] = 0;
    return n;
}

int redirect_parse(Redirects *out, const wchar_t *game, const wchar_t *base, const char *text, size_t len)
{
    memset(out, 0, sizeof *out);
    /* The game folder folded and without a backslash at its end, so "C:\Games\DMT3\" and "...\DMT3" match alike. */
    wchar_t spelled[REDIRECT_PATH];
    size_t g = tidy(game, spelled, out->game, REDIRECT_PATH);
    if (!g || !absolute(out->game))
        return -1;
    while (g > 3 && out->game[g - 1] == L'\\')
        out->game[--g] = 0;
    size_t at = 0;
    /* A byte-order mark at the start is not part of the first line. */
    if (len >= 3 && (unsigned char)text[0] == 0xEF && (unsigned char)text[1] == 0xBB && (unsigned char)text[2] == 0xBF)
        at = 3;
    while (at < len) {
        size_t end = at;
        while (end < len && text[end] != '\n')
            end++;
        size_t stop = end;
        /* A line may end in CR LF (a list saved on Windows). */
        if (stop > at && text[stop - 1] == '\r')
            stop--;
        /* Empty lines and notes (#) say nothing. */
        if (stop > at && text[at] != '#') {
            const char *tab = memchr(text + at, '\t', stop - at);
            if (!tab || out->count >= REDIRECT_MAX)
                return -1;
            Redirect *r = &out->r[out->count];
            wchar_t from[REDIRECT_PATH], to[REDIRECT_PATH];
            if (redirect_utf8(text + at, (size_t)(tab - (text + at)), from, REDIRECT_PATH) <= 0)
                return -1;
            if (redirect_utf8(tab + 1, (size_t)(text + stop - (tab + 1)), to, REDIRECT_PATH) <= 0)
                return -1;
            if (!stays_inside(from))
                return -1;
            /* openDMT3's own files are named from the DLL's folder; an original an earlier openDMT3 kept in the game
             * folder's backup is named from the game folder, after "<game>\". Nothing else: no whole path, no step up,
             * so the list cannot give the game a file outside those two folders. */
            const wchar_t *rel = to;
            const wchar_t *folder = base;
            if (!wcsncmp(to, REDIRECT_GAME_MARK, wcslen(REDIRECT_GAME_MARK))) {
                rel = to + wcslen(REDIRECT_GAME_MARK);
                folder = spelled;
            }
            wchar_t whole[REDIRECT_PATH];
            size_t b = wcslen(folder);
            if (!stays_inside(rel) || !absolute(folder) || b + 1 + wcslen(rel) + 1 > REDIRECT_PATH)
                return -1;
            wcscpy(whole, folder);
            /* One backslash between the folder and the name, whether the folder ends in one or not. */
            if (b && whole[b - 1] != L'\\' && whole[b - 1] != L'/')
                wcscat(whole, L"\\");
            wcscat(whole, rel);
            /* The relative path folded for matching; whether it stands for a folder (its last character a slash). */
            wchar_t ignored[REDIRECT_PATH];
            size_t f = tidy(from, ignored, r->from, REDIRECT_PATH);
            size_t t = tidy(whole, r->to, NULL, REDIRECT_PATH);
            if (!f || !t)
                return -1;
            r->folder = r->from[f - 1] == L'\\';
            /* A folder's own path is kept without its last backslash, so the remainder adds its own. */
            while (r->folder && t > 3 && r->to[t - 1] == L'\\')
                r->to[--t] = 0;
            out->count++;
        }
        at = end + 1;
    }
    return out->count;
}

int redirect_lookup(const Redirects *rs, const wchar_t *full, wchar_t *out, size_t room)
{
    if (!rs->count || !full)
        return 0;
    /* The path tidied as spelled (q) and folded (p), position for position. */
    wchar_t q[REDIRECT_PATH], p[REDIRECT_PATH];
    size_t n = tidy(full, q, p, REDIRECT_PATH);
    /* Inside the game folder: its path, then a backslash, then something. */
    size_t g = wcslen(rs->game);
    if (!n || n <= g + 1 || wcsncmp(p, rs->game, g) != 0 || p[g] != L'\\')
        return 0;
    const wchar_t *rest = p + g + 1;
    for (int i = 0; i < rs->count; i++) {
        const Redirect *r = &rs->r[i];
        size_t f = wcslen(r->from);
        size_t tail = 0;
        int match = 0;
        if (!r->folder) {
            /* A file: the whole remainder is its path. */
            match = wcscmp(rest, r->from) == 0;
        } else if (wcsncmp(rest, r->from, f) == 0) {
            /* Something inside the folder: what follows its path goes after openDMT3's folder. */
            match = 1;
            tail = (size_t)(rest - p) + f;
        } else if (wcsncmp(rest, r->from, f - 1) == 0 && (rest[f - 1] == 0 || (rest[f - 1] == L'\\' && !rest[f]))) {
            /* The folder itself, with or without its last backslash. */
            match = 1;
        }
        if (!match)
            continue;
        size_t to_len = wcslen(r->to);
        /* What follows in the game's own spelling (a file the game makes keeps the name it gave). */
        const wchar_t *after = tail && q[tail] ? q + tail : L"";
        size_t after_len = wcslen(after);
        if (to_len + (after_len ? 1 + after_len : 0) + 1 > room)
            return 0;
        wcscpy(out, r->to);
        if (after_len) {
            out[to_len] = L'\\';
            wcscpy(out + to_len + 1, after);
        }
        return 1;
    }
    return 0;
}
