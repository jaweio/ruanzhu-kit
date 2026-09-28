'use strict';

// Product browser adapter. Selectors verified against the visible official
// page on 2026-09-24. No private classify endpoint or CAPTCHA solving is used.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {spawn} = require('node:child_process');
const WEB_URL = 'https://matrix.tencent.com/ai-detect/';
const PLACEHOLDER = /^(?:请输入需要检测的文本，ctrl\+enter提交检测|Please enter the text,press ctrl\+enter to submit detection)$/;
const CLEAR_BUTTON = /^(?:清空|Clear)$/i;
const SUBMIT_BUTTON = /^(?:立即检测|Detect now)/i;
const LABEL_CLASSES = {'txt-segmentType-success': 0, 'txt-segmentType-danger': 1, 'txt-segmentType-warning': 2};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const normalize = value => String(value).replace(/\s/g, '');
const SUBMISSION_ATTRIBUTE = 'data-ruanzhu-zhuque-submission';

class DetectionError extends Error {
  constructor(reason, message) { super(message); this.reason = reason; }
}

function parseSegments(segments, submittedText) {
  if (!Array.isArray(segments) || !segments.length) return null;
  if (normalize(segments.map(segment => segment.text).join('')) !== normalize(submittedText)) return null;
  // Missing/unknown tags are not human text and must never be counted as zero risk.
  const totals = [0, 0, 0];
  const labels = [];
  let cursor = 0;
  const source = Array.from(submittedText);
  for (const segment of segments) {
    const classes = String(segment.className || '').split(/\s+/);
    const matches = classes.filter(value => Object.hasOwn(LABEL_CLASSES, value));
    if (matches.length !== 1) throw new DetectionError('unsupported', '网页结果标签发生变化，无法可靠读取分类。');
    const label = LABEL_CLASSES[matches[0]];
    const wanted = Array.from(segment.text).filter(char => !/\s/.test(char));
    if (!wanted.length) continue;
    while (cursor < source.length && /\s/.test(source[cursor])) cursor++;
    const start = cursor;
    for (const char of wanted) {
      while (cursor < source.length && /\s/.test(source[cursor])) cursor++;
      if (source[cursor++] !== char) throw new DetectionError('unsupported', '网页返回文字与提交内容不一致。');
    }
    totals[label] += wanted.length;
    // Zhuque positions are [start, length], measured in Unicode code points.
    labels.push({label, order: labels.length + 1, position: [start, cursor - start]});
  }
  const total = totals.reduce((a, b) => a + b, 0);
  if (!total) return null;
  return {status: 'success', labels_ratio: {'0': totals[0] / total, '1': totals[1] / total, '2': totals[2] / total},
    segment_labels: labels, channel: 'web', ratio_source: 'visible-segment-nonwhitespace-character-weighted'};
}

function classifyBlocker({captchaVisible = false, buttonText = '', alerts = '', loginDialog = false, checkQuotaButton = true}) {
  if (captchaVisible) return new DetectionError('captcha', '朱雀网页要求人机验证；请在已打开窗口完成后重试，窗口和已检测缓存均保留。');
  const quotaText = (checkQuotaButton ? buttonText : '') + '\n' + alerts;
  if (/(?:剩余\s*0\s*次|次数(?:已)?(?:用尽|耗尽|不足)|达到.*(?:次数|额度).*上限|今日.*(?:次数|额度).*上限|\b0\s+left\b|(?:quota|limit|attempts?|detections?).*(?:exhausted|exceeded|used up|reached)|no (?:remaining |more )?(?:attempts?|detections?))/i.test(quotaText)) {
    return new DetectionError('quota', '朱雀网页检测次数不足；请登录已有账号、切换已配置API或等待额度恢复。不会重开无痕窗口重置次数。');
  }
  if (loginDialog || /(?:请先登录|登录后(?:才|再|可)检测|please (?:log in|login|sign in)|login required)/i.test(alerts)) return new DetectionError('login', '朱雀网页需要登录；请在已打开窗口登录后重试。');
  if (/检测文本长度|文本(?:过长|太长)|字数.*(?:限制|超过|不足)|text (?:length|is too (?:short|long))|(?:at least|more than|exceed).*(?:characters|words)/i.test(alerts)) return new DetectionError('unsupported', '网页拒绝当前文本长度，请根据页面提示调整检测分段。');
  if (/(?:网络异常|服务异常|服务不可用|检测失败|请求失败|network error|service unavailable|detection failed|request failed)/i.test(alerts)) return new DetectionError('unavailable', '朱雀网页暂时无法完成检测，请保留缓存后重试。');
  return null;
}

