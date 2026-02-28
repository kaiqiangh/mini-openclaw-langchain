"use client";

import dynamic from "next/dynamic";
import { memo, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";

import { ChatDebugEvent, ChatToolCall, RetrievalItem } from "@/lib/store";
import { Badge } from "@/components/ui/primitives";

const RetrievalCard = dynamic(
  () => import("./RetrievalCard").then((mod) => mod.RetrievalCard),
  { ssr: false },
);

const ThoughtChain = dynamic(
  () => import("./ThoughtChain").then((mod) => mod.ThoughtChain),
  { ssr: false },
);
const DebugTrace = dynamic(
  () => import("./DebugTrace").then((mod) => mod.DebugTrace),
  { ssr: false },
);

type Props = {
  role: "user" | "assistant";
  content: string;
  toolCalls: ChatToolCall[];
  retrievals: RetrievalItem[];
  debugEvents: ChatDebugEvent[];
};

function CodeBlock({
  inline = false,
  className,
  children,
  ...props
}: {
  inline?: boolean;
  className?: string;
  children?: ReactNode;
}) {
  if (inline) {
    return (
      <code className={`ui-md-inline ${className ?? ""}`} {...props}>
        {children}
      </code>
    );
  }
  return (
    <code className={className} {...props}>
      {children}
    </code>
  );
}

function extractText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map((item) => extractText(item)).join("");
  if (node && typeof node === "object" && "props" in node) {
    const children = (node as { props?: { children?: ReactNode } }).props?.children;
    return extractText(children ?? "");
  }
  return "";
}

function PreBlock({ children }: { children?: ReactNode }) {
  const [copied, setCopied] = useState(false);
  const value = extractText(children ?? "").replace(/\n$/, "");
  return (
    <div className="ui-md-code-wrap">
      <button
        type="button"
        className="ui-btn ui-btn-ghost absolute right-2 top-2 min-h-[24px] px-2 text-[10px]"
        onClick={async () => {
          if (!navigator?.clipboard) return;
          await navigator.clipboard.writeText(value);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1200);
        }}
        aria-label="Copy code block"
      >
        {copied ? "Copied" : "Copy"}
      </button>
      <pre className="ui-md-pre">{children}</pre>
    </div>
  );
}

function MarkdownBody({ content }: { content: string }) {
  return (
    <div className="ui-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        components={{
          a(props) {
            return <a {...props} target="_blank" rel="noopener noreferrer" className="ui-md-link" />;
          },
          pre(props) {
            return <PreBlock>{props.children}</PreBlock>;
          },
          code(props) {
            return (
              <CodeBlock
                inline={"inline" in props ? (props as { inline?: boolean }).inline : false}
                className={"className" in props ? (props as { className?: string }).className : undefined}
              >
                {"children" in props ? (props as { children?: ReactNode }).children : null}
              </CodeBlock>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function ChatMessageComponent({ role, content, toolCalls, retrievals, debugEvents }: Props) {
  return (
    <article
      className={`mb-3 rounded-md border p-3 text-sm ${
        role === "user"
          ? "ml-8 border-[var(--accent-strong)] bg-[var(--accent-soft)]"
          : "mr-8 border-[var(--border)] bg-[var(--surface-3)]"
      }`}
    >
      <div className="mb-2 flex items-center gap-2">
        <Badge tone={role === "user" ? "accent" : "neutral"}>{role}</Badge>
        <span className="ui-helper ui-mono">{role === "assistant" ? "agent-response" : "operator-input"}</span>
      </div>
      <div className="break-words leading-6 text-[var(--text)]">
        {role === "assistant" ? <MarkdownBody content={content} /> : <div className="whitespace-pre-wrap">{content}</div>}
      </div>
      {retrievals.length > 0 ? <RetrievalCard retrievals={retrievals} /> : null}
      {toolCalls.length > 0 ? <ThoughtChain calls={toolCalls} /> : null}
      {role === "assistant" && debugEvents.length > 0 ? <DebugTrace events={debugEvents} /> : null}
    </article>
  );
}

export const ChatMessage = memo(ChatMessageComponent);
