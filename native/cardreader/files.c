/*
 * The game folder read only (redirect.h): the client's file calls turned to ours, so openDMT3's own files stand in for
 * the few of the game's a PC needs changed, and nothing is written into the game folder.
 *
 * The launcher starts openDMT3's copy of the client from openDMT3's own folder, this DLL beside it, with the game
 * folder as the current folder. The client opens its files by paths relative to the current folder through its own
 * imports: CreateFileA and CreateFileW to open, GetFileAttributesA/W to ask whether one is there, CreateDirectoryA/W
 * for the operator data's folders, DeleteFileA. Each of those slots in the client's import table comes here: a path
 * the list beside this DLL names is opened at openDMT3's file instead (with the wide call, so openDMT3's folder may
 * have letters outside the ANSI code page); every other path goes to Windows exactly as the client gave it.
 *
 * GetModuleFileNameA/W asked for the client itself answer a path in the game folder: the client finds its folder that
 * way when it starts and makes it the current folder (SetCurrentDirectoryA), which must stay the game folder.
 *
 * With no list beside the DLL (the DLL in the game folder, as earlier openDMT3 put it there) nothing is answered and
 * every call goes to Windows as it was. OPENDMT3_FILES_TRACE (measuring only) writes every call into the in-game log.
 */
#define _WIN32_WINNT 0x0600
#include "ingame.h"
#include "redirect.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* The real functions, as Windows bound them into the client's import table. */
typedef HANDLE(WINAPI *OpenA)(LPCSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE);
typedef HANDLE(WINAPI *OpenW)(LPCWSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE);
typedef DWORD(WINAPI *AttrA)(LPCSTR);
typedef DWORD(WINAPI *AttrW)(LPCWSTR);
typedef BOOL(WINAPI *MakeA)(LPCSTR, LPSECURITY_ATTRIBUTES);
typedef BOOL(WINAPI *MakeW)(LPCWSTR, LPSECURITY_ATTRIBUTES);
typedef BOOL(WINAPI *RemoveA)(LPCSTR);
typedef BOOL(WINAPI *RemoveW)(LPCWSTR);
typedef DWORD(WINAPI *NameA)(HMODULE, LPSTR, DWORD);
typedef DWORD(WINAPI *NameW)(HMODULE, LPWSTR, DWORD);
typedef BOOL(WINAPI *SetDirA)(LPCSTR);
typedef DWORD(WINAPI *GetDirA)(DWORD, LPSTR);
typedef HMODULE(WINAPI *LoadA)(LPCSTR);
typedef HMODULE(WINAPI *LoadW)(LPCWSTR);
typedef BOOL(WINAPI *StartA)(LPCSTR, LPSTR, LPSECURITY_ATTRIBUTES, LPSECURITY_ATTRIBUTES, BOOL, DWORD, LPVOID, LPCSTR,
                             LPSTARTUPINFOA, LPPROCESS_INFORMATION);
static OpenA real_open_a;
static OpenW real_open_w;
static AttrA real_attr_a;
static AttrW real_attr_w;
static MakeA real_make_a;
static MakeW real_make_w;
static RemoveA real_remove_a;
static RemoveW real_remove_w;
static NameA real_name_a;
static NameW real_name_w;
static SetDirA real_setdir_a;
static GetDirA real_getdir_a;
static LoadA real_load_a;
static LoadW real_load_w;
static StartA real_start_a;

/* The list (redirect.h), read once at the start. g_listed: there is a list, so openDMT3 runs the game this way. */
static Redirects g_list;
static int g_listed;
/* The game folder as the current folder was when the DLL was loaded (the launcher's choice), as spelled. */
static WCHAR g_game[REDIRECT_PATH];
/* What GetModuleFileName answers for the client: its own file name, in the game folder. */
static WCHAR g_client_path[REDIRECT_PATH];
/* Every call into the log (measuring only). */
static int g_trace;
/* Writes into the game folder that the list does not take (each logged, up to a few). */
static LONG g_strays;
/* Measuring only: an archive's handle remembered when the game opens it (below, with the reads). */
static void note_pak(HANDLE h, const char *path);

/* ------------------------------------------------------------------------------------------------------- words */

/* A wide path as UTF-8 for the log (the log is bytes; a path may have any letters). */
static const char *utf8(const WCHAR *w, char *buf, int room)
{
    if (!w)
        return "(none)";
    if (!WideCharToMultiByte(CP_UTF8, 0, w, -1, buf, room, NULL, NULL))
        return "(not written)";
    return buf;
}

