// Compile-only regressions. This function is never imported or executed.
import { request } from './types';
function checkDesktopContract() {
  request('recording.start');
  request('audio.select', { identifier: 'fixture', loopback: false });
  // @ts-expect-error Unknown command.
  request('recording.strat');
  // @ts-expect-error Missing required source selection.
  request('audio.select');
  // @ts-expect-error No renderer-owned destination paths.
  request('library.migrate', { path: '/outside' });
  // @ts-expect-error A playback offset cannot be text.
  request('playback.seek', { milliseconds: '100' });
  // @ts-expect-error Internal lifecycle methods never enter the renderer API.
  request('app.close');
  request('captions.page').then(page => {
    page.rows.map(row => row.source);
    // @ts-expect-error Captions are typed domain values.
    page.rows.map(row => row.nonexistent);
  });
}
void checkDesktopContract;
