/*
 * The in-game layer's decisions (logic.h): no Windows calls here, so the native tests check each one.
 */
#include "logic.h"
#include "postmath.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Windows' virtual-key numbers the layer reads (winuser.h), written out so this file needs no Windows header. */
#define K_LBUTTON 0x01
#define K_RBUTTON 0x02
#define K_TAB 0x09
#define K_RETURN 0x0D
#define K_ESCAPE 0x1B
#define K_SPACE 0x20
#define K_LEFT 0x25
#define K_UP 0x26
#define K_RIGHT 0x27
#define K_DOWN 0x28

/* The corners' names, in the order of CORNER_* (the launcher's words for them, values.py FPS_POSITIONS). */
static const char *const CORNER_NAMES[4] = {"top_left", "top_right", "bottom_left", "bottom_right"};

void settings_default(Settings *s)
{
    memset(s, 0, sizeof *s);
    /* Our pointer is on unless the launcher says the game hides it (a touch screen). */
    s->cursor = 1;
    /* The chip's corner: the one that covers none of the game's own labels on any of its screens (logic.h). */
    s->fps_corner = CORNER_BOTTOM_RIGHT;
    /* The picture's defaults, as the launcher's (values.py): the ones that looked best on this game's frames. */
    s->upscale = UPSCALE_DEFAULT;
    s->sharpness = SHARPNESS_DEFAULT;
    s->antialiasing = AA_DEFAULT;
    /* The sound engine's shortest period is asked for unless the launcher says not to (engine.c). */
    s->low_latency = 1;
}

/* Text equal to `word`, whatever its case. */
static int same(const char *a, const char *word)
{
    for (; *a && *word; a++, word++)
        if (tolower((unsigned char)*a) != tolower((unsigned char)*word))
            return 0;
    return *a == *word;
}

const char *const SETTINGS_NAMES[] = {"OPENDMT3_LANGUAGE", "OPENDMT3_CURSOR", "OPENDMT3_PACING", "OPENDMT3_FPS",
                                      "OPENDMT3_FPS_POSITION", "OPENDMT3_SOUND_DEVICE", "OPENDMT3_UPSCALE",
                                      "OPENDMT3_SHARPNESS", "OPENDMT3_ANTIALIASING", "OPENDMT3_PICTURE_SHAPE",
                                      "OPENDMT3_PASS_TIMES", "OPENDMT3_LOW_LATENCY", "OPENDMT3_SOUND_PATH",
                                      "OPENDMT3_RENDER"};

/* The sound paths' names, in the order of SOUND_PATH_* (the launcher's words for them, values.py SOUND_PATHS). */
const char *const SOUND_PATH_NAMES[SOUND_PATHS] = {"directsound", "openal", "openal-exclusive"};
const int SETTINGS_COUNT = sizeof SETTINGS_NAMES / sizeof SETTINGS_NAMES[0];

void settings_read(Settings *s, const char *name, const char *value)
{
    if (!name || !value)
        return;
    if (!strcmp(name, "OPENDMT3_LANGUAGE")) {
        /* Korean only when asked for; anything else is the launcher's first language, English. */
        s->korean = same(value, "ko");
    } else if (!strcmp(name, "OPENDMT3_CURSOR")) {
        /* "off": the launcher's touch-screen choice; the game's own pointer rules stay. */
        s->cursor = !same(value, "off");
    } else if (!strcmp(name, "OPENDMT3_PACING")) {
        /* "even": openDMT3's clock; "music": that clock led by a song's music while one plays; anything else the
         * client's own steps. */
        s->music_lock = same(value, "music");
        s->even_pacing = s->music_lock || same(value, "even");
    } else if (!strcmp(name, "OPENDMT3_FPS")) {
        s->show_fps = same(value, "on");
    } else if (!strcmp(name, "OPENDMT3_FPS_POSITION")) {
        /* A known corner's name; anything else leaves the default. */
        int c = corner_from_name(value);
        if (c >= 0)
            s->fps_corner = c;
    } else if (!strcmp(name, "OPENDMT3_UPSCALE")) {
        /* A known filter's name; anything else leaves the default. */
        int u = upscale_from_name(value);
        if (u >= 0)
            s->upscale = u;
    } else if (!strcmp(name, "OPENDMT3_ANTIALIASING")) {
        int a = aa_from_name(value);
        if (a >= 0)
            s->antialiasing = a;
    } else if (!strcmp(name, "OPENDMT3_SHARPNESS")) {
        /* Whole numbers 0 to 100 only; anything else leaves the default. */
        char *end = NULL;
        long v = strtol(value, &end, 10);
        if (end && end != value && !*end && v >= 0 && v <= 100)
            s->sharpness = (int)v;
    } else if (!strcmp(name, "OPENDMT3_PICTURE_SHAPE")) {
        /* "fill" stretches; anything else keeps the game's shape (the default). */
        s->fill = same(value, "fill");
    } else if (!strcmp(name, "OPENDMT3_PASS_TIMES")) {
        /* "on" measures the picture's GPU time by pass; anything else leaves it off (the default). */
        s->pass_times = same(value, "on");
    } else if (!strcmp(name, "OPENDMT3_RENDER")) {
        /* "display" draws the game at the picture's size in the window; anything else at its own (the default). */
        s->render_display = same(value, "display");
    } else if (!strcmp(name, "OPENDMT3_SOUND_DEVICE")) {
        /* A GUID: that device; empty or not a GUID: Windows' default output. */
        s->has_device = parse_guid(value, s->device);
    } else if (!strcmp(name, "OPENDMT3_LOW_LATENCY")) {
        /* "off" leaves Windows' sound engine at its own period; anything else keeps the default, on. */
        s->low_latency = !same(value, "off");
    } else if (!strcmp(name, "OPENDMT3_SOUND_PATH")) {
        /* A known path's name; anything else leaves Windows' own DirectSound (the default). */
        for (int i = 0; i < SOUND_PATHS; i++)
            if (same(value, SOUND_PATH_NAMES[i]))
                s->sound_path = i;
    }
}