/* A path as the client gave it in the ANSI code page, made wide (MAX_PATH and beyond); 0 when it is not a path. */
static int widen(LPCSTR a, WCHAR *out, int room)
{
    return a && MultiByteToWideChar(CP_ACP, 0, a, -1, out, room) > 0;
}

/* Whether a call opens to write or makes the file (anything but reading what is there). */
static int writes(DWORD access, DWORD disposition)
{
    return (access & (GENERIC_WRITE | GENERIC_ALL | FILE_WRITE_DATA | FILE_APPEND_DATA | DELETE)) ||
           disposition == CREATE_ALWAYS || disposition == CREATE_NEW || disposition == OPEN_ALWAYS ||
           disposition == TRUNCATE_EXISTING;
}

/* -------------------------------------------------------------------------------------------------- the answer */

/* Where the client's path is really opened: openDMT3's file when the list names it (1, its path in `out`), else 0. */
static int served(const WCHAR *given, WCHAR *out, size_t room)
{
    if (!g_listed || !given || !given[0])
        return 0;
    WCHAR full[REDIRECT_PATH];
    /* The path made whole against the current folder, as Windows itself would open it. */
    DWORD n = GetFullPathNameW(given, REDIRECT_PATH, full, NULL);
    if (!n || n >= REDIRECT_PATH)
        return 0;
    return redirect_lookup(&g_list, full, out, room);
}

/* Whether a path is in the game folder (for the log's line about a write the list does not take). */
static int in_game(const WCHAR *given)
{
    WCHAR full[REDIRECT_PATH];
    DWORD n = GetFullPathNameW(given, REDIRECT_PATH, full, NULL);
    size_t g = wcslen(g_game);
    return n && n < REDIRECT_PATH && n > g && !_wcsnicmp(full, g_game, g) && full[g] == L'\\';
}

/* A write into the game folder outside the list: into the log, so a test sees it (the first ten). */
static void stray(const char *call, const WCHAR *given)
{
    if (!g_listed || !given || !in_game(given))
        return;
    LONG count = InterlockedIncrement(&g_strays);
    char buf[REDIRECT_PATH * 3];
    if (count <= 10)
        ingame_log("files: %s writes %s in the game folder (not one of openDMT3's)", call, utf8(given, buf, sizeof buf));
}

/* ---------------------------------------------------------------------------------------------------- opening */

static HANDLE WINAPI our_open_w(LPCWSTR name, DWORD access, DWORD share, LPSECURITY_ATTRIBUTES sa, DWORD disposition,
                                DWORD flags, HANDLE template_file)
{
    WCHAR mine[REDIRECT_PATH];
    int ours = served(name, mine, REDIRECT_PATH);
    HANDLE h = real_open_w(ours ? mine : name, access, share, sa, disposition, flags, template_file);
    DWORD err = GetLastError();
    if (!ours && writes(access, disposition))
        stray("CreateFileW", name);
    if (g_trace) {
        char a[REDIRECT_PATH * 3], b[REDIRECT_PATH * 3];
        ingame_log("files: CreateFileW %s access 0x%lx disposition %lu%s%s -> %s %lu", utf8(name, a, sizeof a),
                   (unsigned long)access, (unsigned long)disposition, ours ? " served from " : "",
                   ours ? utf8(mine, b, sizeof b) : "", h == INVALID_HANDLE_VALUE ? "error" : "open",
                   h == INVALID_HANDLE_VALUE ? (unsigned long)err : 0ul);
    }
    SetLastError(err);
    return h;
}

