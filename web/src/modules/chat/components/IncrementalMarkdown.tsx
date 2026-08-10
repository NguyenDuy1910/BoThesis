"use client";

import {
  Children,
  isValidElement,
  memo,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type AnchorHTMLAttributes,
  type HTMLAttributes,
  type ReactNode,
} from "react";
import { Check, Copy } from "lucide-react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

const MARKDOWN_REMARK_PLUGINS = [remarkGfm, remarkMath];
const MARKDOWN_REHYPE_PLUGINS = [rehypeKatex];

// The backend already coalesces tokens into word/phrase chunks; the client only
// eases them onto screen at a STABLE cadence so text flows like natural words
// rather than a per-frame typewriter. Reveal is committed on a fixed interval —
// NOT every animation frame — so markdown is re-parsed ~30x/s instead of ~60x/s,
// and each commit snaps to a word boundary so a half-typed token is never shown.
// Catch-up stays proportional to the backlog (so a burst eases in instead of
// dumping) but a raised floor keeps the tail from decelerating into a crawl.
const SMOOTH_COMMIT_INTERVAL_MS = 32;
const SMOOTH_MIN_CHARS_PER_COMMIT = 10;
const SMOOTH_MAX_CHARS_PER_COMMIT = 110;
const SMOOTH_BACKLOG_DIVISOR = 4;

const MERMAID_THEME_VARIABLES = {
  fontFamily: "Hanken Grotesk, Arial, sans-serif",
  primaryColor: "#ffffff",
  primaryTextColor: "#374151",
  primaryBorderColor: "#e5e7eb",
  lineColor: "#9ca3af",
  secondaryColor: "#f9fafb",
  tertiaryColor: "#f3f4f6",
  background: "#ffffff",
  mainBkg: "#ffffff",
  secondBkg: "#f9fafb",
  tertiaryBkg: "#f3f4f6",
  textColor: "#374151",
};

// Completed answers render mermaid diagrams.
const MARKDOWN_COMPONENTS = createMarkdownComponents({ renderMermaid: true });
// While streaming, stable segments AND the tail share ONE components object so a
// block keeps the same component identity when it crosses the stable boundary
// (no remount/flash). Mermaid stays a code block until the answer is complete —
// it is async/stateful and would flash if it moved between streaming subtrees.
const STREAMING_COMPONENTS = createMarkdownComponents({ renderMermaid: false });

function createMarkdownComponents({ renderMermaid }: { renderMermaid: boolean }): Components {
  return {
    a: MarkdownLink,
    blockquote: MarkdownBlockquote,
    h1: MarkdownHeading1,
    h2: MarkdownHeading2,
    h3: MarkdownHeading3,
    hr: MarkdownRule,
    pre: (props) => <MarkdownPre {...props} renderMermaid={renderMermaid} />,
    code: MarkdownCode,
    table: MarkdownTable,
  };
}

export const StreamingMarkdown = memo(function StreamingMarkdown({
  text,
  isStreaming,
}: {
  text: string;
  isStreaming: boolean;
}) {
  const displayedContent = useSmoothContent(text, isStreaming);

  const { stableSegments, streamingMarkdown } = useMemo(
    () =>
      isStreaming
        ? splitStreamingMarkdown(displayedContent)
        : { stableSegments: [], streamingMarkdown: displayedContent },
    [displayedContent, isStreaming],
  );

  if (!isStreaming) {
    return (
      <MarkdownRenderer content={displayedContent} components={MARKDOWN_COMPONENTS} />
    );
  }

  return (
    <>
      {stableSegments.map((segment, index) => (
        <StableMarkdown key={getStableSegmentKey(segment, index)} content={segment} />
      ))}
      {streamingMarkdown ? (
        <StreamingMarkdownTail content={streamingMarkdown} />
      ) : null}
    </>
  );
});

export const IncrementalMarkdown = StreamingMarkdown;

