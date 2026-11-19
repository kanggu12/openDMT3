// The pages again as the headless shell draws them (puppeteer's headless: 'shell'), for the gaps inside numbers alone
// (measure.js: gaps). The shell steps each glyph by a whole pixel unless the page says otherwise, and the pictures made
// of the site for its owner are drawn so; the new headless, as a desktop's Chrome does, steps by the face's own
// advances and shows no gap inside a number whatever the page says. Every page of both sites, signed in as the server's
// admin, in both languages, at the three widths and the browser's 150 %: each round a browser profile of its own (its
// language chosen, both doors signed in on). Each page is one of the run's lines; the summary gains shell_pages, and a
// page with a gap counts in gap_faults.
const {gaps} = require('/w/measure.js');

// [CSS width, CSS height, device pixels per CSS pixel, the size's name in the run's lines].
const SIZES = [[1280, 860, 1, '1280'], [390, 844, 1, '390'], [360, 740, 1, '360'], [1280, 640, 1.5, 'z150']];

module.exports = async (puppeteer, summary, {base, admin, pages, adminPages, label}) => {
  summary.shell_pages = summary.shell_pages || 0;
  const browser = await puppeteer.launch({headless: 'shell', args: ['--no-sandbox']});
  // A page measured: the pictures that load when they come into view loaded and the fonts in first, as for a picture.
  const look = async (page, lang, size, shown) => {
    await page.evaluate(() => Promise.all([...document.images].map(i => { i.loading = 'eager';
      return i.complete ? null : new Promise(done => { i.onload = i.onerror = done; }); })));
    await page.evaluate(() => document.fonts.ready);
    const found = await gaps(page);
    summary.shell_pages += 1;
    if (found.length) summary.gap_faults = (summary.gap_faults || 0) + 1;
    console.log(lang, size, label + 'shell ' + shown, found.length ? 'GAPS ' + JSON.stringify(found) : 'ok');
  };
  for (const lang of ['en', 'ko']) {
    for (const [width, height, scale, size] of SIZES) {
      const context = await browser.createBrowserContext();
      const page = await context.newPage();
      await page.setViewport({width, height, deviceScaleFactor: scale});
      await page.goto(base + '/lang/' + lang, {waitUntil: 'networkidle0'});
      for (const [site, list, side] of [[base, pages, ''], [admin, adminPages, 'admin ']]) {
        // The site's door, then signed in on it for the rest of its pages.
        await page.goto(site + '/signin', {waitUntil: 'networkidle0'});
        await look(page, lang, size, side + '/signin');
        await page.type('input[name=login_id]', 'BOSS');
        await page.type('input[name=password]', 'pass1234');
        await Promise.all([page.waitForNavigation({waitUntil: 'networkidle0'}), page.click('button.primary')]);
        for (const path of list) {
          await page.goto(site + path, {waitUntil: 'networkidle0'});
          await look(page, lang, size, side + path);
        }
      }
      await context.close();
    }
  }
  await browser.close();
};
