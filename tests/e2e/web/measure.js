// What the site's layout check measures on a page (tests/e2e/web/shoot.js and empty.js both ask it), in the browser:
//
//   page, els     the page's own sideways scroll, and the elements past the right edge (the background shards, the
//                 dialog and the phone menu's own slide left out);
//   cut           words cut off: a line of text that ends outside a box that hides what is past its edge (a title of
//                 two lines once pushed a song's genre and composer under a hero of a fixed height), and a line of
//                 one row that is wider than its own clipped box;
//   unlabelled    at a phone's width, a cell of a table shown as blocks (its headers hidden) that says a number, a date
//                 or a word with nothing beside it to say what it is: its column had a name, the cell has no label;
//                 and a labelled cell whose value wraps back under its label (a line starting left of its first);
//   menu          at a phone's width, a word of the top menu that does not fit the screen (cut mid-word at its edge),
//                 and a menu whose words would not fit the narrowest phone looked after (360 px wide);
//   askew         a button whose words are not in its middle or are larger than it (a link made to look like a button
//                 lost the box that centres its words, and they rose to its top edge beside two buttons that kept it);
//   forms         a field with no label, a slot not of the forms' heights (34, 42, 44, 48), the browser's own list or
//                 tick, a rule in a bracketed placeholder, a field marked wrong with no words under it (FORMS.md);
//   wraps         a number or a date that breaks over two lines (2026-11- over 17 09:30, 1 over 2), a figure parted
//                 from its unit (7.8 over GB) or a time from its date: each is read whole, so it lies on one line; and
//                 a word broken inside itself (syste over m), its column or part squeezed under it;
//   spacing       boxes (a card, a button, a field, a tag, an alert: anything with a fill, a border or a shadow) that
//                 touch or overlap a box beside them in the same parent; words nearer a box's edge than its padding;
//                 a gap between two boxes beside each other that is off the site's scale (whole steps of 2 px up to
//                 32, then 36, 40, 48, 56, 64); and words with no box under them, straight on the page's background
//                 (the bar, the hero, the notice and the foot are boxes of their own).
//
// Each is a short list of what was found (empty: nothing), so a line of the run names it. The page's composition (keys
// by their roles, words in their keys' middles, the type scale, headings, rows, the groups' left edges, fields' widths,
// boxes of one thing, pairs, the head's stage) is measured by compose, below.
const layout = page => page.evaluate(() => {
  const width = document.documentElement.clientWidth;
  const name = e => e.tagName + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\s+/).join('.') : '');
  const said = e => (e.innerText || e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40);
  const shown = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden'; };
  const skip = 'body *:not(.shards):not(.shards *):not(dialog):not(dialog *):not(.menu *)';
  const els = [...document.querySelectorAll(skip)].filter(e => e.getBoundingClientRect().right > width + 1)
    .map(e => e.tagName + '.' + e.className).slice(0, 4);
  // ---- words cut off by a box that hides its overflow
  const cut = [];
  const hides = e => { const s = getComputedStyle(e); return ['hidden', 'clip'].includes(s.overflowY) || ['hidden', 'clip'].includes(s.overflowX); };
  // An element's own words (its text nodes), not its children's.
  const own = e => [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
  for (const box of document.querySelectorAll('body *:not(dialog):not(dialog *)')) {
    // A long notice kept to two lines on a phone has its More right beside it (the strip opens): not cut off. The bar's
    // place-name ends where MENU starts, as a word that fits the bar's room.
    if (!hides(box) || !shown(box) || box.matches('.shards, .shards *, textarea, input, select, .site-notice.long .text')) continue;
    const b = box.getBoundingClientRect(), style = getComputedStyle(box);
    // The box's own line, wider than the box (a row of one line that is clipped at its end).
    if (own(box) && ['hidden', 'clip'].includes(style.overflowX) && box.scrollWidth > box.clientWidth + 1) {
      cut.push(name(box) + ' "' + said(box) + '" (its line is wider than its box)');
    }
    // A line of words inside it that ends under its bottom edge or past its right one.
    for (const e of box.querySelectorAll('*')) {
      if (e.closest('.shards') || !own(e) || !shown(e)) continue;
      const r = e.getBoundingClientRect();
      const under = ['hidden', 'clip'].includes(style.overflowY) && r.bottom > b.bottom + 1;
      const past = ['hidden', 'clip'].includes(style.overflowX) && r.right > b.right + 1;
      if (under || past) cut.push(name(e) + ' "' + said(e) + '" (' + (under ? 'under' : 'past') + ' the edge of ' + name(box) + ')');
    }
  }
  // ---- cells with no label in a table shown as blocks
  const unlabelled = [];
  for (const table of document.querySelectorAll('table')) {
    const head = table.querySelector('thead');
    if (!head || getComputedStyle(head).display !== 'none') continue;
    const names = [...head.querySelectorAll('th')].map(th => th.textContent.trim());
    for (const row of table.querySelectorAll('tbody tr')) {
      [...row.children].forEach((cell, i) => {
        // The row's first cell is its name; a cell with a control in it names itself; a column without a name has
        // none to give; a cell that shows nothing says nothing.
        if (i === 0 || !names[i] || !shown(cell) || !cell.textContent.trim()) return;
        if (cell.querySelector('input, select, button, a.btn')) return;
        const before = getComputedStyle(cell, '::before').content;
        if (!before || before === 'none' || before === '""') {
          unlabelled.push(name(table) + ' "' + said(cell) + '" (column "' + names[i] + '")');
          return;
        }
        // A labelled cell whose value takes more than one line: every line starts where its first did (the label is
        // a column of its own), never back under the label. The cell's own contents as a range: a box for each line
        // of its words and for each element in it, the first the value's start.
        const range = document.createRange();
        range.selectNodeContents(cell);
        const boxes = [...range.getClientRects()].filter(r => r.width > 0 && r.height > 0);
        if (boxes.length > 1 && Math.min(...boxes.map(r => r.left)) < boxes[0].left - 1) {
          unlabelled.push(name(table) + ' "' + said(cell) + '" (column "' + names[i] + '": runs under its label)');
        }
      });
    }
  }
  // ---- the top menu's words on a phone: the bar's one row (the mark, where one is, MENU) whole on the screen, and a
  // menu still in the bar (a page without the sheet) no wider than the narrowest phone looked after.
  const menu = width <= 760 ? [...document.querySelectorAll('.bar a, .bar button, .menu a')].filter(a => {
    const r = a.getBoundingClientRect();
    return r.width > 0 && (r.left < -1 || r.right > width + 1);
  }).map(a => a.textContent.trim()) : [];
  // The room its words take, against the narrowest phone looked after (the page is measured at one phone width; the
  // menu is the one row that must not wrap, so its fit is worked out for the narrower one too): its words from the
  // first to the last with the row's own padding, against the row's width on a 360 px screen (this screen's, less
  // what this screen is wider). A menu the phone shows in MENU's sheet instead has no row to fit.
  const bar = document.querySelector('.menu');
  const links = bar && bar.offsetWidth ? [...bar.querySelectorAll('a')] : [];
  if (width <= 760 && links.length) {
    const pad = getComputedStyle(bar);
    const needs = links[links.length - 1].getBoundingClientRect().right - links[0].getBoundingClientRect().left +
      parseFloat(pad.paddingLeft) + parseFloat(pad.paddingRight);
    const room = bar.clientWidth - (width - 360);
    if (needs > room + 0.5) menu.push('(' + Math.round(needs) + ' px of words: ' + Math.round(room) + ' px on a 360 px phone)');
  }
  // ---- a button's words in its middle, and no larger than it
  const askew = [];
  for (const button of document.querySelectorAll('.btn')) {
    // Only a button that shows, with words of its own (one that holds only a picture has no line to be out of place).
    if (!shown(button) || !own(button)) continue;
    // The room its words take: the box around everything inside it.
    const range = document.createRange();
    range.selectNodeContents(button);
    const words = range.getBoundingClientRect(), box = button.getBoundingClientRect();
    // How far the words' middle is under (or, negative, over) the button's own.
    const off = (words.top + words.bottom) / 2 - (box.top + box.bottom) / 2;
    if (Math.abs(off) > 3) askew.push(name(button) + ' "' + said(button) + '" (' + Math.round(off) + ' px off its middle)');
    else if (words.height > box.height + 1 || words.width > box.width + 1) {
      askew.push(name(button) + ' "' + said(button) + '" (its words are larger than it)');
    }
  }
  // ---- spacing: boxes apart, words inside their box's padding, gaps on the scale, no words on the bare page
  const spacing = [];
  const clear = c => !c || c === 'transparent' || /rgba\([^)]*,\s*0\)$/.test(c);
  // A box: something drawn, so its edge shows (a fill, an image, a border on more than one side, a shadow), seen (not
  // a control laid see-through over another, as the upload's file field is), and not a part of a table (its cells and
  // rows meet by design, a seam between them). A line along one side alone is a seam between rows, not a box's edge.
  const isBox = e => {
    const s = getComputedStyle(e);
    if (parseFloat(s.opacity) === 0 || ['TR', 'TD', 'TH', 'THEAD', 'TBODY', 'TABLE'].includes(e.tagName)) return false;
    const sides = ['Top', 'Right', 'Bottom', 'Left'].filter(side => parseFloat(s['border' + side + 'Width']) > 0 &&
      !clear(s['border' + side + 'Color'])).length;
    return !clear(s.backgroundColor) || s.backgroundImage !== 'none' || s.boxShadow !== 'none' || sides > 1;
  };
  // A band: a box as wide as the page (the bar, the notice's line, the foot), which meets the next band by design.
  const band = r => r.width >= width - 2;
  // Where words are framed: a box, or a row that scrolls sideways (the phone menu), whose own padding frames them.
  // The front door's mark and line (the sign-in, the first run) stand on the page's own perforated metal, as the hero's
  // words stand on its gradient: the door frames them.
  const frames = e => {
    const s = getComputedStyle(e);
    return ['auto', 'scroll'].includes(s.overflowX) || e.matches('.door, .lost, .lost-code');
  };
  // (A chart's scale labels are set on its guides, over the drawing: placed by the data, not by the page's spacing.)
  const outside = 'dialog, dialog *, .shards, .shards *, .tip, svg, svg *, script, style, option, .visually-hidden, ' +
    '.toast, .toast *, .menu-sheet, .menu-sheet *, .trend-y';
  const boxes = [...document.querySelectorAll('body *')].filter(e => !e.matches(outside) && shown(e) && isBox(e) &&
    getComputedStyle(e).position !== 'fixed');
  const steps = new Set([0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 36, 40, 48, 56, 64]);
  const boxed = new Set(boxes);
  for (const box of boxes) {
    const r = box.getBoundingClientRect();
    // Its next box in the same parent, on the same row or in the same column.
    for (let next = box.nextElementSibling; next; next = next.nextElementSibling) {
      if (!boxed.has(next)) continue;
      // A key laid inside its field (Show, Copy, a stepper: a .field-slot's .slot-key) sits over it by design.
      if (box.parentElement.matches('.field-slot') && (box.matches('.slot-key') || next.matches('.slot-key'))) continue;
      const n = next.getBoundingClientRect();
      const sideBySide = n.top < r.bottom - 1 && n.bottom > r.top + 1;
      const stacked = n.left < r.right - 1 && n.right > r.left + 1;
      // The next box neither beside it nor under it (the first of the next row of a grid): nothing to measure.
      if (!sideBySide && !stacked) break;
      const gap = sideBySide ? Math.max(n.left - r.right, r.left - n.right) : Math.max(n.top - r.bottom, r.top - n.bottom);
      if (gap < 1.5 && band(r) && band(n)) break;
      if (gap < 1.5) {
        spacing.push(name(box) + ' and ' + name(next) + ' touch (' + Math.round(gap) + ' px)');
      } else if (gap < 70 && !steps.has(Math.round(gap)) && Math.abs(gap - Math.round(gap)) < 0.3) {
        spacing.push(name(box) + ' to ' + name(next) + ': ' + Math.round(gap) + ' px is off the scale (in ' + name(box.parentElement) + ' at ' +
                     Math.round(r.left) + ',' + Math.round(r.top + window.scrollY) + ')');
      }
      break;
    }
  }
  // Words: each line of text, against the nearest box around it.
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const parent = node.parentElement;
    if (!node.textContent.trim() || !parent || parent.closest(outside) || !shown(parent)) continue;
    const range = document.createRange();
    range.selectNodeContents(node);
    const t = range.getBoundingClientRect();
    if (!t.width || !t.height) continue;
    let box = parent;
    while (box && box !== document.body && !boxed.has(box) && !frames(box)) box = box.parentElement;
    if (!box || box === document.body) {
      spacing.push(name(parent) + ' "' + said(parent) + '" sits on the bare page');
      continue;
    }
    // A field's or a button's own words are placed by the browser and the button's check (askew); words of an inline
    // box (a tag in a line) sit on their line.
    if (box.matches('input, select, textarea, .btn, button') || getComputedStyle(box).display === 'inline') continue;
    // Text kept as written (a licence's) hangs its spaces at a line's end past the padding: its lines are its own.
    if (['pre', 'pre-wrap'].includes(getComputedStyle(parent).whiteSpace)) continue;
    const b = box.getBoundingClientRect(), s = getComputedStyle(box);
    // Sideways only: a line's glyphs reach above and below its line box by the face's own measure, so the padding
    // over and under words is the box's line height's to keep, not theirs (words cut at a box's edge are "cut").
    const near = [['left', t.left - b.left, s.paddingLeft], ['right', b.right - t.right, s.paddingRight]]
      .filter(([, room, pad]) => room < parseFloat(pad) - 1.5);
    if (near.length) {
      spacing.push(name(parent) + ' "' + said(parent) + '" nearer the ' + near[0][0] + ' edge of ' + name(box) +
                   ' than its padding (' + Math.round(near[0][1]) + ' of ' + parseFloat(near[0][2]) + ' px)');
    }
  }
  // ---- forms (FORMS.md): every field a person types in or picks from has its label, the slot's own heights, the
  // site's own list and tick (never the browser's), no rule written as a placeholder in brackets, and a field marked
  // wrong has its words under it.
  const forms = [];
  for (const f of document.querySelectorAll('input:not([type=hidden]):not([type=file]):not([type=checkbox]):not([type=radio]):not([type=range]), select, textarea')) {
    if (!shown(f) || f.closest('dialog')) continue;
    const labelled = (f.labels && f.labels.length > 0) || f.getAttribute('aria-label') || f.getAttribute('aria-labelledby');
    if (!labelled) forms.push(name(f) + ' has no label');
    const h = Math.round(f.getBoundingClientRect().height);
    if (f.tagName !== 'TEXTAREA' && ![34, 42, 44, 48].includes(h)) forms.push(name(f) + ' is ' + h + ' px tall');
    if (f.tagName === 'SELECT' && !['none', 'base-select'].includes(getComputedStyle(f).appearance)) forms.push(name(f) + ' is the browser\'s own list');
    if (/^\(.*\)$/.test(f.getAttribute('placeholder') || '')) forms.push(name(f) + ' says its rule in a placeholder');
  }
  for (const c of document.querySelectorAll('input[type=checkbox], input[type=radio]')) {
    if (!shown(c) || c.closest('.choice, .seg, dialog')) continue;
    if (getComputedStyle(c).appearance !== 'none') forms.push(name(c) + ' is the browser\'s own tick');
  }
  for (const f of document.querySelectorAll('[aria-invalid="true"]')) {
    const said = (f.getAttribute('aria-describedby') || '').split(/\s+/).map(id => document.getElementById(id)).filter(Boolean);
    if (!said.some(e => e.matches('.field-error'))) forms.push(name(f) + ' is marked wrong with no words under it');
  }
  // ---- a number or a date breaking over two lines, or a figure parted from its unit, or a time from its date: each
  // as a range of its text has its first and last boxes on one line (a range that wraps gives a box on each line it is
  // on). A number of two digits or more, or digits with their marks (2026-11-17, 09:30, 1,234, 11/17); a figure and its
  // unit (7.8 GB, 16.8 ms, 3 h, 12 min); a date and its time (2026-11-05 19:23). Only words of their own: digits inside
  // a longer word (a backup's file name, opendmt3-backup-20261117-045835-manual.sqlite) are that word's, which may break
  // where a long name must.
  const wraps = [];
  const texts = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const figure = /(?<![\p{L}\p{N}_.-])\d[\d\u2060:.,/-]*\d(?![\p{L}\p{N}_-])/gu;
  const paired = /(?<![\p{L}\p{N}_.-])(?:\d{4}-\u2060?\d{2}-\u2060?\d{2}[ \u00a0]\d{1,2}:\d{2}|\d[\d,.]*[ \u00a0](?:[KMGT]B|ms|FPS|fps|min|h|Hz|dB|px)(?![\p{L}\p{N}_]))/gu;
  for (let n = texts.nextNode(); n; n = texts.nextNode()) {
    const host = n.parentElement;
    // Words a person sees: not a script's, not a field's own (a textarea draws its text inside itself), not hidden.
    if (!host || host.closest('script, style, textarea, dialog:not([open]), [hidden]') || !shown(host)) continue;
    for (const m of [...n.textContent.matchAll(figure), ...n.textContent.matchAll(paired)]) {
      const range = document.createRange();
      range.setStart(n, m.index);
      range.setEnd(n, m.index + m[0].length);
      const boxes = [...range.getClientRects()].filter(r => r.width > 0 && r.height > 0);
      if (boxes.length > 1 && boxes[boxes.length - 1].top - boxes[0].top > boxes[0].height / 2) {
        wraps.push(name(host) + ' "' + m[0].replace(/\u2060/g, '').replace(/\u00a0/g, ' ') + '" breaks over two lines');
      }
    }
  }
  // ---- a word broken inside itself over two lines: a column or a row's part squeezed under its longest word (a
  // Korean page's table broke "system" into "syste" and "m"). Words of Latin letters (digits after the first letter
  // too), whole: not inside a longer run of letters or digits. Not where a long name may break anywhere by its own
  // rule (code, a token, a hash, a field's own words); a number's breaking is the check above.
  const lettered = /(?<![\p{L}\p{N}_])[A-Za-z][A-Za-z0-9]+(?![\p{L}\p{N}_])/gu;
  const words = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = words.nextNode(); n; n = words.nextNode()) {
    const host = n.parentElement;
    if (!host || host.closest('script, style, textarea, code, pre, kbd, .hex, .token, .token-name, .shards, ' +
                                'dialog:not([open]), [hidden]') || !shown(host)) continue;
    for (const m of n.textContent.matchAll(lettered)) {
      const range = document.createRange();
      range.setStart(n, m.index);
      range.setEnd(n, m.index + m[0].length);
      const boxes = [...range.getClientRects()].filter(r => r.width > 0 && r.height > 0);
      if (boxes.length > 1 && boxes[boxes.length - 1].top - boxes[0].top > boxes[0].height / 2) {
        wraps.push(name(host) + ' "' + m[0] + '" breaks inside itself');
      }
    }
  }
  return {page: document.documentElement.scrollWidth - width, els, cut: cut.slice(0, 6),
          unlabelled: unlabelled.slice(0, 6), menu, askew: askew.slice(0, 6), spacing: [...new Set(spacing)].slice(0, 8),
          forms: forms.slice(0, 6), wraps: wraps.slice(0, 6)};
});

