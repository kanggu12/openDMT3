/*
 * The native tests: the in-game layer's decisions (logic.c) and pictures (paint.c, look.c), built with the same
 * compiler as the DLL and run under Wine by test.sh. Each check prints its name; the program ends with the count of
 * failures as its exit code.
 */
#include <windows.h>
/* windows.h's old 16-bit words, names of the tests' own variables here. */
#undef near
#undef far
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "contacts.h"
#include "ingame.h"
#include "logfile.h"
#include "logic.h"
#include "methods.h"
#include "passtimes.h"
#include "postmath.h"
#include "redirect.h"
#include "look.h"
#include "paint.h"

static int failures, checks;

/* One check: its name, and whether it held. */
static void check(int ok, const char *name)
{
    checks++;
    if (!ok)
        failures++;
    printf("%s %s\n", ok ? "ok  " : "FAIL", name);
}

/* A stand-in for GDI's words: every letter 10 pixels wide, nothing drawn. */
static float no_text(void *ctx, Canvas *c, const char *utf8, float px, float cx, float cy, uint32_t rgb, int edge)
{
    (void)ctx, (void)c, (void)px, (void)cx, (void)cy, (void)rgb, (void)edge;
    return 10.0f * (float)strlen(utf8);
}

static void test_settings(void)
{
    Settings s;
    settings_default(&s);
    check(!s.korean && s.cursor && !s.even_pacing && !s.show_fps && !s.has_device && s.fps_corner == CORNER_BOTTOM_RIGHT,
          "settings: the defaults (the chip's corner the bottom right)");
    settings_read(&s, "OPENDMT3_LANGUAGE", "ko");
    settings_read(&s, "OPENDMT3_CURSOR", "off");
    settings_read(&s, "OPENDMT3_PACING", "even");
    settings_read(&s, "OPENDMT3_FPS", "on");
    settings_read(&s, "OPENDMT3_FPS_POSITION", "Top_Left");
    settings_read(&s, "OPENDMT3_SOUND_DEVICE", "{0000000A-0000-0000-0000-00000000000B}");
    check(s.korean && !s.cursor && s.even_pacing && s.show_fps && s.has_device && s.fps_corner == CORNER_TOP_LEFT,
          "settings: the launcher's choices read");
    settings_read(&s, "OPENDMT3_FPS_POSITION", "middle");
    check(s.fps_corner == CORNER_TOP_LEFT && corner_from_name("bottom_left") == CORNER_BOTTOM_LEFT &&
              corner_from_name("top_right") == CORNER_TOP_RIGHT && corner_from_name("") == -1,
          "settings: the chip's four corners by name, any other name leaves the corner");
    check(s.device[0] == 0x0a && s.device[15] == 0x0b && s.device[1] == 0, "settings: the GUID's bytes in Windows' order");
    char text[39];
    format_guid(s.device, text);
    check(!strcmp(text, "{0000000A-0000-0000-0000-00000000000B}"), "settings: the GUID written back");
    settings_read(&s, "OPENDMT3_PACING", "fast");
    check(!s.even_pacing, "settings: any other pacing is the client's own");
    settings_read(&s, "OPENDMT3_SOUND_DEVICE", "");
    check(!s.has_device, "settings: no device is Windows' default output");
    uint8_t g[16];
    check(!parse_guid("{0000000A-0000-0000-0000-00000000000}", g) && !parse_guid("0000000A_0000-0000-0000-00000000000B", g)
              && parse_guid("0000000a-0000-0000-0000-00000000000b", g),
          "settings: only whole GUIDs, braces optional");
    /* The picture's GPU time by pass: off unless the launcher's switch says "on". */
    Settings t;
    settings_default(&t);
    int off_first = !t.pass_times;
    settings_read(&t, "OPENDMT3_PASS_TIMES", "ON");
    int on = t.pass_times;
    settings_read(&t, "OPENDMT3_PASS_TIMES", "yes");
    check(off_first && on && !t.pass_times, "settings: the GPU time by pass off by default, on only for \"on\"");
    /* The sound engine's shortest period: asked for unless the launcher says "off" (any case). */
    Settings u;
    settings_default(&u);
    int asked_first = u.low_latency;
    settings_read(&u, "OPENDMT3_LOW_LATENCY", "OFF");
    int off = !u.low_latency;
    settings_read(&u, "OPENDMT3_LOW_LATENCY", "maybe");
    check(asked_first && off && u.low_latency, "settings: low latency on by default, off only for \"off\"");
    /* The Mixer: Windows' DirectSound unless a known OpenAL Soft path is named (any case). */
    int direct_first = u.sound_path == SOUND_PATH_DIRECTSOUND;
    settings_read(&u, "OPENDMT3_SOUND_PATH", "OpenAL-Exclusive");
    int exclusive = u.sound_path == SOUND_PATH_OPENAL_EXCLUSIVE;
    settings_read(&u, "OPENDMT3_SOUND_PATH", "openal");
    int shared = u.sound_path == SOUND_PATH_OPENAL;
    settings_read(&u, "OPENDMT3_SOUND_PATH", "xaudio2");
    check(direct_first && exclusive && shared && u.sound_path == SOUND_PATH_OPENAL &&
              !strcmp(SOUND_PATH_NAMES[SOUND_PATH_DIRECTSOUND], "directsound"),
          "settings: the mixer DirectSound by default, OpenAL Soft's two by name, another name leaves it");
    /* The game drawn at the picture's size: off (its own 1280x768) unless the launcher says "display". */
    settings_default(&t);
    int own_first = !t.render_display;
    settings_read(&t, "OPENDMT3_RENDER", "Display");
    int display = t.render_display;
    settings_read(&t, "OPENDMT3_RENDER", "native");
    check(own_first && display && !t.render_display,
          "settings: the game drawn at its own size by default, at the display's only for \"display\"");
}

/* The sound engine's period (engine.c's decisions): what to ask for from IAudioClient3's answer, whether what the
 * engine runs at after is worth holding, and the launcher's note. */
static void test_engine(void)
{
    /* Windows' own HDAudio driver at 48 kHz: 128 to 480 frames (Microsoft, Low Latency Audio). */
    check(engine_period_ask(480, 16, 128, 480) == 128, "engine: the driver's shortest period is asked for");
    /* Many makers' own drivers offer only their default. */
    check(engine_period_ask(480, 480, 480, 480) == 0, "engine: nothing shorter than the default, nothing asked");
    /* Wine's ALSA driver (measured): a shortest of half its default. */
    check(engine_period_ask(480, 1, 240, 480) == 240, "engine: Wine's ALSA answer asks for its 240 frames");
    /* Wine's PulseAudio driver (measured): a shortest of 0 frames, which no stream can be made with. */
    check(engine_period_ask(441, 1, 0, 441) == 0, "engine: a shortest of 0 frames is no answer");
    check(engine_period_ask(480, 32, 100, 480) == 128, "engine: a shortest between steps rounded up to a whole step");
    check(engine_period_ask(480, 512, 100, 480) == 0, "engine: a step rounded past the longest asks nothing");
    check(engine_period_ask(480, 16, 512, 256) == 0 && engine_period_ask(600, 16, 128, 480) == 0 &&
              engine_period_ask(100, 16, 128, 480) == 0 && engine_period_ask(480, 0, 128, 480) == 0 &&
              engine_period_ask(0, 16, 128, 480) == 0,
          "engine: numbers out of the API's own order ask nothing");
    check(engine_period_held(480, 128) && !engine_period_held(480, 480) && !engine_period_held(480, 0) &&
              !engine_period_held(480, 600),
          "engine: held only when the engine runs shorter than its default");
    check(fabs(engine_ms(128, 48000) - 2.6667) < 0.001 && fabs(engine_ms(480, 48000) - 10.0) < 1e-9 &&
              engine_ms(480, 0) == 0.0,
          "engine: frames in milliseconds at the mix rate");
    EngineReport r;
    memset(&r, 0, sizeof r);
    r.result = ENGINE_HELD;
    r.chosen = 1;
    parse_guid("{0000000A-0000-0000-0000-00000000000B}", r.device);
    r.rate = 48000;
    r.def = 480;
    r.step = 16;
    r.min = 128;
    r.max = 480;
    r.before = 480;
    r.asked = 128;
    r.got = 128;
    char line[256];
    engine_note(&r, line, sizeof line);
    check(!strcmp(line, "engine held output=chosen device={0000000A-0000-0000-0000-00000000000B} rate=48000 "
                        "default=480 step=16 min=128 max=480 before=480 asked=128 got=128 hr=0x00000000"),
          "engine: the launcher's note, words then numbers");
    r.chosen = 0;
    engine_note(&r, line, sizeof line);
    check(strstr(line, " output=default ") != NULL, "engine: Windows' default output said as such");
    r.result = ENGINE_RESULTS;
    engine_note(&r, line, sizeof line);
    check(!strncmp(line, "engine unknown ", 15), "engine: a result out of range is no other's word");
    char small[12];
    memset(small, 'x', sizeof small);
    r.result = ENGINE_OFF;
    engine_note(&r, small, 8);
    check(!strcmp(small, "engine ") && small[8] == 'x', "engine: a short buffer holds a cut line and its end");
    check(!strcmp(ENGINE_NAMES[ENGINE_OFF], "off") && !strcmp(ENGINE_NAMES[ENGINE_HELD], "held") &&
              !strcmp(ENGINE_NAMES[ENGINE_UNCHANGED], "unchanged"),
          "engine: the results' words");
}

/* The game drawn at the picture's size: its size, and the rectangles turned to it and back (logic.c). */
static void test_render_size(void)
{
    int w, h, ok = 1;
    render_size_for(1920, 1080, 0, 16384, 16384, &w, &h);
    ok &= w == 1800 && h == 1080;
    render_size_for(2560, 1440, 0, 16384, 16384, &w, &h);
    ok &= w == 2400 && h == 1440;
    render_size_for(3840, 2160, 0, 16384, 16384, &w, &h);
    ok &= w == 3600 && h == 2160;
    check(ok, "render size: the picture's place at 1080, 1440 and 2160 lines");
    render_size_for(1920, 1080, 1, 16384, 16384, &w, &h);
    int filled = w == 1920 && h == 1080;
    render_size_for(1024, 600, 0, 16384, 16384, &w, &h);
    int small = w == 1280 && h == 768;
    render_size_for(3840, 2160, 0, 2048, 2048, &w, &h);
    check(filled && small && w == 2048 && h == 1228 && w * 3 <= h * 5 + 5,
          "render size: filling, a window under the game's size, a device's largest texture in the picture's shape");
    int round_trip = 1;
    for (long v = -10; v <= 1290 && round_trip; v++)
        round_trip = scale_edge(scale_edge(v, 1280, 1800), 1800, 1280) == v &&
                     scale_edge(scale_edge(v, 1280, 3600), 3600, 1280) == v;
    check(scale_edge(1280, 1280, 1800) == 1800 && scale_edge(640, 1280, 1800) == 900 &&
              scale_edge(-1, 1280, 1800) == -1 && round_trip,
          "render size: a rectangle's edges to the larger target and back, every one of the game's pixels");
    /* Through resets with the flip model: made full screen at 1080 lines (1800x1080), its own reset for a 1350x810
     * window and back keeps 1800x1080 (the game's glow targets live on at it); the game's own reset in the window
     * takes the window's; a first making, with nothing kept, takes the chosen. */
    int kw = 1800, kh = 1080, cw, ch;
    render_size_after_reset(1, kw, kh, 1350, 810, &cw, &ch);
    int kept_window = cw == 1800 && ch == 1080;
    render_size_after_reset(1, cw, ch, 1800, 1080, &cw, &ch);
    int kept_back = cw == 1800 && ch == 1080;
    render_size_after_reset(0, cw, ch, 1350, 810, &cw, &ch);
    int game_reset = cw == 1350 && ch == 810;
    render_size_after_reset(1, 0, 0, 1800, 1080, &cw, &ch);
    check(kept_window && kept_back && game_reset && cw == 1800 && ch == 1080,
          "render size: openDMT3's own reset keeps it, the game's own reset chooses it again");
}

/* The picture's GPU time by pass: medians by step name over a stretch (passtimes.c). */
static void test_pass_times(void)
{
    static PassTimes p;
    pt_clear(&p);
    /* Three frames: the blur twice in the second (its passes add up), the chain's pass each time. */
    pt_step(&p, "easu", 100), pt_step(&p, "blur", 10), pt_frame(&p);
    pt_step(&p, "easu", 300), pt_step(&p, "blur", 10), pt_step(&p, "blur", 20), pt_frame(&p);
    pt_step(&p, "easu", 200), pt_frame(&p);
    check(p.names == 2 && p.frames == 3 && p.n[0] == 3 && p.n[1] == 2, "pass times: a name a step, a sample a frame");
    check(fabsf(pt_median(&p, 0) - 200) < 0.01f && fabsf(pt_median(&p, 1) - 20) < 0.01f && pt_median(&p, 2) < 0,
          "pass times: the median of odd and even counts, none for a name not seen");
    char line[128];
    int len = pt_line(&p, line, sizeof line);
    check(!strcmp(line, "easu 200.0 us, blur 20.0 us (3 frames)") && len == (int)strlen(line),
          "pass times: the line names each step in the order first seen");
    /* A short buffer: the line cut, never past it. */
    char small[12];
    memset(small, 'x', sizeof small);
    len = pt_line(&p, small, 8);
    check(len == 7 && small[7] == 0 && small[8] == 'x', "pass times: a short buffer holds a cut line and its end");
    /* Past the room for samples: the later frames not kept, the frame count still right. */
    pt_clear(&p);
    for (int i = 0; i < PT_SAMPLES + 5; i++)
        pt_step(&p, "rcas", (float)i), pt_frame(&p);
    check(p.n[0] == PT_SAMPLES && p.frames == PT_SAMPLES + 5, "pass times: a stretch keeps its room's samples, counts all");
    /* Past the room for names: the step left out, the others kept. */
    pt_clear(&p);
    static char names[PT_NAMES + 1][8];
    for (int i = 0; i <= PT_NAMES; i++) {
        snprintf(names[i], sizeof names[i], "s%d", i);
        pt_step(&p, names[i], 1);
    }
    pt_frame(&p);
    check(p.names == PT_NAMES && pt_median(&p, PT_NAMES - 1) == 1, "pass times: names past the room left out");
}

static void test_pacer(void)
{
    Pacer p;
    /* A counter of 1000 ticks a second and 50 frames a second: a frame every 20 ticks. */
    pacer_start(&p, 1000, 50);
    check(pacer_wait(&p, 1000) == 0, "pacer: the first frame goes at once");
    check(pacer_wait(&p, 1005) == 15, "pacer: an early frame waits for its tick");
    check(pacer_wait(&p, 1043) == 0 && p.next == 1060, "pacer: a little late goes at once, the count kept");
    check(pacer_wait(&p, 1200) == 0 && p.next == 1220, "pacer: a long stall starts the count again");
    /* Frames drawn at once for a second: the pacer lets exactly 50 out. */
    pacer_start(&p, 1000, 50);
    int64_t now = 0, sent = 0;
    while (now < 1000) {
        now += pacer_wait(&p, now);
        sent++;
        now += 1;
    }
    check(sent >= 49 && sent <= 51, "pacer: 50 frames in a second");
    pacer_start(&p, 1000, 0);
    check(pacer_wait(&p, 5) == 0 && pacer_wait(&p, 6) == 0, "pacer: no clock never waits");
    /* The game's own rate on a real counter (10 MHz): 60 frames in a second of frames drawn at once. */
    pacer_start(&p, 10000000, GAME_FPS);
    now = 0;
    sent = 0;
    while (now < 10000000) {
        now += pacer_wait(&p, now);
        sent++;
        now += 1000;
    }
    check(sent == 60 || sent == 61, "pacer: 60 a second, as the game's logic runs");
}

static void test_keys(void)
{
    uint8_t keys[256];
    memset(keys, 0x80, sizeof keys);
    int waiting = hold_keys(keys, 1, 0);
    int all_up = 1;
    for (int i = 0; i < 256; i++)
        all_up &= keys[i] == 0;
    check(all_up && waiting, "keys: nothing is down for the game while the card is up");
    memset(keys, 0, sizeof keys);
    keys[0x0D] = 0x80;
    keys['A'] = 0x80;
    waiting = hold_keys(keys, 0, waiting);
    check(waiting && keys[0x0D] == 0 && keys['A'] == 0x80, "keys: the answer's Enter stays away until let go");
    memset(keys, 0, sizeof keys);
    keys[0x01] = 0x80;
    waiting = hold_keys(keys, 0, waiting);
    check(waiting && keys[0x01] == 0, "keys: the click that answered stays away until let go");
    memset(keys, 0, sizeof keys);
    waiting = hold_keys(keys, 0, waiting);
    keys[0x01] = 0x80;
    waiting = hold_keys(keys, 0, waiting);
    check(!waiting && keys[0x01] == 0x80, "keys: once let go, the game has its clicks back");
    keys[0x1B] = 0x80;
    hold_keys(keys, 0, 0);
    check(keys[0x1B] == 0, "keys: the game never sees Esc (its own would end it at once)");
}

static void test_card(void)
{
    Card c = {0, 0, 0, 0};
    card_open(&c, CARD_QUIT);
    int danger = 0;
    check(c.focus == 0 && !strcmp(card_label(&c, 0, &danger), "KEEP PLAYING") && !danger,
          "card: the question starts on Keep playing");
    card_label(&c, 1, &danger);
    check(danger && !strcmp(card_title(&c), "Quit the game?"), "card: the second answer quits");
    check(card_line(&c) == NULL, "card: no line on the game's menus (no song plays)");
    c.song = 1;
    check(!strcmp(card_line(&c), "This play will not be recorded."), "card: during a song its one line says what is lost");
    check(card_key(&c, 0x0D) == ACT_CLOSE && c.open == CARD_NONE, "card: Enter at once keeps playing");
    card_open(&c, CARD_QUIT);
    check(card_key(&c, 0x27) == ACT_REDRAW && c.focus == 1, "card: Right moves to Quit");
    check(card_key(&c, 0x28) == ACT_REDRAW && c.focus == 0, "card: the ring goes round");
    card_key(&c, 0x26);
    check(card_key(&c, 0x0D) == ACT_QUIT, "card: Enter on Quit quits");
    card_open(&c, CARD_MENU);
    check(card_title(&c) == NULL && card_line(&c) == NULL && !strcmp(card_label(&c, 0, NULL), "BACK TO THE GAME"),
          "card: the menu's rows, with no title or line");
    check(card_key(&c, 'A') == ACT_NONE && c.open == CARD_MENU, "card: other keys wait");
    check(card_key(&c, 0x1B) == ACT_CLOSE && c.open == CARD_NONE, "card: Esc closes");
    card_open(&c, CARD_MENU);
    check(card_count(&c) == 4 && !strcmp(card_label(&c, 1, NULL), "SHOW FPS") && !strcmp(card_state(&c, 1), "OFF") &&
              card_state(&c, 0) == NULL,
          "card: the menu has Show FPS, its state at its right");
    check(card_state(&c, 2) && !strcmp(card_state(&c, 2), "\xe2\x80\xba") && card_state(&c, 3) == NULL,
          "card: the menu's Sound shows a > at its right: it opens a panel");
    check(!strcmp(quit_words(0), "Quitting the game\xe2\x80\xa6") && !strcmp(quit_words(1), "게임을 끝내는 중\xe2\x80\xa6"),
          "card: the bar's words while the game ends, in both languages");
    check(card_choose(&c, 1) == ACT_FPS && c.fps && c.open == CARD_MENU && !strcmp(card_state(&c, 1), "ON"),
          "card: Show FPS turns the chip on and the menu stays");
    card_key(&c, 0x28);
    check(card_key(&c, 0x0D) == ACT_FPS && !c.fps, "card: Enter on Show FPS turns it off again");
    int danger2 = 0;
    card_label(&c, 3, &danger2);
    check(danger2 && card_choose(&c, 3) == ACT_QUIT, "card: the menu's Quit (its last row) quits");
    c.korean = 1;
    card_open(&c, CARD_QUIT);
    c.song = 1;
    check(!strcmp(card_label(&c, 1, NULL), "게임 끝내기") && !strcmp(card_title(&c), "게임을 끝낼까요?") &&
              !strcmp(card_line(&c), "진행 중인 플레이는 기록되지 않습니다."),
          "card: Korean words");
}

