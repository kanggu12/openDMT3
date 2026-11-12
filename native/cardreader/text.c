/*
 * The in-game layer's words (text.h): GDI text in the product's faces, measured and drawn as coverage.
 */
#include "text.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* The three faces, in the order of look.h's TEXT_* face bits: Pretendard Bold (the default: labels, buttons, titles),
 * Pretendard Regular (lines of body text, as the game writes its own messages) and DMT3 Wide (the product's wordmark
 * face, the launcher's titles, for the name and the frame rate's number). */
enum { FACE_BOLD = 0, FACE_REGULAR = 1, FACE_WIDE = 2, FACES = 3 };
/* The family name each file declares (GDI finds a private font by it), the weight asked for, and the file the setup
 * puts beside the DLL (core/cabinet/steps.py CardReader). */
static const WCHAR *const FACE_NAME[FACES] = {L"Pretendard", L"Pretendard", L"DMT3 Wide"};
static const int FACE_WEIGHT[FACES] = {FW_BOLD, FW_NORMAL, FW_NORMAL};
static const WCHAR *const FACE_FILE[FACES] = {L"openDMT3-Pretendard-Bold.ttf", L"openDMT3-Pretendard-Regular.ttf",
                                             L"openDMT3-DMT3Wide.ttf"};
/* Each face's capital height as a share of its size (its OS/2 table: Pretendard 1448 of 2048, DMT3 Wide 688 of
 * 1000): the words are centred on their capitals, as the game centres its own labels, whatever letters they hold. */
static const float FACE_CAP[FACES] = {0.707f, 0.707f, 0.688f};

/* GDI fonts made so far, by face and pixel size, with the ascent GDI gives each (the baseline's distance from the
 * top of the text's cell). Sixteen covers every size the layer draws at one scale. */
typedef struct {
    HFONT font;
    int face, px;
    int ascent;
} Font;
#define FONTS 16
static Font g_fonts[FONTS];
/* The slot the next new size takes (the oldest goes first when all are used). */
static int g_next;

/* Words drawn before, kept as their coverage (and the coverage grown for their edge), so drawing the same words again
 * (a panel drawn again when the pointer moves on it, the chip's numbers) costs no GDI work: the face, size, edge and
 * the words name an entry; the oldest goes when all are used. */
typedef struct {
    char words[128];
    int face, size, edge;
    int w, h, pad, ascent;
    float advance;
    uint8_t *cover, *wide;
    unsigned used;
} Kept;
#define KEPT 48
static Kept g_kept[KEPT];
static unsigned g_clock;
/* How many times GDI drew words (a word not kept yet): the chip's updates must add none. */
static LONG g_renders;

/* Pieces kept for good (TEXT_GLYPHS): a digit, or a run of other characters, by face and size, as coverage, never let
 * go while the sizes stay (when all are used, as after many window sizes, they are let go together and made again). */
typedef struct {
    char str[8];
    int face, size;
    int w, h, pad, ascent;
    float advance;
    uint8_t *cover;
} Piece;
#define PIECES 96
static Piece g_pieces[PIECES];
static int g_npieces;
/* Each face and size's digit cell, once worked out (digit_cell): eight at most, made again with the pieces. */
static struct {
    int face, size;
    float cell;
} g_cells[8];
static int g_ncells;

int text_load_fonts(HMODULE module)
{
    WCHAR path[MAX_PATH];
    /* The folder of the DLL (or of the program, for the design tools that link this file). */
    DWORD n = GetModuleFileNameW(module, path, MAX_PATH);
    if (!n || n >= MAX_PATH)
        return 0;
    WCHAR *slash = wcsrchr(path, L'\\');
    /* Room for the longest file name after the folder. */
    if (!slash || (size_t)(slash - path) + 40 >= MAX_PATH)
        return 0;
    int found = 0;
    for (int f = 0; f < FACES; f++) {
        wcscpy(slash + 1, FACE_FILE[f]);
        /* FR_PRIVATE: the face exists for this process only; nothing is installed on the PC. */
        found += AddFontResourceExW(path, FR_PRIVATE, NULL) > 0;
    }
    return found;
}

