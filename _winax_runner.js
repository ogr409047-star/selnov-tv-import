/**
 * Мост Node -> InDesign 2024 через winax.
 * Выполняет .jsx-скрипт в InDesign и печатает результат.
 *
 * Использование:
 *   node _winax_runner.js <путь_к_модулю_winax> <путь_к_скрипту.jsx>
 *
 * Путь к winax передаётся аргументом намеренно: переменные окружения
 * с кириллицей в пути до Node доходят ненадёжно.
 */
"use strict";

const fs = require("fs");

const winaxPath = process.argv[2];
const scriptPath = process.argv[3];

if (!winaxPath || !fs.existsSync(winaxPath)) {
  console.log("ERR: модуль winax не найден: " + winaxPath);
  process.exit(2);
}
if (!scriptPath || !fs.existsSync(scriptPath)) {
  console.log("ERR: файл скрипта не найден: " + scriptPath);
  process.exit(2);
}

let winax;
try {
  winax = require(winaxPath);
} catch (e) {
  console.log("ERR: не удалось подключить winax: " + e.message);
  process.exit(2);
}

const Object_ = winax.Object || global.ActiveXObject;
if (!Object_) {
  console.log("ERR: в winax нет конструктора Object");
  process.exit(2);
}

// Вызов рабочего варианта (как в indesign-mcp-server):
//   DoScript(<путь к файлу скрипта>, <ID языка JavaScript>)
// Одного аргумента недостаточно: без ID языка InDesign отвечает
// "Компиляция сценария невозможна".
const JS_LANG_ID = 1246973031;

let app;
try {
  app = new Object_("InDesign.Application.2024");
} catch (e) {
  console.log("ERR: не удалось подключиться к InDesign 2024: " + e.message);
  process.exit(3);
}

try {
  const r = app.DoScript(scriptPath, JS_LANG_ID);
  console.log("OK:" + (r === undefined ? "" : String(r)));
} catch (e) {
  console.log("ERR:" + (e && e.message ? e.message : String(e)));
  process.exit(1);
}