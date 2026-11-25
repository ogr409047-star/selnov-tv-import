#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
tv_import.py — импорт ТВ-программы на полосу газеты в InDesign 2024.

Что делает:
  1. Разбирает текстовый файл программы (день -> канал -> передачи).
  2. Пересобирает 7 текстовых колонок полосы ТВ-программы.
  3. Размечает шрифты: весь текст OctavaC Regular 7/7,
     названия каналов (ПЕРВЫЙ, РОССИЯ 1, НТВ, ТВЦ, СЕЙМ) — Bold 7/7.
  4. Ставит пустой абзац-разделитель перед РОССИЯ 1, НТВ, ТВЦ, СЕЙМ.
  5. Обновляет метки дней, даты и заголовок полосы.
  6. Делает резервную копию файла макета.
  7. Проверяет результат и печатает отчёт.

Запуск:
    python tv_import.py ПРОГРАММА.txt --monday 2026-10-19

Обязательные/важные ключи:
    ПРОГРАММА.txt        файл с программой (не изменяется)
    --monday ГГГГ-ММ-ДД  понедельник недели программы; можно --monday auto,
                         тогда дата берётся из имени файла

Ключи:
    --indd ПУТЬ          файл макета (по умолчанию Programs.indd рядом со скриптом)
    --dry-run            только показать план, макет не трогать
    --quiet              без подробного отчёта

