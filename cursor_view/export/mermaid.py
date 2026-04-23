"""Mermaid diagram rendering helpers for the HTML export.

Chat-view rendering is implemented entirely in the React bundle (see
``frontend/src/components/MermaidBlock.js``). This module is only
consumed by :mod:`cursor_view.export.html` and has two jobs:

1. Rewrite fenced code blocks whose info string is ``mermaid`` into
   inline ``<div class="mermaid">`` elements *before*
   :mod:`markdown` (Python-Markdown) sees them, because
   ``fenced_code`` has no native mermaid support and Pygments falls
   back to ``TextLexer`` for unknown languages.
2. Return the vendored ``mermaid.min.js`` contents plus an
   initializer ``<script>`` tag for inclusion in the exported HTML so
   every export is self-contained (no network at view time), matching
   the same inline-everything philosophy the image export path uses
   (see ``.cursor/rules/image-attachments.mdc``).

The fence-rewrite pass assumes its input has already been normalized
by :func:`cursor_view.export.markdown_fences.normalize_markdown_for_html_export`
(line endings collapsed to ``\\n``). Callers outside that pipeline
should do the same first; the regex keys on ``\\n`` explicitly.
"""

import functools
import html
import re
from importlib import resources

# Matches a fenced code block whose info string is exactly ``mermaid``
# (optionally padded with spaces or tabs) at column 0. Captures the
# body so it can be HTML-escaped before being handed to the browser.
# ``re.DOTALL`` lets ``.`` span newlines inside the body; ``re.MULTILINE``
# anchors ``^`` / ``$`` to line boundaries so multiple mermaid fences
# in one message are each matched independently.
_MERMAID_FENCE_RE = re.compile(
    r"^```[ \t]*mermaid[ \t]*\n(.*?)\n```[ \t]*$",
    re.DOTALL | re.MULTILINE,
)


def transform_mermaid_fences_to_html(markdown_content: str) -> str:
    """Replace mermaid fenced-code blocks with ``<div class="mermaid">`` HTML.

    We rewrite the fence to a raw HTML element surrounded by blank
    lines so Python-Markdown treats it as a block-level HTML
    pass-through rather than handing the body to ``fenced_code`` and
    producing a useless ``<pre><code class="language-mermaid">``
    wrapper the browser has no idea what to do with.

    The body is run through :func:`html.escape` so mermaid source
    containing literal ``<``, ``>``, ``&``, or quote characters
    survives as the browser's text content (mermaid's parser operates
    on the decoded text of the ``<div>``, so escaped entities are
    decoded before parsing). This is the actual XSS boundary for
    authored content; mermaid's own ``securityLevel: "strict"`` init
    option is belt-and-braces on top.
    """
    def _wrap(match: "re.Match[str]") -> str:
        body = html.escape(match.group(1))
        return f'\n\n<div class="mermaid">{body}</div>\n\n'

    return _MERMAID_FENCE_RE.sub(_wrap, markdown_content)


@functools.lru_cache(maxsize=1)
def load_vendored_mermaid_js() -> str:
    """Return the vendored ``mermaid.min.js`` contents, cached per process.

    Reads through :mod:`importlib.resources` so the lookup works
    identically from a source checkout and from inside the PyInstaller
    bundle (``cursor_view/export/vendor/mermaid.min.js`` is shipped via
    the spec's ``datas=`` entry). The file is ~3 MB; the
    ``lru_cache`` avoids re-reading it on every exported chat.
    """
    return (
        resources.files("cursor_view.export.vendor")
        .joinpath("mermaid.min.js")
        .read_text(encoding="utf-8")
    )


