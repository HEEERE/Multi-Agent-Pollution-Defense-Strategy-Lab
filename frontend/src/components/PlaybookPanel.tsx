import { Play, RotateCcw } from "lucide-react";

import type { PlaybookSummary } from "../types";

interface PlaybookPanelProps {
  playbooks: PlaybookSummary[];
  activeId: string | null;
  onRun: (id: string) => void;
  onReset: () => void;
}

export function PlaybookPanel({ playbooks, activeId, onRun, onReset }: PlaybookPanelProps) {
  return (
    <div className="absolute left-5 top-5 z-10 w-[330px] rounded-lg border border-slate-200 bg-white p-3 shadow-signal">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold text-slate-950">Playbooks</div>
          <div className="text-xs text-slate-500">Trigger animation scenarios</div>
        </div>
        <button
          className="inline-flex h-8 w-8 items-center justify-center rounded border border-slate-200 text-slate-600 hover:bg-slate-100"
          onClick={onReset}
          title="Reset topology"
          type="button"
        >
          <RotateCcw size={15} />
        </button>
      </div>
      <div className="max-h-[360px] space-y-2 overflow-y-auto pr-1">
        {playbooks.map((playbook) => (
          <button
            className="flex w-full items-start gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-left transition hover:border-teal-400 hover:bg-white disabled:cursor-wait disabled:opacity-60"
            disabled={activeId !== null}
            key={playbook.id}
            onClick={() => onRun(playbook.id)}
            type="button"
          >
            <span className="mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded border border-slate-200 bg-white text-teal-700">
              <Play size={14} />
            </span>
            <span className="min-w-0">
              <span className="block text-xs font-semibold text-slate-900">{playbook.name}</span>
              <span className="mt-1 line-clamp-2 block text-xs leading-5 text-slate-500">{playbook.description}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
