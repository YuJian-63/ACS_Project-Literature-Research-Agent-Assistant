from app.config import Settings


def main() -> None:
    if Settings().task_runner == "agent":
        from app.agent_bridge.worker import main as run
    else:
        from app.workers.research import main as run
    run()


if __name__ == "__main__":
    main()