def build_mermaid_init_script(theme_mode: str) -> str:
    """Return an inline ``<script>`` that renders mermaid diagrams for the export.

    Uses ``startOnLoad: false`` and a manual async rendering loop so that
    syntax errors are handled explicitly: ``mermaid.parse`` validates each
    diagram source first (DOM-free, no bomb-graphic side effect on failure),
    and only diagrams that pass validation proceed to ``mermaid.render``.
    Invalid diagrams are replaced with a styled error block showing the
    error message and raw source, matching the chat view UI's error fallback
    in ``frontend/src/components/MermaidBlock.js``.

    ``theme_mode`` mirrors the ``theme_mode`` argument threaded through
    :func:`cursor_view.export.html.generate_standalone_html` so the mermaid
    theme tracks the CSS palette chosen by the user.
    """
    theme = "dark" if theme_mode == "dark" else "default"
    # The toggle button uses a minimal inline SVG that approximates the
    # CodeIcon (view source) used by MermaidBlock in the chat UI. When the
    # user switches to source view the button label changes to "View diagram".
    # Error-state elements get no toggle: there is no SVG to toggle to,
    # matching MermaidBlock's behaviour of locking to source view on error.
    return (
        f'<script>'
        f'mermaid.initialize({{startOnLoad: false, securityLevel: "strict", theme: "{theme}"}});'
        "(async function(){"
        "function _esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}"
        # Code icon: two angle brackets — shown when diagram is visible (click → view source).
        "var _codeIcon='<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"16\" height=\"16\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><polyline points=\"16 18 22 12 16 6\"></polyline><polyline points=\"8 6 2 12 8 18\"></polyline></svg>';"
        # Diagram icon: AccountTreeIcon path from @mui/icons-material — shown when source is visible (click → view diagram).
        "var _diagIcon='<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"16\" height=\"16\" viewBox=\"0 0 24 24\"><path d=\"M22 11V3h-7v3H9V3H2v8h7V8h2v10h4v3h7v-8h-7v3h-2V8h2v3z\" fill=\"currentColor\"/></svg>';"
        "function _btn(label){"
        "return '<button class=\"mermaid-toggle\" title=\"'+label+'\">'+_codeIcon+'</button>';}"
        "var els=document.querySelectorAll('.mermaid');"
        "for(var i=0;i<els.length;i++){"
        "var el=els[i];"
        # textContent decodes HTML entities, giving the original mermaid source.
        "var src=el.textContent;"
        "try{await mermaid.parse(src);}catch(parseErr){"
        # Parse failed: show styled error + raw source; never call mermaid.render
        # so mermaid's bomb graphic is never injected into the document.
        "el.className='mermaid mermaid-error';"
        "el.innerHTML='<p class=\"mermaid-error-msg\">Mermaid parse error: '+_esc(String(parseErr&&parseErr.message?parseErr.message:parseErr))+'</p>'"
        "+'<pre class=\"mermaid-error-src\">'+_esc(src)+'</pre>';"
        "continue;}"
        "try{"
        "var res=await mermaid.render('mermaid-export-'+i,src);"
        # Successful render: wrap SVG + hidden source pre + toggle button.
        "el.innerHTML=_btn('View source')"
        "+'<div class=\"mermaid-diagram\">'+res.svg+'</div>'"
        "+'<pre class=\"mermaid-source\" style=\"display:none\">'+_esc(src)+'</pre>';"
        # Wire the toggle click handler via closure over el.
        "(function(container){"
        "container.querySelector('.mermaid-toggle').addEventListener('click',function(e){"
        "var diag=container.querySelector('.mermaid-diagram');"
        "var srcEl=container.querySelector('.mermaid-source');"
        "var btn=e.currentTarget;"
        "var showingDiagram=diag.style.display!=='none';"
        "diag.style.display=showingDiagram?'none':'';"
        "srcEl.style.display=showingDiagram?'':'none';"
        "btn.title=showingDiagram?'View diagram':'View source';"
        "btn.innerHTML=showingDiagram?_diagIcon:_codeIcon;"
        "});"
        "})(el);"
        "}catch(renderErr){"
        "el.className='mermaid mermaid-error';"
        "el.innerHTML='<p class=\"mermaid-error-msg\">Mermaid render error: '+_esc(String(renderErr&&renderErr.message?renderErr.message:renderErr))+'</p>'"
        "+'<pre class=\"mermaid-error-src\">'+_esc(src)+'</pre>';}"
        "}})();"
        "</script>"
    )
