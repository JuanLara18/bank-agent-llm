"""Entry point for the bank-agent-llm pipeline."""

import logging
import sys


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)
    logger.info("bank-agent-llm starting up...")
    logger.info("Pipeline not yet implemented — see docs/roadmap.md for M1 tasks.")
    sys.exit(0)


if __name__ == "__main__":
    main()
