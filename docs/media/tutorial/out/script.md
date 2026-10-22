# ShipShape: From Zero to Self-Testing in 10 Minutes

Narration script, generated from scenes.yaml by make_tutorial.py. Voice: en-US-AndrewNeural. Tags: REAL OUTPUT / LIVE RECORDING = captured from the kit; ILLUSTRATION = explanatory slide; MOCK = feature not in the kit yet.

## What ShipShape is

**[00:00] ShipShape** (title)

- Welcome to ShipShape, your autonomous QA crew for Claude Code.
  - AR: أهلاً بك في ShipShape، فريق ضمان الجودة الآلي الخاص بك داخل Claude Code.
- In the next ten minutes we go from zero to an app that tests itself, with real output from a real run.
  - AR: خلال الدقائق العشر القادمة سننتقل من الصفر إلى تطبيق يختبر نفسه، بمخرجات حقيقية من تشغيل حقيقي.

**[00:13] A QA team you install as a plugin** (card, ILLUSTRATION)

- You give it a goal in plain words, like: signup works. ShipShape plans the checks and runs them.
  - AR: تعطيه هدفاً بكلمات بسيطة، مثل: التسجيل يعمل. ويقوم ShipShape بتخطيط الفحوصات وتشغيلها.
- It reviews the code and its security first, then runs every test twice, records it on video, and narrates it.
  - AR: يراجع الكود وأمانه أولاً، ثم يشغّل كل اختبار مرتين، ويسجّله بالفيديو مع تعليق صوتي.
- A load test and a live regression follow, and a refuter tries to prove every failure wrong before anyone files a bug.
  - AR: بعد ذلك يأتي اختبار الحمل واختبار الانحدار، ثم يحاول المُفنِّد إثبات خطأ كل فشل قبل أن يُسجَّل أي خطأ.

**[00:37] Built-in guard rails** (card, ILLUSTRATION)

- It is also careful. It only touches allow-listed local or staging hosts, uses test data, never pays, and sends nothing until you say send.
  - AR: وهو حريص أيضاً: لا يعمل إلا على خوادم محلية أو تجريبية مسموح بها، ويستخدم بيانات اختبار فقط، ولا يدفع أبداً، ولا يرسل شيئاً حتى تقول: أرسل.
- Everything in this video runs against a small local demo shop with fake data.
  - AR: كل ما في هذا الفيديو يعمل على متجر تجريبي محلي صغير ببيانات وهمية.

## Install

**[00:54] Add the marketplace, install the plugin** (terminal, REAL OUTPUT)

- Installing takes two commands. First add the ShipShape marketplace, then install the plugin from it.
  - AR: التثبيت يحتاج أمرين فقط: أولاً أضف متجر ShipShape، ثم ثبّت الإضافة منه.
- Inside Claude Code you can type the same thing as slash plugin commands. Here the plugin list shows it installed and enabled.
  - AR: داخل Claude Code يمكنك كتابة نفس الأوامر كأوامر plugin. وهنا تُظهر القائمة أن الإضافة مثبتة ومفعّلة.
- On a fresh machine, the install script in the bin folder sets up Python packages and the Playwright browser for you.
  - AR: وعلى جهاز جديد، يقوم سكربت التثبيت في مجلد bin بإعداد حزم Python ومتصفح Playwright نيابةً عنك.

## Doctor

**[01:17] Is everything the crew needs installed?** (terminal, REAL OUTPUT)

- Next, run the doctor. It checks Python, Node, ffmpeg, the Playwright browser, the pinned browser tools, and the narration voice.
  - AR: بعد ذلك شغّل أداة الفحص doctor. فهي تتحقق من Python وNode وffmpeg ومتصفح Playwright وأدوات المتصفح المثبتة وصوت التعليق.
- Optional extras, like desktop control or a heavier load engine, are marked optional, with the fix for each.
  - AR: الإضافات الاختيارية، مثل التحكم في سطح المكتب أو محرك حمل أثقل، تظهر كاختيارية مع طريقة إصلاح كل منها.
