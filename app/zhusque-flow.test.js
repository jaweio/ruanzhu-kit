const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { finalizeTask, browserRuntimeEnv, verifiedStatus, canRewrite } = require('./zhusque-flow');

test('App 检测使用自动渠道和默认增量缓存，不隐含强制全量', () => {
  const [script, args] = finalizeTask('/materials/01-中文说明书');
  assert.equal(script, 'zhusque_check.py');
  assert.deepEqual(args.slice(0, 5), ['finalize', '/materials/01-中文说明书', '--allow-upload', '--channel', 'auto']);
  assert.equal(args.includes('--no-cache'), false);
});

test('Python 子进程可使用 Electron 自带 Node 和 App Playwright', () => {
  assert.deepEqual(browserRuntimeEnv('/App/Electron', '/App/Resources/app'), {
    RUANZHU_NODE_EXECUTABLE: '/App/Electron',
    ELECTRON_RUN_AS_NODE: '1',
    NODE_PATH: path.join('/App/Resources/app', 'node_modules'),
  });
});

test('仅完整、内容一致且风险符合阈值的检测可标记完成', () => {
  const pass = { checked: true, content_match: true, coverage_complete: true, risk_ratio: 0.15, max_risk_ratio: 0.2 };
  assert.equal(verifiedStatus(pass).checked, true);
  assert.equal(verifiedStatus({ ...pass, risk_ratio: 0.2 }).checked, true);
  for (const update of [
    { checked: false }, { content_match: false }, { coverage_complete: false },
    { risk_ratio: 0.21 }, { risk_ratio: null }, { risk_ratio: NaN },
    { risk_ratio: -1 }, { max_risk_ratio: 2 }, { max_risk_ratio: undefined },
  ]) assert.equal(verifiedStatus({ ...pass, ...update }).checked, false, JSON.stringify(update));
  assert.equal(verifiedStatus({ report: true, marker: true }).checked, false);
  assert.equal(verifiedStatus().checked, false);
});

test('改写入口只接收当前全文完整检测的高风险任务单', () => {
  const highRisk = { content_match: true, coverage_complete: true, risk_ratio: 0.4, max_risk_ratio: 0.2 };
  assert.equal(canRewrite(highRisk, true), true);
  assert.equal(canRewrite(highRisk, false), false);
  for (const update of [
    { content_match: false }, { coverage_complete: false }, { risk_ratio: null },
    { risk_ratio: 0.1 }, { max_risk_ratio: NaN },
  ]) assert.equal(canRewrite({ ...highRisk, ...update }, true), false);
});

// 执行真实 renderer 函数，避免“无 Key 被提前跳过”再次进入流程。
function rendererRunFixture({ configured = false, code = 0, checked = true } = {}) {
  const source = fs.readFileSync(path.join(__dirname, 'renderer/app.js'), 'utf8');
  const functionSource = source.slice(source.indexOf('async function runZhusque('), source.indexOf("$('#installPy').onclick"));
  const calls = [];
  const messages = [];
  const nav = { classList: { toggle: (_name, value) => { nav.done = value; } } };
  const context = vm.createContext({
    state: { repo: '/project', pid: '01-test' },
    kit: {
      zhusqueStatus: async () => ({ configured }),
      run: async (...args) => { calls.push(args); return { code }; },
    },
    refreshZhusqueStatus: async () => ({ configured, current: { checked } }),
    logEl: { appendChild: item => messages.push(item.textContent) },
    document: { createElement: () => ({}) },
    $: () => nav,
    confirm: () => { throw new Error('无 Key 不应弹窗并跳过检测'); },
  });
  vm.runInContext(functionSource, context);
  return { run: () => context.runZhusque('test-run'), calls, messages, nav };
}

test('未配置 Key 仍提交自动渠道检测任务，成功后验证正文状态', async () => {
  const fixture = rendererRunFixture();
  const result = await fixture.run();
  assert.deepEqual(fixture.calls, [['test-run', 'zhusque', '/project', '01-test']]);
  assert.equal(result.verified, true);
  assert.equal(result.skipped, undefined);
  assert.equal(fixture.nav.done, true);
});

test('退出成功但正文未通过，以及网页受阻，都保持待复核', async () => {
  for (const setup of [{ code: 0, checked: false }, { code: 2, checked: true }]) {
    const fixture = rendererRunFixture(setup);
    assert.equal((await fixture.run()).verified, false);
    assert.equal(fixture.nav.done, false);
    assert.ok(fixture.messages.some(message => message.includes('材料仍待复核')));
  }
});

