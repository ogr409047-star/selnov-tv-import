#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
tv_icons.py — выравнивание значков телеканалов на полосе ТВ-программы.

Второй шаг приложения «Импорт ТВ 2.0»: после замены текста программы значки
ПЕРВЫЙ, РОССИЯ 1, НТВ, ТВЦ, СЕЙМ ставятся ровно по срезу названия канала
(верх прописных букв), как в эталоне Maket1.indd.

Работает через готовый инструмент icon-align, поэтому сам ничего не двигает:
  1. готовит профиль настроек под переданный .indd (каналы и имена ссылок
     те же, что в tv_import.py);
  2. сохраняет макет и делает снимок файла — по нему потом сверяются колонки
     (абзацы, символы, переливка текста);
  3. запускает icon_align.py auto: export → dump → check → plan → apply,
     проход за проходом, пока значки не встанут в допуск 0,25 мм;
  4. делает контрольную сетку «значок + название» для проверки зрением;
  5. сверяет колонки со снимком — текст не должен измениться;
  6. печатает итоговую сводку.

Запуск:
    python tv_icons.py --indd "D:\instal\Progect2026\8_Programs\Programs.indd"

Ключи:
    --indd ПУТЬ        макет полосы (обязателен)
    --tool ПУТЬ        icon_align.py (по умолчанию комплект в 10_PromtIndesing)
    --rounds N         максимум проходов подгонки (по умолчанию 8)
    --check-only       только замерить, ничего не двигать
    --no-montage       не делать контрольную сетку
    --no-sig           не сверять колонки со снимком
    --keep N           сколько снимков макета хранить (по умолчанию 3)
    --quiet            не печатать подробный ход работы

Коды возврата:
    0  значки в допуске (или уже были в допуске)
    1  работа выполнена, но часть значков осталась вне допуска
    2  нет инструмента / нет Python-модулей / неверные пути
    3  ошибка InDesign
