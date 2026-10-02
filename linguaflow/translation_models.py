"""Model family discovery and translation instructions, independent of inference."""
import json
from pathlib import Path

from .translation_context import TranslationContext

HY_MODEL = 'tencent/Hy-MT2-1.8B'


HY_GENERATION = dict(max_new_tokens=1024, temperature=.7, top_p=.6, top_k=20,
                     repetition_penalty=1.05, do_sample=True)


def translation_engine(settings):
    # Older saved sessions selected Metal before the engine preference existed.
    return getattr(settings, 'translation_engine', None) or ('llama' if settings.translation_device == 'metal' else 'pytorch')


def llama_generation():
    options = HY_GENERATION.copy()
    options['max_tokens'] = options.pop('max_new_tokens')
    options['repeat_penalty'] = options.pop('repetition_penalty')
    options.pop('do_sample')
    return options


TARGET_NAMES = dict(zip(
    ('zho_Hans', 'eng_Latn', 'jpn_Jpan', 'kor_Hang', 'fra_Latn', 'deu_Latn',
     'spa_Latn', 'rus_Cyrl', 'arb_Arab', 'por_Latn', 'ita_Latn', 'zho_Hant'),
    ('Simplified Chinese', 'English', 'Japanese', 'Korean', 'French', 'German',
     'Spanish', 'Russian', 'Arabic', 'Portuguese', 'Italian', 'Traditional Chinese'), strict=True))


def is_hy_model(model):
    path = Path(model)
    if path.is_dir():
        try:
            return json.loads((path / 'config.json').read_text(encoding='utf-8')).get('model_type') == 'hunyuan_v1_dense'
        except (OSError, ValueError):
            return False
    return model.lower().startswith('tencent/hy-mt2-')


def translation_prompt(text, target, context=None):
    language = TARGET_NAMES.get(target)
    if language is None:
        raise ValueError(f'翻译暂不支持目标语言：{target}')
    background = ''
    if context and (context.before or context.after):
        # JSON quoting keeps source boundaries unambiguous even with embedded labels.
        background = ('[Background Information]\n' + json.dumps(
            {'preceding_source': context.before, 'following_source': context.after}, ensure_ascii=False)
            + '\nUse this only to resolve meaning and terminology. Do not translate the background.\n')
    return (background + f'Translate only the following source text into {language}. '
            'Output only its translation, without explanations or background text.\n[Source Text]\n' + text)


def batch_translation_prompt(captions, target, context=None):
    # Keep boundaries explicit: free-form concatenation cannot preserve subtitle IDs.
    segments = [{'id': str(c.id), 'source': c.source} for c in captions]
    return (translation_prompt(json.dumps(segments, ensure_ascii=False), target, context)
            + '\nThe source is an ordered list of adjacent subtitle segments. Use all segments together '
            'to resolve meaning. Translate EVERY source segment, preserving its ID and source boundary. '
            'Return ONLY a JSON object mapping each ID to its translated text. Do not merge, omit, '
            'duplicate or add IDs. Do not translate the background or the JSON field names.')


def batch_translation_schema(captions):
    keys = [str(c.id) for c in captions]
    return {'type': 'object', 'properties': {key: {'type': 'string', 'minLength': 1} for key in keys},
            'required': keys, 'additionalProperties': False}


def parse_batch_translation(output, captions):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('合并翻译返回了重复字幕 ID。')
            result[key] = value
        return result
    try:
        values = json.loads(output, object_pairs_hook=unique)
    except ValueError as exc:
        raise ValueError('合并翻译格式无效；已保留原文和已有译文。') from exc
    if (not isinstance(values, dict) or set(values) != {str(c.id) for c in captions}
            or any(not isinstance(v, str) or not v.strip() for v in values.values())):
        raise ValueError('合并翻译返回的字幕缺失、多余或为空；已保留原文和已有译文。')
    return {c.id: values[str(c.id)].strip() for c in captions}


def fit_translation_prompt(build, context, count_tokens, limit):
    """Trim only background, oldest preceding row first; source is never truncated."""
    context = context or TranslationContext()
    original = context
    while True:
        prompt = build(context)
        if count_tokens(prompt) <= limit:
            return prompt, context != original
        if context.before:
            context = TranslationContext(context.before[1:], context.after)
        elif context.after:
            context = TranslationContext((), context.after[:-1])
        else:
            raise ValueError('本段翻译原文超出模型输入预算；已保留完整原文和已有译文。')
