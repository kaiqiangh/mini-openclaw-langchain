"use client";

import dynamic from "next/dynamic";
import { memo, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";

import { ChatDebugEvent, ChatToolCall, RetrievalItem } from "@/lib/store";
import { Badge } from "@/components/ui/primitives";
import { debugBadgeTone } from "@/lib/badge-tones";

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
  timestampMs: number | null;
  toolCalls: ChatToolCall[];
  selectedSkills: string[];
  skillUses: string[];
  retrievals: RetrievalItem[];
  debugEvents: ChatDebugEvent[];
};

const chatTimestampFormatter = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

function formatTimestamp(timestampMs: number | null): string {
  if (typeof timestampMs !== "number" || !Number.isFinite(timestampMs)) {
    return "";
  }
  return chatTimestampFormatter.format(new Date(timestampMs));
}

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
  if (Array.isArray(node))
    return node.map((item) => extractText(item)).join("");
  if (node && typeof node === "object" && "props" in node) {
    const children = (node as { props?: { children?: ReactNode } }).props
      ?.children;
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
        className="ui-btn ui-btn-ghost ui-btn-sm absolute right-2 top-2 px-2"
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
            return (
              <a
                {...props}
                target="_blank"
                rel="noopener noreferrer"
                className="ui-md-link"
              />
            );
          },
          pre(props) {
            return <PreBlock>{props.children}</PreBlock>;
          },
          code(props) {
            return (
              <CodeBlock
                inline={
                  "inline" in props
                    ? (props as { inline?: boolean }).inline
                    : false
                }
                className={
                  "className" in props
                    ? (props as { className?: string }).className
                    : undefined
                }
              >
                {"children" in props
                  ? (props as { children?: ReactNode }).children
                  : null}
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

function ChatMessageComponent({
  role,
  content,
  timestampMs,
  toolCalls,
  selectedSkills,
  skillUses,
  retrievals,
  debugEvents,
}: Props) {
  const timestampLabel = formatTimestamp(timestampMs);
  const uniqueTools = [...new Set(toolCalls.map((call) => call.tool).filter(Boolean))];
  const uniqueSelectedSkills = [...new Set(selectedSkills.filter(Boolean))];
  const uniqueSkills = [...new Set(skillUses.filter(Boolean))];

  return (
    <article
      className={`mb-3 rounded-md border p-3 text-sm sm:p-4 ${
        role === "user"
          ? "ml-4 border-[var(--accent-strong)] bg-[var(--accent-soft)] md:ml-6"
          : "mr-4 border-[var(--border)] bg-[var(--surface-3)] md:mr-6"
      }`}
    >
      <div className="mb-2 flex items-center gap-2">
        <Badge tone={role === "user" ? "accent" : "neutral"}>{role}</Badge>
        <span className="ui-helper ui-mono">
          {role === "assistant" ? "agent-response" : "operator-input"}
        </span>
        {timestampLabel ? (
          <time
            className="ml-auto text-xs text-[var(--muted)]"
            dateTime={new Date(timestampMs ?? 0).toISOString()}
          >
            {timestampLabel}
          </time>
        ) : null}
      </div>
      <div className="break-words leading-6 text-[var(--text)]">
        {role === "assistant" ? (
          <MarkdownBody content={content} />
        ) : (
          <div className="whitespace-pre-wrap">{content}</div>
        )}
      </div>
      {uniqueTools.length > 0 ||
      uniqueSelectedSkills.length > 0 ||
      uniqueSkills.length > 0 ? (
        <div className="mt-3 rounded-md border border-[var(--border)] bg-[var(--surface-2)] p-2">
          <div className="ui-label">Debug Summary</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {uniqueTools.map((tool) => (
              <Badge
                key={`tool-${tool}`}
                tone={debugBadgeTone("tool")}
                className="ui-mono"
              >
                tool:{tool}
              </Badge>
            ))}
            {uniqueSelectedSkills.map((skill) => (
              <Badge
                key={`skill-selected-${skill}`}
                tone={debugBadgeTone("skill_selected")}
                className="ui-mono"
              >
                selected:{skill}
              </Badge>
            ))}
            {uniqueSkills.map((skill) => (
              <Badge
                key={`skill-${skill}`}
                tone={debugBadgeTone("skill_used")}
                className="ui-mono"
              >
                used:{skill}
              </Badge>
            ))}
          </div>
        </div>
      ) : null}
      {retrievals.length > 0 ? <RetrievalCard retrievals={retrievals} /> : null}
      {toolCalls.length > 0 ? <ThoughtChain calls={toolCalls} /> : null}
      {role === "assistant" && debugEvents.length > 0 ? (
        <DebugTrace events={debugEvents} />
      ) : null}
    </article>
  );
}

export const ChatMessage = memo(ChatMessageComponent);