/* Whether two boxes overlap. */
static int overlap(Box a, Box b)
{
    return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

static void test_layout(void)
{
    check(fabsf(ui_unit(768) - 1.0f) < 0.001f && fabsf(ui_unit(1080) - 1.40625f) < 0.001f &&
              fabsf(ui_unit(2160) - 2.8125f) < 0.001f && fabsf(ui_unit(600) - 0.78125f) < 0.001f &&
              fabsf(ui_unit(576) - 0.75f) < 0.001f && fabsf(ui_unit(300) - 0.75f) < 0.001f,
          "layout: the game's own pixels to the area's, smaller with a small window down to three quarters");
    /* In the e2e's 960 x 576 window the bar is the game's own top band there (52 lines), no taller. */
    Card none = {0, 0, 0, 0};
    UiLayout small;
    ui_layout(&none, 960, 576, &small);
    check(small.bar.h <= 70.0f * 576.0f / 768.0f + 0.01f, "layout: in a small window the bar is the game's own band");
    /* Nothing of the layer in the middle half of the game, where the notes come, at every size and shape of window:
     * the bar, its chips, the menu, the question, a long toast, the wide chip. */
    static const int sizes[5][2] = {{1280, 768}, {1920, 1080}, {3840, 2160}, {1600, 1200}, {2560, 1080}};
    int clear = 1;
    for (int k = 0; k < 5; k++) {
        int w = sizes[k][0], h = sizes[k][1];
        Box middle = {w * 0.25f, h * 0.25f, w * 0.5f, h * 0.5f};
        for (int open = CARD_MENU; open <= CARD_SOUND; open++) {
            Card c = {0, 0, 0, 0};
            card_open(&c, open);
            UiLayout l;
            ui_layout(&c, w, h, &l);
            clear &= !overlap(l.bar, middle) && !overlap(l.panel, middle);
            for (int i = 0; i < CHIPS; i++)
                clear &= !overlap(l.chip[i], middle);
            for (int i = 0; i < l.count; i++)
                clear &= !overlap(l.rows[i], middle) && l.rows[i].x >= l.panel.x &&
                         l.rows[i].x + l.rows[i].w <= l.panel.x + l.panel.w + 0.01f &&
                         l.rows[i].y + l.rows[i].h <= l.panel.y + l.panel.h + 0.01f;
        }
        clear &= !overlap(toast_box(w, h, 0.35f * (float)w), middle) && !overlap(ui_mark_box(w, h, 1), middle);
        for (int corner = 0; corner < 4; corner++)
            clear &= !overlap(fps_box(w, h, corner), middle);
    }
    check(clear, "layout: nothing of the layer in the middle half of the game, at five sizes and shapes");
    Card q = {0, 0, 0, 0};
    card_open(&q, CARD_QUIT);
    UiLayout l;
    ui_layout(&q, 1920, 1080, &l);
    /* The bar covers the game's own top band (its 70 lines of 768) and the X sits at its right, the question under
     * the X with its right edge on the X's. */
    check(fabsf(l.bar.h - 70 * 1.40625f) < 0.01f &&
              fabsf(l.chip[CHIP_X].x + l.chip[CHIP_X].w - (1920 - 12 * 1.40625f)) < 0.01f &&
              l.chip[CHIP_MENU].x + l.chip[CHIP_MENU].w < l.chip[CHIP_MIN].x &&
              l.chip[CHIP_MIN].x + l.chip[CHIP_MIN].w < l.chip[CHIP_FULL].x &&
              l.chip[CHIP_FULL].x + l.chip[CHIP_FULL].w < l.chip[CHIP_X].x &&
              l.chip[CHIP_MIN].x - (l.chip[CHIP_MENU].x + l.chip[CHIP_MENU].w) >
                  l.chip[CHIP_X].x - (l.chip[CHIP_FULL].x + l.chip[CHIP_FULL].w),
          "layout: the bar over the game's top band; the menu's chip, then minimise, full screen and the X at its right");
    check(fabsf(l.panel.x + l.panel.w - (l.chip[CHIP_X].x + l.chip[CHIP_X].w)) < 0.01f &&
              fabsf(l.panel.y - l.bar.h) < 0.01f && l.rows[0].x < l.rows[1].x && l.tab.y == l.panel.y && l.line_y == 0,
          "layout: the question hangs from the bar's foot under the X, Keep playing left of Quit, its tab on its top "
          "edge, no line");
    float short_h = l.panel.h;
    q.song = 1;
    ui_layout(&q, 1920, 1080, &l);
    check(l.line_y > l.tab.y + l.tab.h && l.rows[0].y > l.line_y && l.panel.h > short_h,
          "layout: during a song the line sits under the tab and the answers under it");
    check(ui_hit(&l, l.chip[CHIP_X].x + 20, l.chip[CHIP_X].y + 10) == HIT_X &&
              ui_hit(&l, l.chip[CHIP_MENU].x + 20, l.chip[CHIP_MENU].y + 10) == HIT_MENU &&
              ui_hit(&l, l.chip[CHIP_MIN].x + 20, l.chip[CHIP_MIN].y + 10) == HIT_MIN &&
              ui_hit(&l, l.chip[CHIP_FULL].x + 20, l.chip[CHIP_FULL].y + 10) == HIT_FULL &&
              ui_hit(&l, l.rows[1].x + 3, l.rows[1].y + 3) == 1 && ui_hit(&l, l.panel.x + 2, l.panel.y + 2) == HIT_PANEL &&
              ui_hit(&l, 400, 20) == HIT_BAR && ui_hit(&l, 960, 540) == HIT_NONE &&
              ui_hit_chip(HIT_FULL) == CHIP_FULL && ui_hit_chip(HIT_BAR) == -1,
          "layout: each chip, answer, panel and the bar where it is drawn; the game elsewhere");
    card_open(&q, CARD_MENU);
    ui_layout(&q, 1920, 1080, &l);
    check(l.count == 4 && fabsf(l.panel.x - l.chip[CHIP_MENU].x) < 0.01f &&
              fabsf(l.panel.x + l.panel.w - (l.chip[CHIP_X].x + l.chip[CHIP_X].w)) < 0.01f &&
              fabsf(l.panel.y - l.bar.h) < 0.01f && l.rows[1].y > l.rows[0].y + l.rows[0].h,
          "layout: the menu hangs from the bar's foot under its chip and the chips beside it, its rows one under the "
          "other");
    /* Each row a finger's size at 1080 lines (44 pixels or more), and a press anywhere in the menu, its gaps and its
     * sides included, the nearest row's: none falls on the panel alone. */
    int finger = 1, nearest = 1;
    for (int i = 0; i < 4; i++)
        finger &= l.hit[i].h >= 44.0f && l.hit[i].w >= 44.0f;
    for (float y = l.panel.y + 0.5f; y < l.panel.y + l.panel.h; y += 1.0f)
        for (float x = l.panel.x + 0.5f; x < l.panel.x + l.panel.w; x += 7.0f) {
            int hit = ui_hit(&l, x, y);
            /* The nearest row by its plate's middle. */
            int want = 0;
            for (int i = 1; i < 4; i++)
                if (fabsf(y - (l.rows[i].y + l.rows[i].h / 2)) < fabsf(y - (l.rows[want].y + l.rows[want].h / 2)))
                    want = i;
            nearest &= hit == want;
        }
    check(finger, "layout: the menu's rows are 44 pixels or more at 1080 lines");
    check(nearest, "layout: a press in the menu's gaps or at its sides is the nearest row's");
    /* The chips and the question's answers a finger's size too: 40 pixels or more each way at 1080 lines. */
    int big = 1;
    for (int i = 0; i < CHIPS; i++)
        big &= l.chip[i].w >= 40.0f && l.chip[i].h >= 40.0f;
    card_open(&q, CARD_QUIT);
    ui_layout(&q, 1920, 1080, &l);
    for (int i = 0; i < 2; i++)
        big &= l.hit[i].w >= 40.0f && l.hit[i].h >= 40.0f;
    check(big, "layout: the chips and the question's answers are 40 pixels or more at 1080 lines");
    check(ui_at_top_edge(0, 1080) && ui_at_top_edge(2, 1080) && !ui_at_top_edge(4, 1080),
          "reveal: only the very top edge brings the bar (its two top lines of 768)");
    check(ui_swipe_down(2, 40, 1080) && !ui_swipe_down(2, 20, 1080) && !ui_swipe_down(30, 90, 1080),
          "reveal: a finger drawn down from the top edge, not a short one or one from lower down");
    /* The chip at the foot: one line on the line of the game's labels, below the notes (a note of the third lower row
     * has its centre on line 693 of 768 and the foot of its ring on line 748), beside the labels: left of FREE PLAY (x
     * 1131 to 1215, lines 743 to 752) at the right, after ID CARD, NET and PATCH (to x 193, lines 732 to 762) at the
     * left; across in the game's own pixels (a filled picture stretches them), at seven sizes and shapes, kept and
     * filled. At the top, 6 lines down and 12 in from its side. */
    static const int shapes[7][2] = {{1280, 768}, {1800, 1080}, {1920, 1080}, {2560, 1080}, {1920, 1152}, {1280, 1024},
                                     {3600, 2160}};
    int band = 1;
    for (int k = 0; k < 7; k++) {
        int w = shapes[k][0], h = shapes[k][1];
        float sx = (float)w / 1280.0f, sy = (float)h / 768.0f;
        Box br = fps_box(w, h, CORNER_BOTTOM_RIGHT), bl = fps_box(w, h, CORNER_BOTTOM_LEFT);
        Box free_play = {1131 * sx, 743 * sy, 84 * sx, 9 * sy}, badges = {7 * sx, 732 * sy, 186 * sx, 30 * sy};
        /* Under the notes, within the picture, its words' middle on FREE PLAY's (its rows 743 to 752 whole: their
         * middle on line 748) within a game line. */
        band &= br.y >= 741 * sy && br.y + br.h <= (float)h && bl.y >= 741 * sy && bl.y + bl.h <= (float)h &&
                fabsf(br.y + br.h / 2 - 748.0f * sy) <= 1.0f * sy;
        /* Beside the game's labels, never on them. */
        band &= !overlap(br, free_play) && br.x + br.w <= free_play.x - 7.9f * sx && !overlap(bl, badges) &&
                bl.x >= badges.x + badges.w + 7.9f * sx && br.x > bl.x + bl.w;
    }
    Box tl = fps_box(1920, 1080, CORNER_TOP_LEFT), tr = fps_box(1920, 1080, CORNER_TOP_RIGHT);
    check(band && fabsf(tl.y - 6 * 1.40625f) < 0.01f && fabsf(tr.x + tr.w - (1920 - 12 * 1.40625f)) < 0.01f &&
              tl.y + tl.h <= 69 * 1.40625f,
          "layout: the frame rate chip on the line of the game's labels below its notes, beside them, or in its top band");
    /* The handle: at the top centre, deeper lit, on the groove meter's chrome rim (the game's top 12 lines) whatever the
     * shape; resting near it counts, the game's top band elsewhere not. */
    Box m0 = ui_mark_box(1920, 1080, 0), m1 = ui_mark_box(1920, 1080, 1);
    check(m0.y == 0 && fabsf(m0.x + m0.w / 2 - 960) < 0.01f && m1.h > m0.h && m1.h <= 12 * 1.40625f + 0.01f &&
              ui_on_mark(960, 3, 1920, 1080) && ui_on_mark(960 + m1.w / 2 + 8, 5, 1920, 1080) &&
              !ui_on_mark(960, 40, 1920, 1080) && !ui_on_mark(700, 3, 1920, 1080),
          "layout: the handle at the top centre within the game's top 12 lines, near it counts as on it");
}

/* How long the bar stays, as OpenDMTQ's: 600 ms after the pointer, 4 s after a finger, 3 s by itself; a press on the
 * game takes it away. */
static void test_bar_clock(void)
{
    BarClock b;
    bar_clock_start(&b);
    check(!bar_clock_whole(&b, 1000), "bar clock: not shown at the start");
    bar_clock_rest(&b, 1000);
    check(bar_clock_whole(&b, 1599) && !bar_clock_whole(&b, 1600), "bar clock: whole 600 ms after a rest brought it");
    bar_clock_rest(&b, 1500);
    check(bar_clock_whole(&b, 2099) && !bar_clock_whole(&b, 2100), "bar clock: the pointer on it keeps it 600 ms more");
    bar_clock_touch(&b, 3000);
    bar_clock_rest(&b, 3100);
    check(b.by_touch && bar_clock_whole(&b, 6999) && !bar_clock_whole(&b, 7000),
          "bar clock: a finger's bar whole 4 s, the pointer it parks no longer");
    bar_clock_start(&b);
    bar_clock_reveal(&b, 10000);
    bar_clock_rest(&b, 10100);
    check(bar_clock_whole(&b, 12999) && !bar_clock_whole(&b, 13000), "bar clock: by itself whole 3 s");
    bar_clock_rest(&b, 12800);
    check(bar_clock_whole(&b, 13399) && !bar_clock_whole(&b, 13400), "bar clock: the pointer on it at the end keeps it");
    bar_clock_hide(&b);
    check(!bar_clock_whole(&b, 13000), "bar clock: a press on the game takes it away");
    /* A pointer left on the bar's band before it came by itself (the game's first screen, a switch) keeps it no
     * longer than its 3 s until the mouse moves. */
    bar_clock_start(&b);
    check(bar_clock_pointer_counts(&b), "bar clock: the pointer on it counts at the start");
    bar_clock_reveal(&b, 20000);
    check(!bar_clock_pointer_counts(&b), "bar clock: by itself, a pointer parked on it does not keep it");
    bar_clock_moved(&b);
    check(bar_clock_pointer_counts(&b), "bar clock: by itself, the pointer on it keeps it once moved");
    bar_clock_touch(&b, 30000);
    check(!bar_clock_pointer_counts(&b), "bar clock: a finger's parked pointer does not keep it");
    bar_clock_moved(&b);
    check(bar_clock_pointer_counts(&b) && !b.by_touch, "bar clock: a move of the mouse after a finger counts again");
    /* A slow game (the CPU's renderer on a busy machine: 6.4 to 10 frames a second, measured in a run where the bar went
     * from under a resting pointer 1.9 s after it came): the pointer resting on the bar keeps it whole at every frame
     * for six seconds, the pointer looked for by the clock (ten times a second, every frame when frames are slower). */
    static const double paces[3] = {100.0, 118.0, 155.0};
    int kept = 1;
    for (int k = 0; k < 3; k++) {
        bar_clock_start(&b);
        double last = -1e12, t = 50000;
        bar_clock_rest(&b, t);
        for (int f = 0; f < 60; f++) {
            /* Each frame a little late or early (a busy machine), never shorter than the pace's 80 %. */
            t += paces[k] * (f % 3 == 1 ? 1.2 : f % 3 == 2 ? 0.8 : 1.0);
            if (bar_look_due(&last, t))
                bar_clock_rest(&b, t);
            kept &= bar_clock_whole(&b, t);
        }
    }
    check(kept, "bar clock: a slow game keeps the bar whole under a resting pointer (the pointer looked for by the clock)");
}

/* The layer's slides (logic.h): the bar down out of the top edge in 220 ms slowing into place, up in 170 ms gathering
 * speed, a turn midway from where it is and in its share of the time, at once with Windows' animation effects off; and
 * what hangs from the bar's foot. */
static void test_slides(void)
{
    /* The paces: 0 at 0, 1 at 1, the way down quick first, the way up slow first; neither ever goes back. */
    int never_back = 1;
    float d0 = 0, u0 = 0;
    for (int i = 1; i <= 100; i++) {
        float d = slide_ease_down((float)i / 100.0f), up = slide_ease_up((float)i / 100.0f);
        never_back &= d >= d0 && up >= u0;
        d0 = d;
        u0 = up;
    }
    check(slide_ease_down(0) == 0 && slide_ease_down(1) == 1 && fabsf(slide_ease_down(0.5f) - 0.875f) < 1e-5f &&
              slide_ease_up(0) == 0 && slide_ease_up(1) == 1 && fabsf(slide_ease_up(0.5f) - 0.25f) < 1e-5f &&
              slide_ease_down(2) == 1 && slide_ease_up(-1) == 0 && never_back,
          "slides: down slows into place, up gathers speed, neither goes back");
    /* Down: out of sight at its start, 220 ms to its place, on its way until then. */
    Slide s;
    slide_rest(&s, 0);
    check(slide_at(&s, 1000) == 0 && !slide_moving(&s, 1000), "slides: at rest out of sight");
    slide_aim(&s, 1, 1000, 1);
    check(slide_at(&s, 1000) == 0 && fabsf(slide_at(&s, 1110) - 0.875f) < 1e-4f && slide_moving(&s, 1219) &&
              !slide_moving(&s, 1220) && slide_at(&s, 1220) == 1 && slide_at(&s, 5000) == 1,
          "slides: the way down takes 220 ms, slowing into place");
    /* Aimed again at where it is headed: its way goes on as it was. */
    slide_aim(&s, 1, 1100, 1);
    check(s.began == 1000 && fabsf(s.lasts - 220) < 1e-6, "slides: aimed again the same way, it keeps its pace");
    /* Up: 170 ms, slow at first. */
    slide_aim(&s, 0, 2000, 1);
    check(fabsf(slide_at(&s, 2085) - 0.75f) < 1e-4f && slide_moving(&s, 2169) && slide_at(&s, 2170) == 0,
          "slides: the way up takes 170 ms, gathering speed");
    /* A turn midway: down for 110 ms (at 0.875), then up from there, in 0.875 of the way up's time; no jump at the
     * turn, and back down again from where it is then. */
    slide_rest(&s, 0);
    slide_aim(&s, 1, 3000, 1);
    float before = slide_at(&s, 3110);
    slide_aim(&s, 0, 3110, 1);
    float after = slide_at(&s, 3110);
    check(fabsf(before - after) < 1e-5f && fabsf((float)s.lasts - 170.0f * 0.875f) < 1e-3f &&
              slide_at(&s, 3110 + 170.0 * 0.875) == 0,
          "slides: turned back midway, it sets out from where it is, in its share of the way's time");
    float mid = slide_at(&s, 3160);
    slide_aim(&s, 1, 3160, 1);
    check(fabsf(slide_at(&s, 3160) - mid) < 1e-5f && fabsf((float)s.lasts - 220.0f * (1.0f - mid)) < 1e-3f &&
              slide_at(&s, 3160 + 220.0 * (1.0 - mid)) == 1,
          "slides: turned back again, again from where it is");
    /* Windows' animation effects off: there at once, both ways. */
    slide_rest(&s, 0);
    slide_aim(&s, 1, 4000, 0);
    int down_at_once = slide_at(&s, 4000) == 1 && !slide_moving(&s, 4000);
    slide_aim(&s, 0, 4001, 0);
    check(down_at_once && slide_at(&s, 4001) == 0 && !slide_moving(&s, 4001),
          "slides: with Windows' animation effects off, at once both ways");
    /* The bar's foot: nothing in sight until its shadow's room has come out, then its rows, its whole height at 1. */
    float h = 98.4375f, shade = 8 * 1.40625f;
    check(slide_rows(0, h, shade) == 0 && slide_rows(shade / (h + shade) - 0.01f, h, shade) == 0 &&
              slide_rows(1, h, shade) == h && fabsf(slide_rows(0.5f, h, shade) - ((h + shade) / 2 - shade)) < 1e-3f,
          "slides: the bar's foot comes out of the top edge after its shadow, its whole height in place");
    /* The bar itself: whole above the top edge at 0, its shadow too; its top on the edge at 1. */
    check(slide_top(0, 0, h, shade) == -(h + shade) && slide_top(1, 0, h, shade) == 0,
          "slides: the bar slides out of the top edge by its height and its shadow's room");
    /* A panel under the bar's foot, wherever the bar is: wholly above the foot, its shadow too, at 0 (under the bar,
     * which is drawn over it), its top on the foot at 1. */
    float ph = 106 * 1.40625f;
    int under = 1;
    for (int k = 0; k <= 10; k++) {
        float rows = slide_rows((float)k / 10.0f, h, shade);
        under &= slide_top(0, rows, ph, shade) + ph + shade <= rows + 1e-3f &&
                 fabsf(slide_top(1, rows, ph, shade) - rows) < 1e-4f;
    }
    check(under, "slides: a panel out of sight under the bar's foot at 0, its top on the foot at 1, wherever the bar is");
}

/* Where the parts stand on screens of every shape: the menu and the question hang from the bar's foot in the chips'
 * row; the notice clear of the chips' row (so of either panel) and of the middle; the handle on the top 12 lines; a
 * press on a chip of a bar still on its way acts on that chip. */
static void test_places(void)
{
    /* The game's own 5:3, 16:9 kept (the picture 5:3 inside) or filled, 21:9 filled, 16:10 kept, 5:4 filled, 4K. */
    static const int sizes[7][2] = {{1280, 768}, {1800, 1080}, {1920, 1080}, {2560, 1080}, {1920, 1152}, {1280, 1024},
                                    {3600, 2160}};
    /* The widest note the layer shows (the safety net's: 52 letters at about 7.6 game pixels each, English). */
    int clear = 1, hung = 1, handle = 1;
    for (int k = 0; k < 7; k++) {
        int w = sizes[k][0], h = sizes[k][1];
        float u = ui_unit(h);
        Box note = toast_box(w, h, 400 * u);
        Box middle = {w * 0.25f, h * 0.25f, w * 0.5f, h * 0.5f};
        for (int open = CARD_MENU; open <= CARD_SOUND; open++) {
            Card c = {0, 0, 0, 0};
            card_open(&c, open);
            c.song = 1;
            UiLayout l;
            ui_layout(&c, w, h, &l);
            /* The chips' row, from the menu's chip's left edge to the X's right edge. */
            Box row = {l.chip[CHIP_MENU].x, 0, l.chip[CHIP_X].x + l.chip[CHIP_X].w - l.chip[CHIP_MENU].x, (float)h};
            /* The notice, hanging from the bar's foot (the bar down), clear of the panel and of the chips' row. */
            Box hanging = note;
            hanging.y = l.bar.h;
            clear &= !overlap(hanging, l.panel) && note.x + note.w <= row.x - 15.9f * u && note.x >= 11.9f * u &&
                     !overlap(note, middle);
            /* Each panel on the bar's foot, inside the chips' row's width or under the X; the question and the sound
             * panel above a quarter, the menu (its rows a finger's size) ending with its shadow by line 206 of 768. */
            float foot = open == CARD_MENU ? (70 + 128 + SLIDE_SHADE) * u : (float)h * 0.25f;
            hung &= fabsf(l.panel.y - l.bar.h) < 0.01f && l.panel.x + l.panel.w <= row.x + row.w + 0.01f &&
                    l.panel.y + l.panel.h + SLIDE_SHADE * u <= foot + 0.01f;
            if (open == CARD_MENU)
                hung &= fabsf(l.panel.x - row.x) < 0.01f;
        }
        Box m = ui_mark_box(w, h, 1);
        handle &= m.y == 0 && m.h <= 12 * u + 0.01f && fabsf(m.x + m.w / 2 - w / 2.0f) < 0.01f;
    }
    check(clear, "places: the notice clear of the menu, the question and the chips' row, and of the middle, at every shape");
    check(hung, "places: the menu, the question and the sound panel hang from the bar's foot within the chips' row, the "
                "question and the sound panel above a quarter, the menu by line 206");
    check(handle, "places: the handle at the top centre within the game's top 12 lines, at every shape");
    /* A press while the bar comes down: the X where it is drawn now, not where it will be. */
    Card c = {0, 0, 0, 0};
    UiLayout l;
    ui_layout(&c, 1920, 1080, &l);
    float dy = -20;
    float x = l.chip[CHIP_X].x + l.chip[CHIP_X].w / 2, y = l.chip[CHIP_X].y + 4 + dy;
    check(ui_hit_moved(&l, x, y, dy, 0) == HIT_X && ui_hit_moved(&l, x, l.bar.h + dy + 3, dy, 0) == HIT_NONE &&
              ui_hit_moved(&l, x, y - dy, 0, 0) == HIT_X,
          "places: a chip of a bar on its way is hit where it is drawn");
    /* A press on a chip's final place while the bar is still coming down (a slow game draws it there a frame or two
     * later) is that chip's; while it goes up it is the game's, as before. Where it is drawn now counts first. */
    float fy = l.chip[CHIP_MENU].y + l.chip[CHIP_MENU].h / 2, fx = l.chip[CHIP_MENU].x + l.chip[CHIP_MENU].w / 2;
    check(ui_hit_settling(&l, fx, fy, -60, 0, 1) == HIT_MENU && ui_hit_settling(&l, fx, fy, -60, 0, 0) == HIT_NONE &&
              ui_hit_settling(&l, x, y, dy, 0, 1) == HIT_X && ui_hit_settling(&l, 960, 540, -60, 0, 1) == HIT_NONE &&
              ui_hit_settling(&l, fx, -5, -60, 0, 1) == HIT_NONE,
          "places: a press on a chip's final place while the bar comes down is that chip's");
    /* Where a press the game takes was aimed: at a chip's final place (the log says so: a press is never lost
     * silently), or nothing of the bar's. */
    check(ui_press_aim(&l, fx, fy) == HIT_MENU && ui_press_aim(&l, x, l.chip[CHIP_X].y + 4) == HIT_X &&
              ui_press_aim(&l, 960, 540) == HIT_NONE && ui_press_aim(&l, 400, 20) == HIT_NONE,
          "places: a press the game takes is said by the chip whose place it was on");
    /* The question sliding out under the bar: the bar over it where they meet, its answers where they are drawn. */
    card_open(&c, CARD_QUIT);
    ui_layout(&c, 1920, 1080, &l);
    float pdy = -40;
    float ax = l.rows[0].x + 5, ay = l.rows[0].y + 5 + pdy;
    check(ui_hit_moved(&l, ax, ay, 0, pdy) == 0 && ui_hit_moved(&l, l.panel.x + 5, l.bar.h - 5, 0, pdy) == HIT_BAR &&
              ui_hit_moved(&l, ax, ay - pdy, 0, 0) == 0,
          "places: the bar lies over a panel coming out from under it; an answer is hit where it is drawn");
    /* A panel still mostly above the game's top edge (out of sight there, cut by the picture), the bar on its way:
     * nothing of the layer's above the edge, where a kept picture leaves the window's bar and its presses the game's. */
    float high = -(l.panel.h + 8 * l.u);
    check(ui_hit_moved(&l, l.panel.x + 5, -5, -60, high) == HIT_NONE &&
              ui_hit_moved(&l, l.panel.x + 5, -30, -60, high) == HIT_NONE &&
              ui_hit_moved(&l, l.chip[CHIP_X].x + 10, -2, -l.bar.h, 0) == HIT_NONE,
          "places: nothing of the layer is hit above the game's top edge");
}

/* When a rest at the top edge or on the mark may bring the bar: never while a button is held or within 1.5 s of a
 * press or release on the game, only after the pointer moved there and stayed. */
static void test_gate(void)
{
    RevealGate g;
    gate_start(&g);
    gate_move(&g, 1000, 1, 0);
    check(!gate_due(&g, 1100, 1) && gate_due(&g, 1160, 1) && !g.armed, "gate: a rest of 150 ms with the game quiet");
    gate_move(&g, 2000, 1, 0);
    check(!gate_due(&g, 2200, 0) && !g.armed, "gate: the pointer gone from the place takes the rest back");
    /* A click at the top of a song: the rest it moves to waits for the quiet, then comes if still there. */
    gate_press(&g, 3000, 1);
    gate_press(&g, 3080, 0);
    gate_move(&g, 3100, 1, 0);
    check(!gate_due(&g, 3300, 1) && !gate_due(&g, 4500, 1) && g.armed && gate_due(&g, 4600, 1),
          "gate: within 1.5 s of a press nothing, then the rest brings it");
    /* A press takes a waiting rest back: the pointer must move there again. */
    gate_move(&g, 5000, 1, 0);
    gate_press(&g, 5100, 1);
    gate_press(&g, 5150, 0);
    check(!g.armed && !gate_due(&g, 9000, 1), "gate: a press takes the rest back");
    /* Held: no rest, and no quiet for a finger's swipe. */
    gate_move(&g, 9000, 1, 1);
    gate_press(&g, 9100, 1);
    check(!g.armed && !gate_quiet(&g, 20000), "gate: a button held is never a rest, nor quiet");
    gate_press(&g, 9200, 0);
    check(!gate_quiet(&g, 10000) && gate_quiet(&g, 10700), "gate: quiet 1.5 s after the last release");
    /* A load as a song ends: a release, the pointer on the mark, then no frame for 1.4 s. The pause is neither quiet
     * nor rest: the quiet ripens 1.5 s of the game's running time after the release, never at the first frame after
     * it. */
    gate_start(&g);
    gate_press(&g, 20000, 1);
    gate_press(&g, 20050, 0);
    gate_move(&g, 20400, 1, 0);
    gate_stall(&g, 21900, 1400);
    check(!gate_due(&g, 21900, 1) && !gate_quiet(&g, 21900) && g.armed,
          "gate: a pause of the game's frames is no quiet");
    check(!gate_due(&g, 22900, 1) && gate_due(&g, 22960, 1), "gate: the quiet counts the game's running time");
    /* A press the game heard within the pause stays where it was; no press yet stays none. */
    gate_start(&g);
    gate_press(&g, 30600, 0);
    gate_stall(&g, 31000, 600);
    check(g.pressed_at == 30600, "gate: a press heard within the pause stays where it was");
    gate_start(&g);
    gate_move(&g, 40000, 1, 0);
    gate_stall(&g, 41000, 900);
    check(!gate_due(&g, 41040, 1) && gate_due(&g, 41060, 1), "gate: with no press yet, the rest counts running time");
}

/* The handle's press (#7 of the 0.4.0 list: a tap and a long press bring the bar, as a draw down does). */
/* A sine's peak after it has run a second through the mix (its first half second let pass: the filters settle). */
static double mixed_peak(const MixShape *m, double hz, int rate)
{
    static float x[48000 * 2];
    MixState st;
    memset(&st, 0, sizeof st);
    for (int i = 0; i < rate; i++)
        x[2 * i] = x[2 * i + 1] = (float)(0.1 * sin(2 * 3.14159265358979 * hz * i / rate));
    mix_run_float(m, &st, x, rate, 2);
    double peak = 0;
    for (int i = rate / 2; i < rate; i++)
        peak = fmax(peak, fabs(x[2 * i]));
    return peak / 0.1;
}

/* The sound's values (#11 of the 0.4.0 list): the shared file, the volumes' move and the equaliser. */
/* ---- the sound file's writer in the game (soundset.c), with what it calls of the rest of the DLL stood in for: its log
 * kept to look at, the volumes and the mix taking the values as they come. */
static char g_sound_log[8192];
void ingame_log(const char *fmt, ...)
{
    char line[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    if (strlen(g_sound_log) + strlen(line) + 2 < sizeof g_sound_log) {
        strcat(g_sound_log, line);
        strcat(g_sound_log, "\n");
    }
}
void sound_volumes_start(int music, int keys)
{
    (void)music;
    (void)keys;
}
void sound_volumes(int music, int keys)
{
    (void)music;
    (void)keys;
}
void mix_set(const SoundValues *v)
{
    (void)v;
}

/* The file's text, or "" (a test's own read, the file shared as any reader would). */
static void read_sound_file(const WCHAR *path, char *out, int room)
{
    out[0] = 0;
    FILE *f = _wfopen(path, L"rb");
    if (!f)
        return;
    size_t n = fread(out, 1, (size_t)room - 1, f);
    out[n] = 0;
    fclose(f);
}

/* Write a text to a file (the tests' own files). */
static void put_file(const WCHAR *path, const char *text)
{
    FILE *f = _wfopen(path, L"wb");
    if (f) {
        fputs(text, f);
        fclose(f);
    }
}

static void test_sound_file(void)
{
    WCHAR dir[MAX_PATH], path[MAX_PATH], lock_path[MAX_PATH];
    GetTempPathW(MAX_PATH, dir);
    wcscat(dir, L"odt3-sound-test");
    CreateDirectoryW(dir, NULL);
    _snwprintf(path, MAX_PATH, L"%ls\\sound.ini", dir);
    _snwprintf(lock_path, MAX_PATH, L"%ls\\sound.ini.lock", dir);
    SetFileAttributesW(path, FILE_ATTRIBUTE_NORMAL);
    DeleteFileW(path);
    SoundValues v;
    sound_values_default(&v);
    static char text[80 * 1024];
    DWORD error = 0;
    /* A write: only the changed line, the other lines kept, the file swapped in whole. */
    put_file(path, "# mine\nmaster_volume=100\nkey_volume=90\n");
    read_sound_file(path, text, sizeof text);
    v.v[SOUND_MASTER] = 70;
    check(soundset_write_file(path, text, &v, 1u << SOUND_MASTER, &error), "sound file: written");
    read_sound_file(path, text, sizeof text);
    check(!strcmp(text, "# mine\nmaster_volume=70\nkey_volume=90\n"), "sound file: its own line only");
    /* Read-only: the swap is refused (error 5) and the file is as it was. */
    SetFileAttributesW(path, FILE_ATTRIBUTE_READONLY);
    v.v[SOUND_MASTER] = 60;
    error = 0;
    check(!soundset_write_file(path, text, &v, 1u << SOUND_MASTER, &error) && error == ERROR_ACCESS_DENIED,
          "sound file: a read-only file refuses the write, with its error");
    SetFileAttributesW(path, FILE_ATTRIBUTE_NORMAL);
    /* The game's writer as it runs: started on the file, a change made while the file is read-only waits (kept, said
     * in the log once) and is written when the file can be written again; the review found it dropped. */
    SetEnvironmentVariableW(L"OPENDMT3_SOUND_FILE", path);
    SetEnvironmentVariableA("OPENDMT3_SOUND_VALUES", "master_volume=70;key_volume=90");
    soundset_start();
    SetFileAttributesW(path, FILE_ATTRIBUTE_READONLY);
    g_sound_log[0] = 0;
    soundset_change(SOUND_MASTER, 40);
    Sleep(1500);
    read_sound_file(path, text, sizeof text);
    check(strstr(text, "master_volume=70") && strstr(g_sound_log, "not written (error 5"),
          "sound file: a change the file refuses is kept, said in the log");
    SetFileAttributesW(path, FILE_ATTRIBUTE_NORMAL);
    Sleep(1500);
    read_sound_file(path, text, sizeof text);
    check(strstr(text, "master_volume=40") && strstr(g_sound_log, "written (1 value) after"),
          "sound file: the kept change is written when the file can be written again");
    /* The lock held by another writer past its wait: the change waits, and is written once the lock is let go. */
    HANDLE held = CreateFileW(lock_path, GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_ALWAYS,
                              FILE_ATTRIBUTE_TEMPORARY | FILE_FLAG_DELETE_ON_CLOSE, NULL);
    soundset_change(SOUND_KEYS, 30);
    Sleep(2500);
    read_sound_file(path, text, sizeof text);
    int waited = strstr(text, "key_volume=90") != NULL;
    CloseHandle(held);
    Sleep(1500);
    read_sound_file(path, text, sizeof text);
    check(held != INVALID_HANDLE_VALUE && waited && strstr(text, "key_volume=30"),
          "sound file: a change waits out a held lock, then is written");
    /* Another writer's value comes in; one of ours still waiting is never replaced by the file's. */
    SetFileAttributesW(path, FILE_ATTRIBUTE_READONLY);
    soundset_change(SOUND_EQ0 + 2, 5);
    Sleep(800);
    SetFileAttributesW(path, FILE_ATTRIBUTE_NORMAL);
    put_file(path, "# mine\nmaster_volume=40\nkey_volume=30\nmusic_volume=55\neq_1k=-7\n");
    Sleep(1500);
    soundset_frame();
    read_sound_file(path, text, sizeof text);
    check(soundset_values()->v[SOUND_MUSIC] == 55 && soundset_values()->v[SOUND_EQ0 + 2] == 5 &&
              strstr(text, "eq_1k=5") && strstr(text, "music_volume=55"),
          "sound file: the other writer's value taken, ours that waited written over theirs");
    /* The quit's last write: tried for a second when the file refuses, then done once it can. */
    SetFileAttributesW(path, FILE_ATTRIBUTE_READONLY);
    soundset_change(SOUND_MASTER, 20);
    Sleep(50);
    DWORD t0 = GetTickCount();
    int first = soundset_flush();
    DWORD took = GetTickCount() - t0;
    SetFileAttributesW(path, FILE_ATTRIBUTE_NORMAL);
    int second = soundset_flush();
    read_sound_file(path, text, sizeof text);
    check(!first && took < 2500 && second && strstr(text, "master_volume=20"),
          "sound file: the quit's last write tried a second, then written");
    /* A file longer than the old 4 KB read: read whole, its last line kept at the next write (it was cut before). */
    {
        static char longer[6200];
        strcpy(longer, "# a long note\n");
        while (strlen(longer) < 6000)
            strcat(longer, "# padding padding padding padding padding padding padding padding\n");
        strcat(longer, "master_volume=20\neq_12k=12\n");
        put_file(path, longer);
        Sleep(1200);
        soundset_change(SOUND_MASTER, 25);
        Sleep(1500);
        read_sound_file(path, text, sizeof text);
        size_t n = strlen(text);
        check(n > 6000 && strstr(text, "eq_12k=12\n") && strstr(text, "master_volume=25"),
              "sound file: a file over 4 KB read whole and kept whole");
    }
    /* Past 64 KB: not read, never written over (a cut would lose its end), said in the log. */
    {
        FILE *f = _wfopen(path, L"wb");
        for (int i = 0; i < 1200 && f; i++)
            fputs("# a very long note, line after line, past what the game reads ...........\n", f);
        if (f) {
            fputs("master_volume=25\n", f);
            fclose(f);
        }
        Sleep(1200);
        g_sound_log[0] = 0;
        soundset_change(SOUND_MASTER, 35);
        Sleep(1500);
        read_sound_file(path, text, sizeof text);
        check(strstr(g_sound_log, "longer than 64 KB") != NULL, "sound file: past 64 KB not written over, said");
        /* Back to a short file, so what waits is written and the run ends with nothing kept. */
        put_file(path, "master_volume=25\n");
        Sleep(1500);
    }
    SetFileAttributesW(path, FILE_ATTRIBUTE_NORMAL);
}

/* ---- the in-game log's file (logfile.c): kept open from its first line, each line written whole at once. */

/* One line through logfile_line, its words from `fmt` as ingame_log hands them on. */
static int log_line(LogFile *log, const WCHAR *path, unsigned long ms, const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    int ok = logfile_line(log, path, ms, fmt, ap);
    va_end(ap);
    return ok;
}

/* A file's bytes as text into `out` (room for `room`), read through a handle of the test's own while the writer keeps
 * its file open, as a test reading the log while the game runs does; the length, or -1 when it cannot be read. */
static long log_text(const WCHAR *path, char *out, long room)
{
    HANDLE h = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE)
        return -1;
    DWORD got = 0;
    BOOL ok = ReadFile(h, out, (DWORD)room - 1, &got, NULL);
    CloseHandle(h);
    if (!ok)
        return -1;
    out[got] = 0;
    return (long)got;
}

/* Another writer's bytes at the end of a file (a handle of the test's own, opened and closed for them). */
static void log_other(const WCHAR *path, const char *bytes)
{
    HANDLE h = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_ALWAYS,
                           FILE_ATTRIBUTE_NORMAL, NULL);
    DWORD put = 0;
    if (h != INVALID_HANDLE_VALUE) {
        WriteFile(h, bytes, (DWORD)strlen(bytes), &put, NULL);
        CloseHandle(h);
    }
}

