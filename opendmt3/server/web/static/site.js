// The forms (FORMS.md), in the site's own look and words instead of the browser's: a form marked novalidate is checked
// here before it goes (a field it needs left empty, data-missing; one its own rules refuse, data-invalid), and what is
// wrong is said right under that field (.field-error), the field marked for screen readers and given the focus; the
// server checks the same again and answers the same way. A form that goes shows it on its key (aria-busy, the game's
// moving stripes) until the next page comes. Also here: a password's Show inside its field, Copy beside a value to copy,
// the ID kept for a sign-in form (data-remember), counts of what is typed, and text areas that grow with their words.
// This runs before the questions' script below: a form with something wrong is never asked about.
(function () {
  "use strict";
  // What is wrong with a field, in the page's words, or "" when nothing is: empty first, then its own rules.
  function fault(field) {
    if (field.disabled) { return ""; }
    if (field.dataset.missing !== undefined && field.value.trim() === "") { return field.dataset.missing; }
    if (field.dataset.invalid !== undefined && field.value.trim() !== "" && !field.validity.valid) { return field.dataset.invalid; }
    return "";
  }
  // A field's own line of words under it: the server's, or one made here the first time it is needed.
  function lineOf(field) {
    var holder = field.closest(".field") || field.closest("label");
    if (!holder) { return null; }
    var line = holder.querySelector(".field-error");
    if (!line) {
      line = document.createElement("span");
      line.className = "field-error";
      line.setAttribute("role", "alert");
      line.id = (field.id || field.name) + "-error";
      holder.appendChild(line);
    }
    return line;
  }
  // A field put right (typed in, or about to be checked again): its mark and its words go.
  function clear(field) {
    field.removeAttribute("aria-invalid");
    var holder = field.closest(".field") || field.closest("label");
    var line = holder && holder.querySelector(".field-error");
    if (line) {
      line.remove();
      // Its hint (if any) names it again for screen readers.
      var hint = holder.querySelector(".field-hint");
      if (hint && hint.id) { field.setAttribute("aria-describedby", hint.id); } else { field.removeAttribute("aria-describedby"); }
    }
  }
  // Its key working on it, until the next page comes (or the browser keeps this page for its Back button).
  function busy(form, button) {
    form.classList.add("is-sent");
    if (button) { button.setAttribute("aria-busy", "true"); }
  }
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) { return; }
    // Sent already and waiting for the answer: a second press does nothing.
    if (form.classList.contains("is-sent")) { event.preventDefault(); event.stopImmediatePropagation(); return; }
    if (form.noValidate) {
      var fields = form.querySelectorAll("[data-missing], [data-invalid]"), wrong = null, i;
      for (i = 0; i < fields.length; i += 1) {
        if (fault(fields[i]) !== "") { wrong = fields[i]; break; }
      }
      if (wrong) {
        event.preventDefault();
        // Nothing else hears of this send (the question before it is not asked).
        event.stopImmediatePropagation();
        for (i = 0; i < fields.length; i += 1) { if (fields[i].getAttribute("aria-invalid") === "true") { clear(fields[i]); } }
        var line = lineOf(wrong);
        if (line) {
          line.textContent = fault(wrong);
          wrong.setAttribute("aria-describedby", line.id);
        }
        wrong.setAttribute("aria-invalid", "true");
        wrong.focus();
        return;
      }
    }
    // A form that asks first goes once it has its answer (the questions' script sends it again, marked asked).
    if (form.hasAttribute("data-ask") && form.dataset.asked !== "yes") { return; }
    var button = event.submitter || form.querySelector("button:not([type=button])");
    busy(form, button);
  }, true);
  // Typing into a marked field takes its mark away; what it says is up to the next press.
  document.addEventListener("input", function (event) {
    var field = event.target;
    if (field.getAttribute && field.getAttribute("aria-invalid") === "true") { clear(field); }
  });
  // A page the browser kept for Back shows its keys ready again.
  window.addEventListener("pageshow", function () {
    document.querySelectorAll("form.is-sent").forEach(function (form) {
      form.classList.remove("is-sent");
      form.querySelectorAll("[aria-busy]").forEach(function (button) { button.removeAttribute("aria-busy"); });
    });
  });

  // Show, inside a password's field: the password as typed until pressed again. The field keeps the focus and its
  // caret on a click; Tab reaches Show right after the field. A form that goes takes the password hidden again.
  document.querySelectorAll("button[data-reveal]").forEach(function (key) {
    var field = document.getElementById(key.dataset.reveal);
    if (!field) { return; }
    key.hidden = false;
    function set(shown) {
      field.type = shown ? "text" : "password";
      key.setAttribute("aria-pressed", shown ? "true" : "false");
      key.textContent = shown ? key.dataset.hide : key.dataset.show;
    }
    key.addEventListener("mousedown", function (event) { event.preventDefault(); });
    key.addEventListener("click", function () {
      var at = [field.selectionStart, field.selectionEnd];
      set(field.type === "password");
      if (document.activeElement !== key) {
        field.focus();
        try { field.setSelectionRange(at[0], at[1]); } catch (ignored) { /* a field that keeps no caret */ }
      }
    });
    if (field.form) { field.form.addEventListener("submit", function (event) { if (!event.defaultPrevented) { set(false); } }); }
  });

  // Copy, beside a value to copy (a token, a message, an address): the whole value, and the key says so for a while.
  document.querySelectorAll("button[data-copy]").forEach(function (key) {
    var field = document.getElementById(key.dataset.copy);
    if (!field || !navigator.clipboard) { return; }
    key.hidden = false;
    key.addEventListener("click", function () {
      navigator.clipboard.writeText(field.value || field.textContent).then(function () {
        key.textContent = key.dataset.done;
        key.classList.add("on");
        window.setTimeout(function () { key.textContent = key.dataset.word; key.classList.remove("on"); }, 2000);
      });
    });
  });

  // The ID last used to sign in on this browser, back in its field when "Remember my ID" was ticked then: the box ticked
  // again and the focus on the password. Unticked when the form goes, the ID is forgotten. Browser storage may be off (a
  // private window): then nothing is kept and nothing breaks.
  document.querySelectorAll("form[data-remember]").forEach(function (form) {
    var key = "opendmt3.id." + form.dataset.remember;
    var id = form.querySelector("input[autocomplete=username]");
    var password = form.querySelector("input[type=password]");
    var keep = form.querySelector("input[name=remember]");
    if (!id || !keep) { return; }
    var kept = "";
    try { kept = window.localStorage.getItem(key) || ""; } catch (ignored) { /* storage off */ }
    if (kept) {
      keep.checked = true;
      if (!id.value) { id.value = kept; }
      // Not where a finger is the pointer (its keyboard would come up over the page), nor over a field the server's
      // answer chose.
      if (!window.matchMedia("(pointer: coarse)").matches && !form.querySelector("[autofocus]") && password) { password.focus(); }
    }
    form.addEventListener("submit", function (event) {
      if (event.defaultPrevented) { return; }
      try {
        if (keep.checked && id.value.trim()) { window.localStorage.setItem(key, id.value.trim()); } else { window.localStorage.removeItem(key); }
      } catch (ignored) { /* storage off */ }
    });
  });

  // A count of what is typed at its label's right end (a field with a maxlength and a .count naming it): the chalk at the
  // limit, pink past it (a paste). The game counts UTF-16 places, as a string's length does.
  document.querySelectorAll(".count[data-count-for]").forEach(function (count) {
    var field = document.getElementById(count.dataset.countFor);
    if (!field) { return; }
    function show() {
      var most = Number(field.getAttribute("maxlength")) || Number(count.dataset.most) || 0;
      count.textContent = field.value.length + " / " + most;
      count.classList.toggle("full", most > 0 && field.value.length === most);
      count.classList.toggle("over", most > 0 && field.value.length > most);
    }
    field.addEventListener("input", show);
    show();
  });

  // A text area to type in grows with its words, up to its largest height (site.css), then scrolls inside.
  function grow(box) {
    box.style.height = "auto";
    box.style.height = (box.scrollHeight + box.offsetHeight - box.clientHeight) + "px";
  }
  document.querySelectorAll("textarea:not([readonly])").forEach(function (box) {
    box.addEventListener("input", function () { grow(box); });
    grow(box);
  });
}());

