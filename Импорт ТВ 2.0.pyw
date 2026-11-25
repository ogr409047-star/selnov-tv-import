#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Импорт ТВ 2.0 — приложение для замены ТВ-программы на газетной полосе.

Запускается ярлыком на рабочем столе. Само поднимает InDesign 2024,
если тот не открыт, и показывает ход работы в окне.

Полный цикл:
  1. импорт программы (текст, шрифты, даты, шапка полосы);
  2. выравнивание значков каналов по срезу названия (шаг icon-align).

Новое во 2.0: после вёрстки значки ПЕРВЫЙ, РОССИЯ 1, НТВ, ТВЦ, СЕЙМ
ставятся ровно по верхней границе прописных букв — двигаются только
по вертикали, текст колонок не меняется.
"""

import glob
import json
import os
import queue
import re
import subprocess
import sys
import threading
import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_NAME = "Импорт ТВ 2.0"
APP_VERSION = "2.0"
BASE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(BASE, "tv_import.py")
PDF_TOOL = os.path.join(BASE, "tv_pdf.py")
ICON_TOOL = os.path.join(BASE, "tv_icons.py")
SETTINGS = os.path.join(BASE, "настройки.json")

# Макет и папка с программами живут рядом с исходным проектом
PROJECTS = r"D:\instal\Progect2026"
PROGRAM_DIR = os.path.join(PROJECTS, "8_Programs")
DEFAULT_INDD = os.path.join(PROGRAM_DIR, "Programs.indd")

WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг",
            "Пятница", "Суббота", "Воскресенье"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня",
          "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def human_date(d):
    return "%d %s %d" % (d.day, MONTHS[d.month - 1], d.year)


def parse_date(s):
    """Понимает и ГГГГ-ММ-ДД, и «16 ноября 2026». Возвращает date или None."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        pass
    m = re.match(r"^(\d{1,2})\s+([а-яё]+)\.?\s+(\d{4})\.?$", s.lower())
    if m:
        try:
            mon = MONTHS.index(m.group(2).rstrip(".")) + 1
        except ValueError:
            return None
        try:
            return datetime.date(int(m.group(3)), mon, int(m.group(1)))
        except ValueError:
            return None
    return None


def guess_monday(path):
    """Дата из имени файла программы: program_NEW16112026.txt -> 16.11.2026.

    Возвращает понедельник той недели или None. Та же логика, что в tv_import.py
    (--monday auto), чтобы приложение и инструмент понимали дату одинаково.
    """
    stem = os.path.splitext(os.path.basename(path or ""))[0]
    digits = re.sub(r"\D", "", stem)
    for n in (8, 6):
        if len(digits) >= n:
            chunk = digits[:n]
            try:
                if n == 8:
                    day = datetime.date(int(chunk[4:8]), int(chunk[2:4]),
                                        int(chunk[0:2]))
                else:
                    day = datetime.date(2000 + int(chunk[4:6]), int(chunk[2:4]),
                                        int(chunk[0:2]))
            except ValueError:
                continue
            return day - datetime.timedelta(days=day.weekday())
    return None