/* The GDI font for a face at a pixel size, made the first time it is asked for. */
static Font *font_of(int face, int px)
{
    for (int i = 0; i < FONTS; i++)
        if (g_fonts[i].font && g_fonts[i].face == face && g_fonts[i].px == px)
            return &g_fonts[i];
    /* A new one in the next slot, the font that was there (if any) let go first. */
    Font *f = &g_fonts[g_next++ % FONTS];
    if (f->font)
        DeleteObject(f->font);
    /* Grey smoothing, not ClearType: the words are blended in as coverage, and coloured fringes would show on glass.
     * A negative height asks for the em size, so `px` is the type size as a designer means it. */
    f->font = CreateFontW(-px, 0, 0, 0, FACE_WEIGHT[face], FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_TT_PRECIS,
                          CLIP_DEFAULT_PRECIS, ANTIALIASED_QUALITY, DEFAULT_PITCH, FACE_NAME[face]);
    f->face = face;
    f->px = px;
    /* The ascent this size really has (GDI rounds it), for placing the baseline. */
    HDC dc = CreateCompatibleDC(NULL);
    HFONT was = SelectObject(dc, f->font);
    TEXTMETRICW tm;
    f->ascent = GetTextMetricsW(dc, &tm) ? (int)tm.tmAscent : (int)lroundf(0.95f * (float)px);
    SelectObject(dc, was);
    DeleteDC(dc);
    return f;
}

/* The words' coverage, rendered by GDI or found kept: NULL when they cannot be drawn. */
static Kept *render(const char *utf8, int face, int size, int edge)
{
    /* Kept already: the same words, face, size and edge. */
    for (int i = 0; i < KEPT; i++) {
        Kept *k = &g_kept[i];
        if (k->cover && k->face == face && k->size == size && k->edge == edge && !strcmp(k->words, utf8)) {
            k->used = ++g_clock;
            return k;
        }
    }
    /* Too long to keep: never the layer's words (its longest line is about 60 letters). */
    if (strlen(utf8) >= sizeof g_kept[0].words)
        return NULL;
    WCHAR words[256];
    /* UTF-8 in, UTF-16 for GDI; the count includes the end, which is not drawn. */
    int n = MultiByteToWideChar(CP_UTF8, 0, utf8, -1, words, 256);
    if (n <= 1)
        return NULL;
    n--;
    /* The slot used longest ago (or an empty one). */
    Kept *k = &g_kept[0];
    for (int i = 1; i < KEPT; i++)
        if (!g_kept[i].cover || (k->cover && g_kept[i].used < k->used))
            k = &g_kept[i];
    free(k->cover);
    free(k->wide);
    memset(k, 0, sizeof *k);
    Font *f = font_of(face, size);
    /* One more drawing by GDI (counted: the chip's updates are to need none). */
    g_renders++;
    HDC dc = CreateCompatibleDC(NULL);
    HFONT old = SelectObject(dc, f->font);
    SIZE extent;
    GetTextExtentPoint32W(dc, words, n, &extent);
    /* Room round the words for a dark edge (the game's labels on its bright plates have one; the mark's chrome a thinner
     * one, as the launcher's logo, about 2 pixels at the bar's size). */
    int e = edge ? (size / 14 > 1 ? size / 14 : 1) : 0;
    if (edge == 2)
        e = size / 24 > 1 ? size / 24 : 1;
    int pad = 2 * e + 2;
    int w = extent.cx + 2 * pad, h = extent.cy + 2 * pad;
    BITMAPINFO bi;
    memset(&bi, 0, sizeof bi);
    bi.bmiHeader.biSize = sizeof bi.bmiHeader;
    bi.bmiHeader.biWidth = w;
    /* Negative height: rows from the top, as the canvas keeps them. */
    bi.bmiHeader.biHeight = -h;
    bi.bmiHeader.biPlanes = 1;
    bi.bmiHeader.biBitCount = 32;
    bi.bmiHeader.biCompression = BI_RGB;
    void *bits = NULL;
    HBITMAP bmp = CreateDIBSection(dc, &bi, DIB_RGB_COLORS, &bits, NULL, 0);
    uint8_t *cover = bmp ? malloc((size_t)w * (size_t)h) : NULL;
    uint8_t *wide = cover && e ? malloc((size_t)w * (size_t)h) : NULL;
    int ok = bmp && cover && (!e || wide);
    if (ok) {
        HBITMAP was = SelectObject(dc, bmp);
        /* The DIB starts black; white words on it give the coverage in every channel. */
        SetBkMode(dc, TRANSPARENT);
        SetTextColor(dc, RGB(255, 255, 255));
        TextOutW(dc, pad, pad, words, n);
        GdiFlush();
        const uint8_t *p = bits;
        /* Green carries the coverage (grey smoothing makes the three channels equal). */
        for (int i = 0; i < w * h; i++)
            cover[i] = p[i * 4 + 1];
        if (e) {
            /* The edge: the coverage grown by e pixels each way (the largest value near each pixel). */
            for (int yy = 0; yy < h; yy++)
                for (int xx = 0; xx < w; xx++) {
                    uint8_t best = 0;
                    for (int dy = -e; dy <= e; dy++)
                        for (int dx = -e; dx <= e; dx++) {
                            int sx = xx + dx, sy = yy + dy;
                            if (sx >= 0 && sy >= 0 && sx < w && sy < h && cover[sy * w + sx] > best)
                                best = cover[sy * w + sx];
                        }
                    wide[yy * w + xx] = best;
                }
        }
        SelectObject(dc, was);
    }
    if (bmp)
        DeleteObject(bmp);
    SelectObject(dc, old);
    DeleteDC(dc);
    if (!ok) {
        free(cover);
        free(wide);
        return NULL;
    }
    strcpy(k->words, utf8);
    k->face = face;
    k->size = size;
    k->edge = edge;
    k->w = w;
    k->h = h;
    k->pad = pad;
    k->ascent = f->ascent;
    k->advance = (float)extent.cx;
    k->cover = cover;
    k->wide = wide;
    k->used = ++g_clock;
    return k;
}