// Questions before something cannot be undone, asked in the site's own dialog (the game's popup: a tab with the
// title, the question under it, buttons that say what they do) instead of the browser's plain confirm box.
//
// A form asks first when it carries data-ask (the question) and, optionally, data-ask-title, data-ask-detail,
// data-ask-yes (the button's words) and data-ask-tone ("danger", the default, or "warn"). Esc and Cancel keep
// everything as it was; the dialog starts on Cancel, so Enter alone never removes anything.
(function () {
  "use strict";
  var dialog = document.getElementById("ask");
  if (!dialog) { return; }
  if (typeof dialog.showModal !== "function") {
    // An older browser without <dialog>: it asks with its own box, never not at all.
    document.addEventListener("submit", function (event) {
      var form = event.target;
      if (form.hasAttribute && form.hasAttribute("data-ask") && !window.confirm(form.dataset.ask)) {
        event.preventDefault();
      }
    }, true);
    return;
  }
  var pending = null, submitter = null, opened = 0;
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.hasAttribute || !form.hasAttribute("data-ask") || form.dataset.asked === "yes") { return; }
    event.preventDefault();
    pending = form;
    // The button that sent it goes with it again (its name and value, if it has them).
    submitter = event.submitter || null;
    var tone = form.dataset.askTone === "warn" ? "warn" : "danger";
    dialog.className = "ask " + tone;
    document.getElementById("ask-title").textContent = form.dataset.askTitle || "";
    document.getElementById("ask-question").textContent = form.dataset.ask;
    document.getElementById("ask-detail").textContent = form.dataset.askDetail || "";
    var yes = document.getElementById("ask-yes");
    yes.textContent = form.dataset.askYes || "OK";
    yes.className = "btn fill " + tone;
    dialog.returnValue = "cancel";
    opened = Date.now();
    dialog.showModal();
    document.getElementById("ask-cancel").focus();
  }, true);
  dialog.addEventListener("close", function () {
    var form = pending, button = submitter;
    pending = null;
    submitter = null;
    if (form && dialog.returnValue === "yes") {
      // Sent as the person sent it, now without asking again; the next send asks again (a page kept by the
      // browser's back button, or a send that did not go through).
      form.dataset.asked = "yes";
      if (typeof form.requestSubmit === "function") { form.requestSubmit(button || undefined); } else { form.submit(); }
      delete form.dataset.asked;
    }
  });
  // A click on the dimmed page around the panel is a Cancel, as in the launcher.
  dialog.addEventListener("click", function (event) {
    // The second click of a double click on the page's button lands on the dimmed page: it is not a Cancel.
    if (event.target === dialog && event.detail < 2 && Date.now() - opened > 400) { dialog.close("cancel"); }
  });
}());

