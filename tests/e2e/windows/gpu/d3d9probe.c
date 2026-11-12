/*
 * What a 32-bit Windows program's pictures are drawn with under Wine, and whether Direct3D 9 draws them right
 * (tests/e2e/windows/gpu.sh check). Built 32-bit, as the game is, with the in-game layer's compiler.
 *
 *   wine d3d9probe.exe OUT.bmp [WAIT_MS]
 *   wine d3d9probe.exe --present WIDTH HEIGHT
 *
 * 1. OpenGL from this 32-bit process (what Wine's Direct3D 9 is made on): its vendor, renderer and version strings.
 *    In WoW64 Wine on WSL with Mesa's d3d12 driver the renderer names D3D12 and the GPU; on the CPU, llvmpipe.
 * 2. Direct3D 9: the adapter as Wine describes it, then a known picture in a 256 x 256 window: a clear colour, a red
 *    and a green rectangle (each edge's pixels in and out checked), a rectangle drawn by a pixel shader of known
 *    bytecode, an 8 x 8 checker texture with point sampling, a band of white half blended over the clear colour. The
 *    frame is read back, written to OUT.bmp, and 80 points of it are compared with the colours they must have.
 * 3. Two timings: the picture presented 300 times as fast as it goes (what a frame's handing over costs, its showing
 *    on the virtual screen included), and a fill of 500 blended quads over the window a frame, each frame waited for
 *    on the device (what drawing itself costs).
 *
 * --present: only what showing a frame costs, with nothing drawn in it: a window over the screen's WIDTH x HEIGHT, its
 * back buffer cleared and presented 300 times, each frame finished on the device (gpu/measure.sh: under Wine every
 * frame shown is copied to the container's virtual screen, on the GPU read back from the card first).
 *
 * Prints one line a finding; exit 0 when every point had its colour, 1 when one did not, 2 when nothing was drawn.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d9.h>
#include <GL/gl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* The window's and the back buffer's size. */
#define SIZE 256

/* A vertex already in the window's pixels with a colour; and one with a texture coordinate instead. */
typedef struct { float x, y, z, rhw; DWORD color; } ColorVertex;
typedef struct { float x, y, z, rhw; float u, v; } TexVertex;
#define FVF_COLOR (D3DFVF_XYZRHW | D3DFVF_DIFFUSE)
#define FVF_TEX (D3DFVF_XYZRHW | D3DFVF_TEX1)

/* ps_2_0: def c0, 1.0, 0.5, 0.25, 1.0; mov oC0, c0 (the colour 255, 128, 64 wherever it draws). */
static const DWORD SHADER[] = {
    0xFFFF0200,                                     /* ps_2_0 */
    0x05000051, 0xA00F0000,                         /* def c0 (write mask xyzw) */
    0x3F800000, 0x3F000000, 0x3E800000, 0x3F800000, /* 1.0, 0.5, 0.25, 1.0 */
    0x02000001, 0x800F0800, 0xA0E40000,             /* mov oC0, c0 (swizzle xyzw) */
    0x0000FFFF,                                     /* end */
};

/* The clear colour, and the two colours of the checker's texels. */
#define CLEAR_R 32
#define CLEAR_G 64
#define CLEAR_B 96
#define CHECK_A 0xFFFFFF00 /* yellow */
#define CHECK_B 0xFF0000FF /* blue */

/* The window procedure: nothing of its own (the window only carries the pictures). */
static LRESULT CALLBACK window_proc(HWND w, UINT m, WPARAM wp, LPARAM lp)
{
    return DefWindowProcA(w, m, wp, lp);
}

/* A top-level window at (x, 0), w x h inside, shown (on the virtual screen of the test's container). */
static HWND make_window_sized(const char *title, int x, int w, int h)
{
    static int registered;
    if (!registered) {
        WNDCLASSA wc = {0};
        wc.lpfnWndProc = window_proc;
        wc.hInstance = GetModuleHandleA(NULL);
        wc.lpszClassName = "d3d9probe";
        RegisterClassA(&wc);
        registered = 1;
    }
    /* A popup has no frame: its client area is exactly the SIZE x SIZE the screenshot reads. */
    HWND win = CreateWindowExA(0, "d3d9probe", title, WS_POPUP | WS_VISIBLE, x, 0, w, h, NULL, NULL,
                               GetModuleHandleA(NULL), NULL);
    ShowWindow(win, SW_SHOW);
    UpdateWindow(win);
    return win;
}