/* A piece kept for good: its words' coverage, made by GDI the first time (through the words' own cache), copied here. */
static Piece *piece_of(const char *str, int face, int size)
{
    for (int i = 0; i < g_npieces; i++)
        if (g_pieces[i].face == face && g_pieces[i].size == size && !strcmp(g_pieces[i].str, str))
            return &g_pieces[i];
    /* All used (many sizes over a run): let go together, the current size's made again as they are drawn. */
    if (g_npieces == PIECES) {
        for (int i = 0; i < PIECES; i++)
            free(g_pieces[i].cover);
        memset(g_pieces, 0, sizeof g_pieces);
        g_npieces = 0;
        g_ncells = 0;
    }
    Kept *k = render(str, face, size, 0);
    if (!k)
        return NULL;
    uint8_t *cover = malloc((size_t)k->w * (size_t)k->h);
    if (!cover)
        return NULL;
    memcpy(cover, k->cover, (size_t)k->w * (size_t)k->h);
    Piece *p = &g_pieces[g_npieces++];
    snprintf(p->str, sizeof p->str, "%s", str);
    p->face = face;
    p->size = size;
    p->w = k->w;
    p->h = k->h;
    p->pad = k->pad;
    p->ascent = k->ascent;
    p->advance = k->advance;
    p->cover = cover;
    return p;
}

/* The widest digit's advance at a face and size: the cell each digit is drawn in (worked out once a face and size). */
static float digit_cell(int face, int size)
{
    for (int i = 0; i < g_ncells; i++)
        if (g_cells[i].face == face && g_cells[i].size == size)
            return g_cells[i].cell;
    float cell = 0;
    char d[2] = {0, 0};
    for (char c = '0'; c <= '9'; c++) {
        d[0] = c;
        Piece *p = piece_of(d, face, size);
        if (p && p->advance > cell)
            cell = p->advance;
    }
    /* Kept (when all eight are used, as after many sizes, they start again). */
    if (g_ncells == 8)
        g_ncells = 0;
    g_cells[g_ncells].face = face;
    g_cells[g_ncells].size = size;
    g_cells[g_ncells++].cell = cell;
    return cell;
}

/* TEXT_GLYPHS: the line from kept pieces (digits one a cell, other runs whole), measured, then drawn when `c` is
 * given; its width. ASCII only (the chip's words). */