int corner_from_name(const char *name)
{
    if (!name)
        return -1;
    /* The launcher's four names, in any case. */
    for (int i = 0; i < 4; i++)
        if (same(name, CORNER_NAMES[i]))
            return i;
    return -1;
}

/* One hexadecimal digit's value, or -1. */
static int hex(int c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    c = tolower(c);
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    return -1;
}

int parse_guid(const char *text, uint8_t out[16])
{
    if (!text)
        return 0;
    size_t n = strlen(text);
    /* The braces are optional; without them the text is 36 characters. */
    if (n == 38 && text[0] == '{' && text[37] == '}') {
        text++;
        n = 36;
    }
    if (n != 36)
        return 0;
    /* 32 digits in groups of 8-4-4-4-12, hyphens between the groups. */
    uint8_t raw[16];
    int digits = 0;
    for (size_t i = 0; i < 36; i++) {
        if (i == 8 || i == 13 || i == 18 || i == 23) {
            if (text[i] != '-')
                return 0;
            continue;
        }
        int v = hex((unsigned char)text[i]);
        if (v < 0)
            return 0;
        /* Two digits a byte, the first one the high half. */
        if (digits % 2 == 0)
            raw[digits / 2] = (uint8_t)(v << 4);
        else
            raw[digits / 2] |= (uint8_t)v;
        digits++;
    }
    /* The text writes Data1 (4 bytes), Data2 and Data3 (2 each) high byte first; the structure keeps them low byte
     * first. Data4 (8 bytes) stays in order. */
    out[0] = raw[3];
    out[1] = raw[2];
    out[2] = raw[1];
    out[3] = raw[0];
    out[4] = raw[5];
    out[5] = raw[4];
    out[6] = raw[7];
    out[7] = raw[6];
    memcpy(out + 8, raw + 8, 8);
    return 1;
}

void format_guid(const uint8_t in[16], char out[39])
{
    /* The reverse of parse_guid: Data1-3 read low byte first. */
    snprintf(out, 39, "{%02X%02X%02X%02X-%02X%02X-%02X%02X-%02X%02X-%02X%02X%02X%02X%02X%02X}", in[3], in[2], in[1],
             in[0], in[5], in[4], in[7], in[6], in[8], in[9], in[10], in[11], in[12], in[13], in[14], in[15]);
}

void pacer_start(Pacer *p, int64_t frequency, int fps)
{
    /* No limit (or no clock): a period of 0 never waits. */
    p->period = fps > 0 && frequency > 0 ? frequency / fps : 0;
    p->next = 0;
}

int64_t pacer_wait(Pacer *p, int64_t now)
{
    if (p->period <= 0)
        return 0;
    /* The first frame goes at once and starts the count. */
    if (p->next == 0) {
        p->next = now + p->period;
        return 0;
    }
    int64_t wait = p->next - now;
    if (wait > 0) {
        /* Early: wait for its time, and the next one is a period after it (even spacing, no drift). */
        p->next += p->period;
        return wait;
    }
    if (-wait > p->period) {
        /* More than a frame late (a load, a stall): start again from now instead of hurrying to catch up. */
        p->next = now + p->period;
    } else {
        /* A little late: on at once, the count kept so the average stays at the limit. */
        p->next += p->period;
    }
    return 0;
}

void music_lock_start(MusicLock *m)
{
    m->smooth = 0;
    m->primed = 0;
}

int64_t music_lock_step(MusicLock *m, double ahead_ms, int64_t period)
{
    /* The first reading as it is; then a tenth of each new one (the cursor's steps average out). */
    m->smooth = m->primed ? m->smooth * 0.9 + ahead_ms * 0.1 : ahead_ms;
    m->primed = 1;
    double e = m->smooth;
    /* Within 1 ms: nothing to correct (less than the cursor's own steps). */
    if (e > -1.0 && e < 1.0)
        return 0;
    /* A twentieth of the distance a frame: a drift goes in about a second, with no step a player sees. */
    double ms = e * 0.05;
    /* Small drifts at most 1 ms a frame; a stall's distance (over 50 ms) at most 4 ms a frame (a quarter of a frame). */
    double most = (e > 50.0 || e < -50.0) ? 4.0 : 1.0;
    if (ms > most)
        ms = most;
    if (ms < -most)
        ms = -most;
    /* Milliseconds to the counter's ticks (a period is 1000/60 ms). */
    return (int64_t)(ms * (double)period * 60.0 / 1000.0);
}

