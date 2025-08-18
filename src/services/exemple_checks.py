from typing import Mapping, Any

ru_exemple_check = {
  "restaurant": "Пример чека",
  "address": "Ташкент, ул. Амира Темура, 15",
  "phone": "+998 90 123-45-67",
  "table_number": "12",
  "order_number": "A-1024",
  "date": "18.08.2025",
  "time": "12:15",
  "waiter": "Азиз",
  "items": [
    {
      "id": 1,
      "name": "Плов (порция)",
      "quantity": 1,
      "sum": 75000
    },
    {
      "id": 2,
      "name": "Лагман (порция)",
      "quantity": 1,
      "sum": 55000
    },
    {
      "id": 3,
      "name": "Чай зелёный (чайник)",
      "quantity": 1,
      "sum": 20000
    }
  ],
  "subtotal": 150000,
  "service_charge": {
    "name": "Обслуживание",
    "percentage": 10,
    "amount": 15000
  },
  "vat": {
    "rate": 12,
    "amount": 18000
  },
  "discount": {
    "percentage": 0,
    "amount": 0
  },
  "total": 183000,
  "currency": "UZS"
}

en_exemple_check = {
  "restaurant": "Sample receipt",
  "address": "Alexanderplatz 5, 10178 Berlin, Germany",
  "phone": "+49 30 1234567",
  "table_number": "12",
  "order_number": "A-1024",
  "date": "2025-08-18",
  "time": "12:15",
  "waiter": "Anna",
  "items": [
    {
      "id": 1,
      "name": "Margherita Pizza",
      "quantity": 1,
      "sum": 12.5
    },
    {
      "id": 2,
      "name": "Pasta Carbonara",
      "quantity": 1,
      "sum": 14.0
    },
    {
      "id": 3,
      "name": "Mineral Water (750 ml)",
      "quantity": 1,
      "sum": 4.5
    }
  ],
  "subtotal": 31.0,
  "service_charge": {
    "name": "Service charge",
    "percentage": 10,
    "amount": 3.1
  },
  "vat": {
    "rate": 19,
    "amount": 5.89
  },
  "discount": {
    "percentage": 0,
    "amount": 0.0
  },
  "total": 39.99,
  "currency": "EUR"
}

es_exemple_check = {
  "restaurant": "Ejemplo de ticket",
  "address": "Carrer de Mallorca 401, 08013 Barcelona, España",
  "phone": "+34 93 123 45 67",
  "table_number": "12",
  "order_number": "ES-2042",
  "date": "2025-08-18",
  "time": "12:15",
  "waiter": "Lucía",
  "items": [
    {
      "id": 1,
      "name": "Paella mixta",
      "quantity": 1,
      "sum": 16.50
    },
    {
      "id": 2,
      "name": "Tortilla española",
      "quantity": 1,
      "sum": 8.00
    },
    {
      "id": 3,
      "name": "Agua mineral (750 ml)",
      "quantity": 1,
      "sum": 3.00
    }
  ],
  "subtotal": 27.50,
  "service_charge": {
    "name": "Servicio",
    "percentage": 10,
    "amount": 2.75
  },
  "vat": {
    "rate": 21,
    "amount": 5.78
  },
  "discount": {
    "percentage": 0,
    "amount": 0.00
  },
  "total": 36.03,
  "currency": "EUR"
}

fr_exemple_check = {
  "restaurant": "Exemple de ticket de caisse",
  "address": "12 Rue Montorgueil, 75001 Paris, France",
  "phone": "+33 1 23 45 67 89",
  "table_number": "8",
  "order_number": "FR-0778",
  "date": "2025-08-18",
  "time": "12:15",
  "waiter": "Claire",
  "items": [
    {
      "id": 1,
      "name": "Quiche lorraine",
      "quantity": 1,
      "sum": 11.00
    },
    {
      "id": 2,
      "name": "Soupe à l'oignon",
      "quantity": 1,
      "sum": 9.50
    },
    {
      "id": 3,
      "name": "Eau minérale (750 ml)",
      "quantity": 1,
      "sum": 4.00
    }
  ],
  "subtotal": 24.50,
  "service_charge": {
    "name": "Service",
    "percentage": 10,
    "amount": 2.45
  },
  "vat": {
    "rate": 20,
    "amount": 4.90
  },
  "discount": {
    "percentage": 0,
    "amount": 0.00
  },
  "total": 31.85,
  "currency": "EUR"
}

