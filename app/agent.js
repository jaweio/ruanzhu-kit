// 用本机 Claude Code（Agent SDK）按 ruanzhu-kit 的 SKILL.md 执行需要理解代码和写作的步骤。
const fs = require('fs');
const path = require('path');

const { checkBash } = require('./bash-policy');

const READ_ONLY = ['Read', 'Glob', 'Grep', 'TodoWrite'];

function appRules({ kit, output, python }) {
  return `
# 运行环境（软著工具箱桌面 App）
- 你在桌面 App 中为用户生成软著材料。当前工作目录就是用户的软件项目源码目录。
- ruanzhu-kit 的脚本位于 ${kit}/scripts，一律这样调用：\`${python} ${kit}/scripts/<脚本> ...\`。
- 所有产物只写入 ./${output}/ 目录；不得修改项目源代码，不得删除文件，不得启动项目，不得联网，不得安装依赖。
- Bash 只放行白名单：\`${python} ${kit}/scripts/<材料脚本>\`，以及 ls/cat/head/tail/wc/grep/rg/find/git status|log|diff|show 等只读命令；不能用重定向、\`python -c\`、\`sed -i\` 写文件。写文件请用 Write/Edit，且只能写材料目录。
- 跳过 SKILL.md 中“检查更新”一步（App 自行管理版本）。不要执行 Step 7–9（PDF、填表、提交由 App 界面完成）。
- 用户已在 App 中填写的字段（著作权人、开发完成日期、env 环境信息、软件名称/简称/版本等非空值）必须原样保留。
- 事实只能来自源码和配置。查不到的字段保持空字符串；任何文件中都不得写入【待填写】【待核验】【截图预留】等占位文字，也不得编造。
- 默认只做一份软著（黄金原则 1），除非用户在任务中明确要求拆分。
- 最后用简短中文汇报：做了什么、关键结果（模块、取材文件数、AIGC 分数等）、仍需用户补充的信息。
`;
}

const TASKS = {
  analyze: ({ kit, output, python }, extra) => `
执行 ruanzhu-kit 的 Step 1–3（分析项目 → 拆分决策 → 生成配置）：
1. 阅读项目结构、README/设计文档和核心源码，理解真实功能。
2. 运行 \`${python} ${kit}/scripts/manual_spec.py --repo . --out ${output}/说明书素材.json\` 抽取说明书素材。
3. 更新 ${output}/ruanzhu.config.json：
   - projects 保留一份（${extra?.split ? `用户要求拆分：${extra.split}` : '不拆分'}）；name 为空时，按真实核心功能拟定软件全称（像真实产品名，见 SKILL.md 命名规范），并把 id 改为“01-<软件全称>”；name 已由用户填写时保留，只让 id 与之对应。
   - 依据源码填写 short_name、document_kind、artifact_label、position、summary、scope、architecture_overview、data_flow、tech_stack、modules（[[模块名, 真实功能说明]]）、users、source_files（约 60 页所需的核心自有源码，排除第三方/生成代码）、source_map、dev_purpose、target_industry、tech_feature_text。
   - env 中能从代码或配置确认的项（run_support、dev_tools 等）可以补充，不能确认的留空。
4. 运行 \`${python} ${kit}/scripts/copyright_check.py --config ${output}/ruanzhu.config.json --repo . --skip materials\` 做版权预检，按 SKILL.md Step 5 处理 self_open_source / self_aliases。
${extra?.note ? `\n用户补充说明：${extra.note}\n` : ''}`,

  generate: ({ kit, output, python }, extra) => `
执行 ruanzhu-kit 的 Step 4–6（生成材料 → 版权清除 → AIGC 去痕），配置文件为 ${output}/ruanzhu.config.json：
1. \`${python} ${kit}/scripts/generate_docs.py --config ${output}/ruanzhu.config.json\`
2. \`${python} ${kit}/scripts/generate_source_docx.py --config ${output}/ruanzhu.config.json --repo . --preview\`
3. 按 SKILL.md 4.1/4.2 的文风要求，对照源码充实每份 软件说明书.md 的功能模块、使用指南等章节（只写源码能证实的内容）。
4. 按 Step 5 运行 oss_scrub / copyright_check，确保材料零开源痕迹。
5. 按 Step 6：aigc_check → aigc_rewrite --apply → 按 AIGC改写任务单.md 语义改写 → \`aigc_check ... --fail-above 35\`，最多 3 轮。
6. 确认 软件说明书.md 中没有任何占位文字。
${extra?.note ? `\n用户补充说明：${extra.note}\n` : ''}`,

  revise: ({ output }, extra) => `
按用户意见修改 ${output}/${extra.projectId}/软件说明书.md（只改这份说明书，事实必须来自源码）：
${extra.note}
改完后运行 aigc_check 复测该目录，并汇报改动和分数。`,
};

