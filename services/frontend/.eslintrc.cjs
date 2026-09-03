/**
 * Правило ниже — не стилистика, а механическая защита ограничения из Claude.md §3:
 *
 *   «Источник времени для мимики — фактически воспроизводимое аудио, а не
 *    независимый таймер. Никаких setInterval, только AudioContext.currentTime
 *    или HTMLAudioElement.currentTime.»
 *
 * Требование, которое держится только на памяти разработчика, рано или поздно
 * нарушается — обычно в последний вечер перед демо, когда «просто надо, чтобы
 * губы двигались». Здесь оно ломает сборку.
 */
module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  parser: '@typescript-eslint/parser',
  parserOptions: { ecmaVersion: 'latest', sourceType: 'module' },
  plugins: ['@typescript-eslint', 'react-hooks'],
  ignorePatterns: ['dist', 'node_modules', '*.cjs'],
  rules: {
    '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
  },
  overrides: [
    {
      files: ['src/audio/**/*.ts', 'src/audio/**/*.tsx', 'src/avatar/**/*.ts', 'src/avatar/**/*.tsx'],
      rules: {
        'no-restricted-globals': [
          'error',
          {
            name: 'setInterval',
            message:
              'Claude.md §3: часы системы — воспроизводимое аудио. Используйте ' +
              'PlaybackClock (AudioContext.currentTime), а не таймер.',
          },
          {
            name: 'setTimeout',
            message:
              'Claude.md §3: тайминги мимики и субтитров считываются из currentTime ' +
              'аудио. Если нужен отложенный вызов не по аудио — вынесите его за ' +
              'пределы src/audio и src/avatar.',
          },
        ],
        'no-restricted-properties': [
          'error',
          {
            object: 'window',
            property: 'setInterval',
            message: 'Claude.md §3: см. PlaybackClock.',
          },
        ],
      },
    },
  ],
};