static void test_logfile(void)
{
    WCHAR dir[MAX_PATH], path[MAX_PATH], got[16];
    static char text[64 * 1024];
    GetTempPathW(MAX_PATH, dir);
    wcscat(dir, L"odt3-log-test");
    CreateDirectoryW(dir, NULL);
    _snwprintf(path, MAX_PATH, L"%ls\\ingame.log", dir);
    DeleteFileW(path);
    /* The variable: not set (no log), set to nothing (the default file beside the DLL: Windows answers an empty value
     * as it answers none, so the default was never reached before), a path, one too long for the room. */
    SetEnvironmentVariableW(L"OPENDMT3_TEST_LOG", NULL);
    int unset = logfile_variable(L"OPENDMT3_TEST_LOG", got, 16) == LOG_UNSET;
    SetEnvironmentVariableW(L"OPENDMT3_TEST_LOG", L"");
    int empty = logfile_variable(L"OPENDMT3_TEST_LOG", got, 16) == LOG_DEFAULT && !got[0];
    SetEnvironmentVariableW(L"OPENDMT3_TEST_LOG", L"C:\\a.log");
    int named = logfile_variable(L"OPENDMT3_TEST_LOG", got, 16) == LOG_PATH && !wcscmp(got, L"C:\\a.log");
    SetEnvironmentVariableW(L"OPENDMT3_TEST_LOG", L"C:\\a folder too long\\ingame.log");
    int long_value = logfile_variable(L"OPENDMT3_TEST_LOG", got, 16) == LOG_UNSET;
    SetEnvironmentVariableW(L"OPENDMT3_TEST_LOG", NULL);
    check(unset && empty && named && long_value,
          "log: no variable no log, set to nothing the default file, a path, a value too long no path");
    /* Each line in the file as soon as it is written (read through another handle while the log keeps its own open),
     * after the ones before it: its time, a space, its words, "\r\n" as the C runtime's text mode wrote it. */
    LogFile log = {NULL};
    int first = log_line(&log, path, 12, "one %d", 1) && log_text(path, text, sizeof text) == 10 &&
                !strcmp(text, "12 one 1\r\n");
    HANDLE kept = log.h;
    int second = log_line(&log, path, 13, "two %s", "words") && log_text(path, text, sizeof text) == 24 &&
                 !strcmp(text, "12 one 1\r\n13 two words\r\n");
    check(first && second && kept && kept != INVALID_HANDLE_VALUE && log.h == kept,
          "log: each line in the file at once, after the ones before, through the one handle kept open");
    /* A line longer than the room the line is made in, whole; an end inside a line, as text mode wrote it. */
    static char words[5001];
    memset(words, 'x', 5000);
    words[5000] = 0;
    int long_ok = log_line(&log, path, 14, "%s.", words);
    int inner_ok = log_line(&log, path, 15, "a\nb");
    long n = log_text(path, text, sizeof text);
    const char *at = text + 24;
    int whole = n == 24 + 3 + 5001 + 2 + 9 && !strncmp(at, "14 ", 3) && strspn(at + 3, "x") == 5000 &&
                !strcmp(at + 3 + 5000, ".\r\n15 a\r\nb\r\n");
    check(long_ok && inner_ok && whole, "log: a long line whole, an end inside a line written as text mode did");
    logfile_close(&log);
    check(log.h == NULL, "log: let go");
    /* A file whose folder is not there: the line is lost and nothing is kept open; once the folder is there, the next
     * line opens the file (each line tries, as each line opened the file before). */
    WCHAR later_dir[MAX_PATH], later[MAX_PATH];
    _snwprintf(later_dir, MAX_PATH, L"%ls\\later", dir);
    _snwprintf(later, MAX_PATH, L"%ls\\ingame.log", later_dir);
    DeleteFileW(later);
    RemoveDirectoryW(later_dir);
    LogFile late = {NULL};
    int lost = !log_line(&late, later, 1, "lost") && late.h == INVALID_HANDLE_VALUE;
    CreateDirectoryW(later_dir, NULL);
    int found = log_line(&late, later, 2, "found") && log_text(later, text, sizeof text) == 9 &&
                !strcmp(text, "2 found\r\n");
    check(lost && found, "log: a line with no folder for its file is lost, the next opens the file once it is there");
    logfile_close(&late);
    DeleteFileW(later);
    RemoveDirectoryW(later_dir);
    /* Another writer's line between two of the log's (the file kept open meanwhile): the log's next line goes after it,
     * at the file's end as it is then, never over it from a place of its own. (Two writers at the very same moment are
     * a seek and a write apart under Wine, which can overlap, as two C runtime openings could before.) */
    DeleteFileW(path);
    LogFile own = {NULL};
    int a = log_line(&own, path, 1, "ours");
    log_other(path, "theirs\r\n");
    int b = log_line(&own, path, 2, "ours again");
    check(a && b && log_text(path, text, sizeof text) == 30 && !strcmp(text, "1 ours\r\ntheirs\r\n2 ours again\r\n"),
          "log: a line another writer added stays, the log's next goes after it");
    logfile_close(&own);
    DeleteFileW(path);
    RemoveDirectoryW(dir);
}

static void test_sound_panel(void)
{
    /* The menu's Sound opens the panel in its place; its eight columns under the X, each with its track, in the
     * panel; a press at a track's top is its highest, at its foot its lowest, a volume in 5 % steps; the keys move the
     * ringed value a step; Enter and Esc go back to the game; nothing in it quits. (Above a quarter: test_places.) */
    Card c = {0, 0, 0, 0};
    card_open(&c, CARD_MENU);
    check(card_count(&c) == 4 && !strcmp(card_label(&c, 2, NULL), "SOUND") && card_choose(&c, 2) == ACT_SOUND_OPEN &&
          c.open == CARD_SOUND && c.focus == 0 && card_count(&c) == 8, "sound panel: the menu's Sound opens it");
    static const int sizes[5][2] = {{1280, 768}, {1920, 1080}, {3840, 2160}, {1600, 1200}, {2560, 1080}};
    int inside_all = 1;
    for (int k = 0; k < 5; k++) {
        UiLayout l;
        ui_layout(&c, sizes[k][0], sizes[k][1], &l);
        inside_all &= l.panel.x + l.panel.w <= (float)sizes[k][0];
        for (int i = 0; i < 8; i++)
            inside_all &= l.track[i].x >= l.rows[i].x && l.track[i].y >= l.rows[i].y &&
                          l.track[i].y + l.track[i].h <= l.rows[i].y + l.rows[i].h + 0.01f &&
                          l.rows[i].x + l.rows[i].w <= l.panel.x + l.panel.w + 0.01f &&
                          l.rows[i].y + l.rows[i].h <= l.panel.y + l.panel.h + 0.01f;
    }
    check(inside_all, "sound panel: its columns and tracks in the panel, at five sizes and shapes");
    UiLayout l;
    ui_layout(&c, 1920, 1080, &l);
    Box t = l.track[0], e = l.track[SOUND_EQ0 + 2];
    check(ui_sound_value_at(&l, 0, t.y) == 100 && ui_sound_value_at(&l, 0, t.y + t.h) == 0 &&
          ui_sound_value_at(&l, 0, t.y - 50) == 100 && ui_sound_value_at(&l, 0, t.y + t.h / 2) == 50 &&
          ui_sound_value_at(&l, 0, t.y + t.h * 0.37f) % 5 == 0, "sound panel: a volume's place on its track");
    check(ui_sound_value_at(&l, SOUND_EQ0 + 2, e.y + e.h / 2) == 0 && ui_sound_value_at(&l, SOUND_EQ0 + 2, e.y) == 12 &&
          fabsf(ui_sound_y(&l, SOUND_EQ0 + 2, 0) - (e.y + e.h / 2)) < 0.01f, "sound panel: a band flat at its middle");
    check(ui_hit(&l, l.rows[3].x + 2, l.rows[3].y + 2) == 3, "sound panel: a press on a column is that column's");
    /* Only the track (the knob's half over its ends) moves a value; the value over it and the name under it only
     * choose the column (a tap on MUSIC never mutes it). */
    int zones = 1;
    for (int i = 0; i < 8; i++) {
        Box tr = l.track[i], col = l.rows[i];
        zones &= ui_sound_zone(&l, i, tr.y + tr.h / 2) == SOUND_ZONE_TRACK &&
                 ui_sound_zone(&l, i, tr.y - 3 * l.u) == SOUND_ZONE_TRACK &&
                 ui_sound_zone(&l, i, tr.y + tr.h + 3 * l.u) == SOUND_ZONE_TRACK &&
                 ui_sound_zone(&l, i, l.sound_value_y) == SOUND_ZONE_CHOOSE && ui_sound_zone(&l, i, l.sound_name_y) == SOUND_ZONE_CHOOSE &&
                 ui_sound_zone(&l, i, col.y + 1) == SOUND_ZONE_CHOOSE &&
                 ui_sound_zone(&l, i, col.y + col.h - 1) == SOUND_ZONE_CHOOSE;
    }
    check(zones, "sound panel: only the track moves a value; its value and name choose the column");
    /* A finger's size at 1080 lines: each column's track 40 pixels or more across and down, and the way back too. */
    int touch = 1;
    for (int i = 0; i < 8; i++)
        touch &= l.hit[i].w >= 40.0f && l.track[i].h + 2 * 4 * l.u >= 40.0f;
    check(touch && l.back.w >= 40.0f && l.back.h >= 40.0f, "sound panel: its targets are 40 pixels or more at 1080 lines");
    /* A tap above the knob a step up, below a step down, on it nothing; a drag moves the value by the drawn length
     * from what it was (no jump where the finger landed), in the column's steps, within its range. */
    float k60 = ui_sound_y(&l, 0, 60);
    check(ui_sound_tap(&l, 0, 60, k60 - 8 * l.u) == 1 && ui_sound_tap(&l, 0, 60, k60 + 8 * l.u) == -1 &&
              ui_sound_tap(&l, 0, 60, k60 + 1) == 0 && ui_sound_tap(&l, SOUND_EQ0, 0, t.y) == 1,
          "sound panel: a tap above the knob is a step up, below a step down, on it nothing");
    check(ui_sound_drag(&l, 0, 60, k60, k60) == 60 && ui_sound_drag(&l, 0, 60, k60 + 20, k60 + 20) == 60 &&
              ui_sound_drag(&l, 0, 60, k60, k60 - t.h / 2) == 100 && ui_sound_drag(&l, 0, 60, k60, k60 + t.h / 4) == 35 &&
              ui_sound_drag(&l, 0, 60, k60, k60 + t.h * 2) == 0 && ui_sound_drag(&l, SOUND_EQ0, 0, 300, 300 - e.h / 24) == 1,
          "sound panel: a drag moves the value by its length from where it was, in steps, within the range");
    check(!ui_sound_dragging(&l, 300, 300 + 5 * l.u) && ui_sound_dragging(&l, 300, 300 - 7 * l.u),
          "sound panel: a finger's tap is no drag until drawn 6 game pixels");
    /* The wheel: a notch (120) a step; a touchpad's small pieces add up to one first, a turn back takes them back. */
    int rest = 0, steps = 0;
    for (int k = 0; k < 4; k++)
        steps += wheel_notches(&rest, 30);
    int one = steps;
    steps += wheel_notches(&rest, 50) + wheel_notches(&rest, -50);
    check(one == 1 && steps == 1 && rest == 0 && wheel_notches(&rest, 240) == 2 && wheel_notches(&rest, -130) == -1 &&
              rest == -10,
          "sound panel: the wheel steps once a whole notch, a touchpad's pieces added up");
    /* The second press of a double-click on the menu's Sound, landing on the panel that took the menu's place, changes
     * nothing: within Windows' double-click time and rectangle of the press that opened it. */
    check(ui_repeat_press(150, 1, -2, 500, 4, 4) && !ui_repeat_press(650, 1, 1, 500, 4, 4) &&
              !ui_repeat_press(150, 6, 0, 500, 4, 4) && !ui_repeat_press(-1, 0, 0, 500, 4, 4),
          "sound panel: the second press of a double-click on Sound is kept from it");
    /* The way back: its title tab (and the room under it) and Esc go back to the menu, its ring on Sound. */
    check(ui_hit(&l, l.tab.x + l.tab.w / 2, l.tab.y + l.tab.h / 2) == HIT_BACK, "sound panel: its title tab is the way back");
    /* The knob clear of the value over the track and of the name under it, at either end; the keys' ring inside
     * its column, clear of every name: measured on Pretendard Bold at 11 game pixels, MASTER 44.9 wide and 250 20.9
     * (the widest of each kind), Korean's 23.8 at 1.25 times, their capitals 8 tall (Korean's 10). */
    float knob = 4 * l.u, cap = 4 * l.u, kcap = 5 * l.u, ring = 2 * l.u, gap = 2 * l.u;
    int clear = 1;
    for (int i = 0; i < 8; i++) {
        Box col = l.rows[i], tr = l.track[i];
        float widest = i < SOUND_EQ0 ? 44.9f * l.u : 20.9f * l.u;
        clear &= tr.y - knob >= l.sound_value_y + cap + gap - 0.01f && tr.y + tr.h + knob <= l.sound_name_y - kcap - gap + 0.01f &&
                 l.sound_value_y - cap >= col.y + ring + gap - 0.01f && l.sound_name_y + kcap <= col.y + col.h - ring - gap + 0.01f &&
                 (col.w - widest) / 2 >= ring + gap - 0.01f;
    }
    check(clear, "sound panel: the knob clear of the value and the name at both ends, every name inside its ring");
    c.sound[SOUND_EQ0] = 3;
    c.sound[SOUND_EQ0 + 1] = -2;
    c.sound[SOUND_MUSIC] = 80;
    int danger = 1;
    check(!strcmp(card_state(&c, SOUND_EQ0), "+3") && !strcmp(card_state(&c, SOUND_EQ0 + 1), "-2") &&
          !strcmp(card_state(&c, SOUND_MUSIC), "80") && card_label(&c, 7, &danger) && !danger,
          "sound panel: its values as written, nothing in it quits");
    check(card_key(&c, 0x27) == ACT_REDRAW && c.focus == 1 && card_key(&c, 0x26) == ACT_SOUND && c.step == 1 &&
          card_key(&c, 0x28) == ACT_SOUND && c.step == -1 && sound_step(1) == 5 && sound_step(SOUND_EQ0) == 1,
          "sound panel: Right goes along, Up and Down a step");
    check(card_choose(&c, 4) == ACT_NONE && c.open == CARD_SOUND && card_key(&c, 0x0D) == ACT_CLOSE &&
          c.open == CARD_NONE, "sound panel: a column stays, Enter goes back to the game");
    card_open(&c, CARD_MENU);
    card_choose(&c, 2);
    check(c.open == CARD_SOUND && card_key(&c, 0x1B) == ACT_SOUND_BACK && c.open == CARD_MENU && c.focus == 2,
          "sound panel: Esc goes back to the menu, its ring on Sound");
    check(!strcmp(card_label(&c, 0, NULL), "BACK TO THE GAME") && (card_open(&c, CARD_SOUND), 1) &&
              !strcmp(card_label(&c, 0, NULL), "MASTER") && !strcmp(card_label(&c, 1, NULL), "MUSIC") &&
              !strcmp(card_label(&c, 2, NULL), "KEYS"),
          "sound panel: the volumes in the launcher's Sound page's words");
}

/* Back into a song after a panel held it: 3, 2, 1 within about 1.5 s, in the middle of the game area. */
static void test_resume(void)
{
    check(resume_digit(0) == 3 && resume_digit(499) == 3 && resume_digit(500) == 2 && resume_digit(999) == 2 &&
              resume_digit(1000) == 1 && resume_digit(1499) == 1 && resume_digit(1500) == 0 && resume_digit(5000) == 0 &&
              RESUME_MS <= 1500.0,
          "resume: 3, 2, 1, half a second each, then the song goes on");
    static const int sizes[4][2] = {{1280, 768}, {1920, 1080}, {3840, 2160}, {960, 576}};
    int middle = 1;
    for (int k = 0; k < 4; k++) {
        Box b = resume_box(sizes[k][0], sizes[k][1]);
        middle &= fabsf(b.x + b.w / 2 - sizes[k][0] / 2.0f) < 0.5f && fabsf(b.y + b.h / 2 - sizes[k][1] / 2.0f) < 0.5f &&
                  b.y > 70 * ui_unit(sizes[k][1]) && b.w > 0;
    }
    check(middle, "resume: its popup in the middle of the game, under the bar's band, at four sizes");
}

/* The shared table of sound.ini lines (tests/fixtures/sound_lines.txt, copied beside this program by test.sh; the
 * launcher's test reads the same file): each line read by the game's rule as the table says. Returns the lines checked,
 * and puts the first line read otherwise in `wrong`. */
static int sound_table(char *wrong, int room)
{
    char path[MAX_PATH], *slash;
    GetModuleFileNameA(NULL, path, sizeof path);
    slash = strrchr(path, '\\');
    if (!slash)
        return 0;
    strcpy(slash + 1, "sound_lines.txt");
    FILE *f = fopen(path, "rb");
    if (!f)
        return 0;
    char raw[512];
    int checked = 0;
    wrong[0] = 0;
    while (fgets(raw, sizeof raw, f)) {
        raw[strcspn(raw, "\n")] = 0;
        char *tab = strrchr(raw, '\t');
        if (raw[0] == '#' || !tab)
            continue;
        *tab = 0;
        /* The line as the file holds it: \t a tab, \r a carriage return, \B a byte order mark. */
        char line[512];
        int n = 0;
        for (char *c = raw; *c && n < (int)sizeof line - 4; c++) {
            if (c[0] == '\\' && c[1] == 't')
                line[n++] = '\t', c++;
            else if (c[0] == '\\' && c[1] == 'r')
                line[n++] = '\r', c++;
            else if (c[0] == '\\' && c[1] == 'B')
                line[n++] = (char)0xEF, line[n++] = (char)0xBB, line[n++] = (char)0xBF, c++;
            else
                line[n++] = *c;
        }
        line[n] = 0;
        SoundValues v;
        sound_values_default(&v);
        /* Every value set to a mark first, so "read" shows as a change from it. */
        for (int k = 0; k < SOUND_VALUES; k++)
            v.v[k] = 77;
        unsigned named = sound_values_parse(line, &v, NULL, NULL);
        char got[16] = "-";
        for (int k = 0; k < SOUND_VALUES; k++)
            if (named & (1u << k))
                snprintf(got, sizeof got, "%d", v.v[k]);
        if (strcmp(got, tab + 1) && !wrong[0])
            snprintf(wrong, (size_t)room, "%s -> %s, the table says %s", raw, got, tab + 1);
        checked++;
    }
    fclose(f);
    return checked;
}

