/**
 * Палитра и оформление графиков админ-панели.
 *
 * Литералы, а не var(--blue): recharts кладёт цвет в SVG-атрибут
 * stroke/fill, а туда CSS-переменная не подставляется. Значения — копия
 * соответствующих токенов из styles/clarity-ui.css; при смене палитры
 * менять здесь тоже.
 */

export const CHART_COLORS = {
  blue: '#2456E6',
  ink3: '#5C6D89',
  line: '#E2E8F2',
  danger: '#b3352f',
};

export const AXIS_TICK = { fontSize: 10, fill: CHART_COLORS.ink3 };
