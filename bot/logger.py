"""
Настройка структурированного логирования через structlog.

Что даёт:
  - Логи в JSON формате
  - Автоматическое добавление timestamp, service name
  - Контекст можно передавать как kwargs
  - Легко парсится системами сбора логов (ELK, Loki)
"""
import structlog
import logging
import sys


def setup_logging(service_name: str = "bot"):
    """
    Настраиваем structlog + стандартный logging

    Processors — цепочка обработчиков которые трансформируют лог:
      1. add_log_level — добавляет поле "level"
      2. TimeStamper — добавляет "timestamp"
      3. Наш processor — добавляет "service"
      4. JSONRenderer — преобразует в JSON строку
    """
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            # Добавляем имя сервиса к каждому логу
            structlog.processors.CallsiteParameterAdder(
                {
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.LINENO,
                }
            ),
            # Финальный рендер в JSON
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Настраиваем стандартный logging чтобы он не конфликтовал
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )

    # Создаём логгер с привязанным service name
    logger = structlog.get_logger()
    logger = logger.bind(service=service_name)
    return logger