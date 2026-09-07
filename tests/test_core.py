from linguaflow.core import Caption, export_srt, srt_time


def test_srt_rollover_and_bilingual_output():
    assert srt_time(3599.9996) == "01:00:00,000"
    assert export_srt([Caption(7, 1.25, 2.75, "Hello", "en", "你好")]) == (
        "1\n00:00:01,250 --> 00:00:02,750\nHello\n你好\n"
    )
