"""Incremental planner preserves context snapshots through historical edits."""
from dataclasses import replace

from linguaflow.core import Caption
from linguaflow.translation_context import ContextPlanner, TranslationContext


def test_out_of_order_deltas_use_all_neighbours_and_removal_updates_adjacency():
    planner = ContextPlanner(2, 1)
    rows = [Caption(i, i, i + 1, f'row {i}', 'en') for i in range(5)]
    jobs = planner.update_changes(reversed(rows))
    assert [c.id for c in jobs] == list(range(5))
    assert planner.get(2) == TranslationContext(('row 0', 'row 1'), ('row 3',))
    old_context = planner.get(2)
    assert planner.update_changes([replace(rows[1], source='', revision=2)]) == []
    assert not planner.accepts(jobs[1])
    assert planner.get(1) is None
    assert planner.adjacent(jobs[0], jobs[2])
    assert planner.get(2) == old_context  # A neighbour's removal does not retrigger frozen requests.
    fixed = replace(rows[2], source='corrected', revision=2)
    assert planner.update_changes([fixed])[0].source == 'corrected'
    assert planner.get(2) == TranslationContext(('row 0',), ('row 3',))


def test_reopened_historical_row_rejects_old_final_and_finalizes_with_current_background():
    planner = ContextPlanner()
    rows = [Caption(i, i, i + 1, f'row {i}', 'en') for i in range(500)]
    jobs = planner.update_changes(rows)
    reopened = replace(rows[3], source='reopened', revision=2, final=False, ready=False)
    assert planner.update_changes([reopened]) == []
    assert not planner.accepts(jobs[3]) and planner.get(3) is None
    submitted = replace(reopened, ready=True)
    initial = planner.update_changes([submitted])[0]
    assert initial.translation_phase == 'initial'
    assert planner.get(3) == TranslationContext(('row 2',), ('row 4',))
    final = replace(submitted, final=True, revision=3)
    assert planner.update_changes([final])[0].translation_phase == 'final'
    assert not planner.accepts(initial)
    assert planner.get(3) == TranslationContext(('row 0', 'row 1', 'row 2'), ('row 4',))


def test_position_change_updates_stable_index_without_retranslating_unchanged_source():
    planner = ContextPlanner(2, 1)
    rows = [Caption(i, i, i + 1, f'row {i}', 'en') for i in range(3)]
    jobs = planner.update_changes(rows)
    moved = replace(rows[2], start=.5, end=.9, revision=2)
    assert planner.update_changes([moved]) == []
    assert planner.adjacent(jobs[0], jobs[2])
    corrected = replace(rows[1], source='new source', revision=2)
    planner.update_changes([corrected])
    assert planner.get(1) == TranslationContext(('row 0', 'row 2'))
    assert planner.update_changes([]) == []
    planner.update_changes([replace(moved, source='')])
    assert planner.adjacent(jobs[0], jobs[1])


def test_full_snapshot_compatibility_removes_unsubmitted_rows_and_freezes_mutable_input():
    planner = ContextPlanner()
    row = Caption(1, 0, 1, 'draft', 'en', final=False)
    assert planner.update([row]) == []
    row.ready = True
    assert planner.update([row])[0].source == 'draft'
    row.source, row.revision = 'updated', 2
    assert planner.update([row])[0].source == 'updated'
    assert planner.update([]) == []
    assert planner.get(1) is None
    assert planner.update_changes([replace(row, final=True)])[0].translation_phase == 'final'