static void test_sound_values(void)
{
    SoundValues s;
    sound_values_default(&s);
    check(s.v[SOUND_MASTER] == 100 && s.v[SOUND_KEYS] == 100 && s.v[SOUND_EQ0 + 2] == 0, "sound: 100 % and flat");
    /* Read: known lines, spaces and \r allowed; a bad value line left as if absent and counted; other lines left. */
    int refused = 0;
    const char *first = NULL;
    unsigned named = sound_values_parse("# a note\nmaster_volume = 80\r\nmusic_volume=101\neq_1k=-3\nother=5\n"
                                        "key_volume=0x20\n", &s, &refused, &first);
    check(named == ((1u << SOUND_MASTER) | (1u << (SOUND_EQ0 + 2))) && s.v[SOUND_MASTER] == 80 &&
              s.v[SOUND_MUSIC] == 100 && s.v[SOUND_KEYS] == 100 && s.v[SOUND_EQ0 + 2] == -3 && refused == 2 && first &&
              !strncmp(first, "music_volume=101", 16),
          "sound: the file's lines read, bad ones left and counted");
    /* The one rule, line by line, from the table both readers' tests read (the launcher's too). */
    char wrong[600];
    int lines = sound_table(wrong, sizeof wrong);
    check(lines >= 20 && !wrong[0], "sound: every line of the shared table read as it says");
    if (wrong[0])
        printf("     %s\n", wrong);
    /* Written: only the changed value's line, every other line (another writer's, a bad one, a comment) kept, a
     * missing one added, a byte order mark at the start dropped. */
    char out[512];
    s.v[SOUND_KEYS] = 40;
    s.v[SOUND_MASTER] = 10;
    int n = sound_values_merge("\xEF\xBB\xBF# a note\nmaster_volume=55\r\neq_1k=1_0\nkey_volume=90\nkey_volume=91\n",
                               &s, (1u << SOUND_KEYS) | (1u << (SOUND_EQ0 + 4)), out, sizeof out);
    check(n > 0 && !strcmp(out, "# a note\nmaster_volume=55\neq_1k=1_0\nkey_volume=40\neq_12k=0\n"),
          "sound: a write changes its own lines only, the byte order mark dropped");
    n = sound_values_merge("\xEF\xBB\xBFmaster_volume=55\n", &s, 1u << SOUND_MASTER, out, sizeof out);
    check(n > 0 && !strcmp(out, "master_volume=10\n"), "sound: the first line after a byte order mark is a value's too");
    check(sound_values_merge(NULL, &s, 1u << SOUND_MUSIC, out, sizeof out) > 0 && !strcmp(out, "music_volume=100\n"),
          "sound: the first write makes the file");
    check(sound_values_merge("master_volume=55\n", &s, 1u << SOUND_MUSIC, out, 10) == -1, "sound: no room, no file");
    /* The game's own volume curve, as measured at the last stage (the review's L7: the tutorial's music at setting.ini's
     * bgm_volume 96, 64 and 32 came out 4.88, 11.96 and 24.04 dB under 127, within 0.1 dB of 40 log10(value / 127),
     * twice an amplitude's): the percent's value in setting.ini, and its gain. */
    check(game_volume_value(100) == 127 && game_volume_value(50) == 64 && game_volume_value(75) == 95 &&
              game_volume_value(0) == 1 && game_volume_value(1) == 1,
          "sound: a percent as setting.ini's value (never 0)");
    check(fabs(game_curve_db(127)) < 0.001 && fabs(game_curve_db(64) + 11.91) < 0.01 && fabs(game_curve_db(32) + 23.95) < 0.01,
          "sound: the game's curve, 40 log10(value / 127)");
    /* The song's music moved by the game's curve, from the value it started at: 50 % to 100 % takes the game's -11.91 dB
     * off (it was 6.02 by an amplitude's), 100 % to 50 % puts it on, the same value no move, 0 % silent, never louder
     * than DirectSound's 0. */
    check(labs(volume_moved(-1191, 50, 100)) <= 1 && labs(volume_moved(0, 100, 50) + 1191) <= 1 &&
              volume_moved(-1500, 60, 60) == -1500 && volume_moved(-300, 50, 0) == -10000 &&
              volume_moved(-300, 25, 100) == 0,
          "sound: the song's music moved by the game's own curve");
    /* The key sounds: the game never applies setting.ini's sfx_volume (its key sounds' own volumes, its writes and the
     * mix were the same at 127 and 32), so their volume is openDMT3's alone, by the same curve from 100 % whatever the
     * game started at; the menus' loops follow neither (the game's bgm_volume leaves them as they are). */
    check(labs(volume_for_kind(-401, VOLUME_KEYS, 50, 50) - (-401 - 1191)) <= 1 &&
              volume_for_kind(-401, VOLUME_KEYS, 100, 100) == -401 && volume_for_kind(-401, VOLUME_KEYS, 30, 0) == -10000,
          "sound: the key sounds' volume is openDMT3's own, from 100 %");
    check(volume_for_kind(0, VOLUME_MENU, 100, 25) == 0 && labs(volume_for_kind(-1191, VOLUME_SONG, 50, 100)) <= 1,
          "sound: the menus' loops never moved, the song's music by its value");
    /* Which volume a buffer follows, and when its volume is set again at its play: a loop whose volume the game set
     * before its first play (then taken for a key sound) is set again as a loop's, even with nothing moved. */
    check(volume_kind(1, 100, 176400) == VOLUME_MENU && volume_kind(0, 1764000, 176400) == VOLUME_SONG &&
              volume_kind(0, 100, 176400) == VOLUME_KEYS,
          "sound: a loop is the menus', a buffer of 10 s and more the song's music, the rest the key sounds'");
    check(volume_reapply(2, 0, 0) && !volume_reapply(1, 0, 0) && volume_reapply(1, 0, 1) && !volume_reapply(0, 1, 0),
          "sound: a loop set as a key sound before its play is set again at it");
    /* The mix: off at 100 % and flat (nothing touched); the master as an amplitude. */
    MixShape m;
    sound_values_default(&s);
    mix_shape(&m, &s, 48000);
    check(!m.on, "mix: nothing to do at 100 % and flat");
    s.v[SOUND_MASTER] = 50;
    mix_shape(&m, &s, 48000);
    check(m.on && fabs(mixed_peak(&m, 1000, 48000) - 0.5) < 0.01, "mix: the master at 50 % halves the amplitude");
    /* A band raised: its frequency over the others by its gain, the preamp taking the curve's top off, so the raised
     * band stays where it was and a far one goes down by it. */
    sound_values_default(&s);
    s.v[SOUND_EQ0 + 2] = 6;
    mix_shape(&m, &s, 48000);
    double at = mixed_peak(&m, 1000, 48000), far = mixed_peak(&m, 100, 48000);
    check(fabs(at - 1.0) < 0.03 && fabs(far - 0.501) < 0.04 && fabs(m.preamp_db + 6.0f) < 0.1f,
          "mix: +6 dB at 1 kHz, 6 dB over 100 Hz, with the preamp taking 6 dB off");
    /* Every band at +12: neighbouring peaks add up to +14 dB between them; the preamp takes all of it off, so the mix
     * is never louder than it was (the review's 0.9 sine at 1 kHz came out at 4.6 before). */
    sound_values_default(&s);
    for (int b = 0; b < EQ_BANDS; b++)
        s.v[SOUND_EQ0 + b] = 12;
    mix_shape(&m, &s, 48000);
    double worst = 0;
    for (double hz = 30; hz < 18000; hz *= 1.12)
        worst = fmax(worst, mixed_peak(&m, hz, 48000));
    check(m.preamp_db < -13.5f && worst <= 1.02, "mix: every band at +12 dB never louder than the mix was");
    /* The shelves: the low one raises the bass over the top, the high one lowers the top. */
    sound_values_default(&s);
    s.v[SOUND_EQ0] = 12;
    s.v[SOUND_EQ0 + 4] = -12;
    mix_shape(&m, &s, 48000);
    check(mixed_peak(&m, 25, 48000) / mixed_peak(&m, 1000, 48000) > 3.5 && mixed_peak(&m, 20000, 48000) < 0.1,
          "mix: the low shelf raises the bass, the high shelf lowers the top");
    /* Full scale held: 16 bits never wrap, a float never passes 1.0 (a sound already at full scale and a boost). */
    int16_t loud[4] = {30000, -30000, 100, -100};
    MixState st;
    memset(&st, 0, sizeof st);
    sound_values_default(&s);
    s.v[SOUND_EQ0 + 2] = 12;
    mix_shape(&m, &s, 48000);
    mix_run_s16(&m, &st, loud, 2, 2);
    check(loud[0] <= 32767 && loud[1] >= -32768, "mix: 16 bits held at full scale, not wrapped");
    static float big[4800 * 2];
    for (int i = 0; i < 4800; i++)
        big[2 * i] = big[2 * i + 1] = (float)(1.0 * sin(2 * 3.14159265358979 * 1000 * i / 48000.0));
    memset(&st, 0, sizeof st);
    s.v[SOUND_MASTER] = 100;
    mix_shape(&m, &s, 48000);
    mix_run_float(&m, &st, big, 4800, 2);
    float over = 0;
    for (int i = 0; i < 4800 * 2; i++)
        over = fmaxf(over, fabsf(big[i]));
    check(over <= 1.0f, "mix: a float never past full scale");
    /* One NaN does not silence the stream for good: the state starts again after its buffer (it stayed NaN before). */
    memset(&st, 0, sizeof st);
    float buf[480 * 2];
    for (int i = 0; i < 480 * 2; i++)
        buf[i] = 0.1f;
    buf[10] = NAN;
    mix_run_float(&m, &st, buf, 480, 2);
    for (int k = 0; k < 10; k++) {
        for (int i = 0; i < 480 * 2; i++)
            buf[i] = 0.1f;
        mix_run_float(&m, &st, buf, 480, 2);
    }
    check(isfinite(buf[0]) && isfinite(buf[479]) && fabsf(buf[479]) > 0.01f, "mix: a NaN does not poison the stream");
    /* In silence the state goes to 0, never to denormal numbers. */
    memset(&st, 0, sizeof st);
    for (int i = 0; i < 480 * 2; i++)
        buf[i] = 0.1f;
    mix_run_float(&m, &st, buf, 480, 2);
    for (int k = 0; k < 400; k++) {
        memset(buf, 0, sizeof buf);
        mix_run_float(&m, &st, buf, 480, 2);
    }
    int denormal = 0;
    for (int b = 0; b < EQ_BANDS; b++)
        for (int c = 0; c < MIX_CHANNELS; c++)
            denormal |= (st.z1[b][c] != 0 && fabsf(st.z1[b][c]) < 1.2e-38f) || (st.z2[b][c] != 0 && fabsf(st.z2[b][c]) < 1.2e-38f);
    check(!denormal, "mix: no denormal numbers left in the state in silence");
    /* The bands at their places: a band at or above half the rate is left off and said (12 kHz at 22050 Hz), and the
     * mask of the bands running tells a change of them (the state starts again then: mix.c). */
    sound_values_default(&s);
    s.v[SOUND_EQ0 + 1] = 3;
    s.v[SOUND_EQ0 + 4] = 3;
    mix_shape(&m, &s, 22050);
    check(m.bands == 1 && m.mask == (1u << 1) && m.dropped == (1u << 4), "mix: 12 kHz left off at 22050 Hz, and said");
    mix_shape(&m, &s, 48000);
    check(m.bands == 2 && m.mask == ((1u << 1) | (1u << 4)) && !m.dropped, "mix: both at 48000 Hz");
}

/* A screen's rates (#9 of the 0.4.0 list): what motion clarity is offered from, and what is said of the screen. */
static void test_refresh_advice(void)
{
    check(refresh_advice(144, 144, 144) == REFRESH_AS_IS, "refresh: a screen at its highest rate");
    check(refresh_advice(60, 240, 60) == REFRESH_SET_LOWER, "refresh: a 240 Hz screen set to 60 Hz");
    check(refresh_advice(60, 120, 120) == REFRESH_DYNAMIC, "refresh: dynamic refresh: 60 given, 120 on the cable");
    check(refresh_advice(119, 120, 120) == REFRESH_AS_IS && refresh_advice(239, 240, 0) == REFRESH_AS_IS,
          "refresh: 119.88 Hz given as 119 is its highest");
    check(refresh_advice(0, 240, 240) == REFRESH_AS_IS, "refresh: nothing known, nothing said");
    check(refresh_offered(60, 180) == 180 && refresh_offered(240, 0) == 240 && refresh_offered(0, 0) == 0,
          "refresh: offered from the highest at the screen's size");
}

static void test_mark_press(void)
{
    MarkPress m;
    /* A 1080-line area: a game line is 1.40625 pixels. */
    const int h = 1080;
    /* Not the overlay's: off the handle, within the game's quiet, or while a song plays (the finger is the game's). */
    check(!mark_press_begin(&m, 0, 0, 1, 0, 5), "handle: a press beside it is the game's");
    check(!mark_press_begin(&m, 0, 1, 0, 0, 5), "handle: a press soon after play is the game's");
    check(!mark_press_begin(&m, 0, 1, 1, 1, 5), "handle: in a song a press on it is the game's");
    check(!mark_press_due(&m, 10000) && !mark_press_end(&m, 1), "handle: a press of the game's brings nothing");
    /* A tap: let go on it before the hold. */
    check(mark_press_begin(&m, 1000, 1, 1, 0, 5), "handle: a press on it after the quiet is the overlay's");
    check(!mark_press_due(&m, 1120) && mark_press_end(&m, 1) && !m.on, "handle: a tap brings the bar");
    /* A long press: 500 ms on it, once; its release then brings nothing more. */
    mark_press_begin(&m, 2000, 1, 1, 0, 5);
    check(!mark_press_due(&m, 2499) && mark_press_due(&m, 2500) && !mark_press_due(&m, 2600),
          "handle: held 500 ms it brings the bar, once");
    check(!mark_press_end(&m, 1), "handle: let go after its hold brought the bar, nothing more");
    /* Slid off: neither its time nor its release (even back on it) brings the bar. */
    mark_press_begin(&m, 3000, 1, 1, 0, 5);
    check(!mark_press_move(&m, 0, 8, h) && !mark_press_due(&m, 4000), "handle: slid off, its hold brings nothing");
    mark_press_move(&m, 1, 6, h);
    check(!mark_press_end(&m, 1), "handle: slid off and back, its release brings nothing");
    /* Drawn down 24 game lines from where it began, off the handle on the way: the bar, once. */
    mark_press_begin(&m, 5000, 1, 1, 0, 5);
    check(!mark_press_move(&m, 0, 5 + 23.0f * 1.40625f, h) && mark_press_move(&m, 0, 5 + 24.0f * 1.40625f, h) &&
          !mark_press_move(&m, 0, 200, h) && !mark_press_end(&m, 0), "handle: drawn down 24 lines it brings the bar");
}

static void test_pictures(void)
{
    /* A square filled half: its edge pixels covered by half. */
    Canvas *c = canvas_new(4, 4);
    Pt square[4] = {{0, 0}, {2.5f, 0}, {2.5f, 4}, {0, 4}};
    Paint white = paint_solid(0xffffff, 1.0f);
    paint_polygon(c, square, 4, &white);
    uint32_t a1 = c->px[1] >> 24, a2 = c->px[2] >> 24, a3 = c->px[3] >> 24;
    check(a1 == 255 && a2 >= 120 && a2 <= 135 && a3 == 0, "paint: an edge through a pixel covers it by its share");
    canvas_free(c);
    /* The cursor: its tip at the hot spot, opaque there, the pressed one smaller and blue. */
    int counts[2] = {0, 0}, blue[2] = {0, 0}, hx = 0, hy = 0;
    for (int pressed = 0; pressed < 2; pressed++) {
        Canvas *k = canvas_new(32, 32);
        look_cursor(k, pressed, &hx, &hy);
        for (int i = 0; i < 32 * 32; i++) {
            uint32_t p = k->px[i];
            if ((p >> 24) > 200) {
                counts[pressed]++;
                if ((p & 0xff) > ((p >> 16) & 0xff) + 60)
                    blue[pressed]++;
            }
        }
        canvas_free(k);
    }
    check(hx == 3 && hy == 3, "cursor: the hot spot at the dart's tip");
    check(counts[1] < counts[0] && blue[1] > blue[0] && blue[0] > 20, "cursor: pressed is smaller and blue all over");
    Canvas *k = canvas_new(48, 48);
    look_cursor(k, 0, &hx, &hy);
    check(hx == 5 && hy == 5, "cursor: 48 pixels at 150 %, the hot spot with it");
    canvas_free(k);
    /* The question as a sprite at 150 %: glass under its words (the mask opaque), the picture over it, the room round
     * it clear of glass (only its shadow there). */
    Card card = {0, 0, 0, 0};
    card_open(&card, CARD_QUIT);
    UiLayout l;
    ui_layout(&card, 1920, 1080, &l);
    Sprite sp;
    sprite_make(&sp, l.panel.w, l.panel.h, 8 * l.u);
    look_panel(&sp, &card, &l, -1, -1, no_text, NULL);
    int mid = (int)(sp.room + l.panel.h / 2) * sp.mask->w + (int)(sp.room + l.panel.w / 2);
    check((sp.mask->px[mid] >> 24) == 255 && (sp.mask->px[2 * sp.mask->w + 2] >> 24) == 0,
          "pictures: the question's glass fills its box and stops at its edge");
    /* The keys' ring round Keep playing: the game's light blue just outside its left edge. */
    int ring = (int)(sp.room + l.rows[0].y - l.panel.y + l.rows[0].h / 2) * sp.content->w +
               (int)(sp.room + l.rows[0].x - l.panel.x - 4 * l.u);
    uint32_t px = sp.content->px[ring];
    check((px >> 24) > 200 && (px & 0xff) > ((px >> 16) & 0xff) + 60, "pictures: the keys' ring round Keep playing");
    sprite_free(&sp);
    /* The bar: glass across its whole box. */
    sprite_make(&sp, l.bar.w, l.bar.h, 8 * l.u);
    /* The mark's picture: a block of 40 x 20, opaque red, drawn to the layout's height at its place. */
    Canvas *mark = canvas_new(40, 20);
    for (int i = 0; i < 40 * 20; i++)
        mark->px[i] = 0xffff0000u;
    look_bar(&sp, &l, mark);
    check((sp.mask->px[(int)(sp.room + 3) * sp.mask->w + sp.mask->w / 2] >> 24) == 255 &&
              (sp.mask->px[(int)(sp.room + l.bar.h + 4) * sp.mask->w + sp.mask->w / 2] >> 24) == 0,
          "pictures: the bar's glass covers its band and no more");
    /* Inside the drawn mark the picture's red whole; beyond its width (name_h * 2) none of it. */
    int my = (int)(sp.room + l.bar.h / 2), mx = (int)(sp.room + l.name_x + l.name_h);
    int past = (int)(sp.room + l.name_x + 2 * l.name_h + 3);
    check(sp.content->px[my * sp.content->w + mx] == 0xffff0000u && (sp.content->px[my * sp.content->w + past] >> 16 & 0xff) < 0x80,
          "pictures: the bar draws the mark's picture to its height, its shape kept");
    canvas_free(mark);
    sprite_free(&sp);
    /* The chips: four leaning plates; the X the launcher's main blue, the rest its quiet metal. */
    Box both = {l.chip[0].x, l.chip[0].y, l.chip[CHIP_X].x + l.chip[CHIP_X].w - l.chip[0].x, l.chip[0].h};
    sprite_make(&sp, both.w, both.h, 2 * l.u);
    look_chips(&sp, &l, -1, -1, 0);
    uint32_t xpx = sp.content->px[(int)(sp.room + l.chip[CHIP_X].h * 0.8f) * sp.content->w +
                                  (int)(sp.room + l.chip[CHIP_X].x - l.chip[0].x + 6 * l.u)];
    uint32_t mpx = sp.content->px[(int)(sp.room + l.chip[CHIP_MIN].h * 0.8f) * sp.content->w +
                                  (int)(sp.room + l.chip[CHIP_MIN].x - l.chip[0].x + 6 * l.u)];
    /* The plates lean: the top left corner of each chip's box is outside its plate. */
    uint32_t corner = sp.content->px[(int)(sp.room + 1) * sp.content->w + (int)(sp.room + 1)];
    check(xpx == mpx && ((mpx & 0xff) - ((mpx >> 16) & 0xff)) < 40 && (mpx >> 24) == 255 && (corner >> 24) == 0,
          "pictures: the X in the launcher's quiet metal as the others (lit only under the pointer), their ends leaning");
    sprite_free(&sp);
    /* The handle: the rail across its top, the tab's dark glass under the rail's middle, deeper lit, a light chevron
     * in it (the game's light blue lit), no glass of its own. */
    Box mb = ui_mark_box(1920, 1080, 1);
    sprite_make(&sp, mb.w, mb.h, 2 * l.u);
    look_mark(&sp, l.u, 0);
    int cw = sp.content->w, mid_x = cw / 2, top_y = (int)(sp.room + 0.5f * l.u);
    /* Rows inside the unlit tab (5 game pixels down) and between its foot and the lit one's (10.5 down). */
    int in_y = (int)(sp.room + 5.0f * l.u), deep_y = (int)(sp.room + 10.5f * l.u);
    uint32_t rail_end = sp.content->px[top_y * cw + (int)(sp.room + 2)];
    int rail_unlit = (rail_end >> 24) > 150 && ((rail_end >> 16) & 0xff) > 120;
    int below_rail_end = (sp.content->px[in_y * cw + (int)(sp.room + 2)] >> 24) == 0;
    int tab_unlit = (sp.content->px[in_y * cw + mid_x - (int)(8 * l.u)] >> 24) > 150;
    int deep_unlit = (sp.content->px[deep_y * cw + mid_x - (int)(3 * l.u)] >> 24) > 0;
    /* The chevron: a light pixel on the tab's middle line, below the rail. */
    int light = 0;
    for (int y = (int)(sp.room + 3 * l.u); y < (int)(sp.room + 9 * l.u); y++) {
        uint32_t p = sp.content->px[y * cw + mid_x];
        light |= (p >> 24) > 150 && ((p >> 8) & 0xff) > 150;
    }
    int no_glass = (sp.mask->px[in_y * sp.mask->w + mid_x] >> 24) == 0;
    look_mark(&sp, l.u, 1);
    uint32_t rail_lit = sp.content->px[top_y * cw + (int)(sp.room + 2)];
    int deep_lit = (sp.content->px[deep_y * cw + mid_x - (int)(3 * l.u)] >> 24) > 150;
    check(rail_unlit && below_rail_end && tab_unlit && !deep_unlit && light && no_glass,
          "pictures: the handle is a rail along the top edge with the bar's glass tab under its middle and a chevron, "
          "no glass of its own");
    check(deep_lit && (rail_lit & 0xff) > ((rail_lit >> 16) & 0xff) + 60,
          "pictures: the handle lit is deeper, its rail in the game's light blue");
    sprite_free(&sp);
    /* An image drawn smaller: each pixel the average of what it covers. */
    Canvas *src = canvas_new(4, 2), *dst = canvas_new(2, 1);
    for (int i = 0; i < 8; i++)
        src->px[i] = (i % 2) ? 0xff000000u : 0xffffffffu;
    paint_image(dst, src, 0, 0, 2, 1);
    uint32_t g0 = dst->px[0];
    check((g0 >> 24) == 255 && ((g0 >> 16) & 0xff) >= 126 && ((g0 >> 16) & 0xff) <= 129,
          "paint: an image drawn smaller averages what each pixel covers");
    canvas_free(src);
    canvas_free(dst);
    /* The toast: the game's tab hanging from the top edge, wide at its top, narrow at its foot. */
    Box tb = toast_box(1920, 1080, 300);
    sprite_make(&sp, tb.w, tb.h, 8 * l.u);
    look_toast(&sp, l.u, "words", no_text, NULL);
    int top = (int)(sp.room + 1) * sp.mask->w + (int)(sp.room + 3);
    int foot = (int)(sp.room + tb.h - 2) * sp.mask->w + (int)(sp.room + 3);
    check((sp.mask->px[top] >> 24) > 200 && (sp.mask->px[foot] >> 24) == 0, "pictures: the toast's ends lean in to its foot");
    sprite_free(&sp);
}

/* The picture's choices, the passes each runs, and the filters' constants as their sources work them out. */
static void test_post(void)
{
    Settings s;
    settings_default(&s);
    check(s.upscale == UPSCALE_DEFAULT && s.sharpness == SHARPNESS_DEFAULT && s.antialiasing == AA_DEFAULT,
          "post: the defaults");
    settings_read(&s, "OPENDMT3_UPSCALE", "FSR1");
    settings_read(&s, "OPENDMT3_SHARPNESS", "80");
    settings_read(&s, "OPENDMT3_ANTIALIASING", "smaa-ultra");
    check(s.upscale == UPSCALE_FSR1 && s.sharpness == 80 && s.antialiasing == AA_SMAA_ULTRA, "post: the choices read");
    settings_read(&s, "OPENDMT3_UPSCALE", "dlss");
    settings_read(&s, "OPENDMT3_SHARPNESS", "101");
    settings_read(&s, "OPENDMT3_SHARPNESS", "5x");
    settings_read(&s, "OPENDMT3_ANTIALIASING", "msaa16");
    check(s.upscale == UPSCALE_FSR1 && s.sharpness == 80 && s.antialiasing == AA_SMAA_ULTRA,
          "post: unknown names and numbers out of range leave the value");
    check(aa_from_name("SMAA-Ultra") == AA_SMAA_ULTRA && aa_from_name("msaa4") == -1 &&
          aa_smaa_preset(AA_SMAA_HIGH) == 2 && aa_smaa_preset(AA_FXAA) == -1, "post: the anti-aliasing names, no MSAA");
    int plan[8];
    check(!post_wanted(UPSCALE_SMOOTH, AA_OFF) && post_wanted(UPSCALE_OFF, AA_OFF) &&
          post_wanted(UPSCALE_SMOOTH, AA_FXAA), "post: bilinear with no anti-aliasing is Direct3D's own stretch");
    int n = post_plan(UPSCALE_FSR1, AA_SMAA_LOW, 1280, 768, 3840, 2160, plan);
    check(n == 6 && plan[0] == PASS_SMAA_EDGES && plan[2] == PASS_SMAA_BLEND && plan[3] == PASS_EASU_LEN &&
              plan[4] == PASS_EASU && plan[5] == PASS_RCAS,
          "post: SMAA's three passes, then EASU's lengths, EASU and RCAS");
    n = post_plan(UPSCALE_NIS, AA_FXAA, 1280, 768, 1920, 1080, plan);
    check(n == 4 && plan[0] == PASS_FXAA && plan[1] == PASS_NIS_EDGES && plan[2] == PASS_NIS_ROWS &&
              plan[3] == PASS_NIS_SCALE,
          "post: FXAA, then NIS's edge map, its scaler down the columns and across");
    n = post_plan(UPSCALE_FSR1, AA_OFF, 1280, 768, 1024, 600, plan);
    check(n == 1 && plan[0] == PASS_BILINEAR, "post: a window smaller than the game's picture gets bilinear");
    n = post_plan(UPSCALE_OFF, AA_OFF, 1280, 768, 2560, 1536, plan);
    check(n == 1 && plan[0] == PASS_NEAREST, "post: nearest is one pass");
    /* Anime4K: its network and its 2x picture brought to the window, only past 1.2 times both ways (its own rule). */
    n = post_plan(UPSCALE_ANIME4K, AA_OFF, 1280, 768, 1800, 1080, plan);
    int at_1080 = n == 2 && plan[0] == PASS_ANIME4K && plan[1] == PASS_BILINEAR;
    n = post_plan(UPSCALE_ANIME4K, AA_FXAA, 1280, 768, 3600, 2160, plan);
    int at_4k = n == 3 && plan[0] == PASS_FXAA && plan[1] == PASS_ANIME4K && plan[2] == PASS_BILINEAR;
    n = post_plan(UPSCALE_ANIME4K, AA_OFF, 1280, 768, 1536, 920, plan);
    int under = n == 1 && plan[0] == PASS_BILINEAR;
    /* Exactly 1.2 times across, past it down: bilinear (past 1.2 times both ways, not at it); one more pixel across:
     * the network. */
    n = post_plan(UPSCALE_ANIME4K, AA_OFF, 1280, 768, 1536, 922, plan);
    int at_edge = n == 1 && plan[0] == PASS_BILINEAR;
    n = post_plan(UPSCALE_ANIME4K, AA_OFF, 1280, 768, 1537, 922, plan);
    check(at_1080 && at_4k && under && at_edge && n == 2 && plan[0] == PASS_ANIME4K,
          "post: Anime4K's network then bilinear past 1.2 times, bilinear alone up to it");
    check(upscale_from_name("Anime4K") == UPSCALE_ANIME4K && !strcmp(UPSCALE_NAMES[UPSCALE_ANIME4K], "anime4k"),
          "post: Anime4K by its name");
    float con[16];
    easu_constants(1280, 768, 3840, 2160, con);
    check(fabsf(con[0] - 1.0f / 3.0f) < 1e-6f && fabsf(con[2] - (0.5f / 3.0f - 0.5f)) < 1e-6f &&
          fabsf(con[1] - 768.0f / 2160.0f) < 1e-6f && fabsf(con[7] + 1.0f / 768.0f) < 1e-9f &&
          fabsf(con[13] - 4.0f / 768.0f) < 1e-9f, "post: EASU's constants as FsrEasuCon makes them");
    check(rcas_stops(100) == 0.0f && rcas_stops(0) == 2.0f && rcas_stops(50) == 1.0f && rcas_stops(-5) == 2.0f &&
          fabsf(rcas_constant(1.0f) - 0.5f) < 1e-6f, "post: RCAS's stops from the slider, and its constant");
    NisConfig c;
    nis_config(0.5f, 1280, 768, 1920, 1080, &c);
    check(fabsf(c.sharp_strength_min - 0.4f) < 1e-6f && fabsf(c.sharp_strength_scale - 1.2f) < 1e-6f &&
          fabsf(c.sharp_limit_min - 0.14f) < 1e-6f && fabsf(c.sharp_limit_scale - 0.36f) < 1e-6f &&
          fabsf(c.scale_x - 1280.0f / 1920.0f) < 1e-6f && fabsf(c.ratio_norm - 0.125f) < 1e-6f,
          "post: NIS's constants at half sharpness, as NVScalerUpdateConfig makes them");
    nis_config(0.0f, 1280, 768, 1920, 1080, &c);
    check(c.sharp_strength_min == 0.0f && fabsf(c.sharp_limit_min - 0.1f) < 1e-6f,
          "post: NIS at no sharpness holds its strength and limit at their floors");
    float sum = 0;
    for (int t = 0; t < NIS_TAPS; t++)
        sum += NIS_COEF_SCALE[32][t];
    check(fabsf(sum - 1.0f) < 0.01f && NIS_COEF_SCALE[0][2] == 1.0f && NIS_COEF_USM[63][5] == 0.0029f,
          "post: NIS's filter banks as NIS_Config.h has them");
    int w, h;
    back_buffer_size(1920, 1080, 3840, 2160, &w, &h);
    check(w == 3840 && h == 2160, "post: the back buffer is the monitor's size, the window may grow to it");
    back_buffer_size(1000, 600, 1024, 600, &w, &h);
    check(w == 1280 && h == 768, "post: never under the game's picture");
    /* Flipped, the client's size whatever it is (a window the chip makes on a 768-line screen, under the game's
     * picture, too: presented whole, it is what Windows shows one to one); a client of no size: the copy model's. */
    int fw, fh, ok = 1;
    flip_back_buffer_size(960, 576, 1366, 768, &fw, &fh);
    ok &= fw == 960 && fh == 576;
    flip_back_buffer_size(1920, 1080, 1920, 1080, &fw, &fh);
    ok &= fw == 1920 && fh == 1080;
    flip_back_buffer_size(0, 0, 1366, 768, &fw, &fh);
    check(ok && fw == 1366 && fh == 768, "post: flipped, the back buffer is the window's client, a small one too");
}


