// 软著工具箱桌面端：Electron 外壳 + ruanzhu-kit 脚本引擎 + 本机 Claude Code（Agent SDK）。
const { app, BrowserWindow, ipcMain, dialog, shell, safeStorage } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { spawn, execFileSync } = require('child_process');
const { runAgent } = require('./agent');

// 开发时直接用仓库里的 scripts；打包后用 Resources/kit（见 package.json extraResources）
const KIT = app.isPackaged ? path.join(process.resourcesPath, 'kit') : path.resolve(__dirname, '..');
const SCRIPTS = path.join(KIT, 'scripts');
const OUTPUT = 'soft-copyright-materials';
// 从 Finder 启动的 App 只有极简 PATH，补上 Homebrew / 用户目录，便于找到 pandoc、python3、claude
const EXTRA_PATH = ['/opt/homebrew/bin', '/usr/local/bin', path.join(os.homedir(), '.local/bin')];

let win;
let agentAbort = null;

// ---------------------------------------------------------------- 设置
const settingsFile = () => path.join(app.getPath('userData'), 'settings.json');

function loadSettings() {
  try {
    const raw = JSON.parse(fs.readFileSync(settingsFile(), 'utf8'));
    if (raw.apiKeyEnc && safeStorage.isEncryptionAvailable()) {
      raw.apiKey = safeStorage.decryptString(Buffer.from(raw.apiKeyEnc, 'base64'));
    }
    if (raw.zhusqueApiKeyEnc && safeStorage.isEncryptionAvailable()) {
      raw.zhusqueApiKey = safeStorage.decryptString(Buffer.from(raw.zhusqueApiKeyEnc, 'base64'));
    }
    delete raw.apiKeyEnc;
    delete raw.zhusqueApiKeyEnc;
    return raw;
  } catch {
    return {};
  }
}

function saveSettings(s) {
  const out = { ...s };
  delete out.apiKey;
  delete out.zhusqueApiKey;
  if (s.apiKey && safeStorage.isEncryptionAvailable()) {
    out.apiKeyEnc = safeStorage.encryptString(s.apiKey).toString('base64');
  }
  if (s.zhusqueApiKey && safeStorage.isEncryptionAvailable()) {
    out.zhusqueApiKeyEnc = safeStorage.encryptString(s.zhusqueApiKey).toString('base64');
  }
  fs.mkdirSync(path.dirname(settingsFile()), { recursive: true });
  fs.writeFileSync(settingsFile(), JSON.stringify(out, null, 2));
}

function env() {
  const parts = (process.env.PATH || '').split(':');
  return { ...process.env, PATH: [...EXTRA_PATH, ...parts].filter(Boolean).join(':'), PYTHONIOENCODING: 'utf-8' };
}

// 朱雀 Key 只注入脚本子进程，不进入项目配置、AI Agent 环境或日志。
function zhusqueEnv() {
  const s = loadSettings();
  return s.zhusqueApiKey ? { MAKERS_MODELS_KEY: s.zhusqueApiKey } : {};
}

function firstWorking(candidates, testArgs) {
  for (const c of candidates.filter(Boolean)) {
    try {
      execFileSync(c, testArgs, { env: env(), stdio: 'ignore', timeout: 15000 });
      return c;
    } catch { /* 下一个 */ }
  }
  return null;
}

// App 私有虚拟环境：找不到可用 Python 时由“一键安装依赖”创建
const venvPython = () => path.join(app.getPath('userData'), 'pyenv', 'bin', 'python3');

// 所有可能的 python3：设置 > 私有 venv > Homebrew 各版本 > 用户登录 shell 的 PATH > 系统
function pythonCandidates() {
  const s = loadSettings();
  const brew = ['/opt/homebrew/opt', '/usr/local/opt'].flatMap(dir => {
    try {
      return fs.readdirSync(dir).filter(n => /^python@3\.\d+$/.test(n)).sort().reverse()
        .flatMap(n => [path.join(dir, n, 'libexec/bin/python3'), path.join(dir, n, 'bin/python3')]);
    } catch { return []; }
  });
  let shellPaths = [];
  try {
    shellPaths = execFileSync('/bin/zsh', ['-ilc', 'which -a python3'], { encoding: 'utf8', timeout: 8000 })
      .split('\n').map(l => l.trim()).filter(l => l.startsWith('/'));
  } catch { /* 忽略 */ }
  return [...new Set([s.pythonPath, venvPython(), ...brew, ...shellPaths,
    '/opt/homebrew/bin/python3', '/usr/local/bin/python3', '/usr/bin/python3'].filter(Boolean))];
}

