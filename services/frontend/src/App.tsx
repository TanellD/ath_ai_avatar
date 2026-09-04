import { Link, Navigate, Route, Routes } from 'react-router-dom';

import { AdminSessionDetail } from '@/pages/AdminSessionDetail';
import { AdminSessions } from '@/pages/AdminSessions';
import { EmotionLab } from '@/pages/EmotionLab';
import { MethodistReport } from '@/pages/MethodistReport';
import { MethodistScenarios } from '@/pages/MethodistScenarios';
import { TraineeSession } from '@/pages/TraineeSession';

/**
 * Две роли по постановке (Claude.md §2): методист и сотрудник.
 * Отдельной роли администратора нет — в кейсе её нет.
 *
 * `/admin/*` — не третья роль продукта, а инструмент отладки конвейера
 * (путь сессии + Gantt операций из app/tracing.py), поэтому вынесен из
 * основной навигации и живёт отдельной ссылкой.
 *
 * Авторизации нет: §4 выводит её из скоупа. Роль определяется маршрутом.
 */
export function App() {
  return (
    <div className="app">
      <nav className="app__nav">
        <Link to="/scenarios">Сценарии</Link>
        <Link to="/emotion-lab" className="app__nav-tool">Эмоции</Link>
        <Link to="/admin/sessions" className="app__nav-admin">
          Админ-панель
        </Link>
      </nav>

      <div className="app__body">
        <Routes>
          <Route path="/" element={<Navigate to="/scenarios" replace />} />
          <Route path="/scenarios" element={<MethodistScenarios />} />
          <Route path="/session/:scenarioId" element={<TraineeSession />} />
          <Route path="/emotion-lab" element={<EmotionLab />} />
          <Route path="/report/:sessionId" element={<MethodistReport />} />
          <Route path="/admin/sessions" element={<AdminSessions />} />
          <Route path="/admin/sessions/:sessionId" element={<AdminSessionDetail />} />
          <Route path="*" element={<p className="page">Страница не найдена</p>} />
        </Routes>
      </div>
    </div>
  );
}
