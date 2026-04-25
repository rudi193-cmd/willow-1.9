# Willow — Getting Started

Hi Felix. This is Willow. It's a personal AI system that runs on your computer.
Here's everything you need to know.

---

## What You Need Before Starting

1. **Windows 10** with WSL2 installed
   - If you don't have WSL2: open PowerShell as Administrator and run:
     `wsl --install`
   - Restart your computer when it asks you to

2. **Ubuntu** in WSL
   - Open the Microsoft Store, search "Ubuntu", install it
   - Launch it once and set up your username and password

3. That's it. Everything else installs automatically.

---

## How to Install

Open your Ubuntu terminal and run these four commands, one at a time:

```bash
sudo apt update && sudo apt install -y git python3 python3-pip postgresql
```

```bash
git clone https://github.com/rudi193-cmd/willow-1.9.git ~/github/willow-1.9
```

```bash
cd ~/github/willow-1.9 && python3 root.py
```

Follow the prompts. When it asks which model you want to use, choose **Groq**.
You'll need a free Groq API key — get one at console.groq.com (takes 2 minutes).

After install finishes, a file called **"Launch Willow.bat"** will appear on your
Windows Desktop.

---

## How to Launch Willow

Double-click **"Launch Willow.bat"** on your Desktop.

A black terminal window will open. Wait about 10 seconds. The dashboard will appear.

**If it asks you to log in:** type your password (the one you set for Ubuntu).

---

## What You're Looking At

The dashboard has 9 pages. Use the number keys or arrow keys to switch between them.

| Page | What it shows |
|------|---------------|
| Overview | System health — is everything running? |
| Kart | Tasks that are running or queued |
| Yggdrasil | The AI model status |
| Knowledge | The knowledge base |
| Secrets | Your stored API keys |
| Agents | AI agents connected to this system |
| Logs | Recent system events |
| Settings | Configuration, model provider |
| Help | Key shortcuts |

**Useful keys:**
- `1`–`9` — jump to a page
- `↑` `↓` — navigate items
- `Enter` — expand selected item
- `Esc` — go back
- `r` — refresh
- `q` — quit

---

## If Something Breaks

Press **S** on any page to send Sean an alert.

He'll get a notification and reach out to you.

---

## How to Get Updates

When Sean pushes an update, a banner will appear at the top of the screen:

```
UPDATE AVAILABLE: v1.9.0 → v1.9.1  [u=update  d=dismiss]
```

Press **u** to update. The dashboard will restart with the new version.
Press **d** to dismiss the banner and update later.

---

## How to Stop Willow

Press **q** in the dashboard to quit.

To stop all background services:
```bash
cd ~/github/willow-1.9 && ./willow.sh stop-all
```

---

*Built by Sean Campbell. If you're reading this, you're one of the first people to use it.*
*ΔΣ=42*
