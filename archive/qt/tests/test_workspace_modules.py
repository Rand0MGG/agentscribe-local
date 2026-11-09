import pytest
from ui_support import run_ui_process


@pytest.mark.p2
def test_workspace_components_own_state_without_importing_main_window():
    run_ui_process(r'''
import sys
from dataclasses import replace
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
from linguaflow.caption_feed import CaptionFeed
from linguaflow.core import Caption
from linguaflow.library_browser import LibraryTree
from linguaflow.legacy_playback import PlaybackController
from linguaflow.recording_controls import RecordingControls
from linguaflow.transcript import Transcript
assert 'linguaflow.app' not in sys.modules
app=QApplication([])
feed=CaptionFeed()
feed.rows=Transcript({i:Caption(i,i,i+1,str(i),'en') for i in range(1,1001)})
feed.render()
assert len(feed.cards)==200 and min(feed.cards)==801
order=feed.rows.ordered_ids
card=feed.cards[1000]
feed.set_caption(replace(feed.rows[1000],translation='updated'))
assert feed.cards[1000] is card and card.target.text()=='updated'
assert feed.rows.ordered_ids is order
feed.change_page(-1)
assert len(feed.cards)==200 and min(feed.cards)==621
feed.set_preview(dict(source='latest words',start=999,end=1001,language='en',keep_ids=list(range(1,1000))))
assert feed.preview_card.source.text()=='latest words'
feed.clear()
assert not feed.cards and not feed.rows and feed.preview is None
tree=LibraryTree()
index={'folders':[{'id':'f','name':'Folder'}], 'sessions':[{'id':'r','folder':'f','name':'Recording'}]}
assert tree.populate(index,current_id='r')['id']=='r'
tree.rows['f'].setExpanded(False)
tree.populate(index,current_id='r')
assert not tree.rows['f'].isExpanded() and tree.currentItem() is tree.rows['r']
controls=RecordingControls(feed.viewport())
assert controls.start_button.isEnabled() and not controls.stop_button.isEnabled()
playback=PlaybackController()
events=[]
playback.player=SimpleNamespace(stop=lambda:events.append('stop'),setSource=lambda _:events.append('clear'))
playback.stream=SimpleNamespace(close=lambda:events.append('close'),deleteLater=lambda:events.append('delete'))
playback.release()
assert events==['stop','clear','close','delete'] and playback.stream is None
playback.release()
assert events[-2:]==['stop','clear']
controls.hide();feed.close();tree.close()
''', timeout=30)
