const contract = require('../../linguaflow/desktop_contract.json');
const forwardedMethods = new Set(Object.entries(contract).filter(([, spec]) => spec.forward).map(([name]) => name));
const rendererMethods = Object.fromEntries(Object.entries(contract).filter(([, spec]) => !spec.handler || spec.forward || spec.renderer));
function validateRequest(method, params) {
  const spec = Object.hasOwn(rendererMethods, method) && rendererMethods[method];
  if (!spec) throw new Error('不支持的桌面操作。');
  if (!params || typeof params !== 'object' || Array.isArray(params) || Object.keys(params).some(key => !Object.hasOwn(spec.params, key))) throw new Error('操作参数包含未知字段或不是对象。');
  for (const [key, field] of Object.entries(spec.params)) {
    if (!Object.hasOwn(params, key)) {
      if (!field.optional) throw new Error(`缺少操作参数：${key}`);
      continue;
    }
    const value = params[key];
    if (value === null && field.nullable) continue;
    const valid = typeof value === field.type && (field.type !== 'object' || value !== null && !Array.isArray(value)) && (field.type !== 'number' || Number.isFinite(value));
    if (!valid) throw new Error(`操作参数类型无效：${key}`);
  }
}
module.exports = { forwardedMethods, rendererMethods, validateRequest };