let cachedPython;
// 需要装有 python-docx 和 pypdf 的 python3；系统自带 /usr/bin/python3 通常没有
function findPython(refresh = false) {
  if (cachedPython && !refresh && fs.existsSync(cachedPython)) return cachedPython;
  cachedPython = firstWorking(pythonCandidates(), ['-c', 'import docx, pypdf']);
  return cachedPython;
}

// 用任意 Python 3.9+ 创建私有 venv 并安装 requirements.txt（需要联网，由用户点击触发）
async function installPythonDeps(id) {
  const base = firstWorking(pythonCandidates().filter(p => p !== venvPython()),
    ['-c', 'import sys, venv; assert sys.version_info >= (3, 9)']);
  if (!base) {
    log(id, '没有找到 Python 3.9 以上版本。请先安装：brew install python，或从 python.org 下载。\n', 'err');
    return { code: -1 };
  }
  const dir = path.dirname(path.dirname(venvPython()));
  let r = await runProcess(id, base, ['-m', 'venv', dir]);
  if (r.code !== 0) return r;
  r = await runProcess(id, venvPython(), ['-m', 'pip', 'install', '--disable-pip-version-check', '-r', path.join(KIT, 'requirements.txt')]);
  findPython(true);
  return r;
}

// 复用本机已安装、已登录的 Claude Code，不在 App 里再打包一份
function findClaude() {
  const s = loadSettings();
  return firstWorking([s.claudePath, path.join(os.homedir(), '.local/bin/claude'), '/opt/homebrew/bin/claude',
    '/usr/local/bin/claude', 'claude'], ['--version']);
}

// ---------------------------------------------------------------- 路径
const cfgPath = repo => path.join(repo, OUTPUT, 'ruanzhu.config.json');
// 脚本在项目目录下运行，配置参数用相对路径，和 SKILL.md 中的命令行用法一致
const CFG = path.join(OUTPUT, 'ruanzhu.config.json');

// 只允许读写项目的材料目录，防止界面误写源代码
function materialFile(repo, rel) {
  const root = path.resolve(repo, OUTPUT);
  const full = path.resolve(root, rel);
  if (full !== root && !full.startsWith(root + path.sep)) throw new Error(`拒绝访问材料目录之外的文件：${rel}`);
  return full;
}

function log(id, text, kind = 'out') {
  if (win && !win.isDestroyed()) win.webContents.send('log', { id, text, kind });
}

function runProcess(id, cmd, args, opts = {}) {
  return new Promise(resolve => {
    log(id, `$ ${path.basename(cmd)} ${args.map(a => (/\s/.test(a) ? JSON.stringify(a) : a)).join(' ')}\n`, 'cmd');
    const child = spawn(cmd, args, { env: { ...env(), ...(opts.env || {}) }, cwd: opts.cwd });
    child.stdout.on('data', d => log(id, d.toString()));
    child.stderr.on('data', d => log(id, d.toString(), 'err'));
    child.on('error', e => { log(id, `${e.message}\n`, 'err'); resolve({ code: -1 }); });
    child.on('close', code => { log(id, `\n[退出码 ${code}]\n`, code === 0 ? 'ok' : 'err'); resolve({ code }); });
  });
}

async function runPy(id, repo, script, args) {
  const py = findPython();
  if (!py) {
    log(id, '找不到带 python-docx 的 python3。请执行：pip3 install -r requirements.txt，或在设置里指定 Python 路径。\n', 'err');
    return { code: -1 };
  }
  return runProcess(id, py, [path.join(SCRIPTS, script), ...args], {
    cwd: repo, env: zhusqueEnv(),
  });
}