/* The picture's window: SIZE x SIZE. */
static HWND make_window(const char *title, int x)
{
    return make_window_sized(title, x, SIZE, SIZE);
}

/* 1. OpenGL from this process: a context on its own window (a window's pixel format is set once, so Direct3D gets
 *    another), its three strings printed. */
static void opengl_strings(void)
{
    HWND w = make_window("d3d9probe OpenGL", 300);
    HDC dc = GetDC(w);
    PIXELFORMATDESCRIPTOR pfd = {sizeof pfd, 1, PFD_DRAW_TO_WINDOW | PFD_SUPPORT_OPENGL | PFD_DOUBLEBUFFER,
                                 PFD_TYPE_RGBA, 32};
    int format = ChoosePixelFormat(dc, &pfd);
    if (!format || !SetPixelFormat(dc, format, &pfd)) {
        printf("opengl: no pixel format (%lu)\n", GetLastError());
        return;
    }
    HGLRC rc = wglCreateContext(dc);
    if (!rc || !wglMakeCurrent(dc, rc)) {
        printf("opengl: no context (%lu)\n", GetLastError());
        return;
    }
    /* The strings the driver gives: the renderer is the one that names what draws. */
    printf("opengl: vendor \"%s\", renderer \"%s\", version \"%s\"\n", (const char *)glGetString(GL_VENDOR),
           (const char *)glGetString(GL_RENDERER), (const char *)glGetString(GL_VERSION));
    wglMakeCurrent(NULL, NULL);
    wglDeleteContext(rc);
    ReleaseDC(w, dc);
    DestroyWindow(w);
}

/* A rectangle of one colour covering the pixels x0..x1-1, y0..y1-1 (Direct3D 9's pixel centres are on whole numbers:
 * the corners half a pixel up and left cover exactly those). */
static void fill_rect(IDirect3DDevice9 *dev, int x0, int y0, int x1, int y1, DWORD color)
{
    ColorVertex v[4] = {
        {x0 - 0.5f, y0 - 0.5f, 0, 1, color}, {x1 - 0.5f, y0 - 0.5f, 0, 1, color},
        {x0 - 0.5f, y1 - 0.5f, 0, 1, color}, {x1 - 0.5f, y1 - 0.5f, 0, 1, color},
    };
    IDirect3DDevice9_SetFVF(dev, FVF_COLOR);
    IDirect3DDevice9_DrawPrimitiveUP(dev, D3DPT_TRIANGLESTRIP, 2, v, sizeof v[0]);
}