Требования: Python 3, Node.js, InDesign 2024, модуль winax.
"""

import argparse
import datetime
import io
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from collections import OrderedDict

# --------------------------------------------------------------------------- #
# Настройки
# --------------------------------------------------------------------------- #

CHANNELS = ["ПЕРВЫЙ", "РОССИЯ 1", "НТВ", "ТВЦ", "СЕЙМ"]
WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг",
            "Пятница", "Суббота", "Воскресенье"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]
PROGRAM_RE = re.compile(r"^\d{1,2}[.:]\d{2}")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# папка проекта с оригиналом макета и файлами программ
SOURCE_DIR = r"D:\instal\Progect2026\8_Programs"
FALLBACK_INDD = os.path.join(SOURCE_DIR, "Programs.indd")
RUNNER_JS = os.path.join(BASE_DIR, "_winax_runner.js")
WORK_DIR = os.path.join(BASE_DIR, "_work")

FONT_SIZE = 7
FONT_LEADING = 7


def find_winax():
    """Ищет модуль winax рядом с indesign-cli."""
    cands = []
    for env in ("LOCALAPPDATA", "APPDATA", "USERPROFILE"):
        root = os.environ.get(env)
        if not root:
            continue
        cands.append(os.path.join(
            root, "AppData", "Local", "Programs", "Python", "Python313",
            "Lib", "site-packages", "cli_anything", "indesign",
            "server", "node_modules", "winax"))
        cands.append(os.path.join(
            root, "AppData", "Local", "Python", "Python313",
            "site-packages", "cli_anything", "indesign",
            "server", "node_modules", "winax"))
    for c in cands:
        if os.path.isdir(c):
            return c
    return None


# --------------------------------------------------------------------------- #
# Разбор файла программы
# --------------------------------------------------------------------------- #

def parse_program(path):
    """Возвращает OrderedDict: день недели -> [(канал, [передачи]), ...]"""
    days = OrderedDict()
    cur_day = None
    cur_ch = None

    with io.open(path, encoding="utf-8") as fh:
        for raw in fh:
            s = raw.strip()
            if not s or set(s) <= set("=-_ "):
                continue
            if PROGRAM_RE.match(s):
                if cur_ch is None:
                    continue
                cur_ch[2].append(s)
                continue
            if s in CHANNELS:
                if cur_day not in days:
                    days[cur_day] = []
                cur_ch = [s, cur_day, []]
                days[cur_day].append(cur_ch)
            else:
                cur_day = s

    return days


def validate(days):
    """Проверяет, что в файле ровно 7 дней и по 5 каналов."""
    problems = []
    if len(days) != 7:
        problems.append("найдено дней: %d (ожидается 7)" % len(days))
    for d, chs in days.items():
        if len(chs) != 5:
            problems.append("день «%s»: каналов %d (ожидается 5)" % (d, len(chs)))
    return problems


# --------------------------------------------------------------------------- #
# Даты недели
# --------------------------------------------------------------------------- #

def guess_monday_from_name(path):
    """Ищет дату в имени файла: 13102027 -> 13.10.2027 и т.п."""
    stem = os.path.splitext(os.path.basename(path))[0]
    digits = re.sub(r"\D", "", stem)
    for n in (8, 6, 4):
        if len(digits) >= n:
            chunk = digits[:n]
            if n == 8:
                d, m, y = int(chunk[0:2]), int(chunk[2:4]), int(chunk[4:8])
            elif n == 6:
                d, m, y = int(chunk[0:2]), int(chunk[2:4]), 2000 + int(chunk[4:6])
            else:
                d, m, y = int(chunk[0:2]), int(chunk[2:4]), 2000 + int(chunk[0:0] or 26)
            try:
                return datetime.date(y, m, d)
            except ValueError:
                pass
    return None


def monday_of(d):
    return d - datetime.timedelta(days=d.weekday())


def date_labels(monday):
    """Возвращает [(день недели, дата прописью), ...] на 7 дней."""
    out = []
    for i, wd in enumerate(WEEKDAYS):
        dt = monday + datetime.timedelta(days=i)
        out.append((wd, "%d %s" % (dt.day, MONTHS_GEN[dt.month - 1])))
    return out


def date_range_title(monday):
    a = monday
    b = monday + datetime.timedelta(days=6)
    return "ТВ ПРОГРАММА с %d %s по %d %s" % (
        a.day, MONTHS_GEN[a.month - 1], b.day, MONTHS_GEN[b.month - 1])


MONTHS_NOM = ["января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def issue_line(day, number=None, run_number=None, original=""):
    """Собирает строку шапки: '14 октября 2026 г. №42 (7897)'.

    Номер выпуска и номер тиража сохраняются из исходной строки,
    если их не задали явно.
    """
    base = "%d %s %d г." % (day.day, MONTHS_NOM[day.month - 1], day.year)

    if number is None:
        m = re.search(r"№\s*(\d+)", original)
        number = m.group(1) if m else None
    if number:
        base += " №%s" % number

    if run_number is None:
        m = re.search(r"\(([^)]*)\)", original)
        run_number = m.group(1) if m else None
    if run_number:
        base += " (%s)" % run_number

    return base


# --------------------------------------------------------------------------- #
# Генерация ExtendScript
# --------------------------------------------------------------------------- #

def js_str(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def build_jsx(days, labels, title, indd_path, report_path, issue_date=None,
              issue_number=None, run_number=None):
    L = []
    a = L.append

    a("(function(){")
    a("var log=[];")
    a("function mm(v){ return v/72*25.4; }")
    a("var CHN=[%s];" % ",".join("'" + c + "'" for c in CHANNELS))
    a("function isChan(s){ for (var q=0;q<CHN.length;q++){ if (CHN[q]===s) return true; } return false; }")
    a("var doc=null;")
    a("for (var i=0;i<app.documents.length;i++){ if (String(app.documents[i].name)=='%s') doc=app.documents[i]; }" % js_str(indd_name(indd_path)))
    a("if (!doc){")
    a("  try{ doc=app.open(new File('%s')); log.push('открыт: '+doc.name); }" % indd_path.replace("\\", "\\\\"))
    a("  catch(e){ log.push('ОШИБКА открытия: '+e.message); fin(); return; }")
    a("}")
    a("var items=doc.pages[0].allPageItems;")
    a("")
    a("// ---- найти колонки ТВ по геометрии ----")
    a("function getCols(){")
    a("  var cs=[];")
    a("  for (var i=0;i<items.length;i++){")
    a("    var it=items[i];")
    a("    if (it.constructor.name!='TextFrame') continue;")
    a("    var g=null; try{ g=it.geometricBounds; }catch(e){ continue; }")
    a("    var w=mm(g[3]-g[1]), yt=mm(g[0]), yb=mm(g[2]);")
    a("    if (w<10||w>15) continue; if (yt<15||yt>18) continue; if (yb<130||yb>150) continue;")
    a("    cs.push({left:g[1], it:it});")
    a("  }")
    a("  cs.sort(function(a,b){ return a.left-b.left; });")
    a("  return cs;")
    a("}")
    a("var cols=getCols();")
    a("log.push('колонок найдено: '+cols.length);")
    a("if (cols.length!==7){ log.push('СТОП: колонок '+cols.length+' вместо 7'); fin(); return; }")
    a("")

    # ---- содержимое колонок ----
    day_names = list(days.keys())
    for c, day in enumerate(day_names):
        a("/* ===== колонка %d: %s ===== */" % (c, day))
        a("(function(){")
        a("  var tf=cols[%d].it;" % c)
        a("  var lines=[];")
        for k, (name, _d, progs) in enumerate(days[day]):
            if k > 0:
                a("  lines.push('');")
            a("  lines.push('%s');" % js_str(name))
            for pr in progs:
                a("  lines.push('%s');" % js_str(pr))
        a("  tf.contents=lines.join('\\r');")
        a("})();")

    # ---- итеративная разметка шрифтов ----
    a("")
    a("// ---- разметка шрифтов (несколько проходов: текст может 'доезжать') ----")
    a("for (var pass=1; pass<=5; pass++){")
    a("  var cols=getCols(); var fixed=0;")
    a("  for (var c=0;c<cols.length;c++){")
    a("    var tf=cols[c].it; var n=tf.paragraphs.length;")
    a("    for (var p=0;p<n;p++){")
    a("      var pa=tf.paragraphs[p];")
    a("      var tx=''; try{ tx=String(pa.contents); }catch(e){}")
    a("      tx=tx.replace(/[\\r\\n]+/g,'').replace(/^\\s+|\\s+$/g,'');")
    a("      var want=isChan(tx)?'Bold':'Regular';")
    a("      var have=''; try{ have=String(pa.fontStyle); }catch(e){}")
    a("      pa.pointSize=%d; pa.leading=%d;" % (FONT_SIZE, FONT_LEADING))
    a("      try{ pa.paragraphAttributes.justification=Justification.LEFT_ALIGN; }catch(e){}")
    a("      if (have!==want){ try{ pa.fontStyle=want; fixed++; }catch(e){} }")
    a("    }")
    a("  }")
    a("  log.push('разметка, проход '+pass+': исправлено '+fixed);")
    a("  if (fixed===0) break;")
    a("}")
    a("")

    # ---- даты, дни недели, заголовок ----
    a("// ---- метки дней, даты и заголовок ----")
    a("(function(){")
    a("  var dayF=[], dateF=[], titleF=[];")
    a("  for (var i=0;i<items.length;i++){")
    a("    var it=items[i];")
    a("    if (it.constructor.name!='TextFrame') continue;")
    a("    var t=''; try{ t=String(it.contents); }catch(e){ continue; }")
    a("    t=t.replace(/[\\r\\n\\t]+/g,' ').replace(/\\s+/g,' ');")
    a("    t=t.replace(/^\\s+|\\s+$/g,'');")
    a("    if (!t) continue;")
    a("    var g=null; try{ g=it.geometricBounds; }catch(e){ continue; }")
    a("    if (mm(g[0])>20) continue;")
    a("    if (t.indexOf('ТВ ПРОГРАММА')===0) titleF.push(it);")
    a("    else if (/^[0-9]{1,2} [^ ]+$/.test(t)) dateF.push({left:g[1], it:it});")
    a("    else if (/^(понедельник|вторник|среда|четверг|пятница|суббота|воскресенье)$/i.test(t)) dayF.push({left:g[1], it:it});")
    a("  }")
    a("  dateF.sort(function(a,b){ return a.left-b.left; });")
    a("  dayF.sort(function(a,b){ return a.left-b.left; });")
    a("  log.push('найдено меток: дат='+dateF.length+', дней='+dayF.length+', заголовков='+titleF.length);")
    a("  if (dateF.length===7){")
    for i, (wd, dl) in enumerate(labels):
        a("    try{ dateF[%d].it.contents='%s'; }catch(e){}" % (i, js_str(dl)))
    a("  } else log.push('  ВНИМАНИЕ: меток дат '+dateF.length);")
    a("  if (dayF.length===7){")
    for i, (wd, dl) in enumerate(labels):
        a("    try{ dayF[%d].it.contents='%s'; }catch(e){}" % (i, js_str(wd)))
    a("  } else log.push('  ВНИМАНИЕ: меток дней '+dayF.length);")
    a("  for (var q=0;q<titleF.length;q++){ try{ titleF[q].contents='%s'; }catch(e){} }" % js_str(title))
    a("})();")

    # ---- шапка полосы на мастере (дата и номер выпуска) ----
    if issue_date is not None:
        a("")
        a("// ---- шапка полосы: дата и номер выпуска ----")
        a("(function(){")
        a("  var DAY=%d, MON=%d, YR=%d;" % (issue_date.day, issue_date.month, issue_date.year))
        a("  var NUM=%s, RUN=%s;" % (
            ("'" + js_str(str(issue_number)) + "'") if issue_number is not None else "null",
            ("'" + js_str(str(run_number)) + "'") if run_number is not None else "null"))
        a("  var MONN=['января','февраля','марта','апреля','мая','июня',"
          "'июля','августа','сентября','октября','ноября','декабря'];")
        a("  var hit=0;")
        a("  for (var m=0;m<doc.masterSpreads.length;m++){")
        a("    var ms=doc.masterSpreads[m];")
        a("    for (var p=0;p<ms.pages.length;p++){")
        a("      var all=ms.pages[p].allPageItems;")
        a("      for (var i=0;i<all.length;i++){")
        a("        var it=all[i];")
        a("        if (it.constructor.name!='TextFrame') continue;")
        a("        var t=''; try{ t=String(it.contents); }catch(e){ continue; }")
        a("        t=t.replace(/[\\r\\n]+/g,' ').replace(/\\s+/g,' ');")
        a("        t=t.replace(/^\\s+|\\s+$/g,'');")
        a("        if (!/^[0-9]{1,2} [^ ]+ [0-9]{4}/.test(t)) continue;")
        a("        var nv=DAY + ' ' + MONN[MON-1] + ' ' + YR + ' г.';")
        a("        var m1=/№\\s*([0-9]+)/.exec(t);")
        a("        var nNum = NUM ? NUM : (m1 ? m1[1] : null);")
        a("        if (nNum) nv += ' №' + nNum;")
        a("        var m2=/\\(([^)]*)\\)/.exec(t);")
        a("        var nRun = RUN ? RUN : (m2 ? m2[1] : null);")
        a("        if (nRun) nv += ' (' + nRun + ')';")
        a("        if (t!==nv){ try{ it.contents=nv; log.push('  шапка: ' + t + ' -> ' + nv); hit++; }catch(e){} }")
        a("        else log.push('  шапка уже верна: ' + nv);")
        a("      }")
        a("    }")
        a("  }")
        a("  if (hit===0) log.push('  ВНИМАНИЕ: строки шапки с датой выпуска не найдены на мастере');")
        a("})();")
    a("")

    # ---- сохранение ----
    a("try{ doc.save(); log.push('СОХРАНЕНО: '+doc.name); }catch(e){ log.push('ОШИБКА сохранения: '+e.message); }")

    # ---- отчёт о фактическом состоянии ----
    a("")
    a("// ---- отчёт о фактическом содержимом ----")
    a("var rep=[];")
    a("var cols2=getCols();")
    a("var totB=0, totR=0, totE=0, bad=0;")
    a("for (var c2=0;c2<cols2.length;c2++){")
    a("  var tf=cols2[c2].it; var n=tf.paragraphs.length;")
    a("  rep.push('##COL\\t'+c2);")
    a("  for (var p2=0;p2<n;p2++){")
    a("    var pa=tf.paragraphs[p2];")
    a("    var tx=''; try{ tx=String(pa.contents); }catch(e){}")
    a("    tx=tx.replace(/[\\r\\n]+/g,'');")
    a("    var fs=''; try{ fs=String(pa.fontStyle); }catch(e){}")
    a("    rep.push('##L\\t'+tx+'\\t'+fs);")
    a("    var clean=tx.replace(/^\\s+|\\s+$/g,'');")
    a("    if (clean==='') { totE++; continue; }")
    a("    if (isChan(clean)){ totB++; if(fs!=='Bold') bad++; }")
    a("    else { totR++; if(fs!=='Regular') bad++; }")
    a("  }")
    a("}")
    a("rep.push('##SUM\\tbold='+totB+'\\treg='+totR+'\\tempty='+totE+'\\tbad='+bad);")
    a("var rf=new File('%s');" % report_path.replace("\\", "/"))
    a("rf.encoding='UTF-8'; rf.open('w'); rf.write(rep.join('\\n')); rf.close();")
    a("log.push('отчёт записан: bold='+totB+' reg='+totR+' empty='+totE+' bad='+bad);")
    a("")
    a("function fin(){ var f=new File('%s');" % os.path.join(WORK_DIR, "run_log.txt").replace("\\", "/"))
    a("  f.encoding='UTF-8'; f.open('w'); f.write(log.join('\\n')); f.close(); }")
    a("fin();")
    a("})();")

    return "\n".join(L)


def indd_name(path):
    return os.path.basename(path)


# --------------------------------------------------------------------------- #
# Запуск в InDesign
# --------------------------------------------------------------------------- #

def cleanup_backups(keep=5, folder=None):
    """Оставляет `keep` последних автоматических резервных копий.

    Ручную копию Programs_РЕЗЕРВ_ДО_ЗАМЕНЫ.indd не трогает.
    Резервы хранятся рядом с макетом, а не рядом с инструментом.
    """
    import glob
    folder = folder or BASE_DIR
    pat = os.path.join(folder, "Programs_резерв_20*.indd")
    files = sorted(glob.glob(pat))
    if len(files) <= keep:
        return 0
    removed = 0
    for f in files[:len(files) - keep]:
        try:
            os.remove(f)
            removed += 1
        except OSError:
            pass
    if removed:
        print("УДАЛЕНО старых резервных копий: %d (оставлено %d)" % (removed, keep))
    return removed


def indesign_running():
    """Проверяет, запущен ли уже InDesign."""
    try:
        res = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq InDesign.exe", "/NH"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace")
        return "InDesign.exe" in (res.stdout or "")
    except Exception:
        return True   # не смогли определить — считаем, что запущен


def run_in_design(jsx_path, show_ok=False):
    winax = find_winax()
    if not winax:
        print("ОШИБКА: не найден модуль winax. Установите indesign-cli или укажите путь вручную.")
        return 2
    if not os.path.isfile(RUNNER_JS):
        print("ОШИБКА: не найден мост %s" % RUNNER_JS)
        return 2

    cmd = ["node", RUNNER_JS, winax, jsx_path]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=900, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        print("ОШИБКА: node не найден в PATH")
        return 2
    out = (res.stdout or "").strip()
    if res.returncode != 0 or out.startswith("ERR"):
        print("ОШИБКА InDesign: %s" % (out or (res.stderr or "").strip()))
        return 1
    if show_ok and out:
        # мост печатает "OK:<результат скрипта>"; результат полезен в журнале
        print("InDesign: %s" % (out[3:] if out.startswith("OK:") else out))
    return 0


# --------------------------------------------------------------------------- #
# Разбор отчёта и сверка
# --------------------------------------------------------------------------- #

def read_report(path):
    """Читает отчёт, сформированный ExtendScript.

    Формат строк:
        ##COL<TAB>индекс
        ##L<TAB>текст<TAB>начертание
        ##SUM<TAB>bold=N<TAB>reg=N<TAB>empty=N<TAB>bad=N
    """
    cols = []
    summary = ""
    cur = None
    with io.open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            parts = line.split("\t")
            tag = parts[0]
            if tag == "##COL":
                cur = []
                cols.append(cur)
            elif tag == "##L" and cur is not None:
                text = parts[1] if len(parts) > 1 else ""
                style = parts[2] if len(parts) > 2 else ""
                cur.append((text, style))
            elif tag == "##SUM":
                summary = " ".join(p for p in parts[1:] if p)
    return cols, summary


QUOTE_MAP = {
    "«": '"', "»": '"',          # ёлочки
    "“": '"', "”": '"',          # “ ”
    "„": '"', "‟": '"',          # низкие
    "‘": "'", "’": "'",          # ‘ ’
    "–": "-", "—": "-", "−": "-",
    " ": " ", " ": " ", " ": " ",
}


def norm(s):
    """Приводит строку к сравнимому виду: кавычки, тире, пробелы, регистр."""
    s = unicodedata.normalize("NFKC", s)
    for a, b in QUOTE_MAP.items():
        s = s.replace(a, b)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def verify(cols, days, labels):
    """Сравнивает фактические колонки с исходной программой."""
    lines = []
    lines.append("=" * 66)
    lines.append("ПРОВЕРКА РЕЗУЛЬТАТА")
    lines.append("=" * 66)
    lines.append("")

    day_names = list(days.keys())
    total_ok = total_miss = 0
    sum_row = None

    for c, day in enumerate(day_names):
        if c >= len(cols):
            lines.append("  %-14s НЕТ КОЛОНКИ" % day)
            continue
        actual_raw = [t.strip() for t, _f in cols[c] if t.strip()]
        actual = [norm(x) for x in actual_raw]
        actual_set = set(actual)
        exp = []
        for name, _d, progs in days[day]:
            exp.append(name)
            exp.extend(progs)
        exp_clean = [norm(x.strip()) for x in exp]

        aset = [x for x in actual if not PROGRAM_RE.match(x)]
        aset_p = [x for x in actual if PROGRAM_RE.match(x)]
        exp_p = [x for x in exp_clean if PROGRAM_RE.match(x)]

        missing = [x for x in exp_p if x not in actual_set]
        # пропущенные названия каналов
        miss_ch = [n for n, _d, _p in days[day] if norm(n) not in actual_set]

        total_ok += len(exp_p) - len(missing)
        total_miss += len(missing)

        flag = "полностью" if not missing and not miss_ch else "частично"
        lines.append("  %-14s передач: %d из %d найдено  [%s]"
                     % (day, len(exp_p) - len(missing), len(exp_p), flag))
        if miss_ch:
            lines.append("      нет названий каналов: %s" % ", ".join(miss_ch))
        for m in missing[:5]:
            lines.append("      нет: %s" % m)
        if len(missing) > 5:
            lines.append("      ... ещё %d" % (len(missing) - 5))

    lines.append("")
    lines.append("-" * 66)
    lines.append("ИТОГО передач: найдено %d, пропущено %d (%.1f%% попало)"
                 % (total_ok, total_miss,
                    100.0 * total_ok / max(1, total_ok + total_miss)))
    lines.append("")
    lines.append("РАЗМЕТКА ШРИФТОВ:")
    for c, day in enumerate(day_names[:len(cols)]):
        if c >= len(cols):
            break
        b = sum(1 for _t, f in cols[c] if f == "Bold")
        r = sum(1 for _t, f in cols[c] if f == "Regular")
        e = sum(1 for t, _f in cols[c] if not t.strip())
        lines.append("  %-14s жирных=%d обычных=%d пустых=%d" % (day, b, r, e))
    lines.append("")
    lines.append("НЕДЕЛЯ: " + labels[0][1] + " - " + labels[-1][1])
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Основная
# --------------------------------------------------------------------------- #

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Импорт ТВ-программы на полосу газеты (InDesign 2024)")
    ap.add_argument("program", help="файл с программой (txt)")
    ap.add_argument("--monday", required=True,
                    help="понедельник недели: ГГГГ-ММ-ДД или auto")
    ap.add_argument("--indd", default=os.path.join(BASE_DIR, "Programs.indd"),
                    help="файл макета (по умолчанию Programs.indd рядом со скриптом)")
    ap.add_argument("--issue-date", default=None,
                    help="дата выхода газеты ГГГГ-ММ-ДД — обновит шапку полосы на мастере")
    ap.add_argument("--issue-number", default=None,
                    help="номер выпуска для шапки (по умолчанию берётся из текущей строки)")
    ap.add_argument("--run-number", default=None,
                    help="номер тиража в скобках для шапки (по умолчанию сохраняется)")
    ap.add_argument("--dry-run", action="store_true", help="только план, макет не трогать")
    ap.add_argument("--quiet", action="store_true", help="краткий вывод")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.program):
        # относительный путь ищем ещё и рядом с самим инструментом
        alt = os.path.join(BASE_DIR, args.program)
        if os.path.isfile(alt):
            args.program = alt
        else:
            print("ОШИБКА: файл программы не найден: %s" % args.program)
            return 2
    if not os.path.isfile(args.indd):
        # макет по умолчанию ищем в папке проекта, если рядом нет
        if os.path.isfile(FALLBACK_INDD):
            args.indd = FALLBACK_INDD
        else:
            print("ОШИБКА: файл макета не найден: %s" % args.indd)
            return 2

    # дата
    if args.monday.lower() == "auto":
        d = guess_monday_from_name(args.program)
        if d is None:
            print("ОШИБКА: не удалось определить дату из имени файла. Укажите --monday ГГГГ-ММ-ДД")
            return 2
        d = monday_of(d)
    else:
        try:
            d = datetime.datetime.strptime(args.monday, "%Y-%m-%d").date()
        except ValueError:
            print("ОШИБКА: неверный формат даты. Ожидается ГГГГ-ММ-ДД")
            return 2
        d = monday_of(d)

    # разбор
    days = parse_program(args.program)
    problems = validate(days)
    if problems:
        print("ОШИБКА в файле программы:")
        for p in problems:
            print("   " + p)
        return 1

    labels = date_labels(d)
    title = date_range_title(d)
    nprog = sum(len(p) for chs in days.values() for _n, _d, p in chs)

    issue_day = None
    if args.issue_date:
        try:
            issue_day = datetime.datetime.strptime(args.issue_date, "%Y-%m-%d").date()
        except ValueError:
            print("ОШИБКА: неверный формат --issue-date. Ожидается ГГГГ-ММ-ДД")
            return 2

    print("ФАЙЛ ПРОГРАММЫ : %s" % os.path.basename(args.program))
    print("МАКЕТ          : %s" % args.indd)
    print("ДНЕЙ           : %d, передач: %d" % (len(days), nprog))
    print("НЕДЕЛЯ         : %s - %s" % (labels[0][1], labels[-1][1]))
    print("ЗАГОЛОВОК      : %s" % title)
    if issue_day:
        print("ШАПКА (дата)   : %s" % issue_line(
            issue_day,
            number=args.issue_number,
            run_number=args.run_number,
            original=""))
    else:
        print("ШАПКА (дата)   : не меняется (используйте --issue-date ГГГГ-ММ-ДД)")
    print()

    if args.dry_run:
        print("РЕЖИМ ПРОВЕРКИ: макет не изменяется.")
        for day in days:
            chs = days[day]
            print("  %-14s " % day + ", ".join(
                "%s(%d)" % (n, len(p)) for n, _dd, p in chs))
        return 0

    # резервная копия — рядом с макетом, независимо от того, где лежит инструмент
    os.makedirs(WORK_DIR, exist_ok=True)
    out_dir = os.path.dirname(os.path.abspath(args.indd))
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(out_dir, "Programs_резерв_%s.indd" % stamp)
    shutil.copy2(args.indd, backup)
    print("РЕЗЕРВНАЯ КОПИЯ: %s" % os.path.join(out_dir, os.path.basename(backup)))
    cleanup_backups(keep=5, folder=out_dir)

    # генерация и запуск
    jsx = os.path.join(WORK_DIR, "import.jsx")
    report = os.path.join(WORK_DIR, "report.tsv")
    if os.path.isfile(report):
        os.remove(report)

    with io.open(jsx, "w", encoding="utf-8") as fh:
        fh.write(build_jsx(days, labels, title, args.indd, report,
                           issue_date=issue_day,
                           issue_number=args.issue_number,
                           run_number=args.run_number))

    was_running = indesign_running()
    if not was_running:
        print("InDesign не запущен — инструмент запустит его сам.")
        print("Первый запуск занимает около 2 минут (холодный старт).\n")

    rc = run_in_design(jsx)
    if rc != 0:
        return rc

    runlog = os.path.join(WORK_DIR, "run_log.txt")
    if os.path.isfile(runlog) and not args.quiet:
        print()
        print("--- журнал InDesign ---")
        print(io.open(runlog, encoding="utf-8").read().strip())
        print()

    if not os.path.isfile(report):
        print("ОШИБКА: отчёт не получен — смотрите журнал выше")
        return 1

    cols, summary = read_report(report)
    text = verify(cols, days, labels)

    out = os.path.join(out_dir, "ОТЧЁТ_ИМПОРТА_ТВ_%s.md" % stamp[:8])
    with io.open(out, "w", encoding="utf-8") as fh:
        fh.write("# Отчёт импорта ТВ-программы\n\n")
        fh.write("**Дата:** %s  \n" % datetime.datetime.now().strftime("%d.%m.%Y %H:%M"))
        fh.write("**Программа:** %s  \n" % os.path.basename(args.program))
        fh.write("**Макет:** %s  \n" % os.path.basename(args.indd))
        fh.write("**Неделя:** %s - %s\n\n" % (labels[0][1], labels[-1][1]))
        fh.write("```\n%s\n```\n\n" % text)
        fh.write("Сводка из документа: `%s`\n" % summary)
    print("ОТЧЁТ: %s" % os.path.basename(out))
    print()
    print(text)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
