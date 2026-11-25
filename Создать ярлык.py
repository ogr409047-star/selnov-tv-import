#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
Создать ярлык «Импорт ТВ 2.0» на рабочем столе.

Запуск:
    python "Создать ярлык.py"

Ярлык запускает приложение через pythonw.exe — без чёрного окна консоли.
Если ярлык потерялся или переехал, его достаточно создать заново этим файлом.
"""

import os
import sys

APP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "Импорт ТВ 2.0.pyw")
ICON = r"C:\Program Files\Adobe\Adobe InDesign 2024\InDesign.exe"
NAME = "Импорт ТВ 2.0"


def desktop_dir():
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        val, _ = winreg.QueryValueEx(key, "Desktop")
        winreg.CloseKey(key)
        return os.path.expandvars(val)
    except Exception:
        return os.path.join(os.path.expanduser("~"), "Desktop")


def pythonw():
    exe = sys.executable or "python.exe"
    if exe.lower().endswith("python.exe"):
        cand = exe[:-len("python.exe")] + "pythonw.exe"
        if os.path.isfile(cand):
            return cand
    return exe


def main():
    if not os.path.isfile(APP_FILE):
        print("ОШИБКА: не найдено приложение:\n  %s" % APP_FILE)
        return 2

    try:
        import win32com.client
    except ImportError:
        print("ОШИБКА: нужен pywin32 (pip install pywin32).")
        return 2

    lnk = os.path.join(desktop_dir(), NAME + ".lnk")
    shell = win32com.client.Dispatch("WScript.Shell")
    sc = shell.CreateShortCut(lnk)
    sc.TargetPath = pythonw()
    sc.Arguments = '"%s"' % APP_FILE
    sc.WorkingDirectory = os.path.dirname(APP_FILE)
    sc.Description = ("Замена ТВ-программы на полосе газеты "
                      "и выравнивание значков каналов")
    if os.path.isfile(ICON):
        sc.IconLocation = ICON + ",0"
    sc.Save()

    print("ярлык создан: %s" % lnk)
    print("  запускает: %s" % pythonw())
    print("  приложение: %s" % APP_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