/* The known picture (2): every part of it, on a cleared frame. */
static void draw_picture(IDirect3DDevice9 *dev, IDirect3DTexture9 *checker, IDirect3DPixelShader9 *shader)
{
    IDirect3DDevice9_Clear(dev, 0, NULL, D3DCLEAR_TARGET, D3DCOLOR_XRGB(CLEAR_R, CLEAR_G, CLEAR_B), 1.0f, 0);
    IDirect3DDevice9_BeginScene(dev);
    /* No lighting, no depth, no culling, the vertex colour as it is: the fixed pipeline's plainest state. */
    IDirect3DDevice9_SetRenderState(dev, D3DRS_LIGHTING, FALSE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_ZENABLE, D3DZB_FALSE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_CULLMODE, D3DCULL_NONE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_ALPHABLENDENABLE, FALSE);
    IDirect3DDevice9_SetTexture(dev, 0, NULL);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLOROP, D3DTOP_SELECTARG1);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLORARG1, D3DTA_DIFFUSE);
    /* The red and the green rectangle, top left and top right. */
    fill_rect(dev, 16, 16, 112, 112, D3DCOLOR_XRGB(255, 0, 0));
    fill_rect(dev, 144, 16, 240, 112, D3DCOLOR_XRGB(0, 255, 0));
    /* Bottom left: the pixel shader's colour (its vertex colour is never read). */
    IDirect3DDevice9_SetPixelShader(dev, shader);
    fill_rect(dev, 16, 144, 112, 240, D3DCOLOR_XRGB(0, 0, 0));
    IDirect3DDevice9_SetPixelShader(dev, NULL);
    /* Bottom right: the checker, each of its 8 x 8 texels 12 pixels square, sampled at the nearest texel. */
    IDirect3DDevice9_SetTexture(dev, 0, (IDirect3DBaseTexture9 *)checker);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLORARG1, D3DTA_TEXTURE);
    IDirect3DDevice9_SetSamplerState(dev, 0, D3DSAMP_MINFILTER, D3DTEXF_POINT);
    IDirect3DDevice9_SetSamplerState(dev, 0, D3DSAMP_MAGFILTER, D3DTEXF_POINT);
    TexVertex t[4] = {
        {143.5f, 143.5f, 0, 1, 0, 0}, {239.5f, 143.5f, 0, 1, 1, 0},
        {143.5f, 239.5f, 0, 1, 0, 1}, {239.5f, 239.5f, 0, 1, 1, 1},
    };
    IDirect3DDevice9_SetFVF(dev, FVF_TEX);
    IDirect3DDevice9_DrawPrimitiveUP(dev, D3DPT_TRIANGLESTRIP, 2, t, sizeof t[0]);
    IDirect3DDevice9_SetTexture(dev, 0, NULL);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_COLORARG1, D3DTA_DIFFUSE);
    /* The band across the middle: white at alpha 128 over the clear colour (source alpha, one less source alpha). */
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_ALPHAOP, D3DTOP_SELECTARG1);
    IDirect3DDevice9_SetTextureStageState(dev, 0, D3DTSS_ALPHAARG1, D3DTA_DIFFUSE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_ALPHABLENDENABLE, TRUE);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_SRCBLEND, D3DBLEND_SRCALPHA);
    IDirect3DDevice9_SetRenderState(dev, D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    fill_rect(dev, 0, 120, SIZE, 136, D3DCOLOR_ARGB(128, 255, 255, 255));
    IDirect3DDevice9_SetRenderState(dev, D3DRS_ALPHABLENDENABLE, FALSE);
    IDirect3DDevice9_EndScene(dev);
}

/* One point of the picture and the colour it must have (within 2 of each channel: rounding of a blend or a 0.5). */
typedef struct { int x, y; int r, g, b; } Point;

/* The 80 points: the clear colour in three gaps, each rectangle's middle and the pixels on both sides of the red's
 * four edges, the band twice, and the middle of every texel of the checker. */
static int points(Point *p)
{
    int n = 0;
    /* The clear colour: between the top rectangles, left of the band's end, the bottom right corner. */
    p[n++] = (Point){128, 64, CLEAR_R, CLEAR_G, CLEAR_B};
    p[n++] = (Point){8, 8, CLEAR_R, CLEAR_G, CLEAR_B};
    p[n++] = (Point){250, 250, CLEAR_R, CLEAR_G, CLEAR_B};
    /* The red's middle and its edges: its first and last pixel in, the next one out, on each side. */
    p[n++] = (Point){64, 64, 255, 0, 0};
    p[n++] = (Point){16, 64, 255, 0, 0};
    p[n++] = (Point){15, 64, CLEAR_R, CLEAR_G, CLEAR_B};
    p[n++] = (Point){111, 64, 255, 0, 0};
    p[n++] = (Point){112, 64, CLEAR_R, CLEAR_G, CLEAR_B};
    p[n++] = (Point){64, 16, 255, 0, 0};
    p[n++] = (Point){64, 15, CLEAR_R, CLEAR_G, CLEAR_B};
    p[n++] = (Point){64, 111, 255, 0, 0};
    p[n++] = (Point){64, 112, CLEAR_R, CLEAR_G, CLEAR_B};
    /* The green's middle, the shader's colour (0.5 is 127.5: either side within the tolerance). */
    p[n++] = (Point){192, 64, 0, 255, 0};
    p[n++] = (Point){64, 192, 255, 128, 64};
    /* The band: 255 * 128/255 + clear * 127/255 in each channel. */
    for (int i = 0; i < 2; i++) {
        int x = i ? 128 : 4, y = i ? 128 : 124;
        p[n++] = (Point){x, y, (255 * 128 + CLEAR_R * 127 + 127) / 255, (255 * 128 + CLEAR_G * 127 + 127) / 255,
                         (255 * 128 + CLEAR_B * 127 + 127) / 255};
    }
    /* The checker: texel (i, j) yellow when i + j is even, blue when odd. */
    for (int j = 0; j < 8; j++)
        for (int i = 0; i < 8; i++)
            p[n++] = (i + j) % 2 ? (Point){150 + 12 * i, 150 + 12 * j, 0, 0, 255}
                                 : (Point){150 + 12 * i, 150 + 12 * j, 255, 255, 0};
    return n;
}

