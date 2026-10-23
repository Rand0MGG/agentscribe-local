const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('agentScribe', Object.freeze({
  request: (method, params = {}) => ipcRenderer.invoke('desktop:request', { method, params }),
  subscribe: listener => {
    const handler = (_event, value) => listener(value);
    ipcRenderer.on('desktop:event', handler);
    return () => ipcRenderer.removeListener('desktop:event', handler);
  },
}));
