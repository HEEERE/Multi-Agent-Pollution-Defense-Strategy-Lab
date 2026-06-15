import { LoaderCircle } from "lucide-react";

export function Loading({ label = "正在加载" }: { label?: string }) {
  return (
    <div className="flex min-h-40 items-center justify-center gap-2 text-sm text-slate-400">
      <LoaderCircle className="size-4 animate-spin text-cyan-350" />
      {label}
    </div>
  );
}
