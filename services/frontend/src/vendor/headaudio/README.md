# HeadAudio — главный поток

Дерево модулей, которое `TalkingHeadAvatar.tsx` импортирует обычным `import`.
Не npm-пакет — собранный рантайм HeadAudio (met4citizen/HeadAudio, MIT),
скопированный сюда, а не установленный.

Живёт в `src/`, а не в `public/`, потому что Vite не даёт импортировать
файлы из `public/` как ES-модуль в dev-режиме. Ворклет-часть того же рантайма
(`headworklet.mjs` и его зависимости) осталась в
`public/vendor/headaudio/` — она грузится по URL через
`audioWorklet.addModule()`, а не через `import`, и обязана оставаться там.
Подробности и почему `parameters.mjs` продублирован — README рядом с
ворклет-частью.

Лицензия — `public/vendor/headaudio/LICENSE`, одна на весь рантайм.