// The page's floating layers (the charts' and the DJ's weeks' tips), each opened as a person opens it, by pointing at
// it: the first, the middle and the last of each kind, scrolled into the middle of the screen first. Each must lie
// wholly inside the screen and on top of everything at its corners and its middle (nothing drawn over it). Returns
// the list of those that do not (empty: all fine) and how many were opened.
const LAYERS = ['.wk', '.trend-hours .hr', '.slot', '.heat i'];
const layers = async page => {
  const faults = [];
  let opened = 0;
  for (const kind of LAYERS) {
    const all = await page.$$(kind);
    const picked = [...new Set([0, Math.floor(all.length / 2), all.length - 1])].filter(i => i >= 0 && i < all.length);
    for (const i of picked) {
      const handle = all[i];
      await handle.evaluate(e => e.scrollIntoView({block: 'center', inline: 'center'}));
      await handle.hover();
      opened += 1;
      const fault = await handle.evaluate(e => {
        const tip = e.querySelector('.tip');
        if (!tip) return 'no tip';
        const r = tip.getBoundingClientRect();
        if (!r.width || !r.height || getComputedStyle(tip).display === 'none') return 'its tip does not open';
        const w = document.documentElement.clientWidth, h = window.innerHeight;
        if (r.left < 0 || r.top < 0 || r.right > w || r.bottom > h) return 'its tip leaves the screen';
        // The tip lets the pointer through (pointer-events: none): for the look only, it takes it.
        tip.style.pointerEvents = 'auto';
        const points = [[r.left + 2, r.top + 2], [r.right - 2, r.top + 2], [r.left + 2, r.bottom - 2],
                        [r.right - 2, r.bottom - 2], [(r.left + r.right) / 2, (r.top + r.bottom) / 2]];
        for (const [x, y] of points) {
          const top = document.elementFromPoint(x, y);
          if (!top || !(top === tip || tip.contains(top))) tip.style.pointerEvents = '';
          if (!top || !(top === tip || tip.contains(top))) return 'something lies over its tip at ' + Math.round(x) + ',' + Math.round(y) + ' (' + (top ? top.tagName + '.' + top.className : 'nothing') + ')';
        }
        tip.style.pointerEvents = '';
        return '';
      });
      if (fault) faults.push(kind + ' #' + i + ': ' + fault);
    }
  }
  // The pointer moved off, so no tip stays open in the page's screenshot.
  await page.mouse.move(0, 0);
  return {faults, opened};
};

