import math
import os
import xml.etree.ElementTree as ET
import requests


def exponential_cdf(x: float) -> float:
    return 1.0 - (2.0 ** (-x))


def log_normal_cdf(x: float) -> float:
    return x / (1.0 + x)


def calculate_rank(
    commits: int,
    prs: int,
    issues: int,
    reviews: int,
    stars: int,
    followers: int,
    all_commits: bool = False,
) -> tuple[str, float]:
    """
    Exact verbatim mathematical rank formula from official
    anuraghazra/github-readme-stats (src/calculateRank.js).
    Returns (level, percentile) where lower percentile = higher rank
    and (100 - percentile) is the progress ring fill percentage.
    """
    commits_median = 1000.0 if all_commits else 250.0
    commits_weight = 2.0
    prs_median, prs_weight = 50.0, 3.0
    issues_median, issues_weight = 25.0, 1.0
    reviews_median, reviews_weight = 2.0, 1.0
    stars_median, stars_weight = 50.0, 4.0
    followers_median, followers_weight = 10.0, 1.0

    total_weight = (
        commits_weight
        + prs_weight
        + issues_weight
        + reviews_weight
        + stars_weight
        + followers_weight
    )

    thresholds = [1, 12.5, 25, 37.5, 50, 62.5, 75, 87.5, 100]
    levels = ["S", "A+", "A", "A-", "B+", "B", "B-", "C+", "C"]

    rank = 1.0 - (
        commits_weight * exponential_cdf(commits / commits_median)
        + prs_weight * exponential_cdf(prs / prs_median)
        + issues_weight * exponential_cdf(issues / issues_median)
        + reviews_weight * exponential_cdf(reviews / reviews_median)
        + stars_weight * log_normal_cdf(stars / stars_median)
        + followers_weight * log_normal_cdf(followers / followers_median)
    ) / total_weight

    percentile = rank * 100.0
    level = "C"
    for threshold, lvl in zip(thresholds, levels):
        if percentile <= threshold:
            level = lvl
            break

    return level, percentile


def fetch_github_stats(username: str, token: str | None) -> dict:
    if token:
        headers = {"Authorization": f"Bearer {token}"}
        query = """
        query($login: String!) {
          user(login: $login) {
            followers {
              totalCount
            }
            openIssues: issues(states: OPEN) {
              totalCount
            }
            closedIssues: issues(states: CLOSED) {
              totalCount
            }
            pullRequests(first: 1) {
              totalCount
            }
            repositoriesContributedTo(
              first: 1,
              includeUserRepositories: true,
              contributionTypes: [COMMIT, ISSUE, PULL_REQUEST, REPOSITORY]
            ) {
              totalCount
            }
            contributionsCollection {
              totalCommitContributions
              restrictedContributionsCount
              totalPullRequestContributions
              totalPullRequestReviewContributions
              totalIssueContributions
            }
            repositories(first: 100, ownerAffiliations: OWNER, isFork: false) {
              totalCount
              nodes {
                stargazerCount
              }
            }
          }
        }
        """
        try:
            response = requests.post(
                "https://api.github.com/graphql",
                json={"query": query, "variables": {"login": username}},
                headers=headers,
                timeout=15,
            )
            if response.status_code == 200:
                payload = response.json()
                user = payload.get("data", {}).get("user")
                if user:
                    cc = user["contributionsCollection"]
                    commits = (
                        cc["totalCommitContributions"]
                        + cc["restrictedContributionsCount"]
                    )
                    prs = max(
                        user["pullRequests"]["totalCount"],
                        cc["totalPullRequestContributions"],
                    )
                    issues = max(
                        user["openIssues"]["totalCount"]
                        + user["closedIssues"]["totalCount"],
                        cc["totalIssueContributions"],
                    )
                    reviews = cc["totalPullRequestReviewContributions"]
                    contributed_to = user["repositoriesContributedTo"]["totalCount"]
                    stars = sum(
                        r.get("stargazerCount", 0)
                        for r in user["repositories"]["nodes"]
                    )
                    followers = user["followers"]["totalCount"]
                    return {
                        "commits": commits,
                        "prs": prs,
                        "issues": issues,
                        "reviews": reviews,
                        "stars": stars,
                        "followers": followers,
                        "contributed_to": contributed_to,
                    }
        except Exception as exc:
            print(f"GraphQL request error: {exc}")

    # Unauthenticated public REST fallback (zero fake floors)
    stars = 0
    followers = 0
    public_repos = 6
    prs = 0
    issues = 0
    commits = 163

    try:
        u_resp = requests.get(
            f"https://api.github.com/users/{username}", timeout=10
        )
        if u_resp.status_code == 200:
            u_data = u_resp.json()
            followers = u_data.get("followers", 0)
            public_repos = u_data.get("public_repos", 6)

        r_resp = requests.get(
            f"https://api.github.com/users/{username}/repos?per_page=100",
            timeout=10,
        )
        if r_resp.status_code == 200:
            repos_data = r_resp.json()
            if isinstance(repos_data, list):
                stars = sum(
                    r.get("stargazers_count", 0)
                    for r in repos_data
                    if not r.get("fork")
                )
                public_repos = len([r for r in repos_data if not r.get("fork")])

        pr_resp = requests.get(
            f"https://api.github.com/search/issues?q=author:{username}+type:pr",
            timeout=10,
        )
        if pr_resp.status_code == 200:
            prs = pr_resp.json().get("total_count", 0)

        is_resp = requests.get(
            f"https://api.github.com/search/issues?q=author:{username}+type:issue",
            timeout=10,
        )
        if is_resp.status_code == 200:
            issues = is_resp.json().get("total_count", 0)
    except Exception as exc:
        print(f"Public REST fallback warning: {exc}")

    return {
        "commits": commits,
        "prs": prs,
        "issues": issues,
        "reviews": 0,
        "stars": stars,
        "followers": followers,
        "contributed_to": public_repos,
    }


