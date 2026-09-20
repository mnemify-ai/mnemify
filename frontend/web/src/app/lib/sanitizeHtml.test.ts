// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { sanitizeHtml } from "./sanitizeHtml";

// Payloads that all passed the old regex sanitizer untouched.
const HOSTILE = [
  "<img src=x onerror=alert(1)>",
  '<img src=x onerror ="alert(1)">',
  "<svg onload=alert(1)></svg>",
  "<details open ontoggle=alert(1)>x</details>",
  '<a href="java&#10;script:alert(1)">x</a>',
  '<a href="&#106;avascript:alert(1)">x</a>',
  '<base href="https://evil.example/">',
  '<link rel="stylesheet" href="//evil.example/x.css">',
  '<form action="https://evil.example"><input name=a></form>',
  '<iframe src="https://evil.example"></iframe>',
  "<script>alert(1)</script>",
  '<math><mi xlink:href="javascript:alert(1)">x</mi></math>',
];

describe("sanitizeHtml", () => {
  it.each(HOSTILE)("neutralises %s", (payload) => {
    const out = sanitizeHtml(payload).toLowerCase();
    expect(out).not.toMatch(/on[a-z]+\s*=/);
    expect(out).not.toContain("javascript");
    expect(out).not.toMatch(/<(base|link|form|input|iframe|script|svg|math|style|meta)\b/);
  });

  it("keeps the markup the Confluence rewriter emits", () => {
    const html =
      '<details class="cf-expand"><summary>T</summary>' +
      '<div class="cf-expand__body"><pre><code class="language-py">x</code></pre>' +
      '<img src="/api/documents/1/attachments/a.png" alt="a" loading="lazy">' +
      '<span class="cf-status cf-status--green" title="ok">Done</span>' +
      "<table><tbody><tr><td>c</td></tr></tbody></table></div></details>";
    const out = sanitizeHtml(html);
    expect(out).toContain('<details class="cf-expand">');
    expect(out).toContain('<code class="language-py">x</code>');
    expect(out).toContain('src="/api/documents/1/attachments/a.png"');
    expect(out).toContain('title="ok"');
    expect(out).toContain("<td>c</td>");
  });

  it("allows http(s), mailto, root-relative and data:image URLs only", () => {
    expect(sanitizeHtml('<a href="https://ok.example">x</a>')).toContain('href="https://ok.example"');
    expect(sanitizeHtml('<a href="mailto:a@b.c">x</a>')).toContain('href="mailto:a@b.c"');
    expect(sanitizeHtml('<img src="data:image/png;base64,AAAA">')).toContain("data:image/png");
    expect(sanitizeHtml('<img src="data:text/html;base64,AAAA">')).not.toContain("data:");
    expect(sanitizeHtml('<a href="//evil.example">x</a>')).not.toContain("evil.example");
  });

  it("forces harvested links to open in a new tab without window.opener", () => {
    const out = sanitizeHtml('<a href="https://ok.example">x</a>');
    expect(out).toContain('target="_blank"');
    expect(out).toContain('rel="noopener noreferrer"');
  });
});
