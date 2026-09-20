"""Validate editable recording documents before they reach desktop controls."""
import math

from .core import Caption


def read_recording_document(data):
    try:
        if not isinstance(data, dict):
            raise ValueError('顶层必须是对象')
        session, settings, rows = data['session'], data['settings'], data['captions']
        if not isinstance(session, dict) or not isinstance(settings, dict) or not isinstance(rows, list):
            raise ValueError('session/settings 必须是对象，captions 必须是列表')
        for key in ('id', 'name', 'folder', 'created', 'state'):
            if not isinstance(session[key], str):
                raise ValueError(f'session.{key} 必须是文字')
        if 'translate' in settings and not isinstance(settings['translate'], bool):
            raise ValueError('settings.translate 必须是布尔值')
        captions, identifiers = [], set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('字幕条目必须是对象')
            caption = Caption(**row)
            for key in ('id', 'revision'):
                if type(getattr(caption, key)) is not int or getattr(caption, key) < 0:
                    raise ValueError(f'字幕 {key} 必须是非负整数')
            if caption.id in identifiers:
                raise ValueError('字幕标识重复')
            identifiers.add(caption.id)
            for key in ('start', 'end'):
                value = getattr(caption, key)
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError('字幕时间无效')
            if caption.end < caption.start:
                raise ValueError('字幕结束时间早于开始时间')
            for key in ('source', 'language', 'translation', 'error', 'stable_source', 'boundary_reason'):
                if not isinstance(getattr(caption, key), str):
                    raise ValueError(f'字幕 {key} 必须是文字')
            if any(type(getattr(caption, key)) is not bool for key in ('final', 'ready')):
                raise ValueError('字幕状态必须是布尔值')
            captions.append(caption)
        return data, captions
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f'录音元数据格式无效：{exc}。原文件未修改，请检查 session.json 或从备份恢复。') from exc