int64_t display_lock_step(double phase, int64_t refresh_ticks)
{
    if (phase < 0 || refresh_ticks <= 0)
        return 0;
    /* How far from the middle of its refresh the tick fell (-0.5 to 0.5 of a refresh). */
    double off = phase - 0.5;
    /* Near the middle: left as it is (the counter and the display drift apart slowly). */
    if (off > -0.125 && off < 0.125)
        return 0;
    /* A sixteenth of the distance, at most a 64th of a refresh a frame (under 0.07 ms at 240 Hz): late in the refresh
     * moves the next tick earlier, early moves it later. */
    double move = off / 16.0;
    if (move > 1.0 / 64.0)
        move = 1.0 / 64.0;
    if (move < -1.0 / 64.0)
        move = -1.0 / 64.0;
    return (int64_t)(-move * (double)refresh_ticks);
}

void guard_start(Guard *g)
{
    g->seen = g->late = g->bad = 0;
    /* The game's first 10 s load its screens, a stall of its own whatever the chain costs: not counted. */
    g->settle = 600;
    g->chain_ms = -1;
}

int guard_frame(Guard *g, double frame_ms, double chain_ms)
{
    /* The chain's time, smoothed over a few frames (one slow reading is not the chain's cost). */
    if (chain_ms >= 0)
        g->chain_ms = g->chain_ms < 0 ? chain_ms : g->chain_ms * 0.75 + chain_ms * 0.25;
    if (g->settle > 0) {
        g->settle--;
        return 0;
    }
    /* With no reading of the chain's time there is nothing to say it is the chain. */
    if (g->chain_ms < 0)
        return 0;
    const double budget = 1000.0 / 60.0 + 1.0;
    /* Late, and in time without the chain: the chain's doing (a load or a stall of the game's own is not). */
    if (frame_ms > budget && frame_ms - g->chain_ms <= budget)
        g->late++;
    if (++g->seen < GUARD_WINDOW)
        return 0;
    /* Two late windows in a row: the chain's cost holds, not a moment's. */
    g->bad = g->late >= GUARD_NEED ? g->bad + 1 : 0;
    int step = g->bad >= 2;
    /* A new window either way; after a step, its readings settle first (the GPU time is read four frames late). */
    g->seen = g->late = 0;
    if (step) {
        g->bad = 0;
        g->settle = 8;
        g->chain_ms = -1;
    }
    return step;
}

int hold_keys(uint8_t keys[256], int card_open, int waiting)
{
    /* The keys and buttons a player answers the layer with. */
    static const unsigned answer[] = {K_LBUTTON, K_RBUTTON, K_TAB,  K_RETURN, K_ESCAPE,
                                      K_SPACE,   K_LEFT,    K_UP,   K_RIGHT,  K_DOWN};
    const int count = (int)(sizeof answer / sizeof answer[0]);
    if (card_open) {
        /* The menu or the question is up: the game sees nothing pressed (it goes on, untouched), and once it
         * closes the answer's keys must be let go before the game sees them again. */
        memset(keys, 0, 256);
        return 1;
    }
    /* Esc never reaches the game: its own Esc ends it at once, with no question (a stray key would end a song), a quit
     * by a key as Alt+F4 would be; only the bar's X quits, after asking. */
    keys[K_ESCAPE] = 0;
    if (!waiting)
        return 0;
    int still = 0;
    for (int i = 0; i < count; i++) {
        /* The high bit of a key's byte says it is down. */
        if (keys[answer[i]] & 0x80) {
            still = 1;
            keys[answer[i]] = 0;
        }
    }
    /* Every one of them up: the game has its keys back. */
    return still;
}

/* The words: the buttons in the game's capitals (it writes its own so: NO ID CARD), Korean as it is written. */
static const char *const MENU_EN[] = {"BACK TO THE GAME", "SHOW FPS", "QUIT THE GAME"};
static const char *const MENU_KO[] = {"게임으로 돌아가기", "FPS 표시", "게임 끝내기"};
static const char *const QUIT_EN[] = {"KEEP PLAYING", "QUIT THE GAME"};
static const char *const QUIT_KO[] = {"계속하기", "게임 끝내기"};

int card_count(const Card *c)
{
    return c->open == CARD_NONE ? 0 : c->open == CARD_MENU ? 3 : 2;
}

/* The answer that quits: the last one, in both cards. */
static int quit_index(const Card *c)
{
    return card_count(c) - 1;
}

const char *card_label(const Card *c, int i, int *danger)
{
    if (danger)
        *danger = i == quit_index(c);
    if (i < 0 || i >= card_count(c))
        return "";
    if (c->open == CARD_MENU)
        return c->korean ? MENU_KO[i] : MENU_EN[i];
    return c->korean ? QUIT_KO[i] : QUIT_EN[i];
}

