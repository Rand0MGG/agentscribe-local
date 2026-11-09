"""Shared desktop method contract; domain-specific checks stay with their owners."""
import json
import math
from pathlib import Path

CONTRACT = json.loads(Path(__file__).with_name('desktop_contract.json').read_text(encoding='utf-8'))


def validate_params(method, params):
    spec = CONTRACT[method]
    fields = spec.get('backendParams', spec['params'])
    if not isinstance(params, dict) or params.keys() - fields.keys():
        raise ValueError('操作参数包含未知字段或不是对象。')
    for name, field in fields.items():
        if name not in params:
            if not field.get('optional'):
                raise ValueError(f'缺少操作参数：{name}')
            continue
        value = params[name]
        if value is None and field.get('nullable'):
            continue
        valid = {'string': lambda: isinstance(value, str),
                 'boolean': lambda: type(value) is bool,
                 'number': lambda: type(value) in (int, float) and math.isfinite(value),
                 'object': lambda: isinstance(value, dict)}[field['type']]()
        if not valid:
            raise ValueError(f'操作参数类型无效：{name}')
