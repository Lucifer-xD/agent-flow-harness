// Interface language and direction. English is the source language; Arabic is a dictionary keyed by
// the English text. Instead of touching every file, the interface is translated as it appears: an
// observer swaps known English text (and titles/placeholders) for Arabic, and puts the English back
// when you switch again. Conversation content — your messages, the model's replies, code, file
// paths — is never translated; it gets its own per-paragraph direction instead.

const AR = {
  // sidebar, top bar, composer
  "New thread": "محادثة جديدة", "New thread (Ctrl+N)": "محادثة جديدة (Ctrl+N)", "Search threads": "ابحث في المحادثات", "Settings": "الإعدادات",
  "Today": "اليوم", "Yesterday": "أمس", "This week": "هذا الأسبوع", "No threads yet": "لا توجد محادثات بعد", "No matching threads": "لا توجد محادثات مطابقة",
  "Choose a project folder": "اختر مجلد مشروع", "Open a folder to start.": "افتح مجلدًا للبدء.", "Open folder": "افتح مجلدًا", "Open folder…": "افتح مجلدًا…",
  "Open a folder": "افتح مجلدًا", "Projects": "المشاريع",
  "Project memory": "ذاكرة المشروع",
  "AFH account — from anywhere": "حساب AFH — من أي مكان",
  "Sign in and this PC appears in the AFH app on your Android phone or iPhone. Watch and steer your threads while you're away; nothing to open on your router.": "سجّل الدخول ليظهر هذا الجهاز في تطبيق AFH على هاتفك أندرويد أو آيفون. تابع محادثاتك ووجّهها وأنت بعيد؛ دون فتح أي منفذ في الراوتر.",
  "Open the AFH app on your phone and sign in with the same account to reach this PC.": "افتح تطبيق AFH على هاتفك وسجّل الدخول بالحساب نفسه للوصول إلى هذا الجهاز.",
  "Reachable from your phone": "متاح من هاتفك",
  "Connected — open the AFH app on your phone": "متصل — افتح تطبيق AFH على هاتفك",
  "Off — your phone can't reach this PC": "متوقف — لا يستطيع هاتفك الوصول إلى هذا الجهاز",
  "Connecting…": "جارٍ الاتصال…",
  "Reconnecting…": "جارٍ إعادة الاتصال…",
  "Create an account": "إنشاء حساب",
  "Sign in with your browser": "سجّل الدخول عبر المتصفح",
  "Use AFH from your phone": "استخدم AFH من هاتفك",
  "Not signed in": "لم تسجّل الدخول",
  "Signed in": "تم تسجيل الدخول",
  "Sign in and this PC appears in the AFH app on your Android phone or iPhone. Nothing to open on your router.": "سجّل الدخول ليظهر هذا الجهاز في تطبيق AFH على هاتفك أندرويد أو آيفون. دون فتح أي منفذ في الراوتر.",
  "Finish in your browser…": "أكمل في المتصفح…",
  "Phone access off": "الوصول من الهاتف متوقف",
  "Reach this PC from the AFH app on your phone — follow threads, approve steps and send tasks from anywhere.": "صِل إلى هذا الجهاز من تطبيق AFH على هاتفك — تابع المحادثات ووافق على الخطوات وأرسل المهام من أي مكان.",
  "AFH account — reach this PC from your phone": "حساب AFH — صِل إلى هذا الجهاز من هاتفك",
  "Open AFH from a phone, tablet or another computer on your own network: same threads, same approvals, live. To reach this PC from anywhere with the AFH phone app, use the account button at the bottom of the sidebar.": "افتح AFH من هاتف أو جهاز لوحي أو حاسوب آخر على شبكتك: المحادثات نفسها والموافقات نفسها، مباشرة. للوصول إلى هذا الجهاز من أي مكان بتطبيق AFH على الهاتف، استخدم زر الحساب أسفل الشريط الجانبي.",
  "Open the page again": "افتح الصفحة مرة أخرى",
  "Waiting for you in your browser…": "بانتظارك في المتصفح…",
  "Sign in or create your account there and approve this PC. The page shows the code ": "سجّل الدخول أو أنشئ حسابك هناك ووافق على هذا الجهاز. تعرض الصفحة الرمز ",
  "You sign in or create the account on agentflowharness.com — AFH never sees your password. The account is only for remote access.": "تسجّل الدخول أو تنشئ الحساب على agentflowharness.com — لا يرى AFH كلمة مرورك أبدًا. الحساب للوصول عن بُعد فقط.",
  "Manage account": "إدارة الحساب",
  "Create account": "إنشاء الحساب",
  "Sign in": "تسجيل الدخول",
  "Sign out": "تسجيل الخروج",
  "Account": "الحساب",
  "On your own network": "على شبكتك المحلية",
  "Your computers": "أجهزتك",
  "This PC is now in your AFH account": "أصبح هذا الجهاز ضمن حساب AFH",
  "Signed out — this PC was removed from your account": "تم تسجيل الخروج — أُزيل هذا الجهاز من حسابك",
  "Anyone signed in to this account can use AFH here like you — including running commands. Traffic goes over HTTPS through agentflowharness.com, which passes it on without keeping it.": "يستطيع أي شخص مسجّل الدخول بهذا الحساب استخدام AFH هنا مثلك — بما في ذلك تشغيل الأوامر. تمرّ البيانات عبر HTTPS من خلال agentflowharness.com الذي ينقلها دون الاحتفاظ بها.",
  "Private to this computer and kept out of git — tokens and logins are fine here. It's sent only to your model provider, as part of the prompt.": "خاصة بهذا الجهاز ومستبعدة من git — لا بأس بحفظ الرموز وبيانات الدخول هنا. لا تُرسل إلا إلى مزوّد النموذج ضمن التعليمات.",
  "This file was committed to git before, so git still tracks it. Run ": "سبق أن أُضيف هذا الملف إلى git، فما زال git يتتبّعه. شغّل ",
  " in the project before saving credentials here.": " في المشروع قبل حفظ بيانات الدخول هنا.", "Memory": "الذاكرة", "Memory: what the agent knows about this project": "الذاكرة: ما يعرفه الوكيل عن هذا المشروع",
  "Edit as text": "تحرير كنص", "Back to list": "العودة إلى القائمة", "Forget": "انسَ", "Updated": "تم التحديث", "Forgotten": "تم النسيان",
  "Already in memory": "موجود في الذاكرة بالفعل", "Your notes": "ملاحظاتك",
  "Something the agent should always know here… e.g. “Run the tests with pnpm test”": "شيء يجب أن يعرفه الوكيل دائمًا هنا… مثل «شغّل الاختبارات بـ pnpm test»",
  "Add something above, or tell the agent “remember …” in any thread — it also saves what it learns on its own.": "أضف شيئًا في الأعلى، أو قل للوكيل «تذكّر …» في أي محادثة — وهو أيضًا يحفظ ما يتعلّمه بنفسه.",
  "Lines starting with “- ” are facts; anything else is a note the agent reads too.": "الأسطر التي تبدأ بـ «- » حقائق؛ وأي شيء آخر ملاحظة يقرؤها الوكيل أيضًا.",
  "Saved — the agent sees it from its next step": "تم الحفظ — سيراه الوكيل من خطوته التالية", "Checked memory": "راجع الذاكرة", "Checking memory": "يراجع الذاكرة",
  "The agent just changed the memory; save or go back to the list to see it": "غيّر الوكيل الذاكرة للتو؛ احفظ أو ارجع إلى القائمة لتراها", "Project memory: what the agent remembers about this project": "ذاكرة المشروع: ما يتذكره الوكيل عن هذا المشروع",
  "What the agent has learned about this project — how to run it, conventions, your preferences. Every thread here reads it before starting. Fix anything that is wrong; one fact per line, starting with “- ”.": "ما تعلّمه الوكيل عن هذا المشروع — كيف يُشغَّل، الأعراف المتبعة، تفضيلاتك. كل محادثة هنا تقرأه قبل أن تبدأ. صحّح أي خطأ؛ حقيقة واحدة في كل سطر يبدأ بـ «- ».",
  "Nothing remembered yet.": "لا شيء محفوظ بعد.", "The agent just changed the project memory; close and reopen to see it": "غيّر الوكيل ذاكرة المشروع للتو؛ أغلق النافذة وافتحها من جديد لتراه",
  "Remembered": "تذكّر", "Remembering": "يتذكّر", "Forgot": "نسي", "Forgetting": "ينسى", "Corrected memory": "صحّح الذاكرة", "Correcting memory": "يصحّح الذاكرة",
  "Updated project memory": "حدّث ذاكرة المشروع", "Updating project memory": "يحدّث ذاكرة المشروع", "Remove from list": "أزل من القائمة", "Import thread…": "استورد محادثة…",
  "From an export file, OpenCode or Zadloop": "من ملف تصدير أو OpenCode أو Zadloop", "Hide sidebar (Ctrl+B)": "إخفاء الشريط الجانبي (Ctrl+B)", "Show sidebar (Ctrl+B)": "إظهار الشريط الجانبي (Ctrl+B)",
  "Engine connection": "اتصال المحرك", "Switch dark / light": "التبديل بين الداكن والفاتح", "Switch to dark": "التبديل إلى الداكن", "Switch to light": "التبديل إلى الفاتح",
  "Goal": "الهدف", "Live": "مباشر", "Context": "السياق", "Prompt": "التعليمات", "Changes": "التغييرات", "Thread actions": "إجراءات المحادثة",
  "Watch files being written or edited": "شاهد الملفات أثناء كتابتها أو تعديلها", "See and edit everything the model sees": "اعرض وعدّل كل ما يراه النموذج",
  "See what the model is told": "اعرض ما يُقال للنموذج", "Changed files": "الملفات المعدّلة", "Double-click to rename": "انقر مرتين لإعادة التسمية",
  "Ask anything…": "اسأل عن أي شيء…", "Attach files": "إرفاق ملفات", "Send (Enter)": "إرسال (Enter)", "Send (Ctrl+Enter)": "إرسال (Ctrl+Enter)", "Stop (Esc)": "إيقاف (Esc)",
  "Context used": "السياق المستخدم", "Choose model": "اختر نموذجًا", "Ask first": "اسأل أولًا", "Full access": "وصول كامل", "Read only": "قراءة فقط",
  "Approve file edits and commands": "وافق على تعديلات الملفات والأوامر", "Edit files and run commands freely": "عدّل الملفات وشغّل الأوامر بحرية",
  "Can read and search, never edit or run": "يقرأ ويبحث فقط، لا يعدّل ولا يشغّل", "· type / for commands": "· اكتب / للأوامر",
  "Working… press Esc to stop, or type to queue a follow-up": "يعمل… اضغط Esc للإيقاف، أو اكتب رسالة لتُرسل بعده",
  "Set a goal for the new thread": "حدّد هدفًا للمحادثة الجديدة", "Work in a separate git worktree (own branch and folder)": "اعمل في نسخة git منفصلة (فرع ومجلد خاصان)",
  "Worktree": "نسخة عمل", "Goal set": "تم تحديد الهدف", "Set a goal: the agent keeps working until it is achieved": "حدّد هدفًا: يواصل الوكيل العمل حتى يتحقق",
  "This thread works in its own git worktree": "هذه المحادثة تعمل في نسخة git خاصة بها", "Drag to make the chat wider or narrower · double-click to reset": "اسحب لتوسيع المحادثة أو تضييقها · انقر مرتين للإعادة",
  "Your messages": "رسائلك", "Chat width reset": "تمت إعادة عرض المحادثة",
  // home
  "What are we building?": "ماذا سنبني؟", "Welcome to Agent Flow Harness": "مرحبًا بك في Agent Flow Harness",
  "Open a project folder and AFH will read, edit and run code there with any model you choose.": "افتح مجلد مشروع وسيقرأ AFH الكود ويعدّله ويشغّله فيه بأي نموذج تختاره.",
  "Explain this codebase": "اشرح هذا المشروع", "Give me a tour of the architecture and the main entry points.": "خذني في جولة على بنية المشروع ونقاط الدخول الرئيسية.",
  "Find and fix a bug": "اعثر على خطأ وأصلحه", "Run the tests, find what's failing, and fix it.": "شغّل الاختبارات، واعرف ما يفشل، وأصلحه.",
  "Write tests": "اكتب اختبارات", "Add tests for the parts of this project that have none.": "أضف اختبارات للأجزاء التي لا تملك اختبارات.",
  "Review my changes": "راجع تغييراتي", "Review the uncommitted changes and point out problems.": "راجع التغييرات غير المحفوظة في git وأشر إلى المشكلات.",
  "Starting the engine…": "جارٍ تشغيل المحرك…", "AFH couldn't start": "تعذّر تشغيل AFH", "Technical details": "تفاصيل تقنية", "Retry": "أعد المحاولة",
  // conversation
  "Thinking": "يفكّر", "Thoughts": "الأفكار", "Working": "يعمل", "Stopped": "توقف", "You": "أنت", "Assistant": "المساعد", "Copy": "نسخ", "Copied": "تم النسخ",
  "Fork thread from here": "انسخ المحادثة من هنا", "Undo to here — rewind the thread and the files to just before this message": "تراجع إلى هنا — أرجع المحادثة والملفات إلى ما قبل هذه الرسالة",
  "Sending your message": "جارٍ إرسال رسالتك", "The run failed": "فشل التشغيل", "Change model": "غيّر النموذج", "Raw response": "الاستجابة الخام",
  "Couldn't reach the provider": "تعذّر الوصول إلى المزوّد", "The provider rejected the credentials": "رفض المزوّد بيانات الاعتماد", "Rate limited": "تم تجاوز حد الطلبات",
  "Plan or credit limit": "حد الخطة أو الرصيد", "The provider timed out": "انتهت مهلة المزوّد", "The conversation is too long for this model": "المحادثة أطول من قدرة هذا النموذج",
  "The provider had a problem": "حدثت مشكلة لدى المزوّد", "That's on their side. Retry in a bit or switch models.": "المشكلة من جهتهم. أعد المحاولة بعد قليل أو بدّل النموذج.",
  "Allow file changes?": "السماح بتغيير الملفات؟", "Run this command?": "تشغيل هذا الأمر؟", "Approve": "موافقة", "Always allow": "اسمح دائمًا", "Reject": "رفض",
  "Don't ask again for this in this thread": "لا تسأل مجددًا عن هذا في هذه المحادثة", "Tell the agent what to do instead (optional)": "أخبر الوكيل بما يفعله بدلًا من ذلك (اختياري)",
  "Command": "الأمر", "Input": "المدخلات", "Output": "المخرجات", "preparing": "يحضّر", "running": "يعمل", "failed": "فشل", "checked": "تم الفحص",
  "Wrote": "كتب", "Writing": "يكتب", "Edited": "عدّل", "Editing": "يعدّل", "Patched": "رقّع", "Patching": "يرقّع", "Ran": "شغّل", "Running": "يشغّل", "Read": "قرأ", "Reading": "يقرأ",
  "Found files": "عثر على ملفات", "Finding files": "يبحث عن ملفات", "Searched": "بحث", "Searching": "يبحث", "Listed": "سرد", "Listing": "يسرد", "Fetched": "جلب", "Fetching": "يجلب",
  "Searched the web": "بحث في الويب", "Searching the web": "يبحث في الويب", "Loaded skill": "حمّل مهارة", "Loading skill": "يحمّل مهارة", "Asked": "سأل", "Asking": "يسأل",
  "Started in background": "بدأ في الخلفية", "Starting in background": "يبدأ في الخلفية", "Stopped job": "أوقف المهمة", "Stopping job": "يوقف المهمة",
  "Listed jobs": "سرد المهام", "Listing jobs": "يسرد المهام", "Read job output": "قرأ مخرجات المهمة", "Waiting for job output": "ينتظر مخرجات المهمة",
  "Planning": "يخطط", "Checked the to-do list": "راجع قائمة المهام", "Updated the to-do list": "حدّث قائمة المهام", "blocked by hook": "حجبه خطاف",
  "Goal achieved": "تحقق الهدف", "Goal blocked — needs you": "الهدف متوقف — يحتاجك", "How it was verified": "كيف تم التحقق", "Milestone:": "إنجاز:", "Goal set:": "تم تحديد الهدف:",
  "what the agent was told": "ما قيل للوكيل", "Goal not achieved yet — continuing": "لم يتحقق الهدف بعد — يتابع", "A stop hook failed — continuing": "فشل خطاف الإيقاف — يتابع",
  "To-do items still open — checking": "ما زالت هناك مهام مفتوحة — يتحقق", "AFH restarted — picking up where it left off": "أُعيد تشغيل AFH — يتابع من حيث توقف",
  "Earlier context was compacted — summary": "تم ضغط السياق السابق — الملخص", "No summary was kept for this compaction.": "لم يُحفظ ملخص لهذا الضغط.",
  "Summarising older messages to free up context…": "جارٍ تلخيص الرسائل القديمة لتوفير مساحة في السياق…",
  // delegation / subagents
  "Subagents": "الوكلاء الفرعيون", "Subagent": "وكيل فرعي", "Subagent task": "مهمة وكيل فرعي", "Watch": "شاهد", "Done": "تم", "Failed": "فشل", "Preparing": "يحضّر",
  "Needs approval": "يحتاج موافقة", "What the lead asked": "ما طلبه القائد", "What it reported": "ما أبلغ به", "What it replied": "ما ردّ به", "Working on it…": "يعمل عليه…",
  "No subagents in this thread yet.": "لا يوجد وكلاء فرعيون في هذه المحادثة بعد.", "Open the subagent's thread beside this one": "افتح محادثة الوكيل الفرعي بجانب هذه",
  "Open as its own thread": "افتحها كمحادثة مستقلة", "Nothing to watch.": "لا شيء للمشاهدة.", "Delegation failed": "فشل التفويض", "continued": "متابعة", "background": "في الخلفية", "worktree": "نسخة عمل",
  "Helper": "المساعد", "thread model": "نموذج المحادثة",
  // dock: goal, to-do, jobs
  "Current goal": "الهدف الحالي", "Set a new goal": "حدّد هدفًا جديدًا", "Achieved goals": "الأهداف المُحقَّقة", "Completed lists": "القوائم المكتملة", "No achieved goals in this thread yet.": "لا توجد أهداف مُحقَّقة في هذه المحادثة بعد.", "No completed to-do lists yet.": "لا توجد قوائم مهام مكتملة بعد.", "To-do list": "قائمة المهام",
  "To-do": "المهام", "empty": "فارغة", "All done": "اكتمل كل شيء", "Add a step… (Enter)": "أضف خطوة… (Enter)", "Collapse": "طيّ", "Expand": "توسيع",
  "Mark done": "علّمها منجزة", "Mark not done": "علّمها غير منجزة", "Mark in progress": "علّمها قيد التنفيذ", "Not in progress": "ليست قيد التنفيذ", "Remove": "إزالة",
  "Double-click to edit": "انقر مرتين للتعديل", "Goal achieved · set by the agent": "تحقق الهدف · حدده الوكيل", "Goal · set by the agent": "الهدف · حدده الوكيل",
  "Goal · from your request": "الهدف · من طلبك", "Goal blocked": "الهدف متوقف", "Goal paused": "الهدف متوقف مؤقتًا", "Autopilot off": "الطيار الآلي متوقف", "Autopilot on": "الطيار الآلي يعمل",
  "Autopilot paused": "الطيار الآلي متوقف مؤقتًا", "Edit goal": "عدّل الهدف", "Goal actions": "إجراءات الهدف", "Mark achieved": "علّمه متحققًا", "Reopen goal": "أعد فتح الهدف",
  "Back to active, fresh autopilot budget": "عودة إلى النشاط، بميزانية طيار آلي جديدة", "Pause goal": "أوقف الهدف مؤقتًا", "The agent stops working toward it": "يتوقف الوكيل عن العمل عليه",
  "Edit…": "تعديل…", "Remove goal": "أزل الهدف", "Remove the goal?": "إزالة الهدف؟", "Goal marked achieved": "عُلّم الهدف متحققًا", "Goal reopened": "أُعيد فتح الهدف", "Goal paused.": "أوقف الهدف مؤقتًا.",
  "Set a goal": "حدّد هدفًا", "Edit the goal": "عدّل الهدف", "Done when": "يكتمل عندما", "Autopilot": "الطيار الآلي", "Continuations": "مرات المتابعة",
  "Keep working until the goal is achieved, without stopping to ask": "واصل العمل حتى يتحقق الهدف دون التوقف للسؤال",
  "How many times autopilot may send it back to work per message": "كم مرة يمكن للطيار الآلي إعادته للعمل في كل رسالة",
  "Tell the agent what done looks like. It plans the steps in its to-do list, works through them, verifies the result, and reports the goal achieved — or blocked, if it needs you.":
    "أخبر الوكيل كيف يبدو الإنجاز. سيخطط الخطوات في قائمة مهامه، وينفّذها، ويتحقق من النتيجة، ثم يبلغ عن تحقق الهدف — أو توقفه إن احتاجك.",
  "Cancel": "إلغاء", "Save": "حفظ", "Set goal": "حدّد الهدف", "Start now": "ابدأ الآن", "Save & start": "احفظ وابدأ", "Goal saved": "تم حفظ الهدف", "Goal set — working on it": "تم تحديد الهدف — يعمل عليه",
  "Describe the goal first.": "صِف الهدف أولًا.", "Background jobs": "مهام الخلفية", "No background jobs in this thread.": "لا توجد مهام خلفية في هذه المحادثة.",
  "Dismiss": "تجاهل", "Stop": "إيقاف", "stopped": "متوقفة", "Background jobs (finished)": "مهام الخلفية (منتهية)",
  // commands menu
  "Commands": "الأوامر", "↑↓ choose · Enter run · Esc close": "↑↓ للاختيار · Enter للتشغيل · Esc للإغلاق", "built-in": "مدمج", "project": "المشروع", "global": "عام", "yours": "أوامرك",
  "Start a thread first": "ابدأ محادثة أولًا", "Compacting…": "جارٍ الضغط…", "Older messages summarised": "تم تلخيص الرسائل القديمة", "Nothing to compact yet": "لا يوجد ما يُضغط بعد",
  // context popover & drawer
  "In the window now": "في النافذة الآن", "Model": "النموذج", "Mode": "الوضع", "Messages": "الرسائل", "Tokens this thread": "رموز هذه المحادثة", "From the prompt cache": "من ذاكرة التعليمات المؤقتة",
  "Cost": "التكلفة", "plan (no per-token cost)": "خطة (بلا تكلفة لكل رمز)", "price not set": "السعر غير محدد", "Compact now": "اضغط الآن", "Context editor": "محرر السياق",
  "Summarise older messages now to free up context": "لخّص الرسائل القديمة الآن لتوفير مساحة في السياق",
  "Set this model's price in Settings → Usage & cost to track spending.": "حدّد سعر هذا النموذج في الإعدادات ← الاستخدام والتكلفة لتتبع الإنفاق.",
  "No file changes in this thread yet.": "لا توجد تغييرات على الملفات في هذه المحادثة بعد.", "What the model is told": "ما يُقال للنموذج", "Close": "إغلاق",
  "When the model writes or edits a file, or runs a command, it appears here as it happens.": "عندما يكتب النموذج ملفًا أو يعدّله أو يشغّل أمرًا يظهر هنا لحظة بلحظة.", "Running a command": "يشغّل أمرًا", "Ran a command": "شغّل أمرًا", "Waiting for the first output…": "بانتظار أول مخرجات…", "(no output)": "(لا مخرجات)", "follow": "متابعة",
  "Loading the file…": "جارٍ تحميل الملف…", "Waiting for the file path…": "بانتظار مسار الملف…", "Waiting for the text to replace…": "بانتظار النص المراد استبداله…",
  "Locating the text to replace…": "جارٍ تحديد النص المراد استبداله…", "Preparing the file…": "جارٍ تحضير الملف…", "done": "تم", "live": "مباشر",
  "The text to replace isn't in this copy of the file (it may have changed).": "النص المراد استبداله غير موجود في هذه النسخة من الملف (ربما تغيّر).",
  // thread menu, dialogs, toasts
  "Rename": "إعادة تسمية", "Fork thread": "انسخ المحادثة", "Edit context…": "عدّل السياق…", "Change or remove anything the model sees": "غيّر أو احذف أي شيء يراه النموذج",
  "Export thread…": "صدّر المحادثة…", "Save as .afh-session.json to share or move": "احفظ كملف ‎.afh-session.json‎ للمشاركة أو النقل", "Copy as Markdown": "انسخ بتنسيق Markdown",
  "Archive": "أرشفة", "Delete": "حذف", "Delete thread": "حذف المحادثة", "Delete thread?": "حذف المحادثة؟", "Rename thread": "إعادة تسمية المحادثة", "Thread archived": "تمت أرشفة المحادثة",
  "Thread copied": "تم نسخ المحادثة", "Forked into a new thread": "نُسخت إلى محادثة جديدة", "Confirm": "تأكيد", "Keep": "إبقاء", "Put it back": "أرجعها", "Undone": "تم التراجع", "Rewound.": "تم الإرجاع.",
  "Import a thread": "استيراد محادثة", "From a file": "من ملف", "From Zadloop": "من Zadloop", "Choose a file…": "اختر ملفًا…", "or paste JSON:": "أو الصق JSON:", "Import pasted JSON": "استورد JSON الملصق",
  "Import this thread": "استورد هذه المحادثة", "Import": "استيراد", "Reading…": "جارٍ القراءة…", "Open a project folder first.": "افتح مجلد مشروع أولًا.",
  "Merge": "دمج", "Copy folder path": "انسخ مسار المجلد", "Open the folder": "افتح المجلد", "Remove worktree…": "أزل نسخة العمل…", "Branch": "الفرع", "Made from": "مأخوذ من",
  "Merge this thread's branch?": "دمج فرع هذه المحادثة؟", "Remove the worktree?": "إزالة نسخة العمل؟", "Worktree removed": "أُزيلت نسخة العمل", "Path copied": "تم نسخ المسار",
  "Creating a worktree…": "جارٍ إنشاء نسخة عمل…", "Approval needed": "مطلوبة موافقة", "Run failed": "فشل التشغيل", "The thread finished": "انتهت المحادثة",
  "Applying changes…": "جارٍ تطبيق التغييرات…", "Use the paperclip to attach files": "استخدم مشبك الورق لإرفاق الملفات", "Add a provider and pick a model first": "أضف مزوّدًا واختر نموذجًا أولًا",
  // settings: navigation and common
  "General": "عام", "Appearance": "المظهر", "Personalization": "التخصيص", "Agent": "الوكيل", "Delegation": "التفويض", "Models & providers": "النماذج والمزوّدون",
  "Usage & cost": "الاستخدام والتكلفة", "Skills": "المهارات", "MCP servers": "خوادم MCP", "Prompts & agents": "التعليمات والوكلاء", "Hooks": "الخطافات",
  "Remote control": "التحكم عن بُعد", "About": "حول", "Changes save automatically unless a Save button is shown.": "تُحفظ التغييرات تلقائيًا ما لم يظهر زر حفظ.", "Close (Esc)": "إغلاق (Esc)",
  "Saved": "تم الحفظ", "Removed": "تمت الإزالة", "Deleted": "تم الحذف", "Add": "إضافة", "Edit": "تعديل", "Reset": "إعادة تعيين", "Use": "استخدم", "Test": "اختبار",
  "Restart": "إعادة تشغيل", "Name": "الاسم", "Description": "الوصف", "When": "متى", "Type": "النوع", "Off": "إيقاف", "On": "تشغيل", "Templates": "القوالب",
  // general
  "How Agent Flow Harness behaves. Looks are in Appearance.": "كيف يتصرف Agent Flow Harness. الشكل في قسم المظهر.", "New threads": "المحادثات الجديدة", "Default mode": "الوضع الافتراضي",
  "Build, Plan, Delegate or one of your agents": "بناء، أو تخطيط، أو تفويض، أو أحد وكلائك", "Default approval mode": "وضع الموافقة الافتراضي",
  "Ask first shows every edit and command before it runs": "«اسأل أولًا» يعرض كل تعديل وأمر قبل تنفيذه", "Reopen the last thread on start": "افتح آخر محادثة عند البدء",
  "Conversation": "المحادثة", "Show thinking": "إظهار التفكير", "Display the model's reasoning when it shares it": "اعرض تفكير النموذج عندما يشاركه",
  "Show model, tokens and time under replies": "اعرض النموذج والرموز والوقت أسفل الردود", "Otherwise only on hover": "وإلا فعند المرور فقط", "Send with": "الإرسال بـ",
  "Ask before deleting a thread": "اسأل قبل حذف محادثة", "Live file view": "عرض الملفات المباشر", "Open a side pane and show files being written or edited as it happens": "افتح لوحة جانبية واعرض الملفات أثناء كتابتها أو تعديلها",
  "Notifications": "الإشعارات", "When you're in another window": "عندما تكون في نافذة أخرى", "Sounds": "الأصوات", "A short tone when a run finishes or needs your approval": "نغمة قصيرة عندما ينتهي التشغيل أو يحتاج موافقتك",
  "Desktop notifications": "إشعارات سطح المكتب", "System notification when a thread finishes or needs approval": "إشعار نظام عندما تنتهي محادثة أو تحتاج موافقة", "Keyboard": "لوحة المفاتيح",
  "Language & direction": "اللغة والاتجاه", "Interface language": "لغة الواجهة", "Layout direction": "اتجاه التخطيط", "Automatic": "تلقائي", "Left to right": "من اليسار لليمين", "Right to left": "من اليمين لليسار",
  "The conversation always follows the text: Arabic paragraphs read right to left, English left to right.": "المحادثة تتبع النص دائمًا: الفقرات العربية من اليمين لليسار والإنجليزية من اليسار لليمين.",
  // appearance
  "Make it yours: theme, colors, type, shape and motion. Changes apply instantly.": "اجعله لك: السمة والألوان والخط والشكل والحركة. تُطبّق التغييرات فورًا.",
  "Theme": "السمة", "Follow system": "اتبع النظام", "Dark": "داكن", "Light": "فاتح", "Dark themes": "السمات الداكنة", "Light themes": "السمات الفاتحة", "dark": "داكنة", "light": "فاتحة",
  "Custom": "مخصصة", "your colors": "ألوانك", "Background": "الخلفية", "Text": "النص", "Accent": "لون التمييز", "Buttons, focus rings, the active thread, the delegation cards": "الأزرار وحلقات التركيز والمحادثة النشطة وبطاقات التفويض",
  "Font": "الخط", "Text size": "حجم النص", "Shape & layout": "الشكل والتخطيط", "Corner roundness": "استدارة الزوايا", "Density": "الكثافة", "Comfortable": "مريح", "Compact": "مضغوط",
  "type / for commands": "اكتب / للأوامر", "Build": "بناء", "Plan": "تخطيط", "Delegate": "تفويض", "The default mode. Reads, edits and runs code in the project.": "الوضع الافتراضي. يقرأ الكود ويعدّله ويشغّله في المشروع.",
  "Investigates and proposes a plan without changing anything.": "يدرس ويقترح خطة دون تغيير أي شيء.", "Leads the work and delegates tasks to your delegate models.": "يقود العمل ويفوّض المهام إلى نماذجك المفوَّضة.",
  "Create or edit agents…": "أنشئ وكلاء أو عدّلهم…", "Effort ": "الجهد ", "Type a command, thread, model or theme…": "اكتب أمرًا أو محادثة أو نموذجًا أو سمة…", "Actions": "إجراءات", "Thread": "المحادثة",
  "Threads": "المحادثات", "Models": "النماذج", "Themes": "السمات", "English interface": "الواجهة الإنجليزية", "Compact now ": "اضغط الآن ", "Summarise older messages": "لخّص الرسائل القديمة", "Bubbles on the right, or flat with an accent bar": "فقاعات على الجانب، أو مسطحة بشريط ملوّن", "Bubbles": "فقاعات", "Flat": "مسطحة",
  "Glass effect": "تأثير زجاجي", "Translucent composer, sidebar and menus": "صندوق كتابة وشريط جانبي وقوائم شبه شفافة", "Motion": "الحركة", "Animations": "الحركات",
  "Messages, panels, menus": "الرسائل واللوحات والقوائم", "Animation speed": "سرعة الحركة", "Logo flows while a model works": "الشعار يتحرك أثناء عمل النموذج", "Preview": "معاينة",
  "Custom CSS": "CSS مخصص", "For power users: anything here is injected into the app": "للمستخدمين المتقدمين: أي شيء هنا يُضاف إلى التطبيق", "Apply": "تطبيق", "Applied": "تم التطبيق",
  // personalization
  "Tell the agent about you and how you like to work. This becomes an instructions file every thread reads.": "عرّف الوكيل بنفسك وبطريقة عملك. يصبح هذا ملف تعليمات تقرؤه كل محادثة.",
  "Use personalization": "استخدم التخصيص", "Turn off to send none of this to the model": "أوقفه كي لا يُرسل شيء من هذا للنموذج", "About you": "عنك",
  "What should it call you?": "بماذا يناديك؟", "What do you do?": "ماذا تعمل؟", "Anything else it should know?": "هل هناك شيء آخر يجب أن يعرفه؟", "How it responds": "كيف يرد",
  "Response length": "طول الرد", "Concise": "موجز", "Balanced": "متوازن", "Detailed": "مفصّل", "Tone": "النبرة", "Custom instructions": "تعليمات مخصصة",
  "Plain text or Markdown. Added to every thread's instructions.": "نص عادي أو Markdown. يُضاف إلى تعليمات كل محادثة.", "Personalization saved — applies to the next message": "حُفظ التخصيص — يُطبّق من الرسالة التالية",
  // agent tab
  "How the agent works through a task: its step budget, the to-do list, goals with autopilot, and the error checks it gets after every edit.": "كيف ينجز الوكيل المهمة: عدد خطواته، وقائمة المهام، والأهداف مع الطيار الآلي، وفحوص الأخطاء بعد كل تعديل.",
  "Work loop": "حلقة العمل", "Steps per run": "الخطوات لكل تشغيل", "The most model calls one message may trigger before AFH stops and waits for you": "أقصى عدد من استدعاءات النموذج لرسالة واحدة قبل أن يتوقف AFH وينتظرك",
  "Check the to-do list before finishing": "راجع قائمة المهام قبل الإنهاء", "If the agent ends its turn with open to-do items, it is asked once to finish them or update the list": "إذا أنهى الوكيل دوره والمهام مفتوحة يُطلب منه مرة واحدة إكمالها أو تحديث القائمة",
  "Goals": "الأهداف", "Goals for every multi-step task": "هدف لكل مهمة متعددة الخطوات", "Off: the agent sets a goal only when you ask for one. On: when it plans 3 or more steps, your request becomes the thread's goal": "إيقاف: لا يحدّد الوكيل هدفًا إلا إذا طلبتَ ذلك. تشغيل: عندما يخطط لثلاث خطوات أو أكثر، يصبح طلبك هدف المحادثة",
  "Autopilot by default": "الطيار الآلي افتراضيًا", "New goals keep the agent working until it reports them achieved or blocked": "الأهداف الجديدة تُبقي الوكيل يعمل حتى يبلغ عن تحققها أو توقفها",
  "Continuations per message": "مرات المتابعة لكل رسالة", "How often autopilot may send the agent back to work before it waits for you": "كم مرة يعيد الطيار الآلي الوكيل للعمل قبل أن ينتظرك",
  "Pick up after a restart": "المتابعة بعد إعادة التشغيل", "If AFH closes while a thread is working (an update, a crash), it continues that thread when it opens again": "إذا أُغلق AFH أثناء عمل محادثة (تحديث أو عطل) يتابعها عند فتحه مجددًا",
  "Error checks after edits": "فحص الأخطاء بعد التعديل", "When a step changes files, AFH checks them and gives the problems straight back to the model": "عندما تغيّر خطوة ملفات يفحصها AFH ويعيد المشكلات للنموذج مباشرة",
  "TypeScript type check": "فحص أنواع TypeScript", "ruff for Python": "ruff لبايثون", "Your own checks": "فحوصك الخاصة", "Add check": "أضف فحصًا", "Check added": "أُضيف الفحص",
  "No custom checks. The built-in ones run without setup.": "لا توجد فحوص مخصصة. الفحوص المدمجة تعمل دون إعداد.", "Files": "الملفات", "Comma-separated patterns": "أنماط مفصولة بفواصل",
  // hooks, commands, usage
  "Your hooks": "خطافاتك", "Add hook": "أضف خطافًا", "Hook added": "أُضيف الخطاف", "Hook saved": "حُفظ الخطاف", "No hooks yet. Start from a template below or add your own.": "لا توجد خطافات بعد. ابدأ من قالب أدناه أو أضف خطافك.",
  "Before a tool runs": "قبل تشغيل أداة", "After a tool succeeds": "بعد نجاح أداة", "When the agent finishes": "عندما ينتهي الوكيل", "One click fills the form; review the command before saving": "نقرة واحدة تملأ النموذج؛ راجع الأمر قبل الحفظ",
  "Run the tests before finishing": "شغّل الاختبارات قبل الإنهاء", "Format Python files after edits": "نسّق ملفات بايثون بعد التعديل", "Prettier after edits": "Prettier بعد التعديل",
  "Block dangerous commands": "احجب الأوامر الخطرة", "Log every command": "سجّل كل أمر", "Hooks run with your permissions.": "تعمل الخطافات بصلاحياتك.", "Only add commands you understand.": "أضف فقط الأوامر التي تفهمها.",
  "Your commands": "أوامرك", "New command": "أمر جديد", "Add command": "أضف أمرًا", "No saved commands.": "لا توجد أوامر محفوظة.", "From files": "من الملفات", "Built in": "مدمجة",
  "Stored in AFH's settings, available in every project": "محفوظة في إعدادات AFH ومتاحة في كل مشروع",
  "Last 30 days": "آخر 30 يومًا", "Spent": "المُنفق", "Tokens": "الرموز", "From cache": "من الذاكرة المؤقتة", "By model": "حسب النموذج", "Steps": "الخطوات", "In": "داخل", "Out": "خارج",
  "Price / 1M": "السعر / مليون", "Spending limits": "حدود الإنفاق", "Per thread": "لكل محادثة", "Per day": "يوميًا", "USD a single thread may spend": "ما يمكن أن تنفقه محادثة واحدة بالدولار",
  "USD across all threads today": "إجمالي اليوم لكل المحادثات بالدولار", "Limit saved": "حُفظ الحد", "Spending per day": "الإنفاق اليومي", "Tokens per day (no priced model used yet)": "الرموز يوميًا (لم يُستخدم نموذج مسعّر بعد)",
  "No model calls in the last 30 days.": "لا توجد استدعاءات للنماذج في آخر 30 يومًا.", "flat-rate plan": "خطة بسعر ثابت",
  // models
  "Paste an API key for the providers you use, or add any compatible endpoint. Then keep only the models you actually use in the picker.": "الصق مفتاح API للمزوّدين الذين تستخدمهم أو أضف أي نقطة اتصال متوافقة، ثم أبقِ فقط النماذج التي تستخدمها فعلًا.",
  "Default model": "النموذج الافتراضي", "Default model saved": "حُفظ النموذج الافتراضي", "Your providers": "مزوّدوك", "Toggle which models appear in the model picker": "اختر النماذج التي تظهر في قائمة النماذج",
  "Refresh models": "حدّث النماذج", "Model lists refreshed": "تم تحديث قوائم النماذج", "Models refreshed": "تم تحديث النماذج", "Filter models…": "صفِّ النماذج…", "Show all": "أظهر الكل", "Hide all": "أخفِ الكل",
  "Models on this computer": "النماذج على هذا الجهاز", "Scan": "فحص", "Scan again": "افحص مجددًا", "Scanning…": "جارٍ الفحص…", "Add a provider": "أضف مزوّدًا", "Custom endpoint": "نقطة اتصال مخصصة",
  "Connect": "اتصال", "API key": "مفتاح API", "Base URL": "العنوان الأساسي", "Model ids": "معرّفات النماذج", "Picker updated": "تم تحديث القائمة", "Discard": "تجاهل",
  "Model visibility changed.": "تغيّرت النماذج الظاهرة.", "Search all models…": "ابحث في كل النماذج…", "Providers": "المزوّدون", "Add or manage providers…": "أضف المزوّدين أو أدرهم…",
  "Effort": "الجهد", "Effort levels": "مستويات الجهد", "Context window (tokens)": "نافذة السياق (رموز)", "Max output (tokens)": "أقصى مخرجات (رموز)", "Takes in besides text": "يقبل غير النص",
  "Reads images": "يقرأ الصور", "Understands video": "يفهم الفيديو", "Understands audio": "يفهم الصوت", "Reads PDFs": "يقرأ ملفات PDF", "reasoning": "تفكير", "no tools": "بلا أدوات", "edited": "معدّل",
  "Correct this model's context, effort levels or inputs": "صحّح سياق هذا النموذج أو مستويات جهده أو مدخلاته", "Back to the catalog's facts": "عاد إلى بيانات الكتالوج",
  // about
  "Version": "الإصدار", "Engine": "المحرك", "Models available": "النماذج المتاحة", "Reload engine": "أعد تحميل المحرك", "Where things live": "أين تُحفظ الأشياء", "Open source": "مفتوح المصدر",
  "Everything stays on this computer.": "كل شيء يبقى على هذا الجهاز.",
  // 1.7: schedules, developer, bug report, updates, browser, voice, images
  "Schedules": "الجدولة", "Developer": "المطوّر", "Report a bug": "الإبلاغ عن مشكلة", "Jobs": "المهام", "New job": "مهمة جديدة", "Repeat": "التكرار", "Every": "كل",
  "At minute": "عند الدقيقة", "Day": "اليوم", "Time": "الوقت", "Project": "المشروع", "Permissions": "الصلاحيات",
  "Run now": "شغّل الآن", "Other…": "أخرى…", "API keys": "مفاتيح API", "Create key": "أنشئ مفتاحًا", "Where the API is": "مكان الواجهة البرمجية", "Address right now": "العنوان الحالي",
  "Discovery file": "ملف الاكتشاف", "Fixed port": "منفذ ثابت", "Interactive reference": "المرجع التفاعلي", "Quick start": "بداية سريعة", "Open": "فتح",
  "What went wrong": "ما الذي حدث", "Include the backend log": "أرفق سجل الخادم", "Create report": "أنشئ التقرير", "What goes in the zip": "محتويات الملف المضغوط", "Bug report saved": "تم حفظ تقرير المشكلة",
  "Updates": "التحديثات", "Status": "الحالة", "Check now": "تحقق الآن", "Download": "تنزيل", "Restart to update": "أعد التشغيل للتحديث", "Download updates automatically": "نزّل التحديثات تلقائيًا",
  "Update address": "عنوان التحديثات", "Checking for a new version…": "جارٍ البحث عن إصدار جديد…", "Set the update address below to get updates": "اضبط عنوان التحديثات أدناه لتصلك التحديثات",
  "Browser": "المتصفح", "Let the agent use a browser": "اسمح للوكيل باستخدام متصفح", "Show the browser window": "أظهر نافذة المتصفح", "Browser program": "برنامج المتصفح",
  "Voice": "الصوت", "Speech-to-text provider": "مزوّد تحويل الكلام إلى نص", "Language": "اللغة", "Compact the conversation at": "اضغط المحادثة عند",
  "Speak — your words are typed here": "تحدّث — تُكتب كلماتك هنا", "Stop and transcribe": "أوقف وحوّل إلى نص", "Didn't catch any words — try again": "لم تُلتقط أي كلمات — حاول مجددًا",
  "Scheduled job started": "بدأت مهمة مجدولة",
};