const char *card_state(const Card *c, int i)
{
    /* Show FPS says what it is now, at its row's right, as a switch does. */
    if (c->open != CARD_MENU || i != 1)
        return NULL;
    return c->fps ? (c->korean ? "켬" : "ON") : (c->korean ? "끔" : "OFF");
}

const char *card_title(const Card *c)
{
    /* The menu is a list under its chip, with no title; the X asks before anything ends. Titles are sentences, as
     * the game's own ("Data authentication failed"). */
    if (c->open != CARD_QUIT)
        return NULL;
    return c->korean ? "게임을 끝낼까요?" : "Quit the game?";
}

const char *card_line(const Card *c)
{
    /* What quitting loses, plainly: the game sends a play's results when the play ends, so a play cut short (its
     * stages so far and the song in progress) is not kept. Said only while a song plays, where it is true: on the
     * game's menus no play may be going on. */
    if (c->open != CARD_QUIT || !c->song)
        return NULL;
    return c->korean ? "진행 중인 플레이는 기록되지 않습니다." : "A play in progress is not kept.";
}

void card_open(Card *c, int what)
{
    c->open = what;
    /* The first answer goes on with the game: Enter at once never ends a song. */
    c->focus = 0;
}

int card_key(Card *c, unsigned vk)
{
    int n = card_count(c);
    if (!n)
        return ACT_NONE;
    if (vk == K_LEFT || vk == K_UP) {
        /* Round the answers, as a list does. */
        c->focus = (c->focus + n - 1) % n;
        return ACT_REDRAW;
    }
    if (vk == K_RIGHT || vk == K_DOWN || vk == K_TAB) {
        c->focus = (c->focus + 1) % n;
        return ACT_REDRAW;
    }
    if (vk == K_RETURN || vk == K_SPACE)
        return card_choose(c, c->focus);
    if (vk == K_ESCAPE) {
        /* Esc closes: back to the game. */
        c->open = CARD_NONE;
        return ACT_CLOSE;
    }
    /* Any other key waits while the card is open. */
    return ACT_NONE;
}

int card_choose(Card *c, int i)
{
    if (i < 0 || i >= card_count(c))
        return ACT_NONE;
    if (c->open == CARD_MENU && i == 1) {
        /* Show FPS: turned over, the menu stays (its row now says the other state). */
        c->fps = !c->fps;
        return ACT_FPS;
    }
    if (i == quit_index(c)) {
        /* Quit the game: in the question it is the answer; in the menu the player already went looking for it. */
        c->open = CARD_NONE;
        return ACT_QUIT;
    }
    /* The first answer: back to the game. */
    c->open = CARD_NONE;
    return ACT_CLOSE;
}

float ui_unit(int area_h)
{
    /* The game's own 768 lines to the area's; a window never smaller than the game's picture keeps it at 1 or more. */
    float u = (float)area_h / (float)GAME_H;
    return u < 1.0f ? 1.0f : u;
}

/* The measures, in game pixels (multiplied by the unit). The bar is as tall as the game's own top bar in a song (its
 * band ends at line 69 of 768, measured: SKIP or GUIDE ON, the score, the groove meter's label), so it covers that
 * band whole and no more. Its chips are the launcher's buttons (34 tall, their ends leaning as its buttons' do), 50
 * wide, in the bar's middle: the window's three 6 apart with the X 12 from the right edge, the menu's 16 further left.
 * The question is 300 wide (the game's panels hold 16 pixel lines in 627; this one holds one line and two answers),
 * its right edge under the X's; the menu 216 wide under its own chip. Both hang 6 under the bar and are at most 106
 * tall, so with their shadows they end above a quarter of the game's height (line 192 of 768) on a screen of any
 * shape: nothing of the layer reaches the middle of the game. The title tab keeps the game's slope: each end leans in
 * 30 pixels over 37. */
#define BAR_H 70.0f
#define CHIP_W 50.0f
#define CHIP_H 34.0f
#define CHIP_GAP 6.0f
#define MENU_GAP 16.0f
#define EDGE 12.0f
#define DROP 6.0f
#define QUIT_W 300.0f
#define MENU_W 216.0f
#define TAB_H 28.0f
#define PAD 16.0f
#define ANSWER_H 32.0f
#define ROW_H 28.0f
#define ROW_GAP 3.0f

