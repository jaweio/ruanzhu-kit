#!/usr/bin/env node
/**
 * 软著 R11 自动填表脚本 — 使用真实 Chrome 会话
 *
 * 安装（一次性）：
 *   npm install playwright
 *   npx playwright install chromium
 *
 * 用法：
 *   node auto-fill.js                      # 使用同目录 config.json
 *   node auto-fill.js path/to/config.json  # 指定配置文件
 *   node auto-fill.js --check              # 只校验配置，不开浏览器
 *
 * config.json 由 application_form.py 生成，不要手工改；改 ruanzhu.config.json 后重跑。
 * 脚本使用你已登录的本机 Chrome Profile，无需重新登录。
 * 自动完成 5 步表单后【保存至草稿箱】即停，绝不点击「确认填报」——正式提交必须人工操作。
 */

const path = require('path');
const fs = require('fs');
const os = require('os');

// ── 配置 ────────────────────────────────────────────────────────────────────
const configArgument = process.argv.slice(2).find(arg => !arg.startsWith('--'));
const configPath = configArgument
  ? path.resolve(configArgument)
  : path.join(__dirname, 'config.json');

if (!fs.existsSync(configPath)) {
  console.error(`❌ 找不到配置文件: ${configPath}`);
  process.exit(1);
}

const cfg = JSON.parse(fs.readFileSync(configPath, 'utf8'));

// ── 运行前校验：有未填字段就不开浏览器，避免把占位符填进官网 ──────────────
const problems = [];
for (const [section, fields] of Object.entries(cfg)) {
  if (typeof fields !== 'object' || fields === null) continue;
  for (const [k, v] of Object.entries(fields)) {
    if (typeof v === 'string' && /【[^】]*】/.test(v)) problems.push(`${section}.${k} = ${v}`);
  }
}
const mainFn = cfg.step4_features?.mainFunction ?? '';
const mainLen = mainFn.replace(/\s/g, '').length;
if (mainLen < 500 || mainLen > 1300) problems.push(`step4_features.mainFunction 为 ${mainLen} 字，官网要求 500-1300 字`);
for (const key of ['programPdf', 'docPdf']) {
  const rel = cfg.step4_features?.[key];
  if (rel && !/【/.test(rel) && !fs.existsSync(path.resolve(path.dirname(configPath), rel))) {
    problems.push(`step4_features.${key} 找不到文件：${rel}`);
  }
}
if (problems.length) {
  console.error('❌ 配置未通过校验，已中止（没有打开浏览器）：');
  problems.forEach(p => console.error('   - ' + p));
  console.error('\n   修正 ruanzhu.config.json 后重跑：python3 scripts/application_form.py --config <配置>');
  process.exit(1);
}
console.log(`✅ 配置校验通过（主要功能 ${mainLen} 字）`);
if (process.argv.includes('--check')) process.exit(0);

function absPath(p) {
  return path.resolve(path.dirname(configPath), p);
}

// macOS Chrome 用户数据目录（使用已有 Profile，保留登录状态）
const CHROME_USER_DATA = path.join(
  os.homedir(),
  'Library/Application Support/Google/Chrome'
);

// ── Vue 响应式字段填写（核心方法）────────────────────────────────────────────
// 必须用 execCommand('insertText') 触发 Vue 双向绑定，直接赋值 .value 无效

async function fillTA(page, index, value) {
  await page.evaluate(({ index, value }) => {
    const el = document.querySelectorAll('textarea')[index];
    if (!el) return;
    el.focus(); el.select();
    document.execCommand('selectAll');
    document.execCommand('insertText', false, value);
  }, { index, value });
}

async function fillByLabel(page, labelText, value) {
  await page.evaluate(({ labelText, value }) => {
    const labels = Array.from(document.querySelectorAll('label,.el-form-item__label'));
    for (const lbl of labels) {
      if (lbl.textContent.trim().includes(labelText)) {
        const item = lbl.closest('.el-form-item') || lbl.parentElement;
        const el = item?.querySelector('input:not([type=hidden]):not([type=radio]):not([type=checkbox])');
        if (el) {
          el.focus(); el.select();
          document.execCommand('selectAll');
          document.execCommand('insertText', false, value);
          return true;
        }
      }
    }
    return false;
  }, { labelText, value });
}

