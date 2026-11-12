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
//                 lost the box that centres its words, and they rose to its top edge beside two buttons that kept it).
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
    if (!hides(box) || !shown(box) || box.matches('.shards, .shards *, textarea, input, select')) continue;
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
  // ---- the top menu's words on a phone
  const menu = width <= 760 ? [...document.querySelectorAll('.menu a')].filter(a => {
    const r = a.getBoundingClientRect();
    return r.left < -1 || r.right > width + 1;
  }).map(a => a.textContent.trim()) : [];
  // The room its words take, against the narrowest phone looked after (the page is measured at one phone width; the
  // menu is the one row that must not wrap, so its fit is worked out for the narrower one too): its words from the
  // first to the last with the row's own padding, against the row's width on a 360 px screen (this screen's, less
  // what this screen is wider).
  const bar = document.querySelector('.menu');
  const links = bar ? [...bar.querySelectorAll('a')] : [];
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
  return {page: document.documentElement.scrollWidth - width, els, cut: cut.slice(0, 6),
          unlabelled: unlabelled.slice(0, 6), menu, askew: askew.slice(0, 6)};
});

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
  console.log(lang, width, path, faults.length ? faults.join(', ') : 'ok', JSON.stringify(over));
};

module.exports = {layout, record};
