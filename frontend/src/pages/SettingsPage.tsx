import { useCallback, useEffect, useState } from "react";
import { Shield, Cpu, Users, Wrench } from "lucide-react";
import { useStore } from "../store";
import { useT } from "../i18n/context";
import type { SettingsCategory } from "../types";
import { SettingsSection, ToggleField, SliderField, NumberField, TextField, SelectField, TextAreaField } from "../components/SettingsSection";
import { Toast, type ToastState } from "../components/Toast";

const ACTION_OPTIONS = [
  { value: "alert", label: "Alert" },
  { value: "block", label: "Block" },
  { value: "quarantine", label: "Quarantine" },
  { value: "isolate", label: "Isolate" },
];

const SEVERITY_OPTIONS = [
  { value: "info", label: "Info" },
  { value: "warning", label: "Warning" },
  { value: "critical", label: "Critical" },
];

function getBool(vals: Record<string, unknown>, key: string, def: boolean): boolean {
  const v = vals[key];
  if (typeof v === "boolean") return v;
  return def;
}

function getNum(vals: Record<string, unknown>, key: string, def: number): number {
  const v = vals[key];
  if (typeof v === "number") return v;
  return def;
}

function getStr(vals: Record<string, unknown>, key: string, def: string): string {
  const v = vals[key];
  if (typeof v === "string") return v;
  return def;
}

export function SettingsPage() {
  const { t } = useT();
  const { settings, settingsLoading, fetchSettings, updateCategory, resetCategory } = useStore();
  const [toast, setToast] = useState<ToastState | null>(null);
  const [savingCategory, setSavingCategory] = useState<string | null>(null);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  const vals: Record<string, Record<string, unknown>> = (settings?.categories ?? {}) as Record<string, Record<string, unknown>>;

  const showToast = useCallback((type: "success" | "error", message: string) => {
    setToast({ type, message });
  }, []);

  const handleSave = useCallback(async (category: SettingsCategory, values: Record<string, unknown>) => {
    setSavingCategory(category);
    const ok = await updateCategory(category, values);
    setSavingCategory(null);
    showToast(ok ? "success" : "error", ok ? t("settings.saved") : t("settings.saveFailed"));
  }, [updateCategory, showToast, t]);

  const handleReset = useCallback(async (category: SettingsCategory) => {
    if (!window.confirm(t("settings.resetConfirm"))) return;
    setSavingCategory(category);
    await resetCategory(category);
    setSavingCategory(null);
    showToast("success", `"${category}" ${t("settings.resetOk")}`);
  }, [resetCategory, showToast, t]);

  if (settingsLoading && !settings) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-slate-400">{t("settings.loading")}</p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl p-6">
      <Toast toast={toast} onDismiss={() => setToast(null)} />
      <div className="mb-6">
        <h1 className="text-lg font-semibold text-slate-800">{t("settings.title")}</h1>
        <p className="mt-1 text-sm text-slate-500">{t("settings.subtitle")}</p>
      </div>

      <div className="space-y-3">
        <DetectorSection
          vals={vals.detectors ?? {}}
          saving={savingCategory === "detectors"}
          onSave={(v) => handleSave("detectors", v)}
          onReset={() => handleReset("detectors")}
        />
        <LLMSection
          vals={vals.llm ?? {}}
          saving={savingCategory === "llm"}
          onSave={(v) => handleSave("llm", v)}
          onReset={() => handleReset("llm")}
        />
        <AgentSection
          vals={vals.agents ?? {}}
          saving={savingCategory === "agents"}
          onSave={(v) => handleSave("agents", v)}
          onReset={() => handleReset("agents")}
        />
        <SystemSection
          vals={vals.system ?? {}}
          saving={savingCategory === "system"}
          onSave={(v) => handleSave("system", v)}
          onReset={() => handleReset("system")}
        />
      </div>
    </div>
    </div>
  );
}

/* ── Helpers ── */

function Desc({ text }: { text: string }) {
  return <p className="text-[11px] text-slate-400 mt-0.5 ml-7">{text}</p>;
}

/* ── Detector Section ── */