- Channel secrets are only checked by name. Their values are never printed.
  - AR: أما مفاتيح قنوات الإرسال فيُتحقق منها بالاسم فقط، ولا تُطبع قيمها أبداً.

## /qa-goal on the example app

**[01:41] One goal, the whole crew** (card, ILLUSTRATION)

- Now the main event. In Claude Code, type /qa-goal, followed by what should work. Here: signup to welcome works on the demo shop.
  - AR: والآن الحدث الرئيسي. في Claude Code اكتب الأمر qa-goal متبوعاً بما يجب أن يعمل، وهنا: التسجيل حتى صفحة الترحيب يعمل في المتجر التجريبي.
- The QA lead agent drives seven steps, and hands the judgement calls to specialist agents.
  - AR: يقود وكيل قائد الجودة سبع خطوات، ويُسند القرارات التي تحتاج تقديراً إلى وكلاء متخصصين.

**[01:58] The local demo shop (fake data)** (image, LIVE RECORDING)

- This is the example app that ships with the kit: a tiny sign-up page on localhost. Everything on it is fake.
  - AR: هذا هو التطبيق التجريبي المرفق مع الحزمة: صفحة تسجيل صغيرة على الجهاز المحلي، وكل ما فيها وهمي.

**[02:06] History, ledger, then code and security review** (terminal, REAL OUTPUT)

- Step one reads earlier runs, so it knows the baseline and any flaky cases. Step two opens a ledger, which makes the whole run resumable.
  - AR: الخطوة الأولى تقرأ التشغيلات السابقة لتعرف خط الأساس والحالات غير المستقرة. والخطوة الثانية تفتح سجلاً يجعل التشغيل كله قابلاً للاستئناف.
- Step three is the review. The code reviewer reads the diff before any test runs, and the security pass sweeps for secrets and checks headers on the allow-listed host.
  - AR: الخطوة الثالثة هي المراجعة: يقرأ مراجع الكود التغييرات قبل أي اختبار، ويبحث فحص الأمان عن الأسرار المكشوفة ويتحقق من الترويسات على الخادم المسموح به.
- Security findings stay private. Only the count leaves this folder.
  - AR: نتائج الأمان تبقى خاصة، ولا يخرج من هذا المجلد إلا عددها.

**[02:33] Specialist agents in the kit** (terminal, REAL OUTPUT)

- Each role is a plain agent file you can read and change: the code reviewer, the security reviewer, the automation tester, and the refuter.
  - AR: كل دور هو ملف وكيل بسيط يمكنك قراءته وتعديله: مراجع الكود، ومراجع الأمان، ومختبِر الأتمتة، والمُفنِّد.
- A workflow file runs them in order, with the review and the security pass side by side.
  - AR: ويشغّلهم ملف سير عمل بالترتيب، مع تشغيل المراجعة وفحص الأمان جنباً إلى جنب.

**[02:49] Every plan runs twice** (terminal, REAL OUTPUT)

- Step four runs every test plan twice, as two independent passes. A result only counts if both passes agree. If they disagree, the case is marked flaky.
  - AR: الخطوة الرابعة تشغّل كل خطة اختبار مرتين كتمريرتين مستقلتين. ولا تُحتسب النتيجة إلا إذا اتفقت التمريرتان، وإن اختلفتا تُعلَّم الحالة بأنها غير مستقرة.
- Here, four checks pass, and one is blocked on purpose: the never-pay rule stopped the run at the Pay now button and asked for a human.
  - AR: هنا نجحت أربعة فحوصات، وتوقف واحد عن قصد: قاعدة عدم الدفع أوقفت التشغيل عند زر الدفع وطلبت تدخل إنسان.

**[03:10] The recorded pass: signup plan** (video, LIVE RECORDING)

- Every pass is recorded in a real browser. This is pass one of the signup plan.
  - AR: كل تمريرة تُسجَّل في متصفح حقيقي، وهذه التمريرة الأولى لخطة التسجيل.
