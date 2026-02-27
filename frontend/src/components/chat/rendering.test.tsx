import React from "react";
import { render, screen } from "@testing-library/react";

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
});
