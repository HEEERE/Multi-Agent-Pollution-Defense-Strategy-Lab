import { Copy } from "lucide-react";
import { useAppStore } from "../../store/app-store";

export function JsonViewer({
  value,
  className = "",
}: {
  value: unknown;
  className?: string;
}) {
  const addToast = useAppStore((state) => state.addToast);
  const text = JSON.stringify(value ?? {}, null, 2);

  const copy = async () => {
    await navigator.clipboard.writeText(text);
    addToast("JSON 已复制", "success");
  };

  return (
    <div className={`relative ${className}`}>
      <button
        type="button"
        onClick={copy}
        className="btn absolute right-2 top-2 z-10 h-8 px-2"
        title="复制 JSON"
      >
        <Copy className="size-3.5" />
        复制
      </button>
      <pre className="code-surface max-h-full overflow-auto p-4 pr-20 leading-6">
        {text}
      </pre>
    </div>
  );
}
