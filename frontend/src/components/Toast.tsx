import { useEffect, useState } from "react";
import { CheckCircle, AlertCircle, X } from "lucide-react";

export interface ToastState {
  type: "success" | "error";
  message: string;
}

export function Toast({ toast, onDismiss }: { toast: ToastState | null; onDismiss: () => void }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (toast) {
      setVisible(true);
      const t = setTimeout(() => {
        setVisible(false);
        setTimeout(onDismiss, 200);
      }, 3000);
      return () => clearTimeout(t);
    }
  }, [toast, onDismiss]);

  if (!toast) return null;

  const isSuccess = toast.type === "success";

  return (
    <div
      className={`fixed right-4 top-4 z-50 flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm shadow-lg transition-all duration-200 ${
        visible ? "translate-y-0 opacity-100" : "-translate-y-2 opacity-0"
      } ${
        isSuccess
          ? "border-emerald-200 bg-emerald-50 text-emerald-800"
          : "border-red-200 bg-red-50 text-red-800"
      }`}
    >
      {isSuccess ? <CheckCircle size={16} /> : <AlertCircle size={16} />}
      <span>{toast.message}</span>
      <button onClick={() => { setVisible(false); setTimeout(onDismiss, 200); }} className="ml-2 hover:opacity-70">
        <X size={14} />
      </button>
    </div>
  );
}
