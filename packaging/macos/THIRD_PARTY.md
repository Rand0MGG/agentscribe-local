# Binary distribution notices

AgentScribe uses Qt and PySide6 6.11.2, Copyright (C) The Qt Company Ltd. and
contributors, under LGPL-3.0 (with separately licensed third-party components).
Their LGPL/GPL license texts, module attribution records and referenced license
files are in `Qt-PySide/`. The matching Qt 6.11.2 documentation's full third-party notices
(including Chromium/PDFium) are indexed in `QtWebEngine-credits.html`. Unused Qt developer applications and unrelated
Qt modules are omitted. Used Qt libraries remain dynamically linked.

Exact upstream sources for Qt 6.11.2 are available from
https://download.qt.io/official_releases/Qt/6.11/6.11.2/submodules/ and tagged
repositories at https://github.com/qt; PySide/Shiboken sources are at
https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v6.11.2 . Each retained
notice file's source URL and SHA-256 are pinned in the build configuration.
No Qt/PySide source code is patched. Universal libraries are thinned to arm64
and signed locally; binary install names and stale build search paths are
normalized for relocation. The Python application remains readable source.

To use interface-compatible modified libraries for debugging, work on a copy
of the application, replace the corresponding libraries under
`Contents/Frameworks/Python.framework/Versions/A/lib/python3.12/site-packages/`, and sign changed
Mach-O files, nested frameworks/helper apps and finally the outer app with
`codesign --force --sign - --timestamp=none`. Sign inside out; the build script
demonstrates this order. No library-validation/hardened-runtime restriction is
enabled in this ad-hoc test package. Reverse engineering for debugging such
modifications is permitted; this notice does not grant a license to unrelated
application code.

CPython 3.12.15 and its portable build are supplied by
https://github.com/astral-sh/python-build-standalone/releases/tag/20261003 .
The CPython license is `Python-LICENSE.txt`; portable Python's bundled libraries
retain their notices. Node.js 22.23.0 and its bundled libraries/npm notices are
retained under `Contents/Frameworks/Node.app/Contents/Resources/node/` (its
executable is in the helper's MacOS directory); `Node-LICENSE.txt` is a
convenient copy. Sources: https://nodejs.org/dist/v22.23.0/ .

Other desktop Python packages retain original `.dist-info` metadata and supplied
license files under the portable Python's `site-packages`. Exact versions and
original wheel SHA-256 values are in `../desktop.lock`.
See `../THIRD_PARTY_NOTICES.md` for optional runtime/model and DSH adapter notices.
Weights and optional LibreOffice/PDFium/llama.cpp runtimes are downloaded
separately; those installers preserve their upstream notices and source material.
