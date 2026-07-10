"""Worker entrypoint.

The durable claim/execute/verify loop is deliberately not activated until the repository layer and
approval API are implemented. Starting an apparently autonomous worker without those controls would
be misleading and unsafe.
"""

import logging
import time


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger("resolve.worker")
    log.info("control-plane worker scaffold is healthy; execution is disabled")
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