function loadPlaywright() {
  for (const location of [process.env.RUANZHU_PLAYWRIGHT_PATH, 'playwright', path.join(__dirname, '../app/node_modules/playwright')].filter(Boolean)) {
    try { return require(location); } catch (_) { /* Continue to installed alternatives only. */ }
  }
  throw new DetectionError('unavailable', '找不到 Playwright；请先安装 ruanzhu-kit/app 的依赖，不会自动下载浏览器。');
}

function chromeExecutable() {
  const candidates = [process.env.RUANZHU_CHROME_PATH];
  if (process.platform === 'darwin') candidates.push('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome');
  if (process.platform === 'win32') {
    for (const base of [process.env.PROGRAMFILES, process.env['PROGRAMFILES(X86)'], process.env.LOCALAPPDATA].filter(Boolean)) candidates.push(path.join(base, 'Google/Chrome/Application/chrome.exe'));
  }
  if (process.platform === 'linux') candidates.push('/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser');
  const found = candidates.find(candidate => candidate && fs.existsSync(candidate));
  if (!found) throw new DetectionError('unavailable', '未找到 Chrome；请安装 Chrome 或设置 RUANZHU_CHROME_PATH。');
  return found;
}

async function connectChrome(chromium, profileDir, deadline) {
  fs.mkdirSync(profileDir, {recursive: true, mode: 0o700});
  const activePort = path.join(profileDir, 'DevToolsActivePort');
  async function connectExisting() {
    try {
      const port = fs.readFileSync(activePort, 'utf8').split(/\r?\n/)[0];
      if (!/^\d{1,5}$/.test(port)) return null;
      return await chromium.connectOverCDP(`http://127.0.0.1:${port}`, {timeout: 1500});
    } catch (_) { return null; }
  }
  const connected = await connectExisting();
  if (connected) return connected;
  // Fixed dedicated profile, never incognito. Chrome survives driver exit to
  // preserve CAPTCHA/login state; it is not the user's personal profile.
  const chrome = spawn(chromeExecutable(), [`--user-data-dir=${profileDir}`, '--remote-debugging-port=0',
    '--remote-debugging-address=127.0.0.1', '--no-first-run', '--no-default-browser-check', WEB_URL],
  {detached: true, stdio: 'ignore'});
  let spawnFailed = false;
  chrome.on('error', () => { spawnFailed = true; });
  chrome.unref();
  const launchDeadline = Math.min(deadline, Date.now() + 15000);
  while (Date.now() < launchDeadline) {
    if (spawnFailed) break;
    const browser = await connectExisting();
    if (browser) return browser;
    await sleep(250);
    if (Date.now() > deadline - 1000) break;
  }
  throw new DetectionError('unavailable', '无法连接专用 Chrome 窗口，请检查现有窗口是否仍在启动。');
}

function snapshotDOM() {
    const visible = (element, inViewport = false) => {
      if (!element || !element.getClientRects().length) return false;
      for (let node = element; node; node = node.parentElement) {
        const style = getComputedStyle(node);
        if (style.display === 'none' || ['hidden', 'collapse'].includes(style.visibility) || Number(style.opacity) <= 0.01) return false;
      }
      const rect = element.getBoundingClientRect();
      if (rect.width <= 1 || rect.height <= 1) return false;
      return !inViewport || (rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight && rect.left < innerWidth);
    };
    const alerts = Array.from(document.querySelectorAll('[role="alert"]')).filter(element => visible(element)).map(element => element.innerText).join('\n');
    const dialogs = Array.from(document.querySelectorAll('[role="dialog"]')).filter(element => visible(element)).map(element => element.innerText).join('\n');
    return {
      submissionMarker: document.documentElement.getAttribute('data-ruanzhu-zhuque-submission') || '',
      buttonText: Array.from(document.querySelectorAll('button')).filter(element => visible(element)).map(element => element.innerText).find(value => /^(?:立即检测|Detect now)/i.test(value.trim())) || '',
      alerts, loginDialog: /登录|扫码|log\s?in|sign in/i.test(dialogs),
      captchaVisible: visible(document.querySelector('#tcaptcha_iframe_dy'), true),
      segments: Array.from(document.querySelectorAll('.txt-segment-box > span')).filter(element => visible(element)).map(element => ({text: element.innerText, className: element.className})),
    };
}

