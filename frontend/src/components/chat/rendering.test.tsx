import React from "react";
import { render, screen } from "@testing-library/react";

import { ChatMessage } from "@/components/chat/ChatMessage";
import { RetrievalCard } from "@/components/chat/RetrievalCard";
import { ThoughtChain } from "@/components/chat/ThoughtChain";

describe("chat rendering components", () => {
  it("renders retrieval card values", () => {
    render(
      <RetrievalCard
        retrievals={[
          {
            source: "memory/MEMORY.md",
            score: 0.93,
            text: "memory snippet",
          },
        ]}
      />,
    );

    expect(screen.getByText("RAG Retrieval")).toBeInTheDocument();
    expect(screen.getByText("memory/MEMORY.md")).toBeInTheDocument();
    expect(screen.getByText("memory snippet")).toBeInTheDocument();
  });

  it("renders thought chain call input and output", () => {
    render(
      <ThoughtChain
        calls={[
          {
            tool: "read_file",
            input: { path: "memory/MEMORY.md" },
            output: "ok",
          },
        ]}
      />,
    );

    expect(screen.getByText("Tool Trace")).toBeInTheDocument();
    expect(screen.getByText("read_file")).toBeInTheDocument();
    expect(screen.getByText(/memory\/MEMORY.md/)).toBeInTheDocument();
    expect(screen.getByText(/output: ok/)).toBeInTheDocument();
  });

  it("renders markdown for assistant messages with sanitization", () => {
    const markdown = [
      "# Heading",
      "",
      "[Link](https://example.com)",
      "",
      "```ts",
      "const x = 1",
      "```",
      "",
      "<script>alert('xss')</script>",
    ].join("\n");

    const { container } = render(
      <ChatMessage
        role="assistant"
        content={markdown}
        toolCalls={[]}
        retrievals={[]}
        debugEvents={[]}
      />,
    );

    expect(screen.getByText("Heading")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Link" });
    expect(link).toHaveAttribute("href", "https://example.com");
    expect(screen.getByText(/const x = 1/)).toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
  });
});
