"""RECORDS: the chosen player's numbers, weeks, recent plays and best scores, on cards as the other pages have
theirs."""

import threading
import time
import tkinter as tk

from opendmt3.client import actions, theme, widgets

from opendmt3.client.pages.common import CARD_GAP, TITLES, card


def build_records(app, parent):
    """The chosen player's records: numbers, the last 12 weeks, recent plays and best scores (actions.records), read
    on a thread (another server answers over the network); the site's DJ page has the rest."""
    ui, w = app.ui, app.words
    box = tk.Frame(parent, bg=theme.BG)
    box.pack(fill="both", expand=True)
    # Until the records come, the page's card says they are being read (an empty page says nothing).
    waiting = card(box, ui, last=True)
    widgets.label(waiting.body, ui, w("records.loading"), fg=theme.MUTED).pack(anchor="w")
    state, host = app.state, app.host

    def work():
        try:
            found = actions.records(state, host)
        except Exception as e:  # noqa: BLE001  (shown in the page, never a silent stop)
            app.post(lambda e=e: box.winfo_exists() and _records_failed(app, box, e))
            return
        app.post(lambda: box.winfo_exists() and _records_drawn(app, box, found))

    threading.Thread(target=work, daemon=True, name="records").start()


def _records_failed(app, box, error):
    """Why there are no records to show, on the page's card, and the way to what fixes it."""
    ui, w = app.ui, app.words
    for child in box.winfo_children():
        child.destroy()
    why = card(box, ui, last=True)
    widgets.label(why.body, ui, w.error(error), fg=theme.AMBER, wrap_margin=0).pack(fill="x")
    if getattr(error, "key", None) in ("error.records.signin", "error.records.offline"):
        # The page that fixes it, by the menu's own name, as HELP's lines name theirs.
        widgets.link(why.body, ui, TITLES["online"], lambda: app.go("online")).pack(anchor="w", pady=(ui.px(10), 0))
    elif getattr(error, "key", None) == "error.records.guest":
        # A guest has no records: the player is chosen on the PLAY page.
        widgets.link(why.body, ui, TITLES["play"], lambda: app.go("play")).pack(anchor="w", pady=(ui.px(10), 0))
    else:
        # A server that did not answer may answer now.
        widgets.Button(why.body, ui, w("records.again"), lambda: app.go("records")).pack(anchor="w",
                                                                                       pady=(ui.px(10), 0))


def _records_open_site(app, player):
    """The site's DJ page: on this PC signed in at once (a one-use link), on another server where the player signs in."""
    if app.state.mode == "this_pc":
        app.open_records()
    else:
        actions.open_link("%s/dj/%d" % (app.state.server_url.rstrip("/"), player))