// Text to copy (the admin's message to send a player) is selected whole when it gets the focus, and its box grows to
// show every line, a long one wrapped on a phone included, without a scroll bar of its own.
(function () {
  "use strict";
  var boxes = document.querySelectorAll("textarea[readonly]");
  function fit(box) {
    box.style.height = "auto";
    // The text's own height, and the box's border around it.
    box.style.height = (box.scrollHeight + box.offsetHeight - box.clientHeight) + "px";
  }
  for (var i = 0; i < boxes.length; i += 1) {
    boxes[i].addEventListener("focus", function (event) { event.target.select(); });
    fit(boxes[i]);
  }
  window.addEventListener("resize", function () {
    for (var j = 0; j < boxes.length; j += 1) { fit(boxes[j]); }
  });
}());

// The songs list filtered as the visitor types: rows that do not match hide at once (no request), the line above the
// list says how many show, and a word nothing matches says so. The same match as the server's search (Find): the
// title or the composer holds the word (in any case), or it is the song's number.
(function () {
  "use strict";
  var box = document.getElementById("song-filter");
  var count = document.getElementById("song-count");
  var none = document.getElementById("song-none");
  var rows = document.querySelectorAll("table.songs tbody tr");
  // No list on the page (no song, or the server's search found none): its own words stand.
  if (!box || !count || !none || !rows.length) { return; }
  box.addEventListener("input", function () {
    var word = box.value.trim().toLowerCase(), shown = 0;
    for (var i = 0; i < rows.length; i += 1) {
      var hit = !word || rows[i].dataset.find.indexOf(word) >= 0 || rows[i].dataset.number === word;
      rows[i].hidden = !hit;
      if (hit) { shown += 1; }
    }
    // The words come from the page in its language, with their gaps filled here (as text, never as markup).
    count.textContent = count.dataset.words.replace("{n}", String(shown)).replace("{of}", count.dataset.total);
    none.textContent = none.dataset.words.replace("{query}", box.value.trim());
    none.hidden = shown > 0;
  });
}());

