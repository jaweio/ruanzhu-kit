const path = require('path');

function finalizeTask(projectDir) {
  return ['zhusque_check.py', ['finalize', projectDir, '--allow-upload', '--channel', 'auto',
    '--report', path.join(projectDir, '朱雀检测报告.md')]];
}

function browserRuntimeEnv(execPath, appDir) {
  return {
    RUANZHU_NODE_EXECUTABLE: execPath,
    ELECTRON_RUN_AS_NODE: '1',
    NODE_PATH: path.join(appDir, 'node_modules'),
  };
}

// Python 校验正文指纹和覆盖范围；App 只接受明确通过且风险值有效的结果。
function verifiedStatus(status = {}) {
  const risk = status.risk_ratio;
  const threshold = status.max_risk_ratio;
  const ratio = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;
  return {
    ...status,
    checked: status.checked === true && status.content_match === true
      && status.coverage_complete === true && ratio(risk) && ratio(threshold) && risk <= threshold,
  };
}

function canRewrite(status = {}, taskExists = false) {
  const risk = status.risk_ratio;
  const threshold = status.max_risk_ratio;
  return taskExists && status.content_match === true && status.coverage_complete === true
    && typeof risk === 'number' && Number.isFinite(risk) && risk >= 0 && risk <= 1
    && typeof threshold === 'number' && Number.isFinite(threshold) && threshold >= 0 && threshold <= 1
    && risk > threshold;
}

module.exports = { finalizeTask, browserRuntimeEnv, verifiedStatus, canRewrite };
