from linguaflow.caption_changes import revision_note


def test_real_changes_not_fake_typing():
    assert revision_note("The", "The Gaussian distribution") == ""
    assert revision_note("The golden distribution", "The Gaussian distribution") == "原文修订：golden → Gaussian"
    assert "撤回" in revision_note("The wrong word", "The word")
    assert revision_note("same", "same") == ""
