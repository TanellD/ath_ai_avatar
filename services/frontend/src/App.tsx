import { Link, Navigate, Route, Routes } from 'react-router-dom';

import { MethodistReport } from '@/pages/MethodistReport';
import { MethodistScenarios } from '@/pages/MethodistScenarios';
import { TraineeSession } from '@/pages/TraineeSession';

/**
 * Две роли по постановке (Claude.md §2): методист и сотрудник.
 * Отдельной роли администратора нет — в кейсе её нет.
 *
 * Авторизации тоже нет: §4 выводит её из скоупа. Роль определяется маршрутом.
 */
export function App() {
  return (
    <div className="app">
      <nav className="app__nav">
        <Link to="/scenarios">Сценарии</Link>
      </nav>

      <Routes>
        <Route path="/" element={<Navigate to="/scenarios" replace />} />
        <Route path="/scenarios" element={<MethodistScenarios />} />
        <Route path="/session/:scenarioId" element={<TraineeSession />} />
        <Route path="/report/:sessionId" element={<MethodistReport />} />
        <Route path="*" element={<p className="page">Страница не найдена</p>} />
      </Routes>
    </div>
  );
}
