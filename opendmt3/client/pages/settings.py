"""SCREEN, SOUND, CONTROLS and GAME: the settings, on cards as OpenDMTQ's pages set theirs (the client data's files
change only at PLAY)."""

import logging
import os
import threading
import tkinter as tk

from opendmt3.core import game as g
from opendmt3.core.cabinet import values as choices
from opendmt3.client import actions, dialogs, theme, widgets

log = logging.getLogger("opendmt3.launcher")
from opendmt3.client.pages.common import card


# -------------------------------------------------------------------------------------------- Screen


def _work_area(app):
    """The monitor size in the launcher's pixels, to leave out window sizes that would not fit."""
    return app.root.winfo_screenwidth(), app.root.winfo_screenheight()


def _row(card_, ui, title, control, hint, first=False):
    """A setting row on a card, parted from the row before it by the card's faint line."""
    if not first:
        widgets.divider(card_.body, ui)
    widgets.setting_row(card_.body, ui, title, control, hint).pack(fill="x")


def build_screen(app, parent):
    """Four cards, as OpenDMTQ's SCREEN has its Display, Frames and Quality: the display (full screen or a window, its
    size), the frames (VSync, their pacing, motion clarity, the FPS counter), the picture (its shape, the size it is
    drawn at, its enlarging and smoothing, glow, the videos) and the experiments."""
    ui, w, v = app.ui, app.words, app.state.values
    redraw = lambda: app.redraw("screen")  # noqa: E731  (the page drawn again in place)
    mode = v["display_mode"]

    def set_mode(value):
        app.changed("display_mode", value)
        # The size row and the hint depend on the mode: draw the page again.
        redraw()

    display = card(parent, ui, w("screen.display"))
    _row(display, ui, w("screen.mode"),
         lambda p: widgets.Segmented(p, ui, [("fullscreen", w("screen.mode.fullscreen")),
                                             ("window", w("screen.mode.window"))], mode, set_mode),
         w("screen.mode.hint." + mode), first=True)
    sw, sh = _work_area(app)
    # Sizes that fit the monitor with room for the title bar and the taskbar; the smallest always stays.
    sizes = [s for s in choices.WINDOW_SIZES
             if s == choices.WINDOW_SIZES[0] or (int(s.split("x")[0]) <= sw and int(s.split("x")[1]) + 80 <= sh)]
    if mode == "window":
        _row(display, ui, w("screen.size"),
             lambda p: widgets.Select(p, ui, [(s, s.replace("x", " × ")) for s in sizes], v["window_size"],
                                      lambda s: app.changed("window_size", s), width=16),
             w("screen.size.hint"))
    frames = card(parent, ui, w("screen.frames"))
    _row(frames, ui, w("screen.vsync"), lambda p: widgets.Toggle(p, ui, v["vsync"], lambda on: app.changed("vsync", on)),
         w("screen.vsync.hint"), first=True)
    # The game's logic runs once a frame, so it stays at 60 a second; how those frames are paced is the choice.
    _row(frames, ui, w("screen.pacing"),
         lambda p: widgets.Segmented(p, ui, [(value, w("screen.pacing." + value)) for value in choices.FRAME_PACINGS],
                                     v["frame_pacing"], lambda value: app.changed("frame_pacing", value)),
         w("screen.pacing.hint"))
    # Motion clarity: only on a main screen at a whole multiple of 60 Hz from 120 up, where each frame has whole
    # refreshes of its own to be lit over (the in-game overlay turns it off on any other).
    from opendmt3.client import window_room
    if window_room.strobe_offered(window_room.refresh_rate()):
        _row(frames, ui, w("screen.motion"),
             lambda p: widgets.Segmented(p, ui, [(value, w("screen.motion." + value))
                                                 for value in choices.MOTION_CLARITIES],
                                         v["motion_clarity"], lambda value: app.changed("motion_clarity", value)),
             w("screen.motion.hint"))

    def set_fps(on):
        app.changed("show_fps", on)
        # The corner's row is there only while the counter is on, and the hint says the state: draw the page again.
        redraw()

    _row(frames, ui, w("screen.fps"), lambda p: widgets.Toggle(p, ui, v["show_fps"], set_fps),
         w("screen.fps.hint." + ("on" if v["show_fps"] else "off")))
    if v["show_fps"]:
        # Its corner, a choice of its own (kept while the counter is off, for the next time it is on).
        _row(frames, ui, w("screen.fps.position"),
             lambda p: widgets.Select(p, ui, [(c, w("screen.fps.position." + c)) for c in choices.FPS_POSITIONS],
                                      v["fps_position"], lambda c: app.changed("fps_position", c), width=16),
             w("screen.fps.position.hint"))
    picture = card(parent, ui, w("screen.picture"))
    # The game's 5:3 picture in a screen of another shape: kept with bars beside it, or stretched to fill it.
    _row(picture, ui, w("screen.shape"),
         lambda p: widgets.Segmented(p, ui, [(value, w("screen.shape." + value)) for value in choices.PICTURE_SHAPES],
                                     v["picture_shape"], lambda value: app.changed("picture_shape", value)),
         w("screen.shape.hint"), first=True)
    render = v["render_size"]

    def set_render(value):
        app.changed("render_size", value)
        # The upscale filter's rows are there only while the game draws at its own size: draw the page again.
        redraw()

    # The game drawn at its own 1280x768 and enlarged, or at the screen's size (the in-game overlay's render.c).
    _row(picture, ui, w("screen.render"),
         lambda p: widgets.Segmented(p, ui, [(value, w("screen.render." + value)) for value in choices.RENDER_SIZES],
                                     render, set_render),
         w("screen.render.hint." + render))
    upscale = v["upscale"]

    def set_upscale(value):
        app.changed("upscale", value)
        # The sharpness row shows only for the filters that sharpen: draw the page again.
        redraw()

    # The in-game overlay's enlarging of the 1280x768 picture to the window, only while the game draws at its own
    # size; five choices fit one row of choices.
    if render == "game":
        _row(picture, ui, w("screen.upscale"),
             lambda p: widgets.Segmented(p, ui, [(value, w("screen.upscale." + value)) for value in choices.UPSCALES],
                                         upscale, set_upscale),
             w("screen.upscale.hint"))
    if render == "game" and upscale in choices.SHARPENING_UPSCALES:
        # Only FSR 1 and NIS read the sharpness; for the others the row would change nothing, so it is left out.
        _row(picture, ui, w("screen.sharpness"),
             lambda p: widgets.Slider(p, ui, v["sharpness"], lambda val: app.changed("sharpness", val)),
             w("screen.sharpness.hint"))
    # Drawn at the screen's size, nothing is enlarged after the anti-aliasing: its hint says where it runs then.
    aa_hint = "screen.antialiasing.hint" if render == "game" else "screen.antialiasing.hint.display"
    # Nine choices are too many for a row of choices: a drop-down, as the window sizes are.
    _row(picture, ui, w("screen.antialiasing"),
         lambda p: widgets.Select(p, ui, [(value, w("screen.antialiasing." + value)) for value in choices.ANTIALIASINGS],
                                  v["antialiasing"], lambda value: app.changed("antialiasing", value), width=16),
         w(aa_hint))
    for name, key in (("glow", "screen.glow"), ("videos", "screen.videos")):
        _row(picture, ui, w(key), lambda p, n=name: widgets.Toggle(p, ui, v[n], lambda on, n=n: app.changed(n, on)),
             w(key + ".hint"))
    advanced = card(parent, ui, w("screen.advanced"), last=True)
    _row(advanced, ui, w("screen.preload"),
         lambda p: widgets.Toggle(p, ui, v["preload"], lambda on: app.changed("preload", on)),
         w("screen.preload.hint"), first=True)
    # The picture's GPU time by pass, measured while the game runs and logged when it closes (a report carries it).
    _row(advanced, ui, w("screen.pass_times"),
         lambda p: widgets.Toggle(p, ui, v["pass_times"], lambda on: app.changed("pass_times", on)),
         w("screen.pass_times.hint"))
    # Direct3D 9Ex's flip model for the borderless full screen, an experiment (the copy model unless it is on).
    _row(advanced, ui, w("screen.flip"),
         lambda p: widgets.Toggle(p, ui, v["flip_model"], lambda on: app.changed("flip_model", on)),
         w("screen.flip.hint"))


