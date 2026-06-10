# Коммерческий пакет (RU)

Материалы для КП и согласования с службой ИБ заказчика.

| Документ | Назначение |
|----------|------------|
| [COMMERCIAL_PILOT.md](../COMMERCIAL_PILOT.md) | Одностраничное КП на пилот |
| [COMPLIANCE_DRAFT_CONTRACTOR.md](COMPLIANCE_DRAFT_CONTRACTOR.md) | Черновик политики ПДн: оператор — заказчик, подрядчик — внедрение |
| [ARCHITECTURE_FOR_IB.md](ARCHITECTURE_FOR_IB.md) | Выжимка архитектуры для ИБ (исходник) |
| [ARCHITECTURE_FOR_IB.pdf](ARCHITECTURE_FOR_IB.pdf) | PDF для приложения к КП |

**Генерация PDF:**

```bash
# из корня репозитория (нужен reportlab из зависимостей проекта)
poetry run python scripts/generate_commercial_pdf.py
```

Демо: https://fileguardian.info
