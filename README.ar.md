<div align="center" dir="rtl">

<h2>💖 ادعم هذا المشروع المفتوح المصدر</h2>
<p>دعمك يساعدنا في صيانة الخوادم واستمرار تطوير التحديثات!</p>
<a href="https://paypal.me/np4abdou">
  <img src="https://img.shields.io/badge/Donate_with_PayPal-00457C?style=for-the-badge&logo=paypal&logoColor=white" alt="Donate with PayPal">
</a>
<br><br><br>

**AniNova — تطبيق بث أنمي للكمبيوتر مع ترجمات عربية**

<p align="center">
  <a href="https://github.com/nobynoooob/AniNova/stargazers">
    <img src="https://img.shields.io/github/stars/nobynoooob/AniNova?style=for-the-badge" />
  </a>
  <a href="https://github.com/nobynoooob/AniNova/network">
    <img src="https://img.shields.io/github/forks/nobynoooob/AniNova?style=for-the-badge" />
  </a>
  <br>
  <a href="https://github.com/nobynoooob/AniNova/releases">
    <img src="https://img.shields.io/github/v/release/nobynoooob/AniNova?style=for-the-badge" />
  </a>
  <a href="https://github.com/nobynoooob/AniNova/releases">
    <img src="https://img.shields.io/badge/Windows-Linux-blue?style=for-the-badge" />
  </a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/License-GPL--3.0-green?style=for-the-badge" />
</p>

<p>لاختيار اللغة الإنجليزية اضغط على الزر:</p>
<a href="README.md">
  <img src="https://img.shields.io/badge/Language-English-blue?style=for-the-badge&logo=google-translate&logoColor=white" alt="English">
</a>

<br>
<br>

</div>

---

<div dir="rtl">

## 📑 التنقل