async function snapshot(page) {
  return page.evaluate(snapshotDOM);
}

function pendingReceipt(input) {
  const textHash = crypto.createHash('sha256').update(input.text).digest('hex');
  const identity = {request_id: String(input.request_id), text_sha256: textHash,
    profile_dir: path.resolve(input.profile_dir), url: WEB_URL};
  const name = crypto.createHash('sha256').update(JSON.stringify(identity)).digest('hex');
  const file = path.join(path.resolve(input.material_dir), '朱雀复核', '网页证据', `pending-${name}.json`);
  let value = null;
  try { value = JSON.parse(fs.readFileSync(file, 'utf8')); } catch (_) { /* A missing receipt cannot authorize reuse. */ }
  if (value && !Object.entries(identity).every(([key, expected]) => value[key] === expected)) value = null;
  return {file, identity, value};
}

function saveReceipt(file, value) {
  fs.mkdirSync(path.dirname(file), {recursive: true, mode: 0o700});
  const temporary = `${file}.${crypto.randomUUID()}.tmp`;
  fs.writeFileSync(temporary, JSON.stringify(value, null, 2), {encoding: 'utf8', mode: 0o600});
  fs.renameSync(temporary, file);
}

function consumeReceipt(receipt) {
  try { fs.unlinkSync(receipt.file); } catch (error) { if (error.code !== 'ENOENT') throw error; }
}

async function evidence(page, input, state) {
  const directory = path.join(path.resolve(input.material_dir), '朱雀复核', '网页证据');
  fs.mkdirSync(directory, {recursive: true, mode: 0o700});
  const request = String(input.request_id).replace(/[^A-Za-z0-9_.-]/g, '_').slice(0, 80).replace(/^\.+/, '') || 'request';
  const prefix = path.join(directory, `${request}-${Date.now()}`);
  const record = {url: page ? page.url() : WEB_URL, captured_at: new Date().toISOString(),
    text_sha256: crypto.createHash('sha256').update(input.text).digest('hex'),
    request_id: request, visible_state: state || null};
  fs.writeFileSync(`${prefix}.json`, JSON.stringify(record, null, 2), {encoding: 'utf8', mode: 0o600});
  const output = {page_record: `${prefix}.json`, url: record.url, text_sha256: record.text_sha256,
    ratio_source: 'visible-segment-nonwhitespace-character-weighted'};
  if (page) {
    try { await page.screenshot({path: `${prefix}.png`, fullPage: false, timeout: 5000}); output.screenshot = `${prefix}.png`; } catch (_) { /* Record remains useful if screenshot fails. */ }
  }
  return output;
}

