"""ШИМ. Канонический код: /root/relay/services/webhook_service.py

Здесь лежала устаревшая копия (payment_service отставал на 169 строк — без цепочки
эскалации и детектора «нет трейдера»). Реально она не грузилась: relay-fastapi делает
sys.path.insert(0, '/root/relay'), и импорты services.* уходят туда. Копия была миной:
убрали бы строку с path — прод молча откатился бы на старый код.

Загружаем канонический файл ПО ПУТИ, а не через import_module: имя services.webhook_service
уже занято этим шимом, и обычный импорт вернул бы сам шим (петля).
"""
import importlib.util as _u

_spec = _u.spec_from_file_location("_canon_webhook_service", "/root/relay/services/webhook_service.py")
_canon = _u.module_from_spec(_spec)
_spec.loader.exec_module(_canon)
globals().update({k: v for k, v in vars(_canon).items() if not k.startswith("__")})
