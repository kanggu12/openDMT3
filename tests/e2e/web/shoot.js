// The site's layout check, run by tests/e2e/web/run.sh in headless Chrome: every page in English and Korean, at a desktop
// width and a phone width, signed in as the admin. Per page it prints what the layout's measure finds (measure.js: what
// sticks out past the right edge, words cut off inside a box that hides its overflow, a cell of a stacked row with no
// label at the phone width, a word of the phone menu that does not fit, a button's words out of its middle), saves a
// full-page screenshot, then opens the
// questions asked before something goes (a player deleted, a player's plays reset, a new password, every play reset,
// a backup deleted, a token revoked) and checks each fits the screen, makes an
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
const {layout, record: recorded} = require('/w/measure.js');

const base = process.env.SITE || 'http://site:4730';
// The upload field's words in both languages, from the site's own table (run.sh reads strings.py): {key: [en, ko]}.
const words = JSON.parse(process.env.WORDS || '{}');
const pages = ['/', '/rankings', '/rankings?by=best30', '/rankings?by=month', '/songs', '/songs/4', '/dj/4', '/download',
               '/account', '/admin/players', '/admin/cabinets', '/admin/status', '/admin/song_list', '/admin/log',
               '/admin/log/plays', '/admin/backups', '/licenses'];
// The questions asked first: what each is, where, and the button of the form that asks it.
const asking = action => `form[data-ask]:has(input[name=action][value=${action}]) button.danger`;
const questions = [['player delete', '/admin/players', asking('delete')],
                   ['player reset', '/admin/players', asking('reset_plays')],
                   // A new password ends the account's sign-ins: asked first too (its button is a plain one).
                   ['player new password', '/admin/players', 'form[data-ask]:has(input[name=action][value=password]) button'],
                   ['every play reset', '/admin/players', asking('reset_all')],
                   ['backup delete', '/admin/backups', asking('delete')],
                   ['token revoke', '/account', asking('token_revoke')]];

