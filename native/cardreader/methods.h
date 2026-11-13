/*
 * The methods openDMT3 puts in Direct3D's method tables, watched (methods.c): Direct3D 9 has been seen filling a
 * device's method table in again some frames after the device was made (in another build of the game), which leaves
 * the game's Present and Reset its own. With pacing locked to the music the game's own limiter is out, so such a frame
 * would run the game unpaced (four times its speed at 240 Hz). Every entry openDMT3 turned is looked at once a frame
 * from a call the game makes every frame (hooks.c), and put back as openDMT3's when it is not. No Windows types here:
 * the native tests include this.
 */
#ifndef OPENDMT3_METHODS_H
#define OPENDMT3_METHODS_H

/* Entries watched at most: the device's Present, Reset, the chain's three, the larger picture's sixteen, the flip
 * model's and a few surfaces' and textures' tables are far fewer. */
#define METHODS_MOST 64

/* A method openDMT3 put in a table: its entry, the method it put there (the newest when another of openDMT3's wraps
 * it later: the trace's), and its name and number for the log. 0 when it is not watched: no room, or a table outside
 * every module's image (one that could go with its object, which a look would then read after it is freed). */
int methods_watch(void **entry, void *ours, const char *name, int index);

/* One entry a look put back: its name and number, what it held instead of openDMT3's method, and how many times this
 * entry has been put back. */
typedef struct {
    const char *name;
    int index;
    void *held;
    long times;
} MethodBack;

/* The look: every watched entry that no longer holds openDMT3's method gets it again (the real method each kept is
 * left as it is, so nothing of another's is ever called in its place); how many were put back. The ones worth a line
 * in the log (an entry's 1st, 10th, 100th... time) go into `out`, at most `room`, their number in *noted. */
int methods_check(MethodBack *out, int room, int *noted);

/* An entry written as openDMT3's patches write one (its page made writable for the one write, then as it was); 0 when
 * the page could not be made writable. The tests stand in for Direct3D with it. */
int methods_write(void **entry, void *value);

#endif