async function clickBtn(page, text, timeout = 10000) {
  const btn = page.locator(`button:has-text("${text}")`).first();
  await btn.waitFor({ timeout });
  await btn.click();
  await page.waitForTimeout(800);
}

async function waitFor(page, text, timeout = 20000) {
  await page.locator(`text=${text}`).first().waitFor({ timeout });
}

// ── 主流程 ───────────────────────────────────────────────────────────────────
(async () => {
  let chromium;
  try {
    ({ chromium } = require('playwright'));
  } catch {
    console.error('❌ 未安装 playwright。先执行：npm install playwright && npx playwright install chromium');
    process.exit(1);
  }
  console.log('🚀 启动真实 Chrome（使用本机已登录会话）...');

  // 使用本机 Chrome Profile，保留所有登录态
  const context = await chromium.launchPersistentContext(CHROME_USER_DATA, {
    headless: false,
    channel: 'chrome',
    args: [
      '--start-maximized',
      '--disable-blink-features=AutomationControlled', // 避免网站检测到自动化
    ],
    ignoreDefaultArgs: ['--enable-automation'],
  });

  const page = await context.newPage();

  // ── 检查登录状态 ──────────────────────────────────────────────────────────
  console.log('🔐 检查登录状态...');
  await page.goto('https://register.ccopyright.com.cn/r11.html#/application', {
    waitUntil: 'domcontentloaded',
  });
  await page.waitForTimeout(2000);

  // 未登录时会跳转到登录页
  const currentUrl = page.url();
  if (currentUrl.includes('login')) {
    console.log('⚠️  未检测到登录状态，请在浏览器中完成登录（60秒内）...');
    await page.locator('text=用户中心').waitFor({ timeout: 60000 });
    // 登录后重新进入申请页
    await page.goto('https://register.ccopyright.com.cn/r11.html#/application');
    await page.waitForTimeout(1500);
  }

  console.log('✅ 已登录，开始自动填表...\n');

  // ── Step 1: 选择办理身份 ──────────────────────────────────────────────────
  console.log('📋 Step 1: 选择办理身份');

  await waitFor(page, '选择办理身份');

  const s1 = cfg.step1_identity || {};
  for (const val of [s1.applicantRole || '我是申请人', s1.applicantType || '企业法人',
                     s1.developType || '独立开发']) {
    await page.locator(`text=${val}`).first().click();
    await page.waitForTimeout(400);
    console.log(`   ・${val}`);
  }

  await clickBtn(page, '下一步');
  await waitFor(page, '软件申请信息');
  console.log('   ✅ 完成\n');

  // ── Step 2: 软件申请信息 ──────────────────────────────────────────────────
  console.log('📋 Step 2: 软件申请信息');
  const s2 = cfg.step2_basic;

  await fillByLabel(page, '软件全称', s2.softwareName);
  await fillByLabel(page, '软件简称', s2.shortName);
  await fillByLabel(page, '版本号',   s2.version);

  // 软件分类下拉
  const catTrigger = page.locator('.el-select').first();
  await catTrigger.click();
  await page.locator(`.el-select-dropdown__item:has-text("${s2.category || '应用软件'}")`).click();
  await page.waitForTimeout(300);

  // 开发完成日期
  await fillByLabel(page, '开发完成日期', s2.completionDate);
  await page.keyboard.press('Escape'); // 关闭日期选择器
  await page.waitForTimeout(300);

  // 发表状态
  if (!s2.published) {
    await page.locator('text=未发表').first().click();
  }

  // 著作权人：从已登录账户中读取（第一个企业法人）
  // 通常系统会自动带入，无需手动填写

  await clickBtn(page, '下一步');
  await waitFor(page, '软件开发信息');
  console.log('   ✅ 完成\n');

  // ── Step 3: 软件开发信息 ──────────────────────────────────────────────────
  console.log('📋 Step 3: 软件开发信息');
  const s3 = cfg.step3_dev;

  // textarea 顺序由页面决定，通过逐个 focus 确保准确
  const taMap = [
    [0, s3.devHardware,   '开发硬件环境'],
    [1, s3.runHardware,   '运行硬件环境'],
    [2, s3.devOS,         '开发操作系统'],
    [3, s3.devTools,      '开发工具'],
    [4, s3.runOS,         '运行平台/OS'],
    [5, s3.runSupport,    '运行支撑环境'],
  ];
  for (const [idx, val, name] of taMap) {
    await fillTA(page, idx, val);
    console.log(`   ・${name}: ${val.substring(0, 30)}...`);
  }

  // 编程语言勾选
  await page.locator(`button:has-text("${s3.language}")`).first().click();
  await page.waitForTimeout(300);
  await fillTA(page, 6, s3.languageOther);

  // 源程序量（number input）
  await page.evaluate((lines) => {
    const inp = Array.from(document.querySelectorAll('input'))
      .find(i => i.placeholder?.includes('请输入') && i.type !== 'hidden');
    if (inp) {
      inp.focus(); inp.select();
      document.execCommand('selectAll');
      document.execCommand('insertText', false, lines);
    }
  }, s3.sourceLines);

  await clickBtn(page, '下一步');
  await waitFor(page, '软件功能与特点');
  console.log('   ✅ 完成\n');

  // ── Step 4: 软件功能与特点 ────────────────────────────────────────────────
  console.log('📋 Step 4: 软件功能与特点');
  const s4 = cfg.step4_features;

  await fillTA(page, 0, s4.devPurpose);
  console.log(`   ・开发目的: ${s4.devPurpose}`);

  await fillTA(page, 1, s4.targetIndustry);
  console.log(`   ・面向领域: ${s4.targetIndustry}`);

  await fillTA(page, 2, s4.mainFunction);
  console.log(`   ・主要功能: ${s4.mainFunction.length} 字`);

  // 技术特点标签
  await page.locator(`button:has-text("${s4.techFeatureTag}")`).first().click();
  await page.waitForTimeout(300);
  await fillTA(page, 3, s4.techFeatureText);
  console.log(`   ・技术特点: ${s4.techFeatureText}`);

  // 上传程序鉴别材料
  const programPdf = absPath(s4.programPdf);
  const docPdf     = absPath(s4.docPdf);

  if (!fs.existsSync(programPdf)) {
    console.error(`❌ 程序鉴别材料不存在: ${programPdf}`);
    process.exit(1);
  }
  if (!fs.existsSync(docPdf)) {
    console.error(`❌ 文档鉴别材料不存在: ${docPdf}`);
    process.exit(1);
  }

  console.log('   📎 上传程序鉴别材料 PDF...');
  const fileInputs = page.locator('input[type="file"]');
  await fileInputs.nth(0).setInputFiles(programPdf);
  await page.waitForTimeout(2500);

  console.log('   📎 上传文档鉴别材料 PDF...');
  await fileInputs.nth(1).setInputFiles(docPdf);
  await page.waitForTimeout(2500);

  await clickBtn(page, '下一步');
  await waitFor(page, '确认信息');
  console.log('   ✅ 完成\n');

  // ── Step 5: 确认并保存草稿 ────────────────────────────────────────────────
  console.log('📋 Step 5: 确认信息 → 保存至草稿箱');
  await page.waitForTimeout(2000); // 等确认页完全渲染

  const saveBtn = page.locator('button:has-text("保存至草稿箱")');
  await saveBtn.waitFor({ timeout: 10000 });
  await saveBtn.click();

  // 等待保存完成（加载动画出现→消失）
  await page.locator('text=保存中').waitFor({ state: 'visible', timeout: 5000 }).catch(() => {});
  await page.locator('text=保存中').waitFor({ state: 'hidden',  timeout: 20000 }).catch(() => {});

  await page.waitForTimeout(1000);
  console.log('\n🎉 草稿已保存（脚本到此为止，不会提交）。');
  console.log('   请在浏览器中逐项核对确认信息：软件全称、版本号、著作权人、开发完成日期、');
  console.log('   源程序量、两份 PDF 是否正确，无误后【人工点击「确认填报」】正式提交。\n');

  // 浏览器保持打开，供用户检查
})();