// The upload fields (Admin, Song list and Backups; templates/_upload.html), as OpenDMTQ's upload box: the box names the
// chosen or dropped file and its size, says when it is past the server's limit before anything is sent (the server
// refuses it too, but only once a browser has started sending it), and the form's button sends only a file within the
// limit. The words are the page's, in its language (the box's data-*), with their gaps filled here as text, never as
// markup; the limit is the form's data-upload-most, in bytes, read again when the form is sent.
(function () {
  "use strict";
  var boxes = document.querySelectorAll("form[data-upload-most] .drop");
  // A size as the page says sizes: whole KB under a megabyte (at least 1), else MB with one decimal (none for .0).
  function size(bytes) {
    if (bytes < 1048576) { return Math.max(1, Math.round(bytes / 1024)) + " KB"; }
    return (bytes / 1048576).toFixed(1).replace(/\.0$/, "") + " MB";
  }
  Array.prototype.forEach.call(boxes, function (box) {
    var form = box.closest("form");
    var input = box.querySelector("input[type=file]");
    var hint = box.querySelector(".drop-hint");
    var pick = box.querySelector(".drop-pick");
    // The form's sending button: its main one, a plain one marked as the upload's (each page keeps one main button,
    // its own action), or one marked as the button that sends the file (a page with another main).
    var send = form.querySelector("button.send, button.primary, button[data-send]");
    // The page's line for a file past the limit, under the form (shown when the form is sent with one).
    var said = form.parentNode.querySelector(".upload-too-large");
    // The box's own words as the page wrote them, its drop-only part included (the page's markup, no file's name).
    var blank = hint.innerHTML;
    // The box as its file is now; true when that file is past the limit.
    function show() {
      var file = input.files && input.files[0];
      var most = Number(form.dataset.uploadMost) || Infinity;
      var over = Boolean(file) && file.size > most;
      box.classList.toggle("has-file", Boolean(file) && !over);
      box.classList.toggle("too-big", over);
      if (file) {
        // The file's name goes in as text: it is the visitor's, not the page's.
        hint.textContent = file.name + " · " + (over ? box.dataset.tooBig.replace("{size}", size(file.size))
          .replace("{max}", size(most)) : size(file.size));
      } else {
        hint.innerHTML = blank;
      }
      pick.textContent = file ? box.dataset.change : box.dataset.choose;
      if (send) { send.disabled = !file || over; }
      return over;
    }
    input.addEventListener("change", function () {
      // Another file chosen: the line about the last one goes, and the box says this one.
      if (said) { said.hidden = true; }
      show();
    });
    // A file dragged over the box lights it; it lands on the file input lying over the whole box.
    ["dragenter", "dragover"].forEach(function (kind) {
      box.addEventListener(kind, function () { box.classList.add("over"); });
    });
    ["dragleave", "drop"].forEach(function (kind) {
      box.addEventListener(kind, function () { box.classList.remove("over"); });
    });
    form.addEventListener("submit", function (event) {
      // The limit as the page says it when the form is sent; past it, the line under the form says so.
      var over = show();
      if (said) { said.hidden = !over; }
      if (over || !(input.files && input.files.length)) { event.preventDefault(); }
    });
    // At once, without the button's easing: it would show in the section's colour first and fade on every load. Also
    // right after a reload or the back button, when the browser may have kept the file.
    if (send) { send.style.transition = "none"; }
    show();
    if (send) {
      // Reading its size lays it out as it now is, before the easing comes back.
      void send.offsetWidth;
      send.style.transition = "";
    }
  });
}());

