// What the site's layout check measures on a page (tests/e2e/web/shoot.js and empty.js both ask it), in the browser:
//
//   page, els     the page's own sideways scroll, and the elements past the right edge (the background shards, the
//                 dialog and the phone menu's own slide left out);
//   cut           words cut off: a line of text that ends outside a box that hides what is past its edge (a title of
//                 two lines once pushed a song's genre and composer under a hero of a fixed height), and a line of
//                 one row that is wider than its own clipped box;
//   unlabelled    at a phone's width, a cell of a table shown as blocks (its headers hidden) that says a number, a date
//                 or a word with nothing beside it to say what it is: its column had a name, the cell has no label;
//   menu          at a phone's width, a word of the top menu that does not fit the screen (cut mid-word at its edge),
//                 and a menu whose words would not fit the narrowest phone looked after (360 px wide);
//   askew         a button whose words are not in its middle or are larger than it (a link made to look like a button
//                 lost the box that centres its words, and they rose to its top edge beside two buttons that kept it);
//   forms         a field with no label, a slot not of the forms' heights (34, 42, 44, 48), the browser's own list or
//                 tick, a rule in a bracketed placeholder, a field marked wrong with no words under it (FORMS.md);
//   wraps         a number or a date that breaks over two lines (2026-11- over 17 09:30, 1 over 2), a figure parted
//                 from its unit (7.8 over GB) or a time from its date: each is read whole, so it lies on one line;
//   spacing       boxes (a card, a button, a field, a tag, an alert: anything with a fill, a border or a shadow) that
//                 touch or overlap a box beside them in the same parent; words nearer a box's edge than its padding;
//                 a gap between two boxes beside each other that is off the site's scale (whole steps of 2 px up to
//                 32, then 36, 40, 48, 56, 64); and words with no box under them, straight on the page's background
//                 (the bar, the hero, the notice and the foot are boxes of their own).
//
// Each is a short list of what was found (empty: nothing), so a line of the run names it.
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
    return ['auto', 'scroll'].includes(s.overflowX) || e.matches('.door, .lost-code');
  };
  const outside = 'dialog, dialog *, .shards, .shards *, .tip, svg, svg *, script, style, option, .visually-hidden, ' +
    '.toast, .toast *, .menu-sheet, .menu-sheet *';
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
  console.log(lang, width, path, faults.length ? faults.join(', ') : 'ok', JSON.stringify(over));
};

module.exports = {layout, layers, frame, record};