/* The frame read back from the device: compared with the points, written to a 24-bit BMP. Returns the points that
 * had their colour, or -1 when it could not be read. */
static int check_and_write(IDirect3DDevice9 *dev, const char *bmp, int *total)
{
    IDirect3DSurface9 *back = NULL, *copy = NULL;
    D3DLOCKED_RECT lr;
    if (FAILED(IDirect3DDevice9_GetBackBuffer(dev, 0, 0, D3DBACKBUFFER_TYPE_MONO, &back)) ||
        FAILED(IDirect3DDevice9_CreateOffscreenPlainSurface(dev, SIZE, SIZE, D3DFMT_X8R8G8B8, D3DPOOL_SYSTEMMEM, &copy,
                                                            NULL)) ||
        FAILED(IDirect3DDevice9_GetRenderTargetData(dev, back, copy)) ||
        FAILED(IDirect3DSurface9_LockRect(copy, &lr, NULL, D3DLOCK_READONLY)))
        return -1;
    Point p[96];
    int n = points(p), good = 0;
    *total = n;
    for (int i = 0; i < n; i++) {
        DWORD c = ((const DWORD *)((const BYTE *)lr.pBits + p[i].y * lr.Pitch))[p[i].x];
        int r = (c >> 16) & 0xff, g = (c >> 8) & 0xff, b = c & 0xff;
        if (abs(r - p[i].r) <= 2 && abs(g - p[i].g) <= 2 && abs(b - p[i].b) <= 2)
            good++;
        else
            printf("picture: at %d,%d %d,%d,%d where %d,%d,%d belongs\n", p[i].x, p[i].y, r, g, b, p[i].r, p[i].g,
                   p[i].b);
    }
    /* The BMP: its two headers, then the rows bottom up, three bytes a pixel (blue, green, red). */
    FILE *f = fopen(bmp, "wb");
    if (f) {
        BITMAPFILEHEADER fh = {0x4D42, sizeof fh + sizeof(BITMAPINFOHEADER) + SIZE * SIZE * 3, 0, 0,
                               sizeof fh + sizeof(BITMAPINFOHEADER)};
        BITMAPINFOHEADER ih = {sizeof ih, SIZE, SIZE, 1, 24, BI_RGB, SIZE * SIZE * 3, 2835, 2835, 0, 0};
        fwrite(&fh, sizeof fh, 1, f);
        fwrite(&ih, sizeof ih, 1, f);
        for (int y = SIZE - 1; y >= 0; y--) {
            const DWORD *row = (const DWORD *)((const BYTE *)lr.pBits + y * lr.Pitch);
            for (int x = 0; x < SIZE; x++) {
                BYTE px[3] = {row[x] & 0xff, (row[x] >> 8) & 0xff, (row[x] >> 16) & 0xff};
                fwrite(px, 3, 1, f);
            }
        }
        fclose(f);
    }
    IDirect3DSurface9_UnlockRect(copy);
    IDirect3DSurface9_Release(copy);
    IDirect3DSurface9_Release(back);
    return good;
}

/* Milliseconds between two readings of the performance counter. */
static double ms_between(LARGE_INTEGER a, LARGE_INTEGER b)
{
    LARGE_INTEGER f;
    QueryPerformanceFrequency(&f);
    return (double)(b.QuadPart - a.QuadPart) * 1000.0 / (double)f.QuadPart;
}

/* Wait until everything sent to the device so far is done (an event query, flushed). */
static void finish(IDirect3DDevice9 *dev, IDirect3DQuery9 *q)
{
    IDirect3DQuery9_Issue(q, D3DISSUE_END);
    while (IDirect3DQuery9_GetData(q, NULL, 0, D3DGETDATA_FLUSH) == S_FALSE)
        ;
}