void ui_layout(const Card *c, int area_w, int area_h, UiLayout *l)
{
    memset(l, 0, sizeof *l);
    float u = ui_unit(area_h), w = (float)area_w;
    l->u = u;
    /* The bar across the whole top; its height the game's own top bar's. */
    l->bar = (Box){0, 0, w, BAR_H * u};
    /* The product's mark at the left, the launcher's picture of it (cut to what it draws) 46 of the bar's 70 lines
     * tall, in its middle: DMT3's capitals then 23 lines, as the mark set at 34 was. */
    l->px_name = 34 * u;
    l->name_h = 46 * u;
    l->name_x = 20 * u;
    l->name_y = BAR_H * u / 2;
    /* The X at the right edge, minimise and full screen left of it, the menu's chip a little apart: all in the bar's
     * middle. */
    float top = (BAR_H - CHIP_H) / 2 * u;
    l->chip[CHIP_X] = (Box){w - (EDGE + CHIP_W) * u, top, CHIP_W * u, CHIP_H * u};
    l->chip[CHIP_FULL] = (Box){l->chip[CHIP_X].x - (CHIP_GAP + CHIP_W) * u, top, CHIP_W * u, CHIP_H * u};
    l->chip[CHIP_MIN] = (Box){l->chip[CHIP_FULL].x - (CHIP_GAP + CHIP_W) * u, top, CHIP_W * u, CHIP_H * u};
    l->chip[CHIP_MENU] = (Box){l->chip[CHIP_MIN].x - (MENU_GAP + CHIP_W) * u, top, CHIP_W * u, CHIP_H * u};
    /* Type sizes: the title as the game's tab writes (1.2 times its lines), the line as its messages, the answers as its
     * buttons. */
    l->px_title = 17 * u;
    l->px_line = 15 * u;
    l->px_button = 13 * u;
    l->count = card_count(c);
    if (c->open == CARD_QUIT) {
        /* The question under the X, its right edge on the X's. */
        float pw = QUIT_W * u;
        l->panel = (Box){l->chip[CHIP_X].x + l->chip[CHIP_X].w - pw, (BAR_H + DROP) * u, pw, 0};
        /* The tab hangs from the panel's top edge across most of it, narrowing down with the game's slope. */
        l->tab = (Box){l->panel.x + 28 * u, l->panel.y, pw - 56 * u, TAB_H * u};
        /* The one line under the tab while a song plays; with none, the answers come up into its place. */
        float below = card_line(c) ? 36.0f : 12.0f;
        l->line_y = card_line(c) ? l->panel.y + (TAB_H + 19) * u : 0.0f;
        /* The two answers side by side, Keep playing first (left), as the keys go. */
        float aw = (QUIT_W - 2 * PAD - 10) / 2 * u, ay = l->panel.y + (TAB_H + below) * u;
        for (int i = 0; i < l->count && i < 2; i++)
            l->rows[i] = (Box){l->panel.x + PAD * u + (float)i * (aw + 10 * u), ay, aw, ANSWER_H * u};
        l->panel.h = (TAB_H + below + ANSWER_H + 10) * u;
    } else if (c->open == CARD_MENU) {
        /* The menu under its chip, its right edge on the chip's, its rows one under the other. */
        float pw = MENU_W * u;
        l->panel = (Box){l->chip[CHIP_MENU].x + l->chip[CHIP_MENU].w - pw, (BAR_H + DROP) * u, pw, 0};
        for (int i = 0; i < l->count && i < 4; i++)
            l->rows[i] = (Box){l->panel.x + 8 * u, l->panel.y + (8 + (float)i * (ROW_H + ROW_GAP)) * u, pw - 16 * u,
                               ROW_H * u};
        l->panel.h = (16 + (float)l->count * ROW_H + (float)(l->count - 1) * ROW_GAP) * u;
    }
}

/* Inside a box. */
static int inside(const Box *b, float x, float y)
{
    return x >= b->x && x < b->x + b->w && y >= b->y && y < b->y + b->h;
}

int ui_hit(const UiLayout *l, float x, float y)
{
    /* The answers first (they are inside the panel), then the panel, then the chips, then the rest of the bar. */
    for (int i = 0; i < l->count && i < 4; i++)
        if (inside(&l->rows[i], x, y))
            return i;
    if (l->panel.w > 0 && inside(&l->panel, x, y))
        return HIT_PANEL;
    /* A chip is easier to hit with a little room round it (half the gap between the window's chips). */
    static const int hits[CHIPS] = {HIT_MENU, HIT_MIN, HIT_FULL, HIT_X};
    for (int i = 0; i < CHIPS; i++) {
        Box b = l->chip[i];
        float r = CHIP_GAP / 2 * l->u;
        Box near = {b.x - r, b.y - r, b.w + 2 * r, b.h + 2 * r};
        if (inside(&near, x, y))
            return hits[i];
    }
    if (inside(&l->bar, x, y))
        return HIT_BAR;
    return HIT_NONE;
}

int ui_hit_chip(int hit)
{
    /* The chips' hits back to their places in the bar. */
    return hit == HIT_MENU ? CHIP_MENU : hit == HIT_MIN ? CHIP_MIN : hit == HIT_FULL ? CHIP_FULL : hit == HIT_X ? CHIP_X : -1;
}

int ui_at_top_edge(float y, int area_h)
{
    /* The top two lines of a 768-line game (3 at 1080 lines): where a mouse stops against the screen's edge, above
     * every control of the game's (its top bar's buttons start 8 lines down). */
    return y <= 2.0f * ui_unit(area_h);
}

int ui_swipe_down(float start_y, float y, int area_h)
{
    float u = ui_unit(area_h);
    /* Begun within the top 4 lines (a finger cannot land on the very edge) and drawn down 24 lines or more. */
    return start_y <= 4.0f * u && y - start_y >= 24.0f * u;
}

/* The mark: 40 game pixels wide along the top edge, 6 tall (8 with the pointer on it), its ends leaning in with the
 * game's tab slope; small against the game's top band (70 lines), where it hangs over the edge of whatever the game
 * shows there. */
