"""Mensageria: envelope padrão, Transactional Outbox, publisher e consumer RabbitMQ.

Uso nos serviços::

    from tcc_common.events.outbox import registrar_evento
    registrar_evento("monografia.submetida", {...}, actor_id=user.id)
"""