// Text with numbers or names in it.
const AR_PATTERNS = [
  [/^Thought for (.+)$/, "فكّر لمدة $1"], [/^completed in (.+)$/, "اكتمل في $1"], [/^(\d+) running$/, "$1 قيد التشغيل"], [/^(\d+) working$/, "$1 يعمل"],
  [/^(\d+) subagents?$/, "$1 وكيل فرعي"], [/^(\d+) jobs?$/, "$1 مهمة"], [/^(\d+)\/(\d+) done$/, "$1/$2 منجز"], [/^Autopilot (\d+)\/(\d+)$/, "الطيار الآلي $1/$2"],
  [/^Compacted (\d+) earlier messages? — summary$/, "ضُغطت $1 رسالة سابقة — الملخص"], [/^(.+) is working$/, "$1 يعمل"], [/^Delivered · waiting for (.+)$/, "تم الإرسال · بانتظار $1"],
  [/^([\d.]+[kM]?) tokens$/, "$1 رمز"], [/^(\d+) problems?$/, "$1 مشكلة"], [/^(\d+) hooks?$/, "$1 خطاف"], [/^(\d+) tool calls?$/, "$1 استدعاء أداة"], [/^(\d+) files?$/, "$1 ملف"],
  [/^Done when: (.+)$/, "يكتمل عندما: $1"], [/^(\d+) in this thread$/, "$1 في هذه المحادثة"], [/^(\d+) working · (\d+) in this thread$/, "$1 يعمل · $2 في هذه المحادثة"],
  [/^Merge into (.+)$/, "ادمج في $1"], [/^Merged into (.+)$/, "دُمج في $1"], [/^(\d+) configured$/, "$1 مُعدّ"], [/^Edit (.+)$/, "تعديل $1"],
  [/^Summarising (\d+) older messages in (\d+) parts… (\d+)\/(\d+)$/, "جارٍ تلخيص $1 رسالة قديمة على $2 أجزاء… $3/$4"], [/^#(\d+)$/, "#$1"],
];

const EXCLUDE = ".md, .bubble, pre, code, textarea, input, .think-text, .compact-text, .rail-text, .th-title, .tb-title h1, .todo-text, .plan-item, .goal-text, .goal-sub, .goal-card-text, .deleg-sub, .deleg-brief-text, .sub-desc, .sub-text, .job-cmd, .job-tail, .job-full, .live-code, .live-head .path, .diff, .h-pre, .tool-pre, .tool-target, .deleg-last, .err-msg, .slash-desc, .slash-name, .cmd-chip, .file-chip, .tb-path, .wt-path, .li-sub, .pi-sub, .deleg-model, .model";
const ATTRS = ["title", "placeholder", "aria-label"];

const originals = new WeakMap(); // text node -> English text it replaced
const attrOriginals = new WeakMap(); // element -> {attr: English}
let lang = "en";
let observer = null;

function translateText(s) {
  const t = s.trim();
  if (!t) return null;
  let out = AR[t];
  if (out == null) {
    for (const [re, rep] of AR_PATTERNS) {
      if (re.test(t)) { out = t.replace(re, rep); break; }
    }
  }
  if (out == null) return null;
  const lead = s.match(/^\s*/)[0], trail = s.match(/\s*$/)[0];
  return lead + out + trail;
}

function skip(el) {
  return !el || el.closest?.(EXCLUDE);
}

function skipAttrs(el) {
  return !el || (el.closest?.(EXCLUDE) && !el.matches?.("input, textarea"));
}

function translateTree(root) {
  if (root.nodeType === 3) return translateNode(root);
  if (root.nodeType !== 1 || skip(root)) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
    acceptNode: (n) => {
      if (n.nodeType !== 1 || !n.matches(EXCLUDE)) return NodeFilter.FILTER_ACCEPT;
      if (n.matches("input, textarea")) translateAttrs(n); // their placeholder is interface text, their value is not
      return NodeFilter.FILTER_REJECT;
    },
  });
  translateAttrs(root);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (n.nodeType === 3) translateNode(n);
    else translateAttrs(n);
  }
}

