/*
 * The touch screen's contacts as openDMT3 hands them to the game (contacts.h), with no Windows calls.
 */
#include "contacts.h"

#include <string.h>

/* A point that pads the count: off the game's screen on both axes (the game reads it as -64255, -64767), where no note,
 * lane or button of the game's is. */
#define OFF_SCREEN 0xFFFFu

/* A 32-bit and a 16-bit number into the buffer, low byte first, as the game's x86 reads them. */
static void put32(uint8_t *at, uint32_t v)
{
    at[0] = (uint8_t)v;
    at[1] = (uint8_t)(v >> 8);
    at[2] = (uint8_t)(v >> 16);
    at[3] = (uint8_t)(v >> 24);
}

static void put16(uint8_t *at, uint32_t v)
{
    at[0] = (uint8_t)v;
    at[1] = (uint8_t)(v >> 8);
}

/* One axis of a point as the frame's program wrote it: the game takes `edge` - X, so X is `edge` - v; a place no 16-bit
 * number can say (past the far edge, or 65535 pixels before the near one) is off the screen on that axis. */
static uint32_t turned(int v, int edge)
{
    /* In 64 bits: a place far past either edge cannot wrap round into the screen. */
    long long t = (long long)edge - v;
    return t >= 0 && t < (long long)OFF_SCREEN ? (uint32_t)t : OFF_SCREEN;
}

/* The kept contact with this id that is still down, or -1 (an id Windows gave a contact already up may come again for
 * a new one before the game had the first: that first one is kept apart, up). */
static int find_down(const Contacts *t, uint32_t id)
{
    for (int i = 0; i < t->n; i++)
        if (t->c[i].down && t->c[i].id == id)
            return i;
    return -1;
}

void contacts_start(Contacts *t)
{
    /* Nothing kept, nothing handed, the mouse's button never read down. */
    memset(t, 0, sizeof *t);
    t->mouse_at = -1e12;
}

int contacts_down(Contacts *t, uint32_t id, int x, int y, int overlay)
{
    int i = find_down(t, id);
    if (i >= 0) {
        /* Down already (Windows says a contact's first message again): where it is now, nothing more. */
        t->c[i].x = x;
        t->c[i].y = y;
        return 1;
    }
    if (t->n >= CONTACTS_MOST) {
        /* Every place taken: the oldest contact already up gives its place (a tap the game had no read for). */
        int oldest = -1;
        for (int k = 0; k < t->n; k++)
            if (!t->c[k].down && (oldest < 0 || t->c[k].up_at < t->c[oldest].up_at))
                oldest = k;
        /* More down at once than any screen reports: this one is not kept (the game never hears of it). */
        if (oldest < 0)
            return 0;
        /* The rest moved up a place, so the contacts stay in the order they began. */
        memmove(&t->c[oldest], &t->c[oldest + 1], (size_t)(t->n - oldest - 1) * sizeof t->c[0]);
        t->n--;
    }
    /* Kept last, so the contacts stay in the order they began. */
    Contact *c = &t->c[t->n++];
    c->id = id;
    c->x = x;
    c->y = y;
    c->down = 1;
    /* Not handed yet: the next read hands it, even if it is up by then (a tap between two reads). */
    c->seen = 0;
    c->overlay = overlay ? 1 : 0;
    c->up_at = 0;
    return 1;
}

void contacts_move(Contacts *t, uint32_t id, int x, int y)
{
    int i = find_down(t, id);
    /* Only a contact still down moves (a pen over the screen, not on it, is no contact). */
    if (i < 0)
        return;
    t->c[i].x = x;
    t->c[i].y = y;
}

void contacts_up(Contacts *t, uint32_t id, double now)
{
    int i = find_down(t, id);
    /* Up: it goes at the next read if the game had it, after that read if not (and soon enough). */
    if (i >= 0) {
        t->c[i].down = 0;
        t->c[i].up_at = now;
    }
}

void contacts_withhold(Contacts *t, uint32_t id)
{
    for (int i = 0; i < t->n; i++)
        /* The one named (or every one) still down is the overlay's from now on: the game sees it come up. */
        if (t->c[i].down && (id == CONTACT_ALL || t->c[i].id == id))
            t->c[i].overlay = 1;
}

void contacts_clear(Contacts *t)
{
    /* Every contact gone, the taps not read yet too: none of them is on the screen any more. */
    t->n = 0;
}

