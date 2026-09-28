/* global kit, marked */
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

// 与 scripts/aigc_rules.py 的 PLACEHOLDER 保持一致
const PLACEHOLDER = /【\s*(?:待|[^】\n]*(?:预留|占位|字以内|字内|例：|行数))[^】\n]*】|按项目实际(?:填写|依赖填写|支持平台填写)/g;

const state = { repo: null, cfg: null, pid: null, busy: false };
const ZHUSQUE_CONSOLE_URL = 'https://console.cloud.tencent.com/edgeone/makers?tab=models&subTab=apikey';
const ZHUSQUE_WEB_URL = 'https://matrix.tencent.com/ai-detect/';
const store = {
  get: k => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* 忽略 */ } },
};

// ---------------------------------------------------------------- 导航
function show(view) {
  $$('#nav a').forEach(a => a.classList.toggle('active', a.dataset.view === view));
  $$('.view').forEach(v => v.classList.toggle('active', v.id === `view-${view}`));
  if (view === 'editor') loadDoc();
  if (view === 'export') refreshOutputs();
  if (view === 'info') renderInfo();
  store.set('view', view);
}
$$('#nav a').forEach(a => a.addEventListener('click', () => show(a.dataset.view)));

// ---------------------------------------------------------------- 日志
const logEl = $('#log');
let currentRun = null;
kit.onLog(({ id, text, kind }) => {
  if (id !== currentRun) return;
  const span = document.createElement('span');
  span.className = kind;
  span.textContent = text;
  logEl.appendChild(span);
  logEl.scrollTop = logEl.scrollHeight;
});
$('#clearLog').onclick = () => { logEl.textContent = ''; };
$('#toggleLog').onclick = () => {
  const c = $('#logPane').classList.toggle('collapsed');
  $('#toggleLog').textContent = c ? '展开' : '收起';
};

async function withRun(title, fn) {
  if (state.busy) return null;
  if (!state.repo) { alert('请先选择项目文件夹'); return null; }
  state.busy = true;
  currentRun = `${Date.now()}`;
  $('#logTitle').textContent = title;
  $('#busy').hidden = false;
  $('#logPane').classList.remove('collapsed');
  $$('button[data-run],button[data-agent],#fillRun,#fillCheck,#zhusqueRun,#zhusqueExportRun,#zhusqueRewrite,#zhusqueExportRewrite,#zhusqueDecline').forEach(b => { b.disabled = true; });
  logEl.textContent = '';
  try {
    return await fn(currentRun);
  } finally {
    state.busy = false;
    $('#busy').hidden = true;
    $$('button[data-run],button[data-agent],#fillRun,#fillCheck,#zhusqueRun,#zhusqueExportRun,#zhusqueDecline').forEach(b => { b.disabled = false; });
    await refreshZhusqueStatus();
  }
}

// ---------------------------------------------------------------- 项目
async function openRepo(repo) {
  state.repo = repo;
  store.set('repo', repo);
  $('#repoBtn').textContent = repo;
  state.cfg = await kit.loadConfig(repo);
  state.pid = state.cfg.projects?.[0]?.id || null;
  renderRepoCard();
  renderModules();
  renderProjectSelect();
}

$('#repoBtn').onclick = async () => {
  const repo = await kit.pickRepo();
  if (repo) await openRepo(repo);
};

function renderRepoCard() {
  const cfg = state.cfg;
  const projects = (cfg.projects || []).map(p => `<li><b>${esc(p.name || p.id)}</b> <span class="muted">${esc(p.id)}</span></li>`).join('');
  $('#repoCard').innerHTML = `
    <dl class="kv"><dt>源码目录</dt><dd>${esc(state.repo)}</dd>
    <dt>材料目录</dt><dd>${esc(state.repo)}/soft-copyright-materials</dd>
    <dt>软著数量</dt><dd>${(cfg.projects || []).length} 份</dd></dl>
    <ul>${projects}</ul>`;
}

