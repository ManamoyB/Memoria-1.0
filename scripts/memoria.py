"""Local administration: python -m scripts.memoria --help."""

import argparse
import json
import logging
import time

from sqlalchemy.exc import SQLAlchemyError

from app.memory.runtime import Runtime


def worker_cycle(rt):
    """Keep the worker alive during database outages; leases allow later recovery."""
    try:
        rt.schedule()
        rt.process()
        rt.sync.run()
        return True
    except SQLAlchemyError:
        logging.getLogger(__name__).warning("Database unavailable; worker will retry")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["bootstrap", "worker", "health", "sync", "reconcile"])
    args = parser.parse_args()
    rt = Runtime()
    try:
        if args.command == "bootstrap":
            rt.repo.bootstrap(rt.settings.owner_id)
            print(
                json.dumps(
                    rt.repo.issue_key(rt.settings.owner_id, "Local administrator", ["admin"])
                )
            )
        elif args.command == "worker":
            print("Memoria worker running. Press Ctrl+C to stop.")
            while True:
                worker_cycle(rt)
                time.sleep(rt.settings.worker_poll_seconds)
        elif args.command == "health":
            for name, service in (("ollama", rt.llm), ("qdrant", rt.index)):
                try:
                    print(json.dumps({name: service.health()}))
                except Exception:
                    print(json.dumps({name: {"available": False}}))
        elif args.command == "sync":
            print(json.dumps(rt.sync.run(rt.settings.owner_id, force=True)))
        else:
            print(json.dumps(rt.sync.reconcile(rt.settings.owner_id)))
    except KeyboardInterrupt:
        print("Worker stopped")
    finally:
        rt.close()


if __name__ == "__main__":
    main()
