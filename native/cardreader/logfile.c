/*
 * The in-game log's file (logfile.h).
 */
#include "logfile.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* A line's room in place: the layer's lines are far shorter (its longest, the start's choices, under 400 bytes); a
 * longer one is made in memory of its own. */
#define LINE_ROOM 2048

int logfile_variable(const WCHAR *name, WCHAR *out, DWORD room)
{
    /* Windows answers 0 for a variable that is not set and for one set to nothing alike: only the error tells them
     * apart ("not found" for the first; the second succeeds and leaves the error as it was, cleared here first). */
    SetLastError(0);
    DWORD got = GetEnvironmentVariableW(name, out, room);
    if (!got) {
        if (GetLastError() == ERROR_ENVVAR_NOT_FOUND)
            return LOG_UNSET;
        /* Set to nothing: the caller's default file. */
        out[0] = 0;
        return LOG_DEFAULT;
    }
    /* Too long for the buffer: the size it needs comes back with nothing written, which is not a path to open. */
    if (got >= room)
        return LOG_UNSET;
    return LOG_PATH;
}

int logfile_line(LogFile *log, const WCHAR *path, unsigned long ms, const char *fmt, va_list ap)
{
    /* Opened at the first line, and again after a write that failed; kept open between lines. */
    if (!log->h || log->h == INVALID_HANDLE_VALUE) {
        /* Appending only: every write goes to the file's end as the file is then, with no position of ours to seek
         * first (a line another writer added since stays before ours). Shared for reading and writing while it is
         * open, as the C runtime's own opening shared it. */
        log->h = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_ALWAYS,
                             FILE_ATTRIBUTE_NORMAL, NULL);
        /* Not opened (no such folder, no rights): this line is lost, as it was, and the next one tries again. */
        if (log->h == INVALID_HANDLE_VALUE)
            return 0;
    }
    /* The time first, then the words, two bytes kept at the end for the line's end. */
    char text[LINE_ROOM];
    int head = snprintf(text, sizeof text, "%lu ", ms);
    /* A copy of the words' arguments, for a second making of a line too long for the room. */
    va_list again;
    va_copy(again, ap);
    /* How long the words are comes back whether or not they fit (cut short in the room when they do not). */
    int words = vsnprintf(text + head, sizeof text - 2 - (size_t)head, fmt, ap);
    char *line = text;
    if (words >= 0 && (size_t)head + (size_t)words + 2 >= sizeof text) {
        /* Longer than the room: made again whole in memory of its own, its time first, room for its end after. */
        line = malloc((size_t)head + (size_t)words + 3);
        if (line) {
            memcpy(line, text, (size_t)head);
            vsnprintf(line + head, (size_t)words + 1, fmt, again);
        }
    }
    va_end(again);
    /* Words that could not be made (a format the runtime refuses), or no memory for a long line: nothing written. */
    if (words < 0 || !line)
        return 0;
    size_t n = (size_t)head + (size_t)words;
    /* Line ends inside the words: none of the layer's lines has one, but text mode wrote each as "\r\n". */
    size_t inner = 0;
    for (size_t i = (size_t)head; i < n; i++)
        inner += line[i] == '\n';
    /* The bytes as they go: with no inner end, the line itself with its own end after it (its buffer has the room). */
    size_t total = n + inner + 2;
    char *out = inner ? malloc(total) : line;
    if (out && inner) {
        /* Each inner end with its "\r" before it, as text mode wrote it. */
        size_t k = 0;
        for (size_t i = 0; i < n; i++) {
            if (line[i] == '\n')
                out[k++] = '\r';
            out[k++] = line[i];
        }
    }
    int ok = 0;
    if (out) {
        /* The line's own end, then the whole line in one write: a reader sees it at once, with no buffer between. */
        out[total - 2] = '\r';
        out[total - 1] = '\n';
        DWORD put = 0;
        ok = WriteFile(log->h, out, (DWORD)total, &put, NULL) && put == (DWORD)total;
        /* A write that failed (a disk full, a volume gone): the file let go, opened again at the next line. */
        if (!ok) {
            CloseHandle(log->h);
            log->h = INVALID_HANDLE_VALUE;
        }
    }
    /* Memory of its own let go: the translated line's and the long line's. */
    if (out && out != line)
        free(out);
    if (line != text)
        free(line);
    return ok;
}

void logfile_close(LogFile *log)
{
    /* Only a handle that was opened. */
    if (log->h && log->h != INVALID_HANDLE_VALUE)
        CloseHandle(log->h);
    log->h = NULL;
}