de_exemple_check = {
  "restaurant": "Beispiel-Kassenbon",
  "address": "Alexanderplatz 5, 10178 Berlin, Deutschland",
  "phone": "+49 30 1234567",
  "table_number": "4",
  "order_number": "DE-0310",
  "date": "2025-08-18",
  "time": "12:15",
  "waiter": "Lukas",
  "items": [
    {
      "id": 1,
      "name": "Currywurst",
      "quantity": 1,
      "sum": 8.50
    },
    {
      "id": 2,
      "name": "Käsespätzle",
      "quantity": 1,
      "sum": 12.00
    },
    {
      "id": 3,
      "name": "Mineralwasser (750 ml)",
      "quantity": 1,
      "sum": 4.00
    }
  ],
  "subtotal": 24.50,
  "service_charge": {
    "name": "Servicepauschale",
    "percentage": 10,
    "amount": 2.45
  },
  "vat": {
    "rate": 19,
    "amount": 4.66
  },
  "discount": {
    "percentage": 0,
    "amount": 0.00
  },
  "total": 31.61,
  "currency": "EUR"
}

it_exemple_check = {
  "restaurant": "Esempio di scontrino",
  "address": "Via della Scala 21, 00153 Roma, Italia",
  "phone": "+39 06 1234 5678",
  "table_number": "6",
  "order_number": "IT-0990",
  "date": "2025-08-18",
  "time": "12:15",
  "waiter": "Marco",
  "items": [
    {
      "id": 1,
      "name": "Pizza Margherita",
      "quantity": 1,
      "sum": 9.00
    },
    {
      "id": 2,
      "name": "Pasta alla Carbonara",
      "quantity": 1,
      "sum": 13.00
    },
    {
      "id": 3,
      "name": "Acqua minerale (750 ml)",
      "quantity": 1,
      "sum": 3.50
    }
  ],
  "subtotal": 25.50,
  "service_charge": {
    "name": "Servizio",
    "percentage": 10,
    "amount": 2.55
  },
  "vat": {
    "rate": 22,
    "amount": 5.61
  },
  "discount": {
    "percentage": 0,
    "amount": 0.00
  },
  "total": 33.66,
  "currency": "EUR"
}

pt_exemple_check = {
  "restaurant": "Exemplo de fatura",
  "address": "Rua Augusta 200, 1100-053 Lisboa, Portugal",
  "phone": "+351 21 123 4567",
  "table_number": "9",
  "order_number": "PT-0412",
  "date": "2025-08-18",
  "time": "12:15",
  "waiter": "Inês",
  "items": [
    {
      "id": 1,
      "name": "Bacalhau à Brás",
      "quantity": 1,
      "sum": 14.00
    },
    {
      "id": 2,
      "name": "Caldo verde",
      "quantity": 1,
      "sum": 5.50
    },
    {
      "id": 3,
      "name": "Água mineral (750 ml)",
      "quantity": 1,
      "sum": 2.50
    }
  ],
  "subtotal": 22.00,
  "service_charge": {
    "name": "Serviço",
    "percentage": 10,
    "amount": 2.20
  },
  "vat": {
    "rate": 23,
    "amount": 5.06
  },
  "discount": {
    "percentage": 0,
    "amount": 0.00
  },
  "total": 29.26,
  "currency": "EUR"
}

# При наличии региональных вариантов можно добавить, например:
# pt_br_exemple_check: dict[str, Any] = {...}

# ЯВНАЯ таблица соответствия. Ключи — коды по BCP 47 (язык[-РЕГИОН]).
_CHECKS_BY_LOCALE: Mapping[str, dict[str, Any]] = {
    "ru": ru_exemple_check,
    "en": en_exemple_check,
    "es": es_exemple_check,
    "fr": fr_exemple_check,
    "de": de_exemple_check,
    "it": it_exemple_check,
    "pt": pt_exemple_check,
    # "pt-BR": pt_br_exemple_check,  # если есть отдельный вариант для Бразилии
}


def pick_exemple_check_by_locale(locale_code: str | None, default: str = "en") -> dict[str, Any]:
    """
    Вернёт подходящий словарь чека по коду локали.

    Алгоритм выбора:
      1) Пытаемся найти точное совпадение (c учётом нормализации разделителей).
      2) Если не нашли — берём только языковую часть (до '-' или '_').
      3) Если и её нет — берём дефолт (по умолчанию 'en').

    Параметры:
      locale_code: строка вида 'ru', 'ru-RU', 'pt_BR', 'de-DE' и т.п.
      default: код локали по умолчанию (должен быть ключом в _CHECKS_BY_LOCALE).

    Возвращает:
      Словарь чека для наиболее подходящей локали.
    """
    # --- Нормализация локали к виду 'xx' или 'xx-YY' в нижнем регистре
    if not locale_code:
        return _CHECKS_BY_LOCALE[default]

    norm = locale_code.replace("_", "-").strip().lower()

    # Для устойчивого поиска создаём нижнерегистровое отображение ключей:
    by_lower = {k.lower(): v for k, v in _CHECKS_BY_LOCALE.items()}

    # 1) Точное совпадение 'xx-yy'
    if norm in by_lower:
        return by_lower[norm]

    # 2) Совпадение по языку 'xx'
    lang = norm.split("-")[0]
    if lang in by_lower:
        return by_lower[lang]

    # 3) Фолбэк
    return by_lower[default.lower()]