function DetectorSection({ vals, saving, onSave, onReset }: {
  vals: Record<string, unknown>;
  saving: boolean;
  onSave: (v: Record<string, unknown>) => void;
  onReset: () => void;
}) {
  const { t } = useT();
  const [local, setLocal] = useState(vals);
  useEffect(() => { setLocal(vals); }, [vals]);

  const set = (k: string, v: unknown) => setLocal((p) => ({ ...p, [k]: v }));
  const save = () => onSave(local);

  return (
    <SettingsSection title={t("settings.detectors")} desc={t("settings.detectors.desc")} icon={<Shield size={16} />} defaultExpanded onSave={save} onReset={onReset} saving={saving}>
      <fieldset className="space-y-2 rounded border border-slate-100 p-3">
        <legend className="text-xs font-medium text-slate-500">{t("settings.l1")}</legend>
        <ToggleField label={t("settings.l1.enabled")} value={getBool(local, "regex.enabled", true)} onChange={(v) => set("regex.enabled", v)} />
        <Desc text={t("settings.l1.enabled.desc")} />
        <SelectField label={t("settings.l1.action")} value={getStr(local, "regex.action_policy", "block")} options={ACTION_OPTIONS} onChange={(v) => set("regex.action_policy", v)} />
        <Desc text={t("settings.l1.action.desc")} />
      </fieldset>

      <fieldset className="space-y-2 rounded border border-slate-100 p-3">
        <legend className="text-xs font-medium text-slate-500">{t("settings.l2")}</legend>
        <SliderField label={t("settings.l2.threshold")} value={getNum(local, "semantic.threshold", 0.65)} min={0} max={1} step={0.01} onChange={(v) => set("semantic.threshold", v)} />
        <Desc text={t("settings.l2.threshold.desc")} />
        <NumberField label={t("settings.l2.topK")} value={getNum(local, "semantic.top_k", 5)} min={1} max={50} onChange={(v) => set("semantic.top_k", v)} />
        <Desc text={t("settings.l2.topK.desc")} />
        <NumberField label={t("settings.l2.minMatches")} value={getNum(local, "semantic.min_matches", 1)} min={1} max={10} onChange={(v) => set("semantic.min_matches", v)} />
        <Desc text={t("settings.l2.minMatches.desc")} />
        <ToggleField label={t("settings.l2.autoCalibrate")} value={getBool(local, "semantic.auto_calibrate", true)} onChange={(v) => set("semantic.auto_calibrate", v)} />
        <Desc text={t("settings.l2.autoCalibrate.desc")} />
        <SelectField label={t("settings.l2.action")} value={getStr(local, "semantic.action_policy", "quarantine")} options={ACTION_OPTIONS} onChange={(v) => set("semantic.action_policy", v)} />
      </fieldset>

      <fieldset className="space-y-2 rounded border border-slate-100 p-3">
        <legend className="text-xs font-medium text-slate-500">{t("settings.l3")}</legend>
        <ToggleField label={t("settings.l3.enabled")} value={getBool(local, "llm_intent.enabled", true)} onChange={(v) => set("llm_intent.enabled", v)} />
        <Desc text={t("settings.l3.enabled.desc")} />
        <ToggleField label={t("settings.l3.selfConsistency")} value={getBool(local, "llm_intent.self_consistency", true)} onChange={(v) => set("llm_intent.self_consistency", v)} />
        <Desc text={t("settings.l3.selfConsistency.desc")} />
        <NumberField label={t("settings.l3.votes")} value={getNum(local, "llm_intent.self_consistency_votes", 3)} min={1} max={5} onChange={(v) => set("llm_intent.self_consistency_votes", v)} />
        <Desc text={t("settings.l3.votes.desc")} />
        <SelectField label={t("settings.l3.action")} value={getStr(local, "llm_intent.action_policy", "quarantine")} options={ACTION_OPTIONS} onChange={(v) => set("llm_intent.action_policy", v)} />
      </fieldset>

      <fieldset className="space-y-2 rounded border border-slate-100 p-3">
        <legend className="text-xs font-medium text-slate-500">{t("settings.pipeline")}</legend>
        <SliderField label={t("settings.pipeline.fusionThreshold")} value={getNum(local, "pipeline.fusion_threshold", 0.82)} min={0.5} max={1} step={0.01} onChange={(v) => set("pipeline.fusion_threshold", v)} />
        <Desc text={t("settings.pipeline.fusionThreshold.desc")} />
        <ToggleField label={t("settings.pipeline.shortCircuit")} value={getBool(local, "pipeline.short_circuit", true)} onChange={(v) => set("pipeline.short_circuit", v)} />
        <Desc text={t("settings.pipeline.shortCircuit.desc")} />
        <ToggleField label={t("settings.pipeline.logAll")} value={getBool(local, "pipeline.log_all_detections", true)} onChange={(v) => set("pipeline.log_all_detections", v)} />
        <Desc text={t("settings.pipeline.logAll.desc")} />
        <SelectField label={t("settings.pipeline.minSeverity")} value={getStr(local, "pipeline.min_severity_for_llm", "warning")} options={SEVERITY_OPTIONS} onChange={(v) => set("pipeline.min_severity_for_llm", v)} />
        <Desc text={t("settings.pipeline.minSeverity.desc")} />
      </fieldset>

      <fieldset className="space-y-2 rounded border border-slate-100 p-3">
        <legend className="text-xs font-medium text-slate-500">{t("settings.honeypot")}</legend>
        <SliderField label={t("settings.honeypot.grayLow")} value={getNum(local, "honeypot.gray_zone_low", 0.50)} min={0} max={1} step={0.01} onChange={(v) => set("honeypot.gray_zone_low", v)} />
        <Desc text={t("settings.honeypot.grayLow.desc")} />
        <SliderField label={t("settings.honeypot.grayHigh")} value={getNum(local, "honeypot.gray_zone_high", 0.75)} min={0} max={1} step={0.01} onChange={(v) => set("honeypot.gray_zone_high", v)} />
        <Desc text={t("settings.honeypot.grayHigh.desc")} />
      </fieldset>
    </SettingsSection>
  );
}