// A long job's progress card (templates/_job.html: a song list's import, a restore): the job asked for every second
// (/admin/jobs/{id}, in the page's language), its bar, step and count moved as it goes, the step it is on marked in the
// list; once it ends the page opens again at its own address, which then says how it ended. A failed ask tries again
// at the next second; the card's link does the same without the script.
(function () {
  "use strict";
  var card = document.querySelector(".card.job[data-job]");
  if (!card || typeof window.fetch !== "function") { return; }
  var bar = card.querySelector(".job-bar"), fill = bar.querySelector("i");
  var text = card.querySelector(".job-text"), count = card.querySelector(".job-count");
  var steps = card.querySelector(".job-steps");
  function show(job) {
    var pct = Math.round((job.share || 0) * 1000) / 10;
    fill.style.width = pct + "%";
    bar.setAttribute("aria-valuenow", String(Math.round(pct)));
    // Words from the server, as text (never markup).
    text.textContent = job.step_text || "";
    count.textContent = job.count_text || "";
    // The steps as the job now knows them (an import's are known once it started), the one it is on marked.
    var known = job.steps || [], at = known.indexOf(job.step);
    var items = steps.querySelectorAll("li");
    for (var i = 0; i < items.length; i += 1) {
      var place = known.indexOf(items[i].dataset.step);
      items[i].hidden = place < 0;
      items[i].className = place === at ? "on" : (at >= 0 && place >= 0 && place < at ? "done" : "");
    }
  }
  function ask() {
    fetch("/admin/jobs/" + encodeURIComponent(card.dataset.job), {credentials: "same-origin", cache: "no-store"})
      .then(function (answer) { return answer.ok ? answer.json() : null; })
      .then(function (job) {
        if (job && job.state !== "running") {
          // Ended: the page at its own address says how.
          window.location.replace(window.location.pathname + "?job=" + encodeURIComponent(card.dataset.job));
          return;
        }
        if (job) { show(job); }
        window.setTimeout(ask, 1000);
      }, function () { window.setTimeout(ask, 1000); });
  }
  window.setTimeout(ask, 1000);
}());

// After the Server tab's Restart (templates/admin_server_going.html): the health check asked every half second; once
// it answers with another run's mark than the page's (the server that was asked has gone and a new one answers), the
// page goes back to the Server tab.
(function () {
  "use strict";
  var card = document.querySelector(".server-going[data-back]");
  if (!card || typeof window.fetch !== "function") { return; }
  // A minute with no new run answering: the page says so, with the way back (it goes on asking meanwhile).
  var started = Date.now(), slow = card.querySelector(".going-slow");
  function ask() {
    if (slow && slow.hidden && Date.now() - started > 60000) { slow.hidden = false; }
    fetch("/health", {cache: "no-store"})
      .then(function (answer) { return answer.ok ? answer.json() : null; }, function () { return null; })
      .then(function (health) {
        if (health && health.run && health.run !== card.dataset.run) {
          window.location.replace(card.dataset.back);
          return;
        }
        window.setTimeout(ask, 500);
      }, function () { window.setTimeout(ask, 500); });
  }
  window.setTimeout(ask, 500);
}());

