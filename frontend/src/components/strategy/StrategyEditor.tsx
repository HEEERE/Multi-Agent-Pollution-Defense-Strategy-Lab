import Editor, { loader, type OnMount } from "@monaco-editor/react";
import { Braces, WandSparkles } from "lucide-react";
import { useRef } from "react";
import type { editor } from "monaco-editor";
import * as monaco from "monaco-editor/esm/vs/editor/editor.api";
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import JsonWorker from "monaco-editor/esm/vs/language/json/json.worker?worker";
import "monaco-editor/esm/vs/language/json/monaco.contribution";

loader.config({ monaco });

type MonacoRuntime = typeof globalThis & {
  MonacoEnvironment?: {
    getWorker: (_moduleId: string, label: string) => Worker;
  };
};

(globalThis as MonacoRuntime).MonacoEnvironment = {
  getWorker(_moduleId, label) {
    return label === "json" ? new JsonWorker() : new EditorWorker();
  },
};

export function StrategyEditor({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);

  const onMount: OnMount = (instance, monaco) => {
    editorRef.current = instance;
    monaco.editor.defineTheme("majd-dark", {
      base: "vs-dark",
      inherit: true,
      rules: [
        { token: "string.key.json", foreground: "54C7FF" },
        { token: "string.value.json", foreground: "A7E06E" },
        { token: "number", foreground: "D6A8FF" },
      ],
      colors: {
        "editor.background": "#06101A",
        "editorLineNumber.foreground": "#385064",
        "editorLineNumber.activeForeground": "#94B0C3",
        "editor.selectionBackground": "#164863",
        "editor.inactiveSelectionBackground": "#12384D",
        "editorIndentGuide.background1": "#153042",
        "editorIndentGuide.activeBackground1": "#2B6584",
      },
    });
    monaco.editor.setTheme("majd-dark");
  };

  const format = async () => {
    await editorRef.current?.getAction("editor.action.formatDocument")?.run();
  };

  return (
    <section className="flex h-full min-h-[650px] flex-col border-x border-slate-800 bg-[#06101a]">
      <div className="flex h-12 items-center justify-between border-b border-slate-800 px-3">
        <div className="flex items-center gap-2 text-xs text-slate-300">
          <Braces className="size-4 text-cyan-350" />
          策略 JSON
        </div>
        <button type="button" onClick={format} className="btn h-8">
          <WandSparkles className="size-3.5" />
          格式化
        </button>
      </div>
      <div className="min-h-0 flex-1">
        <Editor
          height="100%"
          language="json"
          value={value}
          onChange={(next) => onChange(next ?? "")}
          onMount={onMount}
          options={{
            automaticLayout: true,
            fontFamily: "'Cascadia Code', 'JetBrains Mono', Consolas, monospace",
            fontSize: 13,
            lineHeight: 22,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            padding: { top: 12, bottom: 20 },
            wordWrap: "on",
            tabSize: 2,
            formatOnPaste: true,
          }}
        />
      </div>
      <div className="flex h-8 items-center justify-between border-t border-slate-800 px-3 font-mono text-[10px] text-slate-500">
        <span>JSON · UTF-8 · LF</span>
        <span>保存前会执行 JSON.parse 与后端校验</span>
      </div>
    </section>
  );
}
