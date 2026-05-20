import os
import re
import json
import subprocess
from datetime import datetime

AUTHOR = "rudi193-cmd"
REPO = "rudi193-cmd/willow-1.9"

def run_gh_search(args):
    cmd = ["gh", "search", "prs", "--author", AUTHOR, "--limit", "100", "--json", "number,repository,title,url"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    prs = json.loads(result.stdout)
    # Filter out user's own repos
    return [pr for pr in prs if not pr["repository"]["nameWithOwner"].startswith(f"{AUTHOR}/")]

def main():
    print("Fetching PRs...")
    open_prs = run_gh_search(["--state", "open"])
    merged_prs = run_gh_search(["--merged"])
    all_closed_prs = run_gh_search(["--state", "closed"])
    
    # Identify closed but not merged
    merged_urls = {pr["url"] for pr in merged_prs}
    closed_prs = [pr for pr in all_closed_prs if pr["url"] not in merged_urls]

    # Generate Issue Body
    today = datetime.now().strftime("%Y-%m-%d")
    issue_body = f"## Upstream Contribution Status — {today}\n\n"
    
    if open_prs:
        issue_body += "### ⏳ Still Open\n\n"
        for pr in open_prs:
            issue_body += f"- [{pr['repository']['nameWithOwner']} #{pr['number']}]({pr['url']}) — {pr['title']}\n"
        issue_body += "\n"
        
    if merged_prs:
        issue_body += "### ✅ Merged\n\n"
        for pr in merged_prs:
            issue_body += f"- [{pr['repository']['nameWithOwner']} #{pr['number']}]({pr['url']}) — {pr['title']}\n"
        issue_body += "\n"
        
    if closed_prs:
        issue_body += "### ❌ Closed (Not Merged)\n\n"
        for pr in closed_prs:
            issue_body += f"- [{pr['repository']['nameWithOwner']} #{pr['number']}]({pr['url']}) — {pr['title']}\n"
        issue_body += "\n"
        
    issue_body += "---\n_When PRs merge: close this issue, update CONTRIBUTORS.md, add badge to README._\n"

    # Update Issue
    print("Updating issue...")
    issue_result = subprocess.run(
        ["gh", "issue", "list", "--repo", REPO, "--label", "upstream-tracker", "--state", "open", "--json", "number"],
        capture_output=True, text=True, check=True
    )
    issues = json.loads(issue_result.stdout)
    if issues:
        issue_num = str(issues[0]["number"])
        with open("issue_body.md", "w") as f:
            f.write(issue_body)
        subprocess.run(["gh", "issue", "edit", issue_num, "--repo", REPO, "--body-file", "issue_body.md"], check=True)
        print(f"Updated issue #{issue_num}")
    else:
        print("Could not find upstream-tracker issue")

    # Update CONTRIBUTORS.md
    print("Updating CONTRIBUTORS.md...")
    with open("CONTRIBUTORS.md", "r") as f:
        content = f.read()

    new_table = "| Project | Maintainer | What we contributed | Status |\n|---------|-----------|---------------------|--------|\n"
    
    for pr in merged_prs:
        owner = pr['repository']['owner']['login'] if 'owner' in pr['repository'] else pr['repository']['nameWithOwner'].split('/')[0]
        new_table += f"| [{pr['repository']['nameWithOwner']}](https://github.com/{pr['repository']['nameWithOwner']}) | {owner} | {pr['title']} | [PR #{pr['number']}]({pr['url']}) merged |\n"
    for pr in open_prs:
        owner = pr['repository']['owner']['login'] if 'owner' in pr['repository'] else pr['repository']['nameWithOwner'].split('/')[0]
        new_table += f"| [{pr['repository']['nameWithOwner']}](https://github.com/{pr['repository']['nameWithOwner']}) | {owner} | {pr['title']} | [PR #{pr['number']}]({pr['url']}) open |\n"
    for pr in closed_prs:
        owner = pr['repository']['owner']['login'] if 'owner' in pr['repository'] else pr['repository']['nameWithOwner'].split('/')[0]
        new_table += f"| [{pr['repository']['nameWithOwner']}](https://github.com/{pr['repository']['nameWithOwner']}) | {owner} | {pr['title']} | [PR #{pr['number']}]({pr['url']}) closed |\n"

    pattern = r"\| Project \| Maintainer \| What we contributed \| Status \|\n\|---------\|-----------\|---------------------\|--------\|\n(?:\|.*\|\n)+"
    content = re.sub(pattern, new_table, content)

    with open("CONTRIBUTORS.md", "w") as f:
        f.write(content)
    print("Updated CONTRIBUTORS.md")

if __name__ == "__main__":
    main()