// The bar: its height for what hangs under it (the phone's menu sheet, a toast's strip), MENU's state for screen readers,
// a toast placed in the bar where its words fit (else on a strip of the bar's glass right under it, across the window),
// a job that ended while one was on another page told by a toast with the way to it, and a long notice on a phone kept
// to two lines until it is pressed.
(function () {
  "use strict";
  var bar = document.querySelector(".bar");
  if (!bar) { return; }
  var root = document.documentElement;
  function measure() { root.style.setProperty("--bar-h", Math.round(bar.getBoundingClientRect().height) + "px"); }
  measure();
  window.addEventListener("resize", measure);

  // MENU and its sheet (a popover: the browser opens and closes it, Esc and a tap outside included).
  var sheet = document.getElementById("menu-sheet"), key = bar.querySelector(".menu-key");
  if (sheet && key) {
    sheet.addEventListener("toggle", function (event) {
      var open = event.newState === "open";
      key.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) { measure(); var first = sheet.querySelector("a"); if (first) { first.focus(); } }
    });
    // Past the phone's width the sheet has nothing to do (the bar shows the menu): a sheet left open closes.
    window.addEventListener("resize", function () {
      if (window.innerWidth > 760 && sheet.matches(":popover-open")) { sheet.hidePopover(); }
    });
  }

  // A toast inside the bar, between the menu and the tools, when its words fit there on one line; else across the
  // window right under the bar.
  function place(toast) {
    var b = bar.getBoundingClientRect();
    var menu = bar.querySelector(".menu"), tools = bar.querySelector(".tools"), brand = bar.querySelector(".brand");
    var from = (menu && menu.offsetWidth ? menu : brand).getBoundingClientRect().right + 20;
    var to = (tools && tools.offsetWidth ? tools.getBoundingClientRect().left : b.right) - 20;
    toast.classList.remove("under");
    toast.style.top = b.top + "px";
    toast.style.left = from + "px";
    toast.style.width = Math.max(0, to - from) + "px";
    toast.style.height = b.height + "px";
    var words = toast.querySelector(".toast-words");
    if (window.innerWidth <= 760 || to - from < 260 || words.scrollHeight > words.clientHeight + 1 ||
        words.scrollWidth > words.clientWidth + 1 || words.getClientRects().length > 1 ||
        words.getBoundingClientRect().height > 22) {
      toast.classList.add("under");
      toast.style.top = b.bottom + "px";
      toast.style.left = "0px";
      toast.style.width = "100%";
      toast.style.height = "auto";
    }
  }
  // Shown; a done one goes after six seconds unless the pointer or the keyboard is on it (and six seconds after it
  // leaves); a refusal stays until closed. A toast shown again (toast-later's, for each job that ends) keeps the one set
  // of listeners it got the first time and starts its six seconds again: nothing piles up.
  function show(toast) {
    if (typeof toast.showPopover !== "function") { return; }
    toast.hidden = false;
    toast.showPopover();
    place(toast);
    if (!toast.dataset.watched) {
      // Once per toast: its close key, Esc, what holds it open, and its place when the window changes size.
      toast.dataset.watched = "1";
      var close = toast.querySelector(".toast-close");
      close.onclick = function () { toast.hidePopover(); };
      toast.addEventListener("keydown", function (event) { if (event.key === "Escape") { toast.hidePopover(); } });
      toast.held = { pointer: false, focus: false };
      toast.addEventListener("mouseenter", function () { toast.held.pointer = true; });
      toast.addEventListener("mouseleave", function () { toast.held.pointer = false; });
      toast.addEventListener("focusin", function () { toast.held.focus = true; });
      // The keyboard gone from it (to anywhere but inside it): it holds the toast no more.
      toast.addEventListener("focusout", function (event) {
        toast.held.focus = toast.contains(event.relatedTarget);
      });
      window.addEventListener("resize", function () { if (toast.matches(":popover-open")) { place(toast); } });
    }
    // One timer at a time: one from an earlier showing goes.
    if (toast.timer) { window.clearInterval(toast.timer); toast.timer = null; }
    if (!toast.classList.contains("bad")) {
      toast.timer = window.setInterval(function () {
        if (!toast.held.pointer && !toast.held.focus) {
          window.clearInterval(toast.timer);
          toast.timer = null;
          if (toast.matches(":popover-open")) { toast.hidePopover(); }
        }
      }, 6000);
    }
  }
  document.querySelectorAll(".toast[data-toast]").forEach(show);
  // A dialog that opens over a toast that stays: the toast comes up again over it (the newest of the top layer is drawn
  // on top).
  var ask = document.getElementById("ask");
  if (ask) {
    new MutationObserver(function () {
      if (!ask.open) { return; }
      document.querySelectorAll(".toast").forEach(function (toast) {
        if (toast.matches(":popover-open")) { toast.hidePopover(); toast.showPopover(); place(toast); toast.dataset.raised = "1"; }
      });
    }).observe(ask, { attributes: true, attributeFilter: ["open"] });
  }

  // Long jobs (a song list's import, a restore) an admin started: kept by id in this browser while their card is shown;
  // on any other page, each one still kept is asked once and then every few seconds, and when it has ended a toast says
  // how, with the way to its page.
  var later = document.getElementById("toast-later");
  var KEY = "opendmt3.jobs", PAGES = { song_list: "/admin/song_list", restore: "/admin/backups" };
  function kept() { try { return JSON.parse(window.localStorage.getItem(KEY) || "[]"); } catch (ignored) { return []; } }
  function keep(list) { try { window.localStorage.setItem(KEY, JSON.stringify(list)); } catch (ignored) { /* storage off */ } }
  var card = document.querySelector(".card.job[data-job]");
  if (card && kept().indexOf(card.dataset.job) < 0) { keep(kept().concat([card.dataset.job])); }
  if (later && typeof window.fetch === "function" && kept().length) {
    var ask_ = function () {
      var ids = kept().filter(function (id) { return !card || card.dataset.job !== id; });
      if (!ids.length) { return; }
      ids.forEach(function (id) {
        fetch("/admin/jobs/" + encodeURIComponent(id), { credentials: "same-origin", cache: "no-store" })
          .then(function (answer) { return answer.status === 404 ? { gone: true } : (answer.ok ? answer.json() : null); })
          .then(function (job) {
            if (!job) { return; }
            if (job.gone) { keep(kept().filter(function (k) { return k !== id; })); return; }
            if (job.state === "running") { return; }
            keep(kept().filter(function (k) { return k !== id; }));
            later.classList.toggle("bad", job.state !== "done");
            later.querySelector(".toast-words").textContent = job.text || job.title || "";
            var go = later.querySelector(".toast-go");
            go.textContent = later.dataset.openWord;
            go.href = (PAGES[job.kind] || "/admin/status") + "?job=" + encodeURIComponent(id);
            show(later);
          }, function () { /* asked again at the next round */ });
      });
      window.setTimeout(ask_, 3000);
    };
    ask_();
  }
  // The job's own page, at its end, says how it ended: it is not kept any more.
  if (!card && /[?&]job=/.test(window.location.search)) {
    var shown = (window.location.search.match(/[?&]job=([^&]+)/) || [])[1];
    if (shown) { keep(kept().filter(function (k) { return k !== decodeURIComponent(shown); })); }
  }

  // A long notice on a phone: two lines, the rest when the strip is pressed (a key for the keyboard too).
  document.querySelectorAll(".site-notice").forEach(function (strip) {
    var text = strip.querySelector(".text");
    function fit() {
      strip.classList.remove("long");
      if (window.innerWidth > 760) { strip.removeAttribute("role"); return; }
      var lines = Math.round(text.getBoundingClientRect().height / parseFloat(getComputedStyle(text).lineHeight || "24"));
      if (lines > 2) { strip.classList.add("long"); strip.setAttribute("tabindex", "0"); strip.setAttribute("aria-expanded", strip.classList.contains("open") ? "true" : "false"); }
    }
    function flip() { strip.classList.toggle("open"); strip.setAttribute("aria-expanded", strip.classList.contains("open") ? "true" : "false"); }
    strip.addEventListener("click", function () { if (strip.classList.contains("long")) { flip(); } });
    strip.addEventListener("keydown", function (event) {
      if (strip.classList.contains("long") && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); flip(); }
    });
    fit();
    window.addEventListener("resize", fit);
  });
}());

// The member's card shines once: a sign-in, or a card saved on one's account page, leaves a flag in this tab's storage,
// and the next page that shows the card (the home page's, the account's preview) runs one silver shine across it, then
// forgets the flag. The style draws nothing for it when less motion is asked for; a browser without storage shows none.
(function () {
  "use strict";
  var KEY = "opendmt3.shine";
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || event.defaultPrevented) { return; }
    if (form.matches("[data-remember]") || form.querySelector(".card-preview")) {
      try { window.sessionStorage.setItem(KEY, "1"); } catch (e) { /* no storage: no shine */ }
    }
  });
  var waiting = false;
  try { waiting = window.sessionStorage.getItem(KEY) === "1"; } catch (e) { waiting = false; }
  if (!waiting) { return; }
  var card = document.querySelector(".djcard, .card-preview");
  if (!card) { return; }
  try { window.sessionStorage.removeItem(KEY); } catch (e) { /* nothing kept */ }
  card.classList.add("shine");
  card.addEventListener("animationend", function () { card.classList.remove("shine"); }, { once: true });
}());