/* --present: a window over the screen, its frame cleared and presented 300 times, each finished on the device. */
static int present_only(int w, int h)
{
    HWND win = make_window_sized("d3d9probe present", 0, w, h);
    IDirect3D9 *d3d = Direct3DCreate9(D3D_SDK_VERSION);
    D3DPRESENT_PARAMETERS pp = {0};
    pp.BackBufferWidth = (UINT)w;
    pp.BackBufferHeight = (UINT)h;
    pp.BackBufferFormat = D3DFMT_X8R8G8B8;
    pp.BackBufferCount = 1;
    pp.SwapEffect = D3DSWAPEFFECT_DISCARD;
    pp.hDeviceWindow = win;
    pp.Windowed = TRUE;
    pp.PresentationInterval = D3DPRESENT_INTERVAL_IMMEDIATE;
    IDirect3DDevice9 *dev = NULL;
    IDirect3DQuery9 *q = NULL;
    if (!d3d || FAILED(IDirect3D9_CreateDevice(d3d, D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, win,
                                               D3DCREATE_HARDWARE_VERTEXPROCESSING, &pp, &dev)) ||
        FAILED(IDirect3DDevice9_CreateQuery(dev, D3DQUERYTYPE_EVENT, &q))) {
        printf("present: no device\n");
        return 2;
    }
    /* A few frames first (the first ones make the window's own surfaces), then the 300 timed. */
    LARGE_INTEGER t0, t1;
    for (int i = -30; i < 300; i++) {
        if (!i)
            QueryPerformanceCounter(&t0);
        IDirect3DDevice9_Clear(dev, 0, NULL, D3DCLEAR_TARGET, D3DCOLOR_XRGB(i & 255, 64, 96), 1.0f, 0);
        IDirect3DDevice9_Present(dev, NULL, NULL, NULL, NULL);
        finish(dev, q);
    }
    QueryPerformanceCounter(&t1);
    double ms = ms_between(t0, t1) / 300;
    printf("present: %dx%d cleared and presented %.3f ms a frame (%.0f a second)\n", w, h, ms, 1000.0 / ms);
    IDirect3DQuery9_Release(q);
    IDirect3DDevice9_Release(dev);
    IDirect3D9_Release(d3d);
    DestroyWindow(win);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc > 3 && !strcmp(argv[1], "--present"))
        return present_only(atoi(argv[2]), atoi(argv[3]));
    const char *bmp = argc > 1 ? argv[1] : "d3d9probe.bmp";
    /* Said first: this process's own width (the game's is 32-bit). */
    printf("process: %d-bit\n", (int)sizeof(void *) * 8);
    opengl_strings();
    /* 2. Direct3D 9 and its adapter as Wine describes it (its name is Wine's guess from the OpenGL strings). */
    IDirect3D9 *d3d = Direct3DCreate9(D3D_SDK_VERSION);
    if (!d3d) {
        printf("d3d9: no Direct3D 9\n");
        return 2;
    }
    D3DADAPTER_IDENTIFIER9 id;
    if (SUCCEEDED(IDirect3D9_GetAdapterIdentifier(d3d, 0, 0, &id)))
        printf("d3d9: adapter \"%s\", vendor 0x%04lx, device 0x%04lx, driver \"%s\"\n", id.Description, id.VendorId,
               id.DeviceId, id.Driver);
    HWND w = make_window("d3d9probe", 0);
    D3DPRESENT_PARAMETERS pp = {0};
    pp.BackBufferWidth = SIZE;
    pp.BackBufferHeight = SIZE;
    pp.BackBufferFormat = D3DFMT_X8R8G8B8;
    pp.BackBufferCount = 1;
    pp.SwapEffect = D3DSWAPEFFECT_DISCARD;
    pp.hDeviceWindow = w;
    pp.Windowed = TRUE;
    /* As fast as frames go (no wait for a refresh): the timings below measure the work, not a display. */
    pp.PresentationInterval = D3DPRESENT_INTERVAL_IMMEDIATE;
    IDirect3DDevice9 *dev = NULL;
    HRESULT hr = IDirect3D9_CreateDevice(d3d, D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, w, D3DCREATE_HARDWARE_VERTEXPROCESSING,
                                         &pp, &dev);
    if (FAILED(hr)) {
        printf("d3d9: no device (0x%08lx)\n", (unsigned long)hr);
        return 2;
    }
    /* The checker texture: 8 x 8 texels in the managed pool, filled by hand. */
    IDirect3DTexture9 *checker = NULL;
    D3DLOCKED_RECT lr;
    IDirect3DDevice9_CreateTexture(dev, 8, 8, 1, 0, D3DFMT_A8R8G8B8, D3DPOOL_MANAGED, &checker, NULL);
    if (!checker || FAILED(IDirect3DTexture9_LockRect(checker, 0, &lr, NULL, 0))) {
        printf("d3d9: no texture\n");
        return 2;
    }
    for (int y = 0; y < 8; y++)
        for (int x = 0; x < 8; x++)
            ((DWORD *)((BYTE *)lr.pBits + y * lr.Pitch))[x] = (x + y) % 2 ? CHECK_B : CHECK_A;
    IDirect3DTexture9_UnlockRect(checker, 0);
    /* The pixel shader from its bytecode (no compiler needed). */
    IDirect3DPixelShader9 *shader = NULL;
    if (FAILED(IDirect3DDevice9_CreatePixelShader(dev, SHADER, &shader))) {
        printf("d3d9: the pixel shader was refused\n");
        return 2;
    }
    draw_picture(dev, checker, shader);
    int total = 0, good = check_and_write(dev, bmp, &total);
    if (good < 0) {
        printf("d3d9: the frame could not be read back\n");
        return 2;
    }
    printf("picture: %d of %d points as they must be, written to %s\n", good, total, bmp);
    /* Shown in the window, so the screen can be compared with what was read back. */
    IDirect3DDevice9_Present(dev, NULL, NULL, NULL, NULL);
    IDirect3DQuery9 *q = NULL;
    IDirect3DDevice9_CreateQuery(dev, D3DQUERYTYPE_EVENT, &q);
    /* 3a. The picture drawn and presented 300 times, as fast as it goes. */
    LARGE_INTEGER t0, t1;
    QueryPerformanceCounter(&t0);
    for (int i = 0; i < 300; i++) {
        draw_picture(dev, checker, shader);
        IDirect3DDevice9_Present(dev, NULL, NULL, NULL, NULL);
    }
    if (q)
        finish(dev, q);
    QueryPerformanceCounter(&t1);
    double present_ms = ms_between(t0, t1) / 300;
    printf("timing: the picture drawn and presented %.3f ms a frame (%.0f a second)\n", present_ms, 1000.0 / present_ms);
    /* 3b. Drawing alone: 500 quads of white at alpha 16 over the whole window a frame, each frame finished on the
     *     device, 30 frames (32 million blended pixels a frame). */
    double fill_ms = -1;
    if (q) {
        QueryPerformanceCounter(&t0);
        for (int f = 0; f < 30; f++) {
            IDirect3DDevice9_BeginScene(dev);
            IDirect3DDevice9_SetPixelShader(dev, NULL);
            IDirect3DDevice9_SetRenderState(dev, D3DRS_ALPHABLENDENABLE, TRUE);
            for (int i = 0; i < 500; i++)
                fill_rect(dev, 0, 0, SIZE, SIZE, D3DCOLOR_ARGB(16, 255, 255, 255));
            IDirect3DDevice9_EndScene(dev);
            finish(dev, q);
        }
        QueryPerformanceCounter(&t1);
        fill_ms = ms_between(t0, t1) / 30;
        printf("timing: 500 blended quads over the window %.3f ms a frame, finished on the device\n", fill_ms);
        IDirect3DQuery9_Release(q);
    }
    /* The known picture again, last, so the window shows it for the screenshot. */
    draw_picture(dev, checker, shader);
    IDirect3DDevice9_Present(dev, NULL, NULL, NULL, NULL);
    fflush(stdout);
    /* A moment for the screenshot (the test takes it while this waits). */
    Sleep(argc > 2 ? atoi(argv[2]) : 0);
    IDirect3DPixelShader9_Release(shader);
    IDirect3DTexture9_Release(checker);
    IDirect3DDevice9_Release(dev);
    IDirect3D9_Release(d3d);
    DestroyWindow(w);
    return good == total ? 0 : 1;
}