static HANDLE WINAPI our_open_a(LPCSTR name, DWORD access, DWORD share, LPSECURITY_ATTRIBUTES sa, DWORD disposition,
                                DWORD flags, HANDLE template_file)
{
    WCHAR wide[REDIRECT_PATH], mine[REDIRECT_PATH];
    int known = widen(name, wide, REDIRECT_PATH);
    int ours = known && served(wide, mine, REDIRECT_PATH);
    /* openDMT3's file by its wide path; the client's own by the very call it made. */
    HANDLE h = ours ? real_open_w(mine, access, share, sa, disposition, flags, template_file)
                    : real_open_a(name, access, share, sa, disposition, flags, template_file);
    DWORD err = GetLastError();
    note_pak(h, name);
    if (known && !ours && writes(access, disposition))
        stray("CreateFileA", wide);
    if (g_trace) {
        char b[REDIRECT_PATH * 3];
        ingame_log("files: CreateFileA %s access 0x%lx disposition %lu%s%s -> %s %lu", name ? name : "(none)",
                   (unsigned long)access, (unsigned long)disposition, ours ? " served from " : "",
                   ours ? utf8(mine, b, sizeof b) : "", h == INVALID_HANDLE_VALUE ? "error" : "open",
                   h == INVALID_HANDLE_VALUE ? (unsigned long)err : 0ul);
    }
    SetLastError(err);
    return h;
}

/* ------------------------------------------------------------------------------------------ is it there, folders */

static DWORD WINAPI our_attr_w(LPCWSTR name)
{
    WCHAR mine[REDIRECT_PATH];
    int ours = served(name, mine, REDIRECT_PATH);
    DWORD r = real_attr_w(ours ? mine : name);
    DWORD err = GetLastError();
    if (g_trace) {
        char a[REDIRECT_PATH * 3];
        ingame_log("files: GetFileAttributesW %s%s -> 0x%lx", utf8(name, a, sizeof a), ours ? " (openDMT3's)" : "",
                   (unsigned long)r);
    }
    SetLastError(err);
    return r;
}

static DWORD WINAPI our_attr_a(LPCSTR name)
{
    WCHAR wide[REDIRECT_PATH], mine[REDIRECT_PATH];
    int ours = widen(name, wide, REDIRECT_PATH) && served(wide, mine, REDIRECT_PATH);
    DWORD r = ours ? real_attr_w(mine) : real_attr_a(name);
    DWORD err = GetLastError();
    if (g_trace)
        ingame_log("files: GetFileAttributesA %s%s -> 0x%lx", name ? name : "(none)", ours ? " (openDMT3's)" : "",
                   (unsigned long)r);
    SetLastError(err);
    return r;
}

static BOOL WINAPI our_make_w(LPCWSTR name, LPSECURITY_ATTRIBUTES sa)
{
    WCHAR mine[REDIRECT_PATH];
    int ours = served(name, mine, REDIRECT_PATH);
    BOOL ok = real_make_w(ours ? mine : name, sa);
    DWORD err = GetLastError();
    if (!ours)
        stray("CreateDirectoryW", name);
    if (g_trace) {
        char a[REDIRECT_PATH * 3];
        ingame_log("files: CreateDirectoryW %s%s -> %d %lu", utf8(name, a, sizeof a), ours ? " (openDMT3's)" : "", ok,
                   ok ? 0ul : (unsigned long)err);
    }
    SetLastError(err);
    return ok;
}

static BOOL WINAPI our_make_a(LPCSTR name, LPSECURITY_ATTRIBUTES sa)
{
    WCHAR wide[REDIRECT_PATH], mine[REDIRECT_PATH];
    int known = widen(name, wide, REDIRECT_PATH);
    int ours = known && served(wide, mine, REDIRECT_PATH);
    BOOL ok = ours ? real_make_w(mine, sa) : real_make_a(name, sa);
    DWORD err = GetLastError();
    if (known && !ours)
        stray("CreateDirectoryA", wide);
    if (g_trace)
        ingame_log("files: CreateDirectoryA %s%s -> %d %lu", name ? name : "(none)", ours ? " (openDMT3's)" : "", ok,
                   ok ? 0ul : (unsigned long)err);
    SetLastError(err);
    return ok;
}

static BOOL WINAPI our_remove_a(LPCSTR name)
{
    WCHAR wide[REDIRECT_PATH], mine[REDIRECT_PATH];
    int known = widen(name, wide, REDIRECT_PATH);
    int ours = known && served(wide, mine, REDIRECT_PATH);
    BOOL ok = ours ? real_remove_w(mine) : real_remove_a(name);
    DWORD err = GetLastError();
    if (known && !ours)
        stray("DeleteFileA", wide);
    if (g_trace)
        ingame_log("files: DeleteFileA %s%s -> %d %lu", name ? name : "(none)", ours ? " (openDMT3's)" : "", ok,
                   ok ? 0ul : (unsigned long)err);
    SetLastError(err);
    return ok;
}

/* ------------------------------------------------------------------------------------------ the client's own path */

