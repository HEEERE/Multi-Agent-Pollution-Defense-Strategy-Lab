import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Loading } from "./components/common/Loading";
import { AppShell } from "./components/layout/AppShell";

const Benchmark = lazy(() =>
  import("./pages/Benchmark").then((module) => ({ default: module.Benchmark })),
);
const Dashboard = lazy(() =>
  import("./pages/Dashboard").then((module) => ({ default: module.Dashboard })),
);
const DefenseCenter = lazy(() =>
  import("./pages/DefenseCenter").then((module) => ({
    default: module.DefenseCenter,
  })),
);
const Experiments = lazy(() =>
  import("./pages/Experiments").then((module) => ({
    default: module.Experiments,
  })),
);
const Playbooks = lazy(() =>
  import("./pages/Playbooks").then((module) => ({ default: module.Playbooks })),
);
const Replay = lazy(() =>
  import("./pages/Replay").then((module) => ({ default: module.Replay })),
);
const Runs = lazy(() =>
  import("./pages/Runs").then((module) => ({ default: module.Runs })),
);
const Settings = lazy(() =>
  import("./pages/Settings").then((module) => ({ default: module.Settings })),
);
const StrategyLab = lazy(() =>
  import("./pages/StrategyLab").then((module) => ({
    default: module.StrategyLab,
  })),
);
const TraceExplorer = lazy(() =>
  import("./pages/TraceExplorer").then((module) => ({
    default: module.TraceExplorer,
  })),
);

export function App() {
  return (
    <Suspense
      fallback={
        <div className="grid min-h-screen place-items-center bg-ink-950">
          <Loading label="正在加载工作台" />
        </div>
      }
    >
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Dashboard />} />
          <Route path="strategies" element={<StrategyLab />} />
          <Route path="runs" element={<Runs />} />
          <Route path="runs/:runId" element={<Runs />} />
          <Route path="traces" element={<TraceExplorer />} />
          <Route path="replay" element={<Replay />} />
          <Route path="replay/:traceId" element={<Replay />} />
          <Route path="playbooks" element={<Playbooks />} />
          <Route path="experiments" element={<Experiments />} />
          <Route path="benchmark" element={<Benchmark />} />
          <Route path="defense" element={<DefenseCenter />} />
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
