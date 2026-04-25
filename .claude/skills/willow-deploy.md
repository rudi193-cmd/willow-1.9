---
name: willow-deploy
description: Push changes to a Grove-connected node and verify.
---

1. Commit all changes: git add -p && git commit
2. Push to GitHub: git push origin master
3. Run willow.sh check-updates to queue Grove notification
4. willow_fork_log(fork_id, "grove", "deploy", "github/master", app_id="hanuman")
5. Confirm with Sean that target node received the update banner

For Felix: the update-check.timer fires every 30 min automatically.
Felix sees a banner → clicks yes → willow.sh update runs → dashboard restarts.