/* The music lock against a simulated song: a sound card's clock 0.05 % fast with its cursor moving in 10 ms steps, and
 * a stall of half a second in the middle, as the game's own loads make. Frame k must stay within a frame of k/60 s of
 * the music, and no frame may be shorter than three quarters of one. */
static void test_music_lock(void)
{
    const int64_t f = 10000000;
    Pacer p;
    MusicLock m;
    pacer_start(&p, f, GAME_FPS);
    music_lock_start(&m);
    int64_t now = 0, last = 0;
    double worst_after = 0, base = 0, shortest = 1e9;
    int primed = 0;
    for (long k = 1; k <= 60 * 120; k++) {
        /* The game's own work: 5 ms a frame, and one stall of 500 ms at a minute in. */
        now += k == 3600 ? 5000000 : 50000;
        if (p.next) {
            /* The music now: real time a little fast, read in the cursor's 10 ms steps. */
            double music = (double)now / f * 1000.0 * 1.0005;
            music = (double)(int64_t)(music / 10.0) * 10.0;
            double until = (double)(p.next - now) * 1000.0 / f;
            double ahead = music + (until > 0 ? until : 0) - (double)k * 1000.0 / 60.0;
            if (!primed) {
                base = ahead;
                primed = 1;
            }
            p.next -= music_lock_step(&m, ahead - base, p.period);
        }
        now += pacer_wait(&p, now);
        double music_now = (double)now / f * 1000.0 * 1.0005;
        double off = music_now - (double)k * 1000.0 / 60.0 - base;
        if (off < 0)
            off = -off;
        /* After the stall has been won back (10 s on), and before it. */
        if (k < 3600 || k > 3600 + 600)
            if (off > worst_after)
                worst_after = off;
        if (k > 1 && k != 3600 && (double)(now - last) * 1000.0 / f < shortest)
            shortest = (double)(now - last) * 1000.0 / f;
        last = now;
    }
    check(worst_after < 1000.0 / 60.0, "music lock: frames within a frame of the music for two minutes, a stall won back");
    check(shortest >= 1000.0 / 60.0 * 0.75 - 0.01, "music lock: no frame shorter than three quarters of one");
    music_lock_start(&m);
    check(music_lock_step(&m, 0.5, 166666) == 0, "music lock: under 1 ms is left alone");
}

/* The audio offset's lag of a song's chart (logic.c ChartLag), over a song of 30 s simulated as the score counts it: a
 * tick of `ms_per_tick` ms, a frame each 1/60 s counting the ticks due by then. Returns the seconds the lag took to
 * reach the offset's ticks (-1: never); *back set when a frame's shown count was below the last one's, *past when one
 * was past the score's own (a lag below none) or the lag past the offset's ticks, *stopped when the shown count stood
 * still in a frame the score counted ticks in, *end_lag the lag at the end in ticks, and *ramp_part the shown ticks
 * over the score's own while the lag grew. */
static double lag_song(int offset_ms, double ms_per_tick, int *back, int *past, int *stopped, uint32_t *end_lag,
                       double *ramp_part)
{
    ChartLag c;
    chart_lag_start(&c);
    uint32_t target = chart_lag_ticks(offset_ms, ms_per_tick);
    uint32_t last_real = 0, last_shown = 0, ramp_real = 0, ramp_shown = 0;
    double reached = -1;
    *back = *past = *stopped = 0;
    *end_lag = 0;
    for (long k = 0; k <= 60 * 30; k++) {
        /* The ticks the score has counted by this frame. */
        uint32_t real = (uint32_t)((double)k * 1000.0 / 60.0 / ms_per_tick);
        uint32_t shown = chart_lag_frame(&c, real, target);
        if (shown > real || real - shown > target)
            *past = 1;
        if (k > 0) {
            *back |= shown < last_shown;
            *stopped |= real > last_real && shown == last_shown;
            /* While the lag was still growing at the frame before: what the shown count moved against the score's. */
            if (reached < 0) {
                ramp_real += real - last_real;
                ramp_shown += shown - last_shown;
            }
        }
        if (reached < 0 && real - shown == target)
            reached = (double)k / 60.0;
        last_real = real;
        last_shown = shown;
        *end_lag = real - shown;
    }
    *ramp_part = ramp_real ? (double)ramp_shown / ramp_real : 1.0;
    return reached;
}

/* Motion clarity's refreshes a frame for a display's rate, and the flip model's judgement of a display that follows
 * the frames (logic.c strobe_refreshes, display_follows). */
static void test_display_choices(void)
{
    check(strobe_refreshes(120) == 2 && strobe_refreshes(180) == 3 && strobe_refreshes(240) == 4 &&
              strobe_refreshes(360) == 6, "display: whole multiples of 60 from 120 up");
    check(strobe_refreshes(119) == 2 && strobe_refreshes(239) == 4 && strobe_refreshes(241) == 4,
          "display: within 1 Hz of one (119.88 and 239.76 Hz as Windows gives them)");
    check(!strobe_refreshes(60) && !strobe_refreshes(59) && !strobe_refreshes(144) && !strobe_refreshes(165) &&
              !strobe_refreshes(237) && !strobe_refreshes(0), "display: 60 Hz, 144, 165, 2 Hz off a multiple, none");
    /* One refresh a frame in nine of ten frames, on a mode that gives four: the display follows them. */
    check(display_follows(4, 120, 110), "display: a variable refresh rate found (one refresh a frame at 240 Hz)");
    check(!display_follows(4, 120, 100), "display: not with fewer than nine in ten");
    check(!display_follows(1, 120, 120), "display: not on a 60 Hz mode, where one refresh a frame is its own");
    check(!display_follows(4, 59, 59), "display: not on fewer than 60 frames");
    /* Motion clarity's sub-frames (several presents a frame) are never single steps: none counted, nothing found. */
    check(!display_follows(2, 0, 0), "display: frames with sub-frames say nothing");
}

/* A song locked to its music through resets of the device (hooks.c take_parameters and lock_to_music, logic.c
 * SongLock): at the song's 20th and 40th second a reset stalls the frames `stall_ms`, then the pacer and the lock's
 * readings start again, as a switch between a window and full screen does. Returns how far behind the music the frames
 * end, past the game's own start (ms: 0 when the lock holds it); the longest and shortest gaps between frames from the
 * first reset on, the resets' own frames left out. */
static double reset_song(double stall_ms, double *longest_ms, double *shortest_ms)
{
    const int64_t f = 10000000;
    Pacer p;
    SongLock s;
    song_lock_start(&s);
    pacer_start(&p, f, GAME_FPS);
    int64_t now = 0, last = 0;
    /* The game's own start distance, as the song's first frame found it (never taken again: what the frames end
     * behind is measured from it, whatever the lock holds). */
    double behind = 0, start = 0;
    int started = 0;
    *longest_ms = 0;
    *shortest_ms = 1e9;
    for (long k = 1; k <= 60 * 60; k++) {
        /* The frame's own work. */
        now += 50000;
        /* A reset at the 20th and the 40th second: the device's own time, then the pacer and the lock start again. */
        int reset = k == 60 * 20 || k == 60 * 40;
        if (reset) {
            now += (int64_t)(stall_ms * (double)f / 1000.0);
            pacer_start(&p, f, GAME_FPS);
            song_lock_pause(&s);
        }
        if (p.next) {
            /* The music as it plays, against the frame's place at its tick; the song's music started at frame 1. */
            double music = (double)now / f * 1000.0;
            double until = (double)(p.next - now) * 1000.0 / f;
            double ahead = music + (until > 0 ? until : 0) - (double)k * 1000.0 / 60.0;
            int began;
            double off;
            p.next -= song_lock_frame(&s, 1, ahead, p.period, &began, &off);
            if (!started) {
                start = s.base;
                started = 1;
            }
        }
        now += pacer_wait(&p, now);
        /* How far behind the music this frame is now, past the game's own start distance. */
        behind = (double)now / f * 1000.0 - (double)k * 1000.0 / 60.0 - start;
        /* The gaps after the first reset, but for the resets' own (their stall) and the frame after each. */
        int near = k == 60 * 20 || k == 60 * 20 + 1 || k == 60 * 40 || k == 60 * 40 + 1;
        if (k > 60 * 20 && !near && !reset) {
            double gap = (double)(now - last) * 1000.0 / f;
            if (gap > *longest_ms)
                *longest_ms = gap;
            if (gap < *shortest_ms)
                *shortest_ms = gap;
        }
        last = now;
    }
    return behind;
}

static void test_audio_offset(void)
{
    Settings s;
    settings_default(&s);
    check(s.audio_offset == 0, "audio offset: none by default");
    settings_read(&s, "OPENDMT3_AUDIO_OFFSET", "180");
    check(s.audio_offset == 180, "audio offset: the launcher's milliseconds read");
    settings_read(&s, "OPENDMT3_AUDIO_OFFSET", "-20");
    settings_read(&s, "OPENDMT3_AUDIO_OFFSET", "501");
    settings_read(&s, "OPENDMT3_AUDIO_OFFSET", "12ms");
    check(s.audio_offset == 180, "audio offset: below 0, past the most or not a number leaves it");
    /* Motion clarity and the flip model by the launcher's words; anything else leaves each off. */
    check(s.motion == MOTION_OFF && !s.flip, "settings: motion clarity and the flip model off by default");
    settings_read(&s, "OPENDMT3_MOTION_CLARITY", "CRT");
    settings_read(&s, "OPENDMT3_FLIP_MODEL", "on");
    check(s.motion == MOTION_CRT && s.flip, "settings: the CRT beam and the flip model read");
    settings_read(&s, "OPENDMT3_MOTION_CLARITY", "bfi");
    check(s.motion == MOTION_BFI, "settings: black frames read");
    settings_read(&s, "OPENDMT3_MOTION_CLARITY", "strobe");
    settings_read(&s, "OPENDMT3_FLIP_MODEL", "flipex");
    check(s.motion == MOTION_OFF && !s.flip, "settings: other words leave both off");
    /* The offset in a song's ticks: the nearest whole one, none for no offset or no tempo read. */
    check(chart_lag_ticks(80, 2.5) == 32 && chart_lag_ticks(81, 2.54) == 32 && chart_lag_ticks(500, 2.65) == 189,
          "audio offset: the offset in the nearest whole ticks of the song's tempo");
    check(chart_lag_ticks(0, 2.5) == 0 && chart_lag_ticks(-20, 2.5) == 0 && chart_lag_ticks(80, 0) == 0 &&
              chart_lag_ticks(80, -1) == 0 && chart_lag_ticks(80, nan("")) == 0,
          "audio offset: no lag for no offset, or for a tempo not read");
    /* Over a song: the lag grows at a quarter of the score's pace, then holds the offset's ticks exactly. */
    int back, past, stopped;
    uint32_t end_lag;
    double part;
    double at = lag_song(80, 2.54, &back, &past, &stopped, &end_lag, &part);
    check(at > 0.30 && at < 0.36 && end_lag == chart_lag_ticks(80, 2.54),
          "audio offset: 80 ms reached in a third of a second, then held to the song's end");
    check(part > 0.73 && part < 0.77, "audio offset: the notes at three quarters of their pace while the lag grows");
    check(!back && !past && !stopped, "audio offset: the count shown never back, never past the score's own, never "
                                      "standing still while the score counts");
    at = lag_song(500, 2.65, &back, &past, &stopped, &end_lag, &part);
    check(at > 1.95 && at < 2.05 && end_lag == 189 && !back && !past && !stopped,
          "audio offset: 500 ms (the most) reached in 2 s, the same way");
    at = lag_song(0, 2.54, &back, &past, &stopped, &end_lag, &part);
    check(at == 0 && end_lag == 0 && !back && !past, "audio offset: 0 shows the score's own count");
    /* A slower tempo (fewer ticks for the offset): the lag down to it at once, the count shown going on, never back. A
     * count gone back (the game set it back): the lag from none. */
    ChartLag c;
    chart_lag_start(&c);
    uint32_t shown = 0;
    for (uint32_t real = 0; real <= 400; real += 4)
        shown = chart_lag_frame(&c, real, 32);
    uint32_t slower = chart_lag_frame(&c, 404, 20);
    check(shown == 400 - 32 && slower == 404 - 20, "audio offset: a smaller lag taken at once, the count going on");
    check(chart_lag_frame(&c, 100, 20) == 100 && chart_lag_frame(&c, 104, 20) == 103,
          "audio offset: a count set back starts the lag again at none");
    /* A song through two resets of the device (a window switch each), 300 ms of stall each: the song keeps its own
     * start, so the frames end on the music, and each stall is won back. */
    double longest, shortest, end;
    end = reset_song(300.0, &longest, &shortest);
    check(end > -3.0 && end < 3.0, "music lock: a song through two resets ends on its music");
    check(shortest >= 1000.0 / 60.0 - 4.01, "music lock: a reset's stall won back 4 ms a frame at most");
    /* Another song (its music started at another frame) takes its own start; the same song after a reset keeps its. */
    SongLock sl;
    song_lock_start(&sl);
    int began;
    double off;
    song_lock_frame(&sl, 100, 5.0, 166667, &began, &off);
    check(began && sl.base == 5.0, "music lock: a song's first frame takes its start");
    song_lock_pause(&sl);
    song_lock_frame(&sl, 100, 305.0, 166667, &began, &off);
    check(!began && sl.base == 5.0 && off == 300.0, "music lock: after a reset the same song keeps its start");
    song_lock_frame(&sl, 900, 12.0, 166667, &began, &off);
    check(began && sl.base == 12.0, "music lock: a new song takes its own start");
}

/* Frames started just in time: none while loading or without a clock, the lead from the slowest 1 % of the work and the
 * spare, a miss growing the spare and a calm giving it back; then a song's frames simulated with the pacer, the music
 * lock and the display lock: each frame's input is read just before its tick, and every frame leaves on its tick. */
/* A song simulated with its frames started just in time, as hooks.c our_present and jit_rest run them: the game's
 * work on the processor `cpu` to `cpu + spread` ticks a frame (its input read at its start), its picture done `gpu`
 * after its draws, the present 0.3 ms; the music a little fast and read in 10 ms steps, `jump` ms further ahead from
 * frame `jump_at` on (0: never); a 240 Hz display read at each tick; the lead's slack counted (`slack` 1) or not. The
 * locks move the tick first, then the picture is waited for until that tick at most. Counted after the loading: the
 * frames, those not done by their tick and those of them started late, the frames started late, the input's age at its
 * frame's tick (mean, ms) and the ticks' spread. */
typedef struct {
    int frames, late, late_held, held;
    double read_to_tick, worst_gap, shortest;
} JitSong;

static JitSong jit_song(int64_t cpu, int64_t spread, int64_t gpu, long jump_at, double jump, int slack_on)
{
    const int64_t f = 10000000, ms = f / 1000;
    JitSong s = {0, 0, 0, 0, 0.0, 0.0, 1e9};
    Pacer p;
    MusicLock m;
    JitClock j;
    pacer_start(&p, f, GAME_FPS);
    music_lock_start(&m);
    jit_start(&j, f, GAME_FPS);
    int64_t now = 0, refresh = f / 240, last_tick = 0;
    double base = 0;
    int primed = 0, early = 0, measured = 0;
    for (long k = 1; k <= 60 * 60; k++) {
        /* The frame: its input read at its start, its draws handed over `work` later, its picture done `gpu` after. */
        int64_t read = now, work = cpu + (k * 7919 % (spread + 1));
        now += work;
        int64_t done = now + gpu;
        if (p.next) {
            /* The music lock and the display lock first, from the music and the display as they are now. */
            double music = (double)now / f * 1000.0 * 1.0005 + (jump_at && k >= jump_at ? jump : 0.0);
            music = (double)(int64_t)(music / 10.0) * 10.0;
            double until = (double)(p.next - now) * 1000.0 / f;
            double ahead = music + (until > 0 ? until : 0) - (double)k * 1000.0 / 60.0;
            if (!primed) {
                base = ahead;
                primed = 1;
            }
            p.next -= music_lock_step(&m, ahead - base, p.period);
            /* The display's phase at the tick (its refreshes start at 0). */
            double phase = (double)(p.next % refresh) / (double)refresh;
            p.next += display_lock_step(phase, refresh);
            /* Then the picture against the tick as they set it: waited for until it at most; done by it, or a miss. */
            int in_time = done <= p.next;
            jit_frame(&j, work, in_time, early);
            if (k > JIT_SETTLE + 1) {
                s.frames++;
                s.late += !in_time;
                s.late_held += !in_time && early;
                s.held += early;
            }
            now = in_time ? (done > now ? done : now) : p.next;
        }
        int64_t tick = now + pacer_wait(&p, now);
        if (k > JIT_SETTLE + 60) {
            double gap = (double)(tick - last_tick) * 1000.0 / f - 1000.0 / 60.0;
            if (gap < 0)
                gap = -gap;
            if (gap > s.worst_gap)
                s.worst_gap = gap;
            if ((double)(tick - last_tick) * 1000.0 / f < s.shortest)
                s.shortest = (double)(tick - last_tick) * 1000.0 / f;
            s.read_to_tick += (double)(tick - read) * 1000.0 / f;
            measured++;
        }
        last_tick = tick;
        /* The present, then the next frame held back to just before its tick (jit_rest). */
        now = tick + 3000;
        int64_t slack = slack_on ? (int64_t)(music_lock_most(&m) * (double)ms) + refresh / 64 : 0;
        int64_t lead = jit_lead(&j, slack);
        early = lead > 0 && p.next - lead > now;
        if (early)
            now = p.next - lead;
    }
    s.read_to_tick /= measured > 0 ? measured : 1;
    return s;
}

static void test_jit(void)
{
    const int64_t f = 10000000, ms = f / 1000;
    JitClock j;
    jit_start(&j, f, 0);
    jit_frame(&j, 3 * ms, 1, 0);
    check(jit_lead(&j, 0) == 0, "jit: no clock, every frame at once");
    jit_start(&j, f, GAME_FPS);
    for (int i = 0; i < JIT_SETTLE - 1; i++)
        jit_frame(&j, 3 * ms, 1, 0);
    check(jit_lead(&j, 0) == 0, "jit: the game's loading starts its frames at once");
    jit_frame(&j, 3 * ms, 1, 0);
    check(jit_lead(&j, 0) == 3 * ms + ms, "jit: then the work and a millisecond spare");
    check(jit_lead(&j, ms / 2) == 3 * ms + ms + ms / 2, "jit: and what may still move the tick");
    /* One slow frame in the window is the slowest 1 %'s outlier; a second is counted. */
    jit_frame(&j, 9 * ms, 1, 1);
    check(jit_work(&j) == 3 * ms, "jit: one slow frame of 120 is left out");
    jit_frame(&j, 8 * ms, 1, 1);
    check(jit_work(&j) == 8 * ms, "jit: two are the slowest 1 %");
    for (int i = 0; i < JIT_WINDOW; i++)
        jit_frame(&j, 3 * ms, 1, 1);
    check(jit_work(&j) == 3 * ms, "jit: the window forgets after 120 frames");
    /* A frame started late that misses its tick: a millisecond more; one started at once says nothing. */
    int64_t was = j.spare;
    jit_frame(&j, 3 * ms, 0, 0);
    check(j.spare == was, "jit: a miss of a frame started at once leaves the spare");
    jit_frame(&j, 3 * ms, 0, 1);
    check(j.spare == was + ms, "jit: a miss of a frame started just in time adds a millisecond");
    for (int i = 0; i < 20; i++)
        jit_frame(&j, 3 * ms, 0, 1);
    check(j.spare == j.period / 4, "jit: at most a quarter of a frame spare");
    for (int i = 0; i < JIT_CALM - 1; i++)
        jit_frame(&j, 3 * ms, 1, 1);
    check(j.spare == j.period / 4, "jit: the spare kept through five seconds in time");
    for (int i = 0; i < 400; i++)
        jit_frame(&j, 3 * ms, 1, 1);
    check(j.spare == ms, "jit: then given back down to a millisecond");
    MusicLock m;
    music_lock_start(&m);
    check(music_lock_most(&m) == 4.0, "jit: the lock's first step may be a stall's");
    music_lock_step(&m, 3.0, f / GAME_FPS);
    check(music_lock_most(&m) == 1.0, "jit: a drift's step is at most 1 ms");
    music_lock_start(&m);
    music_lock_step(&m, 200.0, f / GAME_FPS);
    check(music_lock_most(&m) == 4.0, "jit: winning back a stall, 4 ms");
    /* A song with its frames started just in time (jit_song): the game's work 2.5 to 3.5 ms on the processor, its
     * picture done 0.5 ms after its draws. */
    JitSong s = jit_song(25000, 10000, 5000, 0, 0, 1);
    check(s.late == 0, "jit: a song's frames all done by their ticks");
    check(s.held > s.frames * 9 / 10, "jit: nine in ten of them started just in time");
    check(s.read_to_tick < 7.0, "jit: input read under 7 ms before its frame leaves (a period before, without it)");
    check(s.worst_gap < 1.5 && s.shortest > 1000.0 / 60.0 - 1.5,
          "jit: the frames' ticks as even as the locks make them (within 1.5 ms of a period)");
    /* The music 200 ms ahead from the song's 20th second (a stall's distance): the lock takes 4 ms off each tick while
     * it wins it back, which the lead's slack must cover. Without the slack the frames started late miss. */
    JitSong stall = jit_song(25000, 10000, 5000, 1200, 200.0, 1);
    JitSong bare = jit_song(25000, 10000, 5000, 1200, 200.0, 0);
    check(stall.late_held <= 2 && bare.late_held >= 10,
          "jit: winning back a stall, the frames started late still done by their ticks (the slack counted)");
    /* A GPU slower than any spare covers (12 ms after 3 ms of work): after three misses in a row at the most spare,
     * five seconds of frames started at once each time, so few frames are held and fewer miss. */
    JitSong slow = jit_song(30000, 5000, 120000, 0, 0, 1);
    check(slow.late_held <= JIT_STREAK * (slow.frames / JIT_REST + 2) + 5 && slow.held < slow.frames / 10,
          "jit: a GPU slower than the spare: the clock rests instead of holding frames that miss");
}

/* A song on a display, simulated as hooks.c runs it: our_present (the frame's work, at most one frame queued, the
 * music lock and its catch-up in lock_to_music, the display lock, the picture waited for until the tick, the pacer),
 * leave_unshown for a frame planned to be left unshown, and jit_rest. The game's work on the processor is `cpu` to
 * `cpu + spread` ticks a frame, the chain's 0.2 ms after it; on the GPU, once a frame's draws are handed over and the
 * frames before are done there, the game's own draws take `gpu_game` ticks (a frame left unshown has them too) and the
 * chain's passes `gpu_chain`, which the chain's timestamps time; a present shows only once its picture is done; a stall
 * adds
 * `stall_ms[i]` to the frame `stall_s[i]` seconds into the song (0: none). The music starts 10 s in (the frames before
 * it are the game's menus: no lock) and plays 0.05 % fast, read in the sound card's 10 ms steps. The display
 * refreshes every `refresh` ticks (Windows says `hz`; refresh 0: VSync off, every present shown at once); with VSync
 * a present shows at the first refresh after it and after the frame before's, and returns at that refresh (`queue` 0:
 * the present waits, the worst for the frame after a skip) or at once, the next frame then waiting for it before its
 * own present (`queue` 1: Direct3D's queue of one frame). `fixed_on` 0 runs the layer as before this catch-up (the
 * lock's steps all taken, nothing left unshown); `offset` is the audio offset (ms). What the screen shows is judged:
 * the music at the refresh that shows a frame against the frame's place in the song, from the song's first frame's
 * and the offset. */
typedef struct {
    int shown, skips, late, unfit;
    int repeats;           /* frames shown more than a refresh after the frame before, but for the stalls' own */
    int in_a_row;          /* the most frames left unshown in a row */
    int closest;           /* the fewest frames from one left unshown to the next (0: fewer than two) */
    int outside;           /* frames left unshown before the first stall (the menus, the song's start) */
    int lines;             /* catch-ups ended within a frame (a line each in the layer's log) */
    int shown_steady;      /* frames shown in the steady stretches below */
    double caught[2];      /* each stall: seconds from it to the first frame shown within a frame of the music (-1:
                            * never) */
    double worst_steady;   /* the most a frame shown was off the music before the first stall and from 6 s after each */
    double low, high;      /* there, the least and the most it was behind (ms; negative: ahead) */
    double end_behind;     /* how far behind the music the song's last frame shown was (ms) */
    double first_from;     /* how far behind the first catch-up began (ms), and its frames left unshown */
    int first_skips;
} CatchSong;

