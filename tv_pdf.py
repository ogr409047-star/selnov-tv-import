#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
Экспорт полосы в PDF — отдельный шаг приложения «Импорт ТВ 1.0».

Само поднимает InDesign 2024, если тот закрыт, и экспортирует указанный
макет в PDF тем же мостом, что и основной импорт.

Запуск:
    python tv_pdf.py --indd путь\к\Programs.indd [--pdf путь\результата.pdf]
"""

import argparse
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tv_import import (WORK_DIR, SOURCE_DIR, find_winax, indesign_running,
                       run_in_design)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PRESET = "High Quality Print"


def jsx_path(p):
    """Путь для ExtendScript: прямые слэши, обратные экранированы."""
    return p.replace("\\", "/").replace('"', '\\"')


def build_jsx(indd, pdf, preset):
    return '''// Экспорт макета в PDF. Создаётся автоматически приложением «Импорт ТВ 1.0».
(function () {
    var out = [];
    try {
        var inddFile = File("%(indd)s");
        var pdfFile  = File("%(pdf)s");
        var name     = inddFile.name;
        var doc = null, i;

        // Ищем уже открытый документ: открытый в памяти содержит свежие правки.
        for (i = 0; i < app.documents.length; i++) {
            if (app.documents[i].name == name) { doc = app.documents[i]; break; }
        }
        var opened = false;
        if (doc == null) {
            doc = app.open(inddFile);
            opened = true;
            out.push("документ открыт");
        } else {
            out.push("документ уже был открыт");
        }

        if (pdfFile.exists) { pdfFile.remove(); }

        try {
            doc.exportFile(ExportFormat.PDF_TYPE, pdfFile, false, "%(preset)s");
        } catch (e) {
            doc.exportFile(ExportFormat.PDF_TYPE, pdfFile, false);
        }

        if (opened) doc.close(SaveOptions.NO);

        if (!pdfFile.exists) return out.join(" | ") + " | ОШИБКА: файл не создан";
        var kb = Math.round(pdfFile.length / 1024);
        if (kb < 1) kb = 1;
        return out.join(" | ") + " | страниц=" + doc.pages.length
             + " | PDF " + kb + " КБ";
    } catch (e) {
        return "FATAL: " + e.message;
    }
})();
''' % dict(indd=jsx_path(indd), pdf=jsx_path(pdf), preset=preset.replace('"', '\\"'))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Экспорт макета в PDF")
    ap.add_argument("--indd", default=os.path.join(SOURCE_DIR, "Programs.indd"),
                    help="путь к макету .indd")
    ap.add_argument("--pdf", default="", help="путь к PDF (по умолчанию рядом с макетом)")
    ap.add_argument("--preset", default=DEFAULT_PRESET, help="пресет экспорта PDF")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.indd):
        print("ОШИБКА: файл макета не найден: %s" % args.indd)
        return 2

    if args.pdf:
        pdf = args.pdf
    else:
        stem = os.path.splitext(os.path.basename(args.indd))[0]
        import datetime
        stamp = datetime.datetime.now().strftime("%Y%m%d")
        pdf = os.path.join(os.path.dirname(os.path.abspath(args.indd)),
                           "%s_%s.pdf" % (stem, stamp))

    out_dir = os.path.dirname(os.path.abspath(pdf))
    if not os.path.isdir(out_dir):
        try:
            os.makedirs(out_dir)
        except OSError as e:
            print("ОШИБКА: не удалось создать папку %s: %s" % (out_dir, e))
            return 2

    print("МАКЕТ : %s" % args.indd)
    print("PDF   : %s" % pdf)
    print("ПРЕСЕТ: %s" % args.preset)
    print()

    if not indesign_running():
        print("InDesign не запущен — запускаю, это займёт около двух минут...")
    print("Экспорт...")

    os.makedirs(WORK_DIR, exist_ok=True)
    jsx = os.path.join(WORK_DIR, "export_pdf.jsx")
    with io.open(jsx, "w", encoding="utf-8") as fh:
        fh.write(build_jsx(args.indd, pdf, args.preset))

    rc = run_in_design(jsx, show_ok=True)
    if rc != 0:
        print()
        print("ЭКСПОРТ НЕ ВЫПОЛНЕН.")
        return 1

    if not os.path.isfile(pdf):
        print()
        print("ОШИБКА: PDF не создан по пути %s" % pdf)
        return 1

    size = os.path.getsize(pdf)
    print()
    print("ГОТОВО: %s" % pdf)
    print("РАЗМЕР: %.1f МБ" % (size / 1048576.0))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())