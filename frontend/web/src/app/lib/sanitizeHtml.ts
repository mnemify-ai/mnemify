/** Minimal HTML sanitizer: strips <script>/<style>/<iframe>/<object>/<embed>,
 *  inline event handlers, and javascript: URLs. Safe enough for self-owned
 *  content (Confluence storage format, mammoth-emitted DOCX HTML). NOT a
 *  replacement for DOMPurify on truly untrusted input from third parties. */
export function sanitizeHtml(html: string): string {
  let out = html;
  out = out.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "");
  out = out.replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, "");
  out = out.replace(/<iframe\b[^>]*>[\s\S]*?<\/iframe>/gi, "");
  out = out.replace(/<object\b[^>]*>[\s\S]*?<\/object>/gi, "");
  out = out.replace(/<embed\b[^>]*\/?>/gi, "");
  out = out.replace(/\son\w+="[^"]*"/gi, "");
  out = out.replace(/\son\w+='[^']*'/gi, "");
  out = out.replace(/javascript:/gi, "");
  return out;
}