#define MARK_W 40.0f
#define MARK_H 6.0f
#define MARK_LIT_H 8.0f
#define MARK_NEAR 10.0f

Box ui_mark_box(int area_w, int area_h, int lit)
{
    float u = ui_unit(area_h);
    Box b;
    /* In the middle of the top edge. */
    b.w = MARK_W * u;
    b.h = (lit ? MARK_LIT_H : MARK_H) * u;
    b.x = ((float)area_w - b.w) / 2;
    b.y = 0;
    return b;
}

int ui_on_mark(float x, float y, int area_w, int area_h)
{
    float u = ui_unit(area_h);
    /* The lit mark's box with room round it: a pointer resting near enough is on it (it is small to aim at). */
    Box b = ui_mark_box(area_w, area_h, 1);
    float r = MARK_NEAR * u;
    Box near = {b.x - r, b.y - r, b.w + 2 * r, b.h + 2 * r};
    return inside(&near, x, y);
}

void gate_start(RevealGate *g)
{
    /* No press yet: the game has been quiet for as long as can be. */
    g->pressed_at = -1e12;
    g->down = 0;
    g->armed = 0;
    g->rest_at = 0;
}

void gate_press(RevealGate *g, double now, int down)
{
    /* The game is played: the time of it, whether a button stays down, and no rest from before. */
    g->pressed_at = now;
    g->down = down;
    g->armed = 0;
}

void gate_move(RevealGate *g, double now, int at_place, int button_down)
{
    /* Held down, or away from the edge and the mark: no rest. */
    if (button_down || !at_place) {
        g->armed = 0;
        return;
    }
    /* Come to the place: its rest starts now (a move within the place keeps the rest it has). */
    if (!g->armed) {
        g->armed = 1;
        g->rest_at = now;
    }
}

int gate_due(RevealGate *g, double now, int still_there)
{
    if (!g->armed)
        return 0;
    /* Gone from the place, or a button down on the game: the rest is over. */
    if (!still_there || g->down) {
        g->armed = 0;
        return 0;
    }
    /* Not long enough there yet, or the game played too lately: the rest waits (it may still come). */
    if (now - g->rest_at < REVEAL_REST_MS || now - g->pressed_at < REVEAL_QUIET_MS)
        return 0;
    /* The bar comes; the rest is used up. */
    g->armed = 0;
    return 1;
}

int gate_quiet(const RevealGate *g, double now)
{
    /* Nothing down, and the last press or release long enough ago. */
    return !g->down && now - g->pressed_at >= REVEAL_QUIET_MS;
}

void gate_stall(RevealGate *g, double now, double gap)
{
    /* Where the pause began: what came before it moves on by the pause, what the game heard within it stays. */
    double from = now - gap;
    /* The last press or release before the pause: its quiet counts the game's running time only. */
    if (g->pressed_at < from)
        g->pressed_at += gap;
    /* A rest begun before the pause: it has lasted only while the game ran. */
    if (g->armed && g->rest_at < from)
        g->rest_at += gap;
}

void bar_clock_start(BarClock *b)
{
    /* Not shown, never brought. */
    b->since = b->stay = b->reveal_until = 0;
    b->by_touch = 0;
    b->parked = 0;
}

void bar_clock_rest(BarClock *b, double now)
{
    /* A finger's bar keeps its four seconds: the pointer it leaves behind is no mouse on it. */
    if (b->by_touch && now < b->since + b->stay)
        return;
    b->by_touch = 0;
    b->since = now;
    b->stay = BAR_STAY_MS;
}

void bar_clock_touch(BarClock *b, double now)
{
    /* Whole for a finger's time, whatever the pointer it leaves does. */
    b->by_touch = 1;
    b->since = now;
    b->stay = BAR_TOUCH_MS;
}

void bar_clock_reveal(BarClock *b, double now)
{
    /* By itself: whole until then whatever the pointer does (the pointer on it may keep it longer after, once it has
     * moved: where it was when the bar came is no player's doing). */
    b->reveal_until = now + BAR_REVEAL_MS;
    b->parked = 1;
}

void bar_clock_hide(BarClock *b)
{
    /* Its times over: it fades out from now. */
    bar_clock_start(b);
}

void bar_clock_moved(BarClock *b)
{
    /* A real move of the mouse: a finger's bar keeps no longer, and a parked pointer is a pointer again. */
    b->by_touch = 0;
    b->parked = 0;
}

int bar_clock_pointer_counts(const BarClock *b)
{
    /* Neither the pointer a finger leaves nor one that has not moved since the bar came by itself. */
    return !b->by_touch && !b->parked;
}

int bar_clock_whole(const BarClock *b, double now)
{
    /* The later of its stay after the pointer and a showing by itself. */
    double until = b->since + b->stay > b->reveal_until ? b->since + b->stay : b->reveal_until;
    return (b->since > 0 || b->reveal_until > 0) && now < until;
}