// 去掉从父进程继承的 Claude/Anthropic 变量（例如在另一个 Claude Code 会话里启动 App 时），
// 让 Agent 只使用本机 claude 的登录或设置里的 API Key
function cleanEnv(env) {
  return Object.fromEntries(Object.entries(env).filter(([k]) =>
    !/^(ANTHROPIC_|CLAUDE|USE_(STAGING|LOCAL)_OAUTH$|AI_AGENT$)/.test(k)));
}

function describeTool(name, input = {}) {
  if (name === 'Bash') return `$ ${String(input.command || '').slice(0, 300)}`;
  if (input.file_path) return `${name} ${input.file_path}`;
  if (input.pattern) return `${name} ${input.pattern}`;
  return name;
}

async function runAgent({ task, repo, extra, kit, output, python, claude, apiKey, model, env, abort, onEvent }) {
  if (!TASKS[task]) throw new Error(`未知 AI 任务：${task}`);
  const { query } = await import('@anthropic-ai/claude-agent-sdk');
  const skill = fs.readFileSync(path.join(kit, 'SKILL.md'), 'utf8');
  const ctx = { kit, output, python };
  const outRoot = path.resolve(repo, output) + path.sep;

  // 写文件只允许落在材料目录；Bash 走白名单（bash-policy.js）；其余工具（联网等）一律拒绝
  const canUseTool = async (toolName, input) => {
    if (['Write', 'Edit', 'MultiEdit', 'NotebookEdit'].includes(toolName)) {
      const target = path.resolve(repo, String(input.file_path || input.notebook_path || ''));
      return target.startsWith(outRoot)
        ? { behavior: 'allow', updatedInput: input }
        : { behavior: 'deny', message: `只能写入 ${output}/ 目录，不能修改 ${target}` };
    }
    if (toolName === 'Bash') {
      const cmd = String(input.command || '');
      const reason = checkBash(cmd, { kit, repo, outRoot, python });
      return reason
        ? { behavior: 'deny', message: `App 禁止执行该命令（${reason}）：${cmd.slice(0, 120)}` }
        : { behavior: 'allow', updatedInput: input };
    }
    return { behavior: 'deny', message: `App 中不允许使用 ${toolName}` };
  };

  const q = query({
    prompt: TASKS[task](ctx, extra),
    options: {
      cwd: repo,
      additionalDirectories: [kit],
      pathToClaudeCodeExecutable: claude,
      systemPrompt: { type: 'preset', preset: 'claude_code', append: `${appRules(ctx)}\n\n# ruanzhu-kit SKILL.md\n\n${skill}` },
      settingSources: [], // 不加载用户自己的 CLAUDE.md / hooks，保证流程可复现
      allowedTools: READ_ONLY,
      permissionMode: 'default',
      canUseTool,
      ...(model ? { model } : {}),
      maxTurns: 300,
      abortController: abort,
      env: { ...cleanEnv(env), ...(apiKey ? { ANTHROPIC_API_KEY: apiKey } : {}) },
    },
  });

  let final = null;
  for await (const m of q) {
    if (m.type === 'assistant') {
      for (const b of m.message?.content || []) {
        if (b.type === 'text' && b.text.trim()) onEvent(`${b.text.trim()}\n`, 'ai');
        else if (b.type === 'tool_use') onEvent(`· ${describeTool(b.name, b.input)}\n`, 'tool');
      }
    } else if (m.type === 'result') {
      final = m;
    }
  }
  if (!final) return { ok: false };
  const cost = typeof final.total_cost_usd === 'number' ? `，约 $${final.total_cost_usd.toFixed(2)}` : '';
  if (final.subtype === 'success' && !final.is_error) {
    onEvent(`\n✓ 完成（${Math.round(final.duration_ms / 1000)} 秒${cost}）\n`, 'ok');
    return { ok: true, result: final.result };
  }
  onEvent(`\n✗ 未完成：${final.subtype}${cost}\n`, 'err');
  return { ok: false };
}

module.exports = { runAgent, cleanEnv };
