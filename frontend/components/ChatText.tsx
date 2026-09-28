"use client";

import React from "react";

/** Safe Markdown renderer for AI responses; model-authored HTML is never injected. */
function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*|<br\s*\/>|<br>)/gi;
  let last = 0;
  let match: RegExpExecArray | null;
  let index = 0;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    const token = match[0];
    const key = `${keyPrefix}-${index}`;

    if (token.startsWith("**")) {
      nodes.push(<strong key={key} className="font-semibold text-[var(--foreground)]">{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("`")) {
      nodes.push(<code key={key} className="rounded bg-[var(--surface-strong)] px-1.5 py-0.5 font-mono text-[0.85em] text-[var(--foreground)]">{token.slice(1, -1)}</code>);
    } else if (token.toLowerCase().startsWith("<br")) {
      nodes.push(<br key={key} />);
    } else {
      nodes.push(<em key={key}>{token.slice(1, -1)}</em>);
    }

    last = match.index + token.length;
    index += 1;
  }

  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function tableCells(line: string) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function isTableDivider(line: string) {
  const cells = tableCells(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function isBlockStart(lines: string[], index: number) {
  const line = lines[index]?.trim() ?? "";
  const next = lines[index + 1]?.trim() ?? "";
  return line === "" || /^```/.test(line) || /^#{1,4}\s+/.test(line) || /^(?:-{3,}|\*{3,})$/.test(line) || /^>\s?/.test(line) || /^\s*[-*•]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line) || (line.includes("|") && isTableDivider(next));
}

export function ChatText({ content }: { content: string }) {
  const lines = content.replace(/\r\n?/g, "\n").split("\n");
  const blocks: React.ReactNode[] = [];
  let cursor = 0;

  while (cursor < lines.length) {
    const line = lines[cursor].trim();

    if (!line) {
      cursor += 1;
      continue;
    }

    if (/^```/.test(line)) {
      const language = line.slice(3).trim();
      const code: string[] = [];
      cursor += 1;
      while (cursor < lines.length && !/^```/.test(lines[cursor].trim())) {
        code.push(lines[cursor]);
        cursor += 1;
      }
      if (cursor < lines.length) cursor += 1;
      blocks.push(
        <div key={`code-${cursor}`} className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--navy)]">
          {language && <div className="border-b border-white/10 px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider text-white/50">{language}</div>}
          <pre className="overflow-x-auto p-3 text-xs leading-5 text-white/90"><code>{code.join("\n")}</code></pre>
        </div>,
      );
      continue;
    }

    if (line.includes("|") && isTableDivider(lines[cursor + 1] ?? "")) {
      const headers = tableCells(line);
      const rows: string[][] = [];
      cursor += 2;
      while (cursor < lines.length && lines[cursor].trim().includes("|")) {
        rows.push(tableCells(lines[cursor]));
        cursor += 1;
      }
      blocks.push(
        <div key={`table-${cursor}`} className="space-y-2">
          {rows.map((row, rowIndex) => (
            <div key={rowIndex} className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 shadow-[var(--shadow-sm)]">
              {headers.map((header, cellIndex) => (
                <div key={cellIndex} className={`${cellIndex ? "mt-2 border-t border-[var(--border)] pt-2" : ""}`}>
                  <p className="mb-0.5 text-[9px] font-bold uppercase tracking-[0.1em] text-[var(--muted)]">{renderInline(header, `th-${cursor}-${rowIndex}-${cellIndex}`)}</p>
                  <div className="text-xs leading-5 text-[var(--muted-strong)]">{renderInline(row[cellIndex] ?? "", `td-${cursor}-${rowIndex}-${cellIndex}`)}</div>
                </div>
              ))}
            </div>
          ))}
        </div>,
      );
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      const classes = level <= 2 ? "pt-2 text-base font-bold" : "pt-1 text-sm font-bold";
      blocks.push(<div key={`heading-${cursor}`} role="heading" aria-level={level} className={`${classes} leading-snug text-[var(--foreground)]`}>{renderInline(heading[2], `heading-${cursor}`)}</div>);
      cursor += 1;
      continue;
    }

    if (/^(?:-{3,}|\*{3,})$/.test(line)) {
      blocks.push(<hr key={`hr-${cursor}`} className="my-1 border-0 border-t border-[var(--border)]" />);
      cursor += 1;
      continue;
    }

    if (/^[-*•]\s+/.test(line)) {
      const items: string[] = [];
      while (cursor < lines.length) {
        const item = lines[cursor].trim().match(/^[-*•]\s+(.+)$/);
        if (!item) break;
        items.push(item[1]);
        cursor += 1;
      }
      blocks.push(<ul key={`ul-${cursor}`} className="ml-5 list-disc space-y-1.5 marker:text-[var(--accent)]">{items.map((item, index) => <li key={index} className="pl-1">{renderInline(item, `li-${cursor}-${index}`)}</li>)}</ul>);
      continue;
    }

    if (/^\d+[.)]\s+/.test(line)) {
      const items: string[] = [];
      while (cursor < lines.length) {
        const item = lines[cursor].trim().match(/^\d+[.)]\s+(.+)$/);
        if (!item) break;
        items.push(item[1]);
        cursor += 1;
      }
      blocks.push(<ol key={`ol-${cursor}`} className="ml-5 list-decimal space-y-1.5 marker:font-semibold marker:text-[var(--accent)]">{items.map((item, index) => <li key={index} className="pl-1">{renderInline(item, `oli-${cursor}-${index}`)}</li>)}</ol>);
      continue;
    }

    if (/^>\s?/.test(line)) {
      const quote: string[] = [];
      while (cursor < lines.length && /^>\s?/.test(lines[cursor].trim())) {
        quote.push(lines[cursor].trim().replace(/^>\s?/, ""));
        cursor += 1;
      }
      blocks.push(<blockquote key={`quote-${cursor}`} className="rounded-r-lg border-l-2 border-[var(--accent)] bg-[var(--accent-soft)] px-3 py-2 italic text-[var(--muted-strong)]">{renderInline(quote.join(" "), `quote-${cursor}`)}</blockquote>);
      continue;
    }

    const paragraph = [line];
    cursor += 1;
    while (cursor < lines.length && !isBlockStart(lines, cursor)) {
      paragraph.push(lines[cursor].trim());
      cursor += 1;
    }
    blocks.push(<p key={`p-${cursor}`} className="whitespace-pre-wrap leading-relaxed">{renderInline(paragraph.join(" "), `p-${cursor}`)}</p>);
  }

  return <div className="space-y-3 break-words">{blocks}</div>;
}