- First it submits the form empty and expects a clear error. Then it fills in a test user with an example address and expects the welcome message.
  - AR: أولاً يرسل النموذج فارغاً ويتوقع رسالة خطأ واضحة، ثم يملأ بيانات مستخدم تجريبي بعنوان بريد مثالي ويتوقع رسالة الترحيب.
- Screenshots, a Playwright trace, console errors and failed network calls are all saved as evidence.
  - AR: وتُحفظ لقطات الشاشة وملف تتبع Playwright وأخطاء وحدة التحكم وطلبات الشبكة الفاشلة كلها كأدلة.

**[03:33] Load test on the allow-listed host** (terminal, REAL OUTPUT)

- Step five is the load test. The smoke profile sent forty four requests, with a p95 of about sixty seven milliseconds and zero errors.
  - AR: الخطوة الخامسة هي اختبار الحمل. أرسل ملف الاختبار السريع أربعة وأربعين طلباً، بزمن استجابة p95 حوالي سبعة وستين جزءاً من الثانية وبدون أخطاء.
- Ramp, soak and spike profiles are there too, and anything that looks like production is refused unless the owner allows it.
  - AR: وتتوفر أيضاً ملفات التصاعد والتحمل الطويل والذروة المفاجئة، وأي خادم يبدو كبيئة إنتاج يُرفض ما لم يسمح المالك بذلك.

**[03:53] Narrated regression video, made by the kit** (video, LIVE RECORDING)

- The live regression recorder replays your regression list as a real user, read-only on staging or live. Here is the narrated video the kit produced itself.
  - AR: يعيد مسجّل الانحدار تشغيل قائمة الاختبارات كمستخدم حقيقي، للقراءة فقط على بيئة التجربة أو الإنتاج. وهذا هو الفيديو المروي الذي أنتجته الحزمة بنفسها.

**[04:35] A failure pauses the loop: verify, then refute** (terminal, REAL OUTPUT)

- Now a failure. A second plan expects a returning user to see: welcome back. Both passes fail, so the loop pauses and asks for verify and refute.
  - AR: والآن حالة فشل: خطة ثانية تتوقع أن يرى المستخدم العائد عبارة: مرحباً بعودتك. فشلت التمريرتان، فتوقفت الحلقة وطلبت التحقق والتفنيد.

**[04:46] The refuter tries to kill the claim** (terminal, REAL OUTPUT)

- The refuter is the second agent of a two-agent bar. It works on its own path and tries hard to prove the failure wrong.
  - AR: المُفنِّد هو الوكيل الثاني في قاعدة الوكيلَين. يعمل بطريقته المستقلة ويحاول بجدية إثبات أن هذا الفشل خاطئ.
- Its verdict: refuted. Neither the app nor the original plan ever promised welcome back. The test expectation was wrong, not the product.
  - AR: وحكمه: مرفوض. فلا التطبيق ولا الخطة الأصلية وعدا بعبارة مرحباً بعودتك، أي أن توقع الاختبار هو الخاطئ وليس المنتج.
- So no bug is filed, and the ledger shows zero open bugs. That is how ShipShape keeps false alarms out of your tracker.
  - AR: لذلك لا يُسجَّل أي خطأ، ويُظهر السجل صفر أخطاء مفتوحة. هكذا يُبعد ShipShape الإنذارات الكاذبة عن نظام تتبع المهام لديك.

## The local HTML report

**[05:12] report.html: one file, works offline** (scroll, REAL OUTPUT)

- Step six writes one self-contained HTML report. It opens offline, so you can attach it anywhere.
  - AR: الخطوة السادسة تكتب تقريراً واحداً بصيغة HTML مكتفياً بذاته، يفتح دون اتصال بالإنترنت، فيمكنك إرفاقه في أي مكان.
