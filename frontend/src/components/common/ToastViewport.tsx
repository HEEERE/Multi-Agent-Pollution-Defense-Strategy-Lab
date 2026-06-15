import { CheckCircle2, CircleAlert, Info, X } from "lucide-react";
import { useAppStore } from "../../store/app-store";

export function ToastViewport() {
  const toasts = useAppStore((state) => state.toasts);
  const dismiss = useAppStore((state) => state.dismissToast);

  return (
    <div className="fixed right-5 top-20 z-[100] flex w-80 flex-col gap-2">
      {toasts.map((toast) => {
        const Icon =
          toast.kind === "success"
            ? CheckCircle2
            : toast.kind === "error"
              ? CircleAlert
              : Info;
        const tone =
          toast.kind === "success"
            ? "text-emerald-300"
            : toast.kind === "error"
              ? "text-red-300"
              : "text-cyan-300";
        return (
          <div
            key={toast.id}
            className="panel flex items-center gap-3 px-4 py-3 shadow-2xl"
          >
            <Icon className={`size-4 shrink-0 ${tone}`} />
            <div className="flex-1 text-sm text-slate-200">{toast.title}</div>
            <button
              type="button"
              onClick={() => dismiss(toast.id)}
              className="text-slate-500 hover:text-white"
            >
              <X className="size-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