async function renderEnv() {
  const s = await kit.getSettings();
  $('#installPy').hidden = !!s.python;
  $('#envInfo').innerHTML = `
    <dt>Python</dt><dd class="${s.python ? 'ok' : 'err'}">${esc(s.python || '未找到（需要 python3 + python-docx）')}</dd>
    <dt>Claude Code</dt><dd class="${s.claude ? 'ok' : 'err'}">${esc(s.claude || '未找到 claude 命令，AI 步骤不可用')}</dd>
    <dt>AI 身份</dt><dd>${s.apiKey ? '使用设置中的 API Key' : '使用本机 Claude Code 登录'}${s.model ? `，模型 ${esc(s.model)}` : ''}</dd>`;
  await refreshZhusqueStatus();
}

async function refreshZhusqueStatus(materialOutputs = null) {
  const status = await kit.zhusqueStatus();
  const text = $('#zhusqueStatus');
  const hint = $('#zhusqueHint');
  if (!text) return status;
  if (status.configured) {
    text.innerHTML = '<span class="ok">已配置 Key：API 优先，失败时自动尝试网页</span>';
    hint.textContent = '首次覆盖全部正文；修改后只检测变化内容并合并历史结果。网页遇验证码、登录或额度限制时保留待复核状态。';
    $('#zhusqueKey').textContent = '更换 API Key';
  } else {
    text.innerHTML = '<span class="warn">未配置 Key：自动打开浏览器进行朱雀检测</span>';
    hint.textContent = '首次覆盖全部正文；修改后只检测变化内容。网页遇验证码或登录时请在打开的浏览器中处理；额度不足的内容保留待复核，不会标记完成。';
    $('#zhusqueKey').textContent = '获取 / 配置 API Key';
  }
  let current = null;
  if ($('#zhusqueExportStatus')) {
    const p = project();
    const o = state.cfg && p ? materialOutputs || await kit.outputs(state.repo) : null;
    const z = o?.projects.find(x => x.id === p?.id)?.zhusque;
    current = z;
    $('#zhusqueExportStatus').innerHTML = z?.checked
      ? '<span class="ok">当前全文已覆盖，朱雀风险占比符合阈值，报告已保存</span>'
      : z?.waived
        ? `<span class="warn">用户已明确拒绝 ${z.declines} 次，按豁免放行（材料未经朱雀检测）</span>`
      : z?.declines
        ? `<span class="warn">朱雀检测是必需步骤；已记录拒绝 ${z.declines}/2 次，再次明确拒绝才会豁免</span>`
      : z?.stale
        ? '<span class="warn">正文已变化，请复检变化内容；未变部分复用历史检测结果</span>'
      : z?.report
        ? '<span class="warn">已有检测报告，但当前正文尚未通过完整复核；请查看报告和日志中的待处理内容</span>'
        : '<span class="warn">尚未完成朱雀检测，不能把材料当作终稿上传</span>';
  }
  for (const button of $$('#zhusqueRewrite,#zhusqueExportRewrite')) {
    button.disabled = state.busy || !current?.can_rewrite;
    button.title = current?.can_rewrite
      ? '仅修改当前朱雀任务单标记的内容，完成后自动增量复核'
      : '完成当前正文检测并生成需修改任务单后可用；待检测或过期报告不可直接改写';
  }
  return { ...status, current };
}

async function guideZhusqueKey() {
  await kit.openExternal(ZHUSQUE_CONSOLE_URL);
  $('#zhusqueHint').textContent = '已打开 Key 页面。生成 Key 后回到这里，在“设置”中粘贴并保存；Key 只保存在本机。';
  const f = $('#settings form');
  if (f) {
    const s = await kit.getSettings();
    for (const k of ['model', 'apiKey', 'zhusqueApiKey', 'pythonPath', 'claudePath']) f.elements[k].value = s[k] || '';
    $('#settings').showModal();
  }
}

async function openZhusqueWeb() { await kit.openExternal(ZHUSQUE_WEB_URL); }