static CatchSong catch_song(int hz, int64_t refresh, int queue, int64_t cpu, int64_t spread, int64_t gpu_game,
                            int64_t gpu_chain, const double stall_s[2], const double stall_ms[2], int fixed_on,
                            int seconds, double offset)
{
    const int64_t f = 10000000, ms = f / 1000;
    const double frame = 1000.0 / GAME_FPS;
    const long lead_in = 600;
    CatchSong s;
    memset(&s, 0, sizeof s);
    s.caught[0] = s.caught[1] = -1;
    Pacer p;
    MusicLock m;
    JitClock j, w, wgpu;
    CatchUp c;
    pacer_start(&p, f, GAME_FPS);
    music_lock_start(&m);
    jit_start(&j, f, GAME_FPS);
    jit_start(&w, f, GAME_FPS);
    jit_start(&wgpu, f, GAME_FPS);
    catchup_start(&c);
    int vsync = refresh > 0;
    /* The display takes no frame sooner: the lock takes nothing off a tick, and frames may be left unshown. */
    int fixed = fixed_on && catchup_display(vsync, hz);
    /* The refreshes: at v0 + n * refresh, v0 a little way into the first. */
    int64_t v0 = refresh * 37 / 100, last_shown = -1, now = 0, start = 0, frame_start = 0, prev_done = 0, gpu_free = 0;
    int64_t stall_at[2] = {0, 0}, stalled_shown[2] = {-1, -1};
    double base = 0, true_base = 0;
    int primed = 0, true_primed = 0, skip_next = 0, after_skip = 0, started_late = 0, row = 0;
    int64_t skip_deadline = 0;
    long last_skip = -1, music_from = 0;
    int64_t music_t0 = 0;
    for (int i = 0; i < 2; i++)
        stall_at[i] = stall_ms[i] > 0 ? lead_in + (long)(stall_s[i] * GAME_FPS) : 0;
    for (long k = 1; k <= lead_in + (long)seconds * GAME_FPS; k++) {
        /* The game's frame: its input read at `start`, its own work, a stall where one is. */
        int64_t work = cpu + (k * 7919 % (spread + 1));
        for (int i = 0; i < 2; i++)
            if (k == stall_at[i])
                work += (int64_t)(stall_ms[i] * (double)ms);
        int64_t arrival = start + work;
        /* The music starts in the frame after the menus (the game's Play), its time 0 there. */
        if (k == lead_in + 1)
            music_t0 = start, music_from = lead_in;
        int song = k > lead_in;
        if (skip_next) {
            /* leave_unshown: the frame planned is left unshown when the next one can go out before the refresh it
             * would have been shown at. */
            skip_next = 0;
            /* The refresh the frame would have been shown at, by the display's phase as the frame came; the next
             * frame's time to its picture done, the GPU's part too. */
            double phase = vsync ? (double)((arrival - v0) % refresh + refresh) / (double)refresh : -1.0;
            int64_t deadline = catchup_deadline(arrival, p.next, refresh, vsync ? phase - floor(phase) : -1.0);
            if (catchup_fits(arrival, p.next, deadline, catchup_work(jit_work(&w), jit_work(&wgpu)), refresh)) {
                catchup_skipped(&c);
                s.skips++;
                if (k < (stall_at[0] ? stall_at[0] : k + 1))
                    s.outside++;
                if (last_skip > 0 && (s.closest == 0 || k - last_skip < s.closest))
                    s.closest = (int)(k - last_skip);
                last_skip = k;
                if (++row > s.in_a_row)
                    s.in_a_row = row;
                /* Its own picture still drawn on the GPU (the game's draws were handed over). The next frame starts at
                 * once, its work counted from here, its present judged against that refresh. */
                gpu_free = (gpu_free > arrival ? gpu_free : arrival) + gpu_game;
                start = arrival + 200;
                frame_start = start;
                after_skip = 1;
                skip_deadline = deadline;
                started_late = 0;
                continue;
            }
            catchup_unfit(&c);
            s.unfit++;
        }
        row = 0;
        /* The chain's work, then the frame before done on the GPU (at most one queued: with a queue, its refresh). */
        int64_t t0 = arrival + 2000;
        if (queue && prev_done > t0)
            t0 = prev_done;
        /* The recent frames' work for the catch-up, as for the clock, and the chain's time on the GPU. */
        if (frame_start)
            jit_frame(&w, t0 - frame_start, 1, 0);
        jit_frame(&wgpu, gpu_chain, 1, 0);
        if (song) {
            /* lock_to_music: the music now in the cursor's steps, at the tick, against the frame's place. */
            double music = (double)(t0 - music_t0) / f * 1000.0 * 1.0005;
            music = (double)(int64_t)(music / 10.0) * 10.0;
            double until = (double)(p.next - t0) / ms;
            double ahead = music + (until > 0 ? until : 0) - (double)(k - music_from) * frame;
            if (!primed) {
                base = ahead;
                primed = 1;
            }
            double off = ahead - base - offset;
            int64_t step = music_lock_step(&m, off, p.period);
            if (fixed && step > 0)
                step = 0;
            p.next -= step;
            if (fixed_on) {
                skip_next = catchup_frame(&c, off, fixed);
                if (c.done) {
                    if (!s.lines)
                        s.first_skips = c.skips;
                    s.lines++;
                    c.done = 0;
                }
                if (s.first_from == 0 && c.running)
                    s.first_from = c.from_ms;
            }
        }
        /* The display lock: the tick's phase in its refresh. */
        if (vsync) {
            int64_t at = p.next > t0 ? p.next : t0;
            double phase = (double)((at - v0) % refresh + refresh) / (double)refresh;
            p.next += display_lock_step(phase - floor(phase), refresh);
        }
        /* The picture on the GPU after the frames before it, waited for until the tick at most. */
        int64_t done = (gpu_free > t0 ? gpu_free : t0) + gpu_game + gpu_chain;
        gpu_free = done;
        int in_time = done <= p.next;
        if (frame_start)
            jit_frame(&j, t0 - frame_start, in_time, started_late);
        now = in_time ? (done > t0 ? done : t0) : (p.next > t0 ? p.next : t0);
        /* The frame after a skip: its picture waited for until the latest it may go out. */
        int64_t limit = after_skip ? skip_deadline - refresh / 16 : 0;
        int skip_ready = !after_skip || done <= limit;
        if (after_skip && done > now)
            now = done < limit ? done : (limit > now ? limit : now);
        int64_t tp = now + pacer_wait(&p, now);
        if (after_skip) {
            after_skip = 0;
            int in = skip_ready && tp <= limit;
            catchup_after(&c, in);
            s.late += !in;
        }
        /* The present: shown at the first refresh after it, with its picture done, and after the frame before's (with
         * VSync off, as soon as its picture is done). */
        int64_t shown = done > tp ? done : tp;
        if (vsync) {
            int64_t ready_at = done > tp ? done : tp;
            shown = v0 + ((ready_at - v0) / refresh + 1) * refresh;
            if (last_shown >= 0 && shown <= last_shown)
                shown = last_shown + refresh;
        }
        /* A refresh with no new frame where no stall was: the frame before shown twice. */
        if (vsync && last_shown >= 0 && shown - last_shown > refresh * 3 / 2 && k != stall_at[0] && k != stall_at[1])
            s.repeats++;
        last_shown = shown;
        int64_t back = queue || !vsync ? tp + 500 : shown;
        prev_done = vsync ? shown : (done > tp ? done : tp);
        s.shown++;
        if (song) {
            /* What the screen shows: the music then against the frame's place, from the song's first frame's. */
            double behind = (double)(shown - music_t0) / f * 1000.0 * 1.0005 - (double)(k - music_from) * frame;
            if (!true_primed) {
                true_base = behind;
                true_primed = 1;
            }
            behind -= true_base + offset;
            s.end_behind = behind;
            double off = behind < 0 ? -behind : behind;
            for (int i = 0; i < 2; i++) {
                if (stall_at[i] && k >= stall_at[i] && stalled_shown[i] < 0)
                    stalled_shown[i] = shown;
                if (stalled_shown[i] >= 0 && s.caught[i] < 0 && k > stall_at[i] && off < frame &&
                    (i == 1 || !stall_at[1] || k < stall_at[1]))
                    s.caught[i] = (double)(shown - stalled_shown[i]) / f;
            }
            /* Steady: before the first stall, and from 6 s after each. */
            int steady = !stall_at[0] || k < stall_at[0];
            for (int i = 0; i < 2; i++)
                if (stall_at[i] && k > stall_at[i] + 6 * GAME_FPS && (i == 1 || !stall_at[1] || k < stall_at[1]))
                    steady = 1;
            if (steady && off > s.worst_steady)
                s.worst_steady = off;
            if (steady && (s.low > behind || !s.shown_steady))
                s.low = behind;
            if (steady && (s.high < behind || !s.shown_steady))
                s.high = behind;
            s.shown_steady += steady;
        }
        /* jit_rest: the frame to be left unshown starts at once; any other is held to just before its tick. */
        started_late = 0;
        start = back;
        if (!skip_next) {
            int64_t slack = (song && !fixed ? (int64_t)(music_lock_most(&m) * (double)ms) : 0) + (vsync ? refresh / 64 : 0);
            int64_t lead = jit_lead(&j, slack);
            if (lead > 0 && p.next - lead > back) {
                start = p.next - lead;
                started_late = 1;
            }
        }
        frame_start = start;
    }
    return s;
}

static void test_catchup(void)
{
    const int64_t f = 10000000, ms = f / 1000;
    /* The displays that take no frame sooner: VSync on and under 64 Hz. */
    check(catchup_display(1, 60) && catchup_display(1, 59) && catchup_display(1, 61) && catchup_display(1, 50) &&
              catchup_display(1, 63), "catch-up: 60 Hz with VSync takes no frame sooner (and 59, 61, 63, 50)");
    check(!catchup_display(1, 64) && !catchup_display(1, 75) && !catchup_display(1, 120) && !catchup_display(1, 144) &&
              !catchup_display(1, 240) && !catchup_display(0, 60) && !catchup_display(1, 0),
          "catch-up: 64 Hz up, VSync off or no rate known take frames sooner (or are not known)");
    /* The decision: five readings over a frame, then a frame to leave unshown; none while not allowed. */
    CatchUp c;
    catchup_start(&c);
    int plans = 0;
    for (int i = 0; i < 4; i++)
        plans += catchup_frame(&c, 40.0, 1);
    check(!plans && catchup_frame(&c, 40.0, 1) && c.running && c.from_ms == 40.0,
          "catch-up: a frame left unshown after five readings over a frame");
    catchup_skipped(&c);
    plans = 0;
    for (int i = 0; i < 4; i++)
        plans += catchup_frame(&c, 23.0, 1);
    check(!plans && catchup_frame(&c, 23.0, 1), "catch-up: the next one five frames shown later, never two in a row");
    catchup_skipped(&c);
    plans = 0;
    for (int i = 0; i < 5; i++)
        plans += catchup_frame(&c, 6.0, 1);
    check(!plans && c.done && !c.running && c.skips == 2 && c.frames == 2 + 10 && c.to_ms == 6.0,
          "catch-up: within a frame it is over, with its numbers for its line");
    catchup_start(&c);
    plans = 0;
    for (int i = 0; i < 20; i++)
        plans += catchup_frame(&c, 16.0, 1) + catchup_frame(&c, 200.0, 0);
    check(!plans && !c.running, "catch-up: none within a frame, nor while not allowed (a panel, no refresh known)");
    /* A median of five: one reading over a frame among four within is no catch-up. */
    catchup_start(&c);
    plans = catchup_frame(&c, 5.0, 1) + catchup_frame(&c, 90.0, 1) + catchup_frame(&c, 4.0, 1) +
            catchup_frame(&c, 6.0, 1) + catchup_frame(&c, 5.0, 1);
    check(!plans, "catch-up: one reading over a frame among five is not a stall");
    /* A frame after a skip too late: five seconds of none, and none for the song after three. */
    catchup_start(&c);
    for (int i = 0; i < 5; i++)
        catchup_frame(&c, 60.0, 1);
    catchup_skipped(&c);
    catchup_after(&c, 0);
    plans = 0;
    for (int i = 0; i < CATCHUP_REST - 1; i++)
        plans += catchup_frame(&c, 60.0, 1);
    check(!plans && catchup_frame(&c, 60.0, 1), "catch-up: a frame after a skip too late rests it five seconds");
    catchup_after(&c, 0);
    catchup_after(&c, 0);
    plans = 0;
    for (int i = 0; i < 2 * CATCHUP_REST; i++)
        plans += catchup_frame(&c, 60.0, 1);
    check(!plans && c.late_song == CATCHUP_LATE, "catch-up: three too late in a song, none for the rest of it");
    /* A reset of the device in the song: the readings start again, the song's frames too late kept (it goes on). */
    catchup_pause(&c);
    plans = 0;
    for (int i = 0; i < 2 * CATCHUP_REST; i++)
        plans += catchup_frame(&c, 60.0, 1);
    check(!plans && c.late_song == CATCHUP_LATE && c.n == CATCHUP_READINGS,
          "catch-up: a reset in the song keeps its three too late (none left unshown after it either)");
    /* The refresh the skipped frame would have had: the first after its tick by the display's phase now; with no
     * phase, three eighths of a refresh after the tick. The next frame's work must end an eighth of one before it. */
    const int64_t r60 = f / 60;
    check(llabs(catchup_deadline(0, 4 * ms, r60, 0.26) - (4 * ms + (int64_t)(0.5 * CATCHUP_VISIBLE * r60))) <= 2,
          "catch-up: the refresh after the tick by the display's phase now");
    check(llabs(catchup_deadline(10 * ms, 4 * ms, r60, 0.5) - (10 * ms + (int64_t)(0.5 * CATCHUP_VISIBLE * r60))) <= 2 &&
              catchup_deadline(0, 4 * ms, r60, -1.0) == 4 * ms + r60 * 3 / 8,
          "catch-up: after now when the frame came past its tick; three eighths with no phase");
    check(catchup_work(6 * ms, 2 * ms) == 8 * ms && catchup_work(6 * ms, 0) == 6 * ms && catchup_work(-1, -1) == 0,
          "catch-up: the next frame's work, then its chain on the GPU when timed");
    check(catchup_fits(0, 0, 10 * ms, 10 * ms - r60 / 8, r60) && !catchup_fits(0, 0, 10 * ms, 10 * ms - r60 / 8 + 1, r60) &&
              !catchup_fits(0, 0, 10 * ms, ms, 0), "catch-up: the next frame's work must end an eighth of a refresh before");
    check(!catchup_fits(0, 10 * ms - r60 / 8 + 1, 10 * ms, ms, r60),
          "catch-up: nor may the tick it takes over be later (a tick the display lock could not keep mid-refresh)");
    /* Songs on displays, a stall of 100 ms 20 s in and one of 400 ms 60 s in: the game's work 2.5 to 3.5 ms. */
    const double at[2] = {20.0, 60.0}, stalls[2] = {100.0, 400.0}, none[2] = {0.0, 0.0};
    /* As before, at 60 Hz with VSync: the frames shown stay behind the music after the first stall. */
    CatchSong before = catch_song(60, f / 60, 0, 25000, 10000, 2500, 2500, at, stalls, 0, 90, 0);
    check(before.skips == 0 && before.caught[0] < 0 && before.end_behind > 450.0,
          "catch-up: as before, at 60 Hz with VSync the frames stay 500 ms behind the music after the two stalls");
    CatchSong s60 = catch_song(60, f / 60, 0, 25000, 10000, 2500, 2500, at, stalls, 1, 90, 0);
    printf("catch-up 60 Hz: caught %.2f s and %.2f s, %d left unshown (%d late, %d not fitting), closest %d, in a row "
           "%d, %d shown twice, between them %.1f to %.1f ms, end %.1f ms, %d lines, the first from %.1f ms in %d\n",
           s60.caught[0], s60.caught[1], s60.skips, s60.late, s60.unfit, s60.closest, s60.in_a_row, s60.repeats,
           s60.low, s60.high, s60.end_behind, s60.lines, s60.first_from, s60.first_skips);
    check(s60.caught[0] >= 0 && s60.caught[0] < 1.5 && s60.caught[1] >= 0 && s60.caught[1] < 4.0,
          "catch-up: at 60 Hz with VSync, 100 ms won back within 1.5 s and 400 ms within 4 s");
    check(s60.in_a_row == 1 && s60.closest >= CATCHUP_SPACING && s60.late == 0 && s60.outside == 0,
          "catch-up: never two frames unshown in a row, five shown between, none late, none before the first stall");
    /* Outside a song's music lock: a stall of 400 ms on the menus, 5 s before the music starts, leaves nothing unshown
     * (the song's lock starts on its own music, after it). */
    const double menus_at[2] = {-5.0, 0.0}, menus_ms[2] = {400.0, 0.0};
    CatchSong menus = catch_song(60, f / 60, 0, 25000, 10000, 2500, 2500, menus_at, menus_ms, 1, 30, 0);
    check(menus.skips == 0 && menus.end_behind > -10.0 && menus.end_behind < 1000.0 / 60.0 + 10.0,
          "catch-up: none outside a song's music lock (a stall on the menus before the song)");
    /* Between catch-ups (before the first stall and from 6 s after each): a band one frame wide and the few ms the
     * median reads of the sound card's 10 ms steps, never a step past a frame behind nor a step ahead (the lock's
     * reading of the song's start is one step's too). */
    const double frame = 1000.0 / 60.0;
    check(s60.high - s60.low < frame + 5.0 && s60.low > -10.0 && s60.high < frame + 10.0 && s60.lines >= 2 &&
              s60.repeats == 0, "catch-up: between catch-ups within a frame's band of the music, no frame shown twice, "
                                "a line for each");
    CatchSong q60 = catch_song(60, f / 60, 1, 25000, 10000, 2500, 2500, at, stalls, 1, 90, 0);
    printf("catch-up 60 Hz queued: caught %.2f s and %.2f s, %d left unshown (%d late), %d shown twice, between them "
           "%.1f to %.1f ms\n", q60.caught[0], q60.caught[1], q60.skips, q60.late, q60.repeats, q60.low, q60.high);
    check(q60.caught[0] >= 0 && q60.caught[0] < 1.5 && q60.caught[1] >= 0 && q60.caught[1] < 4.0 && q60.late == 0 &&
              q60.in_a_row == 1 && q60.high - q60.low < frame + 5.0 && q60.repeats == 0,
          "catch-up: the same with Direct3D's queue of one frame");
    /* With an audio offset (the lock's target 80 ms behind the music): reached as before, the stalls won back the same. */
    CatchSong o60 = catch_song(60, f / 60, 0, 25000, 10000, 2500, 2500, at, stalls, 1, 90, 80.0);
    printf("catch-up 60 Hz, 80 ms offset: caught %.2f s and %.2f s, %d left unshown (%d late), end %.1f ms past it\n",
           o60.caught[0], o60.caught[1], o60.skips, o60.late, o60.end_behind);
    check(o60.caught[0] >= 0 && o60.caught[0] < 1.5 && o60.caught[1] >= 0 && o60.caught[1] < 4.0 && o60.late == 0 &&
              o60.end_behind > -10.0 && o60.end_behind < frame + 10.0,
          "catch-up: with an audio offset of 80 ms, its target, the stalls won back the same");
    /* 59.94 Hz (Windows says 59): the frames fall a millisecond a second behind with no stall at all. */
    CatchSong s59 = catch_song(59, f * 1001 / 60000, 0, 25000, 10000, 2500, 2500, at, none, 1, 120, 0);
    printf("catch-up 59.94 Hz: %d left unshown, %d shown twice, %.1f to %.1f ms, end %.1f ms\n", s59.skips,
           s59.repeats, s59.low, s59.high, s59.end_behind);
    CatchSong old59 = catch_song(59, f * 1001 / 60000, 0, 25000, 10000, 2500, 2500, at, none, 0, 120, 0);
    check(s59.skips >= 5 && s59.high - s59.low < frame + 5.0 && s59.high < frame + 10.0 && s59.repeats == 0 &&
              old59.end_behind > 100.0,
          "catch-up: at 59.94 Hz the frames kept within a frame's band for two minutes (120 ms behind before)");
    /* Displays that take frames sooner: nothing left unshown, the lock's own steps win the stalls back. */
    static const int rates[3] = {120, 144, 240};
    int none_left = 1, won = 1;
    for (int i = 0; i < 3; i++) {
        CatchSong r = catch_song(rates[i], f / rates[i], 0, 25000, 10000, 2500, 2500, at, stalls, 1, 90, 0);
        none_left &= r.skips == 0;
        won &= r.caught[0] >= 0 && r.caught[0] < 4.0 && r.caught[1] >= 0 && r.caught[1] < 6.0;
        printf("catch-up %d Hz: caught %.2f s and %.2f s, end %.1f ms\n", rates[i], r.caught[0], r.caught[1],
               r.end_behind);
    }
    CatchSong off = catch_song(60, 0, 0, 25000, 10000, 2500, 2500, at, stalls, 1, 90, 0);
    printf("catch-up VSync off: caught %.2f s and %.2f s, end %.1f ms\n", off.caught[0], off.caught[1], off.end_behind);
    check(none_left && off.skips == 0, "catch-up: nothing left unshown at 120, 144 and 240 Hz, nor with VSync off");
    check(won && off.caught[0] >= 0 && off.caught[1] >= 0, "catch-up: there the lock's own steps win both stalls back");
    /* Slower PCs, the present waiting for its refresh: 6 ms of work a frame still wins both back; at 9 ms two frames'
     * work does not fit before a refresh, and nothing is left unshown that would miss it. */
    CatchSong six = catch_song(60, f / 60, 0, 55000, 5000, 2500, 2500, at, stalls, 1, 90, 0);
    CatchSong slow = catch_song(60, f / 60, 0, 90000, 5000, 2500, 2500, at, stalls, 1, 90, 0);
    printf("catch-up 60 Hz, 6 ms of work: caught %.2f s and %.2f s, %d late; 9 ms: %d left unshown, %d late, %d not "
           "fitting, end %.1f ms\n", six.caught[0], six.caught[1], six.late, slow.skips, slow.late, slow.unfit,
           slow.end_behind);
    check(six.caught[0] >= 0 && six.caught[0] < 1.5 && six.caught[1] >= 0 && six.caught[1] < 4.0 && six.late == 0,
          "catch-up: 6 ms of work a frame still wins both stalls back");
    check(slow.late == 0 && slow.repeats == 0,
          "catch-up: a frame's work too long for two in a refresh: no frame left unshown to miss it, none shown twice");
    /* A heavy GPU: the chain's 6 ms a frame, which its timestamps time, after 2 ms of the game's own draws: both stalls
     * still won back. The game's own draws at 6 ms a frame, which nothing times: the frames after the first skips have
     * their pictures too late for their refresh, and after three of them none is left unshown in the song. */
    CatchSong chain = catch_song(60, f / 60, 0, 25000, 10000, 20000, 60000, at, stalls, 1, 90, 0);
    CatchSong game = catch_song(60, f / 60, 0, 25000, 10000, 60000, 10000, at, stalls, 1, 90, 0);
    printf("catch-up 60 Hz, the chain's 6 ms on the GPU: caught %.2f s and %.2f s, %d late; the game's own 6 ms: %d left "
           "unshown, %d late, %d shown twice\n", chain.caught[0], chain.caught[1], chain.late, game.skips, game.late,
           game.repeats);
    check(chain.caught[0] >= 0 && chain.caught[0] < 1.5 && chain.caught[1] >= 0 && chain.caught[1] < 4.0 &&
              chain.late == 0 && chain.repeats == 0, "catch-up: the chain's 6 ms on the GPU, timed: both stalls won back");
    check(game.late <= CATCHUP_LATE && game.skips <= CATCHUP_LATE && game.repeats == 0,
          "catch-up: the game's own 6 ms on the GPU, untimed: three frames too late, then none left unshown in the song");
    /* 50 Hz: the 60 frames a second of the game on 50 refreshes take one frame in six left unshown by themselves. The
     * frames are kept from falling behind (as before, 167 ms a second), but a stall's distance stays. */
    CatchSong s50 = catch_song(50, f / 50, 0, 25000, 10000, 2500, 2500, at, none, 1, 90, 0);
    CatchSong old50 = catch_song(50, f / 50, 0, 25000, 10000, 2500, 2500, at, none, 0, 90, 0);
    printf("catch-up 50 Hz: %d left unshown, %.1f ms behind at the end (%.0f ms before), %d late, %d in a row at most\n",
           s50.skips, s50.end_behind, old50.end_behind, s50.late, s50.in_a_row);
    check(s50.end_behind < 100.0 && s50.high < 100.0 && old50.end_behind > 10000.0 && s50.late == 0 &&
              s50.in_a_row == 1, "catch-up: at 50 Hz the frames kept within 100 ms of the music (18 s behind before)");
}

/* The display lock: a tick late in its refresh moves earlier, early moves later, the middle stays. */
static void test_display_lock(void)
{
    check(display_lock_step(0.5, 41666) == 0 && display_lock_step(-1, 41666) == 0, "display lock: the middle stays");
    check(display_lock_step(0.95, 41666) < 0 && display_lock_step(0.05, 41666) > 0,
          "display lock: an edge moves the tick to the middle");
    check(display_lock_step(1.0, 41666) >= -41666 / 64 - 1, "display lock: at most a 64th of a refresh a frame");
}

/* The safety net: frames late by the chain's doing step it down; a load of the game's own does not. */
static void test_guard(void)
{
    Guard g;
    guard_start(&g);
    int steps = 0;
    for (int i = 0; i < 600 + 120; i++)
        steps += guard_frame(&g, 30.0, 20.0);
    check(steps == 1, "guard: 60 frames made late by the chain step it down once");
    guard_start(&g);
    steps = 0;
    for (int i = 0; i < 600; i++)
        steps += guard_frame(&g, 30.0, 20.0);
    check(steps == 0, "guard: the game's first 10 s of loading are not counted");
    guard_start(&g);
    steps = 0;
    for (int i = 0; i < 600 + 240; i++)
        steps += guard_frame(&g, (i / 60) % 2 ? 30.0 : 16.67, 20.0);
    check(steps == 0, "guard: a late second between good ones is not the chain's cost");
    guard_start(&g);
    steps = 0;
    for (int i = 0; i < 300; i++)
        steps += guard_frame(&g, i % 60 == 0 ? 500.0 : 16.67, 3.0);
    check(steps == 0, "guard: a load of the game's own with a light chain is not the chain");
    guard_start(&g);
    steps = 0;
    for (int i = 0; i < 300; i++)
        steps += guard_frame(&g, 16.67, 12.0);
    check(steps == 0, "guard: a heavy chain within the budget stays");
    guard_start(&g);
    steps = 0;
    for (int i = 0; i < 300; i++)
        steps += guard_frame(&g, 30.0, -1);
    check(steps == 0, "guard: no reading of the chain's time, no step");
    /* Motion clarity at 240 Hz: frames shown over four presents run late by the sub-frames' wait (the game's next frame
     * has one refresh), with the chain's time light enough that they would not be late without it: never judged, so
     * never a step; the same frames shown whole are the chain's doing and step it down. */
    guard_start(&g);
    steps = 0;
    for (int i = 0; i < 600 + 240; i++)
        steps += guard_frame_shown(&g, 18.5, 2.5, 4);
    int shown_over = steps;
    guard_start(&g);
    steps = 0;
    for (int i = 0; i < 600 + 240; i++)
        steps += guard_frame_shown(&g, 18.5, 2.5, 1);
    check(shown_over == 0 && steps >= 1, "guard: frames shown over motion clarity's sub-frames are not judged");
    int up = UPSCALE_NIS, aa = AA_SMAA_ULTRA, n = 0;
    while (post_lighter(&up, &aa))
        n++;
    check(n == 3 && up == UPSCALE_SMOOTH && aa == AA_OFF, "guard: SMAA to FXAA to off, then NIS to bilinear");
    up = UPSCALE_ANIME4K;
    aa = AA_OFF;
    check(post_lighter(&up, &aa) && up == UPSCALE_SMOOTH, "guard: Anime4K steps down to bilinear");
    up = UPSCALE_OFF;
    aa = AA_OFF;
    check(!post_lighter(&up, &aa), "guard: nearest is as light as it goes");
    char words[160];
    note_words(0, 1, AA_FXAA, words, sizeof words);
    check(!strcmp(words, "Picture quality lowered to keep 60 FPS: now FXAA"),
          "guard: the note says why, then what the picture is now (never in brackets, read as a cause)");
    note_words(1, 0, AA_OFF, words, sizeof words);
    check(!strcmp(words, "60 FPS를 지키려고 화질을 낮췄습니다. 지금은 부드럽게 확대"), "guard: the note in Korean");
    Settings s;
    settings_default(&s);
    settings_read(&s, "OPENDMT3_PACING", "music");
    check(s.music_lock && s.even_pacing, "settings: music pacing is even pacing led by the music");
    settings_read(&s, "OPENDMT3_PACING", "even");
    check(!s.music_lock && s.even_pacing, "settings: even pacing alone");
}