Box toast_box(int area_w, int area_h, float text_w)
{
    float u = ui_unit(area_h);
    Box b;
    /* The words with room each side for the tab's slanted ends, 40 tall, hanging from the top edge in the middle as the
     * game's title tab hangs from its panel: inside the game's top band, over the bar when it shows. */
    b.w = text_w + 2 * (22 + 40 * 30.0f / 37.0f) * u;
    b.h = 40 * u;
    b.x = ((float)area_w - b.w) / 2;
    b.y = 0;
    return b;
}

/* The chip's foot at the bottom corners: 41 lines over the game's foot, 6 above ID CARD and NET at the left (from line
 * 733 of 768) and 15 above FREE PLAY at the right (from line 742), measured on the game's screens. */
#define FPS_FOOT 41.0f

Box fps_box(int area_w, int area_h, int corner)
{
    float u = ui_unit(area_h);
    Box b;
    /* 84 x 40: the frames a second over the frame's mean length. */
    b.w = 84 * u;
    b.h = 40 * u;
    int right = corner == CORNER_TOP_RIGHT || corner == CORNER_BOTTOM_RIGHT;
    int foot = corner == CORNER_BOTTOM_LEFT || corner == CORNER_BOTTOM_RIGHT;
    /* 12 in from its side; at the top 6 down, at the foot above the game's labels. */
    b.x = right ? (float)area_w - EDGE * u - b.w : EDGE * u;
    b.y = foot ? (float)area_h - (FPS_FOOT + 40) * u : 6 * u;
    return b;
}

float ease_out(float t)
{
    if (t <= 0.0f)
        return 0.0f;
    if (t >= 1.0f)
        return 1.0f;
    /* A cubic easing out: quick at first, settling into place. */
    float k = 1.0f - t;
    return 1.0f - k * k * k;
}

void note_words(int korean, int aa_changed, int aa, char *out, int size)
{
    /* One short sentence, as the game says its own; what the picture is now in brackets, in the launcher's words for
     * it (the Screen page's names). "Quality lowered", as the Korean says (화질을 낮췄습니다): "lightened" read as a
     * brighter picture. */
    const char *what;
    if (aa_changed)
        what = aa == AA_FXAA ? "FXAA" : korean ? "안티에일리어싱 끔" : "Anti-aliasing off";
    else
        what = korean ? "부드럽게 확대" : "Smooth upscale";
    snprintf(out, (size_t)size, korean ? "60 FPS를 지키려고 화질을 낮췄습니다(%s)" : "Picture quality lowered to keep 60 FPS (%s)",
             what);
}

/* ------------------------------------------------------------------------------------------ the picture's place */

PicRect picture_rect(int cw, int ch, int fill)
{
    PicRect r = {0, 0, cw, ch};
    if (fill || cw <= 0 || ch <= 0)
        return r;
    if ((long long)cw * GAME_H > (long long)ch * GAME_W) {
        /* Wider than the game: its whole height, bars left and right (the width rounded to a whole pixel). */
        r.w = (int)(((long long)ch * GAME_W + GAME_H / 2) / GAME_H);
        r.x = (cw - r.w) / 2;
    } else if ((long long)cw * GAME_H < (long long)ch * GAME_W) {
        /* Taller: its whole width, bars above and below. */
        r.h = (int)(((long long)cw * GAME_H + GAME_W / 2) / GAME_W);
        r.y = (ch - r.h) / 2;
    }
    return r;
}

void render_size_for(int cw, int ch, int fill, int max_w, int max_h, int *w, int *h)
{
    PicRect r = picture_rect(cw, ch, fill);
    /* Past the device's largest texture: the largest of the picture's shape that fits. */
    if (max_w > 0 && max_h > 0 && (r.w > max_w || r.h > max_h)) {
        double k = (double)max_w / r.w, kh = (double)max_h / r.h;
        if (kh < k)
            k = kh;
        r.w = (int)(r.w * k);
        r.h = (int)(r.h * k);
    }
    /* Smaller than the game's own picture either way: its own size (its art is drawn for it). */
    if (r.w < GAME_W || r.h < GAME_H) {
        r.w = GAME_W;
        r.h = GAME_H;
    }
    *w = r.w;
    *h = r.h;
}

long scale_edge(long v, int from, int to)
{
    /* In 64 bits, the half added away from zero before the division. */
    long long n = (long long)v * to;
    return (long)(n >= 0 ? (n + from / 2) / from : -((-n + from / 2) / from));
}

void game_from_client(int qx, int qy, int cw, int ch, int *gx, int *gy)
{
    /* As the helper's imul and idiv do: C's division, towards zero. */
    *gx = cw > 0 ? qx * GAME_W / cw : qx;
    *gy = ch > 0 ? qy * GAME_H / ch : qy;
}

/* One axis: the client coordinate whose helper sum (q * game / client, towards zero) gives the game pixel under the
 * centre of picture pixel `p` (the picture `size` wide, starting at `at`). */
static int pointer_axis(int p, int at, int size, int client, int game)
{
    if (size <= 0 || client <= 0)
        return p;
    /* The game pixel whose area holds the centre: floor((p - at + 0.5) * game / size), in whole numbers. */
    long long num = (long long)(2 * (p - at) + 1) * game, den = 2LL * size;
    long long g = num >= 0 ? num / den : -((-num + den - 1) / den);
    /* The smallest q with q * game / client >= g (for g < 0 the largest with q * game / client <= g, as division goes
     * towards zero there): the first client coordinate inside that game pixel. */
    long long q = g >= 0 ? (g * client + game - 1) / game : -((-g * client + game - 1) / game);
    return (int)q;
}

