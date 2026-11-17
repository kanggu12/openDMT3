// The site's layout check, run by tests/e2e/web/run.sh in headless Chrome: every page of the players' site and of the
// admin site (its own port, its own sign-in) in English and Korean, at a desktop width and two phone widths, signed in
// as the admin, each page's frame the site's own (measure.js: frame). Per page it prints what the layout's measure finds (measure.js: what
// sticks out past the right edge, words cut off inside a box that hides its overflow, a cell of a stacked row with no
// label at the phone width, a word of the phone menu that does not fit, a button's words out of its middle), saves a
// full-page screenshot, then opens the
// questions asked before something goes (a player deleted, a player's plays reset, a new password, every play reset,
// a backup deleted, a token revoked, a player banned, one's own account deleted) and checks each fits the screen, makes an
// account and measures the page with its message to send, shows the Status page's list of what to look at, types in
// the songs filter (rows hide with no request, the count follows), makes an API token and measures it shown once,
// uploads a file too large for the page's limit (told before sending) and a real backup, does the same on the Song
// list tab with the song list the seed saved, and shows the Status page with maintenance off (the seeded server has it
// on, so every other page shows its line beside the notice). Before each upload its field is checked as a person meets
// it (drop()): the site's own box in the page's language with no word of the browser's own control showing, reached
// with Tab and opened with Space, naming the chosen file, and for a screen reader the browser's own control with the
// field's name and what is chosen.
// The last line is a summary the runner reads:
// {"pages": N, "sticking": N, "cut": N, "unlabelled": N, "menu_cut": N, "askew": N, "dialogs": N, "dialog_faults": N,
//  "filters": N, "filter_faults": N, "messages": N,
//  "message_faults": N, "looks": N, "look_faults": N, "tokens": N, "token_faults": N, "uploads": N, "upload_faults": N,
//  "song_lists": N, "song_list_faults": N, "drops": N, "drop_faults": N, "maintenances": N, "maintenance_faults": N}.
const fs = require('fs');
const puppeteer = require('puppeteer');
// The layout's measure, shared with the empty server's run (empty.js).
const {layout, layers, frame, record: recorded} = require('/w/measure.js');

const base = process.env.SITE || 'http://site:4730';
// The admin site, a site of its own on its own port (ADMIN-SITE.md), signed in to on its own door.
const admin = process.env.ADMIN || 'http://site:4731';
// The upload field's words in both languages, from the site's own table (run.sh reads strings.py): {key: [en, ko]}.
const words = JSON.parse(process.env.WORDS || '{}');
const pages = ['/', '/rankings', '/rankings?by=best30', '/rankings?by=month', '/songs', '/songs/4', '/dj/4', '/download',
               '/account', '/licenses'];
// The admin site's pages, and its Licenses page (the console's frame on a page of no tab).
const adminPages = ['/admin/players', '/admin/cabinets', '/admin/status', '/admin/server', '/admin/song_list', '/admin/log',
                    '/admin/log/plays', '/admin/log/requests', '/admin/backups',
                    // The admin's page of a player: one decorated (a picture, MAX points, a level set), one banned.
                    '/admin/players/HANA', '/admin/players/RIO', '/licenses'];
// The questions asked first: what each is, on which site, where, and the button of the form that asks it.
const asking = action => `form[data-ask]:has(input[name=action][value=${action}]) button.danger`;
// A player's own changes are on their page (the Players list leads there).
const questions = [['player delete', admin, '/admin/players/NOVA', asking('delete')],
                   ['player reset', admin, '/admin/players/NOVA', asking('reset_plays')],
                   // A new password ends the account's sign-ins: asked first too (its button is a plain one).
                   ['player new password', admin, '/admin/players/NOVA', 'form[data-ask]:has(input[name=action][value=password]) button'],
                   ['every play reset', admin, '/admin/players', asking('reset_all')],
                   ['backup delete', admin, '/admin/backups', asking('delete')],
                   ['token revoke', base, '/account', asking('token_revoke')],
                   // A form whose field is needed asks only once it is filled (the browser's own check comes first).
                   ['player ban', admin, '/admin/players/HANA', asking('ban'), ['input[name=reason]', 'Made-up reason']],
                   ['account delete', base, '/account', asking('delete_me'), ['#delete-current', 'pass1234']]];

