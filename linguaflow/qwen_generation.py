"""Review official Qwen generation without replacing its audio/text preprocessing."""
from . import diagnostic_log as diag
from .asr_review import MAX_TOKENS, RepetitionReviewError, checked_generation


def install_generation_review(asr):
    # This instance belongs to one serialized online decoder. Keep the package's
    # transcribe/preprocess/parse path; observe its raw generated IDs before it
    # discards token-count metadata. No global patch or generation-config change.
    original = asr.model.generate

    def generate(*args, **parameters):
        prompt_tokens = parameters['input_ids'].shape[1]

        def inspect(result):
            sequences = result.sequences
            if sequences.shape[0] != 1:
                raise ValueError('Qwen 结果审查要求单条生成，未提交未核验的结果。')
            count = sequences.shape[1] - prompt_tokens
            # Decoding again is needed only for capped candidates, or recovery
            # where an empty result must be rejected.
            text = asr.processor.batch_decode(sequences[:, prompt_tokens:],
                skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]
            return text, count

        first = True
        def inspect_candidate(result):
            nonlocal first
            count = result.sequences.shape[1] - prompt_tokens
            if first and count < MAX_TOKENS:
                first = False
                return '', count
            first = False
            return inspect(result)

        try:
            result, review = checked_generation(lambda **options: original(*args, **options),
                                                inspect_candidate, parameters)
        except RepetitionReviewError as exc:
            diag.event('asr_repetition_review', **exc.review)
            raise
        if review:
            diag.event('asr_repetition_review', **review)
        return result

    asr.model.generate = generate
