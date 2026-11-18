// Safe markdown subset for model output (DESIGN §8.3): no raw HTML ever (React escapes every string), no images,
// and links only to medicare.gov, cms.gov and shiphelp.org (anything else renders as plain text).
import type { ReactNode } from "react";

export const ALLOWED_HOSTS = ["medicare.gov", "cms.gov", "shiphelp.org"];

export function allowedLink(href: string): boolean {
  try {
    const u = new URL(href);
    if (u.protocol !== "https:") return false;
    return ALLOWED_HOSTS.some((h) => u.hostname === h || u.hostname.endsWith(`.${h}`));
  } catch {
    return false;
  }
}

function inline(text: string, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\))/g;
  let last = 0;
  let i = 0;
  for (const m of text.matchAll(re)) {
    const idx = m.index ?? 0;
    if (idx > last) out.push(text.slice(last, idx));
    const tok = m[0];
    const k = `${key}-${i++}`;
    if (tok.startsWith("**")) out.push(<strong key={k}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("`")) out.push(<code key={k}>{tok.slice(1, -1)}</code>);
    else if (tok.startsWith("[")) {
      const label = tok.slice(1, tok.indexOf("]"));
      const href = tok.slice(tok.indexOf("(") + 1, -1);
      out.push(
        allowedLink(href) ? (
          <a key={k} href={href} target="_blank" rel="noreferrer noopener">
            {label}
          </a>
        ) : (
          <span key={k}>{label}</span>
        ),
      );
    } else out.push(<em key={k}>{tok.slice(1, -1)}</em>);
    last = idx + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  const lines = text.replace(/\r/g, "").split("\n");
  let list: string[] = [];
  let para: string[] = [];
  const flush = () => {
    if (para.length) {
      const k = `p${blocks.length}`;
      blocks.push(<p key={k}>{inline(para.join(" "), k)}</p>);
      para = [];
    }
    if (list.length) {
      const k = `l${blocks.length}`;
      blocks.push(
        <ul key={k}>
          {list.map((li, j) => (
            <li key={j}>{inline(li, `${k}-${j}`)}</li>
          ))}
        </ul>,
      );
      list = [];
    }
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    const bullet = /^\s*(?:[-*•]|\d+\.)\s+(.*)$/.exec(line);
    if (!line.trim()) flush();
    else if (bullet) {
      if (para.length) flush();
      list.push(bullet[1]);
    } else if (/^#{1,6}\s/.test(line)) {
      flush();
      const k = `h${blocks.length}`;
      blocks.push(<h4 key={k}>{inline(line.replace(/^#+\s*/, ""), k)}</h4>);
    } else {
      if (list.length) flush();
      para.push(line);
    }
  }
  flush();
  return <div className="md">{blocks}</div>;
}