function useSmoothContent(target: string, isStreaming: boolean): string {
  const [displayed, setDisplayed] = useState(() => (isStreaming ? "" : target));
  const targetRef = useRef(target);
  const displayedLenRef = useRef(isStreaming ? 0 : target.length);
  const rafRef = useRef<number | null>(null);
  const lastCommitRef = useRef(0);

  targetRef.current = target;

  useEffect(() => {
    if (!isStreaming) {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      displayedLenRef.current = target.length;
      setDisplayed(target);
      return;
    }

    // A new / regenerated answer resets the reveal buffer.
    if (target.length < displayedLenRef.current) {
      displayedLenRef.current = target.length;
      lastCommitRef.current = 0;
      setDisplayed(target);
    }

    const tick = (now: number) => {
      rafRef.current = null;
      const full = targetRef.current;
      const currentLen = displayedLenRef.current;
      const remaining = full.length - currentLen;
      if (remaining <= 0) return;

      // Hold a steady cadence: at most one reveal per commit interval so the
      // markdown parse + paint happen ~30x/s, not on every frame. The first
      // reveal (lastCommit === 0) paints immediately so text never feels late.
      if (lastCommitRef.current && now - lastCommitRef.current < SMOOTH_COMMIT_INTERVAL_MS) {
        rafRef.current = requestAnimationFrame(tick);
        return;
      }

      const step = Math.min(
        SMOOTH_MAX_CHARS_PER_COMMIT,
        Math.max(SMOOTH_MIN_CHARS_PER_COMMIT, Math.ceil(remaining / SMOOTH_BACKLOG_DIVISOR)),
      );
      let nextLen = Math.min(full.length, currentLen + step);

      // Reveal whole words: never leave a half-typed token on screen — unless
      // snapping back would stall progress (a very long token) or we are
      // finishing the text.
      if (nextLen < full.length) {
        const boundary = revealWordBoundary(full, nextLen);
        if (boundary > currentLen) nextLen = boundary;
      }

      displayedLenRef.current = nextLen;
      lastCommitRef.current = now;
      setDisplayed(full.slice(0, nextLen));

      if (nextLen < targetRef.current.length) {
        rafRef.current = requestAnimationFrame(tick);
      }
    };

    if (rafRef.current === null && displayedLenRef.current < target.length) {
      rafRef.current = requestAnimationFrame(tick);
    }

    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [target, isStreaming]);

  return displayed;
}

function revealWordBoundary(text: string, pos: number): number {
  for (let index = pos; index > 0; index -= 1) {
    const char = text[index - 1];
    if (char === " " || char === "\n" || char === "\t") return index;
  }
  return pos;
}

const StableMarkdown = memo(function StableMarkdown({ content }: { content: string }) {
  return <MarkdownRenderer content={content} components={STREAMING_COMPONENTS} />;
});

const StreamingMarkdownTail = memo(function StreamingMarkdownTail({
  content,
}: {
  content: string;
}) {
  return (
    <MarkdownRenderer
      content={content}
      components={STREAMING_COMPONENTS}
      normalizeMath={false}
    />
  );
});

function MarkdownRenderer({
  content,
  components,
  normalizeMath = true,
}: {
  content: string;
  components: Components;
  normalizeMath?: boolean;
}) {
  const normalizedContent = useMemo(
    () => (normalizeMath ? normalizeMarkdownMath(content) : content),
    [content, normalizeMath],
  );

  return (
    <ReactMarkdown
      remarkPlugins={MARKDOWN_REMARK_PLUGINS}
      rehypePlugins={MARKDOWN_REHYPE_PLUGINS}
      components={components}
    >
      {normalizedContent}
    </ReactMarkdown>
  );
}

function normalizeMarkdownMath(content: string): string {
  if (!content || isInsideOpenCodeFence(content)) return content;

  const fencedCodeBlockPattern = /(^|\n)(```+|~~~+)[^\n]*\n[\s\S]*?\n\2[^\n]*(?=\n|$)/g;
  let normalized = "";
  let lastIndex = 0;

  for (const match of content.matchAll(fencedCodeBlockPattern)) {
    const index = match.index ?? 0;
    normalized += normalizeMarkdownMathText(content.slice(lastIndex, index));
    normalized += match[0];
    lastIndex = index + match[0].length;
  }

  normalized += normalizeMarkdownMathText(content.slice(lastIndex));
  return normalized;
}

function normalizeMarkdownMathText(content: string): string {
  return content
    .replace(/\\\[/g, () => "$$")
    .replace(/\\\]/g, () => "$$")
    .replace(/\\\(/g, () => "$")
    .replace(/\\\)/g, () => "$")
    .replace(/\$\$([\s\S]*?)\$\$/g, (match, expression: string) => {
      const trimmedExpression = expression.trim();
      if (!trimmedExpression) return match;
      return `$$\n${trimmedExpression}\n$$`;
    });
}

function splitStreamingMarkdown(content: string): {
  stableSegments: string[];
  streamingMarkdown: string;
} {
  if (!content) return { stableSegments: [], streamingMarkdown: "" };

  const boundary = getStableMarkdownBoundary(content);
  if (boundary <= 0) {
    return { stableSegments: [], streamingMarkdown: content };
  }

  return {
    stableSegments: splitMarkdownSegments(content.slice(0, boundary)),
    streamingMarkdown: content.slice(boundary),
  };
}

function getStableMarkdownBoundary(content: string): number {
  if (isInsideOpenCodeFence(content)) {
    const fenceStart = findLastFenceStart(content);
    if (fenceStart > 0) {
      const before = content.slice(0, fenceStart);
      const splitIdx = before.lastIndexOf("\n\n");
      if (splitIdx >= 0) {
        return splitIdx + 2;
      }
    }
    return 0;
  }

  const splitIdx = content.lastIndexOf("\n\n");
  return splitIdx >= 0 ? splitIdx + 2 : 0;
}

function splitMarkdownSegments(content: string): string[] {
  return content
    .split(/(\n\n+)/)
    .reduce<string[]>((segments, piece, index, pieces) => {
      if (!piece) return segments;
      if (/^\n\n+$/.test(piece)) {
        const previous = segments.pop() ?? "";
        const next = pieces[index + 1] ?? "";
        if (next) {
          segments.push(previous + piece + next);
          pieces[index + 1] = "";
        } else if (previous) {
          segments.push(previous + piece);
        }
        return segments;
      }
      segments.push(piece);
      return segments;
    }, [])
    .filter((segment) => segment.trim().length > 0);
}

function getStableSegmentKey(segment: string, index: number) {
  return `${index}:${segment.length}:${segment.slice(0, 24)}`;
}

function isInsideOpenCodeFence(content: string): boolean {
  const matches = content.match(/^```/gm);
  return Boolean(matches && matches.length % 2 === 1);
}

function findLastFenceStart(content: string): number {
  const regex = /^```/gm;
  let lastIdx = -1;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(content)) !== null) {
    lastIdx = match.index;
  }
  return lastIdx;
}

function MarkdownHeading1({
  children,
  ...props
}: HTMLAttributes<HTMLHeadingElement> & { children?: ReactNode }) {
  return <h1 {...props}>{children}</h1>;
}

function MarkdownHeading2({
  children,
  ...props
}: HTMLAttributes<HTMLHeadingElement> & { children?: ReactNode }) {
  return <h2 {...props}>{children}</h2>;
}

function MarkdownHeading3({
  children,
  ...props
}: HTMLAttributes<HTMLHeadingElement> & { children?: ReactNode }) {
  return <h3 {...props}>{children}</h3>;
}

function MarkdownLink({
  children,
  href,
  ...props
}: AnchorHTMLAttributes<HTMLAnchorElement> & { children?: ReactNode }) {
  const isExternal = Boolean(href && /^https?:\/\//i.test(href));

  return (
    <a
      {...props}
      href={href}
      rel={isExternal ? "noopener noreferrer" : props.rel}
      target={isExternal ? "_blank" : props.target}
    >
      {children}
    </a>
  );
}

function MarkdownBlockquote({
  children,
  ...props
}: HTMLAttributes<HTMLQuoteElement> & { children?: ReactNode }) {
  return <blockquote {...props}>{children}</blockquote>;
}

function MarkdownRule(props: HTMLAttributes<HTMLHRElement>) {
  return <hr {...props} />;
}

function MarkdownTable({
  children,
  ...props
}: HTMLAttributes<HTMLTableElement> & { children?: ReactNode }) {
  return (
    <div className="markdown-table-wrap">
      <table {...props}>{children}</table>
    </div>
  );
}

function MarkdownPre({
  children,
  renderMermaid,
  ...props
}: HTMLAttributes<HTMLPreElement> & {
  children?: ReactNode;
  renderMermaid: boolean;
}) {
  if (!hasVisibleCodeContent(children)) return null;

  const codeMeta = getCodeBlockMeta(children);
  if (
    renderMermaid &&
    codeMeta.language === "mermaid" &&
    isCompleteMermaidSource(codeMeta.text)
  ) {
    return <MermaidDiagramBlock source={codeMeta.text} />;
  }

  return (
    <div className="markdown-code-block">
      <MarkdownCodeBlockHeader
        language={codeMeta.language || "code"}
        text={codeMeta.text}
      />
      <pre {...props}>{children}</pre>
    </div>
  );
}

function MarkdownCodeBlockHeader({
  language,
  text,
}: {
  language: string;
  text: string;
}) {
  return (
    <div className="markdown-code-block__header">
      <span className="markdown-code-block__language">{language}</span>
      <CopyCodeButton text={text} />
    </div>
  );
}

function CopyCodeButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  async function copyCode() {
    const didCopy = await copyTextToClipboard(text);
    if (!didCopy) return;
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  }

  return (
    <button
      aria-label={copied ? "Copied code" : "Copy code"}
      className="markdown-code-block__copy"
      onClick={copyCode}
      title={copied ? "Copied" : "Copy code"}
      type="button"
    >
      {copied ? <Check size={13} /> : <Copy size={13} />}
      <span>{copied ? "Copied" : "Copy"}</span>
    </button>
  );
}

function MarkdownCode({
  children,
  ...props
}: HTMLAttributes<HTMLElement> & { children?: ReactNode }) {
  if (!hasVisibleCodeContent(children)) return null;
  return <code {...props}>{children}</code>;
}

async function copyTextToClipboard(text: string) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fall back to the hidden textarea path below.
  }

  const textarea = document.createElement("textarea");
  try {
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    textarea.style.top = "0";
    document.body.appendChild(textarea);
    textarea.select();
    const didCopy = document.execCommand("copy");
    document.body.removeChild(textarea);
    return didCopy;
  } catch {
    textarea.remove();
    return false;
  }
}

function isCompleteMermaidSource(source: string): boolean {
  const trimmed = source.trim();
  if (!trimmed) return false;
  return /^(graph|flowchart|sequenceDiagram|classDiagram|stateDiagram|stateDiagram-v2|erDiagram|journey|gantt|pie|mindmap|timeline|gitGraph|quadrantChart|requirementDiagram|C4Context)\b/i.test(
    trimmed
  );
}

type MermaidRenderState =
  | { status: "idle" | "loading" | "error" }
  | { status: "rendered"; svg: string };

function MermaidDiagramBlock({ source }: { source: string }) {
  const reactId = useId();
  const renderId = useMemo(
    () => `mermaid-${sanitizeMermaidId(reactId)}-${hashMermaidSource(source)}`,
    [reactId, source],
  );
  const [renderState, setRenderState] = useState<MermaidRenderState>({ status: "idle" });

  useEffect(() => {
    let isCancelled = false;
    const diagramSource = source.trim();

    if (!diagramSource) {
      setRenderState({ status: "idle" });
      return;
    }

    setRenderState({ status: "loading" });

    void import("mermaid")
      .then(({ default: mermaid }) => {
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: "base",
          themeVariables: MERMAID_THEME_VARIABLES,
        });
        return mermaid
          .parse(diagramSource, { suppressErrors: true })
          .then((parseResult) => {
            if (parseResult === false) throw new Error("Invalid Mermaid source");
            return mermaid.render(renderId, diagramSource);
          });
      })
      .then(({ svg }) => {
        if (!isCancelled) {
          setRenderState({ status: "rendered", svg });
        }
      })
      .catch(() => {
        if (!isCancelled) {
          setRenderState({ status: "error" });
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [renderId, source]);

  const hasRenderedDiagram = renderState.status === "rendered";

  return (
    <div className="mermaid-diagram-block">
      <div className="mermaid-diagram-block__header">
        <span>Mermaid diagram</span>
        <CopyCodeButton text={source} />
      </div>
      <div className="mermaid-diagram-block__canvas">
        {hasRenderedDiagram ? (
          <div dangerouslySetInnerHTML={{ __html: renderState.svg }} />
        ) : (
          <pre>
            <code>{source}</code>
          </pre>
        )}
      </div>
      {hasRenderedDiagram ? (
        <details className="mermaid-diagram-source">
          <summary>Mermaid source</summary>
          <pre>
            <code>{source}</code>
          </pre>
        </details>
      ) : null}
    </div>
  );
}

function sanitizeMermaidId(value: string): string {
  return value.replace(/[^A-Za-z0-9_-]/g, "");
}

function hashMermaidSource(value: string): string {
  let hash = 5381;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 33) ^ value.charCodeAt(index);
  }
  return (hash >>> 0).toString(36);
}

function getCodeBlockMeta(children: ReactNode) {
  const childArray = Children.toArray(children);
  const codeChild = childArray.find(
    (child) => isValidElement<HTMLAttributes<HTMLElement> & { children?: ReactNode }>(child)
  );

  if (isValidElement<HTMLAttributes<HTMLElement> & { children?: ReactNode }>(codeChild)) {
    const className =
      typeof codeChild.props.className === "string" ? codeChild.props.className : "";
    const languageMatch = className.match(/language-([\w-]+)/);
    return {
      language: languageMatch?.[1]?.toLowerCase() ?? "",
      text: extractNodeText(codeChild.props.children).replace(/\n$/, ""),
    };
  }

  return {
    language: "",
    text: extractNodeText(children).replace(/\n$/, ""),
  };
}

function hasVisibleCodeContent(node: ReactNode): boolean {
  return normalizeVisibleText(extractNodeText(node)).length > 0;
}

function normalizeVisibleText(value: string): string {
  return value
    .replace(/[\u200B-\u200D\uFEFF]/g, "")
    .replace(/\u00A0/g, " ")
    .trim();
}

function extractNodeText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractNodeText).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) {
    return extractNodeText(node.props.children);
  }
  return Children.toArray(node).map(extractNodeText).join("");
}