def _records_drawn(app, box, dj):
    ui, w = app.ui, app.words
    for child in box.winfo_children():
        child.destroy()
    # ---- the DJ: name, numbers
    head = widgets.Card(box, ui)
    head.pack(fill="x", pady=(0, ui.px(CARD_GAP)))
    top = tk.Frame(head.body, bg=theme.PANEL)
    top.pack(fill="x")
    tk.Label(top, text=dj["dj_name"], font=ui.fonts.title, fg=theme.TEXT, bg=theme.PANEL).pack(side="left")
    # The DJ card's level, as the game shows it (an older server sends no card).
    card = dj.get("dj_card") or {}
    if card.get("level"):
        tk.Label(top, text="Lv %d" % card["level"], font=ui.fonts.body_bold, fg=theme.AMBER, bg=theme.PANEL).pack(
            side="left", padx=(ui.px(12), 0))
    widgets.Button(top, ui, w("records.site"), lambda: _records_open_site(app, dj["player"])).pack(
        side="right")
    if card.get("comment"):
        # The comment over the plate in the game.
        widgets.label(head.body, ui, card["comment"], fg=theme.MUTED, bg=theme.PANEL, wrap_margin=0).pack(
            fill="x", pady=(ui.px(4), 0))
    summary, done = dj["summary"], dj["activity"]
    seconds = done["seconds"]
    played = (w("common.hours", h=seconds // 3600, m=(seconds % 3600) // 60) if seconds >= 3600
              else w("common.minutes", m=seconds // 60))
    numbers = tk.Frame(head.body, bg=theme.PANEL)
    numbers.pack(fill="x", pady=(ui.px(14), 0))
    for i, (value, key) in enumerate(((summary["plays"], "records.plays"), (summary["songs"], "records.songs"),
                                      (summary["charts"], "records.charts"), (done["sessions"], "records.sessions"),
                                      (played, "records.time"))):
        cell = tk.Frame(numbers, bg=theme.PANEL)
        cell.grid(row=0, column=i, sticky="w", padx=(0, ui.px(28)))
        tk.Label(cell, text=str(value), font=ui.fonts.display_big, fg=theme.TEXT, bg=theme.PANEL).pack(anchor="w")
        tk.Label(cell, text=w(key), font=ui.fonts.small, fg=theme.MUTED, bg=theme.PANEL).pack(anchor="w")
    # ---- the last 12 weeks: one bar a week, this week last; the hovered week's number under the chart
    weeks = done["weeks"]
    most = max([wk["plays"] for wk in weeks] or [0])
    widgets.section(head.body, ui, w("records.weeks"), bg=theme.PANEL).pack(fill="x", pady=(ui.px(18), ui.px(8)))
    chart_height = ui.px(84)
    chart = tk.Canvas(head.body, height=chart_height, bg=theme.PANEL, highlightthickness=0, bd=0)
    chart.pack(fill="x")
    readout = tk.Label(head.body, text=w("records.most", n=most), font=ui.fonts.small, fg=theme.MUTED, bg=theme.PANEL)
    readout.pack(anchor="w", pady=(ui.px(4), 0))
    day = lambda t: time.strftime("%m/%d", time.localtime(t))

    def draw(_event=None):
        chart.delete("all")
        width = chart.winfo_width()
        if width < 50:
            return
        slot = width / len(weeks)
        bar = min(ui.px(22), slot * 0.7)
        base = chart_height - 1
        chart.create_line(0, base, width, base, fill=theme.LINE)
        for i, wk in enumerate(weeks):
            if not wk["plays"] or not most:
                continue
            x = i * slot + (slot - bar) / 2
            top_y = base - (base - ui.px(4)) * wk["plays"] / most
            chart.create_rectangle(x, top_y, x + bar, base, fill=ui.section["light"], outline="")

    def hover(event):
        width = chart.winfo_width()
        i = min(len(weeks) - 1, max(0, int(event.x / max(1, width) * len(weeks))))
        wk = weeks[i]
        readout.configure(text=w("records.week", start=day(wk["from"]), end=day(wk["to"]), n=wk["plays"]),
                          fg=theme.TEXT)

    chart.bind("<Configure>", draw)
    chart.bind("<Motion>", hover)
    chart.bind("<Leave>", lambda e: readout.configure(text=w("records.most", n=most), fg=theme.MUTED))
    # ---- recent plays and best scores, side by side
    row = tk.Frame(box, bg=theme.BG)
    row.pack(fill="x")
    row.columnconfigure(0, weight=1, uniform="lists")
    row.columnconfigure(1, weight=1, uniform="lists")
    for column, (title_key, items) in enumerate((("records.recent", dj["recent"]), ("records.bests", dj["bests"][:10]))):
        card = widgets.Card(row, ui, title=w(title_key))
        card.grid(row=0, column=column, sticky="nsew", padx=(0, ui.px(CARD_GAP)) if column == 0 else 0)
        if not items:
            widgets.label(card.body, ui, w("records.none"), fg=theme.MUTED, bg=theme.PANEL, wrap_margin=0).pack(fill="x")
        for i, item in enumerate(items):
            if i:
                # One play each, parted by the card's faint lines, as PLAY's last game has them.
                widgets.divider(card.body, ui, pady=7)
            widgets.label(card.body, ui, item["title"], font=ui.fonts.body_bold, wrap_margin=0).pack(fill="x")
            line = tk.Frame(card.body, bg=theme.PANEL)
            line.pack(fill="x")
            chart_words = (w("records.chart.level", mode=item["mode_name"], n=item["pattern"], level=item["level"])
                           if item.get("level") else w("records.chart", mode=item["mode_name"], n=item["pattern"]))
            tk.Label(line, text=chart_words, font=ui.fonts.small, fg=theme.MUTED, bg=theme.PANEL).pack(side="left")
            tk.Label(line, text="{:,}".format(item["score"]), font=ui.fonts.display, fg=theme.LIME,
                     bg=theme.PANEL).pack(side="right")
