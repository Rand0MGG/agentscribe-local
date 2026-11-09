"""DesktopModels commands on the single DesktopService owner; no separate business state."""
import json

from .preparation_workflow import preparation_command


class DesktopModels:
    def _selected_models(self):
        values = self.values
        return [{'path': values['asr'] if values['backend'] == 'wlk-whisper' else values['qwen_model'],
                 'kind': 'asr', 'engine': values['backend']},
                {'path': values['llama_model'] if values['translation_engine'] == 'llama' else values['translation'],
                 'kind': 'translation', 'engine': values['translation_engine']}]

    def _selection(self):
        values = self.values
        return dict(backend=values['backend'],
                    asr_model=values['asr'] if values['backend'] == 'wlk-whisper' else values['qwen_model'],
                    translation_engine=values['translation_engine'],
                    translation_model=values['llama_model'] if values['translation_engine'] == 'llama' else values['translation'],
                    translation_device=values['translation_device'])

    def _refresh_models(self):
        if self.closing or self.update_fenced:
            return
        if self.preparation or self.asset_check:
            self.model_refresh.start(100)
            return
        self.check_models()

    def check_models(self):
        if self.asset_check:
            raise ValueError('模型检查正在进行，可取消后重试。')
        from .ui_checks import BackgroundCheck
        selection = self._selection()
        translating = self.values['translate']
        arguments = ['--check', '--selection', json.dumps(selection)]
        if not translating:
            arguments += ['--only', 'asr']
        check = BackgroundCheck('linguaflow.recommended_prepare', arguments, self)
        self.asset_check = check
        self.asset_check_cancelled = False
        def result(value):
            if self.closing or self.asset_check_cancelled:
                return
            if selection != self._selection() or translating != self.values['translate']:
                self.model_refresh.start(100)
            elif isinstance(value, list) and all(isinstance(row, str) for row in value):
                self.asset_selection, self.missing_assets = selection, value
                self.emit('model-check', {'busy': False, 'missing': value,
                                         'message': '所选模型已就绪。' if not value else '所选模型与组件尚需准备。'})
            else:
                message = '模型检查未完成：' + (check.failure_reason or '返回内容不符合预期，请重新检查。')
                self.emit('model-check', {'busy': False, 'error': message})
                self.emit('notice', {'text': message, 'error': True})
        def finished():
            if self.asset_check_cancelled and not self.closing:
                self.emit('model-check', {'busy': False, 'message': '模型检查已取消，已有结果保留。'})
            if self.asset_check is check:
                self.asset_check = None
            check.deleteLater()
            self.changed()
            self._continue_close()
        check.result.connect(result)
        check.completed.connect(finished)
        check.begin()
        self.emit('model-check', {'busy': True, 'message': '正在检查所选模型…'})
        self.changed()

    def cancel_model_check(self):
        if self.asset_check:
            self.asset_check_cancelled = True
            self.asset_check.kill()
            self.emit('model-check', {'busy': True, 'message': '正在取消模型检查…'})

    def model_inventory(self):
        from .model_inventory import inventory
        selected = self._selected_models()
        self._start_task('inventory', lambda: inventory(selected))

    def delete_model(self, identifier):
        self._idle()
        if self.preparation:
            raise ValueError('请先完成或取消模型准备。')
        from .model_inventory import delete_model, inventory
        selected = self._selected_models()
        def remove():
            delete_model(identifier, selected)
            return inventory(selected)
        self._start_task('inventory', remove)

    def prepare(self, only=None, kind='models', selection=None):
        if kind != 'documents':
            self._idle()
        elif self.update_fenced or self.migration.busy or self.pending_library or self.closing:
            raise ValueError('请等待当前文件操作完成。')
        if self.preparation or self.runtime_action or 'inventory' in self.tasks:
            raise ValueError('已有准备任务正在运行。')
        if only not in (None, 'all', 'asr', 'translation'):
            raise ValueError('无效的准备范围。')
        if kind not in ('models', 'runtime', 'documents') or (kind == 'documents' and not self.values['beta_features']):
            raise ValueError('无效的准备任务，请先启用对应功能。')
        settings = self.settings()
        current = dict(backend=settings.backend,
                         asr_model=settings.asr_model if settings.backend == 'wlk-whisper' else settings.qwen_model,
                         translation_engine=settings.translation_engine,
                         translation_model=settings.llama_model if settings.translation_engine == 'llama' else settings.translation_model,
                         translation_device=settings.translation_device)
        if selection is None:
            selection = current
        elif kind != 'models':
            raise ValueError('无效的模型下载快照。')
        if kind == 'models' and only is None and not settings.translate:
            only = 'asr'
        command = preparation_command(selection, kind=kind, only=only)
        self.cancel_model_check()
        self.preparation_command = command, kind
        self._start_preparation(command, kind)

    def retry_preparation(self):
        if not self.preparation_command or self.preparation_command[1] != 'documents':
            self._idle()
        elif self.update_fenced or self.migration.busy or self.pending_library or self.closing:
            raise ValueError('请等待当前文件操作完成。')
        if self.preparation or not self.preparation_command or not self.preparation_recovery:
            raise ValueError('没有可恢复的准备任务。')
        command, kind = self.preparation_command
        if kind == 'documents' and not self.values['beta_features']:
            raise ValueError('请先启用课程助手 Beta。')
        self._start_preparation(command, kind)

    def _warm_runtime(self):
        if self.no_audio or self.closing or self.update_fenced or self.preparation or self.runtime_action:
            return
        if self.runtime is None:
            from .runtime_preparation import RuntimePreparation
            self.runtime = RuntimePreparation()
        self.runtime.prepare()

    def _retire_runtime(self, completed):
        runtime = self.runtime
        def finished(error):
            if not error and self.runtime is runtime:
                self.runtime = None
            completed(error)
        self._start_task('runtime-release', runtime.close, finished)

    def _start_preparation(self, command, kind):
        if self.runtime is not None and kind != 'documents':
            self.runtime_action = (command, kind)
            self.preparation_status = '正在释放推理环境…'
            def released(error):
                action, self.runtime_action = self.runtime_action, None
                if error:
                    self.preparation_status = '准备未完成：' + error
                    self.preparation_recovery = '重试'
                elif action and not self.closing:
                    self._start_preparation(*action)
                self.changed()
            self._retire_runtime(released)
            self.changed()
            return
        self.preparation_recovery = ''
        self.preparation_status = '正在准备所选模型与组件…'
        self.preparation_workflow.start(lambda: self.preparation.run_command(command),
                                        affects_runtime=kind != 'documents', beta_only=kind == 'documents')
        self.changed()

    def _progress(self, value):
        if not self.preparation or self.preparation.cancelled:
            return
        self.progress = value
        self.changed()

    def _preparation_result(self, value):
        self.emit('diagnostic', value)
        from .preparation_task import preparation_error_message
        self.preparation_status = preparation_error_message(value) if value.startswith('未完成：') else value
        self.changed()

    def _preparation_finished(self, task):
        self.preparation_recovery = '继续准备' if task.cancelled else ('重试' if self.preparation_status.startswith('准备未完成：') else '')
        self.progress = None
        if not self.closing:
            self._warm_runtime()
            self.model_refresh.start(100)
            if 'inventory' not in self.tasks:
                self.model_inventory()
        self.changed()
        self._continue_close()

    def cancel_preparation(self):
        if self.runtime_action:
            self.runtime_action = None
            self.preparation_status = '准备已取消，已完成文件保留。'
            self.preparation_recovery = '继续准备'
            self.changed()
        if self.preparation:
            self.preparation_workflow.cancel()
            self.preparation_status = '正在取消，已完成文件保留…'
            self.changed()