// ---------------------------------------------------------------- 配置
function ensureConfig(repo) {
  const p = cfgPath(repo);
  if (!fs.existsSync(p)) {
    fs.mkdirSync(path.dirname(p), { recursive: true });
    const tpl = JSON.parse(fs.readFileSync(path.join(KIT, 'assets', 'ruanzhu.config.example.json'), 'utf8'));
    tpl.project_name = path.basename(repo);
    tpl.output_root = OUTPUT;
    delete tpl._comment;
    // 模板里的示例名称、端类型、用户角色和源码路径不是事实：新项目一律清空，由 AI 分析或用户填写
    tpl.projects = tpl.projects.slice(0, 1).map(proj => ({
      ...proj, id: '01-软件', name: '', short_name: '', artifact_label: '', document_kind: '',
      users: [], source_map: [], source_files: [], modules: [],
    }));
    fs.writeFileSync(p, JSON.stringify(tpl, null, 2) + '\n');
  }
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

function outputs(repo) {
  const cfg = fs.existsSync(cfgPath(repo)) ? JSON.parse(fs.readFileSync(cfgPath(repo), 'utf8')) : { projects: [] };
  const root = path.join(repo, OUTPUT);
  const list = f => (fs.existsSync(f) ? fs.readdirSync(f) : []);
  return {
    root,
    dashboard: fs.existsSync(path.join(root, '看板.html')) ? path.join(root, '看板.html') : null,
    missingInfo: fs.existsSync(path.join(root, '缺失信息清单.md')),
    projects: (cfg.projects || []).map(p => {
      const d = path.join(root, p.id);
      // 提交件目录（新版 提交材料/）优先，兼容旧版放在项目根目录和 源程序提取/ 的 PDF
      const pdfs = ['提交材料', '', '源程序提取'].flatMap(sub => list(path.join(d, sub))
        .filter(n => n.endsWith('.pdf') && !n.includes('作废')).map(n => (sub ? `${sub}/${n}` : n)));
      const markerPath = path.join(d, '.zhusque-final.json');
      const reportPath = path.join(d, '朱雀检测报告.md');
      let zhusqueFresh = fs.existsSync(markerPath) && fs.existsSync(reportPath);
      if (zhusqueFresh) {
        try {
          const markerTime = fs.statSync(markerPath).mtimeMs;
          const materialFiles = [
            path.join(d, '软件说明书.md'),
            path.join(d, '申请表填报文案.md'),
            path.join(d, 'auto-fill', 'config.json'),
            ...pdfs.filter(n => n.includes('软件说明')).map(n => path.join(d, n)),
          ];
          zhusqueFresh = materialFiles.filter(fs.existsSync)
            .every(f => fs.statSync(f).mtimeMs <= markerTime);
        } catch { zhusqueFresh = false; }
      }
      let declines = 0;
      try {
        const raw = JSON.parse(fs.readFileSync(path.join(d, '.zhusque-declined.json'), 'utf8'));
        declines = (raw.declines || []).filter(r => r && String(r.reason || '').trim()).length;
      } catch { declines = 0; }
      return {
        id: p.id, name: p.name, dir: d,
        manual: fs.existsSync(path.join(d, '软件说明书.md')),
        form: fs.existsSync(path.join(d, 'auto-fill', 'config.json')),
        zhusque: {
          checked: zhusqueFresh,
          report: fs.existsSync(reportPath),
          marker: fs.existsSync(markerPath),
          stale: !zhusqueFresh && fs.existsSync(markerPath) && fs.existsSync(reportPath),
          declines,
          waived: declines >= ZHUSQUE_DECLINE_THRESHOLD,
        },
        pdfs,
      };
    }),
  };
}

// ---------------------------------------------------------------- IPC
ipcMain.handle('pick-repo', async () => {
  const r = await dialog.showOpenDialog(win, { title: '选择软件项目的源码目录', properties: ['openDirectory'] });
  return r.canceled ? null : r.filePaths[0];
});

ipcMain.handle('config:load', (_e, repo) => ensureConfig(repo));
ipcMain.handle('config:save', (_e, repo, cfg) => {
  fs.writeFileSync(cfgPath(repo), JSON.stringify(cfg, null, 2) + '\n');
  return true;
});
ipcMain.handle('outputs', (_e, repo) => outputs(repo));

ipcMain.handle('file:read', (_e, repo, rel) => {
  const f = materialFile(repo, rel);
  return fs.existsSync(f) ? fs.readFileSync(f, 'utf8') : null;
});
ipcMain.handle('file:write', (_e, repo, rel, text) => {
  fs.writeFileSync(materialFile(repo, rel), text);
  // 说明书或申请表发生编辑后，旧朱雀报告不再对应当前正文。
  if (['软件说明书.md', '申请表填报文案.md'].includes(path.basename(rel))) {
    const projectDir = path.dirname(materialFile(repo, rel));
    for (const stale of ['.zhusque-final.json', '朱雀检测报告.md']) {
      const f = path.join(projectDir, stale);
      if (fs.existsSync(f)) fs.unlinkSync(f);
    }
  }
  return true;
});

ipcMain.handle('open-path', (_e, p) => shell.openPath(p));
ipcMain.handle('reveal', (_e, p) => shell.showItemInFolder(p));
ipcMain.handle('open-external', (_e, url) => {
  if (!/^https:\/\//i.test(String(url || ''))) throw new Error('只允许打开 HTTPS 链接');
  return shell.openExternal(String(url));
});

ipcMain.handle('settings:get', () => {
  const s = loadSettings();
  return {
    ...s,
    apiKey: s.apiKey ? '••••••••' : '',
    zhusqueApiKey: s.zhusqueApiKey ? '••••••••' : '',
    python: findPython(true), claude: findClaude(),
  };
});
ipcMain.handle('settings:set', (_e, patch) => {
  const s = loadSettings();
  for (const [k, v] of Object.entries(patch)) {
    if ((k === 'apiKey' || k === 'zhusqueApiKey') && v === '••••••••') continue; // 未修改的掩码
    if (v === '' || v == null) delete s[k]; else s[k] = v;
  }
  saveSettings(s);
  return true;
});

// 固定脚本调用（不需要 AI）。只允许白名单脚本，参数由界面拼好
const ZHUSQUE_DECLINE_THRESHOLD = 2;
const SCRIPT_TASKS = {
  preflight: repo => ['preflight.py', ['--config', CFG]],
  // 不调用 AI：先抽取源码素材（源程序量、页面、接口），再按配置生成初稿
  docs: repo => [['manual_spec.py', ['--repo', repo, '--out', path.join(repo, OUTPUT, '说明书素材.json')]],
    ['generate_docs.py', ['--config', CFG]]],
  source: repo => ['generate_source_docx.py', ['--config', CFG, '--repo', repo, '--preview']],
  pdf: repo => ['render_pdfs.py', ['--config', CFG, '--repo', repo]],
  form: repo => ['application_form.py', ['--config', CFG]],
  aigc: (repo, pid) => ['aigc_check.py', [path.join(repo, OUTPUT, pid), '--report', path.join(repo, OUTPUT, pid, 'AIGC检测报告.md')]],
  zhusque: (repo, pid) => ['zhusque_check.py', ['finalize', path.join(repo, OUTPUT, pid), '--allow-upload',
    '--report', path.join(repo, OUTPUT, pid, '朱雀检测报告.md')]],
  // 只有用户在界面上逐次确认拒绝后才调用；累计 2 次才豁免，豁免不等于已检测
  zhusqueDecline: (repo, pid) => ['zhusque_check.py', ['decline', path.join(repo, OUTPUT, pid),
    '--reason', '用户在桌面 App 中确认拒绝朱雀检测', '--source', 'app', '--user-declined']],
  manifest: (repo, pid) => ['artifact_manifest.py', ['--config', CFG, '--project', pid, '--verify']],
  dashboard: repo => ['dashboard.py', ['--config', CFG, '--repo', repo]],
  screenshots: (repo, pid) => ['screenshots.py', ['--materials', path.join(repo, OUTPUT, pid),
    '--spec', path.join(repo, OUTPUT, '说明书素材.json')]],
  plan: (repo, pid) => ['form_plan.py', ['--config', path.join(repo, OUTPUT, pid, 'auto-fill', 'config.json'),
    '--out', path.join(repo, OUTPUT, pid, '填表操作计划.md')]],
};

ipcMain.handle('install-python', (_e, id) => installPythonDeps(id));

ipcMain.handle('run', async (_e, id, task, repo, pid) => {
  if (!SCRIPT_TASKS[task]) throw new Error(`未知任务：${task}`);
  const spec = SCRIPT_TASKS[task](repo, pid);
  const steps = Array.isArray(spec[0]) ? spec : [spec];
  let r = { code: 0 };
  for (const [script, args] of steps) {
    r = await runPy(id, repo, script, args);
    if (r.code !== 0) break;
  }
  return r;
});

// 只返回不含 Key 的朱雀状态。状态检查本身不会上传任何材料。
ipcMain.handle('zhusque:status', async () => {
  const py = findPython();
  const fallback = {
    configured: false,
    source: '',
    console_url: 'https://console.cloud.tencent.com/edgeone/makers?tab=models&subTab=apikey',
    web_url: 'https://matrix.tencent.com/ai-detect/',
    error: py ? '' : '未找到可用 Python',
  };
  if (!py) return fallback;
  return new Promise(resolve => {
    const child = spawn(py, [path.join(SCRIPTS, 'zhusque_check.py'), 'status', '--json'], {
      env: { ...env(), ...zhusqueEnv() },
    });
    let stdout = '';
    let stderr = '';
    const timer = setTimeout(() => { child.kill(); resolve({ ...fallback, error: '状态检查超时' }); }, 8000);
    child.stdout.on('data', d => { stdout += d.toString(); });
    child.stderr.on('data', d => { stderr += d.toString(); });
    child.on('error', e => { clearTimeout(timer); resolve({ ...fallback, error: e.message }); });
    child.on('close', () => {
      clearTimeout(timer);
      try { resolve({ ...fallback, ...JSON.parse(stdout.trim()) }); }
      catch { resolve({ ...fallback, error: stderr.trim() || '无法读取朱雀状态' }); }
    });
  });
});

// 浏览器填表：用 Electron 自带的 Node 运行 auto-fill.js（Playwright 驱动本机 Chrome，停在保存草稿）
ipcMain.handle('autofill', async (_e, id, repo, pid, checkOnly) => {
  const conf = path.join(repo, OUTPUT, pid, 'auto-fill', 'config.json');
  const args = [path.join(SCRIPTS, 'auto-fill', 'auto-fill.js'), conf];
  if (checkOnly) args.push('--check');
  return runProcess(id, process.execPath, args, {
    cwd: repo,
    env: { ELECTRON_RUN_AS_NODE: '1', NODE_PATH: path.join(__dirname, 'node_modules') },
  });
});

ipcMain.handle('screenshot-dir', (_e, repo, pid) => {
  const d = path.join(repo, OUTPUT, pid, '用户截图');
  fs.mkdirSync(d, { recursive: true });
  shell.openPath(d);
  return d;
});

ipcMain.handle('agent:run', async (_e, id, task, repo, extra) => {
  const claude = findClaude();
  if (!claude) {
    log(id, '找不到本机 Claude Code（claude 命令）。请先安装并登录，或在设置里填写 claude 可执行文件路径。\n', 'err');
    return { ok: false };
  }
  const s = loadSettings();
  agentAbort = new AbortController();
  try {
    return await runAgent({
      task, repo, extra, kit: KIT, output: OUTPUT, python: findPython() || 'python3', claude,
      apiKey: s.apiKey, model: s.model, env: env(), abort: agentAbort,
      onEvent: (text, kind) => log(id, text, kind),
    });
  } catch (e) {
    log(id, `\n${e.message}\n`, 'err');
    if (/organization has been disabled|authentication|invalid x-api-key|OAuth|401|403|Please run \/login/i.test(e.message)) {
      log(id, '\n→ AI 账号不可用：请在终端运行 claude 并用 /login 登录可用账号，或在“设置”中填写 Anthropic API Key 后重试。\n'
        + '  不调用 AI 时，可以在“AI 生成材料”页使用“仅用脚本生成”。\n', 'err');
    }
    return { ok: false };
  } finally {
    agentAbort = null;
  }
});
ipcMain.handle('agent:stop', () => { if (agentAbort) agentAbort.abort(); return true; });

// ---------------------------------------------------------------- 窗口
function createWindow() {
  win = new BrowserWindow({
    width: 1280, height: 860, minWidth: 980, minHeight: 640,
    title: '软著工具箱',
    titleBarStyle: 'hiddenInset',
    backgroundColor: '#f6f7f9',
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false },
  });
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
}

app.whenReady().then(createWindow);
app.on('window-all-closed', () => app.quit());
