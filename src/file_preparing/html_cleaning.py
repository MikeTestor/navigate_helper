"""Strip an .htm/.html file down to its plain text content.

Only handles the generic, boilerplate-stripping part (scripts, styles, nav,
entities, whitespace). Picking out a specific site's real content div is
project-specific and belongs in that project, not here.
"""

from bs4 import BeautifulSoup

STRIP_TAGS = ("script", "style", "noscript", "nav", "header", "footer")


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(STRIP_TAGS):
        tag.decompose()

    text = soup.get_text(separator="\n")
    lines = (line.strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)
