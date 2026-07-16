import { useMutation, useQuery } from "@tanstack/react-query";
import { KeyRound, ShieldCheck } from "lucide-react";
import { type FormEvent, type ReactNode, useState } from "react";
import { api } from "../../lib/api";
import { getErrorMessage } from "../../lib/utils";
import { Loading } from "../common/Loading";

export function AuthGate({ children }: { children: ReactNode }) {
  const [apiKey, setApiKey] = useState("");
  const platform = useQuery({
    queryKey: ["platform-config"],
    queryFn: api.getPlatformConfig,
  });
  const session = useQuery({
    queryKey: ["auth-session"],
    queryFn: api.getAuthSession,
    enabled: Boolean(platform.data?.auth_enabled),
    retry: false,
    refetchInterval: 30_000,
  });
  const login = useMutation({
    mutationFn: () => api.createAuthSession(apiKey),
    onSuccess: async () => {
      setApiKey("");
      await session.refetch();
    },
  });

  if (platform.isPending || (platform.data?.auth_enabled && session.isPending)) {
    return (
      <div className="grid min-h-screen place-items-center bg-ink-950">
        <Loading label="正在验证访问权限" />
      </div>
    );
  }

  if (platform.isError) {
    return (
      <div className="grid min-h-screen place-items-center bg-ink-950 p-6 text-sm text-red-300">
        无法读取平台访问配置，请确认后端服务可用。
      </div>
    );
  }

  if (!platform.data?.auth_enabled || session.data?.authenticated) {
    return children;
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (apiKey.trim()) login.mutate();
  }

  return (
    <div className="grid min-h-screen place-items-center bg-ink-950 p-6 text-slate-100">
      <form onSubmit={submit} className="panel w-full max-w-md overflow-hidden">
        <div className="border-b border-slate-800 p-6">
          <div className="mb-4 grid size-11 place-items-center rounded-xl border border-cyan-500/30 bg-cyan-500/10">
            <ShieldCheck className="size-5 text-cyan-300" />
          </div>
          <h1 className="text-lg font-semibold text-white">访问 MAJD-Guard</h1>
          <p className="mt-2 text-xs leading-5 text-slate-500">
            此部署已启用访问控制。密钥只用于换取 HttpOnly 会话，不会保存在浏览器脚本中。
          </p>
        </div>
        <div className="space-y-4 p-6">
          <label className="block text-xs text-slate-400">
            服务访问密钥
            <div className="relative mt-2">
              <KeyRound className="absolute left-3 top-2.5 size-4 text-slate-500" />
              <input
                autoFocus
                type="password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                className="input pl-10"
                autoComplete="current-password"
              />
            </div>
          </label>
          {login.error && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-300">
              {getErrorMessage(login.error)}
            </div>
          )}
          <button type="submit" className="btn-primary w-full" disabled={!apiKey.trim() || login.isPending}>
            {login.isPending ? "正在验证" : "进入平台"}
          </button>
        </div>
      </form>
    </div>
  );
}