async function runZhusque(id, announce = true) {
  if (!state.repo || !state.pid) return { code: -1 };
  if (announce) logEl.appendChild(Object.assign(document.createElement('span'), {
    className: 'cmd', textContent: '\n开始朱雀复核：首次覆盖全部正文，后续只检测变化内容。API 优先，无 Key 或 API 失败时自动尝试网页…\n',
  }));
  const result = await kit.run(id, 'zhusque', state.repo, state.pid);
  const status = await refreshZhusqueStatus();
  const verified = result?.code === 0 && status.current?.checked === true;
  if (!verified) logEl.appendChild(Object.assign(document.createElement('span'), {
    className: 'warn', textContent: '\n材料仍待复核。已完成部分会保留；请根据报告修改风险段落，或处理浏览器提示后再次复检变化内容。\n',
  }));
  const nav = $('#nav a[data-view="generate"]');
  if (nav) nav.classList.toggle('done', verified);
  return { ...result, verified };
}

async function reviewRevision(id) {
  if (dirty) {
    logEl.appendChild(Object.assign(document.createElement('span'), {
      className: 'warn', textContent: '\n编辑器有未保存的修改，请先保存后再复检，确保检测的是当前正文。\n',
    }));
    return { code: 2, pending: true, verified: false };
  }
  const o = await kit.outputs(state.repo);
  const current = o.projects.find(p => p.id === state.pid);
  if (current?.pdfs?.some(file => file.includes('软件说明'))) {
    logEl.appendChild(Object.assign(document.createElement('span'), {
      className: 'cmd', textContent: '\n正文修改完成，先同步正式 PDF，再复检变化内容…\n',
    }));
    const pdf = await kit.run(id, 'pdf', state.repo, state.pid);
    if (pdf?.code !== 0) {
      logEl.appendChild(Object.assign(document.createElement('span'), {
        className: 'warn', textContent: '\n正式 PDF 更新失败，本轮保持待复核；修复导出问题后再复检。\n',
      }));
      $('#nav a[data-view="generate"]')?.classList.remove('done');
      await refreshZhusqueStatus();
      return { ...pdf, verified: false };
    }
  }
  return runZhusque(id);
}

async function rewriteZhusque(id) {
  if (dirty) {
    logEl.appendChild(Object.assign(document.createElement('span'), {
      className: 'warn', textContent: '\n编辑器有未保存的修改，请先保存并复检变化内容，再按新任务单修改。\n',
    }));
    return { code: 2, pending: true };
  }
  const o = await kit.outputs(state.repo);
  const current = o.projects.find(p => p.id === state.pid)?.zhusque;
  if (!current?.can_rewrite) {
    logEl.appendChild(Object.assign(document.createElement('span'), {
      className: 'warn', textContent: '\n请先完成当前正文检测。待检测内容或过期任务单不能直接用于改写。\n',
    }));
    return { code: 2, pending: true };
  }
  const result = await kit.agent(id, 'revise', state.repo, {
    projectId: state.pid,
    zhusqueOnly: true,
    note: '按当前朱雀改写任务单修改有源码依据的风险段落；只做本轮标记内容修改，保持未标记正文不变，同步受影响章节。',
  });
  if (!result?.ok) return result;
  await loadDoc();
  return reviewRevision(id);
}

$('#installPy').onclick = async () => {
  state.busy = false;
  currentRun = `${Date.now()}`;
  $('#logTitle').textContent = '安装 Python 依赖';
  $('#logPane').classList.remove('collapsed');
  logEl.textContent = '';
  $('#installPy').disabled = true;
  await kit.installPython(currentRun);
  $('#installPy').disabled = false;
  renderEnv();
};

