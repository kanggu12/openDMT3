/*
 * The in-game log's file (logfile.c): a line at a time, through one handle opened at the first line and kept, so a line
 * costs one write. Opened and closed for each line, the log cost the frame that writes the counter's two-second lines
 * 2.3 to 5.4 ms under Wine (about twenty lines at 150 to 250 us each, by the log's own times), and that frame's present
 * waits for them after its tick (hooks.c count_present). No Windows types beyond the handle: the native tests include
 * this.
 */
#ifndef OPENDMT3_LOGFILE_H
#define OPENDMT3_LOGFILE_H

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <stdarg.h>

/* A log's file: its handle once a line opened it; NULL (or INVALID_HANDLE_VALUE) while none is open, before the first
 * line and after a write that failed (the next line opens the file again, as each line once did). */
typedef struct {
    HANDLE h;
} LogFile;

/* What a log's environment variable says (logfile_variable): not set (no log), set and empty (the default file beside
 * the DLL), or a path. */
enum { LOG_UNSET = -1, LOG_DEFAULT = 0, LOG_PATH = 1 };

/* Read the variable `name` into `out` (room for `room` characters): LOG_PATH with its value, LOG_DEFAULT when it is set
 * to nothing, LOG_UNSET when it is not set or its value does not fit (a value too long is not a path to open). */
int logfile_variable(const WCHAR *name, WCHAR *out, DWORD room);

/* One line into the file at `path`, opened (at its end) when it is not open: `ms` and a space, the words `fmt` makes of
 * `ap`, then the line's end, each "\n" written "\r\n" as the C runtime's text mode wrote the log before. 1 when the
 * whole line reached the file. Not locked: the caller holds the log's own lock. */
int logfile_line(LogFile *log, const WCHAR *path, unsigned long ms, const char *fmt, va_list ap);

/* The handle let go (the tests: the game keeps its log open until its process ends, which closes it). */
void logfile_close(LogFile *log);

#endif
