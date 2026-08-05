#!/usr/bin/env python3
"""Rebuild the generated sections of README.md from live GitHub data.

Everything this script writes is derived from the GitHub GraphQL API at run
time, so the profile cannot drift out of date the way hardcoded numbers do.

Sections are delimited by HTML comments:

    <!--STATS:START-->    portfolio counters
    <!--LANGS:START-->    language breakdown by repository

Language share is measured in *repositories*, not bytes. Byte counts are
dominated by whatever vendored dependency tree happens to be committed
somewhere, which makes them a measure of `node_modules`, not of authorship.

Auth: GH_TOKEN. A classic PAT with `repo` + `read:user` includes private
repositories in the totals; the default GITHUB_TOKEN only sees public data.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone

API = "https://api.github.com/graphql"
LOGIN = os.environ.get("GH_LOGIN", "w1zardz")
TOKEN = os.environ.get("GH_TOKEN", "")
README = os.environ.get("README_PATH", "README.md")

BIRTH = date(2003, 6, 23)
CAREER_START = 2016

# Markup, config and build scaffolding — present in every repository and
# therefore meaningless as a signal of what someone actually builds.
LANG_IGNORE = {
    "HTML", "CSS", "SCSS", "Less", "Dockerfile", "Makefile", "M4", "Shell",
    "Batchfile", "Procfile", "Roff", "Vim Script", "Jupyter Notebook",
    "EJS", "Handlebars", "Pug", "Blade", "Twig", "Smarty", "Mustache",
}

# Self-assessed proficiency. Anything absent is left blank rather than guessed.
EXPERTISE = {
    "PHP": "Master",
    "Pawn": "Master",
    "TypeScript": "Expert",
    "JavaScript": "Expert",
    "Python": "Advanced",
    "Vue": "Advanced",
    "Go": "Advanced",
    "SQL": "Advanced",
    "C++": "Advanced",
    "C": "Advanced",
    "Lua": "Advanced",
    "Rust": "Intermediate",
}

REPO_QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    followers { totalCount }
    repositories(first: 100, after: $cursor, ownerAffiliations: OWNER, isFork: false) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        isPrivate
        stargazerCount
        pushedAt
        primaryLanguage { name }
        languages(first: 6, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
  }
}
"""


