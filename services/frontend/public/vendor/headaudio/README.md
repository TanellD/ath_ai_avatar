# HeadAudio — только ворклет-дерево

`headaudio.mjs` и `training.mjs` (главный поток) переехали в
`src/vendor/headaudio/` — Vite не даёт импортировать файлы из `public/` как ES-
модуль в dev-режиме («This file is in /public and will be copied as-is...»),
только через `fetch`/`<script src>`/`audioWorklet.addModule`.

Здесь остаётся только то, что и так грузится по URL, а не через `import`:

- `headworklet.mjs` → `processor.mjs` → `classifier.mjs`, `mfcc.mjs`,
  `ringbuffer.mjs`, `vadgate.mjs` — дерево процессора AudioWorklet. Ворклет
  выполняется в отдельном глобальном контексте и не может делить бандл с
  главным потоком, поэтому обязан оставаться отдельным файлом, доступным по
  стабильному URL (`audioWorklet.addModule(url)`), а не частью сборки.
- `model-en-mixed.bin` — бинарная модель, грузится `fetch(url)` изнутри
  `training.mjs`.
- `parameters.mjs` — **сознательно продублирован** с `src/vendor/headaudio/`:
  главный поток и ворклет — разные контексты выполнения, общий модуль между
  ними не работает, поэтому у каждого своя копия.

См. `services/frontend/src/avatar/TalkingHeadAvatar.tsx` и
`docs/engineering/architecture.md`.