test('按任务单修改先检查新鲜完整结果，完成一轮后仅发起一次增量复检', async () => {
  const source = fs.readFileSync(path.join(__dirname, 'renderer/app.js'), 'utf8');
  const functionSource = source.slice(source.indexOf('async function rewriteZhusque('), source.indexOf("$('#installPy').onclick"));
  for (const { allowed, dirty } of [{ allowed: false, dirty: false }, { allowed: true, dirty: true }, { allowed: true, dirty: false }]) {
    const calls = [];
    const context = vm.createContext({
      dirty,
      state: { repo: '/project', pid: '01-test' },
      kit: {
        outputs: async () => ({ projects: [{ id: '01-test', zhusque: { can_rewrite: allowed } }] }),
        agent: async (...args) => { calls.push(['agent', ...args]); return { ok: true }; },
      },
      logEl: { appendChild: () => {} },
      document: { createElement: () => ({}) },
      loadDoc: async () => calls.push(['reload']),
      reviewRevision: async id => { calls.push(['detect', id]); return { verified: true }; },
    });
    vm.runInContext(functionSource, context);
    const result = await context.rewriteZhusque('rewrite-run');
    if (!allowed || dirty) {
      assert.equal(result.pending, true);
      assert.equal(calls.length, 0);
    } else {
      assert.deepEqual(calls.map(call => call[0]), ['agent', 'reload', 'detect']);
      assert.equal(calls[0][2], 'revise');
      assert.equal(calls[0][4].zhusqueOnly, true);
      assert.equal(calls[0][4].projectId, '01-test');
      assert.equal(result.verified, true);
    }
  }
});

test('修改后先同步已有正式 PDF；导出失败不能开始检测或显示通过', async () => {
  const source = fs.readFileSync(path.join(__dirname, 'renderer/app.js'), 'utf8');
  const functionSource = source.slice(source.indexOf('async function reviewRevision('), source.indexOf('async function rewriteZhusque('));
  for (const setup of [
    { pdfs: [], code: 0, expected: ['detect'], verified: true },
    { pdfs: ['提交材料/软件说明.pdf'], code: 0, expected: ['pdf', 'detect'], verified: true },
    { pdfs: ['提交材料/软件说明.pdf'], code: 1, expected: ['pdf', 'pending'], verified: false },
  ]) {
    const calls = [];
    const context = vm.createContext({
      dirty: false,
      state: { repo: '/project', pid: '01-test' },
      kit: {
        outputs: async () => ({ projects: [{ id: '01-test', pdfs: setup.pdfs }] }),
        run: async (_id, task) => { calls.push(task); return { code: setup.code }; },
      },
      logEl: { appendChild: () => {} },
      document: { createElement: () => ({}) },
      $: () => ({ classList: { remove: () => calls.push('pending') } }),
      refreshZhusqueStatus: async () => {},
      runZhusque: async () => { calls.push('detect'); return { verified: true }; },
    });
    vm.runInContext(functionSource, context);
    assert.equal((await context.reviewRevision('review-run')).verified, setup.verified);
    assert.deepEqual(calls, setup.expected);
  }
});

test('检测期间禁用朱雀操作，重复点击只执行一个任务', async () => {
  const source = fs.readFileSync(path.join(__dirname, 'renderer/app.js'), 'utf8');
  const functionSource = source.slice(source.indexOf('async function withRun('), source.indexOf('// ---------------------------------------------------------------- 项目'));
  const buttons = Object.fromEntries(['#zhusqueRun', '#zhusqueExportRun', '#zhusqueRewrite', '#zhusqueExportRewrite', '#zhusqueDecline'].map(id => [id, { disabled: false }]));
  const context = vm.createContext({
    state: { repo: '/project', busy: false },
    currentRun: null,
    logEl: { textContent: '' },
    $: () => ({ classList: { remove: () => {} } }),
    $$: selector => selector.split(',').map(id => buttons[id]).filter(Boolean),
    refreshZhusqueStatus: async () => {},
  });
  vm.runInContext(functionSource, context);
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  let executions = 0;
  const first = context.withRun('首次', async () => { executions += 1; await pending; return 'done'; });
  assert.equal(context.state.busy, true);
  assert.ok(Object.values(buttons).every(button => button.disabled));
  assert.equal(await context.withRun('重复点击', async () => { executions += 1; }), null);
  assert.equal(executions, 1);
  release();
  assert.equal(await first, 'done');
  assert.equal(context.state.busy, false);
  assert.equal(buttons['#zhusqueRun'].disabled, false);
  assert.equal(buttons['#zhusqueExportRun'].disabled, false);
});

test('生成页和导出页的手动复检按钮均先同步正式 PDF', async () => {
  const source = fs.readFileSync(path.join(__dirname, 'renderer/app.js'), 'utf8');
  const handlers = source.split('\n').filter(line => /^\$\('#zhusque(?:Export)?Run'\)\.onclick/.test(line)).join('\n');
  const buttons = {};
  const calls = [];
  const context = vm.createContext({
    $: selector => buttons[selector] ||= {},
    withRun: async (_title, fn) => fn('manual-review'),
    reviewRevision: async id => calls.push(id),
    runZhusque: () => { throw new Error('手动复检不能跳过 PDF 同步流程'); },
  });
  vm.runInContext(handlers, context);
  await buttons['#zhusqueRun'].onclick();
  await buttons['#zhusqueExportRun'].onclick();
  assert.deepEqual(calls, ['manual-review', 'manual-review']);
});
