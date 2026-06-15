import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatTime(timestamp?: number | null, withDate = false) {
  if (!timestamp) return "--";
  const date = new Date(timestamp * 1000);
  return new Intl.DateTimeFormat("zh-CN", {
    month: withDate ? "2-digit" : undefined,
    day: withDate ? "2-digit" : undefined,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

export function formatDuration(ms?: number | null) {
  if (ms == null) return "--";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

export function formatPercent(value?: number | null) {
  if (value == null) return "--";
  return `${(value * 100).toFixed(1)}%`;
}

export function getErrorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  return "发生未知错误";
}

export function compactId(value?: string | null, length = 16) {
  if (!value) return "--";
  if (value.length <= length) return value;
  return `${value.slice(0, length - 3)}...`;
}

export function parseEdge(edge: string) {
  const [source = "", target = ""] = edge.split("->");
  return { source, target };
}

export function safeJsonParse(value: string) {
  const parsed: unknown = JSON.parse(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("JSON 顶层必须是对象");
  }
  return parsed as Record<string, unknown>;
}
