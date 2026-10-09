"""Owned JSON-lines worker for local materials and bounded optional cloud tasks."""
import asyncio
import json
import os
import sys
from dataclasses import asdict
from threading import Thread

from ..core import Caption
from ..library import Library
from .api import DeepSeekService, save_credential
from .files import FileChecks, checked_path, material_cache, read_json, write_json, write_text
from .glossary import compile_context, term_text
from .harness import run_agent
from .materials import RENDERED_PARSER, course_for_folder, import_document, locate_course, read_blocks
from .readings import load_readings, save_reading, validate_reading, visual_blocks
from .rendering import image_bytes, render_material
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
        self.coverage = {}
        self.task = None
        self.automatic = False
        self.last_started = 0.
        self.last_checked = 0.
        self.last_error = False
        self.material_error = ''
        self.last_view_course = None
        self.checked_materials = None
        self.synced_store = None

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

    def sync_materials(self, checks=None):
        identity = (self.course_path, fingerprint((self.course or {}).get('documents', [])))
        if checks and self.checked_materials == (checks, identity) and checks.unchanged():
            return
        previous = self.blocks
        try:
            self.blocks = read_blocks(self.library, self.course_path, self.course, checks) if self.course else []
            visual, self.coverage = visual_blocks(self.library, self.course_path, self.blocks, self.course['documents'], checks) if self.course else ([], {})
            self.blocks += visual
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.blocks = []
            self.coverage = {}
            self.material_error = str(exc)
        if self.blocks != previous or self.synced_store is not self.store:
            self.store.materials(self.blocks)
            self.synced_store = self.store
        self.checked_materials = (checks, identity) if checks and not self.material_error else None

    def view(self):
        view = self.store.view()
        refs = {ref['id'] for note in view['notes'] for ref in note.get('refs', [])}
        captions = {key: row for key, row in view['sources'].items() if row['kind'] == 'caption'}
        if captions:
            refs.add(max(captions, key=lambda key: captions[key]['event_seq']))
        view['sources'] = {key: row for key, row in view['sources'].items() if key in refs}
        value = {'type': 'view', 'manifest': self.manifest, **view, 'material_error': self.material_error,
                     'reading_coverage': self.coverage,
                     'automatic_paused': bool(self.manifest['notes_cloud']) and (not self.automatic or self.last_error),
                     'course_options': [{'id': row['id'], 'name': self.library.folder_label(row['id'])}
                                        for row in self.library.index['folders']],
                     'course_folder_id': next((row['id'] for row in self.library.index['folders'] if self.course_path
                        and self.library.directory(row['id']) == self.course_path.parent.parent), ''),
                     'busy': self.task is not None and not self.task.done()}
        digest = fingerprint([self.course, self.material_error, [(row.id, row.version) for row in self.blocks]])
        if digest != self.last_view_course:
            rendered = {row['id']: row for row in (self.course or {}).get('documents', []) if row['parser'] == RENDERED_PARSER}
            display = [{**asdict(block),
                'text': block.text[:1600] if block.evidence_type == 'visual' else block.text,
                'preview_truncated': block.evidence_type == 'visual' and len(block.text) > 1600} for block in self.blocks]
            for block in display:
                if block['document_id'] in rendered and block['evidence_type'] == 'native':
                    block['preview_image_path'] = str(checked_path(self.library.root,
                        material_cache(self.library, self.course_path, rendered[block['document_id']]) /
                        'pages' / f'page-{block["page"]:04d}.png'))
            value.update(course=self.course, blocks=display)
            self.last_view_course = digest
        self.notify(value)

    def course_version(self):
        return fingerprint([self.course or {}, [(row.id, row.version) for row in self.blocks]])

    def authorize(self, operation, course_id=None):
        """Read the current consent before dispatch, including every harness model turn."""
        self.identity()
        if course_id is not None and self.manifest['course_id'] != course_id:
            raise ValueError('课程关联已变化，未发起后续模型请求。')
        if operation == 'extract':
            if (not self.course or not self.course.get('material_cloud', False)
                    or not self.course.get('material_images_cloud', False)):
                raise ValueError('课件上传许可已关闭，未发起模型请求。')
        elif not self.manifest['notes_cloud']:
            raise ValueError('笔记上传许可已关闭，未发起模型请求。')

    def cancel(self):
        if self.task is not None and not self.task.done() and not self.task.cancelling():
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
            self.task = asyncio.create_task(self.import_task(folder['id'], value['path']))
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
                self.course['material_images_cloud'] = bool(value['materials'])
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
        if operation == 'extract' and not self.course.get('material_images_cloud', False):
            raise ValueError('请先允许将本课程的课件页面图像和文字发送给 DeepSeek。')
        if operation != 'extract' and not self.manifest['notes_cloud']:
            raise ValueError('请先允许将本段录音的已保存定稿文字和相关课件发送给 DeepSeek。')
        self.sync_materials()
        if self.material_error:
            raise ValueError('课程资料不可用或校验失败，请恢复原件或重新关联课程；原笔记保留。')
        if operation != 'extract' and any(not row['complete'] for row in self.coverage.values()):
            raise ValueError('课件尚未完成全页视觉读取，请先点击“完整阅读并提取术语”；原笔记保留。')
        self.last_started = asyncio.get_running_loop().time()
        self.last_error = False
        if operation == 'notes':
            self.automatic = True
        self.task = asyncio.create_task(self.cloud_task(operation, question, section))
        self.notify({'type': 'status', 'message': '正在处理课程资料，可取消。', 'busy': True})

    async def import_task(self, folder_id, path):
        try:
            await import_document(self.library, folder_id, path)
            self.identity()
            self.sync_materials()
            self.view()
            total = sum(row['total'] for row in self.coverage.values())
            read = sum(row['read'] for row in self.coverage.values())
            self.notify({'type': 'status', 'message': f'课件已在本地导入 · 视觉读取 {read}/{total} 页；允许上传后可完整阅读并提取术语。', 'busy': False})
        except asyncio.CancelledError:
            self.notify({'type': 'status', 'message': '课件导入已取消，已有材料和笔记保留。', 'busy': False})
        except Exception as exc:
            self.error(exc)
        finally:
            self.notify({'type': 'idle', 'busy': False})

    async def cloud_task(self, operation, question, section=''):
        service = None
        try:
            self.authorize(operation)
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
            course_id = self.manifest['course_id']
            service = DeepSeekService(notify=lambda usage: self.notify({'type': 'usage', **usage}),
                before_request=lambda: self.authorize(operation, course_id),
                before_image_request=lambda: self.authorize('extract', course_id),
                page_count=sum(row.evidence_type == 'native' for row in self.blocks) if operation == 'extract' else 0,
                images_enabled=bool(self.course and self.course.get('material_images_cloud', False)))
            if operation == 'extract':
                await self.extract_batches(service, course_version)
                self.view()
                return
            batches = 0
            while job is not None:
                result = (await service.update_notes(job) if operation == 'notes' else
                          await run_agent(service, job, answer=operation == 'question'))
                # Let queued changes invalidate a late result before publication.
                await asyncio.sleep(0)
                self.authorize(operation, course_id)
                self.sync_materials()
                if self.material_error:
                    raise ValueError('课件原件或缓存已变化，请恢复后重试；旧结果未发布。')
                _, saved = self.library.load(self.item)
                self.store.verify_saved(saved)
                if self.course_version() != course_version:
                    raise ValueError('课程材料或术语已变化，旧结果已拒绝。')
                if operation == 'question':
                    self.store.validate_job(job, require_latest=True)
                    self.notify({'type': 'answer', **result, 'event_seq': job.event_seq,
                        'notes_version': job.notes_version, 'sources': {ref['id']: {
                            key: job.sources[ref['id']].get(key) for key in (
                                'kind', 'start', 'end', 'page', 'title', 'source_version', 'evidence_type')}
                            for ref in result['refs']}})
                else:
                    self.store.publish(job, result)
                    write_text(self.library.root, self.library.directory(self.item['id']) / '课堂笔记.md', markdown(self.store.view()))
                self.view()
                batches += 1
                if operation != 'organize' or not job.remaining_note_ids:
                    break
                self.notify({'type': 'status', 'message': f'课后整理已保存 {batches} 批，继续处理剩余笔记，可取消。', 'busy': True})
                job = self.store.make_job(course_version, mode='organize', section=section,
                    note_ids=job.remaining_note_ids)
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
        """Every native page gets an image request; blank pages count, validated readings resume."""
        checks = FileChecks(self.library.root)
        try:
            self.sync_materials(checks)
            await self._extract_pages(service, version, checks)
        finally:
            self.checked_materials = None  # No validation memo survives the owned task.

    async def _extract_pages(self, service, version, checks):
        native = [row for row in self.blocks if row.evidence_type == 'native']
        if not native:
            raise ValueError('请先导入课件。')
        completed, omitted = 0, 0
        course_id = self.manifest['course_id']
        descriptors = list(self.course['documents'])
        for descriptor in descriptors:
            pages = [row for row in native if row.document_id == descriptor['id']]
            expected_course = fingerprint(self.course)
            self.notify({'type': 'status', 'message': f'正在本机渲染 {descriptor["name"]} 的全部页面，可取消。', 'busy': True})
            manifest = await render_material(self.library, self.course_path, descriptor, len(pages))
            self.authorize('extract', course_id)
            self.sync_materials(checks)
            if (self.material_error or fingerprint(self.course) != expected_course
                    or [row for row in self.blocks if row.evidence_type == 'native'] != native):
                raise ValueError('渲染期间课程资料已变化，没有发送旧页面。')
            version = self.course_version()
            try:
                cache = load_readings(self.library, self.course_path, descriptor['id'], checks)
            except (ValueError, TypeError):
                cache = {}
            for block, image in zip(pages, manifest['images']):
                self.authorize('extract', course_id)
                self.sync_materials(checks)
                if self.material_error or self.course_version() != version:
                    raise ValueError('课程资料已变化，旧页面未上传；请重新阅读。')
                location = checked_path(self.library.root,
                    material_cache(self.library, self.course_path, descriptor) / 'pages' / image['path'])
                reused = True
                try:
                    result = validate_reading(block, cache[block.id], image['sha256'])
                except (ValueError, KeyError, TypeError):
                    reused = False
                    result = await service.read_page(block, {'image_path': str(location), 'image_hash': image['sha256']})
                await asyncio.sleep(0)
                self.authorize('extract', course_id)
                self.sync_materials(checks)
                if self.material_error or self.course_version() != version:
                    raise ValueError('课程资料已变化，旧阅读结果未保存。')
                checks.get(location, image['sha256'], lambda entry: len(image_bytes(entry, image['sha256'])))
                if not reused:
                    save_reading(self.library, self.course_path, block, image['sha256'], result)
                old = {row['canonical'].casefold() for row in self.course['terms']}
                changed_terms = False
                for term in result['terms']:
                    if term['canonical'].casefold() in old:
                        continue
                    if len(self.course['terms']) >= 200:
                        omitted += 1  # Candidate limits must not skip the rest of the courseware.
                        continue
                    self.course['terms'].append(asdict(Term(term_text(term['canonical']),
                        tuple(term_text(alias) for alias in term['aliases']), tuple(ref['id'] for ref in term['refs']), False)))
                    old.add(term['canonical'].casefold())
                    changed_terms = True
                if changed_terms:
                    write_json(self.library.root, self.course_path, self.course)
                self.sync_materials(checks)
                version = self.course_version()
                completed += 1
                if not reused:
                    self.view()
                self.notify({'type': 'status', 'message': f'课件已读取 {completed}/{len(native)} 页，结果已保存，可取消。', 'busy': True})
        uncertain = sum(row['uncertain'] for row in self.coverage.values())
        if not all(row['complete'] for row in self.coverage.values()):
            raise ValueError('仍有页面未通过阅读校验，没有标记整份课件完成；请继续阅读。')
        self.notify({'type': 'status', 'message': f'全部 {completed} 页已完成视觉读取，{uncertain} 页有待核对内容。'
            + (f'术语候选已达上限，另有 {omitted} 条未加入；页面阅读保留。' if omitted else ''), 'busy': False})

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
