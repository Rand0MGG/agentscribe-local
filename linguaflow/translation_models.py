"""Model family discovery and translation instructions, independent of inference."""
import json
from pathlib import Path

HY_MODEL = 'tencent/Hy-MT2-1.8B'
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
        raise ValueError(f'混元翻译暂不支持目标语言：{target}')
    background = ''
    if context and (context.before or context.after):
        # JSON quoting keeps source boundaries unambiguous even with embedded labels.
        background = ('[Background Information]\n' + json.dumps(
            {'preceding_source': context.before, 'following_source': context.after}, ensure_ascii=False)
            + '\nUse this only to resolve meaning and terminology. Do not translate the background.\n')
    return (background + f'Translate only the following source text into {language}. '
            'Output only its translation, without explanations or background text.\n[Source Text]\n' + text)