- At the top, the verdict and the counts: four pass, zero fail, one blocked. Then every case with its evidence, and the videos you can play in place.
  - AR: في الأعلى الحكم والأرقام: أربعة نجاح، صفر فشل، وواحد متوقف. ثم كل حالة مع دليلها، والفيديوهات التي يمكن تشغيلها مباشرة.
- Further down: console and network checks, the load chart, bugs that survived the refuter, open human gates, and the trend across runs.
  - AR: وفي الأسفل: فحوصات وحدة التحكم والشبكة، ومخطط الحمل، والأخطاء التي صمدت أمام المُفنِّد، والبوابات البشرية المفتوحة، والاتجاه عبر التشغيلات.
- There is also a spoken summary, so a non-technical owner can just listen to the result.
  - AR: وهناك أيضاً ملخص صوتي، حتى يستطيع المالك غير التقني أن يستمع إلى النتيجة فقط.

## Auto-delivery dry run

**[05:48] Telegram and WhatsApp, dry-run by default** (terminal, REAL OUTPUT)

- Step seven is delivery to Telegram, WhatsApp, Slack, email or a webhook, whatever your config lists.
  - AR: الخطوة السابعة هي الإرسال إلى تيليجرام أو واتساب أو سلاك أو البريد أو webhook، حسب ما يحدده ملف الإعدادات.
- First a privacy scan of everything that would leave: zero findings. Then a dry run that prints exactly what would be sent, with the tokens left out.
  - AR: أولاً فحص خصوصية لكل ما سيخرج: لا توجد ملاحظات. ثم تشغيل تجريبي يطبع بالضبط ما سيُرسل، مع إخفاء المفاتيح.
- Nothing leaves the machine until the owner says send, and a channel that is not in the config is refused.
  - AR: لا يخرج شيء من الجهاز حتى يقول المالك: أرسل، وأي قناة غير موجودة في الإعدادات تُرفض.

## A plain-language hook blocks an unsafe action

**[06:14] Rules written in plain language** (terminal, REAL OUTPUT)

- The guard rails are not just advice. The plugin ships hooks that Claude Code runs before risky tools, and most of them are written in plain language.
  - AR: قواعد الحماية ليست مجرد نصائح. فالإضافة تأتي بخطافات يشغّلها Claude Code قبل الأدوات الخطرة، ومعظمها مكتوب بلغة بسيطة.
- For example: block a git push that force-pushes, or pushes to main or production.
  - AR: مثلاً: امنع أي git push يدفع بالقوة، أو يدفع إلى main أو إلى بيئة الإنتاج.

**[06:31] Claude tries a force push to main** (terminal, REAL OUTPUT)

- Here we asked Claude, with the plugin loaded, to force-push to main in a throwaway repo. The hook blocked it before git was even called.
  - AR: هنا طلبنا من Claude، والإضافة محمّلة، أن يدفع بالقوة إلى main في مستودع تجريبي. فمنعه الخطاف قبل أن يُستدعى git أصلاً.
- A second, deterministic hook scans every commit. A fake bot token was staged by mistake, so the commit is blocked, and only the kind and line are shown, never the value.
  - AR: وهناك خطاف ثانٍ ثابت يفحص كل commit. أُضيف مفتاح بوت وهمي بالخطأ، فمُنع الـ commit، ولا يظهر إلا نوع المشكلة ورقم السطر، وليس القيمة أبداً.

## Desktop control (gated)

**[06:52] Outside the browser, behind gates** (terminal, REAL OUTPUT)

- Some flows live outside the browser: native apps, file pickers, OS dialogs. ShipShape can drive the desktop too, but only behind gates.
  - AR: بعض المسارات تكون خارج المتصفح: تطبيقات أصلية، ونوافذ اختيار الملفات، ونوافذ النظام. ويستطيع ShipShape التحكم في سطح المكتب أيضاً، لكن خلف بوابات حماية فقط.
