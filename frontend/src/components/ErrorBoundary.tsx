import React from "react";

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends React.Component<React.PropsWithChildren, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("UI render failed", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div className="flex h-full items-center justify-center bg-slate-100 p-6">
        <div className="max-w-md rounded-lg border border-rose-200 bg-white p-5 text-sm shadow-sm">
          <h1 className="font-semibold text-rose-700">页面渲染出错</h1>
          <p className="mt-2 text-slate-600">
            当前页面遇到前端异常，没有继续白屏。请刷新页面或返回其他页面。
          </p>
          <pre className="mt-3 max-h-40 overflow-auto rounded bg-slate-50 p-2 text-xs text-slate-500">
            {this.state.error.message}
          </pre>
          <button
            className="mt-4 rounded bg-teal-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-teal-700"
            onClick={() => this.setState({ error: null })}
            type="button"
          >
            重试
          </button>
        </div>
      </div>
    );
  }
}