async function detectOnPage(page, input, deadline) {
  await page.getByRole('button', {name: CLEAR_BUTTON}).waitFor({state: 'visible'});
  let state = await snapshot(page);
  const receipt = pendingReceipt(input);
  let delivery = 'new', beforeAlerts = '', blocker;
  if (receipt.value && !input.force) {
    const pending = receipt.value;
    if (!Number.isFinite(Date.parse(pending.submitted_at)) || !/^[a-f0-9-]{36}$/.test(pending.page_marker || '')) {
      throw new DetectionError('unavailable', '待处理检测凭据不完整，无法安全恢复；请核对后选择强制复测。');
    }
    if (pending.phase !== 'submitted') throw new DetectionError('unavailable', '上次网页提交是否成功尚不确定，已暂停以免重复扣次；请核对网页后再选择强制复测。');
    if (page.url() !== pending.url || state.submissionMarker !== pending.page_marker) {
      throw new DetectionError('unavailable', '待处理检测的页面已改变，无法安全恢复；请核对后选择强制复测。');
    }
    // Both the local receipt and a random marker in this same document must
    // match. Reloaded pages, built-in examples and other tabs cannot be reused.
    delivery = 'resumed';
    beforeAlerts = pending.before_alerts || '';
  } else {
    blocker = classifyBlocker(state);
    if (blocker && ['captcha', 'quota', 'login'].includes(blocker.reason)) throw blocker;
    await page.getByRole('button', {name: CLEAR_BUTTON}).click();
    const textbox = page.getByPlaceholder(PLACEHOLDER, {exact: true});
    await textbox.fill(input.text);
    if (await textbox.inputValue() !== input.text) throw new DetectionError('unsupported', '网页输入内容不完整，已停止检测。');
    const before = await snapshot(page);
    if (before.segments.length) throw new DetectionError('unsupported', '网页旧检测结果未清除，已停止以免误认本次结果。');
    beforeAlerts = before.alerts;
    const pageMarker = crypto.randomUUID();
    // This is our own DOM receipt marker, not website application state.
    await page.evaluate(({attribute, value}) => document.documentElement.setAttribute(attribute, value),
      {attribute: SUBMISSION_ATTRIBUTE, value: pageMarker});
    const pending = {...receipt.identity, url: page.url(), page_marker: pageMarker,
      phase: 'click_pending', submitted_at: new Date().toISOString(), before_alerts: beforeAlerts};
    saveReceipt(receipt.file, pending);
    try {
      await page.getByRole('button', {name: SUBMIT_BUTTON}).click();
      saveReceipt(receipt.file, {...pending, phase: 'submitted'});
    } catch (error) {
      saveReceipt(receipt.file, {...pending, phase: 'uncertain'});
      throw new DetectionError('unavailable', '网页提交状态不确定，已保留凭据并暂停；不会自动再次点击扣次。');
    }
    state = await snapshot(page);
  }
  while (Date.now() < deadline) {
    const result = parseSegments(state.segments, input.text);
    if (result) {
      consumeReceipt(receipt);
      return {result: {...result, delivery}, state};
    }
    // The last valid submission may immediately decrement the button to zero.
    // Only explicit quota errors are blockers after a confirmed submission.
    blocker = classifyBlocker({...state, checkQuotaButton: false,
      alerts: state.alerts === beforeAlerts ? '' : state.alerts});
    if (blocker) {
      // An explicit rejection did not leave a request running. A later normal
      // retry should be allowed once quota or text length has been corrected.
      if (['quota', 'unsupported'].includes(blocker.reason)) consumeReceipt(receipt);
      throw blocker;
    }
    await sleep(500);
    state = await snapshot(page);
  }
  throw new DetectionError('unavailable', '网页检测等待超时；窗口保留，可处理页面提示后继续增量复核。');
}

async function detect(input) {
  if (typeof input.text !== 'string' || Array.from(input.text.trim()).length < 351) throw new DetectionError('unsupported', '朱雀网页要求超过350字，请合并相邻原文。');
  if (!input.material_dir || !input.profile_dir) throw new DetectionError('unsupported', '缺少材料目录或专用浏览器目录。');
  const deadline = Date.now() + Math.max(10000, Math.min(Number(input.timeout_ms) || 120000, 600000));
  let page, state;
  try {
    const {chromium} = loadPlaywright();
    const browser = await connectChrome(chromium, path.resolve(input.profile_dir), deadline);
    const context = browser.contexts()[0];
    page = context.pages().find(candidate => candidate.url().startsWith(WEB_URL));
    if (!page) { page = await context.newPage(); await page.goto(WEB_URL, {waitUntil: 'domcontentloaded', timeout: Math.min(30000, deadline - Date.now())}); }
    await page.bringToFront();
    page.setDefaultTimeout(10000);
    const completed = await detectOnPage(page, input, deadline);
    state = completed.state;
    return {...completed.result, evidence: await evidence(page, input, state)};
  } catch (error) {
    if (page) {
      try { state = await snapshot(page); } catch (_) { /* Preserve the existing evidence when the page closes. */ }
    }
    return {status: 'error', reason: error.reason || 'unavailable',
      message: error.reason ? error.message : '网页检测未完成，请查看保留的浏览器窗口；未生成通过结果。',
      evidence: await evidence(page, input, state)};
  }
}

module.exports = {parseSegments, classifyBlocker, detectOnPage, snapshotDOM, DetectionError};
if (require.main === module) {
  let raw = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', chunk => { raw += chunk; });
  process.stdin.on('end', async () => {
    try {
      const result = await detect(JSON.parse(raw));
      process.stdout.write(JSON.stringify(result) + '\n', () => process.exit(result.status === 'success' ? 0 : 2));
    } catch (error) {
      process.stdout.write(JSON.stringify({status: 'error', reason: error.reason || 'unsupported',
        message: error.reason ? error.message : '网页驱动输入无效。'}) + '\n', () => process.exit(2));
    }
  });
}
