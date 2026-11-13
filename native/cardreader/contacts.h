/*
 * The touch screen's contacts as openDMT3 hands them to the game, in plain C with no Windows calls, so the native tests
 * run every rule (touch.c feeds them from Windows; the stand-in multiDLL.dll asks for each read).
 *
 * The cabinet's touch frame came with a program that wrote its points into shared memory; the PC client reads them
 * through multiDLL.dll's WaitNexioMulti into a buffer of its own, once a frame while a song plays. On a PC there is no
 * such program, so the game's OpenNexioMulti fails and it plays one point read from the mouse. openDMT3's own
 * multiDLL.dll opens, and hands the game every finger Windows reports on its window and the mouse as one point more,
 * by these rules (measured in the client, its FUN_0070efa0):
 *   - the buffer as the frame's program filled it: a head of four numbers, then the points, the game taking
 *     x = 1280 - X and y = 768 - Y of each, so each point is written turned the same way;
 *   - the game sees a new press only when its touching starts or, with two points or more, when their count grows (its
 *     head's group and point counts added up against the last read's): a finger down in the read another came up in
 *     would add none, so the read adds a point off the screen, which nothing of the game's is under, until it does;
 *   - a tap that comes and goes between two reads is handed to the game once, if the read comes soon enough after it
 *     (the game reads only while a song plays: a tap on its menus is never handed to the song after);
 *   - a contact the overlay took (begun on its bar or its panel, or answering it) never reaches the game.
 */
#ifndef OPENDMT3_CONTACTS_H
#define OPENDMT3_CONTACTS_H

#include <stddef.h>
#include <stdint.h>

/* The game's buffer, as its INP::OpenNexio allocates it: 16 bytes of head, then 100 groups of 100 points of 24 bytes. */
#define TOUCH_BUFFER 0x3A990
/* The head: [0] touching (0: nothing on the screen), [1] how many touches (above 1: several), [2] groups, [3] points
 * in each group, four 32-bit numbers. */
#define TOUCH_HEAD 16
/* A group's bytes (100 points), and a point's. */
#define TOUCH_GROUP 0x960
#define TOUCH_POINT 24
/* Where a point's X and Y are in it (16-bit, the frame's own turned axes). */
#define TOUCH_X 12
#define TOUCH_Y 14
/* The most points the game takes from a read. */
#define TOUCH_GAME_MOST 100
/* The contacts kept at once: Windows reports ten on most screens; the mouse is one more, and taps already up wait for
 * their read. The game's own most is far past it. */
#define CONTACTS_MOST 24
/* The mouse's own id (Windows' pointer ids are small numbers). */
#define CONTACT_MOUSE 0xFFFFFFFFu
/* The mouse's button counts as held this long after its release, as the game's own reading of it does (its
 * FUN_0070edb0: a release within 50 ms of the button last read down is not one yet), so a mouse plays as before. */
#define MOUSE_HOLD_MS 50.0
/* A tap up this long before a read is no press of that read: the game was not reading (its menus, a long load), and a
 * tap there is not one for the song. Far past a frame's 16.7 ms and the game's own short stalls. */
#define TAP_KEEP_MS 250.0
/* The game's own screen, in its pixels. */
#define TOUCH_GAME_W 1280
#define TOUCH_GAME_H 768

/* One contact: a finger, a pen, or the mouse's button. */
typedef struct {
    uint32_t id;           /* Windows' pointer id, or CONTACT_MOUSE */
    int x, y;              /* where it is, in the game's pixels (past its edges on the picture's bars) */
    uint8_t down;          /* still on the screen */
    uint8_t seen;          /* handed to the game in a read already */
    uint8_t overlay;       /* the overlay's: never handed to the game */
    double up_at;          /* when it came up (ms, any one clock) */
} Contact;

typedef struct {
    Contact c[CONTACTS_MOST];  /* the first `n` are kept, oldest first (the game takes its first point as the touch's
                                * place, so the finger down longest stays first) */
    int n;
    int handed;            /* the points handed at the last read, off-screen ones with them: the game's own count */
    double mouse_at;       /* when the mouse's button was last read down (ms, any one clock) */
    int most;              /* the most points handed in one read so far (for the log) */
} Contacts;

/* Nothing on the screen, nothing handed. */
void contacts_start(Contacts *t);
/* A contact begins at game pixel (x, y): `overlay` the overlay's (begun on its bar or panel, or while it answers).
 * One with the id of a contact still down moves it instead. With every place taken, the oldest contact already up
 * makes room; 0 when all of them are down (the contact is not kept). */
int contacts_down(Contacts *t, uint32_t id, int x, int y, int overlay);
/* A contact moved to game pixel (x, y) (nothing for one not down). */
void contacts_move(Contacts *t, uint32_t id, int x, int y);
/* A contact left the screen at `now` (ms): it goes once the game has had it, or after TAP_KEEP_MS with no read. */
void contacts_up(Contacts *t, uint32_t id, double now);
/* The overlay takes the contact (or, for `id` CONTACT_ALL, every contact down now): it answered the overlay, so it
 * never reaches the game again; a contact begun after is the game's. */
#define CONTACT_ALL 0xFFFFFFFEu
void contacts_withhold(Contacts *t, uint32_t id);
/* Everything off the screen at once, nothing more to hand (the window lost its input). */
void contacts_clear(Contacts *t);
/* The mouse at the game's read: its left button as the game reads it this frame (`button`: down, with the overlay's
 * hold already applied), the game pixel under the pointer, the time (ms). Held MOUSE_HOLD_MS past its release, as the
 * game holds it. */
void contacts_mouse(Contacts *t, int button, int x, int y, double now);
/* Whether a contact with this id is down now (the overlay's or the game's). */
int contacts_is_down(const Contacts *t, uint32_t id);
/* The game's read at `now` (ms) into its buffer (`size` bytes, TOUCH_BUFFER as the game makes it): the head and the
 * points as the frame's program wrote them, nothing at all while the overlay holds the input (`hold`: its menu or
 * question up). The points handed, off-screen ones with them. The contacts handed are seen from now on; those up and
 * seen go, and those up for more than TAP_KEEP_MS go unhanded. */
int contacts_read(Contacts *t, int hold, uint8_t *buffer, size_t size, double now);

#endif
