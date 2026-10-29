"""Atomic JSON preferences, with read-only migration of the former Qt stores."""
import base64
import configparser
import json
import os
import plistlib
import sys
import tempfile
from contextlib import contextmanager
from enum import IntEnum
from pathlib import Path


class SettingsStore:
    class Format(IntEnum):
        NativeFormat = 0
        IniFormat = 1

    class Status(IntEnum):
        NoError = 0
        AccessError = 1
        FormatError = 2

    def __init__(self, path='LinguaFlow', format='LocalCaptions'):
        self._status = self.Status.NoError
        self.dirty = {}
        self.removed = set()
        self.batching = 0
        registry = str(path).strip('\\').casefold() == r'HKEY_CURRENT_USER\Software\LinguaFlow\LocalCaptions'.casefold()
        if isinstance(format, str) or (sys.platform == 'win32' and format == 0 and registry):
            home = Path.home()
            directory = (home / 'Library/Application Support/AgentScribe' if sys.platform == 'darwin' else
                         Path(os.environ.get('LOCALAPPDATA', home / '.local/share')) / 'AgentScribe')
            self.path = directory / 'preferences.json'
            legacy = home / 'Library/Preferences/com.LinguaFlow.LocalCaptions.plist'
            self.values = self._read_json() if self.path.exists() else self._native_legacy(legacy)
        else:
            original = Path(path).expanduser()
            self.path = original if original.suffix == '.json' else original.with_name(original.name + '.backend.json')
            if self.path.exists():
                self.values = self._read_json()
            elif original.is_file():
                self.values = self._read_legacy(original)
            else:
                self.values = {}

    def _read_json(self):
        value = json.loads(self.path.read_text(encoding='utf-8'), object_hook=self._decode)
        if not isinstance(value, dict):
            raise ValueError('设置文件格式无效；原文件已保留。')
        return value

    @staticmethod
    def _decode(value):
        if set(value) == {'$bytes'}:
            return base64.b64decode(value['$bytes'], validate=True)
        return value

    @staticmethod
    def _encode(value):
        if isinstance(value, bytes):
            return {'$bytes': base64.b64encode(value).decode('ascii')}
        raise TypeError('Unsupported preference value')

    @staticmethod
    def _native_legacy(path):
        if sys.platform == 'darwin':
            return plistlib.loads(path.read_bytes()) if path.is_file() else {}
        if sys.platform == 'win32':
            import winreg
            result = {}
            try:
                def read(key, prefix=''):
                    groups, count, _ = winreg.QueryInfoKey(key)
                    for index in range(count):
                        name, value, kind = winreg.EnumValue(key, index)
                        if kind in (winreg.REG_BINARY, winreg.REG_NONE):
                            value = value.decode('utf-16-le')
                        result[prefix + name] = SettingsStore._qt_value(value)
                    for index in range(groups):
                        name = winreg.EnumKey(key, index)
                        with winreg.OpenKey(key, name) as child:
                            read(child, prefix + name + '/')
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\LinguaFlow\LocalCaptions') as key:
                    read(key)
            except FileNotFoundError:
                pass
            return result
        legacy = Path.home() / '.config/LinguaFlow/LocalCaptions.conf'
        return SettingsStore._read_legacy(legacy) if legacy.is_file() else {}

    @staticmethod
    def _qt_value(value):
        if isinstance(value, list):
            return [SettingsStore._qt_value(item) for item in value]
        if isinstance(value, str):
            if value.startswith('@ByteArray(') and value.endswith(')'):
                return value[11:-1].encode('latin1')
            if value.startswith('@String(') and value.endswith(')'):
                return value[8:-1]
            if value.startswith('@@'):
                return value[1:]
        return value

    @staticmethod
    def _read_legacy(path):
        if path.suffix == '.plist':
            return plistlib.loads(path.read_bytes())
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.optionxform = str
        parser.read_string(path.read_text(encoding='utf-8-sig'))
        result = {}
        for section in parser.sections():
            for key, value in parser.items(section):
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                # QSettings INI escapes backslashes, newlines, and binary geometry.
                import re
                def unescape(match):
                    token = match[1]
                    return chr(int(token[1:], 16)) if token.startswith('x') else {
                        'n': '\n', 'r': '\r', 't': '\t', '0': '\0'}.get(token, token)
                value = re.sub(r'\\(x[0-9a-fA-F]{1,2}|.)', unescape, value)
                value = SettingsStore._qt_value(value)
                result[key if section == 'General' else section + '/' + key] = value
        return result

    def value(self, key, default=None, *, type=None):
        value = self.values.get(key, default)
        if type is bool:
            return value if isinstance(value, bool) else str(value).lower() in ('true', '1')
        return type(value) if type and value is not None else value

    def contains(self, key):
        return key in self.values

    def setValue(self, key, value):
        self.values[key] = value
        self.dirty[key] = value
        self.removed.discard(key)
        if not self.batching:
            self.sync()

    def remove(self, key):
        self.values.pop(key, None)
        self.dirty.pop(key, None)
        self.removed.add(key)
        if not self.batching:
            self.sync()

    @contextmanager
    def batch(self):
        self.batching += 1
        try:
            yield self
        finally:
            self.batching -= 1
            if not self.batching:
                self.sync()

    def sync(self):
        from .file_lock import FileLock
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock = FileLock(str(self.path) + '.lock')
            if not lock.tryLock(2000):
                raise OSError('设置正在被另一个进程保存')
            try:
                merged = self._read_json() if self.path.exists() else dict(self.values)
                merged.update(self.dirty)
                for key in self.removed:
                    merged.pop(key, None)
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                                 prefix='.preferences-', delete=False) as stream:
                    temporary = Path(stream.name)
                    json.dump(merged, stream, ensure_ascii=False, default=self._encode)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                self.values, self.dirty, self.removed = merged, {}, set()
                self._status = self.Status.NoError
            finally:
                lock.unlock()
        except (OSError, ValueError, TypeError):
            self._status = self.Status.AccessError
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def status(self):
        return self._status

    def fileName(self):
        return str(self.path)

    def format(self):
        return self.Format.IniFormat
