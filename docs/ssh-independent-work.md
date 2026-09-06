# Работа без SSH

Сервис `obsidian-roadmap-autopilot.service` запускает последовательные итерации
Codex на сервере. Termux и SSH служат только для наблюдения. Разрыв соединения
не завершает сервис. Проверено отдельными systemd-rehearsal: родитель PID 1,
две последовательные итерации, остановка при оставшемся дочернем процессе и
фактическое удаление отделившегося процесса.

Текущая задача: E4; после неё разрешены переходы по E0–E5 согласно
`CURRENT_ROUTE.md` и `autonomous-roadmap-transitions.md`. Переход требует
обоснования, committed evidence и сохранения ограничений следующего этапа.
При раннем blocker поздняя подготовка остаётся KEYLESS_NONPRODUCTION.
064A заморожен. Обычные
обратимые изменения проходят тесты, два независимых review, rollout и проверку
runtime. `codex exec --approve-for-me` сохраняет workspace sandbox, действующие
правила и автоматическую проверку разрешений. Отказ проверки, недоступные
credentials, неоднозначный денежный результат и невозможный rollback
останавливают работу. Обхода ограничений нет.

Посмотреть состояние:

```sh
systemctl status obsidian-roadmap-autopilot.service --no-pager
python3 /usr/local/lib/obsidian-roadmap-autopilot/obsidian_roadmap_autopilot.py status
journalctl -u obsidian-roadmap-autopilot.service -n 30 --no-pager
```

Подробный лог и итоговая JSON-квитанция каждой итерации находятся в закрытом
каталоге `/var/lib/obsidian-roadmap-autopilot/run-*`. Путь текущей итерации
содержится в `status.json`. Логи не предназначены для публикации.

Перед ручным редактированием проекта сначала завершить или остановить сервис:

```sh
systemctl stop obsidian-roadmap-autopilot.service
```

Остановка, timeout или авария не вызывают автоматического повторения. Следующий
исполнитель проверяет Git, журнал, незавершённые действия и runtime, затем
готовит отдельный новый запуск. Состояния `RUNNING`, `STARTING`, `INTERRUPTED`,
`FAILED`, `BLOCKED` нельзя просто переактивировать командой arm. Сначала
сохранить исходные квитанции и установить, что произошло. Автоматический
перезапуск после reboot отключён по той же причине.

Для свежего запуска после завершённой передачи работы: чистый tracked checkout,
нет другого исполнителя, проверенные установленные файлы, затем:

```sh
python3 /usr/local/lib/obsidian-roadmap-autopilot/obsidian_roadmap_autopilot.py arm --max-iterations 8 --hours 12
systemctl start obsidian-roadmap-autopilot.service
```

Лимит одной ночи — максимум восемь итераций или двенадцать часов. Следующая
итерация допускается только после валидной квитанции, сохранённого коммита,
проверок и отсутствия оставшихся процессов. Документационные коммиты сами по
себе не считаются новой продуктовой итерацией. `COMPLETE`, конкретный blocker
или лимит останавливают цикл.

Установка: `bash deploy/obsidian_roadmap_autopilot_install.sh`. Установщик
сохраняет preimage, проверяет отсутствие активного исполнителя и lock, выполняет
systemd validation и daemon-reload; запуск и enable не выполняет. Откат:
остановить сервис, восстановить установленные файлы и unit из записанного
`install-preimage.*`, выполнить daemon-reload. При первой установке достаточно
оставить сервис остановленным: production-приложения не зависят от него.

Это автоматизация поддержки E0–E5, а не отдельный продуктовый этап. Ресурсы
сервера, доступность модели и авторизации ограничивают выполнение; сами по
себе tmux/systemd этих ограничений не устраняют. Noninteractive interface:
[официальная документация Codex](https://learn.chatgpt.com/docs/non-interactive-mode).
