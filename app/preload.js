const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('kit', {
  pickRepo: () => ipcRenderer.invoke('pick-repo'),
  loadConfig: repo => ipcRenderer.invoke('config:load', repo),
  saveConfig: (repo, cfg) => ipcRenderer.invoke('config:save', repo, cfg),
  outputs: repo => ipcRenderer.invoke('outputs', repo),
  readFile: (repo, rel) => ipcRenderer.invoke('file:read', repo, rel),
  writeFile: (repo, rel, text) => ipcRenderer.invoke('file:write', repo, rel, text),
  openPath: p => ipcRenderer.invoke('open-path', p),
  reveal: p => ipcRenderer.invoke('reveal', p),
  openExternal: url => ipcRenderer.invoke('open-external', url),
  getSettings: () => ipcRenderer.invoke('settings:get'),
  setSettings: patch => ipcRenderer.invoke('settings:set', patch),
  zhusqueStatus: () => ipcRenderer.invoke('zhusque:status'),
  installPython: id => ipcRenderer.invoke('install-python', id),
  run: (id, task, repo, pid) => ipcRenderer.invoke('run', id, task, repo, pid),
  autofill: (id, repo, pid, checkOnly) => ipcRenderer.invoke('autofill', id, repo, pid, checkOnly),
  screenshotDir: (repo, pid) => ipcRenderer.invoke('screenshot-dir', repo, pid),
  agent: (id, task, repo, extra) => ipcRenderer.invoke('agent:run', id, task, repo, extra),
  stopAgent: () => ipcRenderer.invoke('agent:stop'),
  onLog: fn => ipcRenderer.on('log', (_e, payload) => fn(payload)),
});