/* Whether GetModuleFileName asks about the client itself (its module, or NULL, which means the same). */
static int asks_client(HMODULE module)
{
    return !module || module == GetModuleHandleW(NULL);
}

/* GetModuleFileName's way with a buffer too small: as much as fits, ended, the size as the result, and the error. */
static DWORD answer_w(const WCHAR *path, LPWSTR out, DWORD size)
{
    DWORD n = (DWORD)wcslen(path);
    if (!size)
        return 0;
    if (n < size) {
        memcpy(out, path, (n + 1) * sizeof(WCHAR));
        SetLastError(ERROR_SUCCESS);
        return n;
    }
    memcpy(out, path, (size - 1) * sizeof(WCHAR));
    out[size - 1] = 0;
    SetLastError(ERROR_INSUFFICIENT_BUFFER);
    return size;
}

static DWORD WINAPI our_name_w(HMODULE module, LPWSTR out, DWORD size)
{
    if (!g_listed || !asks_client(module))
        return real_name_w(module, out, size);
    DWORD r = answer_w(g_client_path, out, size);
    if (g_trace) {
        char a[REDIRECT_PATH * 3];
        ingame_log("files: GetModuleFileNameW of the client -> %s", utf8(g_client_path, a, sizeof a));
    }
    return r;
}

static DWORD WINAPI our_name_a(HMODULE module, LPSTR out, DWORD size)
{
    if (!g_listed || !asks_client(module)) {
        DWORD r = real_name_a(module, out, size);
        if (g_trace)
            ingame_log("files: GetModuleFileNameA %p -> %s", (void *)module, r && out ? out : "(none)");
        return r;
    }
    char path[REDIRECT_PATH * 2];
    /* The game folder's path in the ANSI code page: the launcher gives a path it can be written in. */
    int n = WideCharToMultiByte(CP_ACP, 0, g_client_path, -1, path, sizeof path, NULL, NULL);
    if (n <= 0 || !size)
        return 0;
    DWORD len = (DWORD)strlen(path);
    DWORD r;
    if (len < size) {
        memcpy(out, path, len + 1);
        SetLastError(ERROR_SUCCESS);
        r = len;
    } else {
        memcpy(out, path, size - 1);
        out[size - 1] = 0;
        SetLastError(ERROR_INSUFFICIENT_BUFFER);
        r = size;
    }
    if (g_trace)
        ingame_log("files: GetModuleFileNameA of the client -> %s", path);
    return r;
}

/* ------------------------------------------------------------------------------- watched only (measuring) */

static BOOL WINAPI our_setdir_a(LPCSTR path)
{
    BOOL ok = real_setdir_a(path);
    DWORD err = GetLastError();
    if (g_trace)
        ingame_log("files: SetCurrentDirectoryA %s -> %d %lu", path ? path : "(none)", ok, ok ? 0ul : (unsigned long)err);
    SetLastError(err);
    return ok;
}

static DWORD WINAPI our_getdir_a(DWORD size, LPSTR out)
{
    DWORD r = real_getdir_a(size, out);
    if (g_trace)
        ingame_log("files: GetCurrentDirectoryA -> %s", r && r < size && out ? out : "(none)");
    return r;
}

static HMODULE WINAPI our_load_a(LPCSTR name)
{
    HMODULE m = real_load_a(name);
    DWORD err = GetLastError();
    if (g_trace) {
        char path[MAX_PATH] = "";
        if (m)
            real_name_a(m, path, sizeof path);
        ingame_log("files: LoadLibraryA %s -> %s", name ? name : "(none)", m ? path : "not loaded");
    }
    SetLastError(err);
    return m;
}

static HMODULE WINAPI our_load_w(LPCWSTR name)
{
    HMODULE m = real_load_w(name);
    DWORD err = GetLastError();
    if (g_trace) {
        char a[REDIRECT_PATH * 3];
        char path[MAX_PATH] = "";
        if (m)
            real_name_a(m, path, sizeof path);
        ingame_log("files: LoadLibraryW %s -> %s", utf8(name, a, sizeof a), m ? path : "not loaded");
    }
    SetLastError(err);
    return m;
}