// ---------------------------------------------------------------- 基本信息
const INFO = [
  { h: '著作权信息' },
  { k: 'copyright_holder', label: '著作权人', req: true },
  { k: 'development_completed_date', label: '开发完成日期', type: 'date', req: true },
  { h: '软件信息' },
  { p: 'name', label: '软件全称', req: true },
  { p: 'short_name', label: '软件简称' },
  { p: 'version', label: '版本号', req: true },
  { p: 'artifact_label', label: '端类型（后端 / 桌面端 / 网页端 / 小程序 …）' },
  { p: 'dev_purpose', label: '开发目的（50 字内）', req: true, max: 50 },
  { p: 'target_industry', label: '面向领域/行业（50 字内）', req: true, max: 50 },
  { p: 'tech_feature_text', label: '技术特点（100 字内）', req: true, max: 100, wide: true, area: true },
  { h: '开发与运行环境' },
  { e: 'dev_hardware', label: '开发硬件环境', req: true, max: 100 },
  { e: 'run_hardware', label: '运行硬件环境', req: true, max: 100 },
  { e: 'dev_os', label: '开发操作系统', req: true, max: 50 },
  { e: 'run_os', label: '运行操作系统', req: true, max: 50 },
  { e: 'dev_tools', label: '开发工具（IDE/编译器/构建工具，不写框架名）', req: true, max: 50 },
  { e: 'run_support', label: '运行支撑环境', req: true, max: 50 },
];

function project() {
  return (state.cfg?.projects || []).find(p => p.id === state.pid) || state.cfg?.projects?.[0];
}

function renderInfo() {
  const form = $('#infoForm');
  if (!state.cfg) { form.innerHTML = '<p class="muted wide">请先选择项目。</p>'; return; }
  const p = project() || {};
  const env = state.cfg.env || {};
  form.innerHTML = INFO.map((f, i) => {
    if (f.h) return `<h3>${f.h}</h3>`;
    const v = f.k ? state.cfg[f.k] : f.p ? p[f.p] : env[f.e];
    const val = esc(v ?? '');
    const input = f.area
      ? `<textarea data-i="${i}" rows="2">${val}</textarea>`
      : `<input data-i="${i}" type="${f.type || 'text'}" value="${val}">`;
    return `<label class="field ${f.wide ? 'wide' : ''}"><span>${f.label}${f.req ? ' <i>*</i>' : ''}</span>${input}</label>`;
  }).join('');
}

$('#saveInfo').onclick = async e => {
  e.preventDefault();
  if (!state.cfg) return;
  const p = project();
  state.cfg.env = state.cfg.env || {};
  const problems = [];
  $$('#infoForm [data-i]').forEach(el => {
    const f = INFO[+el.dataset.i];
    const v = el.value.trim();
    if (PLACEHOLDER.test(v)) problems.push(`${f.label} 含占位文字`);
    PLACEHOLDER.lastIndex = 0;
    if (f.max && v.replace(/\s/g, '').length > f.max) problems.push(`${f.label} 超过 ${f.max} 字`);
    if (f.k) state.cfg[f.k] = v; else if (f.p && p) p[f.p] = v; else if (f.e) state.cfg.env[f.e] = v;
  });
  await kit.saveConfig(state.repo, state.cfg);
  renderRepoCard();
  $('#saveInfoMsg').innerHTML = problems.length
    ? `<span class="warn">已保存，但：${esc(problems.join('；'))}</span>`
    : '<span class="ok">已保存</span>';
};

// ---------------------------------------------------------------- AI
function renderModules() {
  const p = project();
  if (!p || !(p.modules || []).length) { $('#modules').innerHTML = '<span class="muted">尚未分析。</span>'; return; }
  $('#modules').innerHTML = `
    <p><b>${esc(p.name)}</b>　${esc(p.summary || '')}</p>
    <ul class="modules">${p.modules.map(m => `<li><b>${esc(m[0])}</b>：${esc(m[1] || '')}</li>`).join('')}</ul>
    <p class="muted">源程序取材文件 ${(p.source_files || []).length} 个。</p>`;
}

$$('button[data-agent]').forEach(btn => btn.addEventListener('click', () => {
  const task = btn.dataset.agent;
  const extra = task === 'analyze'
    ? { split: $('#splitNote').value.trim(), note: $('#analyzeNote').value.trim() }
    : task === 'generate'
      ? { note: $('#generateNote').value.trim() }
      : { projectId: state.pid, note: $('#reviseNote').value.trim() };
  if (task === 'revise' && !extra.note) { $('#reviseNote').focus(); return; }
  const titles = { analyze: 'AI 分析项目', generate: 'AI 生成材料', revise: 'AI 修改说明书' };
  withRun(titles[task], async id => {
    const r = await kit.agent(id, task, state.repo, extra);
    state.cfg = await kit.loadConfig(state.repo);
    if (!state.cfg.projects.find(p => p.id === state.pid)) state.pid = state.cfg.projects[0]?.id;
    renderRepoCard(); renderModules(); renderProjectSelect();
    if (task === 'revise') await loadDoc();
    if (r?.ok) {
      if (task === 'generate' || task === 'revise') {
        const detection = task === 'revise' ? await reviewRevision(id) : await runZhusque(id);
        if (detection?.verified) markDone('generate');
      } else if (task === 'analyze') {
        markDone('analyze');
      }
    }
  });
}));
$$('button[data-stop]').forEach(b => b.addEventListener('click', () => kit.stopAgent()));