/* The list of openDMT3's files in the game's place (redirect.c): what it reads, what it matches, what it refuses. */
static void test_redirect(void)
{
    static Redirects rs;
    const char *list = "\xEF\xBB\xBF# openDMT3's files\r\n"
                       "Resource\\config\\setting.ini\tsetting.ini\r\n"
                       "TECHNIKA\\\tTECHNIKA\\\r\n"
                       "pack\\Config.pak\tpack\\Config.pak\n\n";
    /* openDMT3's folder under a user name outside the ANSI code page (Hangul). */
    check(redirect_parse(&rs, L"D:\\Games\\DMT3\\", L"C:\\Users\\\xD64D\\AppData\\openDMT3\\game", list, strlen(list)) == 3,
          "files: the list's three lines read");
    check(rs.r[0].to[9] == 0xD64D, "files: a folder outside the ANSI code page kept whole");
    wchar_t out[REDIRECT_PATH];
    check(redirect_lookup(&rs, L"D:\\Games\\DMT3\\Resource\\config\\setting.ini", out, REDIRECT_PATH) &&
              !wcscmp(out, L"C:\\Users\\\xD64D\\AppData\\openDMT3\\game\\setting.ini"),
          "files: the settings served from openDMT3's folder");
    check(redirect_lookup(&rs, L"d:\\games\\dmt3\\resource\\CONFIG\\Setting.INI", out, REDIRECT_PATH),
          "files: names matched without letter case");
    check(redirect_lookup(&rs, L"D:\\Games\\DMT3\\pack//Config.pak", out, REDIRECT_PATH) &&
              !wcscmp(out, L"C:\\Users\\\xD64D\\AppData\\openDMT3\\game\\pack\\Config.pak"),
          "files: the game's own double slash read as one, openDMT3's file named from the DLL's folder");
    check(redirect_lookup(&rs, L"D:\\Games\\DMT3\\TECHNIKA\\RANK\\New", out, REDIRECT_PATH) &&
              !wcscmp(out, L"C:\\Users\\\xD64D\\AppData\\openDMT3\\game\\TECHNIKA\\RANK\\New"),
          "files: a file the game makes in the operator data goes to openDMT3's folder, its name as the game spelled it");
    check(redirect_lookup(&rs, L"D:\\Games\\DMT3\\technika", out, REDIRECT_PATH) &&
              !wcscmp(out, L"C:\\Users\\\xD64D\\AppData\\openDMT3\\game\\TECHNIKA"),
          "files: the operator data's folder itself");
    check(redirect_lookup(&rs, L"D:\\Games\\DMT3\\TECHNIKA\\", out, REDIRECT_PATH), "files: the folder with its backslash");
    out[0] = L'x';
    check(!redirect_lookup(&rs, L"D:\\Games\\DMT3\\pack\\DiscInfo.pak", out, REDIRECT_PATH) && out[0] == L'x',
          "files: the game's own files untouched");
    check(!redirect_lookup(&rs, L"D:\\Games\\DMT3x\\pack\\Config.pak", out, REDIRECT_PATH) &&
              !redirect_lookup(&rs, L"D:\\Games\\pack\\Config.pak", out, REDIRECT_PATH) &&
              !redirect_lookup(&rs, L"D:\\Games\\DMT3", out, REDIRECT_PATH),
          "files: nothing outside the game folder");
    check(!redirect_lookup(&rs, L"D:\\Games\\DMT3\\TECHNIKAX\\a", out, REDIRECT_PATH),
          "files: a folder only named alike is not the operator data");
    check(!redirect_lookup(&rs, L"D:\\Games\\DMT3\\pack\\Config.pak", out, 8), "files: no answer that does not fit");
    /* What the launcher never writes: refused whole, so the game reads its own files as it is. */
    check(redirect_parse(&rs, L"D:\\G", L"C:\\o", "a.ini C:\\x\n", 11) == -1, "files: a line without a tab refused");
    check(redirect_parse(&rs, L"D:\\G", L"C:\\o", "..\\a.ini\tC:\\x\n", 14) == -1, "files: a path leaving the game folder refused");
    check(redirect_parse(&rs, L"D:\\G", L"C:\\o", "C:\\a.ini\tC:\\x\n", 14) == -1, "files: an absolute path on the left refused");
    check(redirect_parse(&rs, L"D:\\G", L"C:\\o", "a.ini\tC:\\x\n", 9) == -1 &&
              redirect_parse(&rs, L"D:\\G", L"C:\\o", "a.ini\t\\\\server\\x\n", 15) == -1 &&
              redirect_parse(&rs, L"D:\\G", L"C:\\o", "a.ini\t\\x\n", 9) == -1,
          "files: a whole path on the right refused: nothing outside the game folder and openDMT3's");
    check(redirect_parse(&rs, L"D:\\G", L"C:\\o", "a.ini\t<game>\\..\\x\n", 18) == -1 &&
              redirect_parse(&rs, L"D:\\G", L"C:\\o", "a.ini\t<game>\\C:\\x\n", 18) == -1,
          "files: a path from the game folder that leaves it refused");
    const char *kept = "pack\\c.pak\t<game>\\backup\\pack\\c.pak\n";
    check(redirect_parse(&rs, L"D:\\G\\", L"C:\\o", kept, strlen(kept)) == 1 &&
              redirect_lookup(&rs, L"D:\\G\\pack\\c.pak", out, REDIRECT_PATH) && !wcscmp(out, L"D:\\G\\backup\\pack\\c.pak"),
          "files: an original kept in the game folder's backup named from the game folder");
    check(redirect_parse(&rs, L"D:\\G", L"C:\\o", "a.ini\t..\\x\n", 11) == -1, "files: a path on the right leaving the DLL's folder refused");
    check(redirect_parse(&rs, L"D:\\G", L"C:\\o", "a.ini\tx\xC3\n", 9) == -1, "files: bytes that are not UTF-8 refused");
    check(redirect_parse(&rs, L"D:\\G", L"C:\\o", "", 0) == 0 && !redirect_lookup(&rs, L"D:\\G\\a", out, REDIRECT_PATH),
          "files: an empty list serves nothing");
    wchar_t w[8];
    check(redirect_utf8("\xF0\x9F\x8E\xB5", 4, w, 8) == 2 && w[0] == 0xD83C && w[1] == 0xDFB5,
          "files: a character past the BMP as a surrogate pair");
}

/* "Off" (sharp bilinear) on one row: every input pixel's share of the output adds up to the same width (output over
 * input pixels), whole multiples of the size give nearest exactly, an output pixel wholly inside an input one reads
 * its centre, and each output pixel mixes at most two neighbours. The game's 1280 columns at 1800 (16:9 with the
 * game's shape kept), 1920 (filled), 1280 and 2560; and 768 rows at 1080. */
static void test_sharp(void)
{
    static const int sizes[][2] = {{1280, 1800}, {1280, 1920}, {1280, 1280}, {1280, 2560}, {768, 1080}};
    int uneven = 0, wrong_inside = 0, not_nearest = 0, far = 0;
    for (int k = 0; k < 5; k++) {
        int n = sizes[k][0], m = sizes[k][1];
        float scale = (float)m / (float)n;
        static double share[4096];
        memset(share, 0, sizeof share);
        for (int j = 0; j < m; j++) {
            float t = ((float)j + 0.5f) * (float)n / (float)m;
            float c = sharp_coord(t, scale);
            /* Bilinear between the texels whose centres are either side of c. */
            float u = c - 0.5f;
            int i = (int)floorf(u);
            float f = u - (float)i;
            if (i >= 0)
                share[i] += 1.0 - f;
            if (i + 1 < n)
                share[i + 1] += f;
            /* Wholly inside its texel: read at that texel's centre. */
            float lo = ((float)j) * (float)n / (float)m, hi = ((float)j + 1.0f) * (float)n / (float)m;
            if (floorf(lo) == floorf(hi - 1e-4f) && fabsf(c - (floorf(t) + 0.5f)) > 1e-4f)
                wrong_inside++;
            /* Whole multiples: nearest itself (no mix at all). */
            if (m % n == 0 && f > 1e-4f && f < 1.0f - 1e-4f)
                not_nearest++;
            /* Never further than the next texel. */
            if (fabsf(c - t) > 1.0f)
                far++;
        }
        /* The first and last texels lie against the picture's edge: the rest each the same width. */
        for (int i = 1; i < n - 1; i++)
            if (fabs(share[i] - scale) > 2e-3)
                uneven++;
    }
    check(!uneven, "sharp: every game pixel the same width on the screen (1800, 1920, 1280, 2560 columns, 1080 rows)");
    check(!wrong_inside, "sharp: a screen pixel wholly inside a game pixel shows exactly it");
    check(!not_nearest, "sharp: whole multiples of the game's size are nearest itself");
    check(!far, "sharp: each screen pixel mixes at most two neighbouring game pixels");
}

/* The picture's place and the game's pointer: at 16:9, 21:9, 16:10, 5:4, the game's own 5:3 and windows of other
 * shapes, kept and filled, every client pixel inside the picture handed to the display fix's sums lands on the game
 * pixel under that pixel's centre; the picture's rectangle has the game's shape within a pixel and is centred. */
static void test_picture(void)
{
    static const int sizes[][2] = {{1920, 1080}, {2560, 1080}, {3440, 1440}, {1920, 1200}, {1280, 1024}, {1280, 768},
                                   {3840, 2160}, {1350, 810}, {1600, 900}, {1024, 768}, {800, 600}, {1366, 768}};
    int shape = 0, centred = 0, off = 0, outside_in = 0, checked = 0;
    for (int k = 0; k < 12; k++) {
        int cw = sizes[k][0], ch = sizes[k][1];
        for (int fill = 0; fill < 2; fill++) {
            PicRect r = picture_rect(cw, ch, fill);
            /* Kept: 5:3 within a pixel, and the bars on two sides only, the same on both. */
            if (!fill && (fabs((double)r.w * GAME_H - (double)r.h * GAME_W) > GAME_W || (r.x && r.y)))
                shape++;
            if (abs((cw - r.w) - 2 * r.x) > 1 || abs((ch - r.h) - 2 * r.y) > 1 || r.x < 0 || r.y < 0)
                centred++;
            /* Every pixel of the picture (every 7th row and column, and the edges). */
            for (int py = r.y; py < r.y + r.h; py += (py - r.y) % 7 || py == r.y + r.h - 1 ? 1 : 7) {
                for (int px = r.x; px < r.x + r.w; px += (px - r.x) % 7 || px == r.x + r.w - 1 ? 1 : 7) {
                    int qx, qy, gx, gy;
                    pointer_for_game(px, py, cw, ch, r, &qx, &qy);
                    game_from_client(qx, qy, cw, ch, &gx, &gy);
                    int wx = (int)floor((px - r.x + 0.5) * GAME_W / r.w), wy = (int)floor((py - r.y + 0.5) * GAME_H / r.h);
                    /* A client smaller than the game cannot reach every game pixel: within one there. */
                    int slack = cw < GAME_W || ch < GAME_H;
                    if (abs(gx - wx) > slack || abs(gy - wy) > slack)
                        off++;
                    checked++;
                }
            }
            /* A bar's pixel lands outside the game's picture. */
            if (r.x > 0) {
                int qx, qy, gx, gy;
                pointer_for_game(r.x - 1, r.y + r.h / 2, cw, ch, r, &qx, &qy);
                game_from_client(qx, qy, cw, ch, &gx, &gy);
                if (gx >= 0)
                    outside_in++;
            }
        }
    }
    PicRect a = picture_rect(1920, 1080, 0), b = picture_rect(1920, 1200, 0), c = picture_rect(2560, 1080, 0),
            d = picture_rect(1280, 1024, 0);
    check(a.x == 60 && a.w == 1800 && a.h == 1080 && b.y == 24 && b.h == 1152 && c.x == 380 && d.y == 128 && d.h == 768,
          "picture: kept at 16:9 1800x1080 at 60, at 16:10 1920x1152 at 24 down, at 21:9 at 380, at 5:4 768 at 128 down");
    check(!shape && !centred, "picture: kept, the game's 5:3 within a pixel, centred, bars on two sides only");
    check(!off && checked > 100000, "picture: every client pixel inside the picture reaches the game pixel under its "
                                    "centre through the display fix's sums, kept and filled, 12 screen shapes");
    check(!outside_in, "picture: a bar's pixel left of the picture lands left of the game's picture");
}

/* ------------------------------------------------------------------------------------------- the touch screen */

/* What the game holds of a read, as its point reader keeps it (the client's FUN_0070efa0 with the touch screen open):
 * its points in its own pixels, their count, and its flags, of which the notes take a press from `pressed` (its
 * touching began) or `new_finger` (with several touches, the count grew). */
typedef struct {
    int x[100], y[100];
    int count;
    int touching, pressed, several, new_finger;
    uint32_t sum;          /* the last read's groups and points added up (the game's own 0x199fae0c) */
} GameTouch;

/* Little-endian numbers back out of the buffer, as the game's x86 reads them. */
static uint32_t get32(const uint8_t *at)
{
    return (uint32_t)at[0] | (uint32_t)at[1] << 8 | (uint32_t)at[2] << 16 | (uint32_t)at[3] << 24;
}

static uint32_t get16(const uint8_t *at)
{
    return (uint32_t)at[0] | (uint32_t)at[1] << 8;
}

/* The game's reader, step by step as the client does it after WaitNexioMulti answered `result` (its comparisons are
 * of unsigned numbers). */
static void game_reads(GameTouch *g, const uint8_t *b, int result)
{
    /* Each read starts with no point and no new press. */
    g->count = 0;
    g->pressed = g->new_finger = 0;
    uint32_t h0 = get32(b), h1 = get32(b + 4), h2 = get32(b + 8), h3 = get32(b + 12);
    if (result == 2 || h0 == 0) {
        /* Nothing on the screen: touching ends (an answer of 2 with something said leaves everything as it was). */
        if (h0 == 0) {
            g->touching = g->several = 0;
            g->sum = h2 + h3;
        }
        return;
    }
    if (!g->touching)
        g->pressed = 1;
    g->touching = 1;
    if (h1 > 1) {
        g->several = 1;
        if (g->sum < h2 + h3)
            g->new_finger = 1;
    }
    g->sum = h2 + h3;
    /* Groups times points, 100 at most, each turned back by the game. */
    for (uint32_t c = 0; c < h2; c++)
        for (uint32_t p = 0; p < h3 && g->count < 100; p++, g->count++) {
            g->x[g->count] = 0x500 - (int)get16(b + 0x10 + c * 0x960 + p * 0x18 + 0xc);
            g->y[g->count] = 0x300 - (int)get16(b + 0x10 + c * 0x960 + p * 0x18 + 0xe);
        }
}

/* A note's press as the game judges it: the flags its note judge reads (FUN_00532af0). */
static int game_press(const GameTouch *g)
{
    return g->pressed || g->new_finger;
}

/* Whether the game holds a point at (x, y) this read. */
static int game_has(const GameTouch *g, int x, int y)
{
    for (int i = 0; i < g->count; i++)
        if (g->x[i] == x && g->y[i] == y)
            return 1;
    return 0;
}

/* Whether a point lies on the game's screen (its lanes and boxes take nothing else: FUN_00514740). */
static int game_on_screen(int x, int y)
{
    return x >= 0 && x <= 1280 && y >= 0 && y <= 768;
}

/* The points the game holds on its screen this read. */
static int game_on_screen_count(const GameTouch *g)
{
    int n = 0;
    for (int i = 0; i < g->count; i++)
        n += game_on_screen(g->x[i], g->y[i]);
    return n;
}

/* One frame: openDMT3's read into a buffer of the game's size, then the game's own reading of it; the frames' clock
 * (ms) moves on by a frame. */
static uint8_t g_touch_buffer[TOUCH_BUFFER];
static double g_now = 1000.0;
static void frame_read(Contacts *t, GameTouch *g, int hold)
{
    /* The game's buffer keeps what the last read left in it, as the game's own does. */
    contacts_read(t, hold, g_touch_buffer, sizeof g_touch_buffer, g_now);
    game_reads(g, g_touch_buffer, 0);
    g_now += 1000.0 / 60.0;
}

static void test_touch(void)
{
    Contacts t;
    GameTouch g;
    /* The buffer as the game makes it: 16 bytes of head and 100 groups of 100 points. */
    check(TOUCH_BUFFER == TOUCH_HEAD + 100 * TOUCH_GROUP && TOUCH_GROUP == 100 * TOUCH_POINT,
          "touch: the buffer is the game's 0x3A990 bytes, a head and 100 groups of 100 points of 24 bytes");

    /* One finger: a press, held, let go. */
    contacts_start(&t);
    memset(&g, 0, sizeof g);
    contacts_down(&t, 7, 100, 600, 0);
    frame_read(&t, &g, 0);
    int pressed = game_press(&g) && g.count == 1 && g.x[0] == 100 && g.y[0] == 600;
    /* The point as the frame's program wrote it: turned on both axes. */
    int turned = get16(g_touch_buffer + TOUCH_HEAD + TOUCH_X) == 1180 && get16(g_touch_buffer + TOUCH_HEAD + TOUCH_Y) == 168
                 && get32(g_touch_buffer) == 1 && get32(g_touch_buffer + 8) == 1 && get32(g_touch_buffer + 12) == 1;
    frame_read(&t, &g, 0);
    int held = !game_press(&g) && g.touching && g.count == 1;
    contacts_move(&t, 7, 120, 610);
    frame_read(&t, &g, 0);
    int moved = !game_press(&g) && g.count == 1 && g.x[0] == 120 && g.y[0] == 610;
    contacts_up(&t, 7, g_now);
    frame_read(&t, &g, 0);
    check(pressed && held && moved && !g.touching && g.count == 0 && t.n == 0,
          "touch: one finger is a press, held as it moves, and let go");
    check(turned, "touch: a point is written turned as the touch frame's program wrote it (1280 - x, 768 - y), so the "
                  "game's own turn puts it back under the finger");

    /* A second finger while the first holds: a new press, the first still held and still the game's first point. */
    contacts_start(&t);
    memset(&g, 0, sizeof g);
    contacts_down(&t, 1, 200, 500, 0);
    frame_read(&t, &g, 0);
    contacts_down(&t, 2, 900, 500, 0);
    frame_read(&t, &g, 0);
    check(g.new_finger && g.count == 2 && g.x[0] == 200 && g.x[1] == 900 && g.several,
          "touch: a second finger while the first holds is a new press, the first still held and the first point");

    /* A held note through taps elsewhere: every read has the held finger where it is, and every tap is a press. */
    contacts_start(&t);
    memset(&g, 0, sizeof g);
    contacts_down(&t, 1, 640, 600, 0);
    frame_read(&t, &g, 0);
    int always_held = 1, every_tap = 1;
    for (int k = 0; k < 20; k++) {
        /* A tap down for a read, then up. */
        contacts_down(&t, 10 + (uint32_t)k % 3, 100 + 50 * k, 500, 0);
        frame_read(&t, &g, 0);
        every_tap &= game_press(&g);
        always_held &= game_has(&g, 640, 600);
        contacts_up(&t, 10 + (uint32_t)k % 3, g_now);
        frame_read(&t, &g, 0);
        always_held &= game_has(&g, 640, 600) && !game_press(&g);
    }
    check(always_held && every_tap,
          "touch: a held finger stays in every read through 20 taps elsewhere, and every tap is a press");

    /* Fingers taking turns, each down in the read the other came up in: still a press each time (the count kept
     * growing by a point off the screen), and the finger that came up gone at once. */
    contacts_start(&t);
    memset(&g, 0, sizeof g);
    contacts_down(&t, 1, 300, 600, 0);
    frame_read(&t, &g, 0);
    int trill = 1, gone = 1, padded_off = 1;
    for (int k = 0; k < 30; k++) {
        uint32_t up = k % 2 ? 2 : 1, down = k % 2 ? 1 : 2;
        int x = k % 2 ? 300 : 340;
        contacts_up(&t, up, g_now);
        contacts_down(&t, down, x, 600, 0);
        frame_read(&t, &g, 0);
        trill &= game_press(&g) && game_has(&g, x, 600);
        gone &= !game_has(&g, k % 2 ? 340 : 300, 600) && game_on_screen_count(&g) == 1;
        for (int i = 0; i < g.count; i++)
            if (!(g.x[i] == x && g.y[i] == 600))
                padded_off &= !game_on_screen(g.x[i], g.y[i]);
    }
    /* Each down in the read the other came up in. */
    check(trill && gone, "touch: two fingers taking turns are a press every time, the one up gone at once (30 turns)");
    /* The next read with no new press: the finger alone again (the count may fall; only a press needs it to grow). */
    frame_read(&t, &g, 0);
    check(padded_off && g.count == 1 && !game_press(&g) && g.touching,
          "touch: the points that make the count grow lie off the game's screen, under nothing, and go at the next read "
          "with no new press");

    /* Two fingers held, one let go and another down in the same read: a press. */
    contacts_start(&t);
    memset(&g, 0, sizeof g);
    contacts_down(&t, 1, 100, 600, 0);
    contacts_down(&t, 2, 200, 600, 0);
    frame_read(&t, &g, 0);
    contacts_up(&t, 2, g_now);
    contacts_down(&t, 3, 300, 600, 0);
    frame_read(&t, &g, 0);
    check(game_press(&g) && game_has(&g, 100, 600) && game_has(&g, 300, 600) && !game_has(&g, 200, 600),
          "touch: of two held, one up and another down in the same read is a press, the other still held");

    /* A tap that comes and goes between two reads: handed once, then gone. */
    contacts_start(&t);
    memset(&g, 0, sizeof g);
    contacts_down(&t, 4, 500, 400, 0);
    contacts_up(&t, 4, g_now);
    frame_read(&t, &g, 0);
    int tap = game_press(&g) && g.count == 1 && g.x[0] == 500;
    frame_read(&t, &g, 0);
    check(tap && !g.touching && t.n == 0, "touch: a tap between two reads is handed to the game once, then gone");

    /* A tap the game had no read for in 250 ms (its menus read nothing): never handed to the read after. */
    contacts_start(&t);
    memset(&g, 0, sizeof g);
    contacts_down(&t, 6, 500, 400, 0);
    contacts_up(&t, 6, g_now);
    g_now += TAP_KEEP_MS + 1;
    frame_read(&t, &g, 0);
    int stale = !g.touching && t.n == 0;
    /* Every place taken by taps not read yet: the oldest makes room for a new finger, which is handed. */
    for (uint32_t k = 0; k < CONTACTS_MOST; k++) {
        contacts_down(&t, 100 + k, 10, 10, 0);
        contacts_up(&t, 100 + k, g_now + k);
    }
    int room = contacts_down(&t, 200, 640, 600, 0) && t.n == CONTACTS_MOST && t.c[0].id == 101;
    frame_read(&t, &g, 0);
    check(stale && room && game_has(&g, 640, 600) && g.count == CONTACTS_MOST,
          "touch: a tap with no read for 250 ms is never handed; old taps make room for a new finger");

    /* Windows gives a new finger the id of a tap the game has not had yet: both handed, apart. */
    contacts_start(&t);
    memset(&g, 0, sizeof g);
    contacts_down(&t, 5, 100, 100, 0);
    contacts_up(&t, 5, g_now);
    contacts_down(&t, 5, 900, 100, 0);
    frame_read(&t, &g, 0);
    int both = g.count == 2 && game_has(&g, 100, 100) && game_has(&g, 900, 100);
    frame_read(&t, &g, 0);
    check(both && g.count == 1 && game_has(&g, 900, 100),
          "touch: a new finger with the id of a tap not read yet: both handed, the tap once");

    /* The overlay's contacts: never the game's, beside the game's own. */
    contacts_start(&t);
    memset(&g, 0, sizeof g);
    contacts_down(&t, 1, 1200, 10, 1);
    frame_read(&t, &g, 0);
    int none = !g.touching && g.count == 0;
    contacts_down(&t, 2, 640, 600, 0);
    frame_read(&t, &g, 0);
    int only_game = g.count == 1 && game_has(&g, 640, 600);
    contacts_up(&t, 1, g_now);
    contacts_move(&t, 1, 600, 600);
    frame_read(&t, &g, 0);
    check(none && only_game && g.count == 1 && t.n == 1, "touch: a contact begun on the overlay never reaches the game");

    /* The overlay takes the contacts down when it answers (its panel closes, a finger asks for the bar): the game sees
     * them come up, and a finger after is the game's. */
    contacts_start(&t);
    memset(&g, 0, sizeof g);
    contacts_down(&t, 1, 640, 600, 0);
    contacts_down(&t, 2, 700, 600, 0);
    frame_read(&t, &g, 0);
    contacts_withhold(&t, 1);
    frame_read(&t, &g, 0);
    int one_taken = g.count == 1 && game_has(&g, 700, 600);
    contacts_withhold(&t, CONTACT_ALL);
    contacts_move(&t, 2, 710, 600);
    frame_read(&t, &g, 0);
    int all_taken = !g.touching;
    contacts_down(&t, 3, 100, 600, 0);
    frame_read(&t, &g, 0);
    check(one_taken && all_taken && game_press(&g) && g.count == 1 && game_has(&g, 100, 600),
          "touch: contacts the overlay takes come up for the game until let go, and a finger after is a press");

    /* While the overlay holds the input (its menu or question up): nothing, and no tap made then comes after. */
    contacts_start(&t);
    memset(&g, 0, sizeof g);
    contacts_down(&t, 1, 640, 600, 0);
    frame_read(&t, &g, 0);
    contacts_up(&t, 1, g_now);
    contacts_down(&t, 2, 300, 300, 0);
    contacts_up(&t, 2, g_now);
    frame_read(&t, &g, 1);
    int held_off = !g.touching;
    frame_read(&t, &g, 0);
    check(held_off && !g.touching && t.n == 0,
          "touch: nothing reaches the game while the overlay holds its input, nor a tap made then, after");

    /* The mouse as one point: a press, held 50 ms past its release as the game holds its button, then up. */
    contacts_start(&t);
    memset(&g, 0, sizeof g);
    g_now = 1000.0;
    contacts_mouse(&t, 1, 400, 300, 1000.0);
    frame_read(&t, &g, 0);
    int mouse_press = game_press(&g) && g.count == 1 && game_has(&g, 400, 300);
    contacts_mouse(&t, 0, 410, 300, 1016.0);
    frame_read(&t, &g, 0);
    int still = g.touching && game_has(&g, 410, 300) && !game_press(&g);
    contacts_mouse(&t, 0, 410, 300, 1049.0);
    frame_read(&t, &g, 0);
    int at_49 = g.touching;
    contacts_mouse(&t, 0, 410, 300, 1050.0);
    frame_read(&t, &g, 0);
    check(mouse_press && still && at_49 && !g.touching,
          "touch: the mouse is one point, held 50 ms past its release as the game holds its button, then up");
    /* Pressed again within the 50 ms: the same press, as in the game's own reading. */
    g_now = 2000.0;
    contacts_mouse(&t, 1, 400, 300, 2000.0);
    frame_read(&t, &g, 0);
    contacts_mouse(&t, 0, 400, 300, 2016.0);
    frame_read(&t, &g, 0);
    contacts_mouse(&t, 1, 400, 300, 2032.0);
    frame_read(&t, &g, 0);
    int same = g.touching && !game_press(&g);
    /* The mouse and two fingers: three points, each finger a press. */
    contacts_down(&t, 1, 100, 700, 0);
    frame_read(&t, &g, 0);
    int first = game_press(&g) && g.count == 2;
    contacts_down(&t, 2, 1100, 700, 0);
    frame_read(&t, &g, 0);
    check(same && first && game_press(&g) && g.count == 3,
          "touch: the mouse pressed again within 50 ms is the same press; with two fingers, three points, each a press");

    /* Ten fingers at once, then more than the contacts kept: the ones past the room are not kept. */
    contacts_start(&t);
    memset(&g, 0, sizeof g);
    for (uint32_t k = 0; k < 10; k++)
        contacts_down(&t, k, 100 + 100 * (int)k, 600, 0);
    frame_read(&t, &g, 0);
    int ten = g.count == 10 && game_press(&g) && g.x[9] == 1000;
    int kept = 1;
    for (uint32_t k = 10; k < CONTACTS_MOST + 5; k++)
        kept &= contacts_down(&t, k, 50, 50, 0) == (k < CONTACTS_MOST);
    frame_read(&t, &g, 0);
    check(ten && kept && g.count == CONTACTS_MOST, "touch: ten fingers are ten points; past the contacts kept, none more");

    /* Past the picture's edges (a finger on a bar): no place on the game's screen. */
    contacts_start(&t);
    memset(&g, 0, sizeof g);
    contacts_down(&t, 1, 1290, 300, 0);
    contacts_down(&t, 2, -40, 300, 0);
    contacts_down(&t, 3, 640, 800, 0);
    contacts_down(&t, 4, 640, -70000, 0);
    frame_read(&t, &g, 0);
    int off = g.count == 4;
    for (int i = 0; i < g.count; i++)
        off &= !game_on_screen(g.x[i], g.y[i]);
    check(off && game_has(&g, -40, 300), "touch: a point past the game's edges never lands on its screen (one before "
                                         "its left edge where it is)");

    /* A buffer too small for the head gets nothing; one too small for every point gets what fits. */
    uint8_t small[TOUCH_HEAD + 2 * TOUCH_POINT + 5];
    memset(small, 0xAB, sizeof small);
    contacts_start(&t);
    for (uint32_t k = 0; k < 5; k++)
        contacts_down(&t, k, 10 * (int)k, 10, 0);
    int handed = contacts_read(&t, 0, small, sizeof small, g_now);
    check(handed == 2 && get32(small + 12) == 2 && small[sizeof small - 1] == 0xAB &&
              contacts_read(&t, 0, small, TOUCH_HEAD - 1, g_now) == 0,
          "touch: never a byte past the buffer it is given");

    /* A finger's game pixel is the pointer's: the same game pixel the display fix's sums give the mouse there. */
    static const int clients[][2] = {{1920, 1080}, {2560, 1440}, {1280, 1024}, {1366, 768}, {3840, 2160}};
    int same_pixel = 1, compared = 0;
    for (int k = 0; k < 5; k++) {
        for (int fill = 0; fill < 2; fill++) {
            int cw = clients[k][0], ch = clients[k][1];
            PicRect r = picture_rect(cw, ch, fill);
            for (int py = r.y; py < r.y + r.h; py += 13)
                for (int px = r.x; px < r.x + r.w; px += 11) {
                    int qx, qy, mx, my, fx, fy;
                    pointer_for_game(px, py, cw, ch, r, &qx, &qy);
                    game_from_client(qx, qy, cw, ch, &mx, &my);
                    game_pixel_under(px, py, r, &fx, &fy);
                    same_pixel &= mx == fx && my == fy;
                    compared++;
                }
        }
    }
    /* Kept and filled, five screen shapes. */
    check(same_pixel && compared > 50000, "touch: a finger reaches the game pixel the mouse reaches at the same place");
}

