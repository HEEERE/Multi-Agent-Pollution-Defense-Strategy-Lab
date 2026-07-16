import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { AuthGate } from "./AuthGate";

vi.mock("../../lib/api", () => ({
  api: {
    getPlatformConfig: vi.fn(),
    getAuthSession: vi.fn(),
    createAuthSession: vi.fn(),
  },
}));

function renderGate() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AuthGate><div>protected content</div></AuthGate>
    </QueryClientProvider>,
  );
}

describe("AuthGate", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders directly when server authentication is disabled", async () => {
    vi.mocked(api.getPlatformConfig).mockResolvedValue({
      llm_provider: "mimo",
      llm_base_url: "",
      llm_model: "offline",
      llm_enabled: false,
      llm_ready: false,
      auth_enabled: false,
    });

    renderGate();

    expect(await screen.findByText("protected content")).toBeInTheDocument();
    expect(api.getAuthSession).not.toHaveBeenCalled();
  });

  it("exchanges the access key for a browser session", async () => {
    vi.mocked(api.getPlatformConfig).mockResolvedValue({
      llm_provider: "mimo",
      llm_base_url: "",
      llm_model: "offline",
      llm_enabled: false,
      llm_ready: false,
      auth_enabled: true,
    });
    vi.mocked(api.getAuthSession)
      .mockResolvedValueOnce({ auth_enabled: true, authenticated: false })
      .mockResolvedValue({ auth_enabled: true, authenticated: true });
    vi.mocked(api.createAuthSession).mockResolvedValue({
      auth_enabled: true,
      authenticated: true,
    });

    renderGate();
    const input = await screen.findByLabelText("服务访问密钥");
    await userEvent.type(input, "server-secret");
    await userEvent.click(screen.getByRole("button", { name: "进入平台" }));

    expect(api.createAuthSession).toHaveBeenCalledWith("server-secret");
    expect(await screen.findByText("protected content")).toBeInTheDocument();
  });
});