/* ── LLM Section ── */

function LLMSection({ vals, saving, onSave, onReset }: {
  vals: Record<string, unknown>;
  saving: boolean;
  onSave: (v: Record<string, unknown>) => void;
  onReset: () => void;
}) {
  const { t } = useT();
  const [local, setLocal] = useState(vals);
  const [showKey, setShowKey] = useState(false);
  useEffect(() => { setLocal(vals); }, [vals]);

  const set = (k: string, v: unknown) => setLocal((p) => ({ ...p, [k]: v }));
  const save = () => onSave(local);

  return (
    <SettingsSection title={t("settings.llm")} desc={t("settings.llm.desc")} icon={<Cpu size={16} />} onSave={save} onReset={onReset} saving={saving}>
      <ToggleField label={t("settings.llm.enabled")} value={getBool(local, "llm.enabled", false)} onChange={(v) => set("llm.enabled", v)} />
      <Desc text={t("settings.llm.enabled.desc")} />
      <TextField label={t("settings.llm.provider")} value={getStr(local, "llm.provider", "mimo")} onChange={(v) => set("llm.provider", v)} />
      <TextField label={t("settings.llm.baseUrl")} value={getStr(local, "llm.base_url", "")} onChange={(v) => set("llm.base_url", v)} />
      <TextField label={t("settings.llm.model")} value={getStr(local, "llm.model", "")} onChange={(v) => set("llm.model", v)} />
      <div className="flex items-center justify-between">
        <label className="text-sm text-slate-600 shrink-0">{t("settings.llm.apiKey")}</label>
        <div className="ml-3 flex w-56 items-center gap-1">
          <input
            type={showKey ? "text" : "password"}
            value={getStr(local, "llm.api_key", "")}
            onChange={(e) => set("llm.api_key", e.target.value)}
            placeholder="sk-..."
            className="flex-1 rounded border border-slate-200 px-2 py-1 text-sm text-slate-700 focus:border-teal-400 focus:outline-none"
          />
          <button type="button" onClick={() => setShowKey(!showKey)} className="rounded border border-slate-200 px-2 py-1 text-xs text-slate-500 hover:bg-slate-50">
            {showKey ? t("settings.llm.apiKey.hide") : t("settings.llm.apiKey.show")}
          </button>
        </div>
      </div>
      <SliderField label={t("settings.llm.temperature")} value={getNum(local, "llm.temperature", 0.2)} min={0} max={2} step={0.05} onChange={(v) => set("llm.temperature", v)} />
      <Desc text={t("settings.llm.temperature.desc")} />
      <NumberField label={t("settings.llm.maxTokens")} value={getNum(local, "llm.max_tokens", 700)} min={50} max={32000} onChange={(v) => set("llm.max_tokens", v)} />
      <Desc text={t("settings.llm.maxTokens.desc")} />
      <NumberField label={t("settings.llm.timeout")} value={getNum(local, "llm.request_timeout", 45)} min={5} max={300} onChange={(v) => set("llm.request_timeout", v)} />
      <Desc text={t("settings.llm.timeout.desc")} />
    </SettingsSection>
  );
}

/* ── Agents Section ── */