(async () => {
  const browser = await puppeteer.launch({args: ['--no-sandbox']});
  const page = await browser.newPage();
  const summary = {pages: 0, sticking: 0, cut: 0, unlabelled: 0, menu_cut: 0, askew: 0, spacing: 0, layer_faults: 0,
                   layers: 0, dialogs: 0, dialog_faults: 0,
                   filters: 0, filter_faults: 0, messages: 0,
                   message_faults: 0, looks: 0, look_faults: 0, tokens: 0, token_faults: 0, uploads: 0,
                   upload_faults: 0, song_lists: 0, song_list_faults: 0, drops: 0, drop_faults: 0, maintenances: 0,
                   maintenance_faults: 0, form_faults: 0, frame_faults: 0, wrap_faults: 0, bars: 0, bar_faults: 0};
  // What the layout's measure finds on the page showing (measure.js), and its line and place in the summary.
  // The layout's measure, then the page's floating layers opened one by one (measure.js: layers), together.
  // Last, the page's frame on screen (measure.js: frame), which leaves the page at its top for its picture: the frame of
  // the site the page is on, `kind` ('players', or 'console' for the admin site's).
  const measure = async (kind = 'players') => {
    const over = await layout(page);
    const opened = await layers(page);
    summary.layers += opened.opened;
    const framed = await frame(page, kind);
    return Object.assign(over, {layers: opened.faults, frame: framed});
  };
  // Every whole page's picture is taken at rest at its top (one taken scrolled draws the sticky bar halfway down).
  const full = async path => {
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
    await page.screenshot({path, fullPage: true});
  };
  const record = (lang, width, path, over) => recorded(summary, lang, width, path, over);
  // An upload field on the page as a person meets it, before the round's upload: what it says and that the browser's own
  // words never show, the keyboard reaching it (Tab) and opening it (Space) with its ring showing, the file chosen
  // named with its size and the button then sending, and what a screen reader is told. Screenshots of the field in its
  // states go to /out. Returns whether all of it held.
  const drop = async (lang, width, which, file, name) => {
    const say = key => words[key][lang === 'en' ? 0 : 1];
    const look = () => page.evaluate(() => {
      const box = document.querySelector('form.upload .drop'), input = box.querySelector('input[type=file]');
      const b = box.getBoundingClientRect(), i = input.getBoundingClientRect(), style = getComputedStyle(box);
      return {pick: box.querySelector('.drop-pick').textContent, hint: box.querySelector('.drop-hint').textContent,
              text: box.innerText, sends: !box.closest('form').querySelector('button.send').disabled,
              hidden: getComputedStyle(input).opacity === '0',
              covers: Math.abs(b.left - i.left) < 1 && Math.abs(b.right - i.right) < 1 && Math.abs(b.top - i.top) < 1 &&
                      Math.abs(b.bottom - i.bottom) < 1,
              focused: document.activeElement === input, ring: style.outlineStyle + ' ' + style.outlineColor,
              edge: style.borderTopStyle + ' ' + style.borderTopColor, chosen: box.classList.contains('has-file'),
              // The section's colour as the page has it, for the edge of a box with a file in it.
              accent: (() => { const probe = document.createElement('i'); probe.style.color = 'var(--accent)';
                               document.body.append(probe); const colour = getComputedStyle(probe).color; probe.remove();
                               return colour; })()};
    });
    // The field's card, its heading, the form and the lines under it, as the page shows them.
    const shot = async state => (await page.$('.card:has(form.upload)')).screenshot(
      {path: `/out/${lang}-upload-${which}-${state}-${width}.png`});
    const before = await look();
    await shot('empty');
    // The browser's own control's words, in either language, are nowhere in what the box shows (its own "No file chosen
    // yet" is the site's).
    const own = /Choose File|No file chosen(?! yet)|Browse\.\.\.|파일 선택|선택된 파일 없음/;
    // From the card's heading (given a place in the focus order for this) the next stop of Tab is the field: the form's
    // hidden token takes none.
    await page.evaluate(() => { const h = document.querySelector('form.upload').closest('.card').querySelector('h3');
                                h.tabIndex = -1; h.focus(); });
    await page.keyboard.press('Tab');
    const keyed = await look();
    await shot('focus');
    // What a screen reader is told of the field: the browser's own control, named by the field, described by its hint.
    const reader = async () => {
      const node = await page.accessibility.snapshot({root: await page.$('form.upload input[type=file]'), interestingOnly: false});
      return node ? {role: node.role, name: node.name, description: node.description || ''} : null;
    };
    const told = await reader();
    // Space opens the file chooser, as on the browser's own control; the file chosen there is named in the box.
    const [chooser] = await Promise.all([page.waitForFileChooser({timeout: 5000}), page.keyboard.press('Space')]);
    await chooser.accept([file]);
    await page.waitForFunction(() => document.querySelector('form.upload .drop').classList.contains('has-file'), {timeout: 5000});
    // The edge eases to its colour: measured once it is there.
    await new Promise(r => setTimeout(r, 400));
    const after = await look();
    const toldAfter = await reader();
    await shot('chosen');
    const fine = before.pick === say('upload.choose') && before.hint.startsWith(say('upload.none')) && !before.sends &&
      before.hidden && before.covers && before.edge.startsWith('dashed') && !own.test(before.text) && keyed.focused &&
      keyed.ring.startsWith('solid') && after.edge === 'solid ' + after.accent &&
      keyed.ring.includes('95, 211, 255') && told && told.role === 'button' && told.name.length > 0 &&
      told.description.startsWith(say('upload.none')) && after.chosen && after.sends && after.pick === say('upload.change') &&
      after.hint.startsWith(name + ' · ') && / (KB|MB)$/.test(after.hint) && !own.test(after.text) && toldAfter &&
      toldAfter.description.startsWith(name);
    summary.drops += 1;
    if (!fine) summary.drop_faults += 1;
    console.log(lang, width, which + ' upload field', fine ? 'ok' : 'FAULT', JSON.stringify({before, keyed, told, after, toldAfter}));
  };
  let round = 0;
  for (const lang of ['en', 'ko']) {
    // A desktop, a phone and the narrowest phone looked after (360: a key that fit 390 ran past it).
    for (const [width, height] of [[1280, 860], [390, 844], [360, 740]]) {
      round += 1;
      await page.setViewport({width, height});
      await page.goto(base + '/lang/' + lang, {waitUntil: 'networkidle0'});
      // Each site's door first, then signed in on it for the rest: the players' site, then the admin site (its own
      // sign-in: the players' one never opens it).
      const door = async (site, kind, shot) => {
        await page.goto(site + '/signin', {waitUntil: 'networkidle0'});
        record(lang, width, (kind === 'console' ? 'admin ' : '') + '/signin', await measure(kind));
        await full(`/out/${lang}-${shot}-${width}.png`);
        await page.type('input[name=login_id]', 'BOSS');
        await page.type('input[name=password]', 'pass1234');
        await Promise.all([page.waitForNavigation({waitUntil: 'networkidle0'}), page.click('button.primary')]);
      };
      // A page looked at: everything folded opened first (the DJ card's choices, the tables behind charts, the
      // licences), so it is measured too; the pictures that load when they come into view loaded before the measure.
      const visit = async (site, kind, path, shot) => {
        await page.goto(site + path, {waitUntil: 'networkidle0'});
        await page.evaluate(() => document.querySelectorAll('details').forEach(d => { d.open = true; }));
        await page.evaluate(() => Promise.all([...document.images].map(i => { i.loading = 'eager';
          return i.complete ? null : new Promise(done => { i.onload = i.onerror = done; }); })));
        record(lang, width, (kind === 'console' ? 'admin ' : '') + path, await measure(kind));
        await full(`/out/${lang}-${shot}-${width}.png`);
      };
      await door(base, 'players', 'signin');
      for (const path of pages) {
        await visit(base, 'players', path, path.replace(/[\/?=&]/g, '_') || '_');
      }
      // The admin pages' old address on the players' port, from this browser (another PC than the server's): the
      // players' page that is not there.
      await visit(base, 'players', '/admin/status', 'players-port-admin');
      await door(admin, 'console', 'admin-signin');
      for (const path of adminPages) {
        await visit(admin, 'console', path, path === '/licenses' ? 'admin-licenses' : path.replace(/[\/?=&]/g, '_'));
      }
      // Each question: open, inside the screen, its question filled in; Esc closes it and nothing goes.
      for (const [what, site, path, button, fill] of questions) {
        await page.goto(site + path, {waitUntil: 'networkidle0'});
        const before = await page.evaluate(() => document.querySelectorAll('form[data-ask]').length);
        if (fill) await page.type(fill[0], fill[1]);
        await page.click(button);
        await new Promise(r => setTimeout(r, 400));
        const ask = await page.evaluate(() => {
          const box = document.getElementById('ask').getBoundingClientRect();
          return {open: document.getElementById('ask').open, question: document.getElementById('ask-question').textContent,
                  inside: box.left >= 0 && box.right <= document.documentElement.clientWidth && box.width > 0};
        });
        await page.screenshot({path: `/out/${lang}-dialog-${what}-${width}.png`});
        await page.keyboard.press('Escape');
        await new Promise(r => setTimeout(r, 200));
        const after = await page.evaluate(() => ({open: document.getElementById('ask').open,
                                                  forms: document.querySelectorAll('form[data-ask]').length}));
        const fine = ask.open && ask.inside && ask.question.length > 0 && !after.open && after.forms === before;
        summary.dialogs += 1;
        if (!fine) summary.dialog_faults += 1;
        console.log(lang, width, what + ' question', fine ? 'ok' : 'FAULT', JSON.stringify({ask, after, before}));
      }
      // The message to send: an account made here (an ID of its own each round), the page measured with the message.
      await page.goto(admin + '/admin/players', {waitUntil: 'networkidle0'});
      await page.type('form:has(input[name=action][value=make]) input[name=login_id]', 'MSG' + round);
      await Promise.all([page.waitForNavigation({waitUntil: 'networkidle0'}),
                         page.click('form:has(input[name=action][value=make]) button.primary')]);
      const message = await page.evaluate(() => {
        const box = document.getElementById('message');
        return box ? {lines: box.value.split('\n').length, rows: box.rows, scrolls: box.scrollHeight > box.clientHeight + 1,
                      // The address the server was given for its players (run.sh), never the one this browser used;
                      // one other PCs reach, so the page has nothing to add about it.
                      chosen: box.value.includes('http://192.168.0.5:4730/\n') && box.value.includes('http://192.168.0.5:4730/download') &&
                              !box.value.includes('site:4730') && !box.value.includes('4731'),
                      local: !!document.querySelector('.message-local')} : null;
      });
      record(lang, width, 'admin /admin/players (message)', await measure('console'));
      await full(`/out/${lang}-_admin_players-message-${width}.png`);
      summary.messages += 1;
      const messageFine = message !== null && message.lines === message.rows && !message.scrolls && message.chosen &&
        !message.local;
      if (!messageFine) summary.message_faults += 1;
      console.log(lang, width, 'message to send', messageFine ? 'ok' : 'FAULT', JSON.stringify(message));
      // The bar's floating layers pressed, not only pictured: the toast the account just made left stands inside the bar
      // or on its strip right under it, its middle its own; on a phone MENU opens its sheet from under the bar to the
      // window's foot, across it, its middle its own, MENU saying it is open, and it closes again.
      const bar = await page.evaluate(async () => {
        const out = {}, b = document.querySelector('.bar').getBoundingClientRect();
        const t = document.querySelector('.toast[data-toast]');
        if (t) {
          const r = t.getBoundingClientRect(), hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
          out.toast = {open: t.matches(':popover-open'), mine: t.contains(hit), under: t.classList.contains('under'),
                       inBar: r.top >= b.top - 1 && r.bottom <= b.bottom + 1, onBar: Math.abs(r.top - b.bottom) <= 1};
        }
        const key = document.querySelector('.menu-key');
        if (key && key.offsetWidth) {
          key.click();
          await new Promise(done => setTimeout(done, 200));
          const sheet = document.getElementById('menu-sheet'), r = sheet.getBoundingClientRect();
          const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
          out.sheet = {open: sheet.matches(':popover-open'), mine: sheet.contains(hit), top: Math.abs(r.top - b.bottom) <= 1,
                       foot: Math.abs(r.bottom - innerHeight) <= 1, across: r.left === 0 && Math.abs(r.right - innerWidth) <= 1,
                       said: key.getAttribute('aria-expanded') === 'true'};
          sheet.hidePopover();
          out.sheet.closed = !sheet.matches(':popover-open');
        }
        return out;
      });
      const toastFine = bar.toast && bar.toast.open && bar.toast.mine &&
        ((!bar.toast.under && bar.toast.inBar) || (bar.toast.under && bar.toast.onBar));
      const sheetFine = width > 760 || (bar.sheet && Object.values(bar.sheet).every(Boolean));
      summary.bars += 1;
      if (!toastFine || !sheetFine) summary.bar_faults += 1;
      console.log(lang, width, 'toast and menu sheet', toastFine && sheetFine ? 'ok' : 'FAULT', JSON.stringify(bar));
      // The Status page's list of what to look at, made so for a moment: every other account disabled through the
      // API (the seeded server has a backup, a song list and an installer), the page measured, then all enabled again.
      const others = await page.evaluate(async () => {
        const json = r => r.json();
        const token = (await fetch('/api/v1/session', {method: 'POST', headers: {'content-type': 'application/json'},
          body: JSON.stringify({login_id: 'BOSS', password: 'pass1234'})}).then(json)).token;
        const auth = {Authorization: 'Bearer ' + token};
        const ids = (await fetch('/api/v1/players', {headers: auth}).then(json)).players
          .filter(p => p.login_id !== 'BOSS' && !p.disabled).map(p => p.login_id);
        for (const id of ids) { await fetch('/api/v1/players/' + id + '/disable', {method: 'POST', headers: auth}); }
        return {token, ids};
      });
      await page.goto(admin + '/admin/status', {waitUntil: 'networkidle0'});
      const looks = await page.evaluate(() => document.querySelectorAll('p.alert.look').length);
      record(lang, width, 'admin /admin/status (to look at)', await measure('console'));
      await full(`/out/${lang}-_admin_status-look-${width}.png`);
      await page.evaluate(async others => {
        for (const id of others.ids) {
          await fetch('/api/v1/players/' + id + '/enable', {method: 'POST', headers: {Authorization: 'Bearer ' + others.token}});
        }
      }, others);
      summary.looks += 1;
      const lookFine = others.ids.length > 0 && looks === 1;
      if (!lookFine) summary.look_faults += 1;
      console.log(lang, width, 'to look at', lookFine ? 'ok' : 'FAULT', JSON.stringify({disabled: others.ids.length, looks}));
      // The songs filter: typing hides the rows that do not match, asks the server nothing, and the count follows.
      await page.goto(base + '/songs', {waitUntil: 'networkidle0'});
      let asked = 0;
      const counted = () => { asked += 1; };
      page.on('request', counted);
      await page.type('#song-filter', 'made');
      await new Promise(r => setTimeout(r, 300));
      page.off('request', counted);
      const filtered = await page.evaluate(() => {
        const rows = [...document.querySelectorAll('table.songs tbody tr')];
        return {shown: rows.filter(r => !r.hidden && r.offsetHeight > 0).length, all: rows.length,
                count: document.getElementById('song-count').textContent};
      });
      record(lang, width, '/songs (typed)', await measure());
      await full(`/out/${lang}-_songs-typed-${width}.png`);
      summary.filters += 1;
      const filterFine = asked === 0 && filtered.shown === 2 && filtered.all === 5 && filtered.count.includes('2')
        && filtered.count.includes('5');
      if (!filterFine) summary.filter_faults += 1;
      console.log(lang, width, 'songs filter', filterFine ? 'ok' : 'FAULT', JSON.stringify({asked, filtered}));
      // An API token made on the Account page: shown once in its box, whole (no scroll bar of its own), inside the
      // screen; the page measured with it.
      await page.goto(base + '/account', {waitUntil: 'networkidle0'});
      await page.type('form:has(input[name=action][value=token_make]) input[name=name]', 'Layout check ' + round);
      await page.select('form:has(input[name=action][value=token_make]) select[name=scope]', 'write');
      await Promise.all([page.waitForNavigation({waitUntil: 'networkidle0'}),
                         page.click('form:has(input[name=action][value=token_make]) button')]);
      const token = await page.evaluate(() => {
        const box = document.getElementById('made-token');
        return box ? {shape: /^odt3_[0-9a-f]{12}_[A-Za-z0-9_-]{43}$/.test(box.value),
                      scrolls: box.scrollHeight > box.clientHeight + 1,
                      inside: box.getBoundingClientRect().right <= document.documentElement.clientWidth} : null;
      });
      record(lang, width, '/account (token made)', await measure());
      await full(`/out/${lang}-_account-token-${width}.png`);
      summary.tokens += 1;
      const tokenFine = token !== null && token.shape && !token.scrolls && token.inside;
      if (!tokenFine) summary.token_faults += 1;
      console.log(lang, width, 'token shown once', tokenFine ? 'ok' : 'FAULT', JSON.stringify(token));
      // The Backups tab's upload: its field as a person meets it, then a file past the page's limit (made small here) is
      // told on the page and never sent; then a real backup (one of the list's, downloaded) is uploaded, checked and
      // listed, the page measured.
      await page.goto(admin + '/admin/backups', {waitUntil: 'networkidle0'});
      fs.writeFileSync('/tmp/notes.txt', 'Not a database, and longer than the limit set here.');
      await drop(lang, width, 'backup', '/tmp/notes.txt', 'notes.txt');
      await page.goto(admin + '/admin/backups', {waitUntil: 'networkidle0'});
      await (await page.$('form.upload input[type=file]')).uploadFile('/tmp/notes.txt');
      await page.evaluate(() => { document.querySelector('form[data-upload-most]').dataset.uploadMost = '4'; });
      let posted = 0;
      const posting = r => { if (r.method() === 'POST') posted += 1; };
      page.on('request', posting);
      await page.click('form.upload button.send');
      await new Promise(r => setTimeout(r, 400));
      page.off('request', posting);
      const told = await page.evaluate(() => {
        const said = document.querySelector('.upload-too-large'), box = document.querySelector('.drop');
        return {shown: !said.hidden && said.offsetHeight > 0, where: location.pathname,
                box: box.classList.contains('too-big') && getComputedStyle(box).borderTopColor === 'rgb(255, 79, 160)',
                sends: !box.closest('form').querySelector('button.send').disabled};
      });
      const name = await page.evaluate(() => document.querySelector('a.btn[download]').getAttribute('href').split('/').pop());
      const bytes = await page.evaluate(async name => {
        const data = new Uint8Array(await (await fetch('/admin/backups/' + name)).arrayBuffer());
        let text = '';
        for (const b of data) { text += String.fromCharCode(b); }
        return btoa(text);
      }, name);
      fs.writeFileSync('/tmp/backup.sqlite', Buffer.from(bytes, 'base64'));
      await page.goto(admin + '/admin/backups', {waitUntil: 'networkidle0'});
      await (await page.$('form.upload input[type=file]')).uploadFile('/tmp/backup.sqlite');
      await Promise.all([page.waitForNavigation({waitUntil: 'networkidle0'}), page.click('form.upload button.send')]);
      // What the upload did is said in the toast in the bar's place.
      const uploaded = await page.evaluate(() => ({ok: (document.querySelector('.toast[data-toast]:not(.bad) .toast-words') || {}).textContent || '',
                                                   rows: document.querySelectorAll('table.table tbody tr').length}));
      record(lang, width, 'admin /admin/backups (uploaded)', await measure('console'));
      await full(`/out/${lang}-_admin_backups-uploaded-${width}.png`);
      summary.uploads += 1;
      const uploadFine = posted === 0 && told.shown && told.box && !told.sends && told.where === '/admin/backups' &&
        uploaded.ok.includes('upload.sqlite');
      if (!uploadFine) summary.upload_faults += 1;
      console.log(lang, width, 'upload', uploadFine ? 'ok' : 'FAULT', JSON.stringify({posted, told, uploaded}));
      // The Song list tab's upload, as the Backups tab's: its field, then a file past the page's limit (made small here)
      // is told on the page and never sent; then the song list the seed saved is uploaded, taken in and said, the page
      // measured.
      await page.goto(admin + '/admin/song_list', {waitUntil: 'networkidle0'});
      await drop(lang, width, 'song-list', '/out/openDMT3-song-list.zip', 'openDMT3-song-list.zip');
      await page.goto(admin + '/admin/song_list', {waitUntil: 'networkidle0'});
      await (await page.$('form.upload input[type=file]')).uploadFile('/tmp/notes.txt');
      await page.evaluate(() => { document.querySelector('form[data-upload-most]').dataset.uploadMost = '4'; });
      let listPosted = 0;
      const listPosting = r => { if (r.method() === 'POST') listPosted += 1; };
      page.on('request', listPosting);
      await page.click('form.upload button.send');
      await new Promise(r => setTimeout(r, 400));
      page.off('request', listPosting);
      const listTold = await page.evaluate(() => {
        const said = document.querySelector('.upload-too-large'), box = document.querySelector('.drop');
        return {shown: !said.hidden && said.offsetHeight > 0, where: location.pathname,
                box: box.classList.contains('too-big') && getComputedStyle(box).borderTopColor === 'rgb(255, 79, 160)',
                sends: !box.closest('form').querySelector('button.send').disabled};
      });
      await (await page.$('.card:has(form.upload)')).screenshot({path: `/out/${lang}-upload-song-list-too-big-${width}.png`});
      await page.goto(admin + '/admin/song_list', {waitUntil: 'networkidle0'});
      await (await page.$('form.upload input[type=file]')).uploadFile('/out/openDMT3-song-list.zip');
      await Promise.all([page.waitForNavigation({waitUntil: 'networkidle0'}), page.click('form.upload button.send')]);
      // What the import did, or why it did not, is said in the toast in the bar's place.
      const taken = await page.evaluate(() => ({ok: (document.querySelector('.toast[data-toast]:not(.bad) .toast-words') || {}).textContent || '',
                                                 bad: (document.querySelector('.toast.bad[data-toast] .toast-words') || {}).textContent || ''}));
      record(lang, width, 'admin /admin/song_list (uploaded)', await measure('console'));
      await full(`/out/${lang}-_admin_song_list-uploaded-${width}.png`);
      summary.song_lists += 1;
      const songListFine = listPosted === 0 && listTold.shown && listTold.box && !listTold.sends &&
        listTold.where === '/admin/song_list' &&
        /5/.test(taken.ok) && !taken.bad;
      if (!songListFine) summary.song_list_faults += 1;
      console.log(lang, width, 'song list upload', songListFine ? 'ok' : 'FAULT', JSON.stringify({listPosted, listTold, taken}));
      // The Status page with maintenance off (the API turns it off for a moment, then on again): its card offers to
      // start it, and no page shows the maintenance line.
      const status = await page.evaluate(async token => {
        const auth = {Authorization: 'Bearer ' + token};
        const off = await fetch('/api/v1/maintenance', {method: 'DELETE', headers: auth}).then(r => r.json());
        return {off: off.on === false};
      }, others.token);
      await page.goto(admin + '/admin/status', {waitUntil: 'networkidle0'});
      // The rail's MAINTENANCE no longer in pink (the admin site has the rail where the players' site has its line).
      const offered = await page.evaluate(() => ({start: !!document.querySelector('input[name=action][value=maintenance_on]'),
                                                  line: !!document.querySelector('.site-notice.maintenance'),
                                                  rail: (document.querySelector('.rail a[href$="#maintenance"]') || {}).className}));
      record(lang, width, 'admin /admin/status (maintenance off)', await measure('console'));
      await full(`/out/${lang}-_admin_status-maintenance-off-${width}.png`);
      const back = await page.evaluate(async token => (await fetch('/api/v1/maintenance', {method: 'POST',
        headers: {Authorization: 'Bearer ' + token}}).then(r => r.json())).on, others.token);
      summary.maintenances += 1;
      const maintenanceFine = status.off && offered.start && !offered.line && offered.rail === 'item' && back === true;
      if (!maintenanceFine) summary.maintenance_faults += 1;
      console.log(lang, width, 'maintenance off and on', maintenanceFine ? 'ok' : 'FAULT', JSON.stringify({status, offered, back}));
      // Signed out for the next round (its form needs the page's token, so through the page's own button): the account's
      // round of sign-ins ends, on both sites.
      await page.goto(base + '/', {waitUntil: 'networkidle0'});
      await Promise.all([page.waitForNavigation({waitUntil: 'networkidle0'}),
                         page.evaluate(() => document.querySelector('form[action="/signout"]').requestSubmit())]);
    }
  }
  await browser.close();
  console.log(JSON.stringify(summary));
})().catch(e => { console.error(e); process.exit(1); });