# --------------------------------------------------------------------------------------------- Sound


def build_sound(app, parent):
    """Two cards, as OpenDMTQ's SOUND: the volumes, and the output (the device, who mixes, low latency, how late the
    device plays)."""
    ui, w, v = app.ui, app.words, app.state.values
    redraw = lambda: app.redraw("sound")  # noqa: E731  (the page drawn again in place)
    volume = card(parent, ui, w("sound.volumes"))
    for i, (name, key) in enumerate((("music_volume", "sound.music"), ("key_volume", "sound.keys"))):
        _row(volume, ui, w(key),
             lambda p, n=name: widgets.Slider(p, ui, v[n], lambda val, n=n: app.changed(n, val)),
             w(key + ".hint"), first=i == 0)
    output = card(parent, ui, w("sound.output"), last=True)
    # Windows' output devices, as DirectSound names them (the game plays through DirectSound).
    from opendmt3.client import sound_devices
    devices = sound_devices.listed()
    chosen = v["sound_device"]
    options = [("default", w("sound.device.default"))] + [(guid, name) for guid, name in devices]
    gone = sound_devices.chosen_is_gone(chosen, devices)
    if gone:
        # Kept in the list so the choice shows, and said in the hint: the game plays on the default meanwhile.
        options.append((chosen, w("sound.device.missing")))
    _row(output, ui, w("sound.device"),
         lambda p: widgets.Select(p, ui, options, chosen, lambda value: (app.changed("sound_device", value), redraw()),
                                  width=30),
         w("sound.device.gone") if gone else w("sound.device.hint"), first=True)
    # Who mixes the game's sounds (native/cardreader/openal.c): Windows' DirectSound, or OpenAL Soft sharing the device
    # or having it to itself; after a game where OpenAL Soft did not open, the page says DirectSound played instead.
    session = app.state.last_session or {}
    mixer = v["sound_path"]
    mixer_hint = w("sound.mixer.hint")
    fell_back = actions.sound_mixer_line(session.get("sound_mixer"), mixer, chosen)
    if fell_back:
        mixer_hint += " " + w(fell_back)

    def set_mixer(value):
        app.changed("sound_path", value)
        # The last game's line under it is for the Mixer chosen: draw the page again.
        redraw()

    _row(output, ui, w("sound.mixer"),
         lambda p: widgets.Segmented(p, ui, [(value, w("sound.mixer." + value)) for value in choices.SOUND_PATHS],
                                     mixer, set_mixer),
         mixer_hint)
    # Windows' sound engine at the shortest period that device offers while the game runs (native/cardreader/engine.c);
    # after a game on the device chosen now, the period it ran at (the in-game overlay's note, actions.sound_notes).
    hint = w("sound.low_latency.hint")
    last = (actions.sound_engine_line(session.get("sound_engine"), chosen) if v["low_latency"] else None)
    if last:
        hint += " " + w(last[0], **last[1])

    def set_low_latency(on):
        app.changed("low_latency", on)
        # The last game's line shows only while it is on: draw the page again.
        redraw()

    _row(output, ui, w("sound.low_latency"), lambda p: widgets.Toggle(p, ui, v["low_latency"], set_low_latency), hint)
    # How late the device plays: the in-game overlay's music lock keeps a song's frames that much behind its music.
    low, high = choices.AUDIO_OFFSET_RANGE
    _row(output, ui, w("sound.offset"),
         lambda p: widgets.Slider(p, ui, v["audio_offset"], lambda val: app.changed("audio_offset", val),
                                  low=low, high=high, unit=" ms"),
         w("sound.offset.hint"))


