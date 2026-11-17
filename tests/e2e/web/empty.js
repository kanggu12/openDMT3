// The site on a server with nothing in it, as its owner first meets it (tests/e2e/web/run.sh runs this in headless
// Chrome that shares the empty server's network, so the server sees it as the server PC itself: the first-run page
// shows only there). Both sites: the players' (port 4730) and the admin site (its own port, 4731, its own sign-in). In
// English and Korean, at a desktop and two phone widths:
//
//   - the first-run page, the admin site's (the players' site sends the server PC there; its rules said before one is
//     broken), and a password too short refused in words;
//   - the owner's account made: the admin site's sign-in page says so once, with the ID typed already;
//   - a wrong password said in words;
//   - every page of the empty server (no song, no play, no installer, no cabinet), each measured as the full server's
//     are (measure.js: nothing past the right edge, no words cut off, every cell of a stacked row labelled, the phone
//     menu whole, every button's words in its middle);
//   - the Download page without an installer: the release's file and the address to type, never a file this server
//     lacks nor a launcher that knows this server;
//   - an account made: the message to send, and under it which address to send (the admin's browser reached the site
//     at 127.0.0.1, which no other PC reaches);
//   - a plain player: no admin pages in the menu, and the admin site's door, which takes their right password and says
//     the account has no admin rights.
//
// Screenshots go to /out as LANG-empty-NAME-WIDTH.png. The last line is the summary the runner reads:
// {"pages", "sticking", "cut", "unlabelled", "menu_cut", "askew", "states", "state_faults"}.
const puppeteer = require('puppeteer');
const {layout, layers, frame, record} = require('/w/measure.js');

const base = 'http://127.0.0.1:4730';
// The admin site, on the server PC's own address (where it listens unless its owner opens it).
const admin = 'http://127.0.0.1:4731';
// A desktop, a phone and the narrowest phone looked after.
const sizes = [[1280, 860], [390, 844], [360, 740]];
// Every page of the players' site a signed-in owner can open, and three that are not there (a page, a DJ, a song).
const pages = ['/', '/rankings', '/rankings?by=best30', '/rankings?by=month', '/songs', '/download', '/account',
               '/licenses', '/nothing-here', '/dj/999', '/songs/9999'];
// Every page of the admin site, and one that is not there.
const adminPages = ['/admin/players', '/admin/cabinets', '/admin/status', '/admin/server', '/admin/song_list', '/admin/log',
                    '/admin/log/plays', '/admin/log/requests', '/admin/backups', '/nothing-here'];

