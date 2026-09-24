// App 内 Agent 的 Bash 白名单。黑名单挡不住 `python3 -c`、`sed -i`、重定向等写法，
// 这里只放行两类命令：ruanzhu-kit 的离线脚本，以及不会写文件、不会执行子命令的只读工具。
const path = require('path');

// 只允许离线、只写材料目录的脚本；联网（朱雀/Jev/更新检查）、启动项目、写库、改 git 的脚本由 App 界面单独触发
const KIT_SCRIPTS = new Set([
  'manual_spec.py', 'create_config.py', 'generate_docs.py', 'generate_source_docx.py', 'source_preview.py',
  'copyright_check.py', 'oss_scrub.py', 'aigc_check.py', 'aigc_rewrite.py', 'application_form.py',
  'artifact_manifest.py', 'form_plan.py', 'dashboard.py', 'screenshots.py', 'preflight.py',
  'prepare_demo_data.py', 'ai_compliance.py', 'workflow_smoke.py', 'environment_profile.py',
]);
const OUTPUT_FLAGS = new Set(['--out', '--output', '--report', '--rollback-file']);
const FORBIDDEN_FLAGS = /^--(allow-upload|allow-write|allow-run|jev|output=|pre\b|pre=)/;

// 只读工具及各自禁止的参数（这些参数会写文件或执行其他程序）
const READ_TOOLS = {
  ls: [], cat: [], head: [], tail: [], wc: [], grep: [], pwd: [], echo: [], stat: [], file: [], du: [],
  cut: [], tr: [], basename: [], dirname: [], realpath: [], which: [],
  rg: ['--pre', '--pre-glob'],
  find: ['-exec', '-execdir', '-delete', '-ok', '-okdir', '-fprint', '-fprint0', '-fprintf', '-fls'],
  sort: ['-o', '--output'],
};
const GIT_READ = new Set(['status', 'log', 'diff', 'show', 'ls-files', 'rev-parse', 'blame', 'shortlog']);
const SAFE_REDIRECTS = new Set(['2>/dev/null', '2>&1', '>/dev/null']);

// 按 shell 规则切分：返回 { tokens: [[...], ...] }（按 && || ; | 分段），遇到不允许的语法返回 { error }
function tokenize(cmd) {
  const segments = [[]];
  let cur = '';
  let has = false;
  let quote = null;
  const push = () => { if (has) segments[segments.length - 1].push(cur); cur = ''; has = false; };
  for (let i = 0; i < cmd.length; i++) {
    const c = cmd[i];
    if (quote === "'") { if (c === "'") quote = null; else cur += c; continue; }
    if (c === '`' || (c === '$' && quote !== "'")) return { error: '不允许命令替换或变量展开' };
    if (quote === '"') {
      if (c === '"') quote = null;
      else if (c === '\\' && i + 1 < cmd.length) cur += cmd[++i];
      else cur += c;
      continue;
    }
    if (c === "'" || c === '"') { quote = c; has = true; continue; }
    if (c === '\\' && i + 1 < cmd.length) { cur += cmd[++i]; has = true; continue; }
    if (/\s/.test(c)) { if (c === '\n') { push(); segments.push([]); } else push(); continue; }
    if (c === '>' || c === '<') {
      const rest = (has ? cur : '') + cmd.slice(i);
      const safe = [...SAFE_REDIRECTS].find(r => rest.startsWith(r) && (rest.length === r.length || /[\s;&|]/.test(rest[r.length])));
      if (!safe) return { error: '不允许重定向读写文件' };
      i += safe.length - (has ? cur.length : 0) - 1;
      cur = ''; has = false;
      continue;
    }
    if (c === '&' || c === '|' || c === ';') {
      push();
      const two = cmd.slice(i, i + 2);
      if (two === '&&' || two === '||') i++;
      else if (c === '&') return { error: '不允许后台执行' };
      segments.push([]);
      continue;
    }
    if (c === '(' || c === ')' || c === '{' || c === '}') return { error: '不允许子 shell 或代码块' };
    cur += c; has = true;
  }
  if (quote) return { error: '引号未闭合' };
  push();
  return { tokens: segments.filter(s => s.length) };
}

function isPython(token, python) {
  return token === python || /^python3(\.\d+)?$/.test(path.basename(token));
}

function checkSegment(argv, { kit, repo, outRoot, python }) {
  const [cmd, ...args] = argv;
  if (/^\w+=/.test(cmd)) return '不允许在命令前设置环境变量';
  if (isPython(cmd, python)) {
    const script = args[0] ? path.resolve(repo, args[0]) : '';
    const scriptsDir = path.join(kit, 'scripts');
    if (path.dirname(script) !== scriptsDir || !KIT_SCRIPTS.has(path.basename(script))) {
      return `Python 只能运行 ${scriptsDir} 下的材料脚本`;
    }
    for (let i = 1; i < args.length; i++) {
      const a = args[i];
      if (FORBIDDEN_FLAGS.test(a)) return `App 中不允许使用 ${a}（联网、写库或启动项目需在界面中操作）`;
      const [flag, inline] = a.startsWith('--') && a.includes('=') ? a.split(/=(.*)/s) : [a, null];
      if (OUTPUT_FLAGS.has(flag)) {
        const value = inline ?? args[++i];
        if (!value || !(path.resolve(repo, value) + path.sep).startsWith(outRoot)) {
          return `${flag} 只能写入材料目录`;
        }
      }
    }
    return null;
  }
  if (cmd === 'git') {
    if (!GIT_READ.has(args[0])) return 'git 只允许只读查询（status/log/diff/show 等）';
    if (args.some(a => a.startsWith('--output') || a === '--ext-diff')) return 'git 不允许写出文件或外部 diff';
    return null;
  }
  const banned = READ_TOOLS[cmd];
  if (!banned) return `App 中不允许执行 ${cmd}`;
  const hit = args.find(a => banned.some(b => a === b || a.startsWith(`${b}=`) || (b.length === 2 && a.startsWith(b))));
  return hit ? `${cmd} 不允许使用 ${hit}` : null;
}

// 返回 null 表示放行，否则返回拒绝原因
function checkBash(command, ctx) {
  const parsed = tokenize(String(command || ''));
  if (parsed.error) return parsed.error;
  if (!parsed.tokens.length) return '空命令';
  for (const argv of parsed.tokens) {
    const reason = checkSegment(argv, ctx);
    if (reason) return reason;
  }
  return null;
}

module.exports = { checkBash, tokenize, KIT_SCRIPTS };