# ------------------------------------------------------------------------------------------ Controls


def build_controls(app, parent):
    """Two cards: what the player plays with, and what the game takes from it, a line each parted by the card's faint
    lines, as OpenDMTQ's CONTROLS sets its lines."""
    ui, w, v = app.ui, app.words, app.state.values
    device = "mouse" if v["cursor"] else "touch"

    def set_device(value):
        # A touch screen needs no pointer drawn over the game; a mouse does.
        app.changed("cursor", value == "mouse")
        app.redraw("controls")

    input_card = card(parent, ui, w("controls.device"))
    _row(input_card, ui, w("controls.input"),
         lambda p: widgets.Segmented(p, ui, [("mouse", w("controls.input.mouse")),
                                             ("touch", w("controls.input.touch"))], device, set_device),
         w("controls.input.hint." + device), first=True)
    in_game = card(parent, ui, w("controls.ingame"), last=True)
    for i, key in enumerate(("controls.tap", "controls.drag", "controls.hold", "controls.edge")):
        if i:
            widgets.divider(in_game.body, ui, pady=9)
        widgets.label(in_game.body, ui, w(key), wrap_margin=0).pack(fill="x")


# ---------------------------------------------------------------------------------------------- Game


def _look(app):
    """What the folder in use is (client/intake.py), looked at once per folder and off the window's thread: until it
    is known the card says it is being checked, and the page shows again when it is."""
    from opendmt3.client import intake
    folder = app.state.game_folder
    looked = getattr(app, "folder_look", None)
    if looked is not None and os.path.normcase(looked.path) == os.path.normcase(folder):
        return looked
    checking = app.folder_look = intake.Found(folder)

    def work():
        found = intake.inspect(folder)
        # The folder found at or below the path chosen keeps the chosen path as its key.
        found.path = folder if found.kind != intake.FOLDER else found.path

        def show():
            if app.folder_look is checking:
                app.folder_look = found
                # Shown again only when the Game page of that same folder is still on the screen.
                if app.page == "game":
                    app.go("game")
        app.post(show)

    threading.Thread(target=work, daemon=True, name="look").start()
    return checking