(async () => {
  const browser = await puppeteer.launch({args: ['--no-sandbox']});
  const page = await browser.newPage();
  const summary = {pages: 0, sticking: 0, cut: 0, unlabelled: 0, menu_cut: 0, askew: 0, dialogs: 0, dialog_faults: 0,
                   filters: 0, filter_faults: 0, messages: 0,
                   message_faults: 0, looks: 0, look_faults: 0, tokens: 0, token_faults: 0, uploads: 0,
                   upload_faults: 0, song_lists: 0, song_list_faults: 0, drops: 0, drop_faults: 0, maintenances: 0,
                   maintenance_faults: 0};
  // What the layout's measure finds on the page showing (measure.js), and its line and place in the summary.
  const measure = () => layout(page);
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
              text: box.innerText, sends: !box.closest('form').querySelector('button.primary').disabled,
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
    for (const [width, height] of [[1280, 860], [390, 844]]) {
      round += 1;
      await page.setViewport({width, height});
      await page.goto(base + '/lang/' + lang, {waitUntil: 'networkidle0'});
      // The sign-in page first, then signed in for the rest.
      await page.goto(base + '/signin', {waitUntil: 'networkidle0'});
      record(lang, width, '/signin', await measure());
      await page.screenshot({path: `/out/${lang}-signin-${width}.png`, fullPage: true});
      await page.type('input[name=login_id]', 'BOSS');
      await page.type('input[name=password]', 'pass1234');
      await Promise.all([page.waitForNavigation({waitUntil: 'networkidle0'}), page.click('button.primary')]);
      for (const path of pages) {
        await page.goto(base + path, {waitUntil: 'networkidle0'});
        // Everything folded is opened first (the DJ card's choices, the tables behind charts, the licences), so it
        // is measured too; the pictures that load when they come into view are loaded before the measure.
        await page.evaluate(() => document.querySelectorAll('details').forEach(d => { d.open = true; }));
        await page.evaluate(() => Promise.all([...document.images].map(i => { i.loading = 'eager';
          return i.complete ? null : new Promise(done => { i.onload = i.onerror = done; }); })));
        record(lang, width, path, await measure());
        await page.screenshot({path: `/out/${lang}-${path.replace(/[\/?=&]/g, '_') || '_'}-${width}.png`, fullPage: true});
      }
      // Each question: open, inside the screen, its question filled in; Esc closes it and nothing goes.
      for (const [what, path, button] of questions) {
        await page.goto(base + path, {waitUntil: 'networkidle0'});
        const before = await page.evaluate(() => document.querySelectorAll('form[data-ask]').length);
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
      await page.goto(base + '/admin/players', {waitUntil: 'networkidle0'});
      await page.type('form:has(input[name=action][value=make]) input[name=login_id]', 'MSG' + round);
      await Promise.all([page.waitForNavigation({waitUntil: 'networkidle0'}),
                         page.click('form:has(input[name=action][value=make]) button.primary')]);
      const message = await page.evaluate(() => {
        const box = document.getElementById('message');
        return box ? {lines: box.value.split('\n').length, rows: box.rows, scrolls: box.scrollHeight > box.clientHeight + 1,
                      // The address the server was given for its players (run.sh), never the one this browser used;
                      // one other PCs reach, so the page has nothing to add about it.
                      chosen: box.value.includes('http://192.168.0.5:4730/\n') && box.value.includes('http://192.168.0.5:4730/download') &&
                              !box.value.includes('site:4730'),
                      local: !!document.querySelector('.message-local')} : null;
      });
      record(lang, width, '/admin/players (message)', await measure());
      await page.screenshot({path: `/out/${lang}-_admin_players-message-${width}.png`, fullPage: true});
      summary.messages += 1;
      const messageFine = message !== null && message.lines === message.rows && !message.scrolls && message.chosen &&
        !message.local;
      if (!messageFine) summary.message_faults += 1;
      console.log(lang, width, 'message to send', messageFine ? 'ok' : 'FAULT', JSON.stringify(message));
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
      await page.goto(base + '/admin/status', {waitUntil: 'networkidle0'});
      const looks = await page.evaluate(() => document.querySelectorAll('p.alert.look').length);
      record(lang, width, '/admin/status (to look at)', await measure());
      await page.screenshot({path: `/out/${lang}-_admin_status-look-${width}.png`, fullPage: true});
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
      await page.screenshot({path: `/out/${lang}-_songs-typed-${width}.png`, fullPage: true});
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
                         page.click('form:has(input[name=action][value=token_make]) button.primary')]);
      const token = await page.evaluate(() => {
        const box = document.getElementById('made-token');
        return box ? {shape: /^odt3_[0-9a-f]{12}_[A-Za-z0-9_-]{43}$/.test(box.value),
                      scrolls: box.scrollHeight > box.clientHeight + 1,
                      inside: box.getBoundingClientRect().right <= document.documentElement.clientWidth} : null;
      });
      record(lang, width, '/account (token made)', await measure());
      await page.screenshot({path: `/out/${lang}-_account-token-${width}.png`, fullPage: true});
      summary.tokens += 1;
      const tokenFine = token !== null && token.shape && !token.scrolls && token.inside;
      if (!tokenFine) summary.token_faults += 1;
      console.log(lang, width, 'token shown once', tokenFine ? 'ok' : 'FAULT', JSON.stringify(token));
      // The Backups tab's upload: its field as a person meets it, then a file past the page's limit (made small here) is
      // told on the page and never sent; then a real backup (one of the list's, downloaded) is uploaded, checked and
      // listed, the page measured.
      await page.goto(base + '/admin/backups', {waitUntil: 'networkidle0'});
      fs.writeFileSync('/tmp/notes.txt', 'Not a database, and longer than the limit set here.');
      await drop(lang, width, 'backup', '/tmp/notes.txt', 'notes.txt');
      await page.goto(base + '/admin/backups', {waitUntil: 'networkidle0'});
      await (await page.$('form.upload input[type=file]')).uploadFile('/tmp/notes.txt');
      await page.evaluate(() => { document.querySelector('form[data-upload-most]').dataset.uploadMost = '4'; });
      let posted = 0;
      const posting = r => { if (r.method() === 'POST') posted += 1; };
      page.on('request', posting);
      await page.click('form.upload button.primary');
      await new Promise(r => setTimeout(r, 400));
      page.off('request', posting);
      const told = await page.evaluate(() => {
        const said = document.querySelector('.upload-too-large'), box = document.querySelector('.drop');
        return {shown: !said.hidden && said.offsetHeight > 0, where: location.pathname,
                box: box.classList.contains('too-big') && getComputedStyle(box).borderTopColor === 'rgb(255, 79, 160)',
                sends: !box.closest('form').querySelector('button.primary').disabled};
      });
      const name = await page.evaluate(() => document.querySelector('a.btn[download]').getAttribute('href').split('/').pop());
      const bytes = await page.evaluate(async name => {
        const data = new Uint8Array(await (await fetch('/admin/backups/' + name)).arrayBuffer());
        let text = '';
        for (const b of data) { text += String.fromCharCode(b); }
        return btoa(text);
      }, name);
      fs.writeFileSync('/tmp/backup.sqlite', Buffer.from(bytes, 'base64'));
      await page.goto(base + '/admin/backups', {waitUntil: 'networkidle0'});
      await (await page.$('form.upload input[type=file]')).uploadFile('/tmp/backup.sqlite');
      await Promise.all([page.waitForNavigation({waitUntil: 'networkidle0'}), page.click('form.upload button.primary')]);
      const uploaded = await page.evaluate(() => ({ok: (document.querySelector('p.alert.ok') || {}).textContent || '',
                                                   rows: document.querySelectorAll('table.table tbody tr').length}));
      record(lang, width, '/admin/backups (uploaded)', await measure());
      await page.screenshot({path: `/out/${lang}-_admin_backups-uploaded-${width}.png`, fullPage: true});
      summary.uploads += 1;
      const uploadFine = posted === 0 && told.shown && told.box && !told.sends && told.where === '/admin/backups' &&
        uploaded.ok.includes('upload.sqlite');
      if (!uploadFine) summary.upload_faults += 1;
      console.log(lang, width, 'upload', uploadFine ? 'ok' : 'FAULT', JSON.stringify({posted, told, uploaded}));
      // The Song list tab's upload, as the Backups tab's: its field, then a file past the page's limit (made small here)
      // is told on the page and never sent; then the song list the seed saved is uploaded, taken in and said, the page
      // measured.
      await page.goto(base + '/admin/song_list', {waitUntil: 'networkidle0'});
      await drop(lang, width, 'song-list', '/out/openDMT3-song-list.zip', 'openDMT3-song-list.zip');
      await page.goto(base + '/admin/song_list', {waitUntil: 'networkidle0'});
      await (await page.$('form.upload input[type=file]')).uploadFile('/tmp/notes.txt');
      await page.evaluate(() => { document.querySelector('form[data-upload-most]').dataset.uploadMost = '4'; });
      let listPosted = 0;
      const listPosting = r => { if (r.method() === 'POST') listPosted += 1; };
      page.on('request', listPosting);
      await page.click('form.upload button.primary');
      await new Promise(r => setTimeout(r, 400));
      page.off('request', listPosting);
      const listTold = await page.evaluate(() => {
        const said = document.querySelector('.upload-too-large'), box = document.querySelector('.drop');
        return {shown: !said.hidden && said.offsetHeight > 0, where: location.pathname,
                box: box.classList.contains('too-big') && getComputedStyle(box).borderTopColor === 'rgb(255, 79, 160)',
                sends: !box.closest('form').querySelector('button.primary').disabled};
      });
      await (await page.$('.card:has(form.upload)')).screenshot({path: `/out/${lang}-upload-song-list-too-big-${width}.png`});
      await page.goto(base + '/admin/song_list', {waitUntil: 'networkidle0'});
      await (await page.$('form.upload input[type=file]')).uploadFile('/out/openDMT3-song-list.zip');
      await Promise.all([page.waitForNavigation({waitUntil: 'networkidle0'}), page.click('form.upload button.primary')]);
      const taken = await page.evaluate(() => ({ok: (document.querySelector('p.alert.ok') || {}).textContent || '',
                                                 bad: (document.querySelector('p.alert.bad:not([hidden])') || {}).textContent || ''}));
      record(lang, width, '/admin/song_list (uploaded)', await measure());
      await page.screenshot({path: `/out/${lang}-_admin_song_list-uploaded-${width}.png`, fullPage: true});
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
      await page.goto(base + '/admin/status', {waitUntil: 'networkidle0'});
      const offered = await page.evaluate(() => ({start: !!document.querySelector('input[name=action][value=maintenance_on]'),
                                                  line: !!document.querySelector('.site-notice.maintenance')}));
      record(lang, width, '/admin/status (maintenance off)', await measure());
      await page.screenshot({path: `/out/${lang}-_admin_status-maintenance-off-${width}.png`, fullPage: true});
      const back = await page.evaluate(async token => (await fetch('/api/v1/maintenance', {method: 'POST',
        headers: {Authorization: 'Bearer ' + token}}).then(r => r.json())).on, others.token);
      summary.maintenances += 1;
      const maintenanceFine = status.off && offered.start && !offered.line && back === true;
      if (!maintenanceFine) summary.maintenance_faults += 1;
      console.log(lang, width, 'maintenance off and on', maintenanceFine ? 'ok' : 'FAULT', JSON.stringify({status, offered, back}));
      // Signed out for the next round (its form needs the page's token, so through the page's own button).
      await page.goto(base + '/', {waitUntil: 'networkidle0'});
      await Promise.all([page.waitForNavigation({waitUntil: 'networkidle0'}),
                         page.click('form[action="/signout"] button')]);
    }
  }
  await browser.close();
  console.log(JSON.stringify(summary));
})().catch(e => { console.error(e); process.exit(1); });
