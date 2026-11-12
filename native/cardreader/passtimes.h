/*
 * The picture's GPU time by pass (OPENDMT3_PASS_TIMES=on: the launcher's Screen page, Measure the picture's GPU
 * time, and the tests): post.c puts a timestamp after each step of a frame's picture work and hands this module each
 * step's time in microseconds, the gap since the timestamp before it, by the step's name. This module keeps them over a
 * stretch of frames and sums each name up as its median, in plain C with no Windows calls so the native tests run it.
 */
#ifndef OPENDMT3_PASSTIMES_H
#define OPENDMT3_PASSTIMES_H

/* Distinct step names a stretch keeps, and samples a name keeps (over ten seconds of frames at 60 a second). */
#define PT_NAMES 24
#define PT_SAMPLES 640

typedef struct {
    /* Each name as first seen (post.c's own string constants, compared by their text), its samples. */
    const char *name[PT_NAMES];
    int n[PT_NAMES];
    float us[PT_NAMES][PT_SAMPLES];
    int names;
    /* Frames whose every step was read into the stretch. */
    long frames;
    /* One frame's sums by name, before they become samples (two blur passes in a frame are one sample). */
    float frame_us[PT_NAMES];
    int frame_has[PT_NAMES];
} PassTimes;

/* A new stretch: no names, no samples. */
void pt_clear(PassTimes *p);
/* One step's time in the frame being read; several steps of one name in a frame add up. */
void pt_step(PassTimes *p, const char *name, float us);
/* The frame being read is done: each name it had becomes one sample (a name past PT_SAMPLES is not kept). */
void pt_frame(PassTimes *p);
/* The median of name i's samples, in microseconds; -1 when it has none. */
float pt_median(const PassTimes *p, int i);
/* The stretch in one line: "name 123.4 us, other 5.6 us (120 frames)", each name in the order first seen; how long
 * the line is (cut to fit `size`, which is at least 1). */
int pt_line(const PassTimes *p, char *out, int size);

#endif