// The page's frame on screen, pressed where a person would look for it (elementFromPoint, as a click lands): the bar's
// mark, the menu item of the page showing (on a phone MENU, the menu being in its sheet), and on one's account the
// side menu's item showing; at the page's top, and halfway down its scroll (the bar is sticky; on a tablet or a phone
// the side menu is a band under the head, so it is looked for at the top only). `kind` says which site's frame the page
// must have: 'console' (the admin site's: its band, its mark that says ADMIN, its keys, and its rail at the top) or
// 'players' (the players' bar); a page in the other's frame is a fault. The door (the sign-in, the first run) has no
// frame by design. The page is left at its top, at rest, for its picture (a picture taken scrolled drew the sticky bar
// halfway down the page).
const frame = async (page, kind) => {
  const settle = () => page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
  const look = where => page.evaluate(([where, kind]) => {
    const bar = document.querySelector('.bar');
    if (!bar) return ['no bar'];
    const console_ = bar.classList.contains('console');
    if (kind && console_ !== (kind === 'console')) return [where + ': the ' + (console_ ? "admin site's" : "players'") + ' frame on a page of the ' + (kind === 'console' ? 'admin site' : "players' site")];
    if (bar.classList.contains('door-bar')) return [];
    const at = selector => {
      const e = document.querySelector(selector);
      if (!e) return where + ': no ' + selector;
      const r = e.getBoundingClientRect();
      if (!r.width || !r.height) return where + ': ' + selector + ' not shown';
      const x = r.left + r.width / 2, y = r.top + Math.min(r.height / 2, 16);
      if (y < 0 || y > innerHeight || x < 0 || x > innerWidth) return where + ': ' + selector + ' off the screen';
      const hit = document.elementFromPoint(x, y);
      return hit && (hit === e || e.contains(hit)) ? null : where + ': ' + selector + ' under ' + (hit ? hit.tagName + '.' + hit.className : 'nothing');
    };
    const faults = [at('.bar .brand')];
    // The admin site's mark says ADMIN (the family's lockup: its role word), and its rail is under the band at the top
    // (unless a toast stands over it: a toast's strip lies right under the band, over the page, by design).
    if (console_ && !/ADMIN/.test((bar.querySelector('.brand .s') || {}).textContent || '')) faults.push(where + ': the mark says no ADMIN');
    if (console_ && where === 'top' && document.querySelector('.rail') && !document.querySelector('.toast:popover-open')) {
      faults.push(at('.rail .item'));
    }
    if (innerWidth <= 760) {
      faults.push(at('.bar .menu-key'));
    } else {
      // The item of the page showing; a page of no section (one's account, the licences) has the menu itself.
      faults.push(at(document.querySelector('.bar .menu a.on') ? '.bar .menu a.on' : '.bar .menu'));
    }
    if (document.querySelector('.side-nav') && (where === 'top' || innerWidth > 1000)) faults.push(at('.side-nav a.on'));
    return faults.filter(Boolean);
  }, [where, kind]);
  await page.evaluate(() => window.scrollTo(0, 0));
  await settle();
  const faults = await look('top');
  const room = await page.evaluate(() => document.documentElement.scrollHeight - innerHeight);
  if (room > 40) {
    await page.evaluate(room => window.scrollTo(0, Math.round(room / 2)), room);
    await settle();
    faults.push(...await look('halfway'));
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await settle();
  return faults;
};

// The page's composition, measured (the owner's rules of 11-19: a page is composed, not boxes stacked; every text and key
// measured), in the browser. Each is a short list of what was found (empty: nothing):
//
//   keys      a key not of its role's height or side padding (main and ordinary keys are the page's controls' height,
//             small keys a table row's, an icon key square), or wider than its words and its padding (a key stretched
//             across its card or row);
//   ink       a key's words off its middle: up and down, the ink of its letters (a capital's height over the line, a
//             Hangul syllable's whole ink) against the key's inside; across, the box of everything it holds;
//   type      words of a size off the site's steps, or lines of a paragraph closer or farther apart than reading
//             wants (a line's height 1.35 to 1.8 times its size);
//   headings  a heading smaller than the words under it (a card's name smaller than its rows);
//   rows      controls side by side in one row not on one line (their tops and feet apart), controls stacked in one
//             column not on one edge, a group's row whose name is not on its value's first baseline (a fact) or on its
//             control's middle (a field, a key);
//   align     words in a group that start a few pixels off the group's own left edge (a table's cell padding, an odd
//             margin): every line of a group starts on its edge or well in from it;
//   sizing    a field wider than what it takes by far (an ID of 8 letters across a card);
//   single    a box that holds one key, or one fact, and nothing else;
//   pairs     groups side by side that are not of one height;
//   stage     the head's stage not flush under the bar and clear of every other box (its shards would end in the gap
//             or at a box's edge).
//
// `STEPS` is the site's type scale (site.css's :root says it in words).
const STEPS = [11, 12, 13, 14, 15, 17, 20, 24, 28, 32, 40, 48, 56, 64];
const compose = page => page.evaluate(STEPS => {
  const out = {keys: [], ink: [], type: [], headings: [], rows: [], align: [], sizing: [], single: [], pairs: [], stage: []};
  const width = document.documentElement.clientWidth;
  const name = e => e.tagName + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\s+/).join('.') : '');
  const said = e => (e.innerText || e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 32);
  const shown = e => {
    const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && parseFloat(s.opacity) > 0;
  };
  // Not the page's own: a dialog not open, the phone menu's sheet, a toast, a tip, the mark (a drawing, not words).
  const aside = 'dialog:not([open]), dialog:not([open]) *, .menu-sheet:not(:popover-open), .menu-sheet:not(:popover-open) *, ' +
    '.toast, .toast *, .tip, .tip *, .logo, .logo *, svg, svg *, script, style, .visually-hidden, .skip';
  // Drawings with words in them, in their own proportions: the DJ card as the game draws it, a page's big code.
  const drawn = '.djcard, .djcard *, .card-preview, .card-preview *, .lost-code';
  const px = v => parseFloat(v) || 0;
  const own = e => [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
  // Where a line of words sits: a probe of no size put at the start of its first words (in a span with them, so a flex
  // or grid box does not make the probe an item of its own), its foot the line's baseline.
  const baselineOf = e => {
    const walker = document.createTreeWalker(e, NodeFilter.SHOW_TEXT);
    let text = walker.nextNode();
    while (text && !text.textContent.trim()) text = walker.nextNode();
    if (!text) return null;
    const hold = document.createElement('span'), probe = document.createElement('span');
    probe.style.cssText = 'display:inline-block;width:0;height:0;vertical-align:baseline;padding:0;margin:0;border:0';
    text.parentNode.insertBefore(hold, text);
    hold.appendChild(probe);
    hold.appendChild(text);
    const y = probe.getBoundingClientRect().bottom;
    hold.parentNode.insertBefore(text, hold);
    hold.remove();
    return y;
  };
  const root = getComputedStyle(document.documentElement);
  const ctl = px(root.getPropertyValue('--ctl')), ctlSm = px(root.getPropertyValue('--ctl-sm'));

  // ---- keys: each by its role, at its role's height and side padding, no wider than its words want
  const role = k => k.matches('.btn.primary') ? 'main' : k.matches('.btn.small') ? 'small' : k.matches('.btn') ? 'ordinary' :
    k.matches('.icon-key, .toast-close') ? 'icon' : null;
  const spec = {main: [ctl, 18], ordinary: [ctl, 18], small: [ctlSm, 12], icon: [36, 0]};
  const canvas = document.createElement('canvas').getContext('2d');
  for (const k of document.querySelectorAll('.btn, .icon-key, .toast-close')) {
    if (k.closest(aside) || !shown(k)) continue;
    const r = role(k);
    if (!r) continue;
    const box = k.getBoundingClientRect(), s = getComputedStyle(k);
    const [height, pad] = spec[r];
    if (Math.abs(box.height - height) > 0.5) out.keys.push(`${name(k)} "${said(k)}" is ${box.height.toFixed(1)} px tall (${r} keys: ${height})`);
    if (r !== 'icon' && (Math.abs(px(s.paddingLeft) - pad) > 0.5 || Math.abs(px(s.paddingRight) - pad) > 0.5)) {
      out.keys.push(`${name(k)} "${said(k)}" has ${px(s.paddingLeft)}/${px(s.paddingRight)} px at its sides (${r} keys: ${pad})`);
    }
    if (r === 'icon' && Math.abs(box.width - height) > 0.5) out.keys.push(`${name(k)} is ${box.width.toFixed(1)} px wide (icon keys: square)`);
    // Its words and what it holds (an icon, a lamp): the box of them, as wide as they are.
    const range = document.createRange();
    range.selectNodeContents(k);
    const words = range.getBoundingClientRect();
    if (!words.width) continue;
    // Stretched: wider than its words, its padding and its least width (a key sized for its use, never across its card).
    const wants = Math.max(px(s.minWidth), words.width + px(s.paddingLeft) + px(s.paddingRight));
    if (r !== 'icon' && box.width > wants + 1.5) out.keys.push(`${name(k)} "${said(k)}" is ${Math.round(box.width)} px wide for ${Math.round(wants)} px of words and padding (stretched)`);
    // Across: the middle of what it holds against its own.
    const across = (words.left + words.right) / 2 - (box.left + box.right) / 2;
    // Up and down: the ink. The baseline where it is drawn (a probe of no size on it), the ink from the face itself.
    const text = [...k.childNodes].find(n => n.nodeType === 3 && n.textContent.trim()) ||
      [...k.querySelectorAll('*')].flatMap(e => [...e.childNodes]).find(n => n.nodeType === 3 && n.textContent.trim());
    let up = 0;
    if (text) {
      // The words wrapped for a moment in a span of their own, the probe on its line: in a key laid out as a flex box,
      // a bare probe would be a flex item of its own, set in the middle rather than on the words' baseline.
      const hold = document.createElement('span'), probe = document.createElement('span');
      probe.style.cssText = 'display:inline-block;width:0;height:0;vertical-align:baseline;padding:0;margin:0;border:0';
      text.parentNode.insertBefore(hold, text);
      hold.appendChild(probe);
      hold.appendChild(text);
      const baseline = probe.getBoundingClientRect().bottom;
      hold.parentNode.insertBefore(text, hold);
      hold.remove();
      const ts = getComputedStyle(text.parentElement);
      canvas.font = `${ts.fontStyle} ${ts.fontWeight} ${ts.fontSize} ${ts.fontFamily}`;
      const hangul = /[\uac00-\ud7a3]/.exec(text.textContent);
      const m = canvas.measureText(hangul ? hangul[0] : 'H');
      const top = baseline - m.actualBoundingBoxAscent, bottom = baseline + (hangul ? m.actualBoundingBoxDescent : 0);
      const inside = [box.top + px(s.borderTopWidth), box.bottom - px(s.borderBottomWidth)];
      up = (top + bottom) / 2 - (inside[0] + inside[1]) / 2;
    }
    if (Math.abs(up) > 0.5 || Math.abs(across) > 0.5) {
      out.ink.push(`${name(k)} "${said(k)}" ${Math.abs(up) > 0.5 ? (up > 0 ? 'low' : 'high') + ' by ' + Math.abs(up).toFixed(1) : ''}${Math.abs(up) > 0.5 && Math.abs(across) > 0.5 ? ', ' : ''}${Math.abs(across) > 0.5 ? (across > 0 ? 'right' : 'left') + ' by ' + Math.abs(across).toFixed(1) : ''} px`);
    }
  }

  // ---- type: every line of words at a step of the scale (the mark and pictures are drawings, not text)
  const sizes = new Map();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const host = n.parentElement;
    if (!n.textContent.trim() || !host || host.closest(aside) || host.closest('[hidden], select, option, input, textarea') || !shown(host)) continue;
    if (host.closest(drawn)) continue;
    const size = Math.round(px(getComputedStyle(host).fontSize) * 10) / 10;
    if (!STEPS.includes(size)) {
      const key = size + ' ' + name(host);
      if (!sizes.has(key)) sizes.set(key, `${size} px: ${name(host)} "${said(host)}"`);
    }
  }
  // A paragraph's lines (an element of its own words on two lines or more): its line height reads as a paragraph's.
  for (const e of document.querySelectorAll('p, li, td, dd, .row-value, .field-hint, .lead')) {
    if (e.closest(aside) || e.closest(drawn) || !shown(e) || !own(e)) continue;
    const st = getComputedStyle(e), size = px(st.fontSize), line = st.lineHeight === 'normal' ? size * 1.2 : px(st.lineHeight);
    // Its own words on two lines or more (the lines' boxes at two heights), not a box made tall by its neighbours.
    const words = document.createRange();
    words.selectNodeContents(e);
    const tops = new Set([...words.getClientRects()].filter(q => q.width > 0).map(q => Math.round(q.top)));
    if (tops.size < 2) continue;
    const ratio = line / size;
    if (ratio < 1.35 || ratio > 1.8) sizes.set('line ' + name(e), `${name(e)} "${said(e)}": lines ${line.toFixed(1)} px apart at ${size} px (${ratio.toFixed(2)})`);
  }
  out.type = [...sizes.values()];

  // ---- headings: never smaller than the words under them in their group
  const headings = [...document.querySelectorAll('h1, h2, h3, h4, [role="heading"]')].filter(h => !h.closest(aside) && shown(h));
  for (const h of headings) {
    const group = h.closest('.card, section, .group, .console-head, .page-head, .hero, form, .door, main') || h.parentElement;
    const own = px(getComputedStyle(h).fontSize);
    // The words of the group after the heading that are read (a cell, a row, a line), by how many letters each size has.
    const weight = new Map();
    const w2 = document.createTreeWalker(group, NodeFilter.SHOW_TEXT);
    for (let n = w2.nextNode(); n; n = w2.nextNode()) {
      const host = n.parentElement;
      if (!n.textContent.trim() || !host || host.closest(aside) || h.contains(host) || !shown(host)) continue;
      if (host.closest('h1, h2, h3, h4, th, .tag, .label, .kicker, .field-hint, .muted, .small, .btn, button, a.chip, .count, .lampchip')) continue;
      // Figures (a count, a score, a balance) are read as figures, not as the text a heading names.
      if (host.closest('.value, .big-value, .numeral, .total, .score, .stat, .hf, .plate, ' + drawn)) continue;
      if (!(h.compareDocumentPosition(host) & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
      const size = px(getComputedStyle(host).fontSize);
      weight.set(size, (weight.get(size) || 0) + n.textContent.trim().length);
    }
    if (!weight.size) continue;
    const body = [...weight.entries()].sort((a, b) => b[1] - a[1])[0][0];
    if (own + 0.5 < body) out.headings.push(`${name(h)} "${said(h)}" is ${own} px over words of ${body} px`);
  }

  // ---- rows: controls side by side on one line; stacked ones on one edge
  // (A tick with its words and a switch are controls of their line too.)
  const controls = e => [...e.querySelectorAll('input:not([type=hidden]):not([type=file]):not([type=checkbox]):not([type=radio]), select, textarea, .btn, .drop, label.check, .switch')]
    .filter(c => !c.closest(aside) && shown(c) && !c.matches('.slot-key, .field-slot .btn') && !(c.parentElement && c.parentElement.closest('.drop')));
  for (const form of document.querySelectorAll('form, .row-value, .actions, .form-actions')) {
    if (form.closest(aside) || !shown(form)) continue;
    const list = controls(form).filter(c => c.closest('form, .row-value, .actions, .form-actions') === form || form.matches('form'));
    // Side by side: overlapping rows of the screen.
    for (let i = 0; i < list.length; i++) {
      for (let j = i + 1; j < list.length; j++) {
        const a = list[i].getBoundingClientRect(), b = list[j].getBoundingClientRect();
        const overlap = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        const level = Math.abs(a.height - b.height) < 0.75 ? Math.max(Math.abs(a.top - b.top), Math.abs(a.bottom - b.bottom))
          : Math.abs((a.top + a.bottom) / 2 - (b.top + b.bottom) / 2);
        if (overlap > Math.min(a.height, b.height) / 2 && level > 0.75) {
          out.rows.push(`${name(list[i])} "${said(list[i])}" and ${name(list[j])} "${said(list[j])}" side by side, not on one line (${Math.round(a.top)}-${Math.round(a.bottom)} and ${Math.round(b.top)}-${Math.round(b.bottom)})`);
        }
      }
    }
    // Stacked: the first control of each line of a stacked form starts on one edge.
    if (form.matches('form') && getComputedStyle(form).display === 'grid') {
      const firsts = [];
      for (const c of list) {
        const r = c.getBoundingClientRect();
        if (!list.some(o => o !== c && o.getBoundingClientRect().right <= r.left + 1 && Math.min(o.getBoundingClientRect().bottom, r.bottom) - Math.max(o.getBoundingClientRect().top, r.top) > r.height / 2)) firsts.push([c, r.left]);
      }
      const edges = [...new Set(firsts.map(([, x]) => Math.round(x)))];
      if (edges.length > 1) out.rows.push(`${name(form)} stacks its controls on ${edges.length} edges (${edges.join(', ')})`);
    }
  }

  for (const row of document.querySelectorAll('.rows > .row')) {
    if (row.closest(aside) || !shown(row)) continue;
    const label = row.querySelector(':scope > .row-label'), value = row.querySelector(':scope > .row-value');
    if (!label || !value || !shown(label) || !shown(value)) continue;
    // Stacked (a phone): the name over its value, nothing to line up.
    if (value.getBoundingClientRect().top >= label.getBoundingClientRect().bottom - 1) continue;
    // A control the value starts with, of a line's height (a field, a key): the name on its middle. Words first, or a
    // tall control (an upload's box, a text area) with words in it: the name on the first words' baseline.
    const ctl = controls(value)[0];
    const firstWords = baselineOf(value);
    const first = ctl && ctl.getBoundingClientRect().height <= 48.5 && (firstWords === null || ctl.getBoundingClientRect().top < firstWords - 4) ? ctl : null;
    if (first) {
      // A control on the value's first line: the name's line on its middle.
      const c = first.getBoundingClientRect(), l = label.getBoundingClientRect();
      const lineH = px(getComputedStyle(label).lineHeight) || l.height;
      const mid = l.top + px(getComputedStyle(label).paddingTop) + lineH / 2;
      if (Math.abs(mid - (c.top + c.bottom) / 2) > 0.75) out.rows.push(`row "${said(label)}": its name ${Math.round(mid - (c.top + c.bottom) / 2)} px off its control's middle`);
    } else {
      const a = baselineOf(label), b = baselineOf(value);
      if (a !== null && b !== null && Math.abs(a - b) > 0.75) out.rows.push(`row "${said(label)}": its name ${Math.round(a - b)} px off its value's baseline`);
    }
  }

  // ---- align: in a group, words start on the group's edge or well in from it (never a few pixels off it)
  const framed = e => {
    const st = getComputedStyle(e);
    const clear = c => !c || c === 'transparent' || /rgba\([^)]*,\s*0\)$/.test(c);
    return !clear(st.backgroundColor) || st.backgroundImage !== 'none' || ['Left', 'Right', 'Top', 'Bottom'].filter(side =>
      px(st['border' + side + 'Width']) > 0 && !clear(st['border' + side + 'Color'])).length > 1;
  };
  for (const card of document.querySelectorAll('.card')) {
    if (card.closest(aside) || !shown(card)) continue;
    const cs = getComputedStyle(card), cr = card.getBoundingClientRect();
    const edge = cr.left + px(cs.borderLeftWidth) + px(cs.paddingLeft);
    for (const e of card.querySelectorAll('*')) {
      if (!own(e) || !shown(e) || e.closest(aside) || e.closest(drawn)) continue;
      const st = getComputedStyle(e);
      if (st.display.startsWith('inline') || st.position === 'absolute' || st.textAlign === 'right' || st.textAlign === 'center') continue;
      // A list's item with a marker starts after its marker, by design.
      if (e.tagName === 'LI' && st.listStyleType !== 'none') continue;
      // Words inside a box of their own (a well, a slot, a key, a tag) start on that box's edge, not the group's.
      let holder = e;
      while (holder !== card && holder.parentElement && !(holder !== e && framed(holder))) holder = holder.parentElement;
      if (holder !== card || framed(e)) continue;
      const r = e.getBoundingClientRect();
      const start = r.left + px(st.borderLeftWidth) + px(st.paddingLeft) + (st.textIndent ? px(st.textIndent) : 0);
      const off = start - edge;
      if (Math.abs(off) > 0.75 && Math.abs(off) < 24) out.align.push(`${name(e)} "${said(e)}" starts ${Math.round(off)} px off ${name(card)}'s left edge`);
    }
  }

  // ---- sizing: a field that takes few letters is not as wide as a card
  for (const f of document.querySelectorAll('input[maxlength]:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=file])')) {
    if (f.closest(aside) || !shown(f)) continue;
    const most = parseInt(f.getAttribute('maxlength'), 10);
    if (!most || most > 64) continue;
    const s = getComputedStyle(f);
    canvas.font = `${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
    // What it takes at its widest kind of letter for its field (a Korean name's syllables, else capitals and figures).
    const letter = Math.max(canvas.measureText('W').width * 0.75, canvas.measureText('가').width * (/name|dj|comment|reason|text/.test(f.name) ? 1 : 0));
    const slot = f.closest('.field-slot') || f;
    const keys = [...slot.querySelectorAll('.slot-key')].reduce((sum, k) => sum + k.getBoundingClientRect().width + 5, 0);
    const wants = most * letter + px(s.paddingLeft) + px(s.paddingRight) + keys;
    const r = slot.getBoundingClientRect();
    if (r.width > Math.max(wants * 2, wants + 120)) out.sizing.push(`${name(f)} "${f.name}" is ${Math.round(r.width)} px wide for ${most} letters (${Math.round(wants)} px)`);
  }

  // ---- single: a box with one key or one fact in it and nothing else
  for (const card of document.querySelectorAll('.card, .group')) {
    if (card.closest(aside) || !shown(card)) continue;
    const head = card.querySelector(':scope > h3:first-child, :scope > h2:first-child');
    const parts = [...card.querySelectorAll('*')].filter(e => !(head && head.contains(e)) && shown(e) && !e.closest(aside) &&
      !e.closest('[hidden]') && (e.matches('input:not([type=hidden]), select, textarea, .btn, button, table, img, canvas, .drop') ||
      (e.matches(':not(.btn):not(button):not(.btn *):not(button *):not(table *):not(.drop *)') &&
       [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()))));
    // Parts inside another part count once (a table's cells are the table).
    const top = parts.filter(p => !parts.some(q => q !== p && q.contains(p)));
    const keys = top.filter(p => p.matches('.btn, button'));
    // A table is as many facts as its rows, and its head naming its columns one more (a list of one row is a list).
    const facts = top.flatMap(p => p.matches('table') ? [...p.querySelectorAll('thead tr, tbody tr')] : p.matches('.btn, button') ? [] : [p]);
    if ((keys.length === 1 && facts.length <= 1) || (keys.length === 0 && facts.length === 1)) {
      out.single.push(`${name(card)} "${head ? said(head) : said(card)}" holds ${keys.length ? 'one key' : 'one fact'}${facts.length && keys.length ? ' and one line' : ''}`);
    }
  }

  // ---- pairs: boxes side by side end on one line: each box's column (the boxes stacked under it, as wide and as far
  // in, one gap apart) ends where the column beside it ends.
  const cards = [...document.querySelectorAll('.card')].filter(c => !c.closest(aside) && shown(c));
  const foot = card => {
    let r = card.getBoundingClientRect(), bottom = r.bottom;
    for (let moved = true; moved;) {
      moved = false;
      for (const o of cards) {
        const q = o.getBoundingClientRect();
        if (Math.abs(q.left - r.left) < 1 && Math.abs(q.width - r.width) < 1 && q.top > bottom - 1 && q.top - bottom <= 24.5) {
          bottom = q.bottom; moved = true;
        }
      }
    }
    return bottom;
  };
  for (let i = 0; i < cards.length; i++) {
    for (let j = i + 1; j < cards.length; j++) {
      if (cards[i].contains(cards[j]) || cards[j].contains(cards[i])) continue;
      const a = cards[i].getBoundingClientRect(), b = cards[j].getBoundingClientRect();
      if (Math.abs(a.top - b.top) < 1 && (a.right <= b.left || b.right <= a.left)) {
        const fa = foot(cards[i]), fb = foot(cards[j]);
        if (Math.abs(fa - fb) > 1) {
          out.pairs.push(`${name(cards[i])} "${said(cards[i].querySelector('h2, h3') || cards[i])}" ends at ${Math.round(fa - a.top)} px beside ${name(cards[j])} "${said(cards[j].querySelector('h2, h3') || cards[j])}" at ${Math.round(fb - b.top)} px`);
        }
      }
    }
  }

  // ---- stage: the head's stage flush under the bar, across the window, clear of every other box
  const bar = document.querySelector('.bar');
  for (const stage of document.querySelectorAll('.hero, .page-head')) {
    if (!shown(stage)) continue;
    const r = stage.getBoundingClientRect(), y = window.scrollY;
    if (r.left > 0.5 || r.right < width - 0.5) out.stage.push(`${name(stage)} is not across the window (${Math.round(r.left)}-${Math.round(r.right)})`);
    if (bar && y === 0) {
      const b = bar.getBoundingClientRect();
      if (Math.abs(r.top - b.bottom) > 0.5) out.stage.push(`${name(stage)} starts ${Math.round(r.top - b.bottom)} px under the bar (its shards end in the gap)`);
    }
    if (stage.querySelector('.shards') && !['hidden', 'clip'].includes(getComputedStyle(stage).overflowY)) out.stage.push(`${name(stage)} lets its shards out of its edges`);
    for (const e of document.querySelectorAll('.card, .notices, .notices-sheet, .site-notice, .alert')) {
      if (stage.contains(e) || e.contains(stage) || !shown(e)) continue;
      const q = e.getBoundingClientRect();
      if (q.bottom > r.top + 0.5 && q.top < r.bottom - 0.5 && q.right > r.left && q.left < r.right) {
        out.stage.push(`${name(e)} lies over ${name(stage)} (its shards end at that box's edge)`);
      }
    }
  }
  for (const k of Object.keys(out)) out[k] = [...new Set(out[k])].slice(0, 8);
  return out;
}, STEPS);