/* --------------------------------------------------------------------------------- the methods in the tables */

/* A method table as a library keeps one: read-only data of this program's own image (as Direct3D's is in its
 * library's), its methods two made-up functions. */
static int method_real(void) { return 1; }
static int method_ours(void) { return 2; }
static int method_trace(void) { return 3; }
typedef int (*MethodFn)(void);
static MethodFn const g_method_table[20] = {method_real, method_real, method_real, method_real, method_real,
                                            method_real, method_real, method_real, method_real, method_real,
                                            method_real, method_real, method_real, method_real, method_real,
                                            method_real, method_real, method_real, method_real, method_real};

/* An entry of the table as it is now: its address through a pointer kept volatile, so the compiler cannot answer the read
 * from the const table's first values (it did, with the entry's own address cast volatile). */
static void *method_now(int i)
{
    void *const *volatile table = (void *const *)(void *)g_method_table;
    return table[i];
}

static void test_methods(void)
{
    void **present = (void **)(void *)&g_method_table[17], **reset = (void **)(void *)&g_method_table[16];
    /* openDMT3's methods put in, as hooks.c's patch does it, and watched. */
    int written = methods_write(present, (void *)method_ours) && methods_write(reset, (void *)method_ours);
    int watched = methods_watch(present, (void *)method_ours, "Present", 17) &&
                  methods_watch(reset, (void *)method_ours, "Reset", 16);
    MethodBack back[4];
    int noted = -1;
    int quiet = methods_check(back, 4, &noted) == 0 && noted == 0;
    check(written && watched && quiet && method_now(17) == (void *)method_ours,
          "methods: entries openDMT3 turned in a library's table are watched, and a look with them as they are does "
          "nothing");
    /* Direct3D fills its table in again: the real methods back in both entries. */
    methods_write(present, (void *)method_real);
    methods_write(reset, (void *)method_real);
    int n = methods_check(back, 4, &noted);
    /* Each said, the entries beside them left as they are. */
    check(n == 2 && noted == 2 && method_now(17) == (void *)method_ours && method_now(16) == (void *)method_ours &&
              back[0].held == (void *)method_real && back[0].times == 1 && !strcmp(back[0].name, "Present") &&
              back[0].index == 17 && method_now(15) == (void *)method_real,
          "methods: entries Direct3D filled in again are put back as openDMT3's at the next look");
    /* Filled in again and again (every frame): put back each time, said again only at the 10th. */
    int said = 0, every = 1;
    for (int k = 2; k <= 12; k++) {
        methods_write(present, (void *)method_real);
        every &= methods_check(back, 4, &noted) == 1 && method_now(17) == (void *)method_ours;
        said += noted;
    }
    check(every && said == 1, "methods: an entry filled in at every frame is put back every frame, said again only at "
                              "its 10th time");
    /* The trace's method over openDMT3's in the same entry: the newer one is the one kept. */
    methods_write(present, (void *)method_trace);
    int over = methods_watch(present, (void *)method_trace, "the trace's", 17);
    int left = methods_check(back, 4, &noted) == 0;
    methods_write(present, (void *)method_real);
    methods_check(back, 4, &noted);
    check(over && left && method_now(17) == (void *)method_trace,
          "methods: a method of openDMT3's over another in the same entry is the one put back");
    /* A table in the heap (it could go with its object): not watched, so never read after it is freed. */
    void **heap = calloc(20, sizeof(void *));
    check(heap && !methods_watch(&heap[3], (void *)method_ours, "heap", 3),
          "methods: a table outside every module's image is not watched");
    free(heap);
    /* Put back as it was for the rest of the run (no other check reads it). */
    methods_write(present, (void *)method_real);
    methods_write(reset, (void *)method_real);
}

/* The slot index against a plain list of the same keys: random puts and deletions over a small pool of addresses (so
 * keys come back after they went, and clusters form), every key's slot read back after each step. */
static void test_slot_index(void)
{
    static SlotIndex x;
    static int truth[3000];
    memset(&x, 0, sizeof x);
    for (int k = 0; k < 3000; k++)
        truth[k] = -1;
    /* Addresses 16 bytes apart, as heap objects are. */
    char *base = (char *)0x10000000;
    unsigned seed = 12345;
    int wrong = 0, full = 0;
    for (int step = 0; step < 200000; step++) {
        seed = seed * 1103515245u + 12345u;
        int k = (int)((seed >> 8) % 3000);
        const void *key = base + 16 * k;
        if ((seed >> 4) & 1) {
            int slot = (int)(seed >> 20);
            full += !slot_index_put(&x, key, slot);
            truth[k] = slot;
        } else {
            slot_index_del(&x, key);
            truth[k] = -1;
        }
        /* Every 997 steps, every key read back. */
        if (step % 997 == 0)
            for (int j = 0; j < 3000; j++)
                wrong += slot_index_get(&x, base + 16 * j) != truth[j];
    }
    for (int j = 0; j < 3000; j++)
        wrong += slot_index_get(&x, base + 16 * j) != truth[j];
    check(!wrong && !full, "slot index: 200000 random puts and deletions over 3000 keys, every key read back right");
    /* A key never put: -1; deleting it changes nothing. */
    slot_index_del(&x, base + 16 * 5000);
    check(slot_index_get(&x, base + 16 * 5000) == -1, "slot index: a key never put is not found");
}

/* The score's clock (clock.c). openDMT3's read is called the way the client calls its own, from a probe in assembly
 * that first puts known values in every register and known flags (CF, SF and OF set, ZF clear), then keeps what the
 * read left in each: the read may change EDX:EAX alone. */
uint32_t g_probe_flags_in, g_probe_flags_out, g_probe_lo, g_probe_hi, g_probe_ecx, g_probe_ebx, g_probe_esi,
    g_probe_edi, g_probe_ebp, g_probe_esp_in, g_probe_esp_out;
/* What the probe puts in ECX (the score player, where the client's count calls the read). */
uint32_t g_probe_ecx_in = 0x11223344;
void clock_score_read(void);
/* Where the probe's call of the read returns to (as the client's count's call returns to its own place). */
extern const char clock_probe_back[];
__attribute__((naked)) void clock_probe(void)
{
    __asm__(
        "    pushl %ebp\n"
        "    pushl %ebx\n"
        "    pushl %esi\n"
        "    pushl %edi\n"
        /* Known values in every register the read must leave alone, and in the two it gives its result in. */
        "    movl _g_probe_ecx_in, %ecx\n"
        "    movl $0x55667788, %ebx\n"
        "    movl $0x99aabbcc, %esi\n"
        "    movl $0xddeeff00, %edi\n"
        "    movl $0x0badf00d, %ebp\n"
        "    movl $0x7fffffff, %eax\n"
        "    movl $0x9abcdef0, %edx\n"
        /* Flags with something in them: 0x7fffffff + 1 sets SF and OF and clears ZF, then CF set too. */
        "    addl $1, %eax\n"
        "    stc\n"
        "    pushfl\n"
        "    popl _g_probe_flags_in\n"
        "    pushl _g_probe_flags_in\n"
        "    popfl\n"
        "    movl %esp, _g_probe_esp_in\n"
        "    call _clock_score_read\n"
        ".globl _clock_probe_back\n"
        "_clock_probe_back:\n"
        /* What the read left: the flags first (nothing before them changes any). */
        "    pushfl\n"
        "    popl _g_probe_flags_out\n"
        "    movl %esp, _g_probe_esp_out\n"
        "    movl %eax, _g_probe_lo\n"
        "    movl %edx, _g_probe_hi\n"
        "    movl %ecx, _g_probe_ecx\n"
        "    movl %ebx, _g_probe_ebx\n"
        "    movl %esi, _g_probe_esi\n"
        "    movl %edi, _g_probe_edi\n"
        "    movl %ebp, _g_probe_ebp\n"
        "    popl %edi\n"
        "    popl %esi\n"
        "    popl %ebx\n"
        "    popl %ebp\n"
        "    ret\n");
}

/* A score player of this program's own, as the client keeps one (score.c): its table's first word, its tick's length,
 * its count and its start clock. */
static BYTE *fake_score(ULONG *mem, double ms_per_tick, uint32_t count, int64_t start)
{
    BYTE *p = (BYTE *)mem;
    *(ULONG *)p = 0x007689dc;
    *(double *)(p + 0x20) = ms_per_tick;
    *(uint32_t *)(p + 0x30) = count;
    *(int64_t *)(p + 0x38) = start;
    return p;
}

/* The score player's count set back after each update and put back before the next (score.c), on score players of
 * this program's own: what the score counts is never lost, what is shown is the offset's lag behind it, a start or a
 * count the game set itself is kept, and five scores in four places. */
static void test_score_lag(void)
{
    static ULONG mem[5][0x100];
    BYTE *p = fake_score(mem[0], 2.5, 0, 1000);
    score_lag_ms(80);
    uint32_t own = 0, real = 0, shown = 0;
    int lost = 0, wrong = 0;
    for (int k = 0; k < 600; k++) {
        /* The next count: put back first (the clock read at its start), then 4 ticks counted on from it. */
        score_before_count(p);
        lost += *(uint32_t *)(p + 0x30) != own;
        own += 4;
        *(uint32_t *)(p + 0x30) = own;
        shown = score_counted(p, &real);
        wrong += real != own || *(uint32_t *)(p + 0x30) != shown;
    }
    check(!lost && !wrong, "score: the count put back before each count as the score left it, and set back after it");
    check(own - shown == 32, "score: 80 ms at 2.5 ms a tick shows the count 32 ticks behind the score's own");
    /* The method called again with no count before it: the score's own count is still the one kept. */
    shown = score_counted(p, &real);
    check(real == own && own - shown == 32, "score: an update with no count between keeps the score's own count");
    /* A start between an update and the next count (the count 0, the start clock read again): the 0 kept, and the
     * lag from none. */
    *(uint32_t *)(p + 0x30) = 0;
    *(int64_t *)(p + 0x38) = 2000;
    score_before_count(p);
    int kept = *(uint32_t *)(p + 0x30) == 0;
    *(uint32_t *)(p + 0x30) = 4;
    shown = score_counted(p, &real);
    check(kept && real == 4 && shown == 4, "score: a start's count of 0 is kept, its lag begins at none");
    /* A count the game set itself between an update and the next count: kept as the game set it. */
    for (own = 4; own < 400; own += 4) {
        score_before_count(p);
        *(uint32_t *)(p + 0x30) = own;
        score_counted(p, &real);
    }
    *(uint32_t *)(p + 0x30) = 12345;
    score_before_count(p);
    check(*(uint32_t *)(p + 0x30) == 12345, "score: a count the game set itself is not put back");
    /* No offset: the count left as the score player has it. */
    score_lag_ms(0);
    score_before_count(p);
    *(uint32_t *)(p + 0x30) = 20000;
    shown = score_counted(p, &real);
    check(shown == 20000 && *(uint32_t *)(p + 0x30) == 20000, "score: with no offset nothing is written");
    /* Five scores in four places: the fifth takes the place updated longest ago, its count put back first while its
     * score player lives; one no longer living (its first word another table's) is never written. */
    score_lag_ms(80);
    BYTE *q[5];
    for (int i = 0; i < 5; i++)
        q[i] = fake_score(mem[i], 2.5, 0, 3000 + i);
    for (int i = 0; i < 4; i++) {
        for (uint32_t c = 4; c <= 40; c += 4) {
            score_before_count(q[i]);
            *(uint32_t *)(q[i] + 0x30) = c;
            score_counted(q[i], &real);
        }
    }
    int set_back = *(uint32_t *)(q[0] + 0x30) < 40 && *(uint32_t *)(q[1] + 0x30) < 40;
    /* The first one gone (its table word changed, as a destructor leaves it): its count not written again. */
    *(ULONG *)q[0] = 0x0079d000;
    uint32_t gone = *(uint32_t *)(q[0] + 0x30);
    score_counted(q[4], &real);
    int untouched = *(uint32_t *)(q[0] + 0x30) == gone;
    /* The next oldest, still living, gets its own count back when its place is taken. */
    BYTE *r = fake_score(mem[0], 2.5, 0, 4000);
    score_counted(r, &real);
    check(set_back && untouched && *(uint32_t *)(q[1] + 0x30) == 40,
          "score: a place taken from the oldest score, its count put back while it lives, never once it is gone");
    score_lag_ms(0);
}

static void test_clock(void)
{
    /* The read from the probe: every register but EDX:EAX, the stack and the flags as they were. */
    int64_t before = clock_interrupt_now() - clock_held_total();
    clock_probe();
    int64_t after = clock_interrupt_now() - clock_held_total();
    int64_t got = ((int64_t)g_probe_hi << 32) | g_probe_lo;
    check(g_probe_ecx == 0x11223344 && g_probe_ebx == 0x55667788 && g_probe_esi == 0x99aabbcc &&
              g_probe_edi == 0xddeeff00 && g_probe_ebp == 0x0badf00d && g_probe_esp_out == g_probe_esp_in,
          "clock: the read leaves every register but EDX:EAX, and the stack, as they were");
    check(g_probe_flags_out == g_probe_flags_in && (g_probe_flags_in & 0x881) == 0x881 && !(g_probe_flags_in & 0x40),
          "clock: the read leaves the flags as they were (CF, SF and OF set, ZF clear here)");
    check(got >= before && got <= after, "clock: the read is the interrupt time less the held total");
    /* A hold of a second: the read is a second behind the interrupt time from then on; none, or a clock gone back,
     * adds nothing. */
    int64_t held = clock_held_total();
    clock_held(10000000);
    clock_held(0);
    clock_held(-5);
    before = clock_interrupt_now() - 10000000 - held;
    clock_probe();
    after = clock_interrupt_now() - 10000000 - held;
    got = ((int64_t)g_probe_hi << 32) | g_probe_lo;
    check(clock_held_total() == held + 10000000 && got >= before && got <= after,
          "clock: a hold's length is taken off the read from then on, nothing for none");
    /* A total past 32 bits (a held time over seven minutes): its high word published with it. */
    clock_held(0x100000000LL);
    check(clock_held_total() == held + 10000000 + 0x100000000LL, "clock: the held total carries into its high word");

    /* The turn, on a copy of the client's read in memory of this program's own that may run code. */
    static const BYTE read[18] = {0x55, 0x8b, 0xec, 0x3e, 0x8b, 0x15, 0x0c, 0x00, 0xfe,
                                  0x7f, 0x3e, 0xa1, 0x08, 0x00, 0xfe, 0x7f, 0x5d, 0xc3};
    BYTE *code = VirtualAlloc(NULL, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!code) {
        check(0, "clock: memory for the client's read");
        return;
    }
    memcpy(code, read, sizeof read);
    typedef uint64_t (*ReadFn)(void);
    ReadFn f = (ReadFn)(void *)code;
    /* As the client has it: the interrupt time itself. */
    before = clock_interrupt_now();
    int64_t own = (int64_t)f();
    after = clock_interrupt_now();
    int own_ok = own >= before && own <= after;
    int turned = clock_turn(code) == CLOCK_TURNED && code[0] == 0xe9;
    BYTE once[18];
    memcpy(once, code, sizeof once);
    /* Turned: the held total taken off; turned again (a reset, a second device): nothing changes. */
    before = clock_interrupt_now() - clock_held_total();
    int64_t ours = (int64_t)f();
    after = clock_interrupt_now() - clock_held_total();
    int again = clock_turn(code) == CLOCK_TURNED && !memcmp(code, once, sizeof once);
    check(own_ok && turned && ours >= before && ours <= after && again,
          "clock: the client's read turned to openDMT3's once, the same after a second turn");
    /* Any other bytes (another build of the client): left alone, nothing written. */
    memcpy(code, read, sizeof read);
    code[11] = 0xa0;
    BYTE other[18];
    memcpy(other, code, sizeof other);
    check(clock_turn(code) == CLOCK_LEFT && !memcmp(code, other, sizeof other),
          "clock: a read with other bytes is left as it is");
    VirtualFree(code, 0, MEM_RELEASE);

    /* The read called from the score's count with the audio offset on (its return address the one set, the score
     * player in ECX): the count set back after the last update put back first, every register but EDX:EAX and the
     * flags kept all the same; called from anywhere else, it only reads. */
    static ULONG mem[0x100];
    BYTE *p = fake_score(mem, 2.5, 0, 5000);
    score_lag_ms(80);
    uint32_t real;
    for (uint32_t c = 4; c <= 400; c += 4) {
        score_before_count(p);
        *(uint32_t *)(p + 0x30) = c;
        score_counted(p, &real);
    }
    uint32_t written = *(uint32_t *)(p + 0x30);
    g_probe_ecx_in = (uint32_t)(uintptr_t)p;
    g_clock_count_return = 0x0070047e;
    clock_probe();
    int elsewhere = *(uint32_t *)(p + 0x30) == written;
    g_clock_count_return = (ULONG)(uintptr_t)clock_probe_back;
    before = clock_interrupt_now() - clock_held_total();
    clock_probe();
    after = clock_interrupt_now() - clock_held_total();
    got = ((int64_t)g_probe_hi << 32) | g_probe_lo;
    check(written == 400 - 32 && elsewhere && *(uint32_t *)(p + 0x30) == 400,
          "clock: the read at the score's count puts its count back first, from anywhere else only reads");
    check(g_probe_ecx == (uint32_t)(uintptr_t)p && g_probe_ebx == 0x55667788 && g_probe_esi == 0x99aabbcc &&
              g_probe_edi == 0xddeeff00 && g_probe_ebp == 0x0badf00d && g_probe_esp_out == g_probe_esp_in &&
              g_probe_flags_out == g_probe_flags_in && got >= before && got <= after,
          "clock: putting the count back leaves every register but EDX:EAX, the stack and the flags as they were");
    g_clock_count_return = 0;
    g_probe_ecx_in = 0x11223344;
    score_lag_ms(0);
}

static void test_unit_floor(void)
{
    /* At 100 % (96 dpi) the smallest unit is UI_UNIT_MIN: a window 576 tall and one 300 tall both at 0.75, a chip
     * 37.5 pixels across, the dart 32. */
    ui_unit_floor(96);
    check(fabsf(ui_unit(576) - 0.75f) < 1e-6f && fabsf(ui_unit(300) - 0.75f) < 1e-6f,
          "unit floor: at 96 dpi a small window's unit is 0.75");
    /* At 150 % the dart is 48 pixels: the smallest unit 1.125, a chip 56 x 38 at the least. */
    ui_unit_floor(144);
    check(fabsf(ui_unit(576) - 1.125f) < 1e-6f && 50.0f * ui_unit(300) >= 48.0f,
          "unit floor: at 150 % a small window's chips are wider than the 48-pixel dart (the unit 1.125)");
    /* At 200 % the dart is 64 pixels. */
    ui_unit_floor(192);
    check(fabsf(ui_unit(576) - 1.5f) < 1e-6f && 50.0f * ui_unit(300) >= 64.0f,
          "unit floor: at 200 % a small window's chips are wider than the 64-pixel dart (the unit 1.5)");
    /* A picture tall enough keeps the game's own unit at any scaling: 2160 lines are 2.8125. */
    check(fabsf(ui_unit(2160) - 2.8125f) < 1e-5f, "unit floor: a 2160-line picture at 200 % is still 2160 / 768");
    /* Under 100 % the chips stay as at 100 %. */
    ui_unit_floor(72);
    check(fabsf(ui_unit(300) - 0.75f) < 1e-6f, "unit floor: under 96 dpi the smallest unit stays 0.75");
    /* As the other tests have it. */
    ui_unit_floor(96);
}

static void test_log_repeat(void)
{
    /* The first and each power of two of a run: 1, 2, 4, 8, 16 of the first 17; nothing at 0 or below. */
    int said = 0, right = 1;
    for (long n = 1; n <= 17; n++) {
        int due = log_repeat_due(n);
        said += due;
        right &= due == (n == 1 || n == 2 || n == 4 || n == 8 || n == 16);
    }
    check(right && said == 5 && !log_repeat_due(0) && !log_repeat_due(-4),
          "log repeat: a run of the same line said at its 1st, 2nd, 4th, 8th and 16th, none at 0");
    /* A million failed resets in a row: twenty lines (1 to 524288), not a million. */
    long lines = 0;
    for (long n = 1; n <= 1000000; n++)
        lines += log_repeat_due(n);
    check(lines == 20, "log repeat: a million in a row said in 20 lines");
}

static void test_memory_tally(void)
{
    /* A walk in address order: 64 MB free, 16 MB committed, a free stretch read in two pieces (100 MB and 40 MB),
     * 8 MB reserved, 120 MB free, and a region in a state the walk does not know (counted as in use, 4 MB). */
    const unsigned long long MB = 1ull << 20;
    MemoryTally t;
    memset(&t, 0, sizeof t);
    memory_tally_add(&t, 64 * MB, MEMORY_FREE);
    memory_tally_add(&t, 16 * MB, MEMORY_COMMITTED);
    memory_tally_add(&t, 100 * MB, MEMORY_FREE);
    memory_tally_add(&t, 40 * MB, MEMORY_FREE);
    memory_tally_add(&t, 8 * MB, MEMORY_RESERVED);
    memory_tally_add(&t, 120 * MB, MEMORY_FREE);
    memory_tally_add(&t, 4 * MB, 7);
    check(t.free == 324 * MB && t.reserved == 8 * MB && t.committed == 20 * MB && t.regions == 7,
          "memory tally: free, reserved and committed summed by region, an unknown state counted as committed");
    check(t.largest_free == 140 * MB,
          "memory tally: two free regions next to each other are one 140 MB block, larger than the 120 MB one after");
    check(t.run == 0, "memory tally: a region in use ends the free block before it");
}

int main(void)
{
    test_clock();
    test_score_lag();
    test_settings();
    test_engine();
    test_render_size();
    test_pass_times();
    test_post();
    test_pacer();
    test_music_lock();
    test_jit();
    test_catchup();
    test_audio_offset();
    test_display_choices();
    test_display_lock();
    test_guard();
    test_keys();
    test_gate();
    test_mark_press();
    test_refresh_advice();
    test_sound_values();
    test_sound_panel();
    test_sound_file();
    test_logfile();
    test_bar_clock();
    test_slides();
    test_slot_index();
    test_unit_floor();
    test_log_repeat();
    test_memory_tally();
    test_touch();
    test_methods();
    test_sharp();
    test_picture();
    test_card();
    test_resume();
    test_layout();
    test_places();
    test_pictures();
    test_redirect();
    printf("%d checks, %d failed\n", checks, failures);
    return failures;
}
