/*
 * The native tests: the in-game layer's decisions (logic.c) and pictures (paint.c, look.c), built with the same
 * compiler as the DLL and run under Wine by test.sh. Each check prints its name; the program ends with the count of
 * failures as its exit code.
 */
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "logic.h"
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
    check(!strcmp(card_line(&c), "A play in progress is not kept."), "card: during a song its one line says what is lost");
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
    check(card_count(&c) == 3 && !strcmp(card_label(&c, 1, NULL), "SHOW FPS") && !strcmp(card_state(&c, 1), "OFF") &&
              card_state(&c, 0) == NULL,
          "card: the menu has Show FPS, its state at its right");
    check(card_choose(&c, 1) == ACT_FPS && c.fps && c.open == CARD_MENU && !strcmp(card_state(&c, 1), "ON"),
          "card: Show FPS turns the chip on and the menu stays");
    card_key(&c, 0x28);
    check(card_key(&c, 0x0D) == ACT_FPS && !c.fps, "card: Enter on Show FPS turns it off again");
    int danger2 = 0;
    card_label(&c, 2, &danger2);
    check(danger2 && card_choose(&c, 2) == ACT_QUIT, "card: the menu's Quit (its last row) quits");
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
              fabsf(ui_unit(2160) - 2.8125f) < 0.001f && fabsf(ui_unit(600) - 1.0f) < 0.001f,
          "layout: the game's own pixels to the area's (never under one)");
    /* Nothing of the layer in the middle half of the game, where the notes come, at every size and shape of window:
     * the bar, its chips, the menu, the question, a long toast, the wide chip. */
    static const int sizes[5][2] = {{1280, 768}, {1920, 1080}, {3840, 2160}, {1600, 1200}, {2560, 1080}};
    int clear = 1;
    for (int k = 0; k < 5; k++) {
        int w = sizes[k][0], h = sizes[k][1];
        Box middle = {w * 0.25f, h * 0.25f, w * 0.5f, h * 0.5f};
        for (int open = CARD_MENU; open <= CARD_QUIT; open++) {
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
    check(fabsf(l.panel.x + l.panel.w - (l.chip[CHIP_X].x + l.chip[CHIP_X].w)) < 0.01f && l.panel.y > l.bar.h &&
              l.rows[0].x < l.rows[1].x && l.tab.y == l.panel.y && l.line_y == 0,
          "layout: the question drops under the X, Keep playing left of Quit, its tab on its top edge, no line");
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
    check(l.count == 3 && fabsf(l.panel.x + l.panel.w - (l.chip[CHIP_MENU].x + l.chip[CHIP_MENU].w)) < 0.01f &&
              l.rows[1].y > l.rows[0].y + l.rows[0].h,
          "layout: the menu drops under its own chip, its rows one under the other");
    check(ui_at_top_edge(0, 1080) && ui_at_top_edge(2, 1080) && !ui_at_top_edge(4, 1080),
          "reveal: only the very top edge brings the bar (its two top lines of 768)");
    check(ui_swipe_down(2, 40, 1080) && !ui_swipe_down(2, 20, 1080) && !ui_swipe_down(30, 90, 1080),
          "reveal: a finger drawn down from the top edge, not a short one or one from lower down");
    /* The chip at the bottom: above the game's labels there (ID CARD and NET from line 733 of 768, FREE PLAY from
     * line 742), at any size; at the top, 6 lines down; 12 in from its side. */
    int clear_labels = 1;
    for (int k = 0; k < 5; k++) {
        int w = sizes[k][0], h = sizes[k][1];
        float u = ui_unit(h);
        Box br = fps_box(w, h, CORNER_BOTTOM_RIGHT), bl = fps_box(w, h, CORNER_BOTTOM_LEFT);
        clear_labels &= br.y + br.h <= 733 * u - 6 * u + 0.01f && bl.y + bl.h <= 733 * u - 6 * u + 0.01f &&
                        fabsf(br.x + br.w - (w - 12 * u)) < 0.01f && fabsf(bl.x - 12 * u) < 0.01f;
    }
    Box tl = fps_box(1920, 1080, CORNER_TOP_LEFT), tr = fps_box(1920, 1080, CORNER_TOP_RIGHT);
    check(clear_labels && fabsf(tl.y - 6 * 1.40625f) < 0.01f && fabsf(tr.x + tr.w - (1920 - 12 * 1.40625f)) < 0.01f,
          "layout: the frame rate chip in its corner, at the foot above the game's own labels");
    /* The mark: at the top centre, small, taller lit; resting near it counts, the game's top band elsewhere not. */
    Box m0 = ui_mark_box(1920, 1080, 0), m1 = ui_mark_box(1920, 1080, 1);
    check(m0.y == 0 && fabsf(m0.x + m0.w / 2 - 960) < 0.01f && m1.h > m0.h && m0.h < 10 * 1.40625f &&
              ui_on_mark(960, 3, 1920, 1080) && ui_on_mark(960 + m1.w / 2 + 8, 5, 1920, 1080) &&
              !ui_on_mark(960, 40, 1920, 1080) && !ui_on_mark(700, 3, 1920, 1080),
          "layout: the mark at the top centre, near it counts as on it");
    check(ease_out(0) == 0 && ease_out(1) == 1 && ease_out(0.5f) > 0.5f && ease_out(2) == 1,
          "motion: eased out, quick first and settling");
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
    check((xpx & 0xff) > ((xpx >> 16) & 0xff) + 100 && ((mpx & 0xff) - ((mpx >> 16) & 0xff)) < 40 && (mpx >> 24) == 255 &&
              (corner >> 24) == 0,
          "pictures: the X in the launcher's blue, the others its metal, their ends leaning");
    sprite_free(&sp);
    /* The mark: the game's tab at the top edge, wider at its top, lit taller. */
    Box mb = ui_mark_box(1920, 1080, 1);
    sprite_make(&sp, mb.w, mb.h, 2 * l.u);
    look_mark(&sp, l.u, 0);
    int ty = (int)(sp.room + 1), fy = (int)(sp.room + 7 * l.u);
    int unlit_top = (sp.content->px[ty * sp.content->w + sp.content->w / 2] >> 24) > 0;
    int unlit_low = (sp.content->px[fy * sp.content->w + sp.content->w / 2] >> 24) > 0;
    int edge_top = (sp.content->px[ty * sp.content->w + (int)(sp.room + 1)] >> 24) > 0;
    int edge_foot = (sp.content->px[(int)(sp.room + 5 * l.u) * sp.content->w + (int)(sp.room + 1)] >> 24) > 0;
    look_mark(&sp, l.u, 1);
    int lit_low = (sp.content->px[fy * sp.content->w + sp.content->w / 2] >> 24) > 0;
    check(unlit_top && !unlit_low && lit_low && edge_top && !edge_foot && (sp.mask->px[ty * sp.mask->w + sp.mask->w / 2] >> 24) == 0,
          "pictures: the mark is the game's tab from the top edge, taller lit, with no glass");
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
    int up = UPSCALE_NIS, aa = AA_SMAA_ULTRA, n = 0;
    while (post_lighter(&up, &aa))
        n++;
    check(n == 3 && up == UPSCALE_SMOOTH && aa == AA_OFF, "guard: SMAA to FXAA to off, then NIS to bilinear");
    up = UPSCALE_OFF;
    aa = AA_OFF;
    check(!post_lighter(&up, &aa), "guard: nearest is as light as it goes");
    char words[160];
    note_words(0, 1, AA_FXAA, words, sizeof words);
    check(!strcmp(words, "Picture quality lowered to keep 60 FPS (FXAA)"),
          "guard: the note says why and what, in one sentence");
    note_words(1, 0, AA_OFF, words, sizeof words);
    check(!strcmp(words, "60 FPS를 지키려고 화질을 낮췄습니다(부드럽게 확대)"), "guard: the note in Korean");
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

int main(void)
{
    test_settings();
    test_engine();
    test_render_size();
    test_pass_times();
    test_post();
    test_pacer();
    test_music_lock();
    test_display_lock();
    test_guard();
    test_keys();
    test_gate();
    test_bar_clock();
    test_slot_index();
    test_sharp();
    test_picture();
    test_card();
    test_layout();
    test_pictures();
    test_redirect();
    printf("%d checks, %d failed\n", checks, failures);
    return failures;
}
