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
    ragEnabled: false,
    toggleRag: mockToggleRag,
    isStreaming: false,
    currentAgentId: "default",
  }),
}));

vi.mock("@/lib/api", () => ({
  getTracingConfig: mockGetTracingConfig,
  setTracingConfig: mockSetTracingConfig,
}));

describe("Navbar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the operator console navigation and marks the active route", () => {
    mockUsePathname.mockReturnValue("/runs");

    render(<Navbar />);

    expect(screen.getByRole("link", { name: "Workspace" })).toHaveAttribute(
      "href",
      "/",
    );
    expect(screen.getByRole("link", { name: "Sessions" })).toHaveAttribute(
      "href",
      "/sessions",
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
});
