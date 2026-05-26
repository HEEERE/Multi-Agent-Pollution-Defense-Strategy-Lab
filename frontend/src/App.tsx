import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import { Activity, FlaskConical, PlayCircle } from "lucide-react";
import { LiveMonitor } from "./pages/LiveMonitor";
import { ExperimentStudio } from "./pages/ExperimentStudio";
import { ReplayAnalyzer } from "./pages/ReplayAnalyzer";

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex h-screen flex-col bg-slate-100">
        <nav className="flex h-11 shrink-0 items-center gap-1 border-b border-slate-200 bg-white px-4">
          <NavItem to="/" icon={<Activity size={15} />} label="Live Monitor" />
          <NavItem to="/experiments" icon={<FlaskConical size={15} />} label="Experiment Studio" />
          <NavItem to="/replay" icon={<PlayCircle size={15} />} label="Replay Analyzer" />
          <div className="ml-auto text-xs text-slate-400">
            Multi-Agent Cascading Pollution Detection & Defense Platform
          </div>
        </nav>
        <div className="min-h-0 flex-1">
          <Routes>
            <Route path="/" element={<LiveMonitor />} />
            <Route path="/experiments" element={<ExperimentStudio />} />
            <Route path="/replay" element={<ReplayAnalyzer />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  );
}

function NavItem({ to, icon, label }: { to: string; icon: React.ReactNode; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-xs font-medium transition ${
          isActive
            ? "bg-teal-50 text-teal-700"
            : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
        }`
      }
    >
      {icon}
      {label}
    </NavLink>
  );
}
