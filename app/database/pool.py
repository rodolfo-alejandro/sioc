"""
Pool de conexiones con reintentos ante "Lost connection to MySQL" (error 2013).
Útil cuando MySQL está en Docker o la red tarda en estabilizarse.
"""
import time
from sqlalchemy.pool import QueuePool
from sqlalchemy import exc


# Número de errores 2013 que PyMySQL puede reportar (tupla de excepciones)
def _is_lost_connection(e):
    """True si la excepción es PyMySQL/MySQL 2013 (Lost connection)."""
    if isinstance(e, exc.OperationalError):
        orig = getattr(e, "orig", None)
        if orig is not None:
            args = getattr(orig, "args", ())
            if args and args[0] == 2013:
                return True
        if "2013" in str(e) or "Lost connection" in str(e):
            return True
    return False


class RetryQueuePool(QueuePool):
    """QueuePool que reintenta crear la conexión si MySQL devuelve 2013 (Lost connection)."""

    _retry_attempts = 3
    _retry_delay = 2

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _create_connection(self):
        last_error = None
        for attempt in range(1, RetryQueuePool._retry_attempts + 1):
            try:
                return super()._create_connection()
            except Exception as e:
                last_error = e
                if _is_lost_connection(e) and attempt < RetryQueuePool._retry_attempts:
                    time.sleep(RetryQueuePool._retry_delay)
                    continue
                raise
        raise last_error
