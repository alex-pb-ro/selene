// Render the actual dashboard assets with synthetic HTTP responses; all requests are intercepted.
const { chromium } = require('playwright');
const fs = require('fs/promises');
const path = require('path');
const { createHash } = require('crypto');

(async () => {
  const root = path.resolve(__dirname, '../..');
  const assets = path.join(root, 'src/selene/resources/dashboard');
  const browser = await chromium.launch({headless: true, executablePath:process.env.SELENE_BROWSER_EXECUTABLE, args: [
    '--disable-background-networking', '--disable-component-update', '--no-default-browser-check',
    '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost'
  ]});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 1000}, colorScheme: 'light'});
    let status = 'stale';
    let saved = null;
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin !== 'http://127.0.0.1:8765') return route.abort();
      if (url.pathname.startsWith('/dashboard/')) {
        const relative = url.pathname.slice('/dashboard/'.length) || 'index.html';
        const filename = path.resolve(assets, relative);
        if (!filename.startsWith(assets + path.sep)) return route.abort();
        const contentType = ({'.html':'text/html', '.css':'text/css', '.js':'text/javascript', '.svg':'image/svg+xml', '.png':'image/png'})[path.extname(filename)] || 'application/octet-stream';
        try { return route.fulfill({contentType, body: await fs.readFile(filename)}); }
        catch { return route.fulfill({status:404,body:''}); }
      }
      let body = {};
      if (url.pathname === '/get_config_overview') body = {
        active_project: {name:'Synthetic project', path:'/synthetic/project'}, context:{name:'desktop-app', description:'Local verification'},
        modes:[], active_tools:[], tool_stats_summary:{}, registered_projects:[], available_tools:[], available_modes:[],
        available_contexts:[], available_memories:['architecture/cache'], jetbrains_mode:false, languages:['python'],
        encoding:'utf-8', current_client:'Synthetic verifier', selene_version:'dev'
      };
      if (url.pathname === '/get_tool_names') body = {tool_names:[]};
      if (url.pathname === '/get_log_messages') body = {messages:[],max_idx:-1,active_project:'Synthetic project'};
      if (url.pathname === '/queued_task_executions') body = {status:'success',queued_executions:[]};
      if (url.pathname === '/last_execution') body = {status:'success',last_execution:null};
      if (url.pathname === '/get_memory') body = {
        memory_name:'architecture/cache', memory_sha256:'a'.repeat(64), evidence_status:status,
        content_withheld:status === 'scope_mismatch',
        content:status === 'scope_mismatch' ? '' : 'Keep cache expiry explicit. Review the decision when its supporting configuration changes.'
      };
      if (url.pathname === '/save_memory') {
        saved = route.request().postDataJSON();
        body = {status:'success'};
      }
      return route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
    });
    await page.goto('http://127.0.0.1:8765/dashboard/');
    await page.locator('#memories-header').click();
    await page.locator('.memory-item[data-memory="architecture/cache"]').click();
    await page.getByText('Supporting source has changed. Review this memory.').waitFor();
    await page.waitForFunction(() => !window.jQuery('#edit-memory-modal').is(':animated'));
    await page.locator('#edit-memory-modal').screenshot({path:path.join(root,'research/memory-dashboard-stale.png'), animations:'disabled'});
    await page.locator('#edit-memory-content').fill('A revised local decision.');
    await page.locator('#edit-memory-save-btn').click();
    await page.locator('#edit-memory-modal').waitFor({state:'hidden'});
    if (!saved || saved.expected_memory_sha256 !== 'a'.repeat(64) || saved.content !== 'A revised local decision.') throw Error('The dashboard did not submit its observed memory version and editable body');
    status = 'scope_mismatch';
    await page.locator('#theme-toggle').click();
    await page.locator('.memory-item[data-memory="architecture/cache"]').click();
    await page.getByText('This record belongs to another project. Its content is withheld.').waitFor();
    await page.waitForFunction(() => !window.jQuery('#edit-memory-modal').is(':animated'));
    if (!await page.locator('#edit-memory-save-btn').isDisabled()) throw Error('Foreign record save remained enabled');
    if (await page.locator('#edit-memory-content').inputValue() !== '') throw Error('Foreign record body was displayed');
    await page.locator('#edit-memory-modal').screenshot({path:path.join(root,'research/memory-dashboard-scope.png'), animations:'disabled'});
    if (errors.length) throw Error(JSON.stringify(errors));
    const source_sha256 = {};
    for (const relative of ['src/selene/resources/dashboard/index.html', 'src/selene/resources/dashboard/dashboard.js', 'src/selene/resources/dashboard/dashboard.css',
      'research/probes/memory_dashboard.cjs']) {
      source_sha256[relative] = createHash('sha256').update(await fs.readFile(path.join(root,relative))).digest('hex');
    }
    console.log(JSON.stringify({synthetic_only:true,external_requests_allowed:false,stale_notice_visible:true,
      source_version_submitted_with_edit:true,foreign_body_withheld_and_save_disabled:true,page_errors:errors,source_sha256},null,2));
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