(async () => {
  const browser = await puppeteer.launch({args: ['--no-sandbox']});
  const page = await browser.newPage();
  const summary = {pages: 0, sticking: 0, cut: 0, unlabelled: 0, menu_cut: 0, askew: 0, spacing: 0, layer_faults: 0,
                   layers: 0, states: 0, state_faults: 0, form_faults: 0, frame_faults: 0, wrap_faults: 0};
  const go = path => page.goto(base + path, {waitUntil: 'networkidle0'});
  // The same on the admin site.
  const goAdmin = path => page.goto(admin + path, {waitUntil: 'networkidle0'});
  // A whole page's picture, at rest at its top (one taken scrolled draws the sticky bar halfway down).
  const shot = async (lang, name, width) => {
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
    await page.screenshot({path: `/out/${lang}-empty-${name}-${width}.png`, fullPage: true});
  };
  // A page looked at: measured, shot, and one of the run's lines. `kind`: the site it is on, whose frame it must have
  // ('players', or 'console' for the admin site's).
  const look = async (lang, width, name, shown, kind = 'players') => {
    // The layout's measure, then the page's floating layers opened one by one (measure.js: layers).
    const over = await layout(page);
    const opened = await layers(page);
    summary.layers += opened.opened;
    // The page's frame on screen (measure.js: frame).
    const framed = await frame(page, kind);
    record(summary, lang, width, 'empty ' + (kind === 'console' ? 'admin ' : '') + shown,
           Object.assign(over, {layers: opened.faults, frame: framed}));
    await shot(lang, (kind === 'console' ? 'admin-' : '') + name, width);
  };
  // A state that must hold, said as one of the run's lines.
  const state = (lang, width, what, fine, seen) => {
    summary.states += 1;
    if (!fine) summary.state_faults += 1;
    console.log(lang, width, what, fine ? 'ok' : 'FAULT', JSON.stringify(seen));
  };
  const text = selector => page.evaluate(s => { const e = document.querySelector(s); return e ? e.innerText.trim() : null; }, selector);
  const signIn = async (id, password, next, site = base) => {
    await page.goto(site + '/signin' + (next ? '?next=' + next : ''), {waitUntil: 'networkidle0'});
    await page.type('input[name=login_id]', id);
    await page.type('input[name=password]', password);
    await Promise.all([page.waitForNavigation({waitUntil: 'networkidle0'}), page.click('button.primary')]);
  };
  const signOut = async () => {
    await go('/');
    await Promise.all([page.waitForNavigation({waitUntil: 'networkidle0'}), page.evaluate(() => document.querySelector('form[action="/signout"]').requestSubmit())]);
  };

  // ---- the first run: no account yet, so the site opens on the page that makes the owner's
  for (const lang of ['en', 'ko']) {
    await go('/lang/' + lang);
    for (const [width, height] of sizes) {
      await page.setViewport({width, height});
      // The players' site's top: the server PC is sent on to the admin site's first run.
      await go('/');
      // Each field's rule under it (FORMS.md): the ID's and the password's hints.
      const hint = await page.evaluate(() => [...document.querySelectorAll('.field-hint')].map(e => e.textContent).join(' ') || null);
      await look(lang, width, 'first-run', '/owner', 'console');
      // The rules of an ID, a DJ name and a password stand under the form before one is broken.
      state(lang, width, 'first run', page.url() === admin + '/owner' && hint !== null && /8/.test(hint) && /16/.test(hint),
            {at: page.url(), hint});
    }
    // A password too short (the box's own limit taken off, as a script would send it): refused in words.
    await page.setViewport({width: 1280, height: 860});
    await goAdmin('/owner');
    await page.type('input[name=login_id]', 'boss');
    await page.type('input[name=password]', '123');
    // The field's own rules taken off (the browser's and the page's check), as a script would send it.
    await page.evaluate(() => { const f = document.querySelector('input[name=password]');
                                for (const a of ['minlength', 'pattern', 'data-invalid']) f.removeAttribute(a); });
    await Promise.all([page.waitForNavigation({waitUntil: 'networkidle0'}), page.click('button.primary')]);
    // Said under the password, the field it is about.
    const refused = await text('#owner-password-error');
    await look(lang, 1280, 'first-run-refused', '/owner (a password too short)', 'console');
    state(lang, 1280, 'first run refused', refused !== null && /6/.test(refused) && page.url() === admin + '/owner', {refused});
  }
  // ---- the owner's account made: the sign-in page that opens says so once, with the ID typed already
  await go('/lang/ko');
  await goAdmin('/owner');
  await page.type('input[name=login_id]', 'boss');
  await page.type('input[name=password]', 'pass1234');
  await Promise.all([page.waitForNavigation({waitUntil: 'networkidle0'}), page.click('button.primary')]);
  const made = {said: await text('.done-line'), typed: await page.$eval('input[name=login_id]', e => e.value), at: page.url()};
  await look('ko', 1280, 'owner-made', '/signin (the owner made)', 'console');
  await goAdmin('/signin');
  made.again = await text('.done-line');
  state('ko', 1280, 'owner made', made.at === admin + '/signin' && made.said !== null && made.said.includes('BOSS') &&
        made.typed === 'BOSS' && made.again === null, made);
  // ---- a wrong password
  for (const lang of ['en', 'ko']) {
    await go('/lang/' + lang);
    await signIn('BOSS', 'wrong-one');
    // One sentence for a wrong ID or password, under the password.
    const wrong = await text('#signin-password-error');
    await look(lang, 1280, 'signin-wrong', '/signin (a wrong password)');
    state(lang, 1280, 'wrong password', wrong !== null && wrong.length > 0 && page.url().includes('/signin'), {wrong});
  }
  // ---- signed in as the owner, on each site: every page of the empty server
  await signIn('BOSS', 'pass1234');
  await signIn('BOSS', 'pass1234', null, admin);
  for (const lang of ['en', 'ko']) {
    await go('/lang/' + lang);
    for (const [width, height] of sizes) {
      await page.setViewport({width, height});
      for (const path of pages) {
        await go(path);
        await page.evaluate(() => document.querySelectorAll('details').forEach(d => { d.open = true; }));
        await look(lang, width, path.replace(/[\/?=&]/g, '_') || '_', path);
      }
      for (const path of adminPages) {
        await goAdmin(path);
        await page.evaluate(() => document.querySelectorAll('details').forEach(d => { d.open = true; }));
        await look(lang, width, path.replace(/[\/?=&]/g, '_'), path, 'console');
      }
      // The Download page with no installer: where the launcher comes from, and the address to type by hand.
      await go('/download');
      // No steps (the guides keep them): where the launcher comes from and this server's address, no key to press.
      const download = await page.evaluate(() => ({alert: (document.querySelector('.alert') || {}).innerText || '',
        address: (document.querySelector('.file-facts code') || {}).innerText || '',
        steps: [...document.querySelectorAll('ol.steps li')].map(li => li.innerText), button: !!document.querySelector('a.btn.big')}));
      state(lang, width, 'download without an installer', !download.button && download.alert.length > 0 &&
            download.steps.length === 0 && /:4730$/.test(download.address), download);
      // The Status page before any reading: the song list said once in the list to look at, three "not yet" in the
      // table, and no line more.
      await goAdmin('/admin/status');
      const status = await page.evaluate(() => ({looks: document.querySelectorAll('p.alert.look:not(.data-missing)').length,
        missing: document.querySelectorAll('.data-missing').length,
        stats: [...document.querySelectorAll('.stats')].map(s => s.children.length)}));
      // Four figures in each of the two rows of four.
      state(lang, width, 'status of an empty server', status.missing === 0 && status.looks >= 2 &&
            status.stats.every(n => n === 4), status);
    }
  }
  // ---- an account made here: the message to send, and which address to send (this browser reached 127.0.0.1)
  for (const [lang, id] of [['en', 'RIO'], ['ko', 'HANA']]) {
    await go('/lang/' + lang);
    for (const [width, height] of sizes) {
      await page.setViewport({width, height});
      await goAdmin('/admin/players');
      await page.type('form:has(input[name=action][value=make]) input[name=login_id]', id + (width === 1280 ? '' : width === 390 ? '2' : '3'));
      await page.type('form:has(input[name=action][value=make]) input[name=password]', 'pass1234');
      await Promise.all([page.waitForNavigation({waitUntil: 'networkidle0'}),
                         page.click('form:has(input[name=action][value=make]) button.primary')]);
      const message = await page.evaluate(() => { const box = document.getElementById('message');
        const local = document.querySelector('.message-local');
        return {text: box ? box.value : null, local: local ? local.innerText : null,
                scrolls: box ? box.scrollHeight > box.clientHeight + 1 : null}; });
      await look(lang, width, 'player-made', '/admin/players (an account made)', 'console');
      state(lang, width, 'message with an address only this PC reaches', message.text !== null && !message.scrolls &&
            message.text.includes('http://127.0.0.1:4730/download') && message.local !== null &&
            message.local.includes('127.0.0.1'), message);
    }
  }
  // ---- a plain player: the pages a player sees, no admin pages in the menu, the admin site's door refusing them
  await signOut();
  for (const lang of ['en', 'ko']) {
    await go('/lang/' + lang);
    for (const [width, height] of sizes) {
      await page.setViewport({width, height});
      await signIn('RIO', 'pass1234', '/download');
      for (const path of ['/download', '/', '/account']) {
        await go(path);
        await look(lang, width, 'player' + (path.replace(/[\/?=&]/g, '_') || '_'), path + ' (a plain player)');
      }
      const menu = await page.evaluate(() => [...document.querySelectorAll('.menu a')].map(a => a.getAttribute('href')));
      // The admin pages' address on the players' port: the server PC goes on to the admin site, whose door takes the
      // player's right password and says the account has no admin rights (nobody is signed in there).
      await go('/admin/players');
      const sent = page.url();
      await page.type('input[name=login_id]', 'RIO');
      await page.type('input[name=password]', 'pass1234');
      const [refused] = await Promise.all([page.waitForNavigation({waitUntil: 'networkidle0'}), page.click('button.primary')]);
      const said = await text('.form-error');
      await look(lang, width, 'player_admin', '/signin (a plain player)', 'console');
      state(lang, width, 'a plain player', !menu.some(href => href.startsWith('/admin')) && menu.length === 4 &&
            sent.startsWith(admin + '/signin') && refused.status() === 403 && said !== null && said.length > 0,
            {menu, sent, status: refused.status(), said});
      await signOut();
    }
  }
  await browser.close();
  console.log(JSON.stringify(summary));
})().catch(e => { console.error('FAILED', e); process.exit(1); });