function markDone(view) {
  const a = $(`#nav a[data-view="${view}"]`);
  if (a) a.classList.add('done');
}

// ---------------------------------------------------------------- 脚本
$$('button[data-run]').forEach(btn => btn.addEventListener('click', () => {
  const task = btn.dataset.run;
  withRun(btn.textContent.trim(), async id => {
    const result = await kit.run(id, task, state.repo, state.pid);
    if (result?.code === 0 && task === 'docs') await runZhusque(id);
    if (['pdf', 'form', 'source', 'dashboard', 'manifest', 'docs'].includes(task)) refreshOutputs();
  });
}));

$('[data-shotdir]').onclick = () => state.repo && state.pid && kit.screenshotDir(state.repo, state.pid);
$('#fillCheck').onclick = () => withRun('校验申请表字段', id => kit.autofill(id, state.repo, state.pid, true));
$('#fillRun').onclick = () => {
  if (!confirm('将打开 Chrome 访问版权保护中心。请你本人登录；App 只填写并保存草稿，不会提交。继续？')) return;
  withRun('浏览器填表', id => kit.autofill(id, state.repo, state.pid, false));
};

// ---------------------------------------------------------------- 编辑器
function renderProjectSelect() {
  const sel = $('#editorProject');
  sel.innerHTML = (state.cfg?.projects || []).map(p => `<option value="${esc(p.id)}">${esc(p.name || p.id)}</option>`).join('');
  if (state.pid) sel.value = state.pid;
}
$('#editorProject').onchange = e => { state.pid = e.target.value; loadDoc(); renderModules(); };

const docRel = () => `${state.pid}/软件说明书.md`;
let dirty = false;

async function loadDoc() {
  if (!state.repo || !state.pid) return;
  const text = await kit.readFile(state.repo, docRel());
  $('#docText').value = text ?? '';
  $('#docText').placeholder = text == null ? '还没有说明书，请先在“AI 生成材料”中生成。' : '';
  dirty = false;
  renderPreview();
}

function renderPreview() {
  const text = $('#docText').value;
  const hits = text.match(PLACEHOLDER) || [];
  const badge = $('#phBadge');
  badge.textContent = hits.length ? `${hits.length} 处占位文字，无法生成 PDF` : (text ? '无占位文字' : '');
  badge.className = `badge ${hits.length ? 'bad' : text ? 'good' : ''}`;
  // 相对图片路径指向材料目录
  const base = `file://${encodeURI(`${state.repo}/soft-copyright-materials/${state.pid}/`)}`;
  let html = marked.parse(text.replace(PLACEHOLDER, m => `<mark>${m}</mark>`));
  html = html.replace(/<img src="(?!https?:|file:|data:)([^"]+)"/g, (_m, src) => `<img src="${base}${src}"`);
  $('#docPreview').innerHTML = html;
}

let previewTimer;
$('#docText').addEventListener('input', () => {
  dirty = true;
  clearTimeout(previewTimer);
  previewTimer = setTimeout(renderPreview, 200);
});
$('#saveDoc').onclick = async () => {
  if (!state.repo || !state.pid) return;
  await kit.writeFile(state.repo, docRel(), $('#docText').value);
  dirty = false;
  $('#nav a[data-view="generate"]')?.classList.remove('done');
  await refreshZhusqueStatus();
  $('#saveDoc').textContent = '已保存';
  setTimeout(() => { $('#saveDoc').textContent = '保存'; }, 1200);
};
$('#reloadDoc').onclick = () => { if (!dirty || confirm('放弃未保存的修改？')) loadDoc(); };
document.addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key === 's' && $('#view-editor').classList.contains('active')) {
    e.preventDefault(); $('#saveDoc').click();
  }
});

