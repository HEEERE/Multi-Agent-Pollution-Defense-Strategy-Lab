import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import { StrategyLab } from "./StrategyLab";

vi.mock("../lib/api", () => ({
  api: {
    listStrategies: vi.fn(),
    validateStrategy: vi.fn(),
    createStrategy: vi.fn(),
    updateStrategy: vi.fn(),
    deleteStrategy: vi.fn(),
    runStrategy: vi.fn(),
    getRun: vi.fn(),
    getRunEvents: vi.fn(),
    getRunMetrics: vi.fn(),
  },
}));
vi.mock("../components/strategy/StrategyEditor", () => ({
  StrategyEditor: () => <div data-testid="strategy-editor" />,
}));
vi.mock("../components/strategy/StrategyValidationPanel", () => ({
  StrategyValidationPanel: () => <div />,
}));

describe("StrategyLab", () => {
  it("keeps a new draft selected when saved strategies already exist", async () => {
    vi.mocked(api.listStrategies).mockResolvedValue([
      {
        strategy_id: "saved-1",
        name: "saved strategy",
        description: "saved",
        format: "json",
        content: { topology: { nodes: [{ node_id: "gateway", node_type: "gateway" }] } },
        tags: [],
        version: 1,
        created_at: 1,
        updated_at: 1,
      },
    ]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <MemoryRouter>
        <QueryClientProvider client={client}>
          <StrategyLab />
        </QueryClientProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText("删除当前策略")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "新建" }));

    await waitFor(() =>
      expect(screen.queryByText("删除当前策略")).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "运行" })).toBeDisabled();
  });
});
