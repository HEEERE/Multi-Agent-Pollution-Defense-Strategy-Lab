import { useState } from "react";
import { ChevronDown, ChevronRight, Save, RotateCcw } from "lucide-react";

interface SettingsSectionProps {
  title: string;
  desc?: string;
  icon: React.ReactNode;
  defaultExpanded?: boolean;
  onSave: () => void;
  onReset: () => void;
  saving: boolean;
  children: React.ReactNode;
}

export function SettingsSection({ title, desc, icon, defaultExpanded = false, onSave, onReset, saving, children }: SettingsSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 px-4 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50"
      >
        <span className="text-teal-600">{icon}</span>
        <span className="flex-1 text-left">{title}</span>
        {desc && <span className="mr-2 text-xs text-slate-400 hidden sm:inline">{desc}</span>}
        {expanded ? <ChevronDown size={16} className="text-slate-400" /> : <ChevronRight size={16} className="text-slate-400" />}
      </button>
      {expanded && (
        <div className="border-t border-slate-100 px-4 py-4">
          <div className="space-y-4">{children}</div>
          <div className="mt-5 flex gap-2 border-t border-slate-100 pt-4">
            <button
              onClick={onSave}
              disabled={saving}
              className="inline-flex items-center gap-1.5 rounded-md bg-teal-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-teal-700 disabled:opacity-50"
            >
              <Save size={13} />
              {saving ? "Saving..." : "Save Changes"}
            </button>
            <button
              onClick={onReset}
              className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
            >
              <RotateCcw size={13} />
              Reset to Defaults
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Reusable form field components ── */

export function ToggleField({ label, description, value, onChange }: {
  label: string; description?: string; value: boolean; onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-3">
      <input
        type="checkbox"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
        className="peer sr-only"
      />
      <div className="h-5 w-9 rounded-full bg-slate-200 peer-checked:bg-teal-500 transition-colors relative after:absolute after:top-0.5 after:left-0.5 after:h-4 after:w-4 after:rounded-full after:bg-white after:transition-transform peer-checked:after:translate-x-4" />
      <div>
        <span className="text-sm text-slate-700">{label}</span>
        {description && <p className="text-xs text-slate-400">{description}</p>}
      </div>
    </label>
  );
}

export function SliderField({ label, value, min, max, step, onChange }: {
  label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void;
}) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <label className="text-sm text-slate-600">{label}</label>
        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-mono text-slate-500">{value}</span>
      </div>
      <input
        type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="h-1.5 w-full appearance-none rounded-full bg-slate-200 accent-teal-500"
      />
    </div>
  );
}

export function NumberField({ label, value, min, max, step, onChange }: {
  label: string; value: number; min: number; max: number; step?: number; onChange: (v: number) => void;
}) {
  return (
    <div className="flex items-center justify-between">
      <label className="text-sm text-slate-600">{label}</label>
      <input
        type="number" min={min} max={max} step={step ?? 1} value={value}
        onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
        className="w-24 rounded border border-slate-200 px-2 py-1 text-sm text-slate-700 focus:border-teal-400 focus:outline-none"
      />
    </div>
  );
}

export function TextField({ label, value, type, placeholder, onChange }: {
  label: string; value: string; type?: string; placeholder?: string; onChange: (v: string) => void;
}) {
  return (
    <div className="flex items-center justify-between">
      <label className="text-sm text-slate-600 shrink-0">{label}</label>
      <input
        type={type ?? "text"} value={value} placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="ml-3 w-56 rounded border border-slate-200 px-2 py-1 text-sm text-slate-700 focus:border-teal-400 focus:outline-none"
      />
    </div>
  );
}

export function SelectField({ label, value, options, onChange }: {
  label: string; value: string; options: { value: string; label: string }[]; onChange: (v: string) => void;
}) {
  return (
    <div className="flex items-center justify-between">
      <label className="text-sm text-slate-600">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-36 rounded border border-slate-200 px-2 py-1 text-sm text-slate-700 focus:border-teal-400 focus:outline-none"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  );
}

export function TextAreaField({ label, value, placeholder, rows, onChange }: {
  label: string; value: string; placeholder?: string; rows?: number; onChange: (v: string) => void;
}) {
  return (
    <div>
      <label className="mb-1 block text-sm text-slate-600">{label}</label>
      <textarea
        value={value} placeholder={placeholder} rows={rows ?? 2}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded border border-slate-200 px-2 py-1.5 text-sm text-slate-700 focus:border-teal-400 focus:outline-none"
      />
    </div>
  );
}