static float pieces_line(Canvas *c, const char *line, int face, int size, float cx, float cy, uint32_t rgb, int flags)
{
    float cell = digit_cell(face, size), width = 0;
    /* Two passes: the width first (for the line's placement), then the drawing. */
    for (int pass = 0; pass < (c ? 2 : 1); pass++) {
        float left = flags & TEXT_LEFT ? cx : flags & TEXT_RIGHT ? cx - width : cx - width / 2;
        float baseline = cy + FACE_CAP[face] * (float)size / 2, pen = 0;
        for (const char *at = line; *at;) {
            /* A digit alone, or the run of other characters up to the next digit (at most 7). */
            char str[8];
            int n = 0;
            if (*at >= '0' && *at <= '9')
                str[n++] = *at++;
            else
                while (*at && !(*at >= '0' && *at <= '9') && n < 7)
                    str[n++] = *at++;
            str[n] = 0;
            Piece *p = piece_of(str, face, size);
            if (!p)
                continue;
            int digit = str[0] >= '0' && str[0] <= '9';
            /* A digit centred in its cell; a run at its own advance. */
            float step = digit ? cell : p->advance, inset = digit ? (cell - p->advance) / 2 : 0;
            if (pass == 1)
                paint_coverage(c, (int)lroundf(left + pen + inset) - p->pad, (int)lroundf(baseline) - p->ascent - p->pad,
                               p->w, p->h, p->cover, p->w, rgb, 1.0f);
            pen += step;
        }
        width = pen;
    }
    return width;
}

long text_renders(void)
{
    return g_renders;
}

float text_gdi(void *ctx, Canvas *c, const char *utf8, float px, float cx, float cy, uint32_t rgb, int flags)
{
    (void)ctx;
    int face = flags & TEXT_WIDE ? FACE_WIDE : flags & TEXT_REGULAR ? FACE_REGULAR : FACE_BOLD;
    int size = (int)lroundf(px);
    /* Below 6 pixels nothing can be read: not drawn, measured as nothing. */
    if (size < 6 || !utf8 || !utf8[0])
        return 0;
    /* The chip's changing numbers: from the pieces kept for good, no GDI once they are made. */
    if (flags & TEXT_GLYPHS)
        return pieces_line(c, utf8, face, size, cx, cy, rgb, flags);
    /* The edge's kind: none, a label's (1), or the chrome lettering's thinner one (2). */
    Kept *k = render(utf8, face, size, flags & TEXT_EDGE ? (flags & TEXT_CHROME ? 2 : 1) : 0);
    if (!k)
        return 0;
    if (!c)
        /* Measuring only: the advance width, which is what lays words out side by side. */
        return k->advance;
    /* Where the cell goes: across, centred on cx (or starting or ending there); down, the capitals' middle on cy, so a
     * line of any letters sits where a line of capitals would. */
    float left = flags & TEXT_LEFT ? cx : flags & TEXT_RIGHT ? cx - k->advance : cx - k->advance / 2;
    float baseline = cy + FACE_CAP[face] * (float)size / 2;
    int x = (int)lroundf(left) - k->pad, y = (int)lroundf(baseline) - k->ascent - k->pad;
    if (k->wide)
        /* The edge in near black, under the words: faint round a label, solid round chrome lettering (the logo's
         * dark rim). */
        paint_coverage(c, x, y, k->w, k->h, k->wide, k->w, 0x05070a, flags & TEXT_CHROME ? 0.92f : 0.55f);
    if (flags & TEXT_CHROME) {
        /* The product's mark's chrome (the launcher's art.py, as the game's logo is drawn): bright at the capitals'
         * top, the dark band of a reflected horizon just under their middle, bright again at the baseline; or, for the
         * mark's 3, lit into the logo's blue towards its foot. The band's grey and the blue keep 4.5:1 (4.7 and 4.9) on
         * the glass over a white frame. */
        float top = baseline - FACE_CAP[face] * (float)size;
        Stop chrome[5] = {{0.0f, 0xffffff}, {0.46f, 0xe4e9ee}, {0.56f, 0xa8b1b9}, {0.78f, 0xcdd4da}, {1.0f, 0xf4f6f8}};
        Stop blue[5] = {{0.0f, 0xffffff}, {0.38f, 0xe9eefc}, {0.6f, 0x86adff}, {0.99f, 0x86adff}, {1.0f, 0x86adff}};
        Paint p;
        memset(&p, 0, sizeof p);
        p.nstops = 5;
        memcpy(p.stops, flags & TEXT_BLUE ? blue : chrome, sizeof chrome);
        p.y0 = top;
        p.y1 = baseline;
        p.alpha = 1.0f;
        paint_coverage_paint(c, x, y, k->w, k->h, k->cover, k->w, &p);
    } else {
        paint_coverage(c, x, y, k->w, k->h, k->cover, k->w, rgb, 1.0f);
    }
    return k->advance;
}
