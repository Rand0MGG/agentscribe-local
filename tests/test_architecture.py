"""Dependency contracts: layers may grow, but domain code must stay portable."""
import ast
from importlib.util import resolve_name
from pathlib import Path


def dependencies():
    root = Path(__file__).resolve().parents[1] / 'linguaflow'
    paths = {'.'.join(('linguaflow', *p.relative_to(root).with_suffix('').parts)).removesuffix('.__init__'): p
             for p in root.rglob('*.py')}
    graph, external = {}, {}
    for module, path in paths.items():
        imports = set()
        package = module if path.name == '__init__.py' else module.rpartition('.')[0]
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = resolve_name('.' * node.level + (node.module or ''), package) if node.level else node.module
                if base:
                    imports.add(base)
                    imports.update(base + '.' + alias.name for alias in node.names)
        graph[module] = {name for name in imports if name in paths and name != module}
        external[module] = {name.split('.')[0] for name in imports if not name.startswith('linguaflow')}
    return graph, external


def reachable(graph, module):
    visited, pending = set(), [module]
    while pending:
        node = pending.pop()
        if node not in visited:
            visited.add(node)
            pending.extend(graph[node])
    return visited


def test_domain_and_storage_have_no_transitive_qt_or_model_dependency():
    graph, external = dependencies()
    domain = ('core', 'preferences', 'recording_state', 'capture_control', 'recording_document', 'library', 'library_startup', 'runtime_paths', 'runtime_preparation',
              'wlk_captions', 'translation_queue', 'translation_service', 'translation_context', 'translation_config',
              'translation_models', 'llama_assets', 'llama_translation', 'process_platform', 'managed_process', 'qwen_revisions',
              'revision_audit', 'evaluation', 'ami_evaluation', 'audio_processing.config', 'audio_processing.health')
    forbidden = {'PySide6', 'torch', 'transformers', 'whisperlivekit', 'onnxruntime'}
    for module in domain:
        for dependency in reachable(graph, 'linguaflow.' + module):
            assert not external[dependency] & forbidden, (module, dependency, external[dependency] & forbidden)


def test_runtime_does_not_depend_on_desktop_and_package_has_no_import_cycles():
    graph, _ = dependencies()
    desktop = {'linguaflow.' + name for name in ('app', 'management', 'workspace_widgets',
               'settings_binding', 'deleted_dialog', 'wlk_session', 'recording_save')}
    for module in ('wlk_worker', 'backends', 'semantic_model', 'audio_processing.pipeline'):
        assert not reachable(graph, 'linguaflow.' + module) & desktop
    for module, imports in graph.items():
        for dependency in imports:
            assert module not in reachable(graph, dependency), f'Import cycle: {module} -> {dependency}'
