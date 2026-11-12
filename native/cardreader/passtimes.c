/*
 * The picture's GPU time by pass, kept over a stretch of frames and summed up by its medians (passtimes.h).
 */
#include "passtimes.h"

#include <stdio.h>
#include <string.h>

void pt_clear(PassTimes *p)
{
    /* Everything to zero: no names, no samples, no frame open. */
    memset(p, 0, sizeof *p);
}

/* The index of a name, added when it is new; -1 when the table is full. */
static int slot(PassTimes *p, const char *name)
{
    for (int i = 0; i < p->names; i++)
        /* By text: the same step named by the same constant or an equal one is one name. */
        if (!strcmp(p->name[i], name))
            return i;
    if (p->names >= PT_NAMES)
        return -1;
    p->name[p->names] = name;
    return p->names++;
}

void pt_step(PassTimes *p, const char *name, float us)
{
    int i = name ? slot(p, name) : -1;
    if (i < 0)
        return;
    /* Several steps of one name in a frame (the glass's three blur passes) are its one sample. */
    p->frame_us[i] += us;
    p->frame_has[i] = 1;
}

void pt_frame(PassTimes *p)
{
    for (int i = 0; i < p->names; i++) {
        if (!p->frame_has[i])
            continue;
        /* Past the room for a stretch, a name's later frames are not kept (its median is of the first ones). */
        if (p->n[i] < PT_SAMPLES)
            p->us[i][p->n[i]++] = p->frame_us[i];
        p->frame_us[i] = 0;
        p->frame_has[i] = 0;
    }
    p->frames++;
}

float pt_median(const PassTimes *p, int i)
{
    if (i < 0 || i >= p->names || p->n[i] <= 0)
        return -1;
    /* A sorted copy (an insertion sort: a few hundred numbers at most, twice a second). */
    static float v[PT_SAMPLES];
    int n = p->n[i];
    for (int k = 0; k < n; k++) {
        float x = p->us[i][k];
        int j = k;
        while (j > 0 && v[j - 1] > x) {
            v[j] = v[j - 1];
            j--;
        }
        v[j] = x;
    }
    /* The middle one, or the mean of the two middle ones. */
    return n % 2 ? v[n / 2] : (v[n / 2 - 1] + v[n / 2]) / 2.0f;
}

int pt_line(const PassTimes *p, char *out, int size)
{
    int len = 0;
    out[0] = 0;
    for (int i = 0; i < p->names && len < size - 1; i++) {
        float m = pt_median(p, i);
        if (m < 0)
            continue;
        /* "name 12.3 us", the names apart by a comma. */
        int w = snprintf(out + len, (size_t)(size - len), "%s%s %.1f us", len ? ", " : "", p->name[i], m);
        if (w < 0)
            break;
        len += w < size - len ? w : size - len - 1;
    }
    if (len < size - 1) {
        int w = snprintf(out + len, (size_t)(size - len), " (%ld frames)", p->frames);
        if (w > 0)
            len += w < size - len ? w : size - len - 1;
    }
    return len;
}