[التثبيت](#-التثبيت) • [الميزات](#-الميزات) • [البدء](#-البدء) • [الإعدادات](#️-الإعدادات) • [البناء والنشر](#-البناء-والنشر) • [المساهمون](#-المساهمون) • [الرخصة](#-الرخصة)

---

## 📦 التثبيت

حمّل أحدث إصدار من [صفحة الإصدارات](https://github.com/nobynoooob/AniNova/releases):

| الملف | المنصة | ماذا يوجد بداخله |
|-------|----------|---------------|
| `AniNova-Linux` | لينكس | ملف تنفيذي واحد (بايثون + التطبيق مدمجين) |
| `AniNova-v<version>-Windows-Portable.zip` | ويندوز | مجلد محمول (exe + مكتبات + mpv مدمج) |

### المتطلبات

- **لينكس**: WebKit2GTK/GTK3 (الواجهة الخلفية لـ pywebview) و **mpv** أو **VLC**.
  الإصدار المبني على Ubuntu يستخدم WebKit2GTK 4.1 — على التوزيعات الأخرى ثبّت:
  `libwebkit2gtk-4.1-dev gir1.2-webkit2-4.1 python3-gi`
- **ويندوز**: WebView2 (مثبت مسبقاً على ويندوز 10/11). الإصدار المحمول **يضمّن mpv**، فلا حاجة لمشغل إضافي.
- **Playwright Chromium**: يُنزَّل تلقائياً عند أول بث (غير مضمّن — لإبقاء حجم التنزيل صغيراً).

### من المصدر (للتطوير)

</div>

```bash
git clone https://github.com/nobynoooob/AniNova.git
cd AniNova
pip install -r requirements.txt     # أو: pip install -e .
```

<div dir="rtl">

شغّله:

</div>

```bash
# لينكس (يفعّل بيئة افتراضية محلية تلقائياً إن وجدت)
./launch.sh

# ويندوز
launch.bat

# أو مباشرة:
python -m ani_cli_arabic.gui          # --debug لفتح أدوات المطور
ani-cli-ar-gui                        # بعد pip install
```

<div dir="rtl">

> **ملاحظة لينكس**: يحتاج pywebview إلى مجموعة GTK/WebKit2 —
> `sudo apt-get install libwebkit2gtk-4.1-dev gir1.2-webkit2-4.1 python3-gi python3-gi-cairo libgirepository-1.0-dev`.

---

## 🎯 الميزات

### البث والتشغيل
- **محرك موفّرين متعدد**: Miruro وHiAnime وAllAnime وAPI وMkissa وGogoAnime مترابطون مع عزل فشل لكل خطوة — المصدر الأول العامل يربح، ويمكنك أيضاً **اختيار موفّر محدد**.
- **المسار العربي**: مسار عربي مخصص عبر واجهة برمجة الأنمي مع **مسارات ترجمة عربية** واختيار الجودة (1080p/720p/480p/تلقائي).
- **التشغيل عبر mpv / VLC** مع خيارات تخزين مؤقت للاتصالات البطيئة.
- **حل البث يتم خارج واجهة المستخدم** مع مهلات زمنية محدودة وإمكانية الإلغاء (تمرر أحداث الإلغاء عبر قائمة المتصفح) — الواجهة لا تتجمد أبداً.

### الاكتشاف والتصفح
- **بحث** عبر العناوين الإنجليزية واليابانية بالإضافة إلى **البحث العربي**.
- **الرائج** و**جدول العرض**.
- **تفاصيل غنية**: ملخص، تقييمات، أغلفة (AniList)، وبيانات وصفية وقوائم حلقات لكل موفّر.

### المكتبة الشخصية
- **متابعة المشاهدة**: استكمل من حيث توقفت بالضبط (يُتتبع التقدم).
- **قائمتي (المرجعيات)**: احفظ الأنمي للوصول السريع.

### شاهد معاً 🎬
- أنشئ أو انضم إلى **غرفة** للمشاهدة المتزامنة مع أصدقائك.
- يختار كل مشارك **mpv أو VLC** (مقبس IPC فريد / مضيف rc لكل مشغل).
- يتحكم المضيف في التقديم/الإيقاف/التشغيل؛ تتم مزامنة الحالة عبر Supabase Realtime.

### التجربة
- **نافذة سطح مكتب PyWebView** (WebView2 أصلي على ويندوز / WebKit على لينكس) بواجهة غنية من صفحة واحدة.
- **أغلفة وفنون** لكل أنمي.
- **فحص تحديثات تلقائي**.
- **إحصائيات استخدام مجهولة** (يمكن إيقافها في الإعدادات).

---

## 🚀 البدء

1. **ابحث** عن أنمي (أو استخدم الرائج / جدول العرض في الشاشة الرئيسية).
2. افتح الأنمي لرؤية **الحلقات** عبر المزوّدين.
3. اختر حلقة — يحل AniNova البث تلقائياً (أو دعك تختار المزوّد).
4. اختر **الجودة** واضغط تشغيل — سيفتح mpv/VLC ويبدأ البث.
5. للترجمات العربية، استخدم علامة تبويب **العربي**.

---

## ⚙️ الإعدادات

يتم حفظ الإعدادات محلياً في `~/.ani-cli-arabic/database/config.json`.

- **الجودة الافتراضية** و**مشغل الوسائط** (mpv/VLC)
- **نسبة أبعاد MPV / خيارات المشغل**
- **التحليلات**: الاشتراك/إلغاء الاشتراك في إحصائيات الاستخدام المجهولة (مفعّلة افتراضياً)
- **فحص التحديثات**: تبديل إشعارات التحديث التلقائية

---

## 🔧 البناء والنشر (للمشرفين)

ابنِ الملف التنفيذي بسطح المكتب عبر `build_desktop.py`:

</div>

```bash
python build_desktop.py                         # ملف GUI تنفيذي واحد
python build_desktop.py --onedir --bundle-mpv --zip   # مجلد محمول + zip
python build_desktop.py --exclude-module unittest      # استثناءات إضافية
```

<div dir="rtl">

- تستخدم نسخ ويندوز **--onedir + --bundle-mpv** لإنتاج الرمز البريدي المحمول.
- **سائق** Playwright مضمّن (`--collect-all playwright`)، لكن متصفح **Chromium** غير مضمّن — يُنزَّل عند أول استخدام.
- تُبنى الإصدارات تلقائياً بواسطة `.github/workflows/build.yml` عند دفع وسوم `v*`.

---

## 👥 المساهمون

**المنشئ والمشرف:**
- [@nobynoooob](https://github.com/nobynoooob) - المنشئ والمشرف الرئيسي

تريد المساهمة؟ لا تتردد في فتح قضية أو تقديم طلب سحب!

---

## 📄 الرخصة

هذا المشروع مرخص بموجب **رخصة جنو العمومية الإصدار 3.0**.

يمكنك استخدام وتعديل وتوزيع هذا البرنامج بحرية تحت شروط رخصة GPL-3.0. راجع ملف [LICENSE](LICENSE) للنص القانوني الكامل.

**ببساطة:**
- ✅ استخدمه لأغراض شخصية أو تجارية
- ✅ عدّل الكود المصدري
- ✅ وزّعه على الآخرين
- ⚠️ أي تعديلات يجب أن تكون مفتوحة المصدر أيضاً تحت GPL-3.0
- ⚠️ قم بتضمين إشعار حقوق النشر الأصلي

</div>

---

<div align="center" dir="rtl">

### ⚠️ إشعار مهم

</div>

<div dir="rtl">

> [! CAUTION]
> **باستخدامك لهذا البرنامج أنت تفهم:**
>
> - يتم جمع إحصائيات استخدام مجهولة لشعار إحصائيات صفحة GitHub (يمكن تعطيلها في الإعدادات)
> - المشروع مرخص بموجب GPL-3.0 - راجع [LICENSE](LICENSE) للتفاصيل
> - نحن لا نستضيف أي محتوى؛ جميع البث من مصادر خارجية
> - هذه الأداة للاستخدام الشخصي والأغراض التعليمية فقط

---

<br>

صُنع بـ ❤️ من مجتمع الأنمي

[⭐ ضع نجمة لهذا المستودع](https://github.com/nobynoooob/AniNova) | [🐛 أبلغ عن الأخطاء](https://github.com/nobynoooob/AniNova/issues) | [💬 النقاشات](https://github.com/nobynoooob/AniNova/discussions)

</div>