function translateNode(n) {
  if (skip(n.parentElement)) return;
  const done = originals.get(n);
  if (done != null && n.nodeValue !== done && translateText(done) === n.nodeValue) return; // already Arabic
  const ar = translateText(n.nodeValue);
  if (ar != null && ar !== n.nodeValue) {
    originals.set(n, n.nodeValue);
    n.nodeValue = ar;
  }
}

function translateAttrs(el) {
  for (const a of ATTRS) {
    const v = el.getAttribute?.(a);
    if (!v) continue;
    const ar = translateText(v);
    if (ar != null && ar !== v) {
      const o = attrOriginals.get(el) || {};
      o[a] = v;
      attrOriginals.set(el, o);
      el.setAttribute(a, ar);
    }
  }
}

function restoreTree(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
  for (let n = walker.currentNode; n; n = walker.nextNode()) {
    if (n.nodeType === 3) {
      const o = originals.get(n);
      if (o != null) { n.nodeValue = o; originals.delete(n); }
    } else {
      const o = attrOriginals.get(n);
      if (o) { for (const [a, v] of Object.entries(o)) n.setAttribute(a, v); attrOriginals.delete(n); }
    }
  }
}

let queue = new Set();
let scheduled = false;
function flush() {
  scheduled = false;
  const nodes = queue;
  queue = new Set();
  for (const n of nodes) if (n.isConnected) translateTree(n);
}

