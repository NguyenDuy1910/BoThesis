"use client";

import {
  Children,
  createContext,
  isValidElement,
  memo,
  useContext,
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
import remend, { type RemendOptions } from "remend";

import {
  nextRevealLength,
  REVEAL_COMMIT_INTERVAL_MS,
  splitStreamingMarkdown,
} from "../streaming-markdown";

const MARKDOWN_REMARK_PLUGINS = [remarkGfm, remarkMath];
const MARKDOWN_REHYPE_PLUGINS = [rehypeKatex];

// Only the streaming tail can hold a half-written marker, so self-healing runs
// there and nowhere else. `text-only` keeps a partial `[label](htt` as plain
// text instead of minting a placeholder href the reader could click.
const TAIL_REMEND_OPTIONS: RemendOptions = { linkMode: "text-only" };

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

// ONE components object for every render — the finished prefix, the arriving
// tail, and the completed answer. Element types stay identical across the whole
// turn, so the transition out of streaming is a diff rather than a remount.
const MARKDOWN_COMPONENTS: Components = {
  a: MarkdownLink,
  blockquote: MarkdownBlockquote,
  h1: MarkdownHeading1,
  h2: MarkdownHeading2,
  h3: MarkdownHeading3,
  hr: MarkdownRule,
  pre: MarkdownPre,
  code: MarkdownCode,
  table: MarkdownTable,
};

// Mermaid renders only once the answer is complete: it is async and stateful, so
// rendering it from half-written source would flash. Passing that through
// context instead of a second components object keeps ``pre`` one component.
const MermaidRenderingContext = createContext(false);

export const StreamingMarkdown = memo(function StreamingMarkdown({
  text,
  isStreaming,
  onRevealingChange,
}: {
  text: string;
  isStreaming: boolean;
  /** Report whether text is still easing onto screen, stream ended or not. */
  onRevealingChange?: (isRevealing: boolean) => void;
}) {
  const revealed = useRevealedText(text, isStreaming);
  // Keep draining after the stream ends: snapping to the full text there is
  // what made a fast answer land in one paint.
  const isRevealing = isStreaming || revealed.length < text.length;
  useEffect(() => {
    onRevealingChange?.(isRevealing);
  }, [isRevealing, onRevealingChange]);
  const { stable, tail } = useMemo(
    () => (isRevealing ? splitStreamingMarkdown(revealed) : { stable: revealed, tail: "" }),
    [revealed, isRevealing],
  );

  return (
    <MermaidRenderingContext.Provider value={!isRevealing}>
      <StableMarkdown content={stable} />
      {tail ? <StreamingMarkdownTail content={tail} /> : null}
    </MermaidRenderingContext.Provider>
  );
});

export const IncrementalMarkdown = StreamingMarkdown;

/**
 * Ease the accumulated text onto screen at a steady cadence.
 *
 * Deltas are appended to one canonical string by the message reducer; this only
 * decides how much of that string is painted per commit. The reveal is capped at
 * one commit per interval so markdown is parsed ~30x/s instead of once per
 * delta, and the step scales with the backlog so a burst — or a whole answer
 * that arrives at once — still finishes within a few hundred milliseconds.
 */
function useRevealedText(text: string, isStreaming: boolean): string {
  const [revealed, setRevealed] = useState(() => (isStreaming ? "" : text));
  const targetRef = useRef(text);
  const revealedLengthRef = useRef(revealed.length);
  const frameRef = useRef<number | null>(null);
  const lastCommitRef = useRef(0);
  targetRef.current = text;

  useEffect(() => {
    // A regenerated answer replaces the text instead of extending it.
    if (text.length < revealedLengthRef.current) {
      revealedLengthRef.current = text.length;
      lastCommitRef.current = 0;
      setRevealed(text);
      return;
    }
    if (revealedLengthRef.current >= text.length || frameRef.current !== null) return;

    const commit = (now: number) => {
      frameRef.current = null;
      const target = targetRef.current;
      if (revealedLengthRef.current >= target.length) return;
      if (lastCommitRef.current && now - lastCommitRef.current < REVEAL_COMMIT_INTERVAL_MS) {
        frameRef.current = requestAnimationFrame(commit);
        return;
      }
      const length = nextRevealLength(target, revealedLengthRef.current);
      revealedLengthRef.current = length;
      lastCommitRef.current = now;
      setRevealed(target.slice(0, length));
      if (length < targetRef.current.length) {
        frameRef.current = requestAnimationFrame(commit);
      }
    };

    frameRef.current = requestAnimationFrame(commit);
  }, [text]);

  useEffect(() => () => {
    if (frameRef.current === null) return;
    cancelAnimationFrame(frameRef.current);
    // Clear the handle as well: StrictMode remounts run this between the two
    // effect passes, and a stale handle would make the reveal never restart.
    frameRef.current = null;
  }, []);

  return revealed;
}

const StableMarkdown = memo(function StableMarkdown({ content }: { content: string }) {
  return <MarkdownRenderer content={content} />;
});

const StreamingMarkdownTail = memo(function StreamingMarkdownTail({
  content,
}: {
  content: string;
}) {
  // Close the markers the model has opened but not yet finished, so bold, code,
  // and links render as formatting while they arrive rather than flashing their
  // raw `**` / backtick / bracket syntax at the reader for a frame.
  const healed = useMemo(() => remend(content, TAIL_REMEND_OPTIONS), [content]);

  return <MarkdownRenderer content={healed} normalizeMath={false} />;
});

function MarkdownRenderer({
  content,
  normalizeMath = true,
}: {
  content: string;
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
      components={MARKDOWN_COMPONENTS}
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

function isInsideOpenCodeFence(content: string): boolean {
  const matches = content.match(/^```/gm);
  return Boolean(matches && matches.length % 2 === 1);
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
  ...props
}: HTMLAttributes<HTMLPreElement> & { children?: ReactNode }) {
  const renderMermaid = useContext(MermaidRenderingContext);
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