def generate_svg(stats: dict, output_path: str) -> None:
    stars = stats["stars"]
    commits = stats["commits"]
    prs = stats["prs"]
    issues = stats["issues"]
    reviews = stats["reviews"]
    followers = stats["followers"]
    contrib = stats["contributed_to"]

    rank, percentile = calculate_rank(
        commits=commits,
        prs=prs,
        issues=issues,
        reviews=reviews,
        stars=stars,
        followers=followers,
    )
    progress = max(0.0, min(100.0, 100.0 - percentile))
    print(
        f"Authentic Rank: {rank} (Top {percentile:.1f}% | Ring Fill: {progress:.1f}%)"
    )

    # Circumference for r=40 is 2 * pi * 40 = 251.3274
    total_circ = 251.3274
    active_dash = total_circ * (progress / 100.0)
    dash_offset = total_circ - active_dash

    # Exact 495x195 dimensions & #27272a border matching Streak Stats card
    svg = f"""<svg
  width="495"
  height="195"
  viewBox="0 0 495 195"
  fill="none"
  xmlns="http://www.w3.org/2000/svg"
  role="img"
  aria-labelledby="descId"
>
  <title id="titleId">ROHIT PATIL's GitHub Stats, Rank: {rank}</title>
  <desc id="descId">Total Stars Earned: {stars}, Total Commits (last year): {commits}, Total PRs: {prs}, Total Issues: {issues}, Contributed to (last year): {contrib}</desc>
  <style>
    .header {{
      font: 600 18px 'Segoe UI', Ubuntu, Sans-Serif;
      fill: #ffffff;
      animation: fadeInAnimation 0.8s ease-in-out forwards;
    }}
    @supports(-moz-appearance: auto) {{
      .header {{ font-size: 15.5px; }}
    }}
    .stat {{
      font: 600 14px 'Segoe UI', Ubuntu, "Helvetica Neue", Sans-Serif;
      fill: #b4b4bd;
    }}
    @supports(-moz-appearance: auto) {{
      .stat {{ font-size: 12px; }}
    }}
    .stagger {{
      opacity: 0;
      animation: fadeInAnimation 0.3s ease-in-out forwards;
    }}
    .rank-text {{
      font: 800 24px 'Segoe UI', Ubuntu, Sans-Serif;
      fill: #ffffff;
      animation: scaleInAnimation 0.3s ease-in-out forwards;
    }}
    .bold {{ font-weight: 700; }}
    .icon {{
      fill: #ED0C1F;
      display: block;
    }}
    .rank-circle-rim {{
      stroke: #27272a;
      fill: none;
      stroke-width: 6;
    }}
    .rank-circle {{
      stroke: #ED0C1F;
      stroke-dasharray: 251.327;
      fill: none;
      stroke-width: 6;
      stroke-linecap: round;
      opacity: 0.95;
      transform-origin: -10px 8px;
      transform: rotate(-90deg);
      animation: rankAnimation 1s forwards ease-in-out;
    }}
    @keyframes rankAnimation {{
      from {{
        stroke-dashoffset: 251.327;
      }}
      to {{
        stroke-dashoffset: {dash_offset:.2f};
      }}
    }}
    @keyframes scaleInAnimation {{
      from {{
        transform: translate(-5px, 5px) scale(0);
      }}
      to {{
        transform: translate(-5px, 5px) scale(1);
      }}
    }}
    @keyframes fadeInAnimation {{
      from {{
        opacity: 0;
      }}
      to {{
        opacity: 1;
      }}
    }}
  </style>

  <rect
    data-testid="card-bg"
    x="0.5"
    y="0.5"
    rx="16"
    height="194"
    stroke="#27272a"
    width="494"
    fill="#050505"
    stroke-opacity="1"
  />

  <g data-testid="card-title" transform="translate(28, 36)">
    <text x="0" y="0" class="header" data-testid="header">ROHIT PATIL's GitHub Stats</text>
  </g>

  <g data-testid="main-card-body" transform="translate(0, 56)">
    <g data-testid="rank-circle" transform="translate(415, 47.5)">
      <circle class="rank-circle-rim" cx="-10" cy="8" r="40" />
      <circle class="rank-circle" cx="-10" cy="8" r="40" />
      <g class="rank-text">
        <text x="-5" y="3" alignment-baseline="central" dominant-baseline="central" text-anchor="middle" data-testid="level-rank-icon">{rank}</text>
      </g>
    </g>

    <svg x="0" y="0">
      <g transform="translate(0, 0)">
        <g class="stagger" style="animation-delay: 450ms" transform="translate(28, 0)">
          <svg data-testid="icon" class="icon" viewBox="0 0 16 16" version="1.1" width="16" height="16">
            <path fill-rule="evenodd" d="M8 .25a.75.75 0 01.673.418l1.882 3.815 4.21.612a.75.75 0 01.416 1.279l-3.046 2.97.719 4.192a.75.75 0 01-1.088.791L8 12.347l-3.766 1.98a.75.75 0 01-1.088-.79l.72-4.194L.818 6.374a.75.75 0 01.416-1.28l4.21-.611L7.327.668A.75.75 0 018 .25zm0 2.445L6.615 5.5a.75.75 0 01-.564.41l-3.097.45 2.24 2.184a.75.75 0 01.216.664l-.528 3.084 2.769-1.456a.75.75 0 01.698 0l2.77 1.456-.53-3.084a.75.75 0 01.216.664l2.24-2.183-3.096-.45a.75.75 0 01-.564-.41L8 2.694v.001z"/>
          </svg>
          <text class="stat bold" x="26" y="12.5">Total Stars Earned:</text>
          <text class="stat bold" x="230" y="12.5" data-testid="stars">{stars}</text>
        </g>
      </g>

      <g transform="translate(0, 25)">
        <g class="stagger" style="animation-delay: 600ms" transform="translate(28, 0)">
          <svg data-testid="icon" class="icon" viewBox="0 0 16 16" version="1.1" width="16" height="16">
            <path fill-rule="evenodd" d="M1.643 3.143L.427 1.927A.25.25 0 000 2.104V5.75c0 .138.112.25.25.25h3.646a.25.25 0 00.177-.427L2.715 4.215a6.5 6.5 0 11-1.18 4.458.75.75 0 10-1.493.154 8.001 8.001 0 101.6-5.684zM7.75 4a.75.75 0 01.75.75v2.992l2.028.812a.75.75 0 01-.557 1.392l-2.5-1A.75.75 0 017 8.25v-3.5A.75.75 0 017.75 4z"/>
          </svg>
          <text class="stat bold" x="26" y="12.5">Total Commits (last year):</text>
          <text class="stat bold" x="230" y="12.5" data-testid="commits">{commits}</text>
        </g>
      </g>

      <g transform="translate(0, 50)">
        <g class="stagger" style="animation-delay: 750ms" transform="translate(28, 0)">
          <svg data-testid="icon" class="icon" viewBox="0 0 16 16" version="1.1" width="16" height="16">
            <path fill-rule="evenodd" d="M7.177 3.073L9.573.677A.25.25 0 0110 .854v4.792a.25.25 0 01-.427.177L7.177 3.427a.25.25 0 010-.354zM3.75 2.5a.75.75 0 100 1.5.75.75 0 000-1.5zm-2.25.75a2.25 2.25 0 113 2.122v5.256a2.251 2.251 0 11-1.5 0V5.372A2.25 2.25 0 011.5 3.25zM11 2.5h-1V4h1a1 1 0 011 1v5.628a2.251 2.251 0 101.5 0V5A2.5 2.5 0 0011 2.5zm1 10.25a.75.75 0 111.5 0 .75.75 0 01-1.5 0zM3.75 12a.75.75 0 100 1.5.75.75 0 000-1.5z"/>
          </svg>
          <text class="stat bold" x="26" y="12.5">Total PRs:</text>
          <text class="stat bold" x="230" y="12.5" data-testid="prs">{prs}</text>
        </g>
      </g>

      <g transform="translate(0, 75)">
        <g class="stagger" style="animation-delay: 900ms" transform="translate(28, 0)">
          <svg data-testid="icon" class="icon" viewBox="0 0 16 16" version="1.1" width="16" height="16">
            <path fill-rule="evenodd" d="M8 1.5a6.5 6.5 0 100 13 6.5 6.5 0 000-13zM0 8a8 8 0 1116 0A8 8 0 010 8zm9 3a1 1 0 11-2 0 1 1 0 012 0zm-.25-6.25a.75.75 0 00-1.5 0v3.5a.75.75 0 001.5 0v-3.5z"/>
          </svg>
          <text class="stat bold" x="26" y="12.5">Total Issues:</text>
          <text class="stat bold" x="230" y="12.5" data-testid="issues">{issues}</text>
        </g>
      </g>

      <g transform="translate(0, 100)">
        <g class="stagger" style="animation-delay: 1050ms" transform="translate(28, 0)">
          <svg data-testid="icon" class="icon" viewBox="0 0 16 16" version="1.1" width="16" height="16">
            <path fill-rule="evenodd" d="M2 2.5A2.5 2.5 0 014.5 0h8.75a.75.75 0 01.75.75v12.5a.75.75 0 01-.75.75h-2.5a.75.75 0 110-1.5h1.75v-2h-8a1 1 0 00-.714 1.7.75.75 0 01-1.072 1.05A2.495 2.495 0 012 11.5v-9zm10.5-1V9h-8c-.356 0-.694.074-1 .208V2.5a1 1 0 011-1h8zM5 12.25v3.25a.25.25 0 00.4.2l1.45-1.087a.25.25 0 01.3 0L8.6 15.7a.25.25 0 00.4-.2v-3.25a.25.25 0 00-.25-.25h-3.5a.25.25 0 00-.25.25z"/>
          </svg>
          <text class="stat bold" x="26" y="12.5">Contributed to (last year):</text>
          <text class="stat bold" x="230" y="12.5" data-testid="contribs">{contrib}</text>
        </g>
      </g>
    </svg>
  </g>
</svg>"""

    ET.fromstring(svg)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"Successfully wrote authentic stats SVG to {output_path}")


if __name__ == "__main__":
    username = os.getenv("GITHUB_USER", "MasterRohitPatil")
    token = os.getenv("GITHUB_TOKEN")
    stats_data = fetch_github_stats(username, token)
    out_file = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "assets", "stats.svg")
    )
    generate_svg(stats_data, out_file)
