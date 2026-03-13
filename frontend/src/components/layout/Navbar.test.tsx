import React from "react";
import { render, screen } from "@testing-library/react";

import { Navbar } from "@/components/layout/Navbar";

const { mockUsePathname, mockGetTracingConfig, mockSetTracingConfig, mockToggleRag } =
  vi.hoisted(() => ({
    mockUsePathname: vi.fn(),
    mockGetTracingConfig: vi.fn(async () => ({ enabled: false })),
    mockSetTracingConfig: vi.fn(async (enabled: boolean) => ({ enabled })),
    mockToggleRag: vi.fn(async () => undefined),
  }));

vi.mock("next/navigation", () => ({
  usePathname: () => mockUsePathname(),
}));

const storeState = vi.hoisted(() => ({
  ragEnabled: false,
  isStreaming: false,
  currentAgentId: "default",
  currentSessionId: "session-1" as string | null,
  sessionsScope: "active" as "active" | "archived",
  maxStepsPrompt: null as null | { sessionId: string; message: string },
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/store", () => ({
  useAppStore: () => ({
    ...storeState,
    toggleRag: mockToggleRag,
  }),
}));

vi.mock("@/lib/api", () => ({
  getTracingConfig: mockGetTracingConfig,
  setTracingConfig: mockSetTracingConfig,
}));

describe("Navbar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    storeState.ragEnabled = false;
    storeState.isStreaming = false;
    storeState.currentAgentId = "default";
    storeState.currentSessionId = "session-1";
    storeState.sessionsScope = "active";
    storeState.maxStepsPrompt = null;
  });

  it("renders the operator console navigation and marks the active route", () => {
    mockUsePathname.mockReturnValue("/runs");

    render(<Navbar />);

    expect(screen.getByRole("link", { name: "Agents" })).toHaveAttribute(
      "href",
      "/",
    );
    expect(screen.getByRole("link", { name: "Sessions" })).toHaveAttribute(
      "href",
      "/sessions?agent=default&scope=active&session=session-1",
    );
    expect(screen.getByRole("link", { name: "Runs" })).toHaveAttribute(
      "href",
      "/runs",
    );
    expect(
      screen.getByRole("link", { name: "Trace Explorer" }),
    ).toHaveAttribute("href", "/traces");
    expect(screen.getByRole("link", { name: "Scheduler" })).toHaveAttribute(
      "href",
      "/scheduler",
    );
    expect(screen.getByRole("link", { name: "Usage" })).toHaveAttribute(
      "href",
      "/usage",
    );
    expect(screen.getByRole("link", { name: "Runs" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("shows active runtime state when a session exists even without a live stream", () => {
    mockUsePathname.mockReturnValue("/usage");

    render(<Navbar />);

    expect(screen.getByText("Active")).toBeInTheDocument();
  });
});