static BOOL WINAPI our_start_a(LPCSTR app, LPSTR line, LPSECURITY_ATTRIBUTES pa, LPSECURITY_ATTRIBUTES ta, BOOL inherit,
                               DWORD flags, LPVOID env, LPCSTR dir, LPSTARTUPINFOA si, LPPROCESS_INFORMATION pi)
{
    if (g_trace)
        ingame_log("files: CreateProcessA %s %s in %s", app ? app : "(none)", line ? line : "(none)", dir ? dir : "(here)");
    return real_start_a(app, line, pa, ta, inherit, flags, env, dir, si, pi);
}

/* --------------------------------------------------------------------------- reads of the archives (measuring) */

/* The archives' handles and names while tracing, so a read can be told by archive and place. */
typedef BOOL(WINAPI *ReadFn)(HANDLE, LPVOID, DWORD, LPDWORD, LPOVERLAPPED);
typedef DWORD(WINAPI *SeekFn)(HANDLE, LONG, PLONG, DWORD);
typedef BOOL(WINAPI *SeekExFn)(HANDLE, LARGE_INTEGER, PLARGE_INTEGER, DWORD);
typedef HANDLE(WINAPI *MapFn)(HANDLE, LPSECURITY_ATTRIBUTES, DWORD, DWORD, DWORD, LPCSTR);
static ReadFn real_read;
static SeekFn real_seek;
static SeekExFn real_seek_ex;
static MapFn real_map;
static struct {
    HANDLE h;
    char name[64];
} g_paks[256];
static LONG g_npaks;

/* Remember an archive's handle when the game opens one (tracing only). */
static void note_pak(HANDLE h, const char *path)
{
    if (!g_trace || h == INVALID_HANDLE_VALUE || !path)
        return;
    const char *dot = strrchr(path, '.');
    if (!dot || _stricmp(dot, ".pak") != 0)
        return;
    const char *name = path + strlen(path);
    while (name > path && name[-1] != '\\' && name[-1] != '/')
        name--;
    LONG i = InterlockedIncrement(&g_npaks) - 1;
    if (i < 256) {
        g_paks[i].h = h;
        lstrcpynA(g_paks[i].name, name, sizeof g_paks[i].name);
    }
}

static const char *pak_of(HANDLE h)
{
    LONG n = g_npaks < 256 ? g_npaks : 256;
    for (LONG i = 0; i < n; i++)
        if (g_paks[i].h == h)
            return g_paks[i].name;
    return NULL;
}

static BOOL WINAPI our_read(HANDLE h, LPVOID buf, DWORD n, LPDWORD got, LPOVERLAPPED ov)
{
    const char *pak = pak_of(h);
    LARGE_INTEGER zero = {{0, 0}}, at = {{0, 0}};
    /* Where the read starts: the file pointer the game set before it. */
    if (pak)
        real_seek_ex(h, zero, &at, FILE_CURRENT);
    BOOL ok = real_read(h, buf, n, got, ov);
    if (pak)
        ingame_log("files: read %s at %lld, %lu bytes", pak, (long long)at.QuadPart, (unsigned long)n);
    return ok;
}

static HANDLE WINAPI our_map(HANDLE h, LPSECURITY_ATTRIBUTES sa, DWORD protect, DWORD high, DWORD low, LPCSTR name)
{
    const char *pak = pak_of(h);
    if (pak)
        ingame_log("files: CreateFileMappingA of %s", pak);
    return real_map(h, sa, protect, high, low, name);
}

/* ---------------------------------------------------------------------------------------------------- the list */

/* The list beside this DLL, read into g_list; 1 when there is one the launcher wrote. */
static int read_list(void)
{
    WCHAR path[REDIRECT_PATH];
    DWORD n = GetModuleFileNameW(g_module, path, REDIRECT_PATH);
    WCHAR *slash = n && n < REDIRECT_PATH ? wcsrchr(path, L'\\') : NULL;
    if (!slash || (size_t)(slash - path) + 32 >= REDIRECT_PATH)
        return 0;
    wcscpy(slash + 1, L"openDMT3-files.txt");
    HANDLE f = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    /* No list: openDMT3 put this DLL in the game folder (an earlier openDMT3, or a test), nothing to answer. */
    if (f == INVALID_HANDLE_VALUE)
        return 0;
    /* A list is a few hundred bytes; 256 KB is past anything the launcher writes. */
    static char text[256 * 1024];
    DWORD got = 0;
    BOOL ok = ReadFile(f, text, sizeof text, &got, NULL);
    CloseHandle(f);
    if (!ok || got == sizeof text) {
        ingame_log("files: the list beside the DLL could not be read whole: the game's own files only");
        return 0;
    }
    /* The DLL's folder: the list names openDMT3's files from there. */
    *slash = 0;
    int lines = redirect_parse(&g_list, g_game, path, text, got);
    if (lines < 0) {
        ingame_log("files: the list beside the DLL is not one openDMT3 writes: the game's own files only");
        memset(&g_list, 0, sizeof g_list);
        return 0;
    }
    char a[REDIRECT_PATH * 3];
    ingame_log("files: %d of openDMT3's files stand in for the game's in %s", lines, utf8(g_game, a, sizeof a));
    return 1;
}

