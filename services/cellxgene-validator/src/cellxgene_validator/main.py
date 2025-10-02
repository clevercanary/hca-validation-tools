import sys
import logging
import json
from cellxgene_schema.validate import validate

class ListHandler(logging.Handler):
    """
    Custom logging handler to capture warning and error messages.
    """
    def __init__(self, warning_list, error_list):
        super().__init__()
        self.warning_list = warning_list
        self.error_list = error_list

    def emit(self, record):
        if record.levelno == logging.ERROR:
           self.error_list.append(self.format(record))
        elif record.levelno == logging.WARNING:
           self.warning_list.append(self.format(record))

def run_validator():
  if len(sys.argv) < 2:
    raise Exception("Missing command line argument for file path")
  
  file_path = sys.argv[1]

  logger = logging.getLogger("cellxgene_schema.validate")
  logger.setLevel(logging.WARNING)
  warning_messages = []
  error_messages = []
  logger.addHandler(ListHandler(warning_messages, error_messages))

  try:
    is_valid, _, _ = validate(file_path)
  except Exception as e:
     is_valid = False
     warning_messages = []
     error_messages = [f"Encountered an unexpected error while calling CELLxGENE validator: {e}"]

  result = {
     "valid": is_valid,
     "warnings": warning_messages,
     "errors": error_messages
  }

  print(json.dumps(result))

if __name__ == "__main__":
  run_validator()