void contacts_mouse(Contacts *t, int button, int x, int y, double now)
{
    int i = find_down(t, CONTACT_MOUSE);
    /* Down at this read: the hold past a release counts from now. */
    if (button)
        t->mouse_at = now;
    /* Down, or up for less than the game's own 50 ms since it was last read down (a press it is still holding). */
    int held = button || (i >= 0 && now - t->mouse_at < MOUSE_HOLD_MS);
    if (held && i >= 0)
        /* Held on: it follows the pointer, as the game's own point does. */
        contacts_move(t, CONTACT_MOUSE, x, y);
    else if (held)
        /* A new press of the button: the game's, since the overlay's presses never read down (hooks.c, hold_keys). */
        contacts_down(t, CONTACT_MOUSE, x, y, 0);
    else if (i >= 0)
        /* Let go for 50 ms: the press ends. */
        contacts_up(t, CONTACT_MOUSE, now);
}

int contacts_is_down(const Contacts *t, uint32_t id)
{
    return find_down(t, id) >= 0;
}

int contacts_read(Contacts *t, int hold, uint8_t *buffer, size_t size, double now)
{
    /* No room even for the head: nothing written (never the game's buffer, which is TOUCH_BUFFER bytes). */
    if (!buffer || size < TOUCH_HEAD)
        return 0;
    /* A tap up too long ago is no press of this read (the game read nothing while it was made): it goes unhanded. */
    int recent = 0;
    for (int i = 0; i < t->n; i++) {
        const Contact *c = &t->c[i];
        if (!c->down && !c->seen && now - c->up_at > TAP_KEEP_MS)
            continue;
        t->c[recent++] = *c;
    }
    t->n = recent;
    /* The most points that fit: the game's own most, and no byte past the buffer. */
    size_t room = (size - TOUCH_HEAD) / TOUCH_POINT;
    int most = room < TOUCH_GAME_MOST ? (int)room : TOUCH_GAME_MOST;
    /* What goes to the game, in the contacts' order: each of the game's that is down, and each not handed yet even if it
     * is up now. Nothing while the overlay holds the input. */
    int pick[CONTACTS_MOST];
    int count = 0, fresh = 0;
    for (int i = 0; i < t->n && !hold; i++) {
        const Contact *c = &t->c[i];
        if (c->overlay || (!c->down && c->seen))
            continue;
        pick[count++] = i;
        /* One the game has not had: a press. */
        fresh |= !c->seen;
    }
    /* A press while points are on the screen: the game takes it only from a count larger than the last read's (its
     * groups and points added up grow), so a finger down as another came up would be lost. Points off the screen make
     * the count one more than the last read's. */
    int total = count;
    if (fresh && t->handed >= 1 && total <= t->handed)
        total = t->handed + 1;
    /* Never past what the game takes or the buffer holds (the contacts kept are far fewer). */
    if (total > most)
        total = most;
    if (count > total)
        count = total;
    /* The head: touching or not, the touches, one group of `total` points (the game reads groups times points). */
    put32(buffer, total > 0 ? 1u : 0u);
    put32(buffer + 4, (uint32_t)total);
    put32(buffer + 8, 1u);
    put32(buffer + 12, (uint32_t)total);
    for (int k = 0; k < total; k++) {
        uint8_t *p = buffer + TOUCH_HEAD + (size_t)k * TOUCH_POINT;
        /* A point's other fields are the frame's own (the game reads none of them): zero. */
        memset(p, 0, TOUCH_POINT);
        if (k < count) {
            const Contact *c = &t->c[pick[k]];
            /* Turned as the frame's program turned them, so the game's own turn puts the point back where it is. */
            put16(p + TOUCH_X, turned(c->x, TOUCH_GAME_W));
            put16(p + TOUCH_Y, turned(c->y, TOUCH_GAME_H));
        } else {
            /* A point padding the count. */
            put16(p + TOUCH_X, OFF_SCREEN);
            put16(p + TOUCH_Y, OFF_SCREEN);
        }
    }
    /* What was handed is seen from now on. */
    for (int k = 0; k < count; k++)
        t->c[pick[k]].seen = 1;
    /* Those up go once the game had them (and the overlay's once up); while the overlay holds the input, every one up
     * goes, so no tap made under its panel reaches the game after it. */
    int kept = 0;
    for (int i = 0; i < t->n; i++) {
        const Contact *c = &t->c[i];
        if (!c->down && (c->seen || c->overlay || hold))
            continue;
        t->c[kept++] = *c;
    }
    t->n = kept;
    /* The game's own count now, which the next read's press must pass. */
    t->handed = total;
    if (total > t->most)
        t->most = total;
    return total;
}
