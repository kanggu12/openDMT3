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
    var send = form.querySelector("button.primary");
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
