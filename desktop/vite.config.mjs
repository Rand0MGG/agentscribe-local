import { defineConfig } from 'vite';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('..', import.meta.url));
const python = process.env.AGENTSCRIBE_DESKTOP_PYTHON || path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const themes = JSON.parse(execFileSync(python, ['-c',
  "import json; from linguaflow.ui_theme import THEMES, interaction_color; print(json.dumps({mode: {**colors, **{key: 'rgba(%s,%s,%s,%.6f)' % (*interaction_color(mode,key)[:3], interaction_color(mode,key)[3]/255) for key in ('secondary','secondary_hover','ghost_hover','row_hover')}} for mode, colors in THEMES.items()}))",
], { cwd: root, encoding: 'utf8' }));
const palette = Object.entries(themes).map(([theme, colors]) => `${theme === 'light' ? ':root,' : ''}:root[data-theme=${theme}] {${Object.entries(colors).map(([key, value]) => `--${key.replaceAll('_', '-')}:${value};`).join('')}}`).join('\n');

export default defineConfig({ base: './', build: { outDir: 'dist', emptyOutDir: true }, plugins: [{
  name: 'shared-qt-palette',
  resolveId(id) { if (id === 'virtual:qt-theme.css') return '\0qt-theme.css'; },
  load(id) { if (id === '\0qt-theme.css') return palette; },
}] });
