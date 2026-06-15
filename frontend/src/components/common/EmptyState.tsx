import type { LucideIcon } from "lucide-react";

export function EmptyState({
  icon: Icon,
  title,
  description,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
}) {
  return (
    <div className="grid min-h-52 place-items-center p-8 text-center">
      <div>
        <div className="mx-auto grid size-12 place-items-center rounded-xl border border-slate-700 bg-ink-800 text-slate-400">
          <Icon className="size-5" />
        </div>
        <h3 className="mt-4 text-sm font-semibold text-slate-200">{title}</h3>
        <p className="mx-auto mt-2 max-w-sm text-xs leading-5 text-slate-500">
          {description}
        </p>
      </div>
    </div>
  );
}
