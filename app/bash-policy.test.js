const test = require('node:test');
const assert = require('node:assert');
const path = require('path');
const { checkBash } = require('./bash-policy');

const kit = '/opt/kit';
const repo = '/work/proj';
const ctx = { kit, repo, outRoot: path.join(repo, 'soft-copyright-materials') + path.sep, python: '/usr/local/bin/python3' };
const allowed = cmd => assert.strictEqual(checkBash(cmd, ctx), null, cmd);
const denied = cmd => assert.notStrictEqual(checkBash(cmd, ctx), null, cmd);

test('放行材料脚本和只读命令', () => {
  allowed('/usr/local/bin/python3 /opt/kit/scripts/manual_spec.py --repo . --out soft-copyright-materials/说明书素材.json');
  allowed('python3 /opt/kit/scripts/aigc_check.py soft-copyright-materials/01-x --report "soft-copyright-materials/01-x/AIGC检测报告.md" --fail-above 35');
  allowed('python3 /opt/kit/scripts/oss_scrub.py --config soft-copyright-materials/ruanzhu.config.json --apply');
  allowed('ls -la src && cat README.md | head -50');
  allowed("grep -rn 'router|route' src 2>/dev/null | wc -l");
  allowed('find src -name "*.ts" -type f | sort');
  allowed('git log --oneline -5; git status --short');
  allowed('rg -n "useState" src 2>&1');
});

test('拒绝写文件、执行任意代码和联网', () => {
  denied('rm -rf src');
  denied('python3 -c "open(\'src/a.ts\',\'w\').write(\'\')"');
  denied('python3 /opt/kit/scripts/zhusque_check.py finalize soft-copyright-materials/01-x --allow-upload');
  denied('python3 /opt/kit/scripts/project_runtime.py start --repo . --allow-run');
  denied('python3 /opt/kit/scripts/../../tmp/evil.py');
  denied('python3 /opt/kit/scripts/manual_spec.py --repo . --out src/hack.json');
  denied('python3 /opt/kit/scripts/manual_spec.py --repo . --out=../elsewhere.json');
  denied('python3 /opt/kit/scripts/dashboard.py --config c.json --jev --allow-upload');
  denied('cat a > src/b.ts');
  denied('echo hi >> README.md');
  denied('sed -i s/a/b/ src/a.ts');
  denied('tee src/a.ts');
  denied('cp a b');
  denied('curl https://example.com');
  denied('find . -name "*.ts" -delete');
  denied('find . -exec rm {} \\;');
  denied('sort -o src/a.ts src/a.ts');
  denied('rg --pre ./x foo');
  denied('git push');
  denied('git diff --output=src/a.ts');
  denied('echo $(rm -rf /)');
  denied('echo `id`');
  denied('ls & rm x');
  denied('(cd src && ls)');
  denied('FOO=1 python3 /opt/kit/scripts/aigc_check.py x');
  denied('bash -c "ls"');
  denied('node -e "1"');
  denied('ls\nrm -rf src');
});
