# WebSense Sentinel — Chrome Extension (Analyst & Demo Tool Only)

> **Note for Site Owners / Customers:** Production websites do **not** install this Chrome extension. To monitor visitors on your own site, register your domain in `/dashboard` (**Sites & Embed**) and paste the single hosted `<script src=".../sentinel.js" data-site-id="...">` tag described in [EMBED.md](../EMBED.md).
>
> Use this extension only as an **analyst, research, or live-demo tool** when you want to observe SentinelTrace behavioral telemetry on arbitrary third-party websites without editing their HTML.

This extension injects the Sentinel behavioral telemetry collector onto **any website you visit**, evaluates interactions against the WebSense 5-layer detection engine in real time, and shows the live actor classification (`HUMAN`, `AGENTIC_AI`, `TRADITIONAL_AUTOMATION`) and risk score.

---

## How to Install the Extension in Chrome / Edge / Brave

1. Open **Google Chrome** (or any Chromium browser).
2. Navigate to: `chrome://extensions`
3. Enable **Developer mode** toggle in the top-right corner.
4. Click **Load unpacked** in the top-left corner.
5. Select the folder:
   ```
   d:\RealDevSquad\akshat-projects\ai_agent traffic detection system\extension
   ```
6. The **WebSense Sentinel** extension icon will appear in your browser toolbar!

---

## How It Works

1. **Visit Any Website**: Go to any site (e.g. `wikipedia.org`, `amazon.com`, `news.ycombinator.com`, or your own web app).
2. **Interact with the Page**: Move the mouse, click links, scroll, or type in search boxes.
3. **Check the Extension Badge / Popup**:
   - The toolbar icon badge updates dynamically:
     - 🟩 **`HUM`** (Green) — Organic Human behavior
     - 🟪 **`AI`** (Purple) — Autonomous Agentic AI pattern
     - 🟥 **`BOT`** (Red) — Traditional automation / scripted scraper
   - Click the extension icon to view the full popup with live Risk Score, Kinematics event counts, and a direct link to the **WebSense Analyst Dashboard**.
4. **View Multi-Site Data on Dashboard**:
   - Open `http://localhost:8000/dashboard`
   - In the **Global Site Selector** dropdown, select the site ID for the visited website (e.g., `Extension: wikipedia_org`) to inspect the kinematic feature radar and full session traces!
