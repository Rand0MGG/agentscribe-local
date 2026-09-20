import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from linguaflow.backends import HyMtTranslator
from linguaflow.translation_context import TranslationContext
from linguaflow.translation_models import HY_MODEL, is_hy_model, translation_prompt


def test_model_family_uses_local_config_not_folder_name(tmp_path):
    assert is_hy_model(HY_MODEL)
    assert not is_hy_model('facebook/nllb-200-distilled-600M')
    path = tmp_path / 'my-translator'
    path.mkdir()
    assert not is_hy_model(str(path))
    (path / 'config.json').write_text(json.dumps({'model_type': 'hunyuan_v1_dense'}))
    assert is_hy_model(str(path))


def test_prompt_separates_neighbours_and_uses_language_names():
    context = TranslationContext(('A suitcase.',), ('It held books.',))
    prompt = translation_prompt('It was heavy.', 'zho_Hans', context)
    assert 'Simplified Chinese' in prompt and 'zho_Hans' not in prompt
    assert prompt.endswith('[Source Text]\nIt was heavy.')
    assert 'A suitcase.' in prompt and 'It held books.' in prompt
    assert 'Do not translate the background.' in prompt
    assert 'Background' not in translation_prompt('Hello', 'eng_Latn')
    with pytest.raises(ValueError):
        translation_prompt('Hello', 'invalid')


def test_hy_removes_segment_ids_and_decodes_only_generated_tokens():
    class Inputs(dict):
        def to(self, device):
            return self

    class Tokenizer:
        def apply_chat_template(self, messages, **kwargs):
            assert 'Source Text' in messages[0]['content']
            return Inputs(input_ids=SimpleNamespace(shape=(1, 3)), attention_mask=[1]*3, token_type_ids=[0]*3)

        def decode(self, tokens, **kwargs):
            assert tokens == [10, 20]
            return '译文'

    def generate(**kwargs):
        assert 'token_type_ids' not in kwargs
        assert 'attention_mask' in kwargs
        return [[1, 2, 3, 10, 20]]

    translator = HyMtTranslator.__new__(HyMtTranslator)
    translator.target, translator.source = 'zho_Hans', None
    translator.torch = SimpleNamespace(inference_mode=nullcontext)
    translator.tokenizer = Tokenizer()
    translator.model = SimpleNamespace(device='cpu', generate=generate,
                                       generation_config=SimpleNamespace(eos_token_id=20))
    assert translator.translate('Hello', 'en') == '译文'
