"""Production lifecycle entrypoint: observed state -> durable outbox -> HUB receipt."""
import status_alert_runner

if __name__ == "__main__":
    raise SystemExit(status_alert_runner.main())
