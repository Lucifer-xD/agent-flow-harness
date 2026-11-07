# Changelog

Every desktop and phone release. The same list is at [agentflowharness.com/changelog](https://agentflowharness.com/changelog).

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
