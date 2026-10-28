"""Web tools: `webfetch` (GET a page, return readable text) and `websearch` (Tavily or Brave).

``make_client`` is the single place an ``httpx.AsyncClient`` is built so tests can swap in a
``MockTransport``.
"""

from __future__ import annotations

import os
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

from afh.engine.types import ToolContext, ToolResult, ToolSpec
from afh.engine.tools.files import BaseTool, ToolError, int_arg, str_arg

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 AFH/1.0"
MAX_TEXT = 100_000  # characters of page text handed to the model
DEFAULT_TIMEOUT = 30.0
SEARCH_DEFAULT_LIMIT = 5
SEARCH_MAX_LIMIT = 10

TAVILY_URL = "https://api.tavily.com/search"
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


def make_client(timeout: float = DEFAULT_TIMEOUT) -> httpx.AsyncClient:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    return httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=timeout)


def search_api_key(settings: dict | None) -> tuple[str, str] | None:
    """(provider, key) from settings (top level, `web`, `keys` or `env` sections) or the environment."""
    s = settings or {}
    scopes = [s] + [s.get(k) for k in ("web", "keys", "env") if isinstance(s.get(k), dict)]
    for provider, names in (("tavily", ("TAVILY_API_KEY", "tavilyApiKey")), ("brave", ("BRAVE_API_KEY", "braveApiKey"))):
        for scope in scopes:
            for name in names:
                if scope.get(name):
                    return provider, str(scope[name]).strip()
        for name in names:
            if os.environ.get(name):
                return provider, os.environ[name].strip()
    return None


# ---- HTML → text --------------------------------------------------------------------------

_SKIP_TAGS = frozenset({"script", "style", "noscript", "nav", "template", "svg", "iframe", "head", "canvas", "video", "audio"})
_BLOCK_TAGS = frozenset({
    "p", "div", "section", "article", "main", "aside", "footer", "header", "ul", "ol", "table", "thead", "tbody",
    "tr", "blockquote", "dl", "dt", "dd", "form", "figure", "figcaption", "details", "summary", "address", "fieldset",
})
_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_WS = re.compile(r"\s+")


class HTMLToText(HTMLParser):
    """Readable text from HTML. markdown=True keeps headings, links, lists and code as light markdown."""

    def __init__(self, base_url: str = "", markdown: bool = True):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.markdown = markdown
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False
        self._pre = 0
        self._link: list[tuple[str, list[str]]] = []  # (href, text parts) for nested <a>

    def _emit(self, s: str) -> None:
        if self._link:
            self._link[-1][1].append(s)
        else:
            self.parts.append(s)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
            return
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if self._skip:
            return
        a = dict(attrs)
        if tag in _HEADINGS:
            self._emit("\n\n" + ("#" * _HEADINGS[tag] + " " if self.markdown else ""))
        elif tag == "li":
            self._emit("\n- ")
        elif tag == "br":
            self._emit("\n")
        elif tag == "hr":
            self._emit("\n\n---\n\n" if self.markdown else "\n\n")
        elif tag == "pre":
            self._pre += 1
            self._emit("\n\n```\n" if self.markdown else "\n\n")
        elif tag == "code" and not self._pre and self.markdown:
            self._emit("`")
        elif tag == "a":
            href = (a.get("href") or "").strip()
            if href and not href.startswith(("javascript:", "#")) and self.base_url:
                href = urljoin(self.base_url, href)
            self._link.append((href, []))
        elif tag == "img":
            alt = (a.get("alt") or "").strip()
            if alt:
                self._emit(f"[image: {alt}]")
        elif tag in _BLOCK_TAGS:
            self._emit("\n\n" if tag in ("p", "blockquote", "table", "ul", "ol", "dl") else "\n")
        elif tag in ("td", "th"):
            self._emit(" | " if self.markdown else "  ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
            return
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag in _HEADINGS or tag in _BLOCK_TAGS:
            self._emit("\n\n" if tag in _HEADINGS or tag in ("p", "blockquote", "table", "ul", "ol") else "\n")
        elif tag == "li":
            self._emit("\n")
        elif tag == "pre":
            self._pre = max(0, self._pre - 1)
            self._emit("\n```\n\n" if self.markdown else "\n\n")
        elif tag == "code" and not self._pre and self.markdown:
            self._emit("`")
        elif tag == "a" and self._link:
            href, parts = self._link.pop()
            text = _WS.sub(" ", "".join(parts)).strip()
            if not text:
                return
            if self.markdown and href and href != text:
                self._emit(f"[{text}]({href})")
            else:
                self._emit(text)

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
            return
        if self._skip:
            return
        self._emit(data if self._pre else _WS.sub(" ", data))

    def text(self) -> str:
        raw = "".join(self.parts)
        lines = [l.rstrip() for l in raw.split("\n")]
        out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
        return re.sub(r"(?<=\n)[ \t]+(?=\S)", "", out) if not self.markdown else out


def html_to_text(html_text: str, base_url: str = "", markdown: bool = True) -> tuple[str, str]:
    """Returns (text, title)."""
    parser = HTMLToText(base_url, markdown)
    parser.feed(html_text)
    parser.close()
    return parser.text(), _WS.sub(" ", parser.title).strip()


def _looks_like_html(content_type: str, body: str) -> bool:
    if "html" in content_type or "xml" in content_type:
        return True
    head = body.lstrip()[:200].lower()
    return not content_type and (head.startswith("<!doctype") or head.startswith("<html"))


# ---- webfetch -------------------------------------------------------------------------------


class WebFetchTool(BaseTool):
    spec = ToolSpec(
        name="webfetch",
        description=(
            "Fetches a web page or file over HTTP(S) and returns its content as readable text. HTML is converted "
            "to light markdown by default (headings, links, lists and code blocks kept; scripts, styles and "
            "navigation removed); set `format` to `text` for plain text or `html` for the raw source. JSON and "
            "plain-text responses are returned as-is. Redirects are followed and the result is capped at "
            "100000 characters. Use it for documentation, APIs and pages the user points you to; use `websearch` "
            "first when you do not know the URL."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The http:// or https:// URL to fetch."},
                "format": {"type": "string", "enum": ["markdown", "text", "html"], "description": "How to return HTML pages (default markdown)."},
                "timeout": {"type": "integer", "description": f"Seconds to wait for the response (default {int(DEFAULT_TIMEOUT)})."},
            },
            "required": ["url"],
        },
    )

    async def _run(self, ctx: ToolContext, input: dict) -> ToolResult:
        url = str_arg(input, "url").strip()
        fmt = (str_arg(input, "format", required=False) or "markdown").lower()
        if fmt not in ("markdown", "text", "html"):
            raise ToolError("format must be one of markdown, text, html.")
        timeout = float(min(300, max(1, int_arg(input, "timeout", int(DEFAULT_TIMEOUT)))))
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ToolError(f"Only http:// and https:// URLs can be fetched, got {url!r}.")
        await ctx.permissions.require("web", [url], {"url": url})

        try:
            async with make_client(timeout) as client:
                response = await client.get(url)
        except httpx.HTTPError as e:
            raise ToolError(f"Request to {url} failed: {type(e).__name__}: {e}") from None

        content_type = response.headers.get("content-type", "").lower()
        body = response.text
        final_url = str(response.url)
        title = ""
        if response.status_code >= 400:
            preview = body[:2000]
            return ToolResult(text=f"HTTP {response.status_code} for {final_url}\n\n{preview}".rstrip(), is_error=True,
                              metadata={"url": final_url, "status": response.status_code, "contentType": content_type})

        if fmt != "html" and _looks_like_html(content_type, body):
            body, title = html_to_text(body, final_url, markdown=(fmt == "markdown"))
        truncated = len(body) > MAX_TEXT
        if truncated:
            body = body[:MAX_TEXT] + f"\n\n… (truncated: the page has {len(response.text)} characters) …"
        return ToolResult(text=body or "(empty response)", truncated=truncated,
                          metadata={"url": final_url, "status": response.status_code, "contentType": content_type, "title": title})