// ---------------------------------------------------------------- 产物
async function refreshOutputs() {
  if (!state.repo) return;
  const o = await kit.outputs(state.repo);
  const box = $('#outputs');
  box.className = 'outputs';
  box.innerHTML = o.projects.map(p => `
    <div><b>${esc(p.name || p.id)}</b>
      <button class="ghost small" data-open="${esc(p.dir)}">打开文件夹</button>
      <ul>
        <li>说明书 Markdown：${p.manual ? '<span class="ok">已生成</span>' : '<span class="muted">未生成</span>'}</li>
        <li>申请表字段：${p.form ? '<span class="ok">已生成</span>' : '<span class="muted">未生成</span>'}</li>
        ${p.pdfs.map(f => `<li>${esc(f)} <button class="ghost small" data-open="${esc(`${p.dir}/${f}`)}">打开</button></li>`).join('')
          || '<li class="muted">还没有 PDF</li>'}
      </ul></div>`).join('') + (o.missingInfo ? '<p class="warn">存在缺失信息，见 缺失信息清单.md，或在“基本信息”中补充。</p>' : '');
  box.querySelectorAll('[data-open]').forEach(b => { b.onclick = () => kit.openPath(b.dataset.open); });
  $('#board').src = o.dashboard ? `file://${encodeURI(o.dashboard)}?t=${Date.now()}` : 'about:blank';
  await refreshZhusqueStatus(o);
}

// ---------------------------------------------------------------- 设置
$('#settingsBtn').onclick = async () => {
  const s = await kit.getSettings();
  const f = $('#settings form');
  for (const k of ['model', 'apiKey', 'zhusqueApiKey', 'pythonPath', 'claudePath']) f.elements[k].value = s[k] || '';
  $('#settings').showModal();
};
$('#settings').addEventListener('close', async () => {
  if ($('#settings').returnValue !== 'save') return;
  const f = $('#settings form');
  await kit.setSettings(Object.fromEntries(['model', 'apiKey', 'zhusqueApiKey', 'pythonPath', 'claudePath'].map(k => [k, f.elements[k].value.trim()])));
  renderEnv();
});

$('#openZhusqueConsole').onclick = e => { e.preventDefault(); guideZhusqueKey(); };
$('#zhusqueKey').onclick = () => guideZhusqueKey();
$('#zhusqueWeb').onclick = () => openZhusqueWeb();
$('#zhusqueRun').onclick = () => withRun('朱雀检测 / 复检变化内容', id => reviewRevision(id));
$('#zhusqueExportRun').onclick = () => withRun('朱雀检测 / 复检变化内容', id => reviewRevision(id));
$('#zhusqueRewrite').onclick = () => withRun('按朱雀任务单修改并增量复核', id => rewriteZhusque(id));
$('#zhusqueExportRewrite').onclick = () => withRun('按朱雀任务单修改并增量复核', id => rewriteZhusque(id));
$('#zhusqueExportWeb').onclick = () => openZhusqueWeb();
$('#zhusqueDecline').onclick = () => withRun('记录拒绝朱雀检测', async id => {
  if (!state.repo || !state.pid) return { code: -1 };
  const ok = confirm('朱雀检测是终稿必需步骤，未检测的材料 AIGC 风险无法确认。\n'
    + '确定拒绝本次检测吗？需要分两次明确拒绝才会豁免。');
  if (!ok) return { code: 0, skipped: true };
  const result = await kit.run(id, 'zhusqueDecline', state.repo, state.pid);
  await refreshZhusqueStatus();
  return result;
});

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// ---------------------------------------------------------------- 启动
(async () => {
  renderEnv();
  const repo = store.get('repo');
  if (repo) { try { await openRepo(repo); } catch { /* 目录可能已删除 */ } }
  show(store.get('view') || 'project');
})();
