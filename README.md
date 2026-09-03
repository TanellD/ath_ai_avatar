# AI Avatar Trainer PoC

Браузерный PoC диалогового тренажёра с говорящим 3D-аватаром. Текущий сценарий:

`текст пользователя → LLM → Soniox TTS → avatar-aith + lip-sync`

## Требования

- Node.js 22 или новее
- ключи Soniox и VseLLM

## Установка

```bash
npm install
```

Скопируйте `.env.example` в `.env` и заполните значения:

```dotenv
SONIOX_API_KEY=your_soniox_api_key
VSELLM_API_KEY=your_vsellm_api_key
```

Файл `.env` содержит секреты и не должен попадать в Git.

## Запуск

```bash
npm start
```

Откройте <http://localhost:3001/>.

## Стек

- Node.js и Express
- VseLLM через OpenAI-compatible API
- `google/gemini-2.5-flash`
- Soniox TTS, голос Nina
- TalkingHead для 3D-аватара
- HeadAudio для lip-sync по фактически воспроизводимому аудио
- `avatar-aith.glb`

Сервер публикует только каталог `public/`. Основные API-ключи читаются на сервере из окружения. Браузер может получить только краткоживущий temporary key Soniox через защищённый простым rate limit endpoint `/tts-tmp-key`.

## Attribution и лицензии

Проект использует [TalkingHead](https://github.com/met4citizen/TalkingHead) и [HeadAudio](https://github.com/met4citizen/HeadAudio), созданные Mika Suominen и распространяемые по лицензии MIT.

- Лицензия TalkingHead: [`LICENSE`](LICENSE)
- Лицензия HeadAudio: [`HeadAudio/LICENSE`](HeadAudio/LICENSE)
- Копия лицензии для публикуемых модулей HeadAudio: [`public/vendor/headaudio/LICENSE`](public/vendor/headaudio/LICENSE)

Copyright notices в исходных файлах сторонних компонентов сохранены.
