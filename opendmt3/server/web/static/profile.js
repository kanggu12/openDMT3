// The account area and the admin's page of one player (templates/account.html, admin_player.html): the DJ card's
// preview follows each choice as it is made, the comment counts its characters as the game does, a password typed can
// be shown, and the page opens at the section of what was just done. Without this file every form still works.
(function () {
  "use strict";

  // The DJ card's editors: each form with data-card-editor holds its own preview (_card_editor.html).
  document.querySelectorAll("form[data-card-editor]").forEach(function (form) {
    var preview = form.querySelector(".card-preview");
    if (!preview) { return; }
    form.addEventListener("change", function (event) {
      var input = event.target;
      if (input.type !== "radio" || !/^(icon|plate|pattern)$/.test(input.name)) { return; }
      var picture = preview.querySelector('[data-kind="' + input.name + '"]');
      if (picture) {
        // Pattern 0 is none: the plate alone, as the game draws it.
        picture.hidden = input.name === "pattern" && input.value === "0";
        if (!picture.hidden) { picture.src = "/cards/" + input.name + "/" + input.value + ".png"; }
      }
      if (input.name === "plate") {
        // Each pattern is seen over the plate chosen now.
        form.querySelectorAll(".choices.pattern .choice").forEach(function (choice) {
          choice.style.backgroundImage = "url(/cards/plate/" + input.value + ".png)";
        });
      }
    });
    var comment = form.querySelector('input[name="comment"]');
    var shown = preview.querySelector(".cp-comment");
    var count = form.querySelector("[data-count]");
    if (comment) {
      comment.addEventListener("input", function () {
        // The game counts UTF-16 places, as a string's length here does.
        if (shown) { shown.textContent = comment.value; }
        if (count) { count.textContent = comment.value.length + " / " + comment.maxLength; }
      });
    }
  });

  // A password box's Show button: shown only where this script runs (it is hidden in the page).
  document.querySelectorAll("button[data-reveal]").forEach(function (button) {
    var input = document.getElementById(button.getAttribute("data-reveal"));
    if (!input) { return; }
    button.hidden = false;
    button.addEventListener("click", function () {
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      button.setAttribute("aria-pressed", show ? "true" : "false");
      button.textContent = show ? button.dataset.hide : button.dataset.show;
      input.focus();
    });
  });

  // The section rail: the section in view is the lit one; the page opens at the section of what was just done.
  var area = document.querySelector(".account-area");
  if (area) {
    var links = area.querySelectorAll(".subnav a");
    var light = function (id) {
      links.forEach(function (link) {
        var on = link.getAttribute("href") === "#" + id;
        link.classList.toggle("on", on);
        if (on) { link.setAttribute("aria-current", "true"); } else { link.removeAttribute("aria-current"); }
      });
    };
    links.forEach(function (link) {
      link.addEventListener("click", function () { light(link.getAttribute("href").slice(1)); });
    });
    var open = area.getAttribute("data-open");
    if (open && open !== "profile" && !location.hash) {
      var section = document.getElementById(open);
      if (section) { section.scrollIntoView(); }
    }
  }
})();