def _thumbs(app):
    """Three of the folder's jackets for its card: the ones the PLAY page's header read (app.discs), made once into
    the card's size."""
    from PIL import Image, ImageTk
    discs = app.discs or []
    kept = getattr(app, "game_thumbs", None)
    if kept is not None and kept[0] is discs:
        return kept[1]
    size = app.ui.px(34)
    images = [ImageTk.PhotoImage(d.resize((size, size), Image.LANCZOS), master=app.root) for d in discs[:3]]
    app.game_thumbs = (discs, images)
    return images


def build_game(app, parent):
    """The client data in use on its card (the same card as the guide's DISC CHECK, with what can be done with it) and
    the list to change it under it; the cabinet's settings; the cabinet's operator data once there is some. Each on a
    card of the page, as the other pages have theirs."""
    from opendmt3.client import cards, found_list, intake
    ui, w = app.ui, app.words
    files = card(parent, ui, w("game.files"))
    folder = app.state.game_folder
    opened = getattr(app, "game_list", None)

    def close_list():
        # A folder picked from the list is the one in use: the card says what it is, the list closes.
        if app.game_list is not None:
            app.game_list.stop()
        app.game_list = None
        app.folder_look = None
        app.go("game")

    def change():
        # The same list as the guide's DISC CHECK, under the card; Change... again closes it.
        if app.game_list is None:
            app.game_list = found_list.FoundList(app, on_pick=close_list, hide_chosen=True)
            app.go("game")
        else:
            close_list()

    def put_back(found):
        if found_list.put_back_folder(app, found):
            # Looked at again: what openDMT3 changed is gone from the card.
            app.folder_look = None
            app.go("game")

    if folder:
        found = _look(app)
        # The card's buttons: change the folder, open it, and the song list for a server (saved into a file, or sent
        # to the server this launcher is signed in to as its admin).
        extra = [(w("game.change"), change), (w("common.open"), lambda: actions.open_folder(folder))]
        # The song list comes only from a folder that reads: one that does not (damaged, the cabinet's) offers none.
        ready = found.state == intake.READY
        if ready:
            extra.append((w("game.songlist.save"), lambda: save_song_list(app)))
            if actions.is_server_admin(app.state):
                extra.append((w("game.songlist.send"), lambda: send_song_list(app)))
        cards.Card(files.body, app, found, chosen=ready, on_put_back=put_back, extra=extra,
                   thumbs=_thumbs(app)).pack(fill="x")
        if ready:
            # The song list said once where it is first shown: what its button makes, and what it holds.
            widgets.label(files.body, ui, w("game.songlist.hint"), font=ui.fonts.small, fg=theme.MUTED,
                          wrap_margin=0).pack(fill="x", pady=(ui.px(8), 0))
    else:
        # Nothing chosen yet: the card says so, and the list to choose from is open under it.
        found = intake.Found(w("game.folder.none"), state=intake.NOT_YET)
        found.line, found.tone = ("game.folder.choose", {}), intake.NOTE
        cards.Card(files.body, app, found).pack(fill="x")
        if opened is None:
            opened = app.game_list = found_list.FoundList(app, on_pick=close_list, hide_chosen=True)
    if opened is not None:
        # The list to change to, under the card in use, on the same card of the page.
        widgets.divider(files.body, ui, pady=14)
        box = tk.Frame(files.body, bg=theme.PANEL)
        box.pack(fill="x")
        opened.build(box)
    # The operator data is kept in openDMT3's own folder, made at the first PLAY: its card shows once there is a
    # folder to open (a heading over nothing says nothing).
    data = app.state.own().path(g.DATA_DIR)
    cabinet = card(parent, ui, w("game.cabinet"), last=not os.path.isdir(data))
    _row(cabinet, ui, w("game.freeplay"),
         lambda p: widgets.label(p, ui, w("common.on"), font=ui.fonts.body_bold, fg=theme.LIME),
         w("game.freeplay.hint"), first=True)
    _row(cabinet, ui, w("game.unlock"), lambda p: widgets.Toggle(p, ui, app.state.unlock, app.set_unlock),
         w("game.unlock.hint"))
    if os.path.isdir(data):
        operator = card(parent, ui, w("game.data"), last=True)
        widgets.label(operator.body, ui, w("game.data.hint"), fg=theme.MUTED, wrap_margin=0).pack(fill="x")
        widgets.Button(operator.body, ui, w("common.open"), lambda: actions.open_folder(data)).pack(
            anchor="w", pady=(ui.px(10), 0))


