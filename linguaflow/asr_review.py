"""Shared capped-output review; model adapters supply actual generated token counts."""
import re

MAX_TOKENS = 512


def repetitive_tail(text, generation_tokens):
    """Review capped results only; punctuation/case do not disguise a loop.

    A terminal phrase of 1–4 lexical units must repeat at least 32 times and
    occupy strictly more than half the output's units. CJK characters are units.
    This is a narrow degeneration check, not a general transcription score.
    """
    if generation_tokens < MAX_TOKENS:
        return None
    words = re.findall(r"[\u3400-\u9fff]|[^\W_\u3400-\u9fff]+(?:['’][^\W_\u3400-\u9fff]+)*", text.casefold())
    for width in range(1, 5):
        phrase = words[-width:]
        end, repeats = len(words), 0
        while end >= width and words[end-width:end] == phrase:
            repeats += 1
            end -= width
        if repeats >= 32 and repeats * width * 2 > len(words):
            return dict(phrase_units=width, repeats=repeats, total_units=len(words))
    return None


class RepetitionReviewError(RuntimeError):
    def __init__(self, review):
        super().__init__('识别结果持续重复，恢复识别未成功；原录音和已有文字保留，请保留录音并重试识别。')
        self.review = review


def checked_generate(model, pcm, **parameters):
    """Leave normal generation unchanged; recover once on the same full PCM.

    No rejected hypothesis reaches the online submission/window state. Failure
    uses the existing surfaced ASR error path, rather than returning empty text
    or claiming that unrecognized audio was successfully consumed.
    """
    return checked_generation(lambda **options: model.generate(pcm, **options),
                              lambda result: (result.text, result.generation_tokens), parameters)


def checked_generation(generate, inspect, parameters):
    result = generate(**parameters)
    text, tokens = inspect(result)
    repeated = repetitive_tail(text, tokens)
    if repeated is None:
        return result, None
    review = dict(**repeated, generation_tokens=tokens,
                  max_tokens=MAX_TOKENS, attempts=2, outcome='failed')
    try:
        recovered = generate(**{**parameters, 'repetition_penalty': 1.1})
        recovered_text, recovered_tokens = inspect(recovered)
    except Exception as exc:
        raise RepetitionReviewError(review) from exc
    review['recovery_tokens'] = recovered_tokens
    if not recovered_text.strip() or repetitive_tail(recovered_text, recovered_tokens):
        raise RepetitionReviewError(review)
    review['outcome'] = 'recovered'
    return recovered, review
