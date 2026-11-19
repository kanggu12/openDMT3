// The account area and the admin's page of one player (templates/account.html, admin_player.html): the DJ card's
// preview follows each choice as it is made, and the page opens at the section of what was just done (a password's Show
// and the comment's count are the site's own: site.js). Without this file every form still works.
(function () {
  "use strict";

  // A picker opened shows its chosen picture: its box scrolled (never the page) so the chosen one is whole in it.
  document.querySelectorAll("details.picker").forEach(function (picker) {
    picker.addEventListener("toggle", function () {
      var box = picker.querySelector(".choices"), chosen = picker.querySelector("input:checked");
      if (!picker.open || !box || !chosen) { return; }
      // The chosen one's place inside the box's scrolled content, from both boxes on screen (an offsetTop would be
      // measured from whichever ancestor is positioned, the box itself on one page and its card on another).
      var item = chosen.closest(".choice"), seen = item.getBoundingClientRect(), frame = box.getBoundingClientRect();
      var top = seen.top - frame.top - box.clientTop + box.scrollTop, room = box.clientHeight;
      // Scrolled only when it is not whole already, then to the box's middle (the ones around it in sight too).
      if (top < box.scrollTop || top + seen.height > box.scrollTop + room) {
        box.scrollTop = Math.max(0, top - (room - seen.height) / 2);
      }
    });
  });

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
        form.querySelectorAll(".choices-pattern .choice").forEach(function (choice) {
          choice.style.backgroundImage = "url(/cards/plate/" + input.value + ".png)";
        });
      }
    });
    // The comment shows on the plate as it is typed (its count is the site's own: site.js).
    var comment = form.querySelector('input[name="comment"]');
    var shown = preview.querySelector(".cp-comment");
    if (comment && shown) {
      comment.addEventListener("input", function () { shown.textContent = comment.value; });
    }
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
