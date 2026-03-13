
import logging
import sys
from pathlib import Path

class ColorFormatter(logging.Formatter):

    COLORS = {
        logging.DEBUG:    "\033[36m",
        logging.INFO:     "\033[32m\033[1m",
        logging.WARNING:  "\033[33m\033[1m",
        logging.ERROR:    "\033[31m\033[1m",
        logging.CRITICAL: "\033[35m\033[1m",
    }
    RESET = "\033[0m"

    def format(self, record):
        msg = super().format(record)
        color = self.COLORS.get(record.levelno, "")
        return f"{color}{msg}{self.RESET}"

def setup_logging(level_name, log_file, colored):
    level = getattr(logging, level_name.upper(), logging.INFO)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    fmt = "%(asctime)s %(levelname)-8s %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    if colored and sys.stdout.isatty():
        console.setFormatter(ColorFormatter(fmt, datefmt=datefmt))
    else:
        console.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    root.addHandler(console)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(log_path), mode="a")
        fh.setLevel(level)
        fh.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
        root.addHandler(fh)

    return root