function AgentSection({ vals, saving, onSave, onReset }: {
  vals: Record<string, unknown>;
  saving: boolean;
  onSave: (v: Record<string, unknown>) => void;
  onReset: () => void;
}) {
  const { t } = useT();
  const [local, setLocal] = useState(vals);
  useEffect(() => { setLocal(vals); }, [vals]);

  const set = (k: string, v: unknown) => setLocal((p) => ({ ...p, [k]: v }));
  const save = () => onSave(local);

  return (
    <SettingsSection title={t("settings.agents")} desc={t("settings.agents.desc")} icon={<Users size={16} />} onSave={save} onReset={onReset} saving={saving}>
      <fieldset className="space-y-2 rounded border border-slate-100 p-3">
        <legend className="text-xs font-medium text-slate-500">{t("settings.auditor")}</legend>
        <SliderField label={t("settings.auditor.initial")} value={getNum(local, "auditor.reputation_initial", 1.0)} min={0} max={1} step={0.01} onChange={(v) => set("auditor.reputation_initial", v)} />
        <Desc text={t("settings.auditor.initial.desc")} />
        <NumberField label={t("settings.auditor.recovery")} value={getNum(local, "auditor.reputation_recovery_rate", 0.02)} min={0} max={1} step={0.01} onChange={(v) => set("auditor.reputation_recovery_rate", v)} />
        <Desc text={t("settings.auditor.recovery.desc")} />
        <SliderField label={t("settings.auditor.blockThreshold")} value={getNum(local, "auditor.reputation_block_threshold", 0.30)} min={0} max={1} step={0.01} onChange={(v) => set("auditor.reputation_block_threshold", v)} />
        <Desc text={t("settings.auditor.blockThreshold.desc")} />
        <NumberField label={t("settings.auditor.decayInterval")} value={getNum(local, "auditor.reputation_decay_interval", 60)} min={5} max={600} onChange={(v) => set("auditor.reputation_decay_interval", v)} />
        <Desc text={t("settings.auditor.decayInterval.desc")} />
        <NumberField label={t("settings.auditor.decayRate")} value={getNum(local, "auditor.reputation_decay_rate", 0.05)} min={0} max={1} step={0.01} onChange={(v) => set("auditor.reputation_decay_rate", v)} />
        <Desc text={t("settings.auditor.decayRate.desc")} />
      </fieldset>

      <fieldset className="space-y-2 rounded border border-slate-100 p-3">
        <legend className="text-xs font-medium text-slate-500">{t("settings.redTeam")}</legend>
        <ToggleField label={t("settings.redTeam.enabled")} value={getBool(local, "red_team.enabled", true)} onChange={(v) => set("red_team.enabled", v)} />
        <Desc text={t("settings.redTeam.enabled.desc")} />
        <NumberField label={t("settings.redTeam.interval")} value={getNum(local, "red_team.attack_interval_seconds", 5)} min={1} max={120} step={0.5} onChange={(v) => set("red_team.attack_interval_seconds", v)} />
        <Desc text={t("settings.redTeam.interval.desc")} />
        <NumberField label={t("settings.redTeam.maxAttacks")} value={getNum(local, "red_team.max_attacks", 20)} min={1} max={200} onChange={(v) => set("red_team.max_attacks", v)} />
        <Desc text={t("settings.redTeam.maxAttacks.desc")} />
      </fieldset>

      <fieldset className="space-y-2 rounded border border-slate-100 p-3">
        <legend className="text-xs font-medium text-slate-500">{t("settings.honeypotAgent")}</legend>
        <ToggleField label={t("settings.honeypot.enabled")} value={getBool(local, "honeypot.enabled", true)} onChange={(v) => set("honeypot.enabled", v)} />
        <Desc text={t("settings.honeypot.enabled.desc")} />
        <TextField label={t("settings.honeypot.node")} value={getStr(local, "honeypot.default_node", "Honeypot_Agent")} onChange={(v) => set("honeypot.default_node", v)} />
        <Desc text={t("settings.honeypot.node.desc")} />
      </fieldset>
    </SettingsSection>
  );
}

/* ── System Section ── */

function SystemSection({ vals, saving, onSave, onReset }: {
  vals: Record<string, unknown>;
  saving: boolean;
  onSave: (v: Record<string, unknown>) => void;
  onReset: () => void;
}) {
  const { t } = useT();
  const [local, setLocal] = useState(vals);
  useEffect(() => { setLocal(vals); }, [vals]);

  const set = (k: string, v: unknown) => setLocal((p) => ({ ...p, [k]: v }));
  const save = () => onSave(local);

  return (
    <SettingsSection title={t("settings.system")} desc={t("settings.system.desc")} icon={<Wrench size={16} />} onSave={save} onReset={onReset} saving={saving}>
      <TextAreaField
        label={t("settings.system.cors")}
        value={getStr(local, "system.cors_allowed_origins", "")}
        placeholder="http://localhost:5173,http://127.0.0.1:5173"
        rows={2}
        onChange={(v) => set("system.cors_allowed_origins", v)}
      />
      <Desc text={t("settings.system.cors.desc")} />
      <NumberField label={t("settings.system.retention")} value={getNum(local, "system.event_retention_limit", 10000)} min={100} max={1000000} onChange={(v) => set("system.event_retention_limit", v)} />
      <Desc text={t("settings.system.retention.desc")} />
      <NumberField label={t("settings.system.wsPing")} value={getNum(local, "system.ws_ping_interval", 30)} min={5} max={300} onChange={(v) => set("system.ws_ping_interval", v)} />
      <Desc text={t("settings.system.wsPing.desc")} />
    </SettingsSection>
  );
}