- With desktop control off in the config, the first step is refused. Turned on, only allow-listed apps run, and the delete step stops and asks the user first.
  - AR: عندما يكون التحكم معطلاً في الإعدادات تُرفض الخطوة الأولى. وعند تفعيله لا تعمل إلا التطبيقات المسموح بها، وخطوة الحذف تتوقف وتسأل المستخدم أولاً.
- Banking, payment and password apps are always refused, and every action is logged. These are dry runs, so nothing on this desktop was touched.
  - AR: وتطبيقات البنوك والدفع وكلمات المرور مرفوضة دائماً، وكل إجراء يُسجَّل. وهذه تشغيلات تجريبية، فلم يُلمس أي شيء على سطح المكتب.

## /timesheet

**[07:25] Real hours from Claude Code logs** (terminal, REAL OUTPUT)

- The kit is not only QA. /timesheet measures real working hours from Claude Code session logs, merging sub-agents so parallel work counts once.
  - AR: الحزمة ليست لضمان الجودة فقط. فأمر timesheet يقيس ساعات العمل الفعلية من سجلات جلسات Claude Code، ويدمج الوكلاء الفرعيين حتى يُحتسب العمل المتوازي مرة واحدة.
- Idle gaps are cut, blocks are mapped to tasks, and you get an Excel sheet plus Odoo import rows. This run uses synthetic logs.
  - AR: تُحذف فترات الخمول، وتُربط فترات العمل بالمهام، وتحصل على ملف Excel وصفوف جاهزة للاستيراد إلى Odoo. وهذا التشغيل يستخدم سجلات مصطنعة.
- It never writes to Odoo by itself. A human reviews the file first.
  - AR: ولا يكتب في Odoo من تلقاء نفسه أبداً، بل يراجع إنسان الملف أولاً.

## /odoo-check

**[07:52] Pre-deploy checks for an Odoo module** (terminal, REAL OUTPUT)

- /odoo-check runs pre-deploy checks on an Odoo module. This fake loyalty module has four problems.
  - AR: أمر odoo-check يشغّل فحوصات ما قبل النشر على وحدة Odoo. وهذه الوحدة الوهمية لنقاط الولاء فيها أربع مشكلات.
- A cron outside a no-update block, no neutralize script, a raw commit inside a model, and no tests. Each one is a classic way to break production.
  - AR: مهمة مجدولة خارج كتلة عدم التحديث، ولا يوجد سكربت تحييد، واستدعاء commit مباشر داخل النموذج، ولا توجد اختبارات. وكل واحدة منها طريقة معروفة لكسر بيئة الإنتاج.
- The Odoo expert agent then explains each fix before the deploy.
  - AR: ثم يشرح وكيل خبير Odoo طريقة إصلاح كل منها قبل النشر.

## Where to get help

**[08:15] Next steps** (card, ILLUSTRATION)

- When you get stuck, run the doctor first. It prints the fix for anything missing.
  - AR: إذا واجهتك مشكلة، شغّل أداة الفحص doctor أولاً، فهي تطبع طريقة إصلاح أي شيء ناقص.
- The README and the docs folder cover every command, and you can simply ask Claude how to use any of them.
  - AR: ويشرح ملف README ومجلد docs كل الأوامر، ويمكنك ببساطة أن تسأل Claude عن طريقة استخدام أي منها.
- For questions or bugs, open an issue on the repository. Thanks for watching, and happy shipping.
  - AR: وللأسئلة أو الأخطاء، افتح issue في المستودع. شكراً للمشاهدة، ونتمنى لك إطلاقاً موفقاً.

## Teaser (60 s)

- Meet ShipShape: an autonomous QA crew that lives in Claude Code.
- Give it a goal. It reviews your code and security, then runs every test twice in a real browser, on video.
- A refuter attacks every failure, so false alarms never become bugs.
- You get one offline report with load results, evidence and trends, delivered to Telegram or WhatsApp only when you say send.
- Plain-language hooks block unsafe moves, like a force push to main.
- Install it in two commands, and watch the full ten minute tutorial to go from zero to self-testing.

_Narration words (tutorial): 1161_