void pointer_for_game(int px, int py, int cw, int ch, PicRect r, int *qx, int *qy)
{
    *qx = pointer_axis(px, r.x, r.w, cw, GAME_W);
    *qy = pointer_axis(py, r.y, r.h, ch, GAME_H);
}

/* ------------------------------------------------------------------------------------------------- slot index */

/* A key's first place: Fibonacci hashing of its address (its low bits are its alignment, the same for every key), the
 * product's top bits. */
static unsigned slot_home(const void *key)
{
    unsigned long long v = (unsigned long long)(uintptr_t)key * 0x9E3779B97F4A7C15ull;
    /* 8192 places: the product's top 13 bits. */
    return (unsigned)(v >> 51) & (SLOT_INDEX_SIZE - 1);
}

int slot_index_get(const SlotIndex *x, const void *key)
{
    unsigned mask = SLOT_INDEX_SIZE - 1;
    /* From its first place on, until the key or an empty place (where it would have been put). */
    for (unsigned i = slot_home(key), n = 0; n < SLOT_INDEX_SIZE; i = (i + 1) & mask, n++) {
        if (!x->key[i])
            return -1;
        if (x->key[i] == key)
            return x->slot[i];
    }
    return -1;
}

int slot_index_put(SlotIndex *x, const void *key, int slot)
{
    unsigned mask = SLOT_INDEX_SIZE - 1;
    /* The key's own place when it is in already, else the first empty one from its first place on. */
    for (unsigned i = slot_home(key), n = 0; n < SLOT_INDEX_SIZE; i = (i + 1) & mask, n++) {
        if (!x->key[i] || x->key[i] == key) {
            x->key[i] = key;
            x->slot[i] = slot;
            return 1;
        }
    }
    return 0;
}

void slot_index_del(SlotIndex *x, const void *key)
{
    unsigned mask = SLOT_INDEX_SIZE - 1, hole = slot_home(key);
    /* Its place, or nothing to do. */
    for (unsigned n = 0;; hole = (hole + 1) & mask, n++) {
        if (n == SLOT_INDEX_SIZE || !x->key[hole])
            return;
        if (x->key[hole] == key)
            break;
    }
    /* The keys after it, up to the next empty place, moved back into the hole when the hole lies between a key's first
     * place and where it is (so every key stays reachable from its first place), the hole moving on with each. */
    for (unsigned j = (hole + 1) & mask; x->key[j]; j = (j + 1) & mask) {
        unsigned home = slot_home(x->key[j]);
        if (((j - home) & mask) >= ((j - hole) & mask)) {
            x->key[hole] = x->key[j];
            x->slot[hole] = x->slot[j];
            hole = j;
        }
    }
    x->key[hole] = NULL;
}

/* Each result's word for the log and the launcher's note, in the order of ENGINE_* (opendmt3/client/actions.py reads
 * them back). */
const char *const ENGINE_NAMES[ENGINE_RESULTS] = {"off", "no-device", "no-client3", "no-answer", "none-shorter",
                                                  "locked", "refused", "unchanged", "held"};

unsigned engine_period_ask(unsigned def, unsigned step, unsigned min, unsigned max)
{
    /* Each number must be there, and in the order the API promises: minimum <= default <= maximum. */
    if (!def || !step || !min || !max || min > max || def < min || def > max)
        return 0;
    /* The minimum as a whole number of steps (it is one already when the driver keeps the rules): rounded up, so it
     * never asks for less than the driver offers. */
    unsigned ask = (min + step - 1) / step * step;
    /* Rounded past the maximum, or nothing shorter than the default: nothing to ask. */
    if (ask > max || ask >= def)
        return 0;
    return ask;
}

int engine_period_held(unsigned def, unsigned got)
{
    /* Read, and shorter than the default: the engine runs in shorter steps while the stream runs. */
    return got > 0 && got < def;
}

double engine_ms(unsigned frames, unsigned rate)
{
    /* No rate read: no time to give. */
    return rate ? frames * 1000.0 / rate : 0.0;
}

void engine_note(const EngineReport *r, char *out, int size)
{
    /* A result out of range is never written as some other's word. */
    const char *word = r->result >= 0 && r->result < ENGINE_RESULTS ? ENGINE_NAMES[r->result] : "unknown";
    /* The device by its GUID, as the launcher keeps its choice (format_guid's upper case with braces). */
    char device[39];
    format_guid(r->device, device);
    /* Words then numbers, one space apart, as key=value: the launcher takes the ones it knows. */
    snprintf(out, (size_t)size, "engine %s output=%s device=%s rate=%u default=%u step=%u min=%u max=%u before=%u "
             "asked=%u got=%u hr=0x%08lx", word, r->chosen ? "chosen" : "default", device, r->rate, r->def, r->step,
             r->min, r->max, r->before, r->asked, r->got, r->hr);
}