# ------------------------------------------------------------------------------------- the song list for a server


def song_list_default():
    """Where the Save dialog starts: the desktop (Windows' own answer), with the song list's usual name."""
    from opendmt3.client import shortcuts
    from opendmt3.server.services import songlist
    return os.path.join(shortcuts.desktop(), songlist.NAME)


def _working(app, title, message, detail, work, done):
    """Run `work` off the window's thread with a dialog of work under way over the window (it cannot be cancelled:
    the file is made whole or not at all), then done(result, error) on the window's thread."""
    app.dialog = dialogs.Dialog(app.root, app.ui, "info", title, message, detail, progress=True)
    app.busy = True

    def run():
        try:
            result = work()
        except Exception as e:  # noqa: BLE001  (said in the launcher's own dialog, never swallowed)
            log.exception("%s failed", title)
            app.post(lambda e=e: finish(None, e))
            return
        app.post(lambda: finish(result, None))

    def finish(result, error):
        app.busy = False
        if app.dialog is not None:
            app.dialog.close(None)
            app.dialog = None
        done(result, error)

    threading.Thread(target=run, daemon=True, name="song-list").start()


def save_song_list(app):
    """Save the song list...: where, in the launcher's own Save dialog; a file already there replaced only when asked;
    then made from the game folder in use (actions.save_song_list) and said with its size."""
    from opendmt3.client import leaving
    w = app.words
    path = dialogs.ask_path(app, "info", w("songlist.save.title"), w("songlist.save.message"),
                            w("songlist.save.detail"), w("songlist.save.path"), song_list_default(),
                            w("songlist.save.button"))
    if not path:
        return
    path = os.path.expanduser(path)
    if os.path.isdir(path):
        from opendmt3.server.services import songlist
        path = os.path.join(path, songlist.NAME)
    if os.path.exists(path) and not dialogs.ask(app, "warn", w("songlist.save.replace.title"),
                                                w("songlist.save.replace", name=os.path.basename(path)),
                                                w("songlist.save.replace.detail"), w("songlist.save.replace.button")):
        return

    def done(result, error):
        if error is not None:
            dialogs.tell(app, "error", w("songlist.save.title"), w("songlist.failed"), w.error(error))
            return
        manifest, size = result
        app.set_status(w("status.songlist.saved", path=path), "ok")
        dialogs.tell(app, "info", w("songlist.save.title"), w("songlist.saved", songs=manifest["songs"]),
                     w("songlist.saved.detail", path=path, size=leaving.megabytes(size)))

    _working(app, w("songlist.saving.title"), w("songlist.saving"), None,
             lambda: actions.save_song_list(app.state, path), done)


def send_song_list(app):
    """Send the song list to this server: asked first (it replaces the server's), then made and sent with the
    launcher's sign-in (actions.send_song_list), the server's answer said."""
    w = app.words
    if not dialogs.ask(app, "warn", w("songlist.send.title"), w("songlist.send.ask"),
                       w("songlist.send.detail", server=app.state.server_url), w("songlist.send.button")):
        return

    def done(answer, error):
        if error is not None:
            dialogs.tell(app, "error", w("songlist.send.title"), w("songlist.not_sent"), w.error(error))
            return
        songs = ((answer.get("song_list") or {}).get("songs") or {}).get("count", 0)
        app.set_status(w("status.songlist.sent", songs=songs), "ok")
        dialogs.tell(app, "info", w("songlist.send.title"), w("songlist.sent", songs=songs),
                     w("songlist.sent.detail", server=app.state.server_url))

    _working(app, w("songlist.sending.title"), w("songlist.sending"), None,
             lambda: actions.send_song_list(app.state), done)