/* --------------------------------------------------------------------------------------------------- attaching */

void files_attach(void)
{
    char value[16];
    g_trace = GetEnvironmentVariableA("OPENDMT3_FILES_TRACE", value, sizeof value) > 0;
    /* The game folder: the current folder the launcher started the client in, before any of the client's code ran. */
    DWORD n = GetCurrentDirectoryW(REDIRECT_PATH, g_game);
    if (!n || n >= REDIRECT_PATH)
        g_game[0] = 0;
    /* A root keeps its backslash ("D:\"); any other folder has none at its end. */
    size_t len = wcslen(g_game);
    while (len > 3 && g_game[len - 1] == L'\\')
        g_game[--len] = 0;
    g_listed = g_game[0] && read_list();
    if (g_listed) {
        /* The client is told it runs from the game folder, under its own file name. */
        WCHAR self[REDIRECT_PATH];
        DWORD s = GetModuleFileNameW(NULL, self, REDIRECT_PATH);
        const WCHAR *name = s && s < REDIRECT_PATH ? wcsrchr(self, L'\\') : NULL;
        if (name && len + wcslen(name) < REDIRECT_PATH) {
            wcscpy(g_client_path, g_game);
            wcscat(g_client_path, name);
        } else {
            g_listed = 0;
        }
    }
    HMODULE k = GetModuleHandleA("kernel32.dll");
    HMODULE game = GetModuleHandleA(NULL);
    /* Each real function by name, then every slot of the client's import table that holds it turned to ours. */
#define TURN(real, type, name, ours) \
    (real = (type)(void *)GetProcAddress(k, name), ingame_patch_imports(game, (void *)real, (void *)ours))
    int turned = TURN(real_open_a, OpenA, "CreateFileA", our_open_a) + TURN(real_open_w, OpenW, "CreateFileW", our_open_w) +
                 TURN(real_attr_a, AttrA, "GetFileAttributesA", our_attr_a) +
                 TURN(real_attr_w, AttrW, "GetFileAttributesW", our_attr_w) +
                 TURN(real_make_a, MakeA, "CreateDirectoryA", our_make_a) +
                 TURN(real_make_w, MakeW, "CreateDirectoryW", our_make_w) +
                 TURN(real_remove_a, RemoveA, "DeleteFileA", our_remove_a) +
                 TURN(real_name_a, NameA, "GetModuleFileNameA", our_name_a) +
                 TURN(real_name_w, NameW, "GetModuleFileNameW", our_name_w);
    /* DeleteFileW: the client has no slot for it, but openDMT3's answer to DeleteFileA uses it. */
    real_remove_w = (RemoveW)(void *)GetProcAddress(k, "DeleteFileW");
    if (g_trace)
        turned += TURN(real_setdir_a, SetDirA, "SetCurrentDirectoryA", our_setdir_a) +
                  TURN(real_getdir_a, GetDirA, "GetCurrentDirectoryA", our_getdir_a) +
                  TURN(real_load_a, LoadA, "LoadLibraryA", our_load_a) + TURN(real_load_w, LoadW, "LoadLibraryW", our_load_w) +
                  TURN(real_start_a, StartA, "CreateProcessA", our_start_a) +
                  TURN(real_read, ReadFn, "ReadFile", our_read) + TURN(real_map, MapFn, "CreateFileMappingA", our_map);
    real_seek = (SeekFn)(void *)GetProcAddress(k, "SetFilePointer");
    real_seek_ex = (SeekExFn)(void *)GetProcAddress(k, "SetFilePointerEx");
#undef TURN
    ingame_log("files: %d of the client's file calls turned to openDMT3's%s", turned, g_listed ? "" : " (no list: as they were)");
}
