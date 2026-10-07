"""Owned JSON-lines worker for local materials and bounded optional cloud tasks."""
import asyncio
import json
import os
import sys
from dataclasses import asdict, replace
from threading import Thread

from ..core import Caption
from ..library import Library
from .api import DeepSeekService, save_credential
from .files import checked_path, read_json, write_json, write_text
from .glossary import compile_context, term_text
from .harness import run_agent
from .materials import course_for_folder, import_material, locate_course, read_blocks
from .retrieval import markdown
from .schemas import Term, fingerprint
from .session import read_manifest, write_manifest
from .storage import KnowledgeStore


def emit(value):
    sys.stdout.write(json.dumps(value, ensure_ascii=False) + '\n')
    sys.stdout.flush()


class KnowledgeWorker:
    def __init__(self, notify=emit):
        self.notify = notify
        self.library = self.item = self.store = None
        self.course_path = self.course = None
        self.blocks = []
        self.task = None
        self.automatic = False
        self.last_started = 0.
        self.last_checked = 0.
        self.last_error = False
        self.material_error = ''
        self.last_view_course = None

    def identity(self):
        """Re-resolve and verify identity before every write/publication, including external moves."""
        self.library.refresh()
        directory = self.library.directory(self.item['id'])
        if directory != self.store.path.parent.parent or read_json(directory / 'session.json')['session']['id'] != self.item['id']:
            raise ValueError('录音位置已变化，请重新打开课程资料。')
        self.manifest = read_manifest(self.library, self.item['id'])
        self.load_course()

    def load_course(self):
        self.material_error = ''
        if self.manifest['course_id']:
            try:
                self.course_path, self.course = locate_course(self.library, self.manifest['course_id'])
            except (FileNotFoundError, ValueError) as exc:
                self.course_path = self.course = None
                self.material_error = str(exc)

    def sync_materials(self):
        try:
            self.blocks = read_blocks(self.library, self.course_path, self.course) if self.course else []
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.blocks = []
            self.material_error = str(exc)
        self.store.materials(self.blocks)

    def view(self):
        view = self.store.view()
        refs = {ref['id'] for note in view['notes'] for ref in note.get('refs', [])}
        captions = {key: row for key, row in view['sources'].items() if row['kind'] == 'caption'}
        if captions:
            refs.add(max(captions, key=lambda key: captions[key]['event_seq']))
        view['sources'] = {key: row for key, row in view['sources'].items() if key in refs}
        value = {'type': 'view', 'manifest': self.manifest, **view, 'material_error': self.material_error,
                     'automatic_paused': bool(self.manifest['notes_cloud']) and (not self.automatic or self.last_error),
                     'course_options': [{'id': row['id'], 'name': self.library.folder_label(row['id'])}
                                        for row in self.library.index['folders']],
                     'course_folder_id': next((row['id'] for row in self.library.index['folders'] if self.course_path
                        and self.library.directory(row['id']) == self.course_path.parent.parent), ''),
                     'busy': self.task is not None and not self.task.done()}
        digest = fingerprint([self.course, self.material_error])
        if digest != self.last_view_course:
            value.update(course=self.course, blocks=[asdict(block) for block in self.blocks])
            self.last_view_course = digest
        self.notify(value)

    def course_version(self):
        return fingerprint(self.course or {})

    def cancel(self):
        if self.task is not None and not self.task.done():
            self.task.cancel()
        self.automatic = False

    async def command(self, value):
        operation = value['operation']
        if operation == 'open':
            self.library = Library(value['root'])
            self.item = next(row for row in self.library.index['sessions'] if row['id'] == value['identifier'])
            self.manifest = read_manifest(self.library, self.item['id'])
            if self.manifest['course_id']:
                self.load_course()
            else:
                self.course_path, self.course = course_for_folder(self.library, value['folder_id'], create=True)
                self.manifest['course_id'] = self.course['id']
                self.manifest['asr_context'] = compile_context((Term(**row) for row in self.course['terms']),
                    ((row['id'], row['version']) for row in self.course['documents'])).to_dict()
                write_manifest(self.library, self.manifest)
            self.store = KnowledgeStore(self.library.root, self.library.directory(self.item['id']), self.item['id'], value['epoch'])
            _, captions = self.library.load(self.item)
            self.store.saved(captions, authoritative=True)
            if value.get('live') is not None:
                self.store.live_snapshot([Caption(**row) for row in value['live']])
            self.sync_materials()
            self.automatic = bool(self.manifest['notes_cloud']) and not self.material_error
            self.view()
            return
        if self.store is None:
            raise ValueError('请先打开一段录音。')
        if operation == 'caption':
            self.store.observe(Caption(**value['caption']))
            return  # Do not re-send a whole course on each ASR result.
        if operation == 'saved':
            self.identity()
            self.store.saved([Caption(**row) for row in value['captions']])
            self.view()
            if value.get('final'):
                self.last_started = 0.
            return
        if operation == 'cancel':
            self.cancel()
            self.notify({'type': 'status', 'message': '课程任务已取消；点击更新笔记可继续自动更新，已保存内容保留。', 'busy': False})
            return
        self.identity()
        if operation in ('import', 'terms', 'extract') and self.course is None:
            raise ValueError('关联课程不可用，请恢复资料或选择课程重新关联。')
        if operation == 'import':
            if self.task is not None and not self.task.done():
                raise ValueError('请先取消当前课程任务。')
            folder = next(row for row in self.library.index['folders']
                          if self.library.directory(row['id']) == self.course_path.parent.parent)
            self.notify({'type': 'status', 'message': '正在本地读取课件，可取消。', 'busy': True})
            import_material(self.library, folder['id'], value['path'])
            self.course = read_json(self.course_path)
            self.sync_materials()
            self.view()
        elif operation == 'terms':
            terms = [Term(term_text(row['canonical']), tuple(term_text(alias) for alias in row.get('aliases', [])),
                          tuple(row.get('evidence_ids', [])), bool(row['approved']), row.get('origin', 'manual'))
                     for row in value['terms']]
            if len(terms) > 200:
                raise ValueError('术语过多，请只保留本次课程需要的术语。')
            self.course['terms'] = [asdict(term) for term in terms]
            write_json(self.library.root, self.course_path, self.course)
            self.manifest['asr_context'] = compile_context(terms, ((row['id'], row['version'])
                for row in self.course['documents'])).to_dict()
            write_manifest(self.library, self.manifest)
            self.view()
        elif operation == 'permission':
            self.cancel()
            if self.course:
                self.course['material_cloud'] = bool(value['materials'])
                write_json(self.library.root, self.course_path, self.course)
            elif value['materials']:
                raise ValueError('课程资料不可用，请恢复或重新关联后再允许课件上传。')
            self.manifest['notes_cloud'] = bool(value['notes'])
            write_manifest(self.library, self.manifest)
            self.automatic = self.manifest['notes_cloud'] and not self.material_error
            self.last_error = False
            self.view()
        elif operation == 'credential':
            save_credential(value['value'])
            self.last_error = False
            self.notify({'type': 'status', 'message': '密钥已保存到系统凭据存储。', 'busy': False})
        elif operation == 'associate':
            self.cancel()
            self.course_path, self.course = course_for_folder(self.library, value['folder_id'], create=True)
            self.manifest['course_id'] = self.course['id']
            self.manifest['notes_cloud'] = False
            self.manifest['asr_context'] = compile_context((Term(**row) for row in self.course['terms']),
                ((row['id'], row['version']) for row in self.course['documents'])).to_dict()
            write_manifest(self.library, self.manifest)
            self.material_error = ''
            self.sync_materials()
            self.view()
        elif operation == 'edit':
            self.store.edit_note(value['id'], value['text'])
            self.view()
        elif operation == 'export':
            self.sync_materials()
            _, saved = self.library.load(self.item)
            self.store.verify_saved(saved)
            write_text(self.library.root, checked_path(self.library.root,
                self.library.directory(self.item['id']) / '课堂笔记.md'), markdown(self.store.view()))
            self.notify({'type': 'status', 'message': '已保存课堂笔记.md，可在录音文件夹查看。', 'busy': False})
        elif operation in ('extract', 'notes', 'organize', 'question'):
            self.start_task(operation, value.get('question', ''), value.get('section', ''))
        elif operation == 'view':
            self.sync_materials()
            self.view()
        else:
            raise ValueError('未知课程操作。')

    def start_task(self, operation, question='', section=''):
        if self.task is not None and not self.task.done():
            raise ValueError('已有课程任务正在处理，请等待或取消。')
        if operation == 'extract' and not self.course['material_cloud']:
            raise ValueError('请先允许将本课程课件文本发送给 DeepSeek。')
        if operation != 'extract' and not self.manifest['notes_cloud']:
            raise ValueError('请先允许将本段录音的已保存定稿文字和相关课件发送给 DeepSeek。')
        self.sync_materials()
        if self.material_error:
            raise ValueError('课程资料不可用或校验失败，请恢复原件或重新关联课程；原笔记保留。')
        self.last_started = asyncio.get_running_loop().time()
        self.last_error = False
        if operation == 'notes':
            self.automatic = True
        self.task = asyncio.create_task(self.cloud_task(operation, question, section))
        self.notify({'type': 'status', 'message': '正在处理课程文字，可取消。', 'busy': True})

    async def cloud_task(self, operation, question, section=''):
        service = None
        try:
            self.identity()
            self.sync_materials()
            if self.material_error:
                raise ValueError('课程资料不可用或校验失败，请恢复后重试；没有发起模型请求。')
            _, persisted = self.library.load(self.item)
            self.store.verify_saved(persisted)
            course_version = self.course_version()
            job = None
            if operation != 'extract':
                job = self.store.make_job(course_version, question, 'notes' if operation == 'notes' else operation, section)
                if job is None:
                    self.notify({'type': 'status', 'message': '暂无可更新内容；需要已保存的定稿原文。', 'busy': False})
                    return
            service = DeepSeekService(notify=lambda usage: self.notify({'type': 'usage', **usage}))
            if operation == 'extract':
                await self.extract_batches(service, course_version)
                self.view()
                return
            elif operation == 'notes':
                result = await service.update_notes(job)
            else:
                result = await run_agent(service, job, answer=operation == 'question')
            # Yield once so already queued source updates are applied before validating late results.
            await asyncio.sleep(0)
            self.identity()
            self.sync_materials()
            if self.material_error:
                raise ValueError('课件原件或缓存已变化，请恢复后重试；旧结果未发布。')
            _, saved = self.library.load(self.item)
            self.store.verify_saved(saved)
            if self.course_version() != course_version:
                raise ValueError('课程材料或术语已变化，旧结果已拒绝。')
            if not self.manifest['notes_cloud']:
                raise ValueError('笔记上传许可已关闭，结果未发布。')
            elif operation == 'question':
                # Validate answer against the same source/version transaction as a note patch.
                self.store.validate_job(job, require_latest=True)
                self.notify({'type': 'answer', **result, 'event_seq': job.event_seq,
                    'notes_version': job.notes_version, 'sources': {ref['id']: {
                        key: job.sources[ref['id']].get(key) for key in ('kind', 'start', 'end', 'page', 'source_version')}
                        for ref in result['refs']}})
            else:
                self.store.publish(job, result)
                write_text(self.library.root, self.library.directory(self.item['id']) / '课堂笔记.md', markdown(self.store.view()))
            self.view()
        except asyncio.CancelledError:
            self.notify({'type': 'status', 'message': '任务已取消，已保存内容保留。', 'busy': False})
        except Exception as exc:
            self.last_error = True
            try:
                self.view()
            except (OSError, ValueError):
                pass
            self.error(exc)
        finally:
            if service is not None:
                try:
                    self.identity()
                    write_json(self.library.root, self.store.path.parent / 'last_usage.json', service.budget.view())
                except (OSError, ValueError, KeyError):
                    pass
                finally:
                    await service.close()
            self.notify({'type': 'idle', 'busy': False})

    async def extract_batches(self, service, version):
        """Bound each upload, cache validated candidates and retain completed batches on cancellation."""
        chunks, chunk, used = [], [], 0
        for block in self.blocks:
            if not block.text:
                continue
            # Long pages remain cited by the original page ID; split without altering text.
            pieces = [block] if len(block.text.encode('utf-8')) <= 6000 else [
                replace(block, text=block.text[index:index+1800]) for index in range(0, len(block.text), 1800)]
            for piece in pieces:
                cost = len(piece.text.encode('utf-8'))
                if chunk and (used + cost > 6000 or any(row.id == piece.id for row in chunk)):
                    chunks.append(chunk)
                    chunk, used = [], 0
                chunk.append(piece)
                used += cost
        if chunk:
            chunks.append(chunk)
        cache_path = checked_path(self.library.root, self.course_path.parent / 'terms-cache.json')
        cache = read_json(cache_path) if cache_path.exists() else {}
        for index, batch in enumerate(chunks, 1):
            key = fingerprint(['terms-v1-deepseek-flash', [asdict(row) for row in batch]])
            if key in cache:
                # Cache candidates are data, and retain the same explicit user approval step.
                result = cache[key]
            else:
                result = await service.extract_terms(batch)
            await asyncio.sleep(0)
            self.identity()
            self.sync_materials()
            if self.material_error:
                raise ValueError('课件原件或缓存已变化，请恢复后重试；旧术语结果未发布。')
            if self.course_version() != version or not self.course['material_cloud']:
                raise ValueError('课程或上传许可已变化，旧术语结果未发布。')
            original = {row.id: row for row in batch}
            for term in result:
                if (not any(term['canonical'].casefold() in ref['quote'].casefold() for ref in term['refs'])
                        or any(ref['id'] not in original or not ref['quote'] or ref['quote'] not in original[ref['id']].text
                               for ref in term['refs'])):
                    raise ValueError('缓存术语引用校验失败，请重新导入材料。')
            old = {row['canonical'].casefold() for row in self.course['terms']}
            for row in result:
                if row['canonical'].casefold() not in old:
                    if len(self.course['terms']) >= 200:
                        raise ValueError('候选术语已达 200 条上限，请审核删减后继续；之前保存的候选保留。')
                    aliases = tuple(term_text(alias) for alias in row['aliases'])
                    self.course['terms'].append(asdict(Term(term_text(row['canonical']), aliases,
                        tuple(ref['id'] for ref in row['refs']), False)))
                    old.add(row['canonical'].casefold())
            write_json(self.library.root, self.course_path, self.course)
            cache[key] = result
            cache = dict(list(cache.items())[-100:])
            write_json(self.library.root, cache_path, cache)
            version = self.course_version()
            self.notify({'type': 'status', 'message': f'术语已完成 {index}/{len(chunks)} 批，候选已保存，可取消。', 'busy': True})

    def error(self, exc):
        # Provider/schema errors can contain user text; do not echo them through UI or logs.
        message = str(exc)
        if type(exc).__module__ != 'builtins' or not any('\u3400' <= char <= '\u9fff' for char in message) or len(message) > 250:
            message = '课程处理失败，请检查可选依赖、网络与密钥，或减少输入后手动重试；已保存内容保留。'
        self.notify({'type': 'error', 'message': message, 'busy': False})

    def tick(self):
        now = asyncio.get_running_loop().time()
        if now - self.last_checked < 1:
            return
        self.last_checked = now
        if (self.store and self.automatic and not self.last_error and (self.task is None or self.task.done())
                and now - self.last_started >= 30):
            try:
                if self.store.make_job() is not None:
                    self.start_task('notes')
            except Exception as exc:
                self.last_error = True
                self.error(exc)


async def serve():
    loop, queue = asyncio.get_running_loop(), asyncio.Queue()
    def read():
        for line in sys.stdin:
            try:
                value = json.loads(line)
                loop.call_soon_threadsafe(queue.put_nowait, value)
            except (ValueError, RuntimeError):
                pass
        # EOF also terminates a parser blocked in native code; only this child is owned.
        os._exit(0)
    Thread(target=read, daemon=True).start()
    worker = KnowledgeWorker()
    while True:
        try:
            value = await asyncio.wait_for(queue.get(), 1)
            await worker.command(value)
        except asyncio.TimeoutError:
            pass
        except Exception as exc:
            worker.error(exc)
        worker.tick()


if __name__ == '__main__':
    asyncio.run(serve())