"""

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))

# Комплект выравнивания значков (тот же, что доступен из любой сессии)
ICON_DIR = r"D:\instal\Progect2026\10_PromtIndesing\icon-align"
ICON_TOOL = os.path.join(ICON_DIR, "icon_align.py")

# Профили и рабочие папки шага выравнивания
WORK = os.path.join(BASE, "_work", "icons")
BACKUPS = os.path.join(WORK, "backup")

# Каналы и ссылки значков — как в tv_import.py и в профиле Maket2
CHANNELS = ["ПЕРВЫЙ", "РОССИЯ 1", "НТВ", "ТВЦ", "СЕЙМ"]
LINKS = ["первый1.tif", "россия 1.1.tif", "нтв1.tif",
         "твц1.tif", "сейм новый1.tif"]

DEFAULT_ROUNDS = 8
DEFAULT_KEEP = 3

# Настройки подгонки: значения проверены на Programs.indd и Maket2.indd
PROFILE = {
    "page": 0,
    "channels": CHANNELS,
    "links": LINKS,
    "col_key": "ПЕРВЫЙ",
    "col_min_h": 300,
    "icon_dx_min": -1.0,
    "icon_dx_max": 4.0,
    "move_tol": 0.6,
    "cap_dy": 1.745,
    "tol": 0.25,
    # Порог подгонки равен допуску отчёта: иначе остаются ячейки, которые
    # уже «вне допуска», но сдвигать их никто не будет. От бесполезных
    # проходов на колонке Пт (наклон отклика 4,0) страхует остановка
    # в cmd_auto, когда худшее отклонение перестаёт улучшаться.
    "plan_tol": 0.25,
    "max_step": 20.0,
    "pdf_preset": "High Quality Print",
}

SUMMARY_RE = re.compile(
    r"СВОДКА:\s*(\d+)\s+ячеек.*?min=([-+]?[\d.]+)\s+max=([-+]?[\d.]+)"
    r"\s+mean=([-+]?[\d.]+).*?допуска\s+([\d.]+)\s*мм:\s*(\d+)")


# --------------------------------------------------------------------------- #
# окружение
# --------------------------------------------------------------------------- #

def python_exe():
    """Python с PyMuPDF: pythonw.exe из ярлыка не годится для дочерних вызовов."""
    exe = sys.executable or "python"
    if exe.lower().endswith("pythonw.exe"):
        cand = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.isfile(cand):
            return cand
    return exe


def stem(path):
    return os.path.splitext(os.path.basename(path))[0]


def profile_path(indd):
    return os.path.join(WORK, "%s.json" % stem(indd))


def work_dir(indd):
    return os.path.join(WORK, "work_%s" % stem(indd))


def check_environment(tool):
    """Проверяет инструмент и модули, без которых замер не работает."""
    if not os.path.isfile(tool):
        print("ОШИБКА: не найден инструмент выравнивания значков:\n  %s" % tool)
        print("Комплект icon-align должен лежать в %s" % ICON_DIR)
        return "нет icon_align.py"
    jsx = os.path.join(os.path.dirname(tool), "icon_align.jsx")
    if not os.path.isfile(jsx):
        print("ОШИБКА: нет движка %s" % jsx)
        return "нет icon_align.jsx"
    try:
        import fitz  # noqa: F401
        import numpy  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception as e:
        print("ОШИБКА: для замера нужны PyMuPDF, numpy и Pillow (%s)." % e)
        print("Установить: %s -m pip install pymupdf numpy pillow"
              % python_exe())
        return "нет Python-модулей"
    if shutil.which("node") is None:
        print("ОШИБКА: node не найден в PATH — без него нет моста в InDesign.")
        return "нет node"
    return None


# --------------------------------------------------------------------------- #
# профиль и снимок макета
# --------------------------------------------------------------------------- #

def write_profile(indd, backup):
    import json
    os.makedirs(WORK, exist_ok=True)
    prof = dict(PROFILE)
    prof["doc"] = indd
    prof["work"] = work_dir(indd)
    prof["csv"] = "geom.csv"
    prof["plan"] = "plan.csv"
    prof["pdf"] = "page.pdf"
    prof["backup"] = backup or ""
    path = profile_path(indd)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(prof, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path


def make_snapshot(indd, keep=DEFAULT_KEEP):
    """Снимок макета до правки: по нему sig проверяет, что текст не поехал."""
    os.makedirs(BACKUPS, exist_ok=True)
    stamp = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(BACKUPS, "%s_значки_%s.indd" % (stem(indd), stamp))
    try:
        shutil.copy2(indd, dst)
    except OSError as e:
        print("ПРЕДУПРЕЖДЕНИЕ: не удалось сделать снимок макета (%s)" % e)
        return ""
    print("снимок макета: %s (%.1f МБ)"
          % (dst, os.path.getsize(dst) / 1048576.0))

    olds = sorted(glob.glob(os.path.join(BACKUPS, "%s_значки_*.indd" % stem(indd))))
    for f in olds[:max(0, len(olds) - keep)]:
        try:
            os.remove(f)
        except OSError:
            pass
    return dst


# --------------------------------------------------------------------------- #
# вызов icon-align
# --------------------------------------------------------------------------- #

def run_tool(tool, profile, args, quiet=False):
    """Запускает шаг icon-align, печатает его вывод построчно."""
    cmd = [python_exe(), tool, "--config", profile] + list(args)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    lines = []
    try:
        p = subprocess.Popen(cmd, cwd=WORK, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace",
                             bufsize=1, env=env)
    except OSError as e:
        print("ОШИБКА запуска %s: %s" % (os.path.basename(tool), e))
        return 2, lines
    for line in p.stdout:
        line = line.rstrip("\r\n")
        lines.append(line)
        if not quiet and line.strip():
            print(line, flush=True)
    p.wait()
    return p.returncode, lines


def parse_summary(lines):
    """Последняя сводка замера: число ячеек, разброс, сколько вне допуска."""
    found = None
    for line in lines:
        m = SUMMARY_RE.search(line)
        if m:
            found = {
                "cells": int(m.group(1)),
                "min": float(m.group(2)),
                "max": float(m.group(3)),
                "mean": float(m.group(4)),
                "tol": float(m.group(5)),
                "bad": int(m.group(6)),
            }
    return found


def fmt_summary(s):
    if not s:
        return "замер не получен"
    return ("%d ячеек, разброс %+.3f…%+.3f мм (среднее %+.3f), "
            "вне допуска %.2f мм: %d"
            % (s["cells"], s["min"], s["max"], s["mean"], s["tol"], s["bad"]))


# --------------------------------------------------------------------------- #
# главный ход
# --------------------------------------------------------------------------- #

def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        description="Выравнивание значков каналов на полосе ТВ-программы")
    ap.add_argument("--indd", required=True, help="макет полосы (.indd)")
    ap.add_argument("--tool", default=ICON_TOOL, help="путь к icon_align.py")
    ap.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS,
                    help="максимум проходов подгонки")
    ap.add_argument("--check-only", action="store_true",
                    help="только замерить, ничего не двигать")
    ap.add_argument("--no-montage", action="store_true",
                    help="не делать контрольную сетку значков")
    ap.add_argument("--no-sig", action="store_true",
                    help="не сверять колонки со снимком макета")
    ap.add_argument("--keep", type=int, default=DEFAULT_KEEP,
                    help="сколько снимков макета хранить")
    ap.add_argument("--quiet", action="store_true", help="без подробного вывода")
    a = ap.parse_args(argv)

    indd = os.path.abspath(a.indd.strip().strip('"'))
    tool = os.path.abspath(a.tool)

    print("=" * 62)
    print("ВЫРАВНИВАНИЕ ЗНАЧКОВ КАНАЛОВ" + (" (только замер)" if a.check_only else ""))
    print("=" * 62)
    print("макет: %s" % indd)
    print()

    if not os.path.isfile(indd):
        print("ОШИБКА: макет не найден: %s" % indd)
        return 2
    err = check_environment(tool)
    if err:
        return 2

    os.makedirs(work_dir(indd), exist_ok=True)

    # 1. Сохраняем макет и экспортируем PDF: замер идёт по растру 600 dpi,
    #    а снимок для сверки текста должен совпадать с тем, что на диске.
    profile = write_profile(indd, "")
    rc, lines = run_tool(tool, profile, ["export"], a.quiet)
    if rc != 0:
        print("ОШИБКА InDesign при сохранении макета (код %s)." % rc)
        return 3

    # 2. Снимок макета до правки — для проверки, что текст не изменился.
    backup = ""
    if not a.no_sig:
        backup = make_snapshot(indd, a.keep)
    profile = write_profile(indd, backup)

    # 3. Подгонка
    if a.check_only:
        rc, lines = run_tool(tool, profile, ["dump"], a.quiet)
        if rc != 0:
            print("ОШИБКА InDesign при выгрузке геометрии (код %s)." % rc)
            return 3
        rc, lines = run_tool(tool, profile, ["check"], a.quiet)
        if rc not in (0, 1):
            print("ОШИБКА замера (код %s)." % rc)
            return 3
        before = parse_summary(lines)
        after = before
    else:
        print("\n--- подгонка: до %d проходов ---" % a.rounds)
        rc, lines = run_tool(tool, profile, ["auto", "--rounds", str(a.rounds)],
                             a.quiet)
        if rc != 0:
            print("ОШИБКА InDesign при подгонке (код %s)." % rc)
            return 3
        after = parse_summary(lines)
        # «исходное состояние» и итог различаем по первому и последнему замеру
        marks = [parse_summary(lines[:i + 1]) for i, ln in enumerate(lines)
                 if "СВОДКА:" in ln]
        before = marks[0] if marks else None

    # 4. Контрольная сетка для проверки зрением
    montage = ""
    if not a.no_montage:
        rc, mlines = run_tool(tool, profile, ["montage"], a.quiet)
        if rc == 0 and mlines:
            first = mlines[-1].split()[0]
            if os.path.isfile(first):
                montage = first

    # 5. Текст не должен измениться
    sig_ok = None
    if not a.no_sig and backup:
        print("\n--- сверка колонок со снимком ---")
        rc, slines = run_tool(tool, profile, ["sig"], a.quiet)
        if rc == 0:
            sig_ok = True
            for ln in slines:
                if "ИЗМЕНИЛСЯ" in ln or "резервная копия не найдена" in ln:
                    sig_ok = False
        else:
            print("сверка не выполнена (код %s)" % rc)

    # 6. Итог
    print()
    print("=" * 62)
    print("ИТОГ ВЫРАВНИВАНИЯ ЗНАЧКОВ")
    print("=" * 62)
    if before is not None and after is not None and before != after:
        print("было:  %s" % fmt_summary(before))
    print("стало: %s" % fmt_summary(after))
    if montage:
        print("контрольная сетка: %s" % montage)
    if sig_ok is True:
        print("текст колонок: без изменений (абзацы, символы, переливка совпадают)")
    elif sig_ok is False:
        print("ВНИМАНИЕ: сверка колонок нашла расхождения — проверьте полосу.")
    print("рабочая папка: %s" % work_dir(indd))

    if after is None:
        print("\nЗамер не дал сводки — смотрите журнал выше.")
        return 1
    if after["bad"] == 0:
        print("\nВсе значки стоят по срезу названия канала.")
        return 0
    print("\n%d значк(ов) остались вне допуска %.2f мм — это предел подгонки "
          "для этих колонок (переливка текста)." % (after["bad"], after["tol"]))
    return 1


if __name__ == "__main__":
    sys.exit(main())
