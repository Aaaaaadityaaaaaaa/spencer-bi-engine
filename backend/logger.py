import logging
import sys
from pythonjsonlogger import jsonlogger
import contextvars

# Context var for X-Request-ID
request_id_var = contextvars.ContextVar("request_id", default="-")

class CustomJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)
        log_record['request_id'] = request_id_var.get()
        log_record['level'] = record.levelname
        log_record['logger'] = record.name

def setup_logging():
    logger = logging.getLogger("spencer")
    logger.setLevel(logging.INFO)
    
    # Remove existing handlers
    while logger.handlers:
        logger.handlers.pop()
        
    logHandler = logging.StreamHandler(sys.stdout)
    formatter = CustomJsonFormatter('%(timestamp)s %(level)s %(name)s %(message)s %(request_id)s')
    logHandler.setFormatter(formatter)
    logger.addHandler(logHandler)
    
    # uvicorn access logs
    uvicorn_logger = logging.getLogger("uvicorn.access")
    uvicorn_logger.handlers = []
    uvicorn_logger.addHandler(logHandler)
    
setup_logging()