function startObserver() {
  if (observer) return;
  observer = new MutationObserver((records) => {
    for (const r of records) {
      const target = r.target.nodeType === 3 ? r.target.parentElement : r.target;
      if (r.type === "attributes") { if (!skipAttrs(target)) translateAttrs(target); continue; }
      if (skip(target)) continue; // streaming text in the conversation: nothing to do, and cheap to leave
      if (r.type === "characterData") queue.add(r.target);
      else for (const n of r.addedNodes) queue.add(n);
    }
    if (queue.size && !scheduled) { scheduled = true; queueMicrotask(flush); }
  });
  observer.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
}

function stopObserver() {
  observer?.disconnect();
  observer = null;
}

/** Apply a language ("en" | "ar") and a direction setting ("auto" | "ltr" | "rtl"), live. */
export function applyLanguage(language = "en", direction = "auto") {
  const root = document.documentElement;
  const dir = direction === "ltr" || direction === "rtl" ? direction : language === "ar" ? "rtl" : "ltr";
  root.lang = language === "ar" ? "ar" : "en";
  root.dir = dir;
  if (language === lang) return;
  lang = language;
  if (lang === "ar") {
    translateTree(document.body);
    startObserver();
  } else {
    stopObserver();
    restoreTree(document.body);
  }
}

export const currentLanguage = () => lang;
