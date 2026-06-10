# Коммерческий пакет (RU)

Материалы для КП и согласования с службой ИБ заказчика.

| Документ | Назначение |
|----------|------------|
| [COMMERCIAL_PILOT.md](../COMMERCIAL_PILOT.md) | Одностраничное КП на пилот |
| [COMPLIANCE_DRAFT_CONTRACTOR.md](COMPLIANCE_DRAFT_CONTRACTOR.md) | Черновик политики ПДн: оператор — заказчик, подрядчик — внедрение |
| [ARCHITECTURE_FOR_IB.md](ARCHITECTURE_FOR_IB.md) | Выжимка архитектуры для ИБ (исходник) |
| [ARCHITECTURE_FOR_IB.pdf](ARCHITECTURE_FOR_IB.pdf) | PDF для приложения к КП |
| [OUTREACH_TARGETS.md](../OUTREACH_TARGETS.md) | Список целевых контактов (15) |
| [OUTREACH_EMAILS.md](../OUTREACH_EMAILS.md) | Шаблоны писем |
| [OUTREACH_STATUS.md](../OUTREACH_STATUS.md) | Статусы волны 1 · [CSV](../OUTREACH_STATUS.csv) |

**Генерация PDF:**

```bash
# из корня репозитория (нужен reportlab из зависимостей проекта)
poetry run python scripts/generate_commercial_pdf.py
```

Демо: https://fileguardian.info
