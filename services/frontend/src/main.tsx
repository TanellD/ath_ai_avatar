import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import { App } from '@/App';
// Дизайн-система «Clarity UI» — извлечена из макетов front/*.dc.html
// (см. front/ds/clarity-ui.css, откуда скопирован 1:1). styles.css идёт
// после и переопределяет только то, что специфично для этого приложения
// (полноэкранный SPA-шелл вместо скролла страницы целиком, и т.д.).
import '@/styles/clarity-ui.css';
import '@/styles.css';

const container = document.getElementById('root');
if (!container) throw new Error('#root not found');

createRoot(container).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
