# Changelog

Every desktop and phone release. The same list is at [agentflowharness.com/changelog](https://agentflowharness.com/changelog).

## 1.32.3 (2026-11-12)

**Much lower power use**

AFH no longer keeps the processor busy when it is doing nothing, so a laptop runs cooler and its battery lasts longer.

- **Fixed:** the chat's smooth scroll to the newest message could keep running on every frame for ever, using a whole processor core while AFH sat idle. It now always ends.
- **The logo rests:** the AFH logo flows while a model is working and stands still when nothing is, instead of moving all the time.
- **Nothing moves unseen:** the to-do dot pulses only while the model is on that step, and every animation stops while the window is minimised or covered.
- **Lighter streaming:** while a reply is being written the chat redraws about 30 times a second instead of once per screen frame, which matters most on 120 and 144 Hz screens.

## 1.32.2 (2026-11-11)

**Provider logos in Settings, fewer boxes**

Settings now shows each provider's real logo, the steps in a reply lose their boxes, and a logo bug is fixed.

- **Provider logos in Settings:** every provider shows its real logo on **Models & accounts**, on its own page, on the default model, and in **Connect a provider** (sign in, API key, this computer and search). The usage popup, the command palette and the price table show them too.
- **Fewer boxes:** in a reply's steps, the **Worked for** line, the added and removed line counts, a command, **checked** and **Thought for** are plain text and icons, with no box around each one.
- **Fixed:** a provider's logo could turn into a coloured square after switching between light and dark. This affected logos drawn with gradients or masks, such as Antigravity, Gemini and Poe.

## 1.32.1 (2026-11-11)

**Cleaner icons**

The icons in the Studio chat now stand on their own, without a box around each one.

- **Model logos:** the logo beside each reply, in the model picker and on the model button has no tile behind it. While a reply is being written, the logo itself pulses.
- **Step icons:** file, command and to-do icons in a reply's steps, and in the bar that sums up the work, are plain icons side by side.
- **Unchanged:** a provider with no logo keeps its coloured two-letter tile. Focus, Compact and Canvas keep their own look.

## 1.32.0 (2026-11-10)

**A new chat: replies you can read at a glance**

The main chat screen is redesigned in the Studio interface: how replies, steps, commands and to-dos look, the chat box, and a simpler model picker that shows each provider's logo and asks for the effort.

- **Each reply under its model:** a reply starts with the provider's logo, the model's name and the effort it used, so you always know who answered.
- **Work folds away:** everything the model did on the way (its notes, its thinking and its steps) sits under one bar that sums it up, such as **Worked for 32s · Edited 3 files · Ran 1 command**. It stays open while the model works and folds when it is done, leaving the answer in front. Click the bar to open it again.
- **Commands as a terminal:** open a command to see it in a small terminal: the command, its output, how long it took and how it ended (**exit 0**, failed or timed out), with a button to copy it.
- **Files changed:** the end of a reply lists every file it changed with its icon and +/− lines. **Review** opens the Changes panel.
- **File and language icons:** Python, TypeScript, CSS, Rust, Go, Dockerfile, package.json and many more show their own logo in steps, code blocks, the Live view, Changes and attachments.
- **To-dos:** the to-do list in a reply and the one above the chat box have a progress ring and round checks; the one in progress is highlighted. The list above the chat box slides out from behind it.
- **A simpler model picker:** one search box and one list, grouped under each provider's real logo. Pick a model that has effort levels and a second step asks for the effort (Auto, Low, Medium, High and more), each with a short note on what it means. The chat box shows the model's logo and the effort you chose.
- **The picker follows Settings:** remove a provider, turn one off or hide a model in Settings and the picker updates at once, even while it is open, without restarting the app.
- **New thread:** the greeting, the chat box and a few ideas sit together in the middle of the screen.
- **Sidebar and top bar:** each thread shows a second line with its model, **Working…** or **Needs your answer**, and its to-do progress. The top bar's buttons are now quiet icons that show their names when you point at them.
- **Everywhere:** Focus, Compact and Canvas keep their own look and get the icons and the new picker. Light and dark, Arabic and phone width are covered.

## 1.31.0 (2026-11-10)

**New settings: easier to find, easier to understand**

Every settings page is redesigned, with the biggest changes where you spend the most time: your models, your providers and the accounts behind them.

- **Search every setting:** type in the box at the top of Settings (or press Ctrl+F) to find any option on any page, in English or Arabic. Pick a result and AFH opens the page, scrolls to it and highlights it.
- **Clearer groups:** the pages are sorted into Basics, Models, How the agent works, Connect and Help. Long pages such as Agent get a bar of their sections that stays at the top and shows where you are.
- **Models & accounts:** the old Models & providers page is now one overview: your default model, and a tile for each provider that shows whether it works, how it is connected, how much of its limit is used, and how many models and accounts it has. Open a tile to see its Accounts, Models and Connection tabs.
- **Accounts you can read at a glance:** each account shows its usage bars and whether it is in use, ready or resting until a set time. Use one by hand, or rename, reorder, turn off or remove it from its menu. **Sign in another** and **Add key** add more.
- **Connecting a provider:** pick one of four ways (sign in with a plan you pay for, an API key, models on this computer, or any compatible server), with one search across all of them.
- **A new model picker:** providers on the side, your recent models at the top, tags for images, thinking and models without tools, the context size, and effort at the bottom. Arrow keys and Enter work.
- **Smoother:** pages slide in, choices slide instead of jumping, and every control has a cleaner look in Studio, Focus, Compact and Canvas, light and dark, and at phone width.
- **Everywhere:** the terminal app's settings follow the same order and names, and the guide now says **Settings → Models & accounts**.

## 1.30.0 (2026-11-10)

**Several accounts per provider, switched for you, and your own Chrome**

A major release. Connect more than one account or API key to the same provider, and AFH moves a running task to the next account before the one in use runs out, without stopping it. This release also brings the agent into your own Chrome, Edge or Brave.

- **Several accounts for one provider:** add as many sign-ins or API keys as you have to Gemini (Antigravity), ChatGPT, Grok, Kimi, Z.ai GLM, Anthropic and the rest. Open a provider in **Settings → Models & providers** and use **Add account** (sign in with another account) or **Add key**. Your current key or sign-in becomes the first account, so nothing changes until you add a second.
- **Switched before the limit:** when the account in use reaches 90% of its 5-hour, weekly or other plan limit, the next step of the task runs on the next account. Each step is a separate request, so the task never stops. If a provider refuses a request for its limit anyway, AFH sends the same step to the next account at once.
- **A note in the chat:** each switch leaves a line like <i>“Account switched: Antigravity, from you1@… to you2@…. you1 is at 92% of its 5-hour limit (resets 14:32).”</i> The model never sees it.
- **Busy is not used up:** when a provider's servers are overloaded, every account would get the same answer, so AFH keeps the account and retries as before. Only a used-up quota, plan, credit or rate limit moves to another account.
- **Your rules:** switch at 70 to 95% or only when refused; use the accounts one after another or least used first; and when every account is used up, wait for the first one to come back and continue by itself, or stop. Each account shows its usage, and you can rename, reorder, switch off or pick one by hand.
- **Your own Chrome:** the agent can work in the Chrome, Edge or Brave you use every day, with your sign-ins and open tabs. Your browser asks you to click Allow, and AFH asks about each new site. Turn it on in **Settings → Agent → Your Chrome**.
- **Everywhere:** the Windows and Mac apps, the terminal app (provider → Accounts) and the new `afh accounts` command, in English and Arabic.

**Fixes**

- **Terminal command:** `afh run` printed some notices as raw data; it now prints their text.

## 1.26.0 (2026-11-10)

**Your own Chrome: the agent can use your real browser**

AFH can now work in the browser you use every day (Chrome, Edge or Brave), with your sign-ins and your open tabs. Its built-in browser is a separate, clean one for checking its work, and it stays. The new `chrome` tool is for things only your own browser can do.

- **Your sign-ins and your tabs:** ask for something behind a login, such as “check my GitHub notifications” or “summarise the tab I have open”. The agent opens a tab in your browser or works in one of yours. It can list your tabs, switch to one, click, type, scroll, read the page, and look at the console and network.
- **No extension and no separate profile:** AFH connects through the browser's own remote-debugging switch, in Chrome and Edge 144 or newer. Turn it on once at `chrome://inspect/#remote-debugging`. **Settings → Agent → Your Chrome** opens that page for you and shows when your browser is ready.
- **You stay in charge:** your browser asks you to click Allow each time AFH connects, and shows a bar while it is connected. AFH then asks about each new site: Allow, Always allow or Don't allow. Always-allowed sites are listed in Settings, and sites on your blocked list are never used, in any thread.
- **A site you refuse is left again:** if a click lands on a site you say no to, a tab that click opened is closed, and a page that moved goes back.
- **Careful by design:** the agent is told to stop and ask before anything that buys, sends, posts or deletes, never to type passwords or card numbers, and to treat what a web page says as information, not instructions. Closing AFH never closes your browser, and AFH only closes tabs it opened.
- **Everywhere:** the Windows and Mac apps, the terminal app and the `afh` command all have it, in English and Arabic. Large and high-resolution windows are handled, so clicks land where the screenshot shows.

**Fixes**

- **Settings → Agent:** the Always-allowed apps list under Computer control now lines up with the rest of its card.

## 1.25.0 (2026-11-09)

**Three new interfaces: Focus, Compact and Canvas**

**Settings → Appearance → Interface** now has four choices: Studio and three new ones. The new ones are as plain as Studio, but each is laid out differently and has its own parts and motion.

- **Focus:** just the conversation. A calm centered column, your messages as soft pills, and steps as single quiet lines. A step opens as an outline under a thin rail, sliding in out of a blur. Buttons are pills, and the message box is one large rounded field.
- **Compact:** built for long working sessions. Turns read like a thread, with an avatar and a name line. A run of steps stacks into one list, and a step opens in place like a panel in an inspector, with a strip for each part. The message box is docked along the bottom, and everything moves fast and straight.
- **Canvas:** the thread sits on its own sheet inside a tinted frame. Your request reads as a headline, and steps flow as small chips that lift when you point at them. A step opens as a raised card that springs out of its chip, with each part on its own tile.
- **Twelve new themes,** four for each. Focus has Graphite, Umber, Chalk and Sage, and starts dark. Compact has Indigo, Carbon, Tide and Daylight, and starts dark. Canvas has Porcelain, Sandstone, Nightfall and Pine, and starts light.
- Each interface remembers its own look, works with the classic themes and custom colors, and works at phone width and right to left. The terminal app has the new themes too.

**Removed**

- **The Harness and Paper interfaces are gone,** with their eight themes. If you were using one of them, AFH opens in Studio, in the look you last had there.

## 1.24.0 (2026-11-09)

**Two new interfaces: The Harness and Paper**

- **Pick how the whole app looks.** **Settings → Appearance → Interface** now has three choices, and the change applies right away.
  - **Studio:** the layout you know.
  - **The Harness:** the thread runs along one live strand. Every message and step is a node on it, the step being worked on glows, helpers branch off in violet, and the strand lands in a port in the message box. The thread list shows each thread's state as a small strand.
  - **Paper:** each thread reads like a document on a sheet. It has a title you can click to rename, a line of facts (agent, mode, model, when it started, changed files), your message as a quote and the plan as a checklist. The agent's steps are quiet rows with the time each one ran.
- **Each interface has its own themes.** The Harness comes with Harness, Steel, Voltage and Harness Day, and starts dark. Paper comes with Cream, Newsprint, Linen and Night Ink, and starts light. Studio keeps Sunset. The classic themes and custom colors work with all three.
- **Each interface remembers its own look.** Change the theme in one interface, and the others keep theirs. Switching back brings yours back.
- **Works everywhere:** phone width, right-to-left languages, and light and dark. The terminal app has the new themes too, and keeps its own Harness design.

**Fixes**

- **A wrong computer clock now says so.** When a computer's date, time or time zone is wrong, every secure connection fails. Sign-ins and chats used to show a raw `CERTIFICATE_VERIFY_FAILED … certificate is not yet valid` error. AFH now explains that the clock is wrong, shows what the clock says, and tells you where to turn on automatic time. In Arabic too.
- **Antivirus HTTPS scanning is named.** When something on the computer or network intercepts secure connections, AFH says so and suggests turning the scanning off or trying another network.
- **No more stray "null" in the sign-in dialog** and a few other places.

## 1.23.1 (2026-11-07)

**Grok on your subscription**

- **Grok now runs on your plan.** In 1.23.0 the Grok sign-in connected, but xAI charged your xAI API team instead of your subscription, so chats stopped at a rate limit of 0. AFH now sends Grok through xAI's Grok CLI endpoint, the one your SuperGrok or X Premium+ plan pays for. Tool calls work there too.
- **Know the risk:** xAI lets the plan pay only for its own Grok CLI, so AFH tells xAI it is the Grok CLI. xAI could stop this from working, or act on your account. AFH says so before you sign in. An xAI API key has no such risk.
- **Only what your plan covers.** The model list for a Grok sign-in comes from that endpoint, so it shows the models your plan can use.

## 1.23.0 (2026-11-07)

**Sign in with Grok, and more plans**

- **Sign in with Grok.** Use your SuperGrok or X Premium+ subscription with no API key. AFH shows a code, and you approve it on x.ai from any device. Search for Grok in **Models & providers**, or type `/connect` in the terminal app. An xAI API key still works too.
- **MiniMax Token Plan sign-in,** on minimax.io and on the China site, minimax.cn.
- **Poe and DigitalOcean sign-in.** Each one creates a key on your account for you. When a key runs out, AFH asks you to sign in again.
- **ChatGPT with a code.** For the terminal app over SSH, or a computer without a browser: sign in to your ChatGPT plan by typing a code on any device. In the app it's **Use a code instead** in the ChatGPT sign-in.
- **Good to know:** some of these sign-in pages show another coding tool's name, such as OpenCode or OpenClaw. Those providers let coding agents share one public sign-in.

## 1.22.1 (2026-11-06)

**A smooth logo in your terminal**

- **The real logo, as a real image.** In Windows Terminal and other terminals that can show images, the mark is now a smooth image instead of characters: while it starts, on the start screen and at the message box, with the same animation as the app.
- **In the installer too.** The one-command install plays the same smooth mark. Terminals that can't show images keep the block version.
- **Fixed:** pressing Enter while the terminal app was still starting could crash it. What you typed now waits in the box.

## 1.22.0 (2026-11-05)

**AFH's own terminal design**

- **A design of its own.** The terminal app is redrawn from nothing around one idea: the harness. Filled surfaces instead of boxes, lines of light, and everything connected.
- **The real mark, moving.** The same mark and the same animation as the desktop app, drawn in your terminal: on the start screen, while it starts, and at the message box, where it flows while a model works.
- **Sharp at every size.** The mark is cut from exact block shapes with hard edges, in the terminal app and the installer, so it never blurs.
- **A slim message box.** Four rows, line of light included, and it grows as you type. The strand lands right on the mark.
- **The strand.** The conversation runs down a strand, with every message, edit and command a point on it, and it joins the message box. During a run, light travels along it.
- **Threads beside you.** On a wide terminal your threads sit in a rail on the left, like the app, with tabs along the top and chips you can click. `F3` shows or hides the rail.
- **Sheets that rise.** Approvals, questions and pickers come up from the bottom, and diffs have line numbers and code colours.
- **It opens at once.** The animated mark shows while the engine starts, instead of a blank terminal.
- **The installer shows the mark too.** The one-command install plays the animated mark on its own card, on any terminal, with a line of light for progress.
- **Motion settings in the terminal.** Settings has **Logo flows while a model works** and **Animation speed**, shared with the app.
- **Fixed:** a reply that started very fast could crash the terminal app.
- **Fixed:** quitting while a reply was still drawing could print a crash.
- **Fixed:** on a busy machine, opening a thread could fail with a false "Not found" or "API misuse" error, in the app and the terminal.

## 1.21.0 (2026-11-05)

**AFH in your terminal**

- **All of AFH, full screen in your terminal.** Type `afh` for threads, models, approvals, goals, helpers, the live file panel and all of Settings, with `/` commands, `@` files, `!` shell, a command palette and the same 46 themes. It shares your threads, settings and keys with the desktop app.
- **One command to install.** Windows, Mac and Linux, with no desktop app needed. `afh update` gets the newest version and `afh uninstall` removes it, keeping your data. See the [Terminal page](https://agentflowharness.com/cli).
- **Run shell commands in a thread.** `!command` runs it in the project and shows the agent the output.
- **A new website front door.** The download button follows your system, Mac has real download buttons, and the install command is one Copy away.
- **Update log.** The desktop app keeps a log of its updates, and bug reports include it.

## 1.20.0 (2026-11-05)

**Mac, the command line, GitHub and model races**

- **AFH for Mac,** for Apple Silicon and Intel. Apple hasn't signed it yet, so you approve it once in System Settings, and new versions are a download rather than an automatic update. Computer use stays on Windows.
- **The afh command.** Chat with the agent in any terminal, or run one task from a script or CI with `afh run`. Turn it on in Settings → Developer.
- **GitHub agent.** Write `/afh` and a task on an issue or pull request. AFH does the work on your computer and opens a draft pull request. Only people you allow can start it, and merging stays with you.
- **Model races.** `afh race` gives one task to several models, each in its own worktree. Your tests score them, and you merge the one you pick.

## 1.19.5 (2026-11-04)

**Worktree merges on a fresh PC**

- **Merging a worktree works on a PC where git has no name or email set.** It used to stop with an error. Your own git name is still used when you have one.

## 1.19.4 (2026-11-04)

**Sign-ins are back, and a cleaner first run**

- **Google Antigravity sign-in is back,** with its Gemini and Claude models and its quota in the usage meter.
- **ChatGPT (chat) can use your browser login again.** Pasting a session still works as well.
- **Primary buttons are readable everywhere.** Some labels were hidden behind the button's colour.
- Settings uses the room a large window has, sign-in tiles are easier to read, and nothing runs off the side on a phone.
- **The sidebar hides completely.** Collapse it and it's gone, with one button at the top left to bring it back.

## 1.19.3 (2026-11-04)

**No more reading browser cookies**

- **ChatGPT (chat) now connects with a session you paste in.** AFH no longer opens your browser's cookie store. If you're already connected, nothing changes.
- The app now checks for updates at agentflowharness.com only.

## 1.19.2 (2026-11-04)

**Google Antigravity sign-in removed**

- **Sign in with Google Antigravity is gone.** If you were signed in, updating removes that sign-in and its saved tokens from your computer, and its models leave the list.
- Gemini models still work with a Google API key in **Settings → Models**.

## 1.19.1 (2026-11-03)

**The Studio redesign, and DevTools in the built-in browser**

- **A new look for the app — Studio.** The thread list folds into a slim icon rail (hover to peek, Ctrl+B to pin), the conversation gets a wider, calmer reading column, and the message box floats as a glass card above it.
- **One Workbench on the right** instead of separate drawers: Live, Changes, Browser, Context, Prompt and Agents as tabs. Drag its edge to resize; it remembers its width and the tab you were on (Ctrl+Shift+W).
- Tool cards are cleaner — a verb, the file as a chip, `+N −N` for edits, and browser screenshots as a thumbnail strip. All 46 themes, Arabic/RTL and compact density carry over.
- The built-in browser now has **DevTools** the agent can use: it runs JavaScript in the page's console, reads console errors and warnings, inspects every network request (method, status, timing and the response body) and reads the source files the page loaded — so when a page misbehaves it sees the failing request or the exception instead of guessing from a screenshot.
- A new website to match: agentflowharness.com was rebuilt in a light design with the mark in glossy 3D.

## 1.18.0 (2026-11-03)

**Chat with ChatGPT**

- A second ChatGPT sign-in, beside the Codex one: connect your ChatGPT browser session and use the real GPT-6 family — GPT-6 Astra, GPT-6.1 Sol, GPT-5.6 Terra and the rest — as normal chat models, drawn from your ChatGPT plan rather than your Codex credits.
- These chat models drive the full harness: they can read, edit and run code and use every tool, even though the backend has no native tool calling — AFH teaches them a protocol and runs their actions.
- Every reply carries a badge confirming the real model answered (they all self-report as “GPT-6”), so you can see exactly which model served it.
- Sign in by importing the session from your browser, or by pasting a session token.

## 1.17.0 (2026-11-03)

**Red Team mode**

- A new mode next to Build, Plan and Delegate. Red Team audits your own project for the security weaknesses an attacker could actually use: OTP and login flaws, privilege escalation and admin bypass, injection, exposed secrets, and weak sessions or tokens. It skips low-value noise.
- It finds and reports — it never changes your code. It reads the project, safely probes the app you run locally for review, and gives each finding a severity, where it is, how it’s exploited, the impact, and a concrete fix. One click switches to Build to apply the fixes.
- It stays in scope (only your own project and local or dev instances, never third-party or live sites) and is non-destructive.

## 1.16.0 (2026-11-03)

**Design first**

- Before building a new app, website or set of screens, the agent shows you 2 to 4 design options (A, B, C…) as live example screens. It works for any platform: web, Android, iOS, Windows, macOS and more.
- Each screen shows in the right frame: phone, tablet, desktop, laptop, app window, watch or TV, with iPhone and Android versions.
- Compare the same screen across every option, open any screen full size and click through it, or open it in the built-in browser.
- Choose an option, add notes or a mix ("A's colours with B's layout"), ask for new options, or skip.
- The chosen design becomes the project's design system (.afh/design.md), and every later chat in that project follows it.

## 1.15.0 (2026-11-02)

**A built-in browser**

- A browser with tabs opens in a side panel, so you can watch the agent work in it, or use it yourself like a normal browser.
- The agent can click elements or exact spots, double-click, hover, drag, type, use keyboard shortcuts, scroll, and go back and forward.
- Click into the agent's tab to take over; the agent waits until you hand it back or send a new message.
- Sign-ins in the built-in browser are kept between runs. You can still choose an external Chrome or Edge in Settings.

## 1.14.0 (2026-11-02)

**A new look**

- The whole app has been redesigned: the sidebar, messages, tool cards, message box, menus, Settings and dialogs are cleaner and more consistent, in dark and light themes and in Arabic.
- AFH now ships its own fonts (Inter and JetBrains Mono), so text looks the same on every PC.
- The home screen shows your project and four quick-start cards.
- The buttons under the message box no longer overflow when the window is narrow.
- Fixed leftover markers and the "jump to bottom" arrow showing on the home screen.

## 1.13.1 (2026-11-02)

**Antigravity fixes**

- Antigravity models no longer fail with **HTTP 400 "Unknown name exclusiveMinimum"** when tools from MCP servers are on. AFH now sends Google only the parts of a tool's description it understands, for Gemini as well.
- Models Google lists once per effort, like Gemini 3.8 Flash (Low), (Medium) and (High), are now one model with the usual **effort picker**.
- Context sizes and effort levels for Antigravity models now come from your account's own model list.

## 1.13.0 (2026-11-02)

**Usage meter and Google Antigravity**

- **Usage meter**: a small meter in the message box shows how much of your plan you've used, live. ChatGPT shows its 5-hour and weekly limits, Copilot its premium requests, Antigravity the quota left per model family, Kimi and Z.AI coding plans their windows, and OpenRouter, DeepSeek and Moonshot your balance. It turns yellow at 70% and red at 90%.
- Click it for every window with its reset time, what AFH sent in the last 5 hours and 7 days, and your other providers. Any other API key shows the rate limits from its last answer.
- **Sign in with Google Antigravity** (Settings → Models) to use its Gemini and Claude models on your Google account's quota. Google has suspended Antigravity access for accounts used outside its own apps, so AFH warns you first: use an account you can afford to lose Antigravity on.

## 1.12.1 (2026-11-02)

**Goals only when you ask**

- The agent no longer sets a **goal** for every task. It plans with the to-do list and sets a goal only when you ask for one, or tell it to keep going until something is done.
- **Autopilot** stops looping: if the agent is sent back to work and makes no progress, it pauses and waits for you. It continues at most 3 times per message, and marks a goal that turns out impossible as blocked instead of retrying.
- Want the old behaviour? Turn on Settings → Agent → Goals for every multi-step task.

## 1.12.0 (2026-11-02)

**AFH can use your computer**

- **Computer use**: for work with no file, command or web route — a desktop app, a settings screen, a tool with no API — the agent looks at your screen and uses the mouse and keyboard itself. You see its own cursor glide to each spot, with every click, keystroke and scroll shown as it happens.
- A thin frame around the screen and a bar at the top show while AFH is working. AFH steps aside while it works and comes back when it's done. Press **Esc** or **Stop** any time to take back control.
- AFH asks before it uses an app, once for everything a task needs, and you can always allow apps you trust. In **Full access** mode it doesn't ask. Password managers, Windows security screens and AFH itself are always off limits.
- **Show me how**: ask how to do something and AFH teaches you step by step, pointing at each control with a tip and waiting for you to click Next.
- Turn it on or off, and choose whether AFH steps aside or shows its cursor, in Settings → Agent → Computer control. Computer use is Windows only.
- The phone app is unchanged at 1.11.0.

## 1.10.2 (2026-11-02)

**Watch commands run, and stop right away**

- **Live command output**: while the agent runs a command or a script, its card shows the output as it arrives, no click needed. Progress bars show their latest state, and waiting on a background job shows its output too.
- The **Live** pane follows commands as well as file edits: the command on top, its output scrolling underneath like a terminal.
- **Stop** ends a run immediately, even mid-command or mid-reply: the command and everything it started is closed in the background, and the step is marked as stopped.
- The phone app is unchanged at 1.11.0.

## 1.11.0 (2026-11-01)

**An assistant that can use your phone, every provider, and AFH on the web**

- The phone AI now has **tools**: it searches the web and reads pages, checks the weather and where you are, sets reminders, adds calendar events, finds contacts, drafts calls, texts and emails for you to send, opens maps and links, uses the clipboard, does math, and remembers things you tell it. Signed in, it can also hand a task to AFH on your computer. Each step shows in the reply, and Settings → Tools turns it off.
- Show it **photos** or a text file with **+**, or **dictate** with the mic.
- **All 228 providers** from the desktop app are on the phone, with a search. **Sign in** with your ChatGPT plan, GitHub Copilot or OpenRouter instead of pasting a key.
- **AFH Chat on the web**: sign in or create an account from any page, then [chat with any model](https://agentflowharness.com/chat) right in your browser — the same providers, sign-ins and tools as the phone app, with chats kept in your browser. [Computers](https://agentflowharness.com/computers) follows AFH on your PCs live, answers approvals and starts new tasks.
- [Get the phone app](https://agentflowharness.com/download#phone) — it updates the earlier one in place. The desktop app is unchanged at 1.10.0.

## 1.10.1 (2026-11-01)

**The phone app, redesigned**

- The **AFH app for Android and iPhone** has a calmer, cleaner look: it opens straight into a chat, and your chats, computers and settings live in a side menu instead of a bottom bar. [Get it](https://agentflowharness.com/download#phone) — it updates 1.10.0 in place.
- **Themes**: Settings → Appearance follows your phone's light or dark mode, or pick Dark or Light yourself, with the same theme presets as the desktop app.
- **Run on PC** right from the message box: pick an online computer and project, and the message starts a new thread there.
- Threads waiting on you are marked correctly, and the screen fits around the keyboard and the home indicator on every phone.
- The desktop app is unchanged at 1.10.0.

## 1.10.0 (2026-11-01)

**A brand-new phone app: chat with any model, and run your PC from anywhere**

- The **AFH app for Android and iPhone** is rebuilt from scratch as a full app with its own look and lots of motion. [Get it](https://agentflowharness.com/download#phone) — it updates the earlier app in place.
- **Chats**: talk to OpenAI, Anthropic, Gemini, OpenRouter, Groq, DeepSeek, xAI, Mistral or your own OpenAI-compatible server straight from the phone, with your own keys kept in the phone's secure storage. Replies stream in with markdown and code blocks, thinking folds away, switch model mid-chat, retry, copy, pin, rename and search chats. Works with your computer off and without an account.
- **Computers**: sign in with your AFH account to see which computers are online, follow their threads live step by step, approve and answer with a tap, send the next message while AFH works, start new threads or stop a run.
- On the desktop, your **AFH account** has its own button at the bottom of the sidebar, showing who's signed in and whether your phone can reach this PC. **Settings** moved next to the language and theme buttons.

## 1.9.1 (2026-10-31)

**A real phone app, and sign-in on the website**

- The **AFH app for Android and iPhone** is rebuilt as an app of its own, made for the phone: your computers with who's online, recent threads across projects, live replies with what the agent is doing step by step, one-tap approvals and answers to questions, and a message box to send the next task or stop a run. Start new threads in any project with **+**. [Get it](https://agentflowharness.com/download#phone).
- Your **AFH account** now lives on the website: [agentflowharness.com/account](https://agentflowharness.com/account) to create it, sign in, rename or remove computers, change the password or delete the account.
- AFH no longer asks for your password: **Settings → Remote control → Sign in with your browser** opens the website, you approve the computer there, and AFH connects by itself.
- The phone pages at `/m` are gone; the app replaces them.

## 1.9.0 (2026-10-31)

**AFH on your phone**

- New **AFH app for Android and iPhone**: see your computers, tap one and you're in the full AFH on it — threads streaming live, approvals, the message box — from anywhere. [Get it](https://agentflowharness.com/download#phone).
- New optional **AFH account**, only for remote access. Sign in under **Settings → Remote control → AFH account** and the computer shows up in the app; nothing to open on your router.
- The server only passes traffic along over HTTPS. It keeps your email, a hash of your password and your list of computers — never threads, files or keys.
- Remote access settings can only be changed on the computer itself. Removing a computer in the app signs it out at once.

## 1.8.7 (2026-10-31)

**Memory for credentials too**

- The project memory is now the place for access tokens, API keys and logins you want the agent to have: it saves them when you give them to it and uses them when a task needs them, without asking again.
- AFH keeps the memory file out of git by itself, with a local ignore that leaves your `.gitignore` alone, so a token in it can't end up in a commit.
- If an older commit already has the file, the Memory window warns you and shows the command that stops git tracking it.

## 1.8.6 (2026-10-31)

**Memory, one click away**

- A **Memory** button now sits beside Goal — in the thread bar, and in the message box before a thread starts — with a count of what the agent knows about the project.
- It opens a list you can work with: add facts (several at once, one per line), click one to edit it, forget it, or switch to **Edit as text** for the whole file.
- Changes the agent makes show up live, marked **new**; your own reach it on its very next step, even mid-run.
- Type `/remember` and a fact to save it straight from the message box; `/memory` opens the list.
- The agent knows better when to save: when you say “remember”, “always” or “never”, when you correct it, when it works out how to build or test the project, and before it wraps up a long task. It can read the memory back mid-thread too.
- Notes you write in the memory file outside the list now reach the agent as well.

## 1.8.5 (2026-10-31)

**A new address**

- AFH's home is now `agentflowharness.com`; the app checks it for updates by itself.
- If that address can't be reached, the app checks a second address that serves the same updates, so no copy is left on an old version.

## 1.8.4 (2026-10-31)

**Project memory**

- The agent remembers what it learns about each project — how to run it and test it, conventions, how you like things done — and every new thread there starts knowing it.
- Read and correct it any time; one fact per line, saved in `.afh/memory.md` in the project.
- The agent keeps it tidy with a `memory` tool (add, correct, forget), and you watch its changes land live.

## 1.8.3 (2026-10-30)

**A home on the web**

- This website, with the installer and the update feed.
- AFH now checks `agentflowharness.com` for updates by itself — no address to set.

## 1.8.2 (2026-10-30)

**Real model lists everywhere**

- When a provider publishes its own model list, that list wins — guessed models it doesn't offer are gone.
- GitHub Copilot shows the models your account can really pick.
- A removed provider or hidden model never stays selected: threads move to a model that exists and tell you so.

## 1.8.1 (2026-10-30)

- ChatGPT sign-in lists exactly the models your plan has, with their reasoning levels.

## 1.8.0 (2026-10-30)

**Every provider, and sign-in**

- **228 providers** from models.dev, with context sizes, prices and reasoning levels.
- **Sign in** with ChatGPT (Plus, Pro, Team), GitHub Copilot or OpenRouter — no API key needed.
- Window controls drawn by the app, more themes, theme-switch effects and message animations.
- SDK additions.

## 1.7.5 (2026-10-29)

- The agent can pause and ask you multiple-choice questions.

## 1.7.1 – 1.7.4 (2026-10-29)

- The agent installs skills, MCP servers, slash commands, hooks and agents by itself (1.7.3).
- Dropped connections are retried; the to-do spinner stops when the thread isn't running.

## 1.7.0 (2026-10-29)

**Eyes, ears and an API**

- **Browser tool**: the agent drives Chrome or Edge, and screenshots go to models that can see.
- Paste or drop images; speak instead of typing.
- **Schedules** that run prompts on a timetable.
- A **developer API** with Python and JavaScript SDKs.
- Automatic updates and one-click bug reports (keys masked, sent nowhere).

## 1.6.0 – 1.6.3 (2026-10-29)

- Interrupted runs resume after a restart.
- Model facts from models.dev.
- **Arabic** with right-to-left layout.
- Light/dark switch, command palette (Ctrl P).
- Compaction keeps your whole history readable.
- Undo puts your message back in the box.

## 1.5.0 (2026-10-29)

- The agent sets its own goals.
- A built-in Helper subagent.
- Working Zadloop imports.
- A new look.

## 1.4.0 (2026-10-29)

**Built for long jobs**

- Goals, a live to-do list and error checks after edits.
- Background jobs, hooks, slash commands and git worktrees.
- Cost tracking with budgets.

## 1.3.0 – 1.3.3 (2026-10-28)

**AFH's own engine**

- A new agent engine written for AFH replaces OpenCode.
- Code now streams into the Live pane as it's written, and config changes no longer restart anything.
- Import threads from Zadloop exports; installer fixes.

## 1.1 – 1.2.1 (2026-10-28)

- The Live file pane, an activity timeline and states before the reply starts.
- AFH's own harness prompt, an Appearance tab, a two-step model picker and a custom title bar.
- Tokens per second and time per reply.

## 1.0 (2026-10-28)

**Hello, AFH**

- The Sunset look, Delegate mode and the desktop app.
- Models, skills, prompts, context and remote control.