def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(s):
    try:
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except Exception:
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("860x760")
        self.minsize(760, 620)
        self.configure(bg="#f2f2f2")

        self.q = queue.Queue()
        self.busy = False
        self.rcs = []
        self.pending_pdf = ""
        self._issue_suggested = ""
        self._issue_auto = True
        self.prog_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Готово к работе")
        self.settings = load_settings()

        self._build()
        self.after(100, self._drain)
        self._reload_programs()
        self._suggest_dates()

    # ------------------------------------------------------------------ UI
    def _build(self):
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass

        top = ttk.Frame(self, padding=(12, 12, 12, 0))
        top.pack(fill="x")

        ttk.Label(top, text=APP_NAME, font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(
            top,
            text="Замена ТВ-программы на полосе газеты и выравнивание значков "
                 "каналов. InDesign 2024 откроется сам.",
            font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))

        # ---- файл программы ----
        f1 = ttk.LabelFrame(self, text=" Файл программы ", padding=10)
        f1.pack(fill="x", padx=12, pady=(12, 0))

        self.file_var = tk.StringVar()
        row = ttk.Frame(f1)
        row.pack(fill="x")
        self.file_combo = ttk.Combobox(row, textvariable=self.file_var, state="readonly")
        self.file_combo.pack(side="left", fill="x", expand=True)
        self.file_combo.bind("<<ComboboxSelected>>", self._program_changed)
        ttk.Button(row, text="Обзор...", width=12,
                   command=self._browse).pack(side="left", padx=(8, 0))

        self.file_info = ttk.Label(f1, text="", font=("Segoe UI", 8))
        self.file_info.pack(anchor="w", pady=(6, 0))

        # ---- файл макета ----
        f4 = ttk.LabelFrame(self, text=" Макет полосы ", padding=10)
        f4.pack(fill="x", padx=12, pady=(10, 0))

        self.indd_var = tk.StringVar(
            value=self.settings.get("indd") or DEFAULT_INDD)
        r2 = ttk.Frame(f4)
        r2.pack(fill="x")
        self.indd_entry = ttk.Entry(r2, textvariable=self.indd_var)
        self.indd_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(r2, text="Обзор...", width=12,
                   command=self._browse_indd).pack(side="left", padx=(8, 0))

        self.indd_info = ttk.Label(f4, text="", font=("Segoe UI", 8))
        self.indd_info.pack(anchor="w", pady=(6, 0))

        # ---- даты ----
        f2 = ttk.LabelFrame(self, text=" Даты ", padding=10)
        f2.pack(fill="x", padx=12, pady=(10, 0))
        f2.columnconfigure(1, weight=1)

        ttk.Label(f2, text="Понедельник недели программы:").grid(
            row=0, column=0, sticky="w", pady=3)
        self.monday_var = tk.StringVar()
        e1 = ttk.Entry(f2, textvariable=self.monday_var, width=14)
        e1.grid(row=0, column=1, sticky="w", pady=3)
        ttk.Label(f2, text="  ← ГГГГ-ММ-ДД, например 2026-11-16",
                  font=("Segoe UI", 8)).grid(row=0, column=2, sticky="w")

        ttk.Label(f2, text="Дата выхода газеты (шапка):").grid(
            row=1, column=0, sticky="w", pady=3)
        self.issue_var = tk.StringVar()
        e2 = ttk.Entry(f2, textvariable=self.issue_var, width=14)
        e2.grid(row=1, column=1, sticky="w", pady=3)
        ttk.Label(f2, text="  ← пусто = шапку не менять",
                  font=("Segoe UI", 8)).grid(row=1, column=2, sticky="w")

        self.date_hint = ttk.Label(f2, text="", font=("Segoe UI", 8),
                                   foreground="#555")
        self.date_hint.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

        self.indd_entry.bind("<Return>", lambda ev: self._show_indd())
        self.indd_entry.bind("<FocusOut>", lambda ev: self._show_indd())
        self._show_indd()

        e1.bind("<Return>", lambda ev: self._suggest_dates())
        e2.bind("<Return>", lambda ev: self._suggest_dates())
        e2.bind("<KeyRelease>", self._issue_edited)

        tip = ("Понедельник подставляется из имени файла программы — проверьте его.\n"
               "Для программы с 19 по 25 октября нужен понедельник 19 октября.\n"
               "Дата выхода меняет строку в шапке полосы; пустое поле — шапку не трогать.\n"
               "Допустимы и даты прописью: 16 ноября 2026.")
        ttk.Label(f2, text=tip, font=("Segoe UI", 8),
                  foreground="#555").grid(row=3, column=0, columnspan=3,
                                         sticky="w", pady=(6, 0))

        # ---- значки каналов ----
        f5 = ttk.LabelFrame(self, text=" Значки каналов ", padding=10)
        f5.pack(fill="x", padx=12, pady=(10, 0))

        self.icons_var = tk.BooleanVar(
            value=bool(self.settings.get("icons", True)))
        ttk.Checkbutton(
            f5, variable=self.icons_var,
            text="Выравнивать значки по срезу названия после импорта",
            command=self._remember).pack(anchor="w")
        ttk.Label(
            f5,
            text="ПЕРВЫЙ, РОССИЯ 1, НТВ, ТВЦ, СЕЙМ ставятся ровно по верхней "
                 "границе прописных букв.\n"
                 "Значки двигаются только по вертикали, текст колонок не меняется.",
            font=("Segoe UI", 8), foreground="#555").pack(anchor="w", pady=(4, 0))

        # ---- кнопки ----
        b = ttk.Frame(self, padding=(12, 10, 12, 0))
        b.pack(fill="x")

        self.btn_start = tk.Button(b, text="ПУСК", width=9, height=1,
                                   font=("Segoe UI", 11, "bold"),
                                   bg="#2d6a2d", fg="white", activebackground="#245224",
                                   activeforeground="white", relief="raised", bd=2,
                                   command=self._start)
        self.btn_start.pack(side="left")
        ttk.Label(b, text="  полный цикл: импорт программы → значки каналов",
                  font=("Segoe UI", 8), foreground="#555").pack(side="left", padx=(4, 0))

        self.btn_run = ttk.Button(b, text="Импортировать",
                                  command=lambda: self._run(dry=False))
        self.btn_run.pack(side="left", padx=(8, 0))
        self.btn_check = ttk.Button(b, text="Проверить (без изменений)",
                                    command=lambda: self._run(dry=True))
        self.btn_check.pack(side="left", padx=(8, 0))
        self.btn_icons = ttk.Button(b, text="Выровнять значки",
                                    command=self._icons_only)
        self.btn_icons.pack(side="left", padx=(8, 0))
        self.btn_pdf = ttk.Button(b, text="Создать PDF",
                                  command=self._make_pdf)
        self.btn_pdf.pack(side="left", padx=(8, 0))
        ttk.Button(b, text="Открыть отчёт", command=self._open_report).pack(side="left", padx=(8, 0))
        ttk.Button(b, text="Выход", command=self._close).pack(side="right")

        self.pbar = ttk.Progressbar(self, mode="indeterminate")
        self.pbar.pack(fill="x", padx=12, pady=(10, 0))
        self.pbar.pack_forget()  # на холостом ходу полоса не нужна

        # ---- журнал ----
        f3 = ttk.LabelFrame(self, text=" Ход работы ", padding=8)
        f3.pack(fill="both", expand=True, padx=12, pady=(10, 12))
        wrap = tk.Frame(f3)
        wrap.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(wrap)
        scroll.pack(side="right", fill="y")
        self.log = tk.Text(wrap, wrap="none", font=("Consolas", 9),
                           bg="#ffffff", relief="flat", height=14)
        self.log.pack(side="left", fill="both", expand=True)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.configure(command=self.log.yview)

        ttk.Label(self, textvariable=self.status_var, padding=(14, 0, 12, 8),
                  font=("Segoe UI", 8)).pack(fill="x")

    def _close(self):
        self._remember()
        self.destroy()

    # -------------------------------------------------------------- логика
    def _reload_programs(self):
        files = sorted(glob.glob(os.path.join(PROGRAM_DIR, "program*.txt")))
        names = [os.path.basename(f) for f in files]
        self._files = dict(zip(names, files))
        self.file_combo["values"] = names
        cur = self.file_var.get()
        if cur not in self._files:
            saved = self.settings.get("program")
            if saved in self._files:
                self.file_var.set(saved)
            elif names:
                self.file_var.set(names[0])
            else:
                self.file_var.set("")
        self._program_changed()

    def _program_changed(self, event=None):
        """Выбран другой файл программы: показать сведения и предложить даты."""
        self._show_info()
        if not self.monday_var.get().strip():
            g = guess_monday(self._files.get(self.file_var.get()))
            if g:
                self.monday_var.set(g.isoformat())
        self._suggest_dates()

    def _browse(self):
        p = filedialog.askopenfilename(
            title="Выберите файл программы",
            initialdir=PROGRAM_DIR,
            filetypes=[("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")])
        if p:
            self.file_var.set(os.path.basename(p))
            self._files[os.path.basename(p)] = p
            self._program_changed()

    def _show_info(self):
        p = self._files.get(self.file_var.get())
        if p and os.path.isfile(p):
            st = os.stat(p)
            self.file_info.configure(
                text="%s   ·   %d КБ   ·   изменён %s"
                     % (p, st.st_size // 1024,
                        datetime.datetime.fromtimestamp(st.st_mtime).strftime("%d.%m.%Y %H:%M")))
        else:
            self.file_info.configure(text="")

    def _suggest_dates(self):
        """Подставляет дату выхода (понедельник − 5 дней) и объясняет даты словами."""
        m = parse_date(self.monday_var.get())
        if not m:
            if self.monday_var.get().strip():
                self.date_hint.configure(
                    text="Понедельник не распознан — нужен формат ГГГГ-ММ-ДД.",
                    foreground="#b03030")
            else:
                self.date_hint.configure(
                    text="Понедельник недели не указан.", foreground="#b03030")
            return

        mon = m - datetime.timedelta(days=m.weekday())
        if self._issue_auto:
            self._issue_suggested = (mon - datetime.timedelta(days=5)).isoformat()
            self.issue_var.set(self._issue_suggested)

        parts = []
        if m != mon:
            parts.append("%s — понедельник недели %s" % (human_date(m), human_date(mon)))
        else:
            parts.append("неделя с %s" % human_date(mon))
        iss = parse_date(self.issue_var.get())
        if iss:
            parts.append("шапка: %s" % human_date(iss))
        elif self.issue_var.get().strip():
            parts.append("дата выхода не распознана")
        else:
            parts.append("шапку не меняем")
        self.date_hint.configure(
            text=" · ".join(parts),
            foreground="#555" if (iss or not self.issue_var.get().strip()) else "#b03030")

    def _issue_edited(self, event=None):
        """Пользователь правит дату выхода — больше не перезаписываем её сами."""
        if self.issue_var.get().strip() != self._issue_suggested:
            self._issue_auto = False
        self._suggest_dates()

    def _validate(self):
        p = self._files.get(self.file_var.get())
        if not p or not os.path.isfile(p):
            return None, "Не выбран файл программы."
        m = parse_date(self.monday_var.get())
        if not m:
            return None, ("Понедельник недели должен быть датой в формате "
                          "ГГГГ-ММ-ДД (например 2026-11-16).")
        iss_raw = self.issue_var.get().strip()
        iss = parse_date(iss_raw) if iss_raw else None
        if iss_raw and not iss:
            return None, ("Дата выхода должна быть в формате ГГГГ-ММ-ДД "
                          "или поле должно быть пустым.")
        # приводим поля к виду, который понимает tv_import.py
        self.monday_var.set(m.isoformat())
        self.issue_var.set(iss.isoformat() if iss else "")
        self._suggest_dates()
        return p, None

    def _run(self, dry):
        if self.busy:
            return
        prog, err = self._validate()
        if err:
            messagebox.showwarning("Проверьте данные", err)
            return

        indd = self._current_indd()
        if not indd or not os.path.isfile(indd):
            messagebox.showwarning(
                "Проверьте данные",
                "Укажите существующий файл макета в поле «Макет полосы».")
            return
        self._remember()

        with_icons = bool(self.icons_var.get()) and not dry
        if not dry:
            what = "Заменить программу на полосе?"
            if with_icons:
                what += "\nПосле импорта значки каналов встанут по срезу названия."
            if not messagebox.askyesno(
                    "Подтверждение",
                    "%s\n\n"
                    "Перед изменением будет создана резервная копия макета.\n"
                    "Программа: %s\nМакет:  %s\n\n"
                    "Продолжить?" % (what, os.path.basename(prog), indd)):
                return

        # передаём ПОЛНЫЕ пути: программа и макет лежат в другой папке,
        # чем само приложение, и относительные имена ищутся не там
        args = [sys.executable, TOOL, prog,
                "--monday", self.monday_var.get().strip(),
                "--indd", indd]
        iss = self.issue_var.get().strip()
        if iss:
            args += ["--issue-date", iss]
        if dry:
            args.append("--dry-run")

        steps = [args]
        if with_icons:
            steps.append([sys.executable, ICON_TOOL, "--indd", indd])

        title = "ПРОВЕРКА (макет не изменяется)" if dry else "ИМПОРТ"
        if with_icons:
            title += " + ЗНАЧКИ КАНАЛОВ"
        self._launch(steps, title,
                     "Проверка..." if dry else
                     "Импорт... первый запуск InDesign может занять 2 минуты",
                     header_extra="Макет: %s\n\n" % indd)

    def _icons_only(self):
        """Только выравнивание значков — без импорта программы."""
        if self.busy:
            return
        indd = self._current_indd()
        if not indd or not os.path.isfile(indd):
            messagebox.showwarning(
                "Проверьте данные",
                "Укажите существующий файл макета в поле «Макет полосы».")
            return
        if not os.path.isfile(ICON_TOOL):
            messagebox.showerror(
                APP_NAME,
                "Не найден шаг выравнивания значков:\n%s" % ICON_TOOL)
            return
        self._remember()
        if not messagebox.askyesno(
                "Подтверждение",
                "Выровнять значки каналов на полосе?\n\n"
                "Макет: %s\n\n"
                "Значки двигаются только по вертикали, текст не меняется.\n"
                "Перед правкой делается снимок макета для сверки."
                % os.path.basename(indd)):
            return
        self._launch([[sys.executable, ICON_TOOL, "--indd", indd]],
                     "ВЫРАВНИВАНИЕ ЗНАЧКОВ КАНАЛОВ",
                     "Выравнивание значков...",
                     header_extra="Макет: %s\n\n" % indd)

    def _browse_indd(self):
        cur = self.indd_var.get().strip()
        init = os.path.dirname(cur) if os.path.isfile(cur) else PROGRAM_DIR
        p = filedialog.askopenfilename(
            title="Выберите макет полосы",
            initialdir=init if os.path.isdir(init) else PROGRAM_DIR,
            filetypes=[("Макеты InDesign", "*.indd"), ("Все файлы", "*.*")])
        if p:
            self.indd_var.set(p)
            self._show_indd()
            self._remember()

    def _current_indd(self):
        return self.indd_var.get().strip().strip('"')

    def _show_indd(self):
        """Показывает сведения о макете и предупреждает, если файла нет."""
        p = self._current_indd()
        if p and os.path.isfile(p):
            st = os.stat(p)
            self.indd_info.configure(
                text="%s   ·   %.1f МБ   ·   изменён %s"
                     % (p, st.st_size / 1048576.0,
                        datetime.datetime.fromtimestamp(st.st_mtime).strftime("%d.%m.%Y %H:%M")),
                foreground="#555")
        elif p:
            self.indd_info.configure(
                text="%s   ·   ФАЙЛ НЕ НАЙДЕН" % p, foreground="#b03030")
        else:
            self.indd_info.configure(text="Макет не указан", foreground="#b03030")

    def _remember(self):
        self.settings["indd"] = self._current_indd()
        if self.file_var.get():
            self.settings["program"] = self.file_var.get()
        self.settings["icons"] = bool(self.icons_var.get())
        save_settings(self.settings)

    def _start(self):
        """Общая кнопка запуска: импорт программы и значки, без лишних вопросов."""
        self._run(dry=False)

    def _make_pdf(self):
        """Экспортирует выбранный макет в PDF."""
        if self.busy:
            return
        indd = self._current_indd()
        if not indd or not os.path.isfile(indd):
            messagebox.showwarning(
                "Проверьте данные",
                "Укажите существующий файл макета в поле «Макет полосы».")
            return
        self._remember()
        suggested = os.path.splitext(indd)[0] + ".pdf"
        out = filedialog.asksaveasfilename(
            title="Сохранить PDF",
            initialdir=os.path.dirname(indd),
            initialfile=os.path.basename(suggested),
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")])
        if not out:
            return

        self._launch([[sys.executable, PDF_TOOL, "--indd", indd, "--pdf", out]],
                     "СОЗДАНИЕ PDF",
                     "Создание PDF... первый запуск InDesign может занять 2 минуты",
                     header_extra="Макет: %s\n\n" % indd,
                     pdf=out)

    def _launch(self, steps, title, status, header_extra="", pdf=""):
        self.busy = True
        self.rcs = [None] * len(steps)
        self.pending_pdf = pdf
        self._set_buttons(False)
        self.pbar.pack(fill="x", padx=12, pady=(10, 0))
        self.pbar.start(12)
        self.status_var.set(status)
        self._log("=" * 62 + "\n" + title + "\n" + "=" * 62 + "\n")
        if header_extra:
            self._log(header_extra)
        threading.Thread(target=self._work, args=(steps,), daemon=True).start()

    def _set_buttons(self, enabled):
        state = "normal" if enabled else "disabled"
        self.btn_check.configure(state=state)
        self.btn_run.configure(state=state)
        self.btn_icons.configure(state=state)
        self.btn_pdf.configure(state=state)
        self.btn_start.configure(state=state)

    def _work(self, steps):
        """Выполняет шаги по очереди в одном потоке: импорт, затем значки."""
        try:
            for idx, args in enumerate(steps):
                p = subprocess.Popen(list(args), cwd=BASE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True,
                                     encoding="utf-8", errors="replace",
                                     bufsize=1)
                for line in p.stdout:
                    self.q.put(line.rstrip("\n"))
                p.wait()
                self.q.put("__RC__%d:%d" % (idx, p.returncode))
                if p.returncode != 0:
                    break
        except Exception as e:
            self.q.put("ОШИБКА запуска: %s" % e)
            self.q.put("__RC__0:-1")
        finally:
            self.q.put(None)

    def _drain(self):
        try:
            while True:
                line = self.q.get_nowait()
                if line is None:
                    self._finish()
                    break
                if line.startswith("__RC__"):
                    idx, _, code = line[6:].partition(":")
                    try:
                        self.rcs[int(idx)] = int(code)
                    except (ValueError, IndexError):
                        pass
                    continue
                if line.strip():
                    self._log(line + "\n")
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _finish(self):
        self.busy = False
        self.pbar.stop()
        self.pbar.pack_forget()
        self._set_buttons(True)
        self._reload_programs()
        rcs = list(self.rcs)
        self.rcs = []
        rc = rcs[0] if rcs and rcs[0] is not None else -1
        icons_rc = rcs[1] if len(rcs) > 1 else None
        pdf = self.pending_pdf
        self.pending_pdf = ""

        if rc != 0:
            self.status_var.set("Ошибка — смотрите журнал.")
            messagebox.showerror(APP_NAME,
                                 "Работа не завершена (код %s).\n"
                                 "Причина — в журнале.\n"
                                 "Макет не изменён." % rc)
            return

        if pdf:
            self.status_var.set("PDF создан.")
            messagebox.showinfo(APP_NAME, "PDF создан:\n%s" % pdf)
            try:
                os.startfile(pdf)
            except Exception:
                pass
            return

        # итог по шагу значков: 0 — всё в допуске, 1 — часть вне допуска
        if icons_rc == 0:
            self.status_var.set("Готово: программа заменена, значки выровнены.")
            messagebox.showinfo(
                APP_NAME,
                "Работа завершена.\n\n"
                "Программа на полосе заменена.\n"
                "Значки каналов стоят по срезу названия.")
            self._open_report_folder()
            return

        if icons_rc == 1:
            self.status_var.set("Готово, но часть значков вне допуска 0,25 мм.")
            messagebox.showwarning(
                APP_NAME,
                "Работа завершена.\n\n"
                "Программа на полосе заменена, значки выровнены.\n"
                "Часть значков осталась вне допуска 0,25 мм — это предел\n"
                "подгонки для этих колонок (переливка текста).\n"
                "Подробности — в журнале.")
            self._open_report_folder()
            return

        if icons_rc is not None:
            self.status_var.set("Программа заменена, значки НЕ выровнены.")
            messagebox.showwarning(
                APP_NAME,
                "Программа на полосе заменена, но шаг выравнивания значков\n"
                "не выполнен (код %s). Причина — в журнале." % icons_rc)
            self._open_report_folder()
            return

        self.status_var.set("Готово. Отчёт в папке проекта.")
        messagebox.showinfo(APP_NAME,
                            "Работа завершена.\nПодробности — в журнале и в файле отчёта.")
        self._open_report_folder()

    def _log(self, s):
        self.log.insert("end", s)
        self.log.see("end")

    def _open_report(self):
        files = sorted(glob.glob(os.path.join(PROGRAM_DIR, "ОТЧЁТ_ИМПОРТА_ТВ_*.md")),
                       key=os.path.getmtime, reverse=True)
        if not files:
            messagebox.showinfo(APP_NAME, "Отчётов пока нет.")
            return
        os.startfile(files[0])

    def _open_report_folder(self):
        try:
            os.startfile(PROGRAM_DIR)
        except Exception:
            pass


if __name__ == "__main__":
    App().mainloop()