def graphql(query: str, **variables) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={
            "Authorization": f"bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": f"{LOGIN}-profile-stats",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        sys.exit(f"GitHub API HTTP {exc.code}: {exc.read().decode(errors='replace')[:500]}")
    if "errors" in payload:
        sys.exit(f"GitHub API errors: {json.dumps(payload['errors'])[:500]}")
    return payload["data"]


def collect() -> dict:
    stars = private = public = followers = 0
    # repos_by_lang counts a language once per repository that uses it
    # meaningfully (>=5% of that repository's code), so a 30MB vendored
    # dependency tree cannot outvote thirty hand-written projects.
    repos_by_lang: dict[str, int] = {}
    primary_by_lang: dict[str, int] = {}
    active_this_year = 0
    this_year = datetime.now(timezone.utc).year
    cursor = None

    while True:
        user = graphql(REPO_QUERY, login=LOGIN, cursor=cursor)["user"]
        followers = user["followers"]["totalCount"]
        repos = user["repositories"]

        for node in repos["nodes"]:
            stars += node["stargazerCount"]
            if node["isPrivate"]:
                private += 1
            else:
                public += 1

            if node["pushedAt"] and int(node["pushedAt"][:4]) == this_year:
                active_this_year += 1

            edges = [e for e in node["languages"]["edges"] if e["node"]["name"] not in LANG_IGNORE]
            total = sum(e["size"] for e in edges)
            if not total:
                continue
            for edge in edges:
                if edge["size"] / total >= 0.05:
                    name = edge["node"]["name"]
                    repos_by_lang[name] = repos_by_lang.get(name, 0) + 1

            top = max(edges, key=lambda e: e["size"])["node"]["name"]
            primary_by_lang[top] = primary_by_lang.get(top, 0) + 1

        if not repos["pageInfo"]["hasNextPage"]:
            break
        cursor = repos["pageInfo"]["endCursor"]

    return {
        "stars": stars,
        "private": private,
        "public": public,
        "total": private + public,
        "followers": followers,
        "active_this_year": active_this_year,
        "repos_by_lang": repos_by_lang,
        "primary_by_lang": primary_by_lang,
    }


def age_and_experience() -> tuple[int, int]:
    today = datetime.now(timezone.utc).date()
    age = today.year - BIRTH.year - ((today.month, today.day) < (BIRTH.month, BIRTH.day))
    return age, today.year - CAREER_START


def bar(fraction: float, width: int = 20) -> str:
    filled = round(fraction * width)
    return "█" * filled + "░" * (width - filled)


def badge(label: str, value: str, color: str) -> str:
    esc = lambda s: str(s).replace("-", "--").replace("_", "__").replace(" ", "_")
    return (
        f"![{label}](https://img.shields.io/badge/{esc(label)}-{esc(value)}-{color}"
        "?style=for-the-badge&labelColor=0d1117)"
    )


def render_stats(data: dict, experience: int) -> str:
    private_pct = round(data["private"] / data["total"] * 100) if data["total"] else 0
    langs = len(data["repos_by_lang"])

    rows = [
        ("🗂", f"{data['total']}", "Repositories"),
        ("🔒", f"{private_pct}%", "Private Work"),
        ("🧩", f"{langs}", "Languages Shipped"),
        ("🛠", f"{experience}", "Years Building"),
    ]
    cells = "\n".join(
        f'<td align="center" width="25%">\n<h1>{icon}</h1>\n<h3>{value}</h3>\n'
        f"<sub>{label}</sub>\n</td>"
        for icon, value, label in rows
    )

    top = sorted(data["primary_by_lang"].items(), key=lambda kv: kv[1], reverse=True)[:5]
    lang_badges = "\n".join(
        badge(name, f"{count} repos", "58a6ff") for name, count in top
    )

    return f"""<div align="center">

<table>
<tr>
{cells}
</tr>
</table>

<br/>

{lang_badges}

{badge("Pushed this year", f"{data['active_this_year']} repos", "c9d1d9")}
{badge("Stars", f"{data['stars']}", "c9d1d9")}

<sub>Regenerated daily from the GitHub GraphQL API, private repositories
included. Nothing in this block is typed by hand.</sub>

</div>"""


def render_langs(data: dict) -> str:
    counts = data["repos_by_lang"]
    if not counts:
        return '<div align="center">\n\n_No language data available._\n\n</div>'

    total_repos = data["total"] or 1
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:8]
    width = max(max(len(n) for n, _ in top), len("Language"))
    primary = data["primary_by_lang"]

    lines = [
        f" {'Language'.ljust(width)}   Repos   Primary   Reach                  Level",
        "─" * (width + 57),
    ]
    for name, count in top:
        share = count / total_repos
        lines.append(
            f" {name.ljust(width)}   {count:>5}   {primary.get(name, 0):>7}   "
            f"{bar(share)}   {EXPERTISE.get(name, '')}"
        )
    lines.append("─" * (width + 57))
    lines.append(f" across {data['total']} repositories, {data['private']} of them private")

    body = "\n".join(lines)
    return f"""<div align="center">

```
{body}
```

<sub><b>Repos</b> — repositories where the language is at least 5% of the code.
<b>Primary</b> — repositories where it is the largest language. Counted per
repository rather than per byte, because byte counts measure vendored
dependencies, not authorship.</sub>

</div>"""


def replace_block(text: str, name: str, body: str) -> str:
    pattern = re.compile(rf"(<!--{name}:START-->)(.*?)(<!--{name}:END-->)", re.DOTALL)
    if not pattern.search(text):
        sys.exit(f"marker <!--{name}:START--> not found in {README}")
    return pattern.sub(lambda m: f"{m.group(1)}\n{body}\n{m.group(3)}", text)


def main() -> None:
    if not TOKEN:
        sys.exit("GH_TOKEN is required")

    data = collect()
    age, experience = age_and_experience()

    with open(README, encoding="utf-8") as fh:
        text = fh.read()

    # Anchored so "age: " does not also match "first_language: ".
    text = re.sub(r"^age: .*$", f"age: {age}", text, flags=re.M)
    text = re.sub(
        r"^(\s*)years_of_experience: .*$",
        rf"\g<1>years_of_experience: {experience}",
        text,
        flags=re.M,
    )

    text = replace_block(text, "STATS", render_stats(data, experience))
    text = replace_block(text, "LANGS", render_langs(data))

    with open(README, "w", encoding="utf-8") as fh:
        fh.write(text)

    print(
        f"age={age} experience={experience} repos={data['total']} "
        f"private={data['private']} stars={data['stars']} "
        f"langs={len(data['repos_by_lang'])} active={data['active_this_year']}"
    )


if __name__ == "__main__":
    main()