# ---- websearch ------------------------------------------------------------------------------


class WebSearchTool(BaseTool):
    spec = ToolSpec(
        name="websearch",
        description=(
            "Searches the web and returns the top results with title, URL and a snippet. Use it to find "
            "documentation, error messages, library versions or anything you are not sure about, then open the "
            "best result with `webfetch`. Keep queries short and specific (a library name plus the exact error "
            "works better than a sentence). Returns up to `limit` results (default 5, max 10)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
                "limit": {"type": "integer", "description": f"Number of results (default {SEARCH_DEFAULT_LIMIT}, max {SEARCH_MAX_LIMIT})."},
            },
            "required": ["query"],
        },
    )

    async def _run(self, ctx: ToolContext, input: dict) -> ToolResult:
        query = str_arg(input, "query").strip()
        limit = min(SEARCH_MAX_LIMIT, max(1, int_arg(input, "limit", SEARCH_DEFAULT_LIMIT)))
        key = search_api_key(ctx.settings)
        if key is None:
            raise ToolError("Web search is not configured. Add a Tavily (TAVILY_API_KEY) or Brave (BRAVE_API_KEY) key in Settings to enable it.")
        provider, api_key = key
        await ctx.permissions.require("web", [f"search:{query}"], {"query": query, "provider": provider})

        try:
            async with make_client(DEFAULT_TIMEOUT) as client:
                if provider == "tavily":
                    response = await client.post(TAVILY_URL, headers={"Authorization": f"Bearer {api_key}"},
                                                 json={"api_key": api_key, "query": query, "max_results": limit, "include_answer": True})
                else:
                    response = await client.get(BRAVE_URL, params={"q": query, "count": limit},
                                                headers={"X-Subscription-Token": api_key, "Accept": "application/json"})
        except httpx.HTTPError as e:
            raise ToolError(f"Search request failed: {type(e).__name__}: {e}") from None
        if response.status_code >= 400:
            raise ToolError(f"{provider} search returned HTTP {response.status_code}: {response.text[:500]}")
        try:
            data = response.json()
        except ValueError:
            raise ToolError(f"{provider} search returned a non-JSON response.") from None

        results: list[dict] = []
        answer = ""
        if provider == "tavily":
            answer = (data.get("answer") or "").strip()
            for r in data.get("results") or []:
                results.append({"title": r.get("title") or "", "url": r.get("url") or "", "snippet": r.get("content") or ""})
        else:
            for r in ((data.get("web") or {}).get("results") or []):
                results.append({"title": r.get("title") or "", "url": r.get("url") or "", "snippet": r.get("description") or ""})
        results = results[:limit]
        if not results:
            return ToolResult(text=f"No results for {query!r}.", metadata={"provider": provider, "count": 0})

        lines = []
        if answer:
            lines.append(f"Summary: {answer}\n")
        for i, r in enumerate(results, 1):
            snippet = _WS.sub(" ", r["snippet"]).strip()
            lines.append(f"{i}. {r['title']}\n   {r['url']}" + (f"\n   {snippet}" if snippet else ""))
        return ToolResult(text="\n".join(lines), metadata={"provider": provider, "count": len(results), "results": results})