// A page's measure as one of the run's lines, and its place in the run's summary: `summary` counts the pages looked
// at and those with each kind of fault ({pages, sticking, cut, unlabelled, menu_cut, askew}).
const record = (summary, lang, width, path, over) => {
  summary.pages += 1;
  const faults = [];
  if (over.page > 0 || over.els.length > 0) { summary.sticking += 1; faults.push('STICKS OUT'); }
  if (over.cut.length > 0) { summary.cut += 1; faults.push('CUT OFF'); }
  if (over.unlabelled.length > 0) { summary.unlabelled += 1; faults.push('NO LABEL'); }
  if (over.menu.length > 0) { summary.menu_cut += 1; faults.push('MENU CUT'); }
  if (over.askew.length > 0) { summary.askew += 1; faults.push('BUTTON ASKEW'); }
  if (over.spacing.length > 0) { summary.spacing = (summary.spacing || 0) + 1; faults.push('SPACING'); }
  if (over.layers && over.layers.length > 0) { summary.layer_faults = (summary.layer_faults || 0) + 1; faults.push('LAYER'); }
  if (over.forms && over.forms.length > 0) { summary.form_faults = (summary.form_faults || 0) + 1; faults.push('FORM'); }
  if (over.frame && over.frame.length > 0) { summary.frame_faults = (summary.frame_faults || 0) + 1; faults.push('FRAME'); }
  if (over.wraps && over.wraps.length > 0) { summary.wrap_faults = (summary.wrap_faults || 0) + 1; faults.push('WRAPS'); }
  // The composition (compose, above): each kind a count of the pages that have it, and its word on the page's line.
  for (const [kind, key, word] of [['keys', 'key_faults', 'KEYS'], ['ink', 'ink_faults', 'WORDS OFF THEIR KEY'],
                                   ['type', 'type_faults', 'TYPE'], ['headings', 'heading_faults', 'HEADING'],
                                   ['rows', 'row_faults', 'ROWS'], ['align', 'align_faults', 'LEFT EDGE'],
                                   ['sizing', 'sizing_faults', 'SIZING'], ['single', 'single_faults', 'ONE THING'],
                                   ['pairs', 'pair_faults', 'PAIRS'], ['stage', 'stage_faults', 'STAGE']]) {
    if (over[kind] && over[kind].length > 0) { summary[key] = (summary[key] || 0) + 1; faults.push(word); }
  }
  console.log(lang, width, path, faults.length ? faults.join(', ') : 'ok', JSON.stringify(over));
};

module.exports = {layout, layers, frame, record, compose, STEPS};